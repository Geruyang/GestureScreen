#ifndef GS_UI_RENDER_H
#define GS_UI_RENDER_H

#include "gs_ui.h"
#include "gs_preview.h"
#include "gs_static_recognition.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GS_UI_RENDER_MIN_WIDTH 320U
#define GS_UI_RENDER_MIN_HEIGHT 240U
#define GS_UI_PREVIEW_TTL_MS 1500U /* Display-only last image; age is always shown. */

typedef enum {
    GS_UI_RENDER_OK = 0,
    GS_UI_RENDER_INVALID_ARGUMENT,
    GS_UI_RENDER_BUFFER_TOO_SMALL,
    GS_UI_RENDER_INVALID_STATE
} gs_ui_render_status_t;

typedef struct {
    uint16_t background;
    uint16_t surface;
    uint16_t primary;
    uint16_t secondary;
    uint16_t text;
    uint16_t muted_text;
} gs_ui_render_theme_t;

gs_ui_render_theme_t gs_ui_render_default_theme(void);

typedef struct {
    gs_static_result_t recognition;
    /* Display only: latest completed, qualified target within 300 ms. */
    uint32_t hint_valid, hint_class;
    uint32_t camera_frames, camera_drops, camera_errors, healthy, seven_class_ready, now_ms, processing;
    uint32_t preview_age_ms, preview_frame_id;
    uint32_t control_enabled, business_validated;
    uint32_t gesture_state, gesture_progress;
    uint32_t vision_frames, vision_age_ms, camera_fps_milli, vision_fps_milli;
    uint32_t quality_rejects, preview_drops, inference_errors, inference_timeouts;
    uint32_t max_inference_ms, heap_free_bytes, heap_min_free_bytes, stack_min_free_bytes;
    uint32_t content_checked, content_total, content_errors;
    const char *content_version;
    const uint8_t *content_rgb565_be;
    uint32_t content_image_bytes;
    uint16_t content_image_width, content_image_height;
} gs_ui_live_status_t;

#define GS_UI_HINT_TTL_MS 300U
typedef struct {
    uint32_t last_terminal_frame_id, seen_terminal, valid;
    gs_static_result_t qualified;
} gs_ui_hint_cache_t;

void gs_ui_hint_update(gs_ui_hint_cache_t *cache,
    const gs_static_result_t *snapshot, uint32_t now_ms,
    uint32_t control_enabled, gs_ui_live_status_t *live);

typedef struct {
    uint16_t x, y, width, height;
} gs_ui_render_region_t;

/* Full-screen Chinese reader. Snapshot is owned by GUI; no HAL reads. */
gs_ui_render_status_t gs_ui_render_dashboard_rgb565(const gs_ui_t *ui,
    const gs_ui_live_status_t *status, uint16_t *pixels, size_t capacity,
    uint16_t width, uint16_t height, size_t stride,
    const gs_ui_render_theme_t *theme);

/* Redraw only the supplied regions by running the same dashboard composition
 * with clipped writes. The target buffer must already contain a complete frame
 * produced for the same UI generation and critical layout state. */
gs_ui_render_status_t gs_ui_render_dashboard_regions_rgb565(const gs_ui_t *ui,
    const gs_ui_live_status_t *status, uint16_t *pixels, size_t capacity,
    uint16_t width, uint16_t height, size_t stride,
    const gs_ui_render_theme_t *theme,
    const gs_ui_render_region_t *regions, size_t region_count);

/* 将完整 RGB565 帧绘制到调用者持有的内存；不依赖 HAL、RTOS、LVGL、堆或全局状态。
 * 显示 BSP 可先绘制到后缓冲，再通过 gs_display_swap 在垂直消隐时提交。 */
gs_ui_render_status_t gs_ui_render_rgb565(
    const gs_ui_t *ui,
    uint16_t *pixels,
    size_t pixel_capacity,
    uint16_t width,
    uint16_t height,
    size_t stride_pixels,
    const gs_ui_render_theme_t *theme);

/* 可选相机缩略图叠加；在 gs_ui_render_rgb565 之后、预览租约有效期间调用，
 * 完成后将预览 ticket 归还 CameraTask。 */
gs_ui_render_status_t gs_ui_render_preview_rgb565(
    uint16_t *pixels,
    size_t pixel_capacity,
    uint16_t width,
    uint16_t height,
    size_t stride_pixels,
    const gs_preview_frame_t *preview);

#ifdef __cplusplus
}
#endif
#endif
