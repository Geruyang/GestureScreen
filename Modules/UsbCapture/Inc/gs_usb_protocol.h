#ifndef GS_USB_PROTOCOL_H
#define GS_USB_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#define GS_USB_HEADER_BYTES 48U
#define GS_USB_CONTROL_BYTES 24U
#define GS_USB_FRAME_BYTES 153600U
#define GS_USB_CRC32_INITIAL UINT32_MAX
typedef struct { uint32_t enabled, interval_ms, epoch, cookie; } gs_usb_control_t;
uint32_t gs_usb_crc32_update(uint32_t state, const void *data, size_t bytes);
uint32_t gs_usb_crc32_finish(uint32_t state);
uint32_t gs_usb_crc32(const void *data, size_t bytes);
bool gs_usb_decode_control(const uint8_t *data, gs_usb_control_t *control);
void gs_usb_frame_header(uint8_t *data, uint32_t frame_id, uint32_t capture_ms,
                         uint32_t epoch, uint32_t crc, const uint32_t uid[3]);
#endif
