#include "gs_usb_capture.h"
#include "gs_capture_config.h"
#include "gs_usb_protocol.h"
#include "gs_memory_map.h"
#include "stm32f4xx_hal.h"
#if GS_ENABLE_USB_CAPTURE
#include "usb_device.h"
#include "usbd_cdc_if.h"
#include "usbd_cdc.h"
extern USBD_HandleTypeDef hUsbDeviceHS;
#define RX_CAP 256U
#define TX_CAP 4096U
#define CONTROL_TTL 1500U
#define FRAME_TIMEOUT 3000U
#define CRC_STEP_BYTES 4096U
enum { FREE, WRITING, READY, SENDING };
typedef struct {
    volatile uint32_t state;
    uint32_t id, ms, epoch, cookie, sequence;
    uint32_t crc_state, crc_bytes, crc_value, crc_ready;
    uint8_t *data;
} slot_t;
static slot_t slots[2];
static uint8_t rx[RX_CAP], command[GS_USB_CONTROL_BYTES];
static uint8_t tx[TX_CAP] __ALIGNED(4);
static volatile uint32_t rx_write, rx_read, link_generation, tx_busy;
/* This control snapshot is read by a higher priority producer. The writer
 * cannot use a spin seqlock: it may be preempted by that reader. */
static volatile uint32_t enabled, interval_ms, epoch, cookie, control_ms;
static uint32_t seen_generation, command_bytes, last_offer_ms, offer_seen;
static uint32_t last_offer_epoch, last_offer_cookie, offset, start_ms, header_sent;
/* CameraTask is the sole producer. Number successful READY publications,
 * independently of camera timestamps/IDs and without changing slot ownership. */
static uint32_t offer_sequence;
static int active=-1;
static uint32_t acquire(const volatile uint32_t *p) { uint32_t v=*p; __DMB(); return v; }
static void publish(volatile uint32_t *p,uint32_t v) { __DMB(); *p=v; }

void gs_usb_capture_receive(const uint8_t *data,size_t bytes)
{
    uint32_t w=rx_write, r=acquire(&rx_read);
    if (bytes>RX_CAP-(w-r)) { ++g_gs_usb_diag.rx_overflow; return; }
    for (size_t i=0;i<bytes;++i) rx[(w+(uint32_t)i)&(RX_CAP-1U)]=data[i];
    publish(&rx_write,w+(uint32_t)bytes);
}
void gs_usb_capture_link_reset(void)
{
    enabled=0; tx_busy=0; ++link_generation; ++g_gs_usb_diag.link_resets;
}
void gs_usb_capture_tx_complete(void) { publish(&tx_busy,0); }

void gs_usb_capture_init(void)
{
    slots[0].data=(uint8_t *)GS_UPLOAD_BUFFER0_ADDR;
    slots[1].data=(uint8_t *)GS_UPLOAD_BUFFER1_ADDR;
    interval_ms=200U;
    g_gs_usb_diag.initialized=1;
    MX_USB_DEVICE_Init(); /* once, after SDRAM validation, from running task */
}
bool gs_usb_capture_offer(const void *pixels,size_t bytes,uint32_t id,uint32_t ms)
{
    uint32_t e, c, period, updated, on;
    uint32_t mask=__get_PRIMASK();
    __disable_irq();
    on=enabled; e=epoch; c=cookie; period=interval_ms; updated=control_ms;
    __set_PRIMASK(mask);
    if (!g_gs_usb_diag.initialized || !on || pixels==NULL || bytes!=GS_USB_FRAME_BYTES ||
        HAL_GetTick()-updated>CONTROL_TTL) return false;
    if (offer_seen && last_offer_epoch==e && last_offer_cookie==c && ms-last_offer_ms<period) return false;
    for (unsigned i=0;i<2U;++i) {
        if (acquire(&slots[i].state)!=FREE) continue;
        slots[i].state=WRITING;
        memcpy(slots[i].data,pixels,bytes);
        slots[i].id=id; slots[i].ms=ms; slots[i].epoch=e; slots[i].cookie=c;
        slots[i].sequence=offer_sequence++;
        publish(&slots[i].state,READY);
        offer_seen=1; last_offer_ms=ms; last_offer_epoch=e; last_offer_cookie=c;
        ++g_gs_usb_diag.offered;
        return true;
    }
    ++g_gs_usb_diag.busy; return false;
}
static void consume_controls(uint32_t now)
{
    unsigned budget=RX_CAP;
    while (budget-- && rx_read!=acquire(&rx_write)) {
        command[command_bytes++]=rx[rx_read&(RX_CAP-1U)];
        publish(&rx_read,rx_read+1U);
        if (command_bytes<GS_USB_CONTROL_BYTES) continue;
        gs_usb_control_t ctl;
        if (gs_usb_decode_control(command,&ctl)) {
            uint32_t mask=__get_PRIMASK();
            __disable_irq();
            enabled=ctl.enabled; interval_ms=ctl.interval_ms; epoch=ctl.epoch;
            cookie=ctl.cookie; control_ms=now;
            __set_PRIMASK(mask);
            command_bytes=0; ++g_gs_usb_diag.controls;
        } else {
            memmove(command,command+1,GS_USB_CONTROL_BYTES-1U);
            command_bytes=GS_USB_CONTROL_BYTES-1U; ++g_gs_usb_diag.bad_controls;
        }
    }
}
/* No slot pointer reaches the asynchronous USB stack. Only this staging
 * buffer remains immutable until DataIn completion (including its ZLP). */
static bool submit(uint16_t bytes)
{
    uint32_t mask=__get_PRIMASK();
    uint8_t status;
    __disable_irq();
    if (hUsbDeviceHS.dev_state!=USBD_STATE_CONFIGURED || hUsbDeviceHS.pClassData==NULL) {
        __set_PRIMASK(mask); return false;
    }
    tx_busy=1;
    status=CDC_Transmit_HS(tx,bytes);
    if (status!=USBD_OK) tx_busy=0;
    __set_PRIMASK(mask);
    if (status!=USBD_OK && status!=USBD_BUSY) ++g_gs_usb_diag.tx_errors;
    return status==USBD_OK;
}
void gs_usb_capture_step(uint32_t now)
{
    if (seen_generation!=acquire(&link_generation)) {
        seen_generation=link_generation;
        enabled=0; command_bytes=0;
        /* Discard pre-reset bytes; IRQ producer cannot interleave this update. */
        uint32_t mask=__get_PRIMASK(); __disable_irq(); rx_read=rx_write; __set_PRIMASK(mask);
        if (active>=0) { publish(&slots[active].state,FREE); active=-1; ++g_gs_usb_diag.dropped; }
    }
    consume_controls(now);
    g_gs_usb_diag.configured=hUsbDeviceHS.dev_state==USBD_STATE_CONFIGURED;
    bool valid=enabled && g_gs_usb_diag.configured && now-control_ms<=CONTROL_TTL;
    g_gs_usb_diag.capture_enabled=valid; g_gs_usb_diag.epoch=epoch;
    g_gs_usb_diag.interval_ms=interval_ms;
    if (active>=0 && (!valid || slots[active].epoch!=epoch || slots[active].cookie!=cookie || now-start_ms>FRAME_TIMEOUT)) {
        publish(&slots[active].state,FREE); active=-1; ++g_gs_usb_diag.dropped;
    }
    for (unsigned i=0;i<2U;++i) {
        if (acquire(&slots[i].state)==READY && (!valid || slots[i].epoch!=epoch || slots[i].cookie!=cookie)) {
            publish(&slots[i].state,FREE); ++g_gs_usb_diag.dropped;
        }
    }
    if (!valid || acquire(&tx_busy)) return;
    if (active<0) {
        int oldest=-1;
        for (unsigned i=0;i<2U;++i) {
            if (acquire(&slots[i].state)!=READY) continue;
            /* At most two pending publications; their serial distance is below
             * half the uint32 range, including UINT32_MAX -> 0 rollover.
             * A refilled slot0 must not overtake an older waiting slot1. */
            if (oldest<0 || slots[i].sequence-slots[oldest].sequence>=0x80000000U) {
                oldest=(int)i;
            }
        }
        if (oldest>=0) {
            slots[oldest].state=SENDING; active=oldest;
            offset=0; header_sent=0; start_ms=now;
            slots[oldest].crc_state=GS_USB_CRC32_INITIAL;
            slots[oldest].crc_bytes=0U; slots[oldest].crc_value=0U;
            slots[oldest].crc_ready=0U;
        }
    }
    if (active<0) return;
    slot_t *s=&slots[active];
    if (!s->crc_ready) {
        uint32_t n=GS_USB_FRAME_BYTES-s->crc_bytes;
        if (n>CRC_STEP_BYTES) n=CRC_STEP_BYTES;
        s->crc_state=gs_usb_crc32_update(s->crc_state,s->data+s->crc_bytes,n);
        s->crc_bytes+=n;
        if (s->crc_bytes==GS_USB_FRAME_BYTES) {
            s->crc_value=gs_usb_crc32_finish(s->crc_state);
            s->crc_ready=1U;
        }
        return; /* At most one 4 KiB CRC slice per StorageTask service. */
    }
    if (!header_sent) {
        uint32_t uid[3]={HAL_GetUIDw0(),HAL_GetUIDw1(),HAL_GetUIDw2()};
        gs_usb_frame_header(tx,s->id,s->ms,s->epoch,s->crc_value,uid);
        if (submit(GS_USB_HEADER_BYTES)) header_sent=1;
    } else if (offset<GS_USB_FRAME_BYTES) {
        uint32_t n=GS_USB_FRAME_BYTES-offset; if (n>TX_CAP) n=TX_CAP;
        memcpy(tx,s->data+offset,n);
        if (submit((uint16_t)n)) offset+=n;
    } else {
        g_gs_usb_diag.last_frame_id=s->id; g_gs_usb_diag.last_send_ms=now;
        ++g_gs_usb_diag.sent; publish(&s->state,FREE); active=-1;
    }
}
#else
void gs_usb_capture_init(void) {}
void gs_usb_capture_step(uint32_t now) { (void)now; }
bool gs_usb_capture_offer(const void *p,size_t n,uint32_t id,uint32_t ms)
{ (void)p; (void)n; (void)id; (void)ms; return false; }
void gs_usb_capture_receive(const uint8_t *p,size_t n) { (void)p; (void)n; }
void gs_usb_capture_link_reset(void) {}
void gs_usb_capture_tx_complete(void) {}
#endif
volatile gs_usb_diag_t g_gs_usb_diag;
