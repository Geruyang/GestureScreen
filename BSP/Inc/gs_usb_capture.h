#ifndef GS_USB_CAPTURE_H
#define GS_USB_CAPTURE_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef struct {
    uint32_t initialized, configured, controls, bad_controls, rx_overflow;
    uint32_t capture_enabled, epoch, interval_ms, offered, busy, sent, dropped;
    uint32_t tx_errors, last_frame_id, last_send_ms, link_resets;
} gs_usb_diag_t;
extern volatile gs_usb_diag_t g_gs_usb_diag;
/* StorageTask owns USB stack start and sender; CameraTask is sole producer.
 * Independent SDRAM copies; no frame lease retained, no allocation in the loop. */
void gs_usb_capture_init(void);
void gs_usb_capture_step(uint32_t now_ms);
bool gs_usb_capture_offer(const void *pixels, size_t bytes, uint32_t id, uint32_t ms);
/* CDC callbacks: bounded IRQ work, no RTOS API. */
void gs_usb_capture_receive(const uint8_t *data, size_t bytes);
void gs_usb_capture_link_reset(void);
void gs_usb_capture_tx_complete(void);
#endif
