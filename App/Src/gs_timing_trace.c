#include "gs_timing_trace.h"
#include "main.h"

#include <limits.h>
#include <string.h>

volatile gs_timing_trace_ring_t g_gs_timing_trace;

static uint32_t gs_trace_saturating_increment(uint32_t value)
{
    return value == UINT32_MAX ? value : value + 1U;
}

void gs_timing_trace_init(void)
{
    memset((void *)&g_gs_timing_trace, 0, sizeof(g_gs_timing_trace));
    g_gs_timing_trace.version = GS_TIMING_TRACE_VERSION;
    g_gs_timing_trace.record_bytes = sizeof(gs_timing_trace_payload_t);
    g_gs_timing_trace.capacity = GS_TIMING_TRACE_CAPACITY;
}

void gs_timing_trace_publish(const gs_timing_trace_payload_t *payload)
{
    gs_timing_trace_payload_t complete;
    volatile gs_timing_trace_slot_t *slot;
    uint32_t sequence;
    uint32_t total;
    if (payload == NULL) {
        return;
    }
    sequence = g_gs_timing_trace.published_sequence + 1U;
    if (sequence == 0U) {
        sequence = 1U;
    }
    complete = *payload;
    complete.sequence = sequence;
    slot = &g_gs_timing_trace.slots[(sequence - 1U) % GS_TIMING_TRACE_CAPACITY];
    /* Invalidate first. A debugger that catches this slot while it is being
     * replaced rejects it because the two sequence guards cannot agree. */
    slot->end_sequence = 0U;
    __DMB();
    slot->begin_sequence = sequence;
    slot->payload = complete;
    __DMB();
    slot->end_sequence = sequence;
    __DMB();
    total = g_gs_timing_trace.total_published;
    if (total >= GS_TIMING_TRACE_CAPACITY) {
        g_gs_timing_trace.overwrite_count =
            gs_trace_saturating_increment(g_gs_timing_trace.overwrite_count);
    }
    g_gs_timing_trace.total_published = gs_trace_saturating_increment(total);
    __DMB();
    g_gs_timing_trace.published_sequence = sequence;
}

bool gs_timing_trace_read(uint32_t sequence, gs_timing_trace_payload_t *payload)
{
    volatile const gs_timing_trace_slot_t *slot;
    uint32_t end_before;
    uint32_t end_after;
    uint32_t begin;
    if (sequence == 0U || payload == NULL) {
        return false;
    }
    slot = &g_gs_timing_trace.slots[(sequence - 1U) % GS_TIMING_TRACE_CAPACITY];
    end_before = slot->end_sequence;
    __DMB();
    begin = slot->begin_sequence;
    *payload = slot->payload;
    __DMB();
    end_after = slot->end_sequence;
    return end_before == sequence && end_after == sequence &&
           begin == sequence && payload->sequence == sequence;
}

void gs_timing_trace_count_observation_drop(void)
{
    g_gs_timing_trace.observation_queue_drops = gs_trace_saturating_increment(
        g_gs_timing_trace.observation_queue_drops);
}

void gs_timing_trace_count_stale_input(void)
{
    g_gs_timing_trace.stale_before_inference = gs_trace_saturating_increment(
        g_gs_timing_trace.stale_before_inference);
}

void gs_timing_trace_count_gesture_tick_fault(void)
{
    g_gs_timing_trace.gesture_tick_faults = gs_trace_saturating_increment(
        g_gs_timing_trace.gesture_tick_faults);
}

void gs_timing_trace_count_input_fault(void)
{
    g_gs_timing_trace.input_fault_signals = gs_trace_saturating_increment(
        g_gs_timing_trace.input_fault_signals);
}

void gs_timing_trace_count_observation_enqueued(void)
{
    g_gs_timing_trace.observations_enqueued = gs_trace_saturating_increment(
        g_gs_timing_trace.observations_enqueued);
}

void gs_timing_trace_count_observation_consumed(void)
{
    g_gs_timing_trace.observations_consumed = gs_trace_saturating_increment(
        g_gs_timing_trace.observations_consumed);
}

void gs_timing_trace_count_reset_discarded(uint32_t count)
{
    uint32_t value = g_gs_timing_trace.reset_discarded;
    if (UINT32_MAX - value < count) {
        value = UINT32_MAX;
    } else {
        value += count;
    }
    g_gs_timing_trace.reset_discarded = value;
}
