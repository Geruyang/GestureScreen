#include "gs_timing_trace.h"

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    gs_timing_trace_payload_t input;
    gs_timing_trace_payload_t output;
    uint32_t i;
    assert(sizeof(gs_timing_trace_payload_t) == 92U);
    assert(sizeof(gs_timing_trace_slot_t) == 100U);
    assert(sizeof(gs_timing_trace_ring_t) == 3252U);
    gs_timing_trace_init();
    assert(g_gs_timing_trace.version == GS_TIMING_TRACE_VERSION);
    assert(g_gs_timing_trace.record_bytes == 92U);
    assert(g_gs_timing_trace.capacity == 32U);
    memset(&input, 0, sizeof input);
    input.frame_id = 7U;
    input.stage_valid = GS_TIMING_STAGE_CAPTURE_END | GS_TIMING_STAGE_GESTURE_CONSUME;
    input.capture_end_ms = UINT32_MAX - 10U;
    input.gesture_consume_ms = 20U;
    input.consume_age_ms = 31U;
    input.inference_scheduled_cycles = 123456U;
    gs_timing_trace_publish(&input);
    assert(g_gs_timing_trace.published_sequence == 1U);
    assert(gs_timing_trace_read(1U, &output));
    assert(output.sequence == 1U && output.frame_id == 7U && output.consume_age_ms == 31U);
    g_gs_timing_trace.slots[0].end_sequence = 0U;
    assert(!gs_timing_trace_read(1U, &output));
    g_gs_timing_trace.slots[0].end_sequence = 1U;
    for (i = 0U; i < 32U; ++i) {
        input.frame_id = 8U + i;
        gs_timing_trace_publish(&input);
    }
    assert(g_gs_timing_trace.total_published == 33U);
    assert(g_gs_timing_trace.overwrite_count == 1U);
    assert(!gs_timing_trace_read(1U, &output));
    assert(gs_timing_trace_read(33U, &output) && output.frame_id == 39U);
    gs_timing_trace_init();
    g_gs_timing_trace.published_sequence = UINT32_MAX - 1U;
    gs_timing_trace_publish(&input);
    assert(g_gs_timing_trace.published_sequence == UINT32_MAX);
    assert(gs_timing_trace_read(UINT32_MAX, &output));
    gs_timing_trace_publish(&input);
    assert(g_gs_timing_trace.published_sequence == 1U);
    assert(gs_timing_trace_read(1U, &output));
    gs_timing_trace_count_observation_enqueued();
    gs_timing_trace_count_observation_consumed();
    gs_timing_trace_count_observation_drop();
    gs_timing_trace_count_stale_input();
    gs_timing_trace_count_gesture_tick_fault();
    gs_timing_trace_count_input_fault();
    gs_timing_trace_count_reset_discarded(3U);
    assert(g_gs_timing_trace.observations_enqueued == 1U);
    assert(g_gs_timing_trace.observations_consumed == 1U);
    assert(g_gs_timing_trace.observation_queue_drops == 1U);
    assert(g_gs_timing_trace.stale_before_inference == 1U);
    assert(g_gs_timing_trace.gesture_tick_faults == 1U);
    assert(g_gs_timing_trace.input_fault_signals == 1U);
    assert(g_gs_timing_trace.reset_discarded == 3U);
    g_gs_timing_trace.reset_discarded = UINT32_MAX - 1U;
    gs_timing_trace_count_reset_discarded(4U);
    assert(g_gs_timing_trace.reset_discarded == UINT32_MAX);
    puts("PASS: timing trace ABI, guarded publish/read, overwrite, wrap and counters");
    return 0;
}
