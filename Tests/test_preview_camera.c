/* Actual CameraTask/App C + actual preprocess + actual two-slot preview pool.
 * Deterministic scheduler/queues; no peripheral or target access. */
#define GS_TEST_REAL_PREVIEW
#define main startup_regression_main
#include "test_startup.c"
#undef main
static uint8_t preview_raw[GS_CAMERA_FRAME_BYTES];
static void capture(uint32_t id, uint32_t time)
{
    injected_frame.frame_id = id; injected_frame.capture_ms = time;
    camera_poll_pending = 1; run_task(&threads[GS_TASK_CAMERA + 1]);
    assert(!camera_poll_pending);
}
int main(void)
{
    uint32_t i;
    gs_port_frame_t selected;
    reset_model(); MX_FREERTOS_Init(); start_scheduler();
    injected_frame.image.data = preview_raw;
    injected_frame.image.data_size = sizeof preview_raw;
    injected_frame.image.width = 320; injected_frame.image.height = 240;
    injected_frame.image.stride_bytes = 640; injected_frame.image.byte_order = GS_RGB565_MSB_FIRST;
    for (i = 0; i < sizeof preview_raw; i += 2) { preview_raw[i] = (uint8_t)(i >> 8); preview_raw[i+1] = (uint8_t)i; }
    memset(s_ai_input, 0x37, sizeof s_ai_input);
    /* Camera can publish many new frames without running Vision/inference.
       The one-slot raw queue must retain the newest completed frame and return
       each superseded raw lease instead of making Vision process old FIFO data. */
    for (i = 1; i <= 5; ++i) {
        capture(i, 100U+i);
        assert(g_gs_diag.preview_frames == i && queued_preview.frame_id == i);
        for (uint32_t at = 0; at < GS_PREVIEW_BYTES; ++at) {
            assert(s_ai_input[at] == 0x37);
        }
        gui_render_and_return_preview(); assert(consumed_preview.frame_id == i && preview_return_queued);
        assert(camera_frame_queued && queued_camera_frame.frame_id == i);
        assert(raw_releases == i - 1U && g_gs_diag.camera_drops == i - 1U);
    }
    assert(!g_gs_static_diag.completed && !g_gs_static_diag.progress_chunks);
    assert(osMessageQueueGet(s_camera_frames, &selected, NULL, 0U) == osOK);
    assert(selected.frame_id == 5U && selected.capture_ms == 105U);
    gs_port_camera_release(&selected);
    /* A persistent queue error still previews, then returns its raw lease. */
    camera_queue_blocked = 1; capture(6, 106);
    assert(raw_releases == 6 && g_gs_diag.camera_drops == 5 && queued_preview.frame_id == 6);
    assert(!camera_frame_queued);
    camera_queue_blocked = 0;
    gui_render_and_return_preview(); camera_reclaim_previews();
    /* BAD_QUALITY is a valid dark/bright image; recognition still rejects it. */
    memset(preview_raw, 0, sizeof preview_raw); capture(7, 107);
    for (i=0;i<GS_PREVIEW_BYTES;++i) assert(queued_preview.pixels[i] == 0);
    gui_render_and_return_preview(); camera_reclaim_previews();
    memset(preview_raw, 0xFF, sizeof preview_raw); capture(8, 108);
    for (i=0;i<GS_PREVIEW_BYTES;++i) assert(queued_preview.pixels[i] == 255);
    gui_render_and_return_preview(); camera_reclaim_previews();
    assert(g_gs_preview_diag.invalid == 0 && g_gs_diag.preview_frames == 8);
    /* Invalid image cannot expose partially generated/stale pixels. */
    injected_frame.image.data_size--; capture(9,109);
    assert(!preview_queued && g_gs_preview_diag.invalid == 1 && g_gs_diag.preview_frames == 8);
    injected_frame.image.data_size++;
    /* Keep a GUI-held lease while filling the other slot: held pixels immutable. */
    memset(preview_raw, 0, sizeof preview_raw); capture(10,110);
    gs_preview_frame_t held = queued_preview; preview_queued = 0;
    memset(preview_raw,0xFF,sizeof preview_raw); capture(11,111);
    for(i=0;i<GS_PREVIEW_BYTES;++i) assert(held.pixels[i] == 0 && queued_preview.pixels[i] == 255);
    capture(12,112); assert(g_gs_diag.preview_frames == 10 && queued_preview.frame_id == 11);
    assert(gs_preview_release(&s_preview_pool,held.ticket)==GS_PREVIEW_OK);
    assert(gs_preview_release(&s_preview_pool,held.ticket)==GS_PREVIEW_STALE);
    gui_render_and_return_preview(); camera_reclaim_previews();
    preview_put_failure = 1; capture(13,113);
    assert(!s_preview_pool.slots[0].in_use && !s_preview_pool.slots[1].in_use);
    preview_put_failure = 0; capture(14,114);
    assert(queued_preview.frame_id == 14 && g_gs_preview_diag.published_id == 14);
    /* Timing regression for the measured phase1 failure: while a 200 ms
       inference is busy, three captures arrive. Selecting frame 22 keeps the
       eventual observation at 220 ms; retaining frame 20 would be 500 ms old
       and trip the unchanged 300 ms business gate. */
    assert(osMessageQueueGet(s_camera_frames, &selected, NULL, 0U) == osOK);
    gs_port_camera_release(&selected);
    capture(20, 0U); capture(21, 140U); capture(22, 280U);
    assert(osMessageQueueGet(s_camera_frames, &selected, NULL, 0U) == osOK);
    assert(selected.frame_id == 22U && selected.capture_ms == 280U);
    assert(500U - selected.capture_ms == 220U && 500U - selected.capture_ms <= 300U);
    gs_port_camera_release(&selected);
    puts("PASS: actual Camera preview independent of Vision; exact pixels, quality, leases, queue/drop/rollback");
    return 0;
}
