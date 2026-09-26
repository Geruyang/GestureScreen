#include "gs_camera_pool.h"
#include "gs_display_swap.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

/* 使用小型对齐主机缓冲验证元数据，不代表目标板的实际帧缓冲。 */
static uint32_t camera_memory[2][16];
static uint32_t display_memory[2][16];

static void init_camera(gs_camera_pool_t *pool)
{
    assert(gs_camera_pool_init(pool, camera_memory[0], sizeof(camera_memory[0]),
                               camera_memory[1], sizeof(camera_memory[1]),
                               sizeof(camera_memory[0])) == GS_CAMERA_OK);
}

static gs_camera_ticket_t begin_camera(gs_camera_pool_t *pool)
{
    gs_camera_ticket_t ticket;
    void *buffer = NULL;
    assert(gs_camera_begin(pool, &ticket, &buffer) == GS_CAMERA_OK);
    assert(buffer == camera_memory[ticket.slot]);
    return ticket;
}

static void complete_camera(gs_camera_pool_t *pool, gs_camera_ticket_t ticket,
                            uint32_t timestamp)
{
    assert(gs_camera_report(pool, ticket, GS_CAMERA_EVENT_FRAME_END, 0u, 0u)
           == GS_CAMERA_OK);
    assert(gs_camera_report(pool, ticket, GS_CAMERA_EVENT_DMA_DONE,
                            sizeof(camera_memory[0]), 0u) == GS_CAMERA_OK);
    assert(pool->slots[ticket.slot].state == GS_CAMERA_CAPTURING);
    assert(gs_camera_finish_quiesced(pool, ticket, timestamp, 0u) == GS_CAMERA_OK);
}

static void test_camera_complete_and_late_events(void)
{
    gs_camera_pool_t pool;
    gs_camera_ticket_t a, b;
    gs_camera_frame_t frame;
    void *buffer;
    init_camera(&pool);
    a = begin_camera(&pool);
    assert(gs_camera_begin(&pool, &b, &buffer) == GS_CAMERA_BUSY);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE,
                            sizeof(camera_memory[0]), 0u) == GS_CAMERA_OK);
    assert(gs_camera_acquire_latest(&pool, &frame) == GS_CAMERA_BUSY);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_FRAME_END, 0u, 0u)
           == GS_CAMERA_OK);
    assert(gs_camera_acquire_latest(&pool, &frame) == GS_CAMERA_BUSY);
    assert(gs_camera_finish_quiesced(&pool, a, 123u, 0u) == GS_CAMERA_OK);
    assert(gs_camera_acquire_latest(&pool, &frame) == GS_CAMERA_OK);
    assert(frame.frame_id == a.token && frame.timestamp_ms == 123u);
    assert(frame.data == (uint8_t *)camera_memory[a.slot]);
    assert(gs_camera_report(&pool, a, 0u, 0u, 1u) == GS_CAMERA_STALE);
    assert(gs_camera_release(&pool, a) == GS_CAMERA_OK);
    b = begin_camera(&pool);
    assert(b.slot == a.slot && b.token != a.token);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE, 64u, 0u)
           == GS_CAMERA_STALE);
    assert(gs_camera_abort_quiesced(&pool, a) == GS_CAMERA_STALE);
    assert(gs_camera_release(&pool, a) == GS_CAMERA_STALE);
    assert(pool.slots[b.slot].state == GS_CAMERA_CAPTURING);
    assert(gs_camera_abort_quiesced(&pool, b) == GS_CAMERA_OK);
}

static void test_camera_incomplete_and_error(void)
{
    gs_camera_pool_t pool;
    gs_camera_ticket_t a;
    gs_camera_frame_t frame;
    init_camera(&pool);
    a = begin_camera(&pool);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_FRAME_END, 0u, 0u)
           == GS_CAMERA_OK);
    assert(gs_camera_finish_quiesced(&pool, a, 1u, 0u) == GS_CAMERA_INCOMPLETE);
    assert(gs_camera_acquire_latest(&pool, &frame) == GS_CAMERA_BUSY);
    a = begin_camera(&pool);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE, 64u, 0u)
           == GS_CAMERA_OK);
    assert(gs_camera_finish_quiesced(&pool, a, 2u, 0u) == GS_CAMERA_INCOMPLETE);
    a = begin_camera(&pool);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE |
                            GS_CAMERA_EVENT_FRAME_END, 60u, 0u) == GS_CAMERA_OK);
    /* 后续正确的长度报告不能清除先前不完整传输留下的错误记录。 */
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE, 64u, 0u)
           == GS_CAMERA_OK);
    assert(gs_camera_finish_quiesced(&pool, a, 3u, 0u) == GS_CAMERA_ERROR);
    a = begin_camera(&pool);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE |
                            GS_CAMERA_EVENT_FRAME_END, 64u, 0u) == GS_CAMERA_OK);
    assert(gs_camera_finish_quiesced(&pool, a, 4u, 0x20u) == GS_CAMERA_ERROR);
    assert(gs_camera_acquire_latest(&pool, &frame) == GS_CAMERA_BUSY);
    a = begin_camera(&pool);
    assert(gs_camera_report(&pool, a, 0u, 0u, 0x10u) == GS_CAMERA_OK);
    assert(gs_camera_report(&pool, a, GS_CAMERA_EVENT_DMA_DONE |
                            GS_CAMERA_EVENT_FRAME_END, 64u, 0u) == GS_CAMERA_OK);
    assert(gs_camera_finish_quiesced(&pool, a, 5u, 0u) == GS_CAMERA_ERROR);
}

static void test_camera_slow_consumer_and_latest(void)
{
    gs_camera_pool_t pool;
    gs_camera_ticket_t a, b, c;
    gs_camera_frame_t first, second;
    void *buffer;
    init_camera(&pool);
    a = begin_camera(&pool);
    complete_camera(&pool, a, 1u);
    b = begin_camera(&pool);
    complete_camera(&pool, b, 2u);
    assert(gs_camera_begin(&pool, &c, &buffer) == GS_CAMERA_BUSY);
    assert(gs_camera_acquire_latest(&pool, &first) == GS_CAMERA_OK);
    assert(first.frame_id == b.token);
    assert(pool.slots[a.slot].state == GS_CAMERA_FREE);
    assert(pool.slots[b.slot].state == GS_CAMERA_PROCESSING);
    c = begin_camera(&pool);
    assert(c.slot == a.slot);
    complete_camera(&pool, c, 3u);
    assert(gs_camera_acquire_latest(&pool, &second) == GS_CAMERA_OK);
    assert(second.frame_id == c.token);
    assert(pool.slots[b.slot].state == GS_CAMERA_PROCESSING);
    assert(gs_camera_begin(&pool, &a, &buffer) == GS_CAMERA_BUSY);
    assert(gs_camera_release(&pool, first.ticket) == GS_CAMERA_OK);
    assert(gs_camera_release(&pool, second.ticket) == GS_CAMERA_OK);
    assert(gs_camera_release(&pool, second.ticket) == GS_CAMERA_STALE);
}

static void test_camera_validation_and_exhaustion(void)
{
    gs_camera_pool_t pool;
    gs_camera_ticket_t ticket;
    void *buffer;
    assert(gs_camera_pool_init(&pool, camera_memory[0], 64u,
                               camera_memory[0], 64u, 64u) == GS_CAMERA_INVALID);
    assert(gs_camera_pool_init(&pool, camera_memory[0], 63u,
                               camera_memory[1], 64u, 64u) == GS_CAMERA_INVALID);
    assert(gs_camera_pool_init(&pool, (uint8_t *)camera_memory[0] + 1u, 63u,
                               camera_memory[1], 64u, 60u) == GS_CAMERA_INVALID);
    assert(gs_camera_pool_init(&pool, camera_memory[0], 64u,
                               camera_memory[1], 64u, 63u) == GS_CAMERA_INVALID);
    init_camera(&pool);
    pool.next_token = UINT32_MAX; /* 白盒设置计数器，模拟 token 耗尽边界。 */
    ticket = begin_camera(&pool);
    assert(ticket.token == UINT32_MAX);
    assert(gs_camera_abort_quiesced(&pool, ticket) == GS_CAMERA_OK);
    assert(gs_camera_begin(&pool, &ticket, &buffer) == GS_CAMERA_TOKEN_EXHAUSTED);
}

static void init_display(gs_display_swap_t *swap)
{
    assert(gs_display_swap_init(swap, display_memory[0], sizeof(display_memory[0]),
                                display_memory[1], sizeof(display_memory[1]),
                                sizeof(display_memory[0])));
}

static void test_display_exchange_and_unchanged_pixels(void)
{
    gs_display_swap_t swap;
    gs_display_composition_t first, second, blocked;
    const void *pending;
    memset(display_memory[0], 0x11, sizeof(display_memory[0]));
    memset(display_memory[1], 0xee, sizeof(display_memory[1]));
    init_display(&swap);
    assert(gs_display_begin(&swap, &first));
    assert(!gs_display_begin(&swap, &blocked));
    assert(!gs_display_submit(&swap, first.token, &pending));
    memcpy(first.back, first.front, first.bytes);
    assert(gs_display_copy_complete(&swap, first.token));
    first.back[0] = 0x22;
    assert(gs_display_submit(&swap, first.token, &pending));
    assert(pending == first.back);
    assert(!gs_display_cancel_quiesced(&swap, first.token));
    assert(!gs_display_submit_abort_unarmed(&swap, first.token + 1U, pending));
    assert(!gs_display_submit_abort_unarmed(&swap, first.token, first.front));
    assert(!gs_display_begin(&swap, &blocked));
    assert(!gs_display_reload_confirm(&swap, first.token, first.front));
    assert(!gs_display_reload_confirm(&swap, first.token + 1u, pending));
    assert(swap.front_index == 0u);
    assert(gs_display_reload_confirm(&swap, first.token, pending));
    assert(swap.front_index == 1u);
    assert(!gs_display_reload_confirm(&swap, first.token, pending));
    assert(gs_display_begin(&swap, &second));
    assert(second.back == first.front && second.front == first.back);
    assert(!gs_display_copy_complete(&swap, first.token));
    memcpy(second.back, second.front, second.bytes);
    assert(gs_display_copy_complete(&swap, second.token));
    second.back[1] = 0x33;
    assert(gs_display_submit(&swap, second.token, &pending));
    assert(gs_display_reload_confirm(&swap, second.token, pending));
    assert(((const uint8_t *)pending)[0] == 0x22);
    assert(((const uint8_t *)pending)[1] == 0x33);
    assert(((const uint8_t *)pending)[63] == 0x11);
}

static void test_display_cancel_validation_exhaustion(void)
{
    gs_display_swap_t swap;
    gs_display_composition_t frame;
    assert(!gs_display_swap_init(&swap, display_memory[0], 64u,
                                 display_memory[0], 64u, 64u));
    assert(!gs_display_swap_init(&swap, display_memory[0], 63u,
                                 display_memory[1], 64u, 64u));
    assert(!gs_display_swap_init(&swap, (uint8_t *)display_memory[0] + 1u, 63u,
                                 display_memory[1], 64u, 60u));
    init_display(&swap);
    assert(gs_display_begin(&swap, &frame));
    assert(gs_display_cancel_quiesced(&swap, frame.token));
    assert(!gs_display_cancel_quiesced(&swap, frame.token));
    assert(gs_display_begin(&swap, &frame));
    assert(gs_display_copy_complete(&swap, frame.token));
    assert(gs_display_cancel_quiesced(&swap, frame.token));
    swap.next_token = UINT32_MAX;
    assert(gs_display_begin(&swap, &frame));
    assert(frame.token == UINT32_MAX);
    assert(gs_display_cancel_quiesced(&swap, frame.token));
    assert(!gs_display_begin(&swap, &frame));
}

static void test_display_unarmed_submit_abort(void)
{
    gs_display_swap_t swap;
    gs_display_composition_t frame, retry;
    const void *pending;
    init_display(&swap);
    assert(gs_display_begin(&swap, &frame));
    assert(gs_display_copy_complete(&swap, frame.token));
    assert(gs_display_submit(&swap, frame.token, &pending));
    assert(gs_display_submit_abort_unarmed(&swap, frame.token, pending));
    assert(swap.state == GS_DISPLAY_IDLE && swap.front_index == 0U);
    assert(!gs_display_submit_abort_unarmed(&swap, frame.token, pending));
    assert(gs_display_begin(&swap, &retry));
    assert(retry.back == frame.back && retry.front == frame.front);
    assert(gs_display_cancel_quiesced(&swap, retry.token));
}

static gs_display_refresh_input_t refresh_sample(uint32_t now)
{
    gs_display_refresh_input_t input;
    memset(&input, 0, sizeof input);
    input.now_ms = now;
    input.generation = 1U;
    input.preview_visible = true;
    input.preview_id = 10U;
    input.preview_capture_ms = now - 20U;
    input.healthy = true;
    input.control_enabled = true;
    input.content_checked = 1U;
    return input;
}

static void refresh_expect_critical(gs_display_refresh_t *refresh,
                                    gs_display_refresh_input_t *input)
{
    assert((gs_display_refresh_observe(refresh, input) &
            GS_DISPLAY_REFRESH_CRITICAL) != 0U);
    gs_display_refresh_commit(refresh, input);
    assert(gs_display_refresh_observe(refresh, input) == GS_DISPLAY_REFRESH_NONE);
}

static void test_display_refresh_preview_cadence_and_busy_retention(void)
{
    gs_display_refresh_t refresh;
    gs_display_refresh_input_t input = refresh_sample(100U);
    memset(&refresh, 0, sizeof refresh);
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_INITIAL);
    /* A failed/BUSY submission does not consume the initial dirty reason. */
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_INITIAL);
    gs_display_refresh_commit(&refresh, &input);
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);

    input.now_ms = 120U;
    input.preview_id = 11U;
    input.preview_capture_ms = 110U;
    assert((gs_display_refresh_observe(&refresh, &input) &
            GS_DISPLAY_REFRESH_PREVIEW) != 0U);
    /* Simulate gs_display_begin/LTDC BUSY: the same preview stays dirty. */
    input.now_ms = 140U;
    assert((gs_display_refresh_observe(&refresh, &input) &
            GS_DISPLAY_REFRESH_PREVIEW) != 0U);
    gs_display_refresh_commit(&refresh, &input);
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);

    input.generation = 2U;
    assert((gs_display_refresh_observe(&refresh, &input) &
            GS_DISPLAY_REFRESH_GENERATION) != 0U);
    gs_display_refresh_commit(&refresh, &input);
}

static void test_display_refresh_critical_edges(void)
{
    gs_display_refresh_t refresh;
    gs_display_refresh_input_t input = refresh_sample(100U);
    memset(&refresh, 0, sizeof refresh);
    gs_display_refresh_commit(&refresh, &input);

    input.healthy = false; refresh_expect_critical(&refresh, &input);
    input.healthy = true; refresh_expect_critical(&refresh, &input);
    input.control_enabled = false; refresh_expect_critical(&refresh, &input);
    input.camera_fault = true; refresh_expect_critical(&refresh, &input);
    input.camera_fault = false; refresh_expect_critical(&refresh, &input);
    input.display_errors = 1U; refresh_expect_critical(&refresh, &input);
    input.display_stalled = true; refresh_expect_critical(&refresh, &input);
    input.inference_errors = 1U; refresh_expect_critical(&refresh, &input);
    input.inference_timeouts = 1U; refresh_expect_critical(&refresh, &input);
    input.inference_fault = true; refresh_expect_critical(&refresh, &input);
    input.inference_fault = false; refresh_expect_critical(&refresh, &input);
    input.content_checked = 2U; refresh_expect_critical(&refresh, &input);
    input.content_errors = 1U; refresh_expect_critical(&refresh, &input);
    input.result_stale = true; refresh_expect_critical(&refresh, &input);
    input.result_stale = false; refresh_expect_critical(&refresh, &input);
    input.preview_visible = false;
    input.preview_id = input.preview_capture_ms = 0U;
    refresh_expect_critical(&refresh, &input);
}

static void test_display_refresh_terminal_grace_and_wrap(void)
{
    gs_display_refresh_t refresh;
    gs_display_refresh_input_t input = refresh_sample(UINT32_MAX - 100U);
    memset(&refresh, 0, sizeof refresh);
    gs_display_refresh_commit(&refresh, &input);

    /* Last in-flight terminal changed but no newer preview arrived. */
    input.ordinary_changed = true;
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);
    input.now_ms = 148U; /* 249 ms after UINT32_MAX-100, across wrap. */
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);
    input.now_ms = 149U;
    assert((gs_display_refresh_observe(&refresh, &input) &
            GS_DISPLAY_REFRESH_GRACE) != 0U);
    /* BUSY retains the elapsed grace reason until a successful commit. */
    input.now_ms = 160U;
    assert((gs_display_refresh_observe(&refresh, &input) &
            GS_DISPLAY_REFRESH_GRACE) != 0U);
    gs_display_refresh_commit(&refresh, &input);
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);

    /* A transient ordinary value that returns to the displayed value is not
       repainted later by a stale pending timer. */
    input.ordinary_changed = true;
    input.now_ms = 200U;
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);
    input.ordinary_changed = false;
    input.now_ms = 500U;
    assert(gs_display_refresh_observe(&refresh, &input) == GS_DISPLAY_REFRESH_NONE);
}

int main(void)
{
    test_camera_complete_and_late_events();
    test_camera_incomplete_and_error();
    test_camera_slow_consumer_and_latest();
    test_camera_validation_and_exhaustion();
    test_display_exchange_and_unchanged_pixels();
    test_display_cancel_validation_exhaustion();
    test_display_unarmed_submit_abort();
    test_display_refresh_preview_cadence_and_busy_retention();
    test_display_refresh_critical_edges();
    test_display_refresh_terminal_grace_and_wrap();
    puts("buffer ownership tests passed");
    return 0;
}
