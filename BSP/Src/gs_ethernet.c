/* STM32F429 V1 capture uploader. Original application/port code; lwIP itself
 * stays unmodified in the selected CubeF4 SDK. See gs_ethernet.h for ownership.
 * HTTP parsing is deliberately bounded and also builds as a host self-test. */
#include "gs_ethernet.h"
#include <string.h>
#include <stdio.h>

#define HTTP_RESPONSE_CAP 1024U
#define CONTROL_BODY_CAP 256U

typedef struct {
    uint32_t enabled, interval_ms, epoch;
} control_values_t;

typedef struct {
    unsigned status;
    size_t header_bytes, body_bytes;
} response_info_t;

static bool decimal_u32(const char *p, size_t n, uint32_t *out)
{
    uint32_t value = 0U;
    size_t i;
    if (n == 0U) return false;
    for (i = 0; i < n; ++i) {
        uint32_t digit;
        if (p[i] < '0' || p[i] > '9') return false;
        digit = (uint32_t)(p[i] - '0');
        if (value > (UINT32_MAX - digit) / 10U) return false;
        value = value * 10U + digit;
    }
    *out = value;
    return true;
}

static bool name_equal(const char *p, size_t n, const char *name)
{
    size_t i;
    if (strlen(name) != n) return false;
    for (i = 0; i < n; ++i) {
        char c = p[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + ('a' - 'A'));
        if (c != name[i]) return false;
    }
    return true;
}

/* -1 malformed/unsupported, 0 incomplete, 1 complete. No unbounded strstr,
 * atoi, chunked coding, interim responses or response pipelining. */
static int parse_response(const char *data, size_t bytes, bool eof,
                          response_info_t *info)
{
    size_t line_end = 0U, pos, header_end = 0U;
    uint32_t length = 0U;
    bool has_length = false;
    if (bytes > HTTP_RESPONSE_CAP) return -1;
    for (pos = 0U; pos + 3U < bytes; ++pos) {
        if (memcmp(data + pos, "\r\n\r\n", 4U) == 0) {
            header_end = pos + 4U;
            break;
        }
    }
    if (header_end == 0U) return (eof || bytes == HTTP_RESPONSE_CAP) ? -1 : 0;
    while (line_end + 1U < header_end &&
           !(data[line_end] == '\r' && data[line_end + 1U] == '\n')) ++line_end;
    if (line_end < 12U ||
        (memcmp(data, "HTTP/1.0 ", 9U) != 0 && memcmp(data, "HTTP/1.1 ", 9U) != 0) ||
        data[9] < '1' || data[9] > '5' || data[10] < '0' || data[10] > '9' ||
        data[11] < '0' || data[11] > '9' || (line_end > 12U && data[12] != ' ')) return -1;
    info->status = (unsigned)(data[9] - '0') * 100U +
                   (unsigned)(data[10] - '0') * 10U + (unsigned)(data[11] - '0');
    if (info->status < 200U) return -1;
    pos = line_end + 2U;
    while (pos + 2U < header_end) {
        size_t end = pos, colon, value, value_end;
        while (end + 1U < header_end && !(data[end] == '\r' && data[end + 1U] == '\n')) ++end;
        colon = pos;
        while (colon < end && data[colon] != ':') ++colon;
        if (colon == pos || colon == end) return -1;
        value = colon + 1U;
        while (value < end && (data[value] == ' ' || data[value] == '\t')) ++value;
        value_end = end;
        while (value_end > value && (data[value_end - 1U] == ' ' || data[value_end - 1U] == '\t')) --value_end;
        if (name_equal(data + pos, colon - pos, "transfer-encoding")) return -1;
        if (name_equal(data + pos, colon - pos, "content-length")) {
            if (has_length || !decimal_u32(data + value, value_end - value, &length)) return -1;
            has_length = true;
        }
        pos = end + 2U;
    }
    info->header_bytes = header_end;
    if (has_length) {
        if (length > HTTP_RESPONSE_CAP - header_end) return -1;
        info->body_bytes = (size_t)length;
        if (bytes - header_end < length) return eof ? -1 : 0;
        if (bytes - header_end != length) return -1;
        return 1;
    }
    info->body_bytes = bytes - header_end;
    return eof ? 1 : 0; /* HTTP/1.0 close-delimited response */
}

static bool parse_control(const char *body, size_t bytes, control_values_t *out)
{
    size_t pos = 0U;
    unsigned seen = 0U;
    control_values_t value = {0U, 0U, 0U};
    if (bytes == 0U || bytes > CONTROL_BODY_CAP) return false;
    while (pos < bytes) {
        size_t end = pos, stop, equal;
        uint32_t number;
        unsigned bit;
        while (end < bytes && body[end] != '\n') ++end;
        stop = end;
        if (stop > pos && body[stop - 1U] == '\r') --stop;
        if (stop == pos) { pos = end + (end < bytes); continue; }
        equal = pos;
        while (equal < stop && body[equal] != '=') ++equal;
        if (equal == stop || !decimal_u32(body + equal + 1U, stop - equal - 1U, &number)) return false;
        if (name_equal(body + pos, equal - pos, "enabled")) {
            bit = 1U; value.enabled = number;
        } else if (name_equal(body + pos, equal - pos, "interval_ms")) {
            bit = 2U; value.interval_ms = number;
        } else if (name_equal(body + pos, equal - pos, "epoch")) {
            bit = 4U; value.epoch = number;
        } else return false;
        if ((seen & bit) != 0U) return false;
        seen |= bit;
        pos = end + (end < bytes);
    }
    if (seen != 7U || value.enabled > 1U || value.interval_ms < 200U || value.interval_ms > 5000U) return false;
    *out = value;
    return true;
}

#ifndef GS_ETHERNET_PARSER_TEST

#include "stm32f4xx_hal.h"
#include "lwip/init.h"
#include "lwip/netif.h"
#include "lwip/etharp.h"
#include "lwip/tcp.h"
#include "lwip/timeouts.h"
#include "netif/ethernet.h"

#define RX_BUFFER_BYTES 1536U
#define RX_BUFFER_COUNT 6U
#define TX_BUFFER_COUNT 4U
#define GS_PHY_BSR 1U
#define GS_PHY_ID1 2U
#define GS_PHY_ID2 3U
#define GS_PHY_SCSR 31U
#define GS_PHY_LINK_BIT 0x0004U
#define GS_PHY_AN_DONE_BIT 0x0020U
#define SLOT_FREE 0U
#define SLOT_WRITING 1U
#define SLOT_READY 2U
#define SLOT_SENDING 3U

#if ETH_RX_DESC_CNT >= RX_BUFFER_COUNT
#error "RX_BUFFER_COUNT must exceed ETH_RX_DESC_CNT"
#endif
#if GS_ETH_FRAME1_ADDR < (GS_ETH_FRAME0_ADDR + GS_ETH_FRAME_BYTES)
#error "Ethernet image slots overlap"
#endif

extern ETH_HandleTypeDef heth;
volatile gs_ethernet_diag_t g_gs_eth_diag;

typedef struct {
    struct pbuf_custom custom; /* Must be first: pbuf -> rx_buffer_t */
    uint32_t used;
    uint8_t data[RX_BUFFER_BYTES] __ALIGNED(32);
} rx_buffer_t;
typedef struct {
    uint32_t used;
    uint8_t data[RX_BUFFER_BYTES] __ALIGNED(32);
} tx_buffer_t;
typedef struct {
    volatile uint32_t state; /* SPSC handoff, aligned 32-bit plus DMB */
    uint32_t frame_id, capture_ms, epoch;
    uint8_t *data;
} frame_slot_t;
typedef struct {
    volatile uint32_t sequence;
    volatile uint32_t enabled, interval_ms, epoch, updated_ms;
} shared_control_t;
typedef enum { REQUEST_NONE, REQUEST_CONTROL, REQUEST_FRAME } request_kind_t;

static rx_buffer_t s_rx[RX_BUFFER_COUNT];
static tx_buffer_t s_tx[TX_BUFFER_COUNT];
static frame_slot_t s_frames[2];
static shared_control_t s_control;
static struct netif s_netif;
static ip_addr_t s_server;
static uint8_t s_mac[6];
static char s_device_id[32];
static volatile uint32_t s_initialized;
static uint32_t s_rng = 0x69B2FCA1U;
static uint32_t s_last_offer_ms, s_last_offer_epoch, s_offer_seen;
static uint32_t s_next_control_ms, s_next_post_ms, s_next_phy_ms;
static uint32_t s_phy_mode = UINT32_MAX;
static uint32_t s_mdio_stage, s_mdio_started_ms, s_mdio_bsr;
static uint32_t s_init_attempted;
static uint32_t s_fault;
static struct tcp_pcb *s_pcb;
static request_kind_t s_request;
static int s_active_frame = -1;
static char s_header[512], s_response[HTTP_RESPONSE_CAP];
static size_t s_header_length, s_header_sent, s_body_sent, s_response_length;
static uint32_t s_request_ms, s_activity_ms;
static bool s_connected, s_eof, s_failed, s_processed;

static bool due(uint32_t now, uint32_t deadline)
{
    return (int32_t)(now - deadline) >= 0;
}
static uint32_t acquire(const volatile uint32_t *p)
{
    uint32_t value = *p;
    __DMB();
    return value;
}
static void release(volatile uint32_t *p, uint32_t value)
{
    __DMB();
    *p = value;
}
static void publish_control(const control_values_t *v, uint32_t now)
{
    /* Producer is lower priority: CameraTask seeing odd returns immediately. */
    ++s_control.sequence;
    __DMB();
    s_control.enabled = v->enabled;
    s_control.interval_ms = v->interval_ms;
    s_control.epoch = v->epoch;
    s_control.updated_ms = now;
    __DMB();
    ++s_control.sequence;
    g_gs_eth_diag.capture_enabled = v->enabled;
    g_gs_eth_diag.interval_ms = v->interval_ms;
    g_gs_eth_diag.control_epoch = v->epoch;
}
static bool read_control(control_values_t *v, uint32_t *updated)
{
    uint32_t before = acquire(&s_control.sequence);
    if ((before & 1U) != 0U) return false;
    v->enabled = s_control.enabled;
    v->interval_ms = s_control.interval_ms;
    v->epoch = s_control.epoch;
    *updated = s_control.updated_ms;
    __DMB();
    return before == s_control.sequence;
}
static void disable_capture(uint32_t now)
{
    control_values_t v = {0U, 500U, s_control.epoch};
    publish_control(&v, now);
}

void gs_lwip_assert(const char *file, unsigned line)
{
    (void)file;
    g_gs_eth_diag.fatal = 0x80000000U | (line & 0x7FFFFFFFU);
    /* A violated stack invariant cannot safely resume. The health/watchdog
     * layer can detect this StorageTask stall; no semihosting is attempted. */
    for (;;) { __NOP(); }
}
uint32_t gs_lwip_rand(void)
{
    s_rng ^= s_rng << 13;
    s_rng ^= s_rng >> 17;
    s_rng ^= s_rng << 5;
    return s_rng;
}
u32_t sys_now(void) { return HAL_GetTick(); }

static void rx_free(struct pbuf *p)
{
    ((rx_buffer_t *)p)->used = 0U;
}
void HAL_ETH_RxAllocateCallback(uint8_t **buffer)
{
    unsigned i;
    *buffer = NULL;
    /* Called by HAL Start/ReadData, both on StorageTask, never by our ISR. */
    for (i = 0U; i < RX_BUFFER_COUNT; ++i) {
        if (s_rx[i].used == 0U) {
            s_rx[i].used = 1U;
            s_rx[i].custom.custom_free_function = rx_free;
            (void)pbuf_alloced_custom(PBUF_RAW, 0U, PBUF_REF, &s_rx[i].custom,
                                     s_rx[i].data, RX_BUFFER_BYTES);
            *buffer = s_rx[i].data;
            return;
        }
    }
}
void HAL_ETH_RxLinkCallback(void **start, void **end, uint8_t *buffer, uint16_t length)
{
    rx_buffer_t *rx = (rx_buffer_t *)(buffer - offsetof(rx_buffer_t, data));
    struct pbuf *p = &rx->custom.pbuf;
    struct pbuf *q;
    p->next = NULL;
    p->len = length <= RX_BUFFER_BYTES ? length : 0U;
    p->tot_len = 0U;
    if (*start == NULL) *start = p;
    else ((struct pbuf *)*end)->next = p;
    *end = p;
    for (q = (struct pbuf *)*start; q != NULL; q = q->next) q->tot_len = (u16_t)(q->tot_len + p->len);
}
void HAL_ETH_TxFreeCallback(uint32_t *buffer)
{
    /* HAL_ETH_ReleaseTxPacket is called ONLY from StorageTask. These are
     * fixed copies, not retained lwIP pbufs; no ISR-side free/refcount occurs. */
    ((tx_buffer_t *)buffer)->used = 0U;
}
void HAL_ETH_RxCpltCallback(ETH_HandleTypeDef *h)
{
    if (h == &heth) ++g_gs_eth_diag.rx_irq;
}
void HAL_ETH_TxCpltCallback(ETH_HandleTypeDef *h)
{
    if (h == &heth) ++g_gs_eth_diag.tx_irq;
}
void HAL_ETH_ErrorCallback(ETH_HandleTypeDef *h)
{
    if (h == &heth) ++g_gs_eth_diag.error_irq;
}

static err_t eth_output(struct netif *netif, struct pbuf *p)
{
    unsigned i;
    ETH_BufferTypeDef buffer = {0};
    ETH_TxPacketConfigTypeDef packet = {0};
    if (p->tot_len > RX_BUFFER_BYTES || s_fault != 0U ||
        !netif_is_link_up(netif) || HAL_ETH_GetState(&heth) != HAL_ETH_STATE_STARTED) return ERR_IF;
    for (i = 0U; i < TX_BUFFER_COUNT; ++i) if (s_tx[i].used == 0U) break;
    if (i == TX_BUFFER_COUNT) { ++g_gs_eth_diag.tx_busy; return ERR_MEM; }
    if (pbuf_copy_partial(p, s_tx[i].data, p->tot_len, 0U) != p->tot_len) return ERR_IF;
    buffer.buffer = s_tx[i].data;
    buffer.len = p->tot_len;
    packet.Attributes = ETH_TX_PACKETS_FEATURES_CRCPAD;
    packet.CRCPadCtrl = ETH_CRC_PAD_INSERT;
    packet.Length = p->tot_len;
    packet.TxBuffer = &buffer; /* HAL consumes the list before returning. */
    packet.pData = &s_tx[i];
    s_tx[i].used = 1U;
    __DMB();
    if (HAL_ETH_Transmit_IT(&heth, &packet) != HAL_OK) {
        s_tx[i].used = 0U;
        ++g_gs_eth_diag.tx_busy;
        return ERR_MEM;
    }
    ++g_gs_eth_diag.tx_packets;
    return ERR_OK;
}
static err_t netif_initialize(struct netif *netif)
{
    netif->name[0] = 'g'; netif->name[1] = 's';
    netif->hwaddr_len = 6U;
    memcpy(netif->hwaddr, s_mac, 6U);
    netif->mtu = 1500U;
    netif->flags = NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP | NETIF_FLAG_ETHERNET;
    netif->output = etharp_output;
    netif->linkoutput = eth_output;
    return ERR_OK;
}

static void request_abort(void)
{
    if (s_pcb != NULL) {
        struct tcp_pcb *p = s_pcb;
        s_pcb = NULL;
        tcp_arg(p, NULL); tcp_err(p, NULL); tcp_recv(p, NULL); tcp_sent(p, NULL);
        tcp_abort(p);
    }
}
static err_t receive(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t error)
{
    (void)arg;
    if (error != ERR_OK) s_failed = true;
    if (p == NULL) { s_eof = true; return ERR_OK; }
    if (p->tot_len > HTTP_RESPONSE_CAP - s_response_length) s_failed = true;
    else {
        u16_t copied = pbuf_copy_partial(p, s_response + s_response_length, p->tot_len, 0U);
        if (copied != p->tot_len) s_failed = true;
        else s_response_length += copied;
    }
    tcp_recved(pcb, p->tot_len);
    pbuf_free(p);
    s_activity_ms = HAL_GetTick();
    return ERR_OK;
}
static void tcp_failed(void *arg, err_t error)
{
    (void)arg; (void)error;
    s_pcb = NULL; /* lwIP already freed it. Never tcp_close/abort this pointer. */
    s_failed = true;
}
static err_t sent(void *arg, struct tcp_pcb *pcb, u16_t bytes)
{
    (void)arg; (void)pcb; (void)bytes;
    s_activity_ms = HAL_GetTick();
    return ERR_OK;
}
static err_t connected(void *arg, struct tcp_pcb *pcb, err_t error)
{
    (void)arg; (void)pcb;
    if (error != ERR_OK) s_failed = true;
    else s_connected = true;
    s_activity_ms = HAL_GetTick();
    return ERR_OK;
}
static void install_callbacks(struct tcp_pcb *pcb)
{
    tcp_arg(pcb, NULL); tcp_recv(pcb, receive); tcp_sent(pcb, sent); tcp_err(pcb, tcp_failed);
}
static bool request_begin(request_kind_t kind, int frame, uint32_t now)
{
    int count;
    s_request = kind;
    s_active_frame = frame;
    s_header_sent = s_body_sent = s_response_length = 0U;
    s_connected = s_eof = s_failed = s_processed = false;
    s_request_ms = s_activity_ms = now;
    if (kind == REQUEST_CONTROL) {
        count = snprintf(s_header, sizeof s_header,
                         "GET /api/control HTTP/1.0\r\nHost: %s:%u\r\nX-Device-ID: %s\r\nConnection: close\r\n\r\n",
                         GS_ETH_SERVER_IP, (unsigned)GS_ETH_SERVER_PORT, s_device_id);
    } else {
        const frame_slot_t *slot = &s_frames[frame];
        count = snprintf(s_header, sizeof s_header,
                         "POST /api/frames HTTP/1.0\r\nHost: %s:%u\r\nConnection: close\r\n"
                         "Content-Type: application/octet-stream\r\nContent-Length: 153600\r\n"
                         "X-Device-ID: %s\r\nX-Frame-ID: %lu\r\nX-Capture-Ms: %lu\r\n"
                         "X-Width: 320\r\nX-Height: 240\r\nX-Pixel-Format: RGB565_BE\r\n"
                         "X-Control-Epoch: %lu\r\n\r\n",
                         GS_ETH_SERVER_IP, (unsigned)GS_ETH_SERVER_PORT, s_device_id,
                         (unsigned long)slot->frame_id, (unsigned long)slot->capture_ms,
                         (unsigned long)slot->epoch);
    }
    if (count <= 0 || (size_t)count >= sizeof s_header) { s_failed = true; return false; }
    s_header_length = (size_t)count;
    s_pcb = tcp_new_ip_type(IPADDR_TYPE_V4);
    if (s_pcb == NULL) { s_failed = true; return false; }
    install_callbacks(s_pcb);
    tcp_nagle_disable(s_pcb);
    if (tcp_connect(s_pcb, &s_server, GS_ETH_SERVER_PORT, connected) != ERR_OK) {
        request_abort(); s_failed = true; return false;
    }
    return true;
}
static void request_pump(void)
{
    unsigned budget;
    if (s_pcb == NULL || !s_connected || s_processed || s_failed) return;
    for (budget = 0U; budget < 4U; ++budget) {
        const uint8_t *source;
        size_t remaining;
        u16_t chunk, room = tcp_sndbuf(s_pcb);
        bool header = s_header_sent < s_header_length;
        err_t error;
        if (header) {
            source = (const uint8_t *)s_header + s_header_sent;
            remaining = s_header_length - s_header_sent;
        } else if (s_request == REQUEST_FRAME && s_body_sent < GS_ETH_FRAME_BYTES) {
            source = s_frames[s_active_frame].data + s_body_sent;
            remaining = GS_ETH_FRAME_BYTES - s_body_sent;
        } else break;
        if (room == 0U) break;
        chunk = (u16_t)(remaining < TCP_MSS ? remaining : TCP_MSS);
        if (chunk > room) chunk = room;
        /* COPY means TCP retransmissions never refer to a released frame slot. */
        error = tcp_write(s_pcb, source, chunk, TCP_WRITE_FLAG_COPY);
        if (error == ERR_MEM) break;
        if (error != ERR_OK) { s_failed = true; break; }
        if (header) s_header_sent += chunk;
        else s_body_sent += chunk;
    }
    if (s_pcb != NULL) {
        err_t error = tcp_output(s_pcb);
        if (error != ERR_OK && error != ERR_MEM && error != ERR_BUF && error != ERR_RTE) s_failed = true;
    }
}
static void finish_result(const response_info_t *info, bool success, uint32_t now)
{
    if (s_processed) return;
    s_processed = true;
    if (!success) {
        ++g_gs_eth_diag.http_errors;
        s_next_control_ms = now + GS_ETH_CONTROL_MS;
        if (s_request == REQUEST_CONTROL) disable_capture(now);
    } else {
        unsigned status = info->status;
        g_gs_eth_diag.last_http_status = status;
        if (s_request == REQUEST_CONTROL) {
            control_values_t v;
            if (status == 200U && parse_control(s_response + info->header_bytes, info->body_bytes, &v)) {
                publish_control(&v, now);
            } else { disable_capture(now); ++g_gs_eth_diag.http_errors; }
            s_next_control_ms = now + GS_ETH_CONTROL_MS;
        } else if (status == 201U || status == 200U) {
            if (status == 201U) ++g_gs_eth_diag.uploaded;
            else ++g_gs_eth_diag.duplicate;
            g_gs_eth_diag.last_frame_id = s_frames[s_active_frame].frame_id;
            g_gs_eth_diag.last_upload_ms = now;
            /* The PC applies its interval after committing the previous
             * frame, not after the start of its upload. */
            s_next_post_ms = now + s_control.interval_ms;
        } else if (status == 409U) {
            ++g_gs_eth_diag.rejected_epoch;
            disable_capture(now);
            s_next_control_ms = now;
        } else if (status == 429U) {
            ++g_gs_eth_diag.rate_limited;
            s_next_post_ms = now + (s_control.interval_ms > 1000U ? s_control.interval_ms : 1000U);
            s_next_control_ms = now;
        } else ++g_gs_eth_diag.http_errors;
    }
    if (s_active_frame >= 0) {
        if (!success || (info->status != 200U && info->status != 201U)) ++g_gs_eth_diag.dropped;
        release(&s_frames[s_active_frame].state, SLOT_FREE);
        s_active_frame = -1;
    }
}
static void request_service(uint32_t now)
{
    response_info_t info = {0U, 0U, 0U};
    int result;
    if (s_request == REQUEST_NONE) return;
    if (!s_processed) {
        result = parse_response(s_response, s_response_length, s_eof, &info);
        if (s_failed || result < 0 || now - s_activity_ms >= GS_ETH_HTTP_IDLE_MS ||
            now - s_request_ms >= GS_ETH_HTTP_TOTAL_MS) {
            request_abort(); finish_result(&info, false, now);
        } else if (result > 0) {
            /* A 2xx before the full declared body was queued is not an upload. */
            bool valid = s_request != REQUEST_FRAME || info.status >= 300U || s_body_sent == GS_ETH_FRAME_BYTES;
            finish_result(&info, valid, now);
        } else request_pump();
    }
    if (s_processed) {
        if (s_pcb != NULL) {
            struct tcp_pcb *pcb = s_pcb;
            err_t error;
            tcp_recv(pcb, NULL); tcp_sent(pcb, NULL); tcp_err(pcb, NULL);
            error = tcp_close(pcb);
            if (error == ERR_OK) s_pcb = NULL;
            else {
                install_callbacks(pcb);
                if (now - s_activity_ms >= GS_ETH_HTTP_IDLE_MS) request_abort();
            }
        }
        if (s_pcb == NULL) s_request = REQUEST_NONE;
    }
}

bool gs_ethernet_init(void)
{
    ip4_addr_t ip, mask, gateway;
    uint32_t uid[3], id1, id2;
    ETH_MACConfigTypeDef mac;
    unsigned i;
    if (acquire(&s_initialized) != 0U) return s_fault == 0U;
    if (s_init_attempted != 0U) return false;
    if (heth.Instance != ETH || heth.gState != HAL_ETH_STATE_READY ||
        heth.Init.RxBuffLen != RX_BUFFER_BYTES || heth.Init.RxDesc == NULL || heth.Init.TxDesc == NULL) return false;
    /* DMA data/descriptor ranges must be in the 192 KiB ordinary SRAM. */
    if ((uintptr_t)heth.Init.RxDesc < 0x20000000UL ||
        (uintptr_t)heth.Init.RxDesc + sizeof(ETH_DMADescTypeDef) * ETH_RX_DESC_CNT > 0x20030000UL ||
        (uintptr_t)heth.Init.TxDesc < 0x20000000UL ||
        (uintptr_t)heth.Init.TxDesc + sizeof(ETH_DMADescTypeDef) * ETH_TX_DESC_CNT > 0x20030000UL) return false;
    s_init_attempted = 1U; /* A partially initialized stack must not be initialized twice. */
    uid[0] = HAL_GetUIDw0(); uid[1] = HAL_GetUIDw1(); uid[2] = HAL_GetUIDw2();
    s_rng ^= uid[0] ^ uid[1] ^ uid[2];
    if (s_rng == 0U) s_rng = 1U;
    s_mac[0] = 0x02U; /* locally administered, unicast */
    for (i = 1U; i < 6U; ++i) s_mac[i] = (uint8_t)gs_lwip_rand();
    (void)snprintf(s_device_id, sizeof s_device_id, "gs-%08lX%08lX%08lX",
                   (unsigned long)uid[0], (unsigned long)uid[1], (unsigned long)uid[2]);
    heth.Init.MACAddr = s_mac;
    /* Rebuild once using the permanent UID MAC, not CubeMX's default address. */
    if (HAL_ETH_Init(&heth) != HAL_OK) return false;
    if (HAL_ETH_ReadPHYRegister(&heth, GS_ETH_PHY_ADDRESS, GS_PHY_ID1, &id1) != HAL_OK ||
        HAL_ETH_ReadPHYRegister(&heth, GS_ETH_PHY_ADDRESS, GS_PHY_ID2, &id2) != HAL_OK ||
        id1 != 0x0007U || (id2 & 0xFFF0U) != 0xC0F0U) {
        ++g_gs_eth_diag.phy_errors; return false;
    }
    if (!ip4addr_aton(GS_ETH_BOARD_IP, &ip) || !ip4addr_aton(GS_ETH_NETMASK, &mask) ||
        !ip4addr_aton(GS_ETH_GATEWAY, &gateway) || !ipaddr_aton(GS_ETH_SERVER_IP, &s_server)) return false;
    memset(s_rx, 0, sizeof s_rx); memset(s_tx, 0, sizeof s_tx);
    s_frames[0].data = (uint8_t *)GS_ETH_FRAME0_ADDR;
    s_frames[1].data = (uint8_t *)GS_ETH_FRAME1_ADDR;
    s_frames[0].state = s_frames[1].state = SLOT_FREE;
    lwip_init();
    if (netif_add(&s_netif, &ip, &mask, &gateway, NULL, netif_initialize, ethernet_input) == NULL) return false;
    netif_set_default(&s_netif); netif_set_up(&s_netif); netif_set_link_down(&s_netif);
    if (HAL_ETH_GetMACConfig(&heth, &mac) != HAL_OK) return false;
    mac.ChecksumOffload = DISABLE;
    if (HAL_ETH_SetMACConfig(&heth, &mac) != HAL_OK) return false;
    /* Keep HAL in READY until PHY negotiation supplies the actual mode:
     * HAL_ETH_SetMACConfig rejects STARTED in this CubeF4 version. */
    disable_capture(HAL_GetTick());
    s_next_control_ms = s_next_post_ms = s_next_phy_ms = HAL_GetTick();
    g_gs_eth_diag.initialized = 1U;
    release(&s_initialized, 1U);
    return true;
}

bool gs_ethernet_offer_frame(const void *rgb565_be, size_t bytes,
                            uint32_t frame_id, uint32_t capture_ms)
{
    control_values_t control;
    uint32_t updated, now = HAL_GetTick();
    unsigned i;
    if (rgb565_be == NULL || bytes != GS_ETH_FRAME_BYTES || acquire(&s_initialized) == 0U ||
        !read_control(&control, &updated) || control.enabled == 0U ||
        now - updated >= GS_ETH_CONTROL_TTL_MS || now - capture_ms >= GS_ETH_CONTROL_TTL_MS) return false;
    if (s_offer_seen != 0U && s_last_offer_epoch == control.epoch &&
        capture_ms - s_last_offer_ms < control.interval_ms) return false;
    for (i = 0U; i < 2U; ++i) if (acquire(&s_frames[i].state) == SLOT_FREE) break;
    if (i == 2U) { ++g_gs_eth_diag.offer_busy; return false; }
    s_frames[i].state = SLOT_WRITING;
    memcpy(s_frames[i].data, rgb565_be, GS_ETH_FRAME_BYTES);
    s_frames[i].frame_id = frame_id; s_frames[i].capture_ms = capture_ms; s_frames[i].epoch = control.epoch;
    release(&s_frames[i].state, SLOT_READY);
    s_last_offer_ms = capture_ms; s_last_offer_epoch = control.epoch; s_offer_seen = 1U;
    ++g_gs_eth_diag.offered;
    return true;
}

static bool mdio_begin(uint32_t reg, uint32_t now)
{
    uint32_t mii = heth.Instance->MACMIIAR;
    if ((mii & ETH_MACMIIAR_MB) != 0U) return false;
    /* Exactly the fields used by HAL_ETH_ReadPHYRegister, retaining HAL's
     * HCLK-derived MDC prescaler. Completion is checked on the next step,
     * avoiding HAL's potentially 1 s busy wait during a disconnected PHY. */
    heth.Instance->MACMIIAR = (mii & ETH_MACMIIAR_CR) |
        ((GS_ETH_PHY_ADDRESS << 11U) & ETH_MACMIIAR_PA) |
        ((reg << 6U) & ETH_MACMIIAR_MR) | ETH_MACMIIAR_MB;
    s_mdio_started_ms = now;
    return true;
}
static void apply_phy_mode(uint32_t bsr, uint32_t mode, uint32_t now)
{
    ETH_MACConfigTypeDef mac;
    if ((bsr & (GS_PHY_LINK_BIT | GS_PHY_AN_DONE_BIT)) != (GS_PHY_LINK_BIT | GS_PHY_AN_DONE_BIT)) {
        if (netif_is_link_up(&s_netif)) {
            netif_set_link_down(&s_netif);
            disable_capture(now); s_failed = true;
        }
        g_gs_eth_diag.link_up = 0U;
        return;
    }
    mode &= 0x001CU;
    if (mode != 0x0004U && mode != 0x0008U && mode != 0x0014U && mode != 0x0018U) return;
    if (mode != s_phy_mode) {
        if (HAL_ETH_GetState(&heth) == HAL_ETH_STATE_STARTED) {
            /* Keep every RX/TX allocation and descriptor intact across a
             * speed change. Stop is NOT permission to recycle DMA buffers. */
            netif_set_link_down(&s_netif); disable_capture(now); s_failed = true;
            g_gs_eth_diag.link_up = 0U;
            if (HAL_ETH_Stop_IT(&heth) != HAL_OK) return;
        }
        if (HAL_ETH_GetMACConfig(&heth, &mac) != HAL_OK) return;
        mac.Speed = (mode & 0x0004U) != 0U ? ETH_SPEED_10M : ETH_SPEED_100M;
        mac.DuplexMode = (mode & 0x0010U) != 0U ? ETH_FULLDUPLEX_MODE : ETH_HALFDUPLEX_MODE;
        mac.ChecksumOffload = DISABLE;
        if (HAL_ETH_SetMACConfig(&heth, &mac) != HAL_OK) return;
        s_phy_mode = mode;
    }
    if (HAL_ETH_GetState(&heth) == HAL_ETH_STATE_READY && HAL_ETH_Start_IT(&heth) != HAL_OK) return;
    if (!netif_is_link_up(&s_netif)) {
        netif_set_link_up(&s_netif); s_next_control_ms = now;
    }
    g_gs_eth_diag.link_up = 1U;
}

static void phy_service(uint32_t now)
{
    uint32_t value;
    if (s_mdio_stage == 0U) {
        if (!due(now, s_next_phy_ms)) return;
        if (!mdio_begin(GS_PHY_BSR, now)) {
            ++g_gs_eth_diag.phy_errors;
            apply_phy_mode(0U, 0U, now);
            s_next_phy_ms = now + 500U;
        } else s_mdio_stage = 1U;
        return;
    }
    if ((heth.Instance->MACMIIAR & ETH_MACMIIAR_MB) != 0U) {
        if (now - s_mdio_started_ms >= 20U) {
            ++g_gs_eth_diag.phy_errors;
            s_mdio_stage = 0U; s_next_phy_ms = now + 500U;
            apply_phy_mode(0U, 0U, now);
        }
        return;
    }
    value = heth.Instance->MACMIIDR & 0xFFFFU;
    if (s_mdio_stage == 1U) {
        /* BSR is latched-low: discard the first result and read current link. */
        if (mdio_begin(GS_PHY_BSR, now)) s_mdio_stage = 2U;
    } else if (s_mdio_stage == 2U) {
        s_mdio_bsr = value;
        if (mdio_begin(GS_PHY_SCSR, now)) s_mdio_stage = 3U;
    } else {
        s_mdio_stage = 0U; s_next_phy_ms = now + 500U;
        apply_phy_mode(s_mdio_bsr, value, now);
    }
}

void gs_ethernet_step(uint32_t now_ms)
{
    unsigned i;
    control_values_t control;
    uint32_t updated;
    if (acquire(&s_initialized) == 0U || s_fault != 0U) return;
    if (HAL_ETH_GetState(&heth) == HAL_ETH_STATE_ERROR ||
        (HAL_ETH_GetDMAError(&heth) & ETH_DMA_FATAL_BUS_ERROR_FLAG) != 0U) {
        ++g_gs_eth_diag.dma_errors;
        disable_capture(now_ms); request_abort();
        s_fault = 1U; g_gs_eth_diag.fatal = 1U;
        /* Preserve DMA-owned buffers on fatal bus error. Recovery requires a
         * stopped/reset MAC; never reclaim memory on an unproven DMA stop. */
        return;
    }
    (void)HAL_ETH_ReleaseTxPacket(&heth);
    /* Bounded RX work: prevent an incoming flood from starving task heartbeat. */
    for (i = 0U; i < 8U; ++i) {
        struct pbuf *p = NULL;
        uint32_t error = 0U;
        if (HAL_ETH_ReadData(&heth, (void **)&p) != HAL_OK || p == NULL) break;
        (void)HAL_ETH_GetRxDataErrorCode(&heth, &error);
        if (error != 0U || p->tot_len < 14U || p->tot_len > RX_BUFFER_BYTES) {
            ++g_gs_eth_diag.rx_errors; pbuf_free(p);
        } else {
            ++g_gs_eth_diag.rx_packets;
            if (s_netif.input(p, &s_netif) != ERR_OK) pbuf_free(p);
        }
    }
    sys_check_timeouts();
    phy_service(now_ms);
    if (read_control(&control, &updated) && control.enabled != 0U &&
        now_ms - updated >= GS_ETH_CONTROL_TTL_MS) disable_capture(now_ms);
    request_service(now_ms);
    /* Discard copies made under a previous control epoch, expired control or
     * a stopped session. Never touch SLOT_WRITING: the CameraTask owns it. */
    for (i = 0U; i < 2U; ++i) {
        if (acquire(&s_frames[i].state) == SLOT_READY &&
            (s_control.enabled == 0U || s_frames[i].epoch != s_control.epoch ||
             now_ms - s_frames[i].capture_ms >= GS_ETH_CONTROL_TTL_MS)) {
            ++g_gs_eth_diag.dropped; release(&s_frames[i].state, SLOT_FREE);
        }
    }
    if (s_request != REQUEST_NONE || !netif_is_link_up(&s_netif)) return;
    if (due(now_ms, s_next_control_ms)) {
        (void)request_begin(REQUEST_CONTROL, -1, now_ms);
    } else if (s_control.enabled != 0U && due(now_ms, s_next_post_ms)) {
        for (i = 0U; i < 2U; ++i) {
            if (acquire(&s_frames[i].state) == SLOT_READY) {
                s_frames[i].state = SLOT_SENDING;
                s_next_post_ms = now_ms + s_control.interval_ms;
                (void)request_begin(REQUEST_FRAME, (int)i, now_ms);
                break;
            }
        }
    }
}

#else /* GS_ETHERNET_PARSER_TEST: compile with the host C compiler. */
#include <assert.h>
int main(void)
{
    response_info_t info;
    control_values_t control;
    uint32_t value;
    const char reply[] = "HTTP/1.0 200 OK\r\nContent-Length: 40\r\n\r\nenabled=1\ninterval_ms=500\nepoch=1234567\n";
    size_t n;
    assert(decimal_u32("4294967295", 10U, &value) && value == UINT32_MAX);
    assert(!decimal_u32("4294967296", 10U, &value));
    assert(!decimal_u32("-1", 2U, &value));
    for (n = 0U; n < sizeof reply - 1U; ++n) assert(parse_response(reply, n, false, &info) == 0);
    assert(parse_response(reply, sizeof reply - 1U, false, &info) == 1);
    assert(parse_control(reply + info.header_bytes, info.body_bytes, &control));
    assert(control.enabled == 1U && control.interval_ms == 500U && control.epoch == 1234567U);
    {
        const char too_fast[] = "enabled=1\ninterval_ms=199\nepoch=1\n";
        const char repeated[] = "enabled=1\ninterval_ms=500\nepoch=1\nepoch=2\n";
        assert(!parse_control(too_fast, sizeof too_fast - 1U, &control));
        assert(!parse_control(repeated, sizeof repeated - 1U, &control));
    }
    {
        const char truncated[] = "HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\na";
        const char duplicate[] = "HTTP/1.0 200 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n";
        const char chunked[] = "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n";
        const char close_reply[] = "HTTP/1.0 201 Created\r\n\r\nOK";
        assert(parse_response(truncated, sizeof truncated - 1U, true, &info) == -1);
        assert(parse_response(duplicate, sizeof duplicate - 1U, false, &info) == -1);
        assert(parse_response(chunked, sizeof chunked - 1U, false, &info) == -1);
        assert(parse_response(close_reply, sizeof close_reply - 1U, false, &info) == 0);
        assert(parse_response(close_reply, sizeof close_reply - 1U, true, &info) == 1 && info.status == 201U);
    }
    puts("gs_ethernet HTTP/control parser: bounded fragments, EOF, uint32, duplicate/chunked checks passed");
    return 0;
}
#endif
