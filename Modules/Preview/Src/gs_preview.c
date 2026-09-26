/* 预览双槽：将独立的 AI 输入复制缩小后交给 GUI，不保留相机原图。
 * 槽在 publish 后保持占用，匹配 ticket 的 release 才能使其再次可用。 */
#include "gs_preview.h"

#include <string.h>

static void gs_preview_commit(gs_preview_pool_t *pool, gs_preview_slot_t *slot,
    uint32_t index, uint32_t frame_id, uint32_t capture_ms, gs_preview_frame_t *frame)
{
    slot->token = pool->next_token++;
    slot->in_use = true;
    frame->ticket.token = slot->token;
    frame->ticket.slot = (uint8_t)index;
    frame->pixels = slot->pixels;
    frame->bytes = GS_PREVIEW_BYTES;
    frame->width = GS_PREVIEW_WIDTH;
    frame->height = GS_PREVIEW_HEIGHT;
    frame->frame_id = frame_id;
    frame->capture_ms = capture_ms;
}

static uint32_t gs_preview_y(uint16_t pixel)
{
    uint32_t r5 = (pixel >> 11U) & 31U, g6 = (pixel >> 5U) & 63U, b5 = pixel & 31U;
    uint32_t r8 = (r5 << 3U) | (r5 >> 2U), g8 = (g6 << 2U) | (g6 >> 4U), b8 = (b5 << 3U) | (b5 >> 2U);
    return (77U * r8 + 150U * g8 + 29U * b8 + 128U) >> 8U;
}

gs_preview_result_t gs_preview_publish_rgb565(gs_preview_pool_t *pool,
    const gs_rgb565_frame_t *source, uint32_t frame_id,
    uint32_t capture_ms, gs_preview_frame_t *frame)
{
    size_t required;
    gs_preview_slot_t *slot = NULL;
    uint32_t index, row, column;
    if (pool == NULL || !pool->initialized || source == NULL || source->data == NULL ||
        frame == NULL || frame_id == 0U || source->width != GS_CAMERA_WIDTH ||
        source->height != GS_CAMERA_HEIGHT || source->stride_bytes < GS_CAMERA_WIDTH * 2U ||
        (source->byte_order != GS_RGB565_MSB_FIRST && source->byte_order != GS_RGB565_LSB_FIRST) ||
        source->stride_bytes > (SIZE_MAX - GS_CAMERA_WIDTH * 2U) / (GS_CAMERA_HEIGHT - 1U)) {
        return GS_PREVIEW_INVALID;
    }
    required = source->stride_bytes * (GS_CAMERA_HEIGHT - 1U) + GS_CAMERA_WIDTH * 2U;
    if (source->data_size < required || (uintptr_t)source->data > UINTPTR_MAX - required) {
        return GS_PREVIEW_INVALID;
    }
    for (index = 0U; index < GS_PREVIEW_SLOTS; ++index) {
        if (!pool->slots[index].in_use) { slot = &pool->slots[index]; break; }
    }
    if (slot == NULL) { return GS_PREVIEW_BUSY; }
    if (pool->next_token == 0U) { return GS_PREVIEW_TOKEN_EXHAUSTED; }
    if ((uintptr_t)source->data < (uintptr_t)slot->pixels + GS_PREVIEW_BYTES &&
        (uintptr_t)slot->pixels < (uintptr_t)source->data + required) {
        return GS_PREVIEW_INVALID;
    }
    for (row = 0U; row < GS_PREVIEW_HEIGHT; ++row) {
        const uint8_t *top = source->data + (GS_ROI_Y + row * 2U) * source->stride_bytes + GS_ROI_X * 2U;
        const uint8_t *bottom = top + source->stride_bytes;
        uint8_t *out = slot->pixels + row * GS_PREVIEW_WIDTH;
        for (column = 0U; column < GS_PREVIEW_WIDTH; ++column) {
            uint16_t a = (uint16_t)(((uint16_t)top[0] << 8U) | top[1]);
            uint16_t b = (uint16_t)(((uint16_t)top[2] << 8U) | top[3]);
            uint16_t c = (uint16_t)(((uint16_t)bottom[0] << 8U) | bottom[1]);
            uint16_t d = (uint16_t)(((uint16_t)bottom[2] << 8U) | bottom[3]);
            if (source->byte_order == GS_RGB565_LSB_FIRST) {
                a = (uint16_t)((a << 8U) | (a >> 8U)); b = (uint16_t)((b << 8U) | (b >> 8U));
                c = (uint16_t)((c << 8U) | (c >> 8U)); d = (uint16_t)((d << 8U) | (d >> 8U));
            }
            out[column] = (uint8_t)((gs_preview_y(a) + gs_preview_y(b) + gs_preview_y(c) + gs_preview_y(d) + 2U) / 4U);
            top += 4U; bottom += 4U;
        }
    }
    gs_preview_commit(pool, slot, index, frame_id, capture_ms, frame);
    return GS_PREVIEW_OK;
}

static bool gs_preview_regions_valid(void *buffer0, void *buffer1)
{
    uintptr_t buffer0_addr = (uintptr_t)buffer0;
    uintptr_t buffer1_addr = (uintptr_t)buffer1;
    if (buffer0 == NULL || buffer1 == NULL || (buffer0_addr & 3U) != 0U ||
        (buffer1_addr & 3U) != 0U || GS_PREVIEW_BYTES > UINTPTR_MAX - buffer0_addr ||
        GS_PREVIEW_BYTES > UINTPTR_MAX - buffer1_addr) {
        return false;
    }
    return buffer0_addr + GS_PREVIEW_BYTES <= buffer1_addr || buffer1_addr + GS_PREVIEW_BYTES <= buffer0_addr;
}

gs_preview_result_t gs_preview_pool_init(gs_preview_pool_t *pool,
    void *buffer0, size_t capacity0, void *buffer1, size_t capacity1)
{
    if (pool == NULL || capacity0 < GS_PREVIEW_BYTES ||
        capacity1 < GS_PREVIEW_BYTES ||
        !gs_preview_regions_valid(buffer0, buffer1)) {
        return GS_PREVIEW_INVALID;
    }
    memset(pool, 0, sizeof(*pool));
    pool->slots[0].pixels = (uint8_t *)buffer0;
    pool->slots[1].pixels = (uint8_t *)buffer1;
    pool->next_token = 1U;
    pool->initialized = true;
    return GS_PREVIEW_OK;
}

gs_preview_result_t gs_preview_publish(gs_preview_pool_t *pool,
    const int8_t *source, size_t source_count, uint32_t frame_id,
    uint32_t capture_ms, gs_preview_frame_t *frame)
{
    gs_preview_slot_t *slot = NULL;
    uint32_t index;
    uint32_t row;
    if (pool == NULL || !pool->initialized || source == NULL ||
        source_count != GS_PREVIEW_SOURCE_BYTES || frame == NULL ||
        frame_id == 0U) {
        return GS_PREVIEW_INVALID;
    }
    for (index = 0U; index < GS_PREVIEW_SLOTS; ++index) {
        if (!pool->slots[index].in_use) {
            slot = &pool->slots[index];
            break;
        }
    }
    if (slot == NULL) {
        return GS_PREVIEW_BUSY;
    }
    if (pool->next_token == 0U) {
        return GS_PREVIEW_TOKEN_EXHAUSTED;
    }
    for (row = 0U; row < GS_PREVIEW_HEIGHT; ++row) {
        uint32_t column;
        for (column = 0U; column < GS_PREVIEW_WIDTH; ++column) {
            size_t at = row * GS_PREVIEW_SOURCE_WIDTH + column;
            slot->pixels[at] = (uint8_t)((int32_t)source[at] + 128);
        }
    }
    gs_preview_commit(pool, slot, index, frame_id, capture_ms, frame);
    return GS_PREVIEW_OK;
}

gs_preview_result_t gs_preview_release(gs_preview_pool_t *pool,
    gs_preview_ticket_t ticket)
{
    gs_preview_slot_t *slot;
    if (pool == NULL || !pool->initialized || ticket.slot >= GS_PREVIEW_SLOTS ||
        ticket.token == 0U) {
        return GS_PREVIEW_INVALID;
    }
    slot = &pool->slots[ticket.slot];
    if (!slot->in_use || slot->token != ticket.token) {
        return GS_PREVIEW_STALE;
    }
    slot->in_use = false;
    return GS_PREVIEW_OK;
}
