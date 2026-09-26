/* 显示交换状态：IDLE → COPYING → DRAWING → PENDING → IDLE。
 * 提交后冻结后缓冲，只有实际 LTDC 重载确认才能交换前后缓冲。 */
#include "gs_display_swap.h"

#include <string.h>

static bool gs_display_matches(const gs_display_swap_t *swap, uint32_t token,
                               gs_display_state_t state)
{
    return (swap != NULL) && swap->initialized && (token != 0u) &&
           (swap->active_token == token) && (swap->state == state);
}

static bool gs_display_refresh_critical_changed(
    const gs_display_refresh_input_t *before,
    const gs_display_refresh_input_t *after)
{
    return before->preview_visible != after->preview_visible ||
           before->healthy != after->healthy ||
           before->control_enabled != after->control_enabled ||
           before->camera_fault != after->camera_fault ||
           before->display_stalled != after->display_stalled ||
           before->inference_fault != after->inference_fault ||
           before->result_stale != after->result_stale ||
           before->display_errors != after->display_errors ||
           before->inference_errors != after->inference_errors ||
           before->inference_timeouts != after->inference_timeouts ||
           before->content_checked != after->content_checked ||
           before->content_errors != after->content_errors;
}

uint32_t gs_display_refresh_observe(gs_display_refresh_t *refresh,
                                   const gs_display_refresh_input_t *input)
{
    uint32_t reasons = GS_DISPLAY_REFRESH_NONE;
    if (refresh == NULL || input == NULL) {
        return GS_DISPLAY_REFRESH_NONE;
    }
    if (!refresh->initialized) {
        return GS_DISPLAY_REFRESH_INITIAL;
    }
    if (input->generation != refresh->committed.generation) {
        reasons |= GS_DISPLAY_REFRESH_GENERATION;
    }
    if (input->preview_visible &&
        (input->preview_id != refresh->committed.preview_id ||
         input->preview_capture_ms != refresh->committed.preview_capture_ms)) {
        reasons |= GS_DISPLAY_REFRESH_PREVIEW;
    }
    if (gs_display_refresh_critical_changed(&refresh->committed, input)) {
        reasons |= GS_DISPLAY_REFRESH_CRITICAL;
    }
    if (!input->ordinary_changed) {
        refresh->ordinary_pending = false;
    } else {
        if (!refresh->ordinary_pending) {
            refresh->ordinary_pending = true;
            refresh->ordinary_since_ms = input->now_ms;
        }
        if (input->now_ms - refresh->ordinary_since_ms >=
            GS_DISPLAY_REFRESH_GRACE_MS) {
            reasons |= GS_DISPLAY_REFRESH_GRACE;
        }
    }
    return reasons;
}

void gs_display_refresh_commit(gs_display_refresh_t *refresh,
                               const gs_display_refresh_input_t *input)
{
    if (refresh == NULL || input == NULL) {
        return;
    }
    refresh->committed = *input;
    refresh->committed.ordinary_changed = false;
    refresh->initialized = true;
    refresh->ordinary_pending = false;
}

bool gs_display_swap_init(gs_display_swap_t *swap,
                          void *buffer0, size_t capacity0,
                          void *buffer1, size_t capacity1, size_t frame_bytes)
{
    uintptr_t buffer0_addr = (uintptr_t)buffer0;
    uintptr_t buffer1_addr = (uintptr_t)buffer1;
    if ((swap == NULL) || (buffer0 == NULL) || (buffer1 == NULL) ||
        (frame_bytes == 0u) || (capacity0 < frame_bytes) ||
        (capacity1 < frame_bytes) || ((buffer0_addr & 3u) != 0u) || ((buffer1_addr & 3u) != 0u) ||
        (frame_bytes > UINTPTR_MAX - buffer0_addr) || (frame_bytes > UINTPTR_MAX - buffer1_addr)) {
        return false;
    }
    if (!((buffer0_addr + frame_bytes <= buffer1_addr) || (buffer1_addr + frame_bytes <= buffer0_addr))) {
        return false;
    }
    memset(swap, 0, sizeof(*swap));
    swap->buffers[0] = (uint8_t *)buffer0;
    swap->buffers[1] = (uint8_t *)buffer1;
    swap->frame_bytes = frame_bytes;
    swap->next_token = 1u;
    swap->initialized = true;
    return true;
}

bool gs_display_begin(gs_display_swap_t *swap,
                      gs_display_composition_t *composition)
{
    if ((swap == NULL) || !swap->initialized || (composition == NULL) ||
        (swap->state != GS_DISPLAY_IDLE) || (swap->next_token == 0u)) {
        return false;
    }
    swap->active_token = swap->next_token++;
    swap->state = GS_DISPLAY_COPYING;
    composition->token = swap->active_token;
    composition->front = swap->buffers[swap->front_index];
    composition->back = swap->buffers[1u - swap->front_index];
    composition->bytes = swap->frame_bytes;
    return true;
}

bool gs_display_copy_complete(gs_display_swap_t *swap, uint32_t token)
{
    if (!gs_display_matches(swap, token, GS_DISPLAY_COPYING)) {
        return false;
    }
    swap->state = GS_DISPLAY_DRAWING;
    return true;
}

bool gs_display_submit(gs_display_swap_t *swap, uint32_t token,
                       const void **pending_front)
{
    if ((pending_front == NULL) ||
        !gs_display_matches(swap, token, GS_DISPLAY_DRAWING)) {
        return false;
    }
    swap->state = GS_DISPLAY_PENDING;
    *pending_front = swap->buffers[1u - swap->front_index];
    return true;
}

bool gs_display_submit_abort_unarmed(gs_display_swap_t *swap, uint32_t token,
                                     const void *pending_front)
{
    if (!gs_display_matches(swap, token, GS_DISPLAY_PENDING) ||
        pending_front != swap->buffers[1u - swap->front_index]) {
        return false;
    }
    swap->state = GS_DISPLAY_IDLE;
    return true;
}

bool gs_display_reload_confirm(gs_display_swap_t *swap, uint32_t token,
                               const void *active_front)
{
    if (!gs_display_matches(swap, token, GS_DISPLAY_PENDING) ||
        (active_front != swap->buffers[1u - swap->front_index])) {
        return false;
    }
    swap->front_index = (uint8_t)(1u - swap->front_index);
    swap->state = GS_DISPLAY_IDLE;
    return true;
}

bool gs_display_cancel_quiesced(gs_display_swap_t *swap, uint32_t token)
{
    if (!gs_display_matches(swap, token, GS_DISPLAY_COPYING) &&
        !gs_display_matches(swap, token, GS_DISPLAY_DRAWING)) {
        return false;
    }
    swap->state = GS_DISPLAY_IDLE;
    return true;
}
