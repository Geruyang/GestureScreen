#ifndef GS_ETHERNET_H
#define GS_ETHERNET_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Editable LAN profile. The PC capture server must be reachable on this subnet.
 * These are local development defaults, not DHCP-discovered addresses. */
#define GS_ETH_BOARD_IP       "192.168.1.40"
#define GS_ETH_NETMASK        "255.255.255.0"
#define GS_ETH_GATEWAY        "192.168.1.1"
#define GS_ETH_SERVER_IP      "192.168.1.100"
#define GS_ETH_SERVER_PORT    8765U
#define GS_ETH_PHY_ADDRESS    0U
#define GS_ETH_FRAME_BYTES    153600U
#define GS_ETH_FRAME0_ADDR    0xD0380000UL
#define GS_ETH_FRAME1_ADDR    0xD03A5800UL
#define GS_ETH_CONTROL_MS     1000U
#define GS_ETH_CONTROL_TTL_MS 5000U
#define GS_ETH_HTTP_IDLE_MS   5000U
#define GS_ETH_HTTP_TOTAL_MS  15000U

typedef struct {
    uint32_t initialized;
    uint32_t link_up;
    uint32_t capture_enabled;
    uint32_t interval_ms;
    uint32_t control_epoch;
    uint32_t offered;
    uint32_t offer_busy;
    uint32_t uploaded;
    uint32_t duplicate;
    uint32_t rejected_epoch;
    uint32_t rate_limited;
    uint32_t dropped;
    uint32_t http_errors;
    uint32_t last_http_status;
    uint32_t rx_packets;
    uint32_t tx_packets;
    uint32_t rx_errors;
    uint32_t tx_busy;
    uint32_t phy_errors;
    uint32_t dma_errors;
    uint32_t fatal;
    uint32_t last_frame_id;
    uint32_t last_upload_ms;
    uint32_t rx_irq;
    uint32_t tx_irq;
    uint32_t error_irq;
} gs_ethernet_diag_t;

/* Diagnostic fields have individual writers; a debugger snapshot is not an
 * atomic transaction across every counter. MAC/device ID are derived from UID. */
extern volatile gs_ethernet_diag_t g_gs_eth_diag;

/* StorageTask only, once, AFTER SDRAM validation, MX_ETH_Init and PHY reset
 * release. Descriptors must remain in ordinary SRAM (never CCM). Initialization
 * may perform HAL's bounded hardware setup; it never waits for cable/link/TCP. */
bool gs_ethernet_init(void);

/* StorageTask only, every 5..10 ms. This is the ONLY lwIP/raw API caller.
 * The lwIP port is NO_SYS=1 despite the surrounding FreeRTOS application.
 * IRQ callbacks only record flags/counters; pbuf operations occur here. */
void gs_ethernet_step(uint32_t now_ms);

/* Single producer: CameraTask only. Call while owning a complete RGB565_BE
 * frame. Copies bytes into an independent SDRAM slot before returning; never
 * retains rgb565_be. No network wait, allocation or RTOS lock. False means
 * disabled/expired control, rate limit, wrong size, or both slots unavailable.
 * The bounded 150 KiB CPU copy is intentional and needs on-board timing QA. */
bool gs_ethernet_offer_frame(const void *rgb565_be, size_t bytes,
                            uint32_t frame_id, uint32_t capture_ms);

/* Called by the generated lwIP arch header; no printing/semihosting. */
void gs_lwip_assert(const char *file, unsigned line);
uint32_t gs_lwip_rand(void);

#endif
