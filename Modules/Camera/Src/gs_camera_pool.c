/* 相机双缓冲状态管理：FREE → CAPTURING → READY → PROCESSING → FREE。
 * ticket 的槽号与 token 共同识别一次租约，防止迟到事件操作已复用的槽。
 * 本模块只维护元数据，硬件停止、DMA 完成确认和跨任务串行化由 BSP/CameraTask 负责。 */
#include "gs_camera_pool.h"

#include <string.h>

#define GS_CAMERA_ERROR_LENGTH (1u << 31)
#define GS_CAMERA_EVENTS_ALL (GS_CAMERA_EVENT_FRAME_END | GS_CAMERA_EVENT_DMA_DONE)

static bool gs_camera_regions_valid(void *buffer0, void *buffer1, size_t bytes)
{
    uintptr_t buffer0_addr = (uintptr_t)buffer0;
    uintptr_t buffer1_addr = (uintptr_t)buffer1;
    if ((buffer0 == NULL) || (buffer1 == NULL) || (bytes == 0u) ||
        ((bytes & 3u) != 0u) || ((buffer0_addr & 3u) != 0u) || ((buffer1_addr & 3u) != 0u) ||
        (bytes > UINTPTR_MAX - buffer0_addr) || (bytes > UINTPTR_MAX - buffer1_addr)) {
        return false;
    }
    return ((buffer0_addr + bytes <= buffer1_addr) || (buffer1_addr + bytes <= buffer0_addr));
}

static gs_camera_slot_t *gs_camera_find(gs_camera_pool_t *pool,
                                      gs_camera_ticket_t ticket,
                                      gs_camera_state_t state)
{
    gs_camera_slot_t *slot;
    if ((pool == NULL) || !pool->initialized ||
        (ticket.slot >= GS_CAMERA_SLOTS) || (ticket.token == 0u)) {
        return NULL;
    }
    slot = &pool->slots[ticket.slot];
    if ((slot->state != state) || (slot->token != ticket.token)) {
        return NULL;
    }
    return slot;
}

gs_camera_result_t gs_camera_pool_init(gs_camera_pool_t *pool,
                                      void *buffer0, size_t capacity0,
                                      void *buffer1, size_t capacity1,
                                      size_t frame_bytes)
{
    if ((pool == NULL) || (capacity0 < frame_bytes) ||
        (capacity1 < frame_bytes) ||
        !gs_camera_regions_valid(buffer0, buffer1, frame_bytes)) {
        return GS_CAMERA_INVALID;
    }
    memset(pool, 0, sizeof(*pool));
    pool->slots[0].data = (uint8_t *)buffer0;
    pool->slots[1].data = (uint8_t *)buffer1;
    pool->frame_bytes = frame_bytes;
    pool->next_token = 1u;
    pool->initialized = true;
    return GS_CAMERA_OK;
}

gs_camera_result_t gs_camera_begin(gs_camera_pool_t *pool,
                                  gs_camera_ticket_t *ticket, void **buffer)
{
    size_t i;
    gs_camera_slot_t *slot = NULL;
    uint8_t index = 0u;
    if ((pool == NULL) || !pool->initialized ||
        (ticket == NULL) || (buffer == NULL)) {
        return GS_CAMERA_INVALID;
    }
    for (i = 0u; i < GS_CAMERA_SLOTS; ++i) {
        if (pool->slots[i].state == GS_CAMERA_CAPTURING) {
            return GS_CAMERA_BUSY;
        }
        if ((slot == NULL) && (pool->slots[i].state == GS_CAMERA_FREE)) {
            slot = &pool->slots[i];
            index = (uint8_t)i;
        }
    }
    if (slot == NULL) {
        return GS_CAMERA_BUSY;
    }
    if (pool->next_token == 0u) {
        return GS_CAMERA_TOKEN_EXHAUSTED;
    }
    slot->state = GS_CAMERA_CAPTURING;
    slot->token = pool->next_token++;
    slot->events = 0u;
    slot->errors = 0u;
    slot->received_bytes = 0u;
    slot->timestamp_ms = 0u;
    ticket->slot = index;
    ticket->token = slot->token;
    *buffer = slot->data;
    return GS_CAMERA_OK;
}

gs_camera_result_t gs_camera_report(gs_camera_pool_t *pool,
                                   gs_camera_ticket_t ticket,
                                   uint32_t events, size_t received_bytes,
                                   uint32_t error_flags)
{
    gs_camera_slot_t *slot = gs_camera_find(pool, ticket, GS_CAMERA_CAPTURING);
    if ((events & ~GS_CAMERA_EVENTS_ALL) != 0u) {
        return GS_CAMERA_INVALID;
    }
    if (slot == NULL) {
        return GS_CAMERA_STALE;
    }
    if ((events & GS_CAMERA_EVENT_DMA_DONE) != 0u) {
        if (((slot->events & GS_CAMERA_EVENT_DMA_DONE) != 0u) &&
            (slot->received_bytes != received_bytes)) {
            slot->errors |= GS_CAMERA_ERROR_LENGTH;
        }
        slot->received_bytes = received_bytes;
        if (received_bytes != pool->frame_bytes) {
            slot->errors |= GS_CAMERA_ERROR_LENGTH;
        }
    }
    slot->events |= events;
    slot->errors |= error_flags;
    return GS_CAMERA_OK;
}

gs_camera_result_t gs_camera_finish_quiesced(gs_camera_pool_t *pool,
                                            gs_camera_ticket_t ticket,
                                            uint32_t timestamp_ms,
                                            uint32_t final_error_flags)
{
    gs_camera_slot_t *slot = gs_camera_find(pool, ticket, GS_CAMERA_CAPTURING);
    if (slot == NULL) {
        return GS_CAMERA_STALE;
    }
    slot->errors |= final_error_flags;
    if (slot->errors != 0u) {
        slot->state = GS_CAMERA_FREE;
        return GS_CAMERA_ERROR;
    }
    if ((slot->events != GS_CAMERA_EVENTS_ALL) ||
        (slot->received_bytes != pool->frame_bytes)) {
        slot->state = GS_CAMERA_FREE;
        return GS_CAMERA_INCOMPLETE;
    }
    slot->timestamp_ms = timestamp_ms;
    slot->state = GS_CAMERA_READY;
    return GS_CAMERA_OK;
}

gs_camera_result_t gs_camera_abort_quiesced(gs_camera_pool_t *pool,
                                           gs_camera_ticket_t ticket)
{
    gs_camera_slot_t *slot = gs_camera_find(pool, ticket, GS_CAMERA_CAPTURING);
    if (slot == NULL) {
        return GS_CAMERA_STALE;
    }
    slot->state = GS_CAMERA_FREE;
    return GS_CAMERA_OK;
}

gs_camera_result_t gs_camera_acquire_latest(gs_camera_pool_t *pool,
                                           gs_camera_frame_t *frame)
{
    size_t i;
    gs_camera_slot_t *latest = NULL;
    uint8_t index = 0u;
    if ((pool == NULL) || !pool->initialized || (frame == NULL)) {
        return GS_CAMERA_INVALID;
    }
    for (i = 0u; i < GS_CAMERA_SLOTS; ++i) {
        gs_camera_slot_t *candidate = &pool->slots[i];
        if ((candidate->state == GS_CAMERA_READY) &&
            ((latest == NULL) || (candidate->token > latest->token))) {
            latest = candidate;
            index = (uint8_t)i;
        }
    }
    if (latest == NULL) {
        return GS_CAMERA_BUSY;
    }
    for (i = 0u; i < GS_CAMERA_SLOTS; ++i) {
        if ((&pool->slots[i] != latest) &&
            (pool->slots[i].state == GS_CAMERA_READY)) {
            pool->slots[i].state = GS_CAMERA_FREE;
        }
    }
    latest->state = GS_CAMERA_PROCESSING;
    frame->ticket.slot = index;
    frame->ticket.token = latest->token;
    frame->data = latest->data;
    frame->bytes = pool->frame_bytes;
    frame->frame_id = latest->token;
    frame->timestamp_ms = latest->timestamp_ms;
    return GS_CAMERA_OK;
}

gs_camera_result_t gs_camera_release(gs_camera_pool_t *pool,
                                    gs_camera_ticket_t ticket)
{
    gs_camera_slot_t *slot = gs_camera_find(pool, ticket, GS_CAMERA_PROCESSING);
    if (slot == NULL) {
        return GS_CAMERA_STALE;
    }
    slot->state = GS_CAMERA_FREE;
    return GS_CAMERA_OK;
}
