#ifndef GS_TIMING_TRACE_H
#define GS_TIMING_TRACE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Debugger-readable, frame-correlated timing records. The trace is diagnostic
 * only: it does not own camera, preview, inference, or observation storage. */
#define GS_TIMING_TRACE_VERSION 1U
#define GS_TIMING_TRACE_CAPACITY 32U

enum {
    GS_TIMING_STAGE_CAPTURE_END = 1U << 0,
    GS_TIMING_STAGE_CAMERA_PUBLISH = 1U << 1,
    GS_TIMING_STAGE_VISION_DEQUEUE = 1U << 2,
    GS_TIMING_STAGE_PREPROCESS_DONE = 1U << 3,
    GS_TIMING_STAGE_INFERENCE_BEGIN = 1U << 4,
    GS_TIMING_STAGE_INFERENCE_END = 1U << 5,
    GS_TIMING_STAGE_GESTURE_CONSUME = 1U << 6
};

enum {
    GS_TIMING_OUTCOME_OBSERVATION_VALID = 1U << 0,
    GS_TIMING_OUTCOME_COMMAND = 1U << 1,
    GS_TIMING_OUTCOME_FAULT = 1U << 2,
    GS_TIMING_OUTCOME_FAULT_AGE = 1U << 3,
    GS_TIMING_OUTCOME_FAULT_INVALID = 1U << 4,
    GS_TIMING_OUTCOME_FAULT_SCORES = 1U << 5,
    GS_TIMING_OUTCOME_FAULT_ORDER = 1U << 6,
    GS_TIMING_OUTCOME_FAULT_GAP = 1U << 7,
    GS_TIMING_OUTCOME_DUPLICATE = 1U << 8,
    GS_TIMING_OUTCOME_RECOVERY_CUTOFF = 1U << 9,
    GS_TIMING_OUTCOME_DISABLED = 1U << 10,
    GS_TIMING_OUTCOME_FAULT_UNATTRIBUTED = 1U << 11
};

/* All fields are fixed-width and intentionally pointer-free for debugger and
 * offline decoders. A tick value of zero is valid; stage_valid says whether a
 * timestamp exists. Unsigned subtraction is the defined wrap-safe duration. */
typedef struct {
    uint32_t sequence;
    uint32_t frame_id;
    uint32_t stage_valid;
    uint32_t capture_end_ms;
    uint32_t camera_publish_ms;
    uint32_t vision_dequeue_ms;
    uint32_t preprocess_done_ms;
    uint32_t inference_begin_ms;
    uint32_t inference_end_ms;
    uint32_t gesture_consume_ms;
    uint32_t terminal_age_ms;
    uint32_t consume_age_ms;
    uint32_t preprocess_status;
    uint32_t inference_status;
    uint32_t static_status;
    uint32_t outcome_flags;
    uint32_t gesture_state_before;
    uint32_t gesture_state_after;
    uint32_t fault_count_before;
    uint32_t fault_count_after;
    uint32_t command_sequence;
    uint32_t command_action;
    uint32_t inference_scheduled_cycles;
} gs_timing_trace_payload_t;

typedef struct {
    volatile uint32_t begin_sequence;
    gs_timing_trace_payload_t payload;
    volatile uint32_t end_sequence;
} gs_timing_trace_slot_t;

typedef struct {
    uint32_t version;
    uint32_t record_bytes;
    uint32_t capacity;
    volatile uint32_t published_sequence;
    volatile uint32_t total_published;
    volatile uint32_t overwrite_count;
    volatile uint32_t observation_queue_drops;
    volatile uint32_t stale_before_inference;
    volatile uint32_t gesture_tick_faults;
    volatile uint32_t input_fault_signals;
    volatile uint32_t observations_enqueued;
    volatile uint32_t observations_consumed;
    volatile uint32_t reset_discarded;
    gs_timing_trace_slot_t slots[GS_TIMING_TRACE_CAPACITY];
} gs_timing_trace_ring_t;

extern volatile gs_timing_trace_ring_t g_gs_timing_trace;

void gs_timing_trace_init(void);
void gs_timing_trace_publish(const gs_timing_trace_payload_t *payload);
bool gs_timing_trace_read(uint32_t sequence, gs_timing_trace_payload_t *payload);
void gs_timing_trace_count_observation_drop(void);
void gs_timing_trace_count_stale_input(void);
void gs_timing_trace_count_gesture_tick_fault(void);
void gs_timing_trace_count_input_fault(void);
void gs_timing_trace_count_observation_enqueued(void);
void gs_timing_trace_count_observation_consumed(void);
void gs_timing_trace_count_reset_discarded(uint32_t count);

#ifdef __cplusplus
}
#endif
#endif
