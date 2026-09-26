#ifndef GS_PREVIEW_H
#define GS_PREVIEW_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "gs_preprocess.h"

#ifdef __cplusplus
extern "C" {
#endif

#define GS_PREVIEW_SLOTS 2U
#define GS_PREVIEW_WIDTH 96U
#define GS_PREVIEW_HEIGHT 96U
#define GS_PREVIEW_BYTES (GS_PREVIEW_WIDTH * GS_PREVIEW_HEIGHT)
#define GS_PREVIEW_SOURCE_WIDTH 96U
#define GS_PREVIEW_SOURCE_HEIGHT 96U
#define GS_PREVIEW_SOURCE_BYTES (GS_PREVIEW_SOURCE_WIDTH * GS_PREVIEW_SOURCE_HEIGHT)

typedef enum {
    GS_PREVIEW_OK = 0,
    GS_PREVIEW_INVALID,
    GS_PREVIEW_BUSY,
    GS_PREVIEW_STALE,
    GS_PREVIEW_TOKEN_EXHAUSTED
} gs_preview_result_t;

typedef struct {
    uint32_t token;
    uint8_t slot;
} gs_preview_ticket_t;

typedef struct {
    gs_preview_ticket_t ticket;
    const uint8_t *pixels;
    size_t bytes;
    uint16_t width;
    uint16_t height;
    uint32_t frame_id;
    uint32_t capture_ms;
} gs_preview_frame_t;

typedef struct {
    uint8_t *pixels;
    uint32_t token;
    bool in_use;
} gs_preview_slot_t;

typedef struct {
    gs_preview_slot_t slots[GS_PREVIEW_SLOTS];
    uint32_t next_token;
    bool initialized;
} gs_preview_pool_t;

/* CameraTask 独占预览池。publish 将 96×96 int8 输入复制为
 * 96×96 无符号灰度图，因此无需继续持有相机原图租约。
 * 把返回的小描述符交给 GuiTask；GuiTask 在 gs_port_gui_render 返回后
 * 归还 ticket，只有 CameraTask 执行释放。
 * 调用者提供两块互不重叠、4 字节对齐、容量为 GS_PREVIEW_BYTES 的缓冲。 */
gs_preview_result_t gs_preview_pool_init(gs_preview_pool_t *pool,
    void *buffer0, size_t capacity0, void *buffer1, size_t capacity1);
gs_preview_result_t gs_preview_publish(gs_preview_pool_t *pool,
    const int8_t *source, size_t source_count, uint32_t frame_id,
    uint32_t capture_ms, gs_preview_frame_t *frame);
/* Preview-only sampling: exactly the model's RGB565/Y/ROI/2x2 rounding, with
 * no recognition quality statistics. Dark/bright images remain visible.
 * Camera must hold the complete raw lease throughout this call. It writes only
 * a FREE preview slot, then publishes its immutable lease after all pixels.
 * Input must not overlap the chosen slot. No inference tensor is accessed. */
gs_preview_result_t gs_preview_publish_rgb565(gs_preview_pool_t *pool,
    const gs_rgb565_frame_t *source, uint32_t frame_id,
    uint32_t capture_ms, gs_preview_frame_t *frame);
gs_preview_result_t gs_preview_release(gs_preview_pool_t *pool,
    gs_preview_ticket_t ticket);

/* Independent debugger evidence; old App/board diagnostic layouts are unchanged.
 * Camera writes sample/published fields; GUI writes copied/confirmed fields.
 * A debugger read is not an atomic snapshot. Durations/ages are wall-clock ms;
 * confirmation age includes the GUI's delay observing the reload IRQ. */
typedef struct {
    uint32_t sampled, invalid, max_sample_ms, published_id, published_capture_ms;
    uint32_t copied, copied_id, copied_capture_ms;
    uint32_t confirmed_unique, confirmed_id, confirmed_capture_ms, confirmed_age_ms;
} gs_preview_diagnostics_t;
extern volatile gs_preview_diagnostics_t g_gs_preview_diag;

#ifdef __cplusplus
}
#endif
#endif
