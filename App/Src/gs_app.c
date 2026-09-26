#include "gs_app.h"
#include "gs_app_config.h"
#include "gs_vision_profile.h"
#include "gs_port.h"
#include "gs_preview.h"
#include "gs_content.h"
#include "gs_timing_trace.h"
#include "main.h"
#include "cmsis_os2.h"
#include "FreeRTOS.h"
#include "task.h"
#include <string.h>

/* 只用于本文件的静态数组；不能传入指针。 */
#define GS_ARRAY_COUNT(array) (sizeof(array) / sizeof((array)[0]))
#define GS_VISION_TERMINAL_MAX_AGE_MS 300U
#define GS_VISION_DEQUEUE_REMAINING_BUDGET_MS 200U
#define GS_VISION_PREPROCESS_REMAINING_BUDGET_MS 220U
#define GS_VISION_ADMISSION_MAX_AGE_MS \
    (GS_VISION_TERMINAL_MAX_AGE_MS - GS_VISION_DEQUEUE_REMAINING_BUDGET_MS)
#define GS_VISION_PREPROCESS_ADMISSION_MAX_AGE_MS \
    (GS_VISION_TERMINAL_MAX_AGE_MS - GS_VISION_PREPROCESS_REMAINING_BUDGET_MS)
#if GS_VISION_DEQUEUE_REMAINING_BUDGET_MS >= GS_VISION_TERMINAL_MAX_AGE_MS || \
    GS_VISION_PREPROCESS_REMAINING_BUDGET_MS >= GS_VISION_TERMINAL_MAX_AGE_MS
#error "Vision remaining-work budgets must leave positive admission windows"
#endif

volatile gs_app_diagnostics_t g_gs_diag;
volatile gs_static_diagnostics_t g_gs_static_diag;
volatile gs_preview_diagnostics_t g_gs_preview_diag;
volatile uint32_t g_gs_deadline_admission_drops;
volatile uint32_t g_gs_preprocess_admission_drops;
static void *s_cycle_task;
static volatile uint32_t s_cycle_available, s_cycle_running, s_cycle_start, s_cycle_total;
#ifndef GS_VISION_CYCLE_READ
#define GS_VISION_CYCLE_READ() (DWT->CYCCNT)
#endif
void gs_vision_profile_switched_in(void *task)
{
#if GS_VISION_CYCLE_PROFILE
    if (s_cycle_available && task == s_cycle_task) {
        s_cycle_start = GS_VISION_CYCLE_READ(); s_cycle_running = 1U;
    }
#else
    (void)task;
#endif
}
void gs_vision_profile_switched_out(void *task)
{
#if GS_VISION_CYCLE_PROFILE
    if (s_cycle_available && task == s_cycle_task && s_cycle_running) {
        s_cycle_total += GS_VISION_CYCLE_READ() - s_cycle_start; s_cycle_running = 0U;
    }
#else
    (void)task;
#endif
}
static void vision_cycle_init(void *task)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    s_cycle_available = s_cycle_running = s_cycle_total = 0U; s_cycle_task = task;
#if GS_VISION_CYCLE_PROFILE
    if ((DWT->CTRL & DWT_CTRL_NOCYCCNT_Msk) == 0U) {
        uint32_t before, after;
        CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
        DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk; /* Preserve existing CYCCNT origin. */
        before = GS_VISION_CYCLE_READ();
        for (uint32_t i = 0U; i < 32U; ++i) { after = GS_VISION_CYCLE_READ(); (void)after; }
        after = GS_VISION_CYCLE_READ();
        if (before != after) {
            s_cycle_available = s_cycle_running = 1U; s_cycle_start = after;
        }
    }
#endif
    g_gs_static_diag.cycles_available = s_cycle_available;
    __set_PRIMASK(mask);
}
static uint32_t vision_cycle_snapshot(void)
{
    uint32_t mask = __get_PRIMASK(), total;
    __disable_irq(); total = s_cycle_total;
#if GS_VISION_CYCLE_PROFILE
    if (s_cycle_available && s_cycle_running) { total += GS_VISION_CYCLE_READ() - s_cycle_start; }
#endif
    __set_PRIMASK(mask); return total;
}
static gs_static_result_t s_static_snapshot;
static volatile uint32_t s_static_busy;
static volatile uint32_t s_camera_fault_ms, s_camera_fault_seen;
volatile int32_t g_gs_debug_action = -1;
/* 队列只传递描述符；像素缓冲的生命周期由租约决定。 */
static osMessageQueueId_t s_camera_frames;        /* CameraTask → VisionTask：完整帧。 */
static osMessageQueueId_t s_camera_returns;       /* VisionTask → CameraTask：原图租约。 */
static osMessageQueueId_t s_gesture_observations; /* VisionTask → GestureTask：观测+同帧trace。 */
static osMessageQueueId_t s_gesture_commands;     /* GestureTask → GuiTask：业务命令。 */
static osMessageQueueId_t s_local_actions;        /* 按键/触摸 → GuiTask：本地操作。 */
static osMessageQueueId_t s_previews;             /* CameraTask → GuiTask：缩略图。 */
static osMessageQueueId_t s_preview_returns;      /* GuiTask → CameraTask：预览租约。 */
static osThreadId_t s_threads[GS_TASK_COUNT];
static gs_gesture_t s_gesture;
static gs_ui_t s_ui;
static gs_preview_pool_t s_preview_pool;
/* 两个对齐字段分别由 GuiTask、VisionTask 单独写入；诊断结构仅保存副本。 */
static volatile uint32_t s_ui_generation;
static volatile uint32_t s_model_ready;
static volatile uint32_t s_recognition_enabled = 1U;
static uint32_t s_rate_sample_ms, s_rate_camera_frames, s_rate_vision_frames;
static uint32_t s_camera_fps_milli, s_vision_fps_milli;
/* 每个任务只写自己的一个字节，HealthTask 读取全部字节。
 * 这样无需并发读改写共享位掩码，并确保所有任务实际运行过一次后才允许喂狗。 */
static volatile uint8_t s_heartbeat_seen[GS_TASK_COUNT];
#if defined(_MSC_VER)
__declspec(align(4)) static int8_t s_ai_input[GS_AI_INPUT_SIZE];
#else
static int8_t s_ai_input[GS_AI_INPUT_SIZE] __attribute__((aligned(4))); /* Cube.AI input alignment; 27 KiB ordinary SRAM. */
#endif
static uint32_t s_preview_storage[GS_PREVIEW_SLOTS][GS_PREVIEW_BYTES / 4U];
#define GS_APP_MAX_COLLECTIONS 8U
static gs_ui_collection_t s_runtime_collections[GS_APP_MAX_COLLECTIONS];
static uint16_t s_runtime_collection_count, s_content_collection_count;

typedef struct {
    gs_gesture_observation_t observation;
    gs_timing_trace_payload_t trace;
} gs_gesture_envelope_t;

static bool trace_scores_valid(const gs_gesture_observation_t *observation)
{
    uint32_t i;
    float sum = 0.0f;
    for (i = 0U; i < (uint32_t)GS_CLASS_COUNT; ++i) {
        float score = observation->scores[i];
        if (!(score >= 0.0f && score <= 1.0f)) { return false; }
        sum += score;
    }
    return sum >= 0.99f && sum <= 1.01f;
}

static bool trace_sequence_newer(uint32_t newer, uint32_t older)
{
    uint32_t delta = newer - older;
    return delta != 0U && delta < UINT32_C(0x80000000);
}

static uint32_t trace_reason_before_process(const gs_gesture_t *gesture,
    const gs_gesture_observation_t *observation, uint32_t consume_ms)
{
    uint32_t reasons = 0U;
    if (gesture->enabled && gesture->have_frame && !gesture->gap_fault_latched &&
        consume_ms - gesture->last_receive_ms > gesture->config.max_gap_ms) {
        reasons |= GS_TIMING_OUTCOME_FAULT_GAP;
    }
    if (!gesture->enabled) {
        reasons |= GS_TIMING_OUTCOME_DISABLED;
    } else if (consume_ms - observation->capture_ms > gesture->config.max_age_ms) {
        reasons |= GS_TIMING_OUTCOME_FAULT_AGE;
    } else if (!observation->valid) {
        reasons |= GS_TIMING_OUTCOME_FAULT_INVALID;
    } else if (!trace_scores_valid(observation)) {
        reasons |= GS_TIMING_OUTCOME_FAULT_SCORES;
    } else if (gesture->have_frame && observation->frame_id == gesture->last_frame_id) {
        reasons |= GS_TIMING_OUTCOME_DUPLICATE;
    } else if (gesture->have_frame &&
        (!trace_sequence_newer(observation->frame_id, gesture->last_frame_id) ||
         !trace_sequence_newer(observation->capture_ms, gesture->last_capture_ms))) {
        reasons |= GS_TIMING_OUTCOME_FAULT_ORDER;
    } else if (gesture->have_frame &&
        (observation->capture_ms - gesture->last_capture_ms > gesture->config.max_gap_ms ||
         consume_ms - gesture->last_receive_ms > gesture->config.max_gap_ms)) {
        reasons |= GS_TIMING_OUTCOME_FAULT_GAP;
    }
    return reasons;
}

static void trace_finalize_fault(gs_timing_trace_payload_t *trace,
                                 uint32_t fault_count_after)
{
    trace->fault_count_after = fault_count_after;
    if (trace->fault_count_after != trace->fault_count_before) {
        trace->outcome_flags |= GS_TIMING_OUTCOME_FAULT;
        if ((trace->outcome_flags & (GS_TIMING_OUTCOME_FAULT_AGE |
            GS_TIMING_OUTCOME_FAULT_INVALID | GS_TIMING_OUTCOME_FAULT_SCORES |
            GS_TIMING_OUTCOME_FAULT_ORDER | GS_TIMING_OUTCOME_FAULT_GAP)) == 0U) {
            trace->outcome_flags |= GS_TIMING_OUTCOME_FAULT_UNATTRIBUTED;
        }
    }
}

static bool prepare_runtime_collections(void)
{
    uint16_t i;
    if (g_gs_content_builtin_package.collection_count > GS_APP_MAX_COLLECTIONS) {
        return false;
    }
    s_content_collection_count = g_gs_content_builtin_package.collection_count;
    for (i = 0U; i < s_content_collection_count; ++i) {
        s_runtime_collections[i] = g_gs_content_builtin_package.collections[i];
        s_runtime_collections[i].kind = GS_UI_COLLECTION_CONTENT;
    }
    s_runtime_collection_count = i;
    return true;
}

/* 毫秒向上取整为 RTOS tick，至少让出一个 tick；业务时间仍使用 HAL_GetTick。 */
static void delay_ms(uint32_t ms)
{
    uint32_t ticks = (ms * osKernelGetTickFreq() + 999U) / 1000U;
    (void)osDelay(ticks == 0U ? 1U : ticks);
}

static void heartbeat(gs_task_id_t id)
{
    g_gs_diag.heartbeat[id] = HAL_GetTick();
    s_heartbeat_seen[id] = 1U;
}

/* 保留可由调试器观察的故障现场，停止喂狗。 */
void gs_app_fatal(uint32_t code)
{
    g_gs_diag.fatal_code = code;
    __disable_irq();
    for (;;) {
        __NOP();
    }
}

static void signal_gesture(uint32_t flags)
{
    if (osThreadFlagsSet(s_threads[GS_TASK_GESTURE], flags) & osFlagsError) {
        gs_app_fatal(GS_FATAL_GESTURE_SIGNAL);
    }
}

static void camera_reclaim_previews(void);
static void camera_publish_preview(const gs_port_frame_t *frame);
static void camera_publish_latest(const gs_port_frame_t *frame);

/* 相机任务：独占原图时采样预览，再交推理队列。 */
static void camera_task(void *argument)
{
    gs_port_frame_t frame, returned;
    (void)argument;
    for (;;) {
        camera_reclaim_previews();
        if (s_camera_fault_seen && HAL_GetTick() - s_camera_fault_ms > GS_STATIC_RESULT_TTL_MS) {
            s_camera_fault_seen = 0U; /* Camera is the only writer; bounded cutoff lifetime. */
        }
        while (osMessageQueueGet(s_camera_returns, &returned, NULL, 0U) == osOK) {
            gs_port_camera_release(&returned);
        }
        gs_port_status_t status = gs_port_camera_poll(&frame);
        if (status == GS_PORT_OK) {
            ++g_gs_diag.camera_frames;
            camera_publish_preview(&frame);
            camera_publish_latest(&frame);
        } else if (status == GS_PORT_ERROR) {
            ++g_gs_diag.camera_errors;
            s_camera_fault_ms = HAL_GetTick(); s_camera_fault_seen = 1U;
            signal_gesture(GS_FLAG_INPUT_FAULT);
        }
        heartbeat(GS_TASK_CAMERA);
        delay_ms(GS_CAMERA_PERIOD_MS);
    }
}

/* 预览池仅由 CameraTask 修改，GUI 只通过队列归还 ticket。 */
static void camera_reclaim_previews(void)
{
    gs_preview_ticket_t returned_preview;
    while (osMessageQueueGet(s_preview_returns, &returned_preview,
                             NULL, 0U) == osOK) {
        if (gs_preview_release(&s_preview_pool, returned_preview) != GS_PREVIEW_OK) {
            gs_app_fatal(GS_FATAL_PREVIEW_RETURN);
        }
    }
}

/* Sample while holding the raw lease, without touching Vision's tensor/workspace.
 * Preview has no quality gate: dark/bright scenes must remain visible.
 * Invalid frames never publish; congestion rolls back the exact preview lease. */
static void camera_publish_preview(const gs_port_frame_t *frame)
{
    gs_preview_frame_t preview;
    uint32_t start_ms = HAL_GetTick();
    gs_preview_result_t status = gs_preview_publish_rgb565(&s_preview_pool,
        &frame->image, frame->frame_id, frame->capture_ms, &preview);
    ++g_gs_preview_diag.sampled;
    if (status == GS_PREVIEW_INVALID) {
        ++g_gs_preview_diag.invalid;
        ++g_gs_diag.preview_drops;
    } else if (status == GS_PREVIEW_OK) {
        if (osMessageQueuePut(s_previews, &preview, 0U, 0U) == osOK) {
            ++g_gs_diag.preview_frames;
            g_gs_preview_diag.published_id = frame->frame_id;
            g_gs_preview_diag.published_capture_ms = frame->capture_ms;
        } else {
            ++g_gs_diag.preview_drops;
            if (gs_preview_release(&s_preview_pool, preview.ticket) != GS_PREVIEW_OK) {
                gs_app_fatal(GS_FATAL_PREVIEW_ROLLBACK);
            }
        }
    } else {
        ++g_gs_diag.preview_drops;
    }
    uint32_t sample_ms = HAL_GetTick() - start_ms;
    if (sample_ms > g_gs_preview_diag.max_sample_ms) {
        g_gs_preview_diag.max_sample_ms = sample_ms;
    }
}

/* 原图只用到预处理结束；归还后仅读取 frame 描述符，推理使用独立张量。 */
static void static_publish(const gs_static_result_t *result)
{
    uint32_t mask = __get_PRIMASK();
    /* Bounded result copy only: no HAL/RTOS/wait while interrupts are masked.
       Vision is sole writer; GUI takes the same protected copy. */
    __disable_irq();
    s_static_snapshot = *result;
    s_static_busy = result->status == GS_STATIC_RUNNING;
    __set_PRIMASK(mask);
    g_gs_static_diag.result = *result;
    g_gs_static_diag.busy = s_static_busy;
}

/* The single-slot Vision queue is a latest-frame mailbox. Inference is slower
 * than capture, so retaining the first frame that arrived while Vision was
 * busy made the next result 345--474 ms old even though inference took about
 * 200 ms. Replace an unconsumed frame with the newest completed capture. The
 * producer is the sole owner allowed to release an evicted raw lease.
 *
 * Vision may consume between the failed put and get. A second put then fills
 * the newly empty queue. Any unexpected second failure releases the new lease
 * as well; no raw buffer is orphaned. */
static void camera_publish_latest(const gs_port_frame_t *frame)
{
    gs_port_frame_t waiting;
    gs_port_frame_t published = *frame;
    published.camera_publish_ms = HAL_GetTick();
    if (osMessageQueuePut(s_camera_frames, &published, 0U, 0U) == osOK) {
        return;
    }
    if (osMessageQueueGet(s_camera_frames, &waiting, NULL, 0U) == osOK) {
        ++g_gs_diag.camera_drops;
        gs_port_camera_release(&waiting);
    }
    published.camera_publish_ms = HAL_GetTick();
    if (osMessageQueuePut(s_camera_frames, &published, 0U, 0U) != osOK) {
        ++g_gs_diag.camera_drops;
        gs_port_camera_release(frame);
    }
}
typedef struct { uint32_t start_ms, last_ms, yield_ms, layer_start_ms, layer; bool timeout;
    uint32_t cycle_start, cycle_last, layer_cycle_start; } static_progress_t;
static void static_begin_display(const gs_static_result_t *frame_result)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq(); s_static_busy = 1U;
    /* Keep the last terminal result with its original capture timestamp while
       the next frame computes. GUI independently expires it; no age freezing. */
    if (s_static_snapshot.frame_id == 0U) { static_publish(frame_result); }
    __set_PRIMASK(mask); g_gs_static_diag.busy = 1U;
}
static bool static_progress(void *context, size_t layer, uint32_t outputs)
{
    static_progress_t *progress = context;
    uint32_t now = HAL_GetTick(), chunk_ms = now - progress->last_ms;
    uint32_t cycles = vision_cycle_snapshot();
    if (layer != progress->layer) {
        progress->layer_start_ms = progress->last_ms;
        progress->layer_cycle_start = progress->cycle_last;
        progress->layer = (uint32_t)layer;
    }
    g_gs_static_diag.current_layer = (uint32_t)layer;
    g_gs_static_diag.current_outputs = outputs;
    if (layer < 29U) { g_gs_static_diag.layer_ms[layer] = now - progress->layer_start_ms; }
    if (layer < 29U) { g_gs_static_diag.layer_cycles[layer] = cycles - progress->layer_cycle_start; }
    g_gs_static_diag.scheduled_cycles = cycles - progress->cycle_start;
    progress->cycle_last = cycles;
    ++g_gs_static_diag.progress_chunks;
    if (chunk_ms > g_gs_static_diag.max_chunk_ms) { g_gs_static_diag.max_chunk_ms = chunk_ms; }
    progress->last_ms = now;
    if (now - progress->start_ms >= 1000U) { progress->timeout = true; return false; }
    heartbeat(GS_TASK_VISION); /* Only after an actual completed output chunk. */
    if (now - progress->yield_ms >= 10U) {
        uint32_t yield_start_ms = HAL_GetTick();
        delay_ms(1U); /* Real block permits peer GUI and lower-priority Health/Storage. */
        progress->yield_ms = HAL_GetTick();
        ++g_gs_static_diag.yield_count;
        g_gs_static_diag.yield_wait_ms += progress->yield_ms - yield_start_ms;
    }
    return true;
}

static bool vision_deadline_admit(uint32_t capture_ms, uint32_t dequeue_ms)
{
    return s_recognition_enabled == 0U ||
        dequeue_ms - capture_ms <= GS_VISION_ADMISSION_MAX_AGE_MS;
}

static bool vision_preprocess_deadline_expired(uint32_t capture_ms,
    uint32_t preprocess_done_ms, gs_preprocess_status_t preprocess_status)
{
    return preprocess_status == GS_PREPROCESS_OK && s_recognition_enabled != 0U &&
        preprocess_done_ms - capture_ms > GS_VISION_PREPROCESS_ADMISSION_MAX_AGE_MS;
}

static void vision_count_deadline_drop(void)
{
    if (g_gs_deadline_admission_drops != UINT32_MAX) {
        ++g_gs_deadline_admission_drops;
    }
}

static void vision_count_preprocess_deadline_drop(void)
{
    vision_count_deadline_drop();
    if (g_gs_preprocess_admission_drops != UINT32_MAX) {
        ++g_gs_preprocess_admission_drops;
    }
}

static void vision_process_frame(const gs_port_frame_t *frame, uint32_t dequeue_ms)
{
    gs_gesture_envelope_t envelope;
    gs_gesture_observation_t *observation = &envelope.observation;
    gs_timing_trace_payload_t *trace = &envelope.trace;
    gs_quality_stats_t quality;
    gs_preprocess_status_t preprocess_status;
    gs_static_result_t static_result;
    gs_ai_status_t inference_status = GS_AI_UNAVAILABLE;

    memset(&envelope, 0, sizeof(envelope));
    observation->frame_id = frame->frame_id;
    observation->capture_ms = frame->capture_ms;
    trace->frame_id = frame->frame_id;
    trace->stage_valid = GS_TIMING_STAGE_CAPTURE_END |
        GS_TIMING_STAGE_CAMERA_PUBLISH | GS_TIMING_STAGE_VISION_DEQUEUE;
    trace->capture_end_ms = frame->capture_ms;
    trace->camera_publish_ms = frame->camera_publish_ms;
    trace->vision_dequeue_ms = dequeue_ms;
    preprocess_status = gs_preprocess_rgb565(
        &frame->image, s_ai_input, sizeof(s_ai_input), NULL, &quality);
    trace->preprocess_done_ms = HAL_GetTick();
    trace->stage_valid |= GS_TIMING_STAGE_PREPROCESS_DONE;
    trace->preprocess_status = (uint32_t)preprocess_status;
    /* 通过归还队列交给 CameraTask 释放租约，避免并发修改相机帧池。 */
    if (osMessageQueuePut(s_camera_returns, frame, 0U, 0U) != osOK) {
        /* 相机帧池只有两个槽；不能丢失待归还的租约。 */
        gs_app_fatal(GS_FATAL_CAMERA_RETURN);
    }
    if (vision_preprocess_deadline_expired(frame->capture_ms,
            trace->preprocess_done_ms, preprocess_status)) {
        /* The raw lease is already safely returned. Preserve the previous
           result and its original age; do not start or publish doomed work. */
        vision_count_preprocess_deadline_drop();
        return;
    }
    memset(&static_result, 0, sizeof static_result);
    static_result.frame_id = frame->frame_id; static_result.capture_ms = frame->capture_ms;
    if (preprocess_status == GS_PREPROCESS_OK && s_recognition_enabled != 0U) {
        static_progress_t progress;
        progress.start_ms = progress.last_ms = progress.yield_ms = HAL_GetTick();
        trace->inference_begin_ms = progress.start_ms;
        trace->stage_valid |= GS_TIMING_STAGE_INFERENCE_BEGIN;
        progress.layer_start_ms = progress.start_ms; progress.layer = UINT32_MAX;
        progress.cycle_start = progress.cycle_last = progress.layer_cycle_start = vision_cycle_snapshot();
        g_gs_static_diag.current_layer = UINT32_MAX; g_gs_static_diag.current_outputs = 0U;
        g_gs_static_diag.current_frame_id = frame->frame_id;
        g_gs_static_diag.inference_start_ms = progress.start_ms;
        g_gs_static_diag.profile_frame_id = frame->frame_id;
        g_gs_static_diag.yield_count = g_gs_static_diag.yield_wait_ms = 0U;
        memset((void *)g_gs_static_diag.layer_ms, 0, sizeof g_gs_static_diag.layer_ms);
        memset((void *)g_gs_static_diag.layer_cycles, 0, sizeof g_gs_static_diag.layer_cycles);
        g_gs_static_diag.scheduled_cycles = 0U;
        progress.timeout = false;
        static_result.status = GS_STATIC_RUNNING; static_begin_display(&static_result);
        inference_status = gs_static_recognize(s_ai_input, sizeof s_ai_input,
            static_progress, &progress, &static_result);
        trace->inference_end_ms = HAL_GetTick();
        trace->stage_valid |= GS_TIMING_STAGE_INFERENCE_END;
        static_result.inference_ms = trace->inference_end_ms - progress.start_ms;
        g_gs_diag.inference_ms = static_result.inference_ms;
        g_gs_static_diag.terminal_scheduled_cycles = vision_cycle_snapshot() - progress.cycle_start;
        g_gs_static_diag.terminal_cycle_frame_id = frame->frame_id;
        trace->inference_scheduled_cycles = g_gs_static_diag.terminal_scheduled_cycles;
        if (static_result.inference_ms > g_gs_static_diag.max_inference_ms) {
            g_gs_static_diag.max_inference_ms = static_result.inference_ms;
        }
        if (progress.timeout || static_result.inference_ms >= 1000U) {
            static_result.status = GS_STATIC_TIMEOUT;
            static_result.confidence_permille = static_result.margin_permille = 0U;
            static_result.scores_valid = 0U;
            memset(static_result.scores, 0, sizeof static_result.scores);
            ++g_gs_static_diag.timeouts;
        }
        else if (inference_status != GS_AI_OK) { ++g_gs_static_diag.errors; }
        else { ++g_gs_static_diag.completed; }
    } else if (preprocess_status == GS_PREPROCESS_OK) {
        static_result.status = GS_STATIC_WAITING;
    } else { static_result.status = GS_STATIC_BAD_QUALITY; }
    gs_static_expire(&static_result, HAL_GetTick()); static_publish(&static_result);
    if (preprocess_status == GS_PREPROCESS_OK && inference_status == GS_AI_OK &&
        static_result.status != GS_STATIC_TIMEOUT && static_result.scores_valid != 0U &&
        s_model_ready != 0U) {
        memcpy(observation->scores, static_result.scores, sizeof observation->scores);
        observation->valid = true;
    } else if (preprocess_status != GS_PREPROCESS_OK) {
        ++g_gs_diag.quality_rejects;
    }
    trace->inference_status = (uint32_t)inference_status;
    trace->static_status = (uint32_t)static_result.status;
    trace->terminal_age_ms = HAL_GetTick() - frame->capture_ms;
    if (observation->valid) {
        trace->outcome_flags |= GS_TIMING_OUTCOME_OBSERVATION_VALID;
    }
    g_gs_diag.vision_age_ms = trace->terminal_age_ms;
    ++g_gs_diag.vision_frames;
    if (osMessageQueuePut(s_gesture_observations, &envelope, 0U, 0U) != osOK) {
        ++g_gs_diag.observation_drops;
        gs_timing_trace_count_observation_drop();
        signal_gesture(GS_FLAG_INPUT_FAULT);
    } else {
        gs_timing_trace_count_observation_enqueued();
    }
}

/* 视觉任务：初始化模型一次，处理独立推理输入；不修改预览池。 */
static void vision_task(void *argument)
{
    gs_port_frame_t frame;
    (void)argument;
    vision_cycle_init(osThreadGetId());
    g_gs_diag.model_status = (uint32_t)gs_static_model_status();
    s_model_ready = g_gs_diag.model_status == (uint32_t)GS_AI_OK;
    g_gs_diag.model_ready = s_model_ready;
    for (;;) {
        if (osMessageQueueGet(s_camera_frames, &frame, NULL, 0U) == osOK) {
            uint32_t dequeue_ms = HAL_GetTick();
            uint32_t dequeue_age_ms = dequeue_ms - frame.capture_ms;
            /* Return old queued images before spending another inference budget. */
            if (dequeue_age_ms > GS_VISION_TERMINAL_MAX_AGE_MS) {
                ++g_gs_static_diag.stale_inputs;
                gs_timing_trace_count_stale_input();
                if (osMessageQueuePut(s_camera_returns, &frame, 0U, 0U) != osOK) {
                    gs_app_fatal(GS_FATAL_CAMERA_RETURN);
                }
            } else if (!vision_deadline_admit(frame.capture_ms, dequeue_ms)) {
                /* Do not spend the model budget on a frame that cannot meet
                   the unchanged 300 ms terminal-age contract. This path owns
                   no result, observation or fault publication. */
                vision_count_deadline_drop();
                if (osMessageQueuePut(s_camera_returns, &frame, 0U, 0U) != osOK) {
                    gs_app_fatal(GS_FATAL_CAMERA_RETURN);
                }
            } else { vision_process_frame(&frame, dequeue_ms); }
        }
        heartbeat(GS_TASK_VISION);
        delay_ms(GS_VISION_PERIOD_MS);
    }
}

/* 手势任务：故障通知优先于观测处理；无图像时也检查停帧超时。 */
static void gesture_task(void *argument)
{
    gs_gesture_envelope_t envelope;
    gs_ui_command_t command;
    uint32_t recovery_cutoff_ms = 0U;
    bool have_recovery_cutoff = false;
    (void)argument;
    for (;;) {
        uint32_t flags = osThreadFlagsWait(GS_FLAG_REQUIRE_CLEAR | GS_FLAG_INPUT_FAULT,
                                          osFlagsWaitAny, 0U);
        gs_gesture_set_enabled(&s_gesture,
            GS_RECOGNITION_REQUESTED && GS_UNKNOWN_NEUTRAL_REARM && s_model_ready != 0U &&
            s_recognition_enabled != 0U);
        if ((flags & osFlagsError) == 0U) {
            /* 清除故障发生时已排队的观测；这些旧帧不能作为恢复依据。
             * 后续还需按采集时间过滤，防止正在推理的旧图像迟到。 */
            uint32_t discarded = osMessageQueueGetCount(s_gesture_observations);
            (void)osMessageQueueReset(s_gesture_observations);
            gs_timing_trace_count_reset_discarded(discarded);
            recovery_cutoff_ms = HAL_GetTick();
            have_recovery_cutoff = true;
            if (flags & GS_FLAG_INPUT_FAULT) {
                gs_timing_trace_count_input_fault();
                gs_gesture_report_fault(&s_gesture);
            } else {
                gs_gesture_require_clear(&s_gesture);
            }
        }
        uint32_t state_before_tick = (uint32_t)s_gesture.state;
        uint32_t faults_before_tick = s_gesture.fault_count;
        gs_gesture_tick(&s_gesture, HAL_GetTick(), s_ui_generation);
        bool tick_fault = s_gesture.fault_count != faults_before_tick;
        if (tick_fault) { gs_timing_trace_count_gesture_tick_fault(); }
        /* 超过帧年龄窗口后，常规新鲜度检查已能拒绝故障前图像。
         * 及时关闭截止时间检查，避免半周期时间比较长期有效而产生歧义。 */
        if (have_recovery_cutoff && HAL_GetTick() - recovery_cutoff_ms >
            s_gesture.config.max_age_ms) {
            have_recovery_cutoff = false;
        }
        if (osMessageQueueGet(s_gesture_observations, &envelope, NULL, 0U) == osOK) {
            gs_gesture_observation_t *observation = &envelope.observation;
            gs_timing_trace_payload_t *trace = &envelope.trace;
            uint32_t consume_ms = HAL_GetTick();
            bool emitted;
            gs_timing_trace_count_observation_consumed();
            trace->gesture_consume_ms = consume_ms;
            trace->consume_age_ms = consume_ms - observation->capture_ms;
            trace->stage_valid |= GS_TIMING_STAGE_GESTURE_CONSUME;
            trace->gesture_state_before = state_before_tick;
            trace->fault_count_before = faults_before_tick;
            if (tick_fault) { trace->outcome_flags |= GS_TIMING_OUTCOME_FAULT_GAP; }
            /* 清空队列无法取消 VisionTask 正在处理的故障前图像。 */
            if (have_recovery_cutoff &&
                (observation->capture_ms - recovery_cutoff_ms) >= 0x80000000UL) {
                trace->outcome_flags |= GS_TIMING_OUTCOME_RECOVERY_CUTOFF;
                trace->gesture_state_after = (uint32_t)s_gesture.state;
                trace_finalize_fault(trace, s_gesture.fault_count);
                gs_timing_trace_publish(trace);
                heartbeat(GS_TASK_GESTURE);
                delay_ms(GS_GESTURE_PERIOD_MS);
                continue;
            }
            trace->outcome_flags |= trace_reason_before_process(&s_gesture,
                observation, consume_ms);
            emitted = gs_gesture_process(&s_gesture, observation, consume_ms,
                                         s_ui_generation, &command);
            if (emitted) {
                trace->outcome_flags |= GS_TIMING_OUTCOME_COMMAND;
                trace->command_sequence = command.sequence;
                trace->command_action = (uint32_t)command.action;
                if (osMessageQueuePut(s_gesture_commands, &command, 0U, 0U) != osOK) {
                    ++g_gs_diag.command_drops;
                    gs_gesture_require_clear(&s_gesture);
                }
            }
            trace->gesture_state_after = (uint32_t)s_gesture.state;
            trace_finalize_fault(trace, s_gesture.fault_count);
            gs_timing_trace_publish(trace);
        }
        g_gs_diag.gesture_state = (uint32_t)s_gesture.state;
        g_gs_diag.gesture_progress = gs_gesture_progress(&s_gesture);
        heartbeat(GS_TASK_GESTURE);
        delay_ms(GS_GESTURE_PERIOD_MS);
    }
}

bool gs_app_post_action(gs_ui_action_t action)
{
    if ((unsigned)action > (unsigned)GS_UI_HOME || s_local_actions == NULL) {
        return false;
    }
    return osMessageQueuePut(s_local_actions, &action, 0U, 0U) == osOK;
}

/* BSP 返回前必须完成预览绘制/复制；此后 GUI 不再访问预览像素。 */
static void gui_render_and_return_preview(void)
{
    static gs_ui_hint_cache_t display_hint_cache;
    gs_ui_live_status_t live;
    const gs_content_image_t *content_image = NULL;
    uint32_t elapsed, i;
    uint32_t mask = __get_PRIMASK();
    memset(&live, 0, sizeof live);
    __disable_irq(); live.recognition = s_static_snapshot; live.processing = s_static_busy; __set_PRIMASK(mask);
    live.now_ms = HAL_GetTick();
    elapsed = live.now_ms - s_rate_sample_ms;
    if (s_rate_sample_ms == 0U) {
        s_rate_sample_ms = live.now_ms;
        s_rate_camera_frames = g_gs_diag.camera_frames;
        s_rate_vision_frames = g_gs_diag.vision_frames;
    } else if (elapsed >= 1000U) {
        s_camera_fps_milli = (uint32_t)(((uint64_t)(g_gs_diag.camera_frames -
            s_rate_camera_frames) * 1000000U) / elapsed);
        s_vision_fps_milli = (uint32_t)(((uint64_t)(g_gs_diag.vision_frames -
            s_rate_vision_frames) * 1000000U) / elapsed);
        s_rate_sample_ms = live.now_ms;
        s_rate_camera_frames = g_gs_diag.camera_frames;
        s_rate_vision_frames = g_gs_diag.vision_frames;
    }
    gs_static_expire(&live.recognition, live.now_ms);
    if (s_camera_fault_seen && live.now_ms - s_camera_fault_ms <= GS_STATIC_RESULT_TTL_MS &&
        (live.recognition.frame_id == 0U ||
        s_camera_fault_ms - live.recognition.capture_ms < 0x80000000UL)) {
        live.recognition.status = GS_STATIC_CAMERA_ERROR;
        live.recognition.confidence_permille = live.recognition.margin_permille = 0U;
    }
    live.camera_frames = g_gs_diag.camera_frames; live.camera_drops = g_gs_diag.camera_drops;
    live.camera_errors = g_gs_diag.camera_errors;
    live.healthy = g_gs_diag.healthy; live.seven_class_ready = s_model_ready;
    live.control_enabled = GS_RECOGNITION_REQUESTED && GS_UNKNOWN_NEUTRAL_REARM && s_model_ready != 0U &&
        s_recognition_enabled != 0U;
    /* Display-only: RUNNING retains a fresh completed target; a newly
       completed non-target/uncertain result or 300 ms expiry clears it. */
    gs_ui_hint_update(&display_hint_cache, &live.recognition, live.now_ms,
        live.control_enabled, &live);
    live.business_validated = GS_MODEL_VALIDATED_FOR_BUSINESS;
    live.gesture_state = g_gs_diag.gesture_state;
    live.gesture_progress = g_gs_diag.gesture_progress;
    live.vision_frames = g_gs_diag.vision_frames;
    live.vision_age_ms = g_gs_diag.vision_age_ms;
    live.camera_fps_milli = s_camera_fps_milli;
    live.vision_fps_milli = s_vision_fps_milli;
    live.quality_rejects = g_gs_diag.quality_rejects;
    live.preview_drops = g_gs_diag.preview_drops;
    live.inference_errors = g_gs_static_diag.errors;
    live.inference_timeouts = g_gs_static_diag.timeouts;
    live.max_inference_ms = g_gs_static_diag.max_inference_ms;
    live.heap_free_bytes = g_gs_diag.heap_free_bytes;
    live.heap_min_free_bytes = g_gs_diag.heap_min_free_bytes;
    for (i = 0U; i < GS_TASK_COUNT; ++i) {
        uint32_t free_bytes = g_gs_diag.stack_free_bytes[i];
        if (free_bytes != 0U && (live.stack_min_free_bytes == 0U ||
            free_bytes < live.stack_min_free_bytes)) {
            live.stack_min_free_bytes = free_bytes;
        }
    }
    live.content_checked = g_gs_content.checked;
    live.content_total = g_gs_content_builtin_package.image_count;
    live.content_errors = g_gs_content.errors;
    live.content_version = g_gs_content_builtin_package.version;
    if (s_ui.mode == GS_UI_READER && s_ui.selected < s_content_collection_count) {
        content_image = gs_content_find_image(&g_gs_content, s_ui.selected, s_ui.page);
    }
    if (content_image != NULL) {
        live.content_rgb565_be = content_image->rgb565_be;
        live.content_image_bytes = content_image->bytes;
        live.content_image_width = content_image->width;
        live.content_image_height = content_image->height;
    }
    gs_port_gui_set_status(&live);
    gs_preview_frame_t preview;
    if (osMessageQueueGet(s_previews, &preview, NULL, 0U) == osOK) {
        g_gs_diag.display_status = (uint32_t)gs_port_gui_render(&s_ui, &preview);
        if (osMessageQueuePut(s_preview_returns, &preview.ticket, 0U, 0U) != osOK) {
            gs_app_fatal(GS_FATAL_PREVIEW_RETURN_QUEUE);
        }
    } else {
        g_gs_diag.display_status = (uint32_t)gs_port_gui_render(&s_ui, NULL);
    }
}

/* 界面任务：本地操作、手势命令、自动翻页依次执行，再发布代际和绘制。 */
static void gui_task(void *argument)
{
    gs_ui_action_t local;
    gs_ui_command_t command;
    (void)argument;
    for (;;) {
        uint32_t now = HAL_GetTick();
        bool recognition_before = s_ui.recognition_enabled;
#if GS_ENABLE_DEBUG_INPUT
        int32_t action = g_gs_debug_action;
        if (action >= 0 && action <= (int32_t)GS_UI_HOME) {
            g_gs_debug_action = -1;
            (void)gs_ui_local_action(&s_ui, (gs_ui_action_t)action, now);
        }
#endif
        if (osMessageQueueGet(s_local_actions, &local, NULL, 0U) == osOK) {
            (void)gs_ui_local_action(&s_ui, local, now);
        }
        if (osMessageQueueGet(s_gesture_commands, &command, NULL, 0U) == osOK) {
            gs_ui_result_t status = gs_ui_execute(&s_ui, &command, now);
            if (status == GS_UI_REJECTED_STALE) {
                ++g_gs_diag.stale_commands;
                signal_gesture(GS_FLAG_REQUIRE_CLEAR);
            }
        }
        (void)gs_ui_tick(&s_ui, now);
        if (recognition_before != s_ui.recognition_enabled) {
            s_recognition_enabled = s_ui.recognition_enabled ? 1U : 0U;
            g_gs_diag.recognition_enabled = s_recognition_enabled;
            signal_gesture(GS_FLAG_INPUT_FAULT);
        }
        g_gs_diag.gui_generation = s_ui.generation;
        s_ui_generation = s_ui.generation;
        g_gs_diag.gui_mode = (uint32_t)s_ui.mode;
        g_gs_diag.gui_page = s_ui.page;
        g_gs_diag.gui_selected = s_ui.selected;
        g_gs_diag.gui_playing = s_ui.playing;
        gui_render_and_return_preview();
        heartbeat(GS_TASK_GUI);
        delay_ms(GS_GUI_PERIOD_MS);
    }
}

/* 存储任务：以有界步骤服务存储端口，避免阻塞其他处理链路。 */
static void storage_task(void *argument)
{
    (void)argument;
    for (;;) {
        gs_content_step(&g_gs_content, 1024U);
        g_gs_diag.content_checked = g_gs_content.checked;
        g_gs_diag.content_errors = g_gs_content.errors;
        g_gs_diag.storage_status = (uint32_t)gs_port_storage_step();
        heartbeat(GS_TASK_STORAGE);
        delay_ms(GS_STORAGE_PERIOD_MS);
    }
}

/* 健康任务：确认每个任务已运行且心跳未超时，再刷新看门狗。 */
static void health_task(void *argument)
{
    (void)argument;
    for (;;) {
        uint32_t now, times[GS_TASK_COUNT], seen_mask = 0U;
        bool healthy = true;
        heartbeat(GS_TASK_HEALTH);
        /* A higher priority heartbeat after a previously sampled 'now' would
         * make unsigned age wrap to ~UINT32_MAX. Snapshot clock and timestamps
         * together; all RTOS task heartbeats are excluded for these six reads. */
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        now = HAL_GetTick();
        for (uint32_t i = 0; i < GS_TASK_COUNT; ++i) {
            times[i] = g_gs_diag.heartbeat[i];
            if (s_heartbeat_seen[i]) { seen_mask |= 1UL << i; }
        }
        __set_PRIMASK(mask);
        for (uint32_t i = 0; i < GS_TASK_COUNT; ++i) {
            if ((seen_mask & (1UL << i)) == 0U) {
                healthy = false;
            }
            if ((seen_mask & (1UL << i)) != 0U &&
                now - times[i] > GS_HEALTH_DEADLINE_MS) {
                healthy = false;
            }
            g_gs_diag.stack_free_bytes[i] = osThreadGetStackSpace(s_threads[i]);
        }
        g_gs_diag.heartbeat_seen_mask = seen_mask;
        g_gs_diag.heap_free_bytes = (uint32_t)xPortGetFreeHeapSize();
        g_gs_diag.heap_min_free_bytes = (uint32_t)xPortGetMinimumEverFreeHeapSize();
        g_gs_diag.healthy = healthy ? 1U : 0U;
        if (healthy) {
            gs_port_watchdog_refresh();
        }
        delay_ms(GS_HEALTH_PERIOD_MS);
    }
}

/* Running bootstrap initializes BSP/modules/queues before publishing task handles. */
void gs_app_init(void)
{
    static const osThreadFunc_t functions[GS_TASK_COUNT] = {
        camera_task, vision_task, gesture_task, gui_task, storage_task, health_task
    };
    static const osThreadAttr_t attributes[GS_TASK_COUNT] = {
        {.name = "CameraTask", .stack_size = 1536U, .priority = osPriorityAboveNormal},
        {.name = "VisionTask", .stack_size = 4096U, .priority = osPriorityNormal},
        {.name = "GestureTask", .stack_size = 1536U, .priority = osPriorityAboveNormal},
        {.name = "GuiTask", .stack_size = 3072U, .priority = osPriorityNormal},
        /* USB frame CRC and 4 KiB transfers must make progress while Vision is
         * runnable. Whole-layer Cube.AI yields cannot feed a lower-priority
         * sender reliably; equal-priority time slicing preserves both tasks.
         * Storage still blocks for 2 ms on every step. */
        {.name = "StorageTask", .stack_size = 1536U, .priority = osPriorityNormal},
        {.name = "HealthTask", .stack_size = 1024U, .priority = osPriorityLow}
    };
    if (osKernelGetState() != osKernelRunning) {
        gs_app_fatal(GS_FATAL_INIT_CONTEXT);
    }
    gs_port_init();
    gs_timing_trace_init();
    if (!gs_content_init(&g_gs_content, &g_gs_content_builtin_package) ||
        !prepare_runtime_collections() ||
        !gs_gesture_init(&s_gesture, NULL) ||
        !gs_ui_init(&s_ui, s_runtime_collections, s_runtime_collection_count, GS_AUTOPLAY_MS) ||
        gs_preview_pool_init(&s_preview_pool,
            s_preview_storage[0], sizeof(s_preview_storage[0]),
            s_preview_storage[1], sizeof(s_preview_storage[1])) != GS_PREVIEW_OK) {
        gs_app_fatal(GS_FATAL_MODULE_INIT);
    }
    s_recognition_enabled = s_ui.recognition_enabled ? 1U : 0U;
    g_gs_diag.recognition_enabled = s_recognition_enabled;
    g_gs_diag.gui_generation = s_ui.generation;
    s_ui_generation = s_ui.generation;
    s_camera_frames = osMessageQueueNew(GS_FRAME_QUEUE_DEPTH, sizeof(gs_port_frame_t), NULL);
    s_camera_returns = osMessageQueueNew(GS_RETURN_QUEUE_DEPTH, sizeof(gs_port_frame_t), NULL);
    s_gesture_observations = osMessageQueueNew(
        GS_OBSERVATION_QUEUE_DEPTH, sizeof(gs_gesture_envelope_t), NULL);
    s_gesture_commands = osMessageQueueNew(
        GS_COMMAND_QUEUE_DEPTH, sizeof(gs_ui_command_t), NULL);
    s_local_actions = osMessageQueueNew(GS_LOCAL_INPUT_QUEUE_DEPTH, sizeof(gs_ui_action_t), NULL);
    s_previews = osMessageQueueNew(GS_PREVIEW_QUEUE_DEPTH, sizeof(gs_preview_frame_t), NULL);
    s_preview_returns = osMessageQueueNew(GS_PREVIEW_RETURN_QUEUE_DEPTH,
                                          sizeof(gs_preview_ticket_t), NULL);
    if (!s_camera_frames || !s_camera_returns || !s_gesture_observations ||
        !s_gesture_commands || !s_local_actions || !s_previews || !s_preview_returns) {
        gs_app_fatal(GS_FATAL_QUEUE_INIT);
    }
    /* Scheduler lock keeps an early CameraTask from signalling a not-yet-created
     * GestureTask. It does not mask TIM6 IRQs; BSP delays are outside this gate.
     * This bootstrap supports only a previously unlocked scheduler (return 0). */
    if (osKernelLock() != 0) {
        gs_app_fatal(GS_FATAL_TASK_START_GATE);
    }
    for (uint32_t i = 0; i < GS_TASK_COUNT; ++i) {
        s_threads[i] = osThreadNew(functions[i], NULL, &attributes[i]);
        if (s_threads[i] == NULL) {
            gs_app_fatal(GS_FATAL_THREAD_INIT_BASE + i);
        }
    }
    if (osKernelRestoreLock(0) != 0) {
        gs_app_fatal(GS_FATAL_TASK_START_GATE);
    }
}
