/* Runs the actual C bootstrap/app code with a deterministic scheduler/port model.
 * No ARM instructions, target peripherals, USB APIs or probe access occur here. */
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "gs_port.h"
#include "cmsis_os2.h"
#include "main.h"

/* Including production files allows publication invariants to inspect their
 * private handles without adding test hooks to the firmware. */
#include "../App/Src/gs_app.c"
#include "../Core/Src/freertos.c"

typedef struct {
    osThreadFunc_t function;
    void *argument;
    const osThreadAttr_t *attr;
} mock_thread_t;
static mock_thread_t threads[7];
static uint32_t queues[7], thread_count, queue_count;
static uint32_t basepri, nesting, primask, tick, port_calls, task_runs;
static uint32_t lock_calls, restore_calls, signal_calls, usb_calls, usb_starts, bootstrap_exits;
static uint32_t queue_fail, task_fail, watchdog_feeds;
static int default_fail, module_fail, lock_failure, restore_failure, usb_initialized;
static osKernelState_t kernel;
static mock_thread_t *current;
static jmp_buf scenario_jump, task_jump;
static gs_ui_live_status_t observed_live;
static uint32_t tick_step, allow_delay_return, injected_frame_pending, camera_returns, observation_puts, command_puts;
static uint32_t late_completion_deadline;
static uint32_t delay_extra_ms;
gs_mock_dwt_t gs_mock_dwt;
gs_mock_core_debug_t gs_mock_core_debug;
static uint32_t mock_cycle_step;
static gs_port_frame_t injected_frame;
static gs_gesture_observation_t observed_observation;
static const gs_ui_page_t mock_content_pages[] = {{"PAGE", "BODY"}};
static const gs_ui_collection_t mock_content_collections[] = {
    {"CONTENT", 1U, mock_content_pages, GS_UI_COLLECTION_CONTENT}
};
const gs_content_package_t g_gs_content_builtin_package = {
    "mock-content", mock_content_collections, 1U, 0U, NULL
};
gs_content_context_t g_gs_content;
/* Stateful preview transport for the Camera/GUI regression. Default startup
 * scenarios remain empty and keep the original injected camera fault. */
static gs_preview_frame_t queued_preview, consumed_preview;
static gs_preview_ticket_t queued_preview_return;
static uint32_t preview_queued, preview_return_queued, preview_put_failure;
static uint32_t camera_poll_pending, camera_queue_blocked, raw_releases, camera_puts;
static uint32_t camera_frame_queued;
static gs_port_frame_t queued_camera_frame;
enum { TRAP_FATAL = 1, TRAP_BLOCKED_TICK = 2 };

static void reset_model(void)
{
    memset(threads, 0, sizeof threads); memset(queues, 0, sizeof queues);
    memset((void *)&g_gs_diag, 0, sizeof g_gs_diag);
    memset((void *)s_heartbeat_seen, 0, sizeof s_heartbeat_seen);
    memset(s_threads, 0, sizeof s_threads);
    g_gs_bootstrap_stack_free_bytes = 0;
    memset((void *)&g_gs_static_diag, 0, sizeof g_gs_static_diag);
    g_gs_deadline_admission_drops = 0U;
    g_gs_preprocess_admission_drops = 0U;
    memset((void *)&g_gs_preview_diag, 0, sizeof g_gs_preview_diag);
    preview_queued = preview_return_queued = preview_put_failure = 0;
    camera_poll_pending = camera_queue_blocked = raw_releases = camera_puts = 0;
    camera_frame_queued = 0; memset(&queued_camera_frame, 0, sizeof queued_camera_frame);
    memset(&s_static_snapshot, 0, sizeof s_static_snapshot);
    s_static_busy = s_camera_fault_seen = s_camera_fault_ms = 0;
    s_recognition_enabled = 1U;
    s_rate_sample_ms = s_rate_camera_frames = s_rate_vision_frames = 0U;
    s_camera_fps_milli = s_vision_fps_milli = 0U;
    s_runtime_collection_count = s_content_collection_count = 0U;
    memset(s_runtime_collections, 0, sizeof s_runtime_collections);
    memset(&g_gs_content, 0, sizeof g_gs_content);
    tick_step = allow_delay_return = injected_frame_pending = camera_returns = observation_puts = command_puts = 0;
    late_completion_deadline = 0;
    delay_extra_ms = 0;
    memset(&gs_mock_dwt, 0, sizeof gs_mock_dwt);
    memset(&gs_mock_core_debug, 0, sizeof gs_mock_core_debug);
    s_cycle_task = NULL; s_cycle_available = s_cycle_running = s_cycle_start = s_cycle_total = 0U;
    mock_cycle_step = 0U;
    thread_count = queue_count = basepri = primask = tick = port_calls = task_runs = 0;
    lock_calls = restore_calls = signal_calls = usb_calls = usb_starts = bootstrap_exits = 0;
    queue_fail = task_fail = watchdog_feeds = 0;
    default_fail = module_fail = lock_failure = restore_failure = usb_initialized = 0;
    nesting = 0xAAAAAAAAU; kernel = osKernelReady; current = NULL;
}
uint32_t gs_mock_cycle_read(void)
{
    uint32_t result = gs_mock_dwt.CYCCNT;
    if (gs_mock_dwt.CTRL & DWT_CTRL_CYCCNTENA_Msk) { gs_mock_dwt.CYCCNT += mock_cycle_step; }
    return result;
}
static void enter_critical(void) { basepri = 0x50U; ++nesting; }
static void exit_critical(void) { assert(nesting); if (--nesting == 0) basepri = 0; }
uint32_t HAL_GetTick(void)
{
    if (late_completion_deadline && g_gs_static_diag.progress_chunks >= 29U) {
        /* All 29 generated-layer callbacks ran below budget; terminal work crosses it. */
        tick += 1000U; late_completion_deadline = 0;
    }
    uint32_t now = tick; tick += tick_step; return now;
}
void HAL_Delay(uint32_t delay)
{
    if (basepri || primask) longjmp(scenario_jump, TRAP_BLOCKED_TICK);
    tick += delay; /* Model TIM6 being able to deliver ticks, not hardware timing. */
}
uint32_t __get_PRIMASK(void) { return primask; }
void __set_PRIMASK(uint32_t mask) { primask = mask; }
void __disable_irq(void) { primask = 1; }
void __NOP(void) { assert(g_gs_diag.fatal_code); longjmp(scenario_jump, TRAP_FATAL); }
osKernelState_t osKernelGetState(void) { return kernel; }
uint32_t osKernelGetTickFreq(void) { return 1000; }
int32_t osKernelLock(void)
{
    ++lock_calls;
    assert(kernel == osKernelRunning && basepri == 0 && port_calls == 1 && queue_count == 7);
    if (lock_failure) return lock_failure;
    kernel = osKernelLocked; return 0;
}
static void run_task(mock_thread_t *thread)
{
    mock_thread_t *saved = current;
    assert(kernel == osKernelRunning && thread_count == 7 && queue_count == 7);
    for (uint32_t i = 0; i < GS_TASK_COUNT; ++i) assert(s_threads[i] == &threads[i + 1]);
    assert(s_camera_frames && s_camera_returns && s_gesture_observations && s_gesture_commands);
    assert(s_local_actions && s_previews && s_preview_returns);
    ++task_runs; current = thread;
    if (setjmp(task_jump) == 0) thread->function(thread->argument);
    current = saved;
}
int32_t osKernelRestoreLock(int32_t lock)
{
    ++restore_calls; assert(lock == 0 && kernel == osKernelLocked);
    if (restore_failure) return -1;
    kernel = osKernelRunning;
    /* Try all actual task entry points immediately on publication. Camera's
     * injected fault proves GestureTask is already addressable at this point. */
    for (uint32_t i = 1; i < thread_count; ++i) run_task(&threads[i]);
    return 0;
}
osThreadId_t osThreadNew(osThreadFunc_t function, void *argument, const osThreadAttr_t *attr)
{
    assert(attr && function);
    if (kernel == osKernelReady) {
        assert(thread_count == 0 && function == StartDefaultTask && attr->stack_size == 1024);
        if (default_fail) return NULL;
    } else {
        assert(kernel == osKernelLocked && queue_count == 7 && port_calls == 1);
        if (task_fail == thread_count) return NULL;
    }
    enter_critical();
    mock_thread_t *thread = &threads[thread_count++];
    thread->function = function; thread->argument = argument; thread->attr = attr;
    exit_critical();
    /* A running, unlocked scheduler would try immediate higher-priority
     * preemption here; the assert above rejects that unsafe creation phase. */
    assert(kernel != osKernelRunning);
    return thread;
}
osThreadId_t osThreadGetId(void) { return current; }
uint32_t osThreadGetStackSpace(osThreadId_t thread)
{
    assert(thread);
    for (uint32_t i = 0; i < thread_count; ++i) if (thread == &threads[i]) return 640;
    assert(0); return 0;
}
void osThreadExit(void) { assert(current == &threads[0]); ++bootstrap_exits; }
uint32_t osThreadFlagsSet(osThreadId_t thread, uint32_t flags)
{
    assert(thread == &threads[GS_TASK_GESTURE + 1] && flags == GS_FLAG_INPUT_FAULT);
    ++signal_calls; return flags;
}
uint32_t osThreadFlagsWait(uint32_t flags, uint32_t options, uint32_t timeout)
{ (void)flags; (void)options; (void)timeout; return osFlagsError; }
osStatus_t osDelay(uint32_t ticks)
{
    assert(current && current != &threads[0] && ticks && basepri == 0 && primask == 0);
    tick += ticks + delay_extra_ms; if (allow_delay_return) { return osOK; } longjmp(task_jump, 1);
}
osMessageQueueId_t osMessageQueueNew(uint32_t count, uint32_t size, const void *attr)
{
    (void)attr; assert(kernel == osKernelRunning && count && size && queue_count < 7);
    uint32_t index = ++queue_count;
    if (queue_fail == index) return NULL;
    enter_critical(); exit_critical(); return &queues[index - 1];
}
osStatus_t osMessageQueueGet(osMessageQueueId_t queue, void *message, uint8_t *priority, uint32_t timeout)
{
    (void)priority; (void)timeout; assert(queue);
    if (queue == s_previews && preview_queued) {
        memcpy(message, &queued_preview, sizeof queued_preview); preview_queued = 0; return osOK;
    }
    if (queue == s_preview_returns && preview_return_queued) {
        memcpy(message, &queued_preview_return, sizeof queued_preview_return); preview_return_queued = 0; return osOK;
    }
    if (queue == s_camera_frames && injected_frame_pending) {
        memcpy(message, &injected_frame, sizeof injected_frame); injected_frame_pending = 0; return osOK;
    }
    if (queue == s_camera_frames && camera_frame_queued) {
        memcpy(message, &queued_camera_frame, sizeof queued_camera_frame);
        camera_frame_queued = 0; return osOK;
    }
    return osErrorResource;
}
osStatus_t osMessageQueuePut(osMessageQueueId_t queue, const void *message, uint8_t priority, uint32_t timeout)
{
    (void)priority; (void)timeout; assert(queue);
    if (queue == s_previews) {
        if (preview_queued || preview_put_failure) return osErrorResource;
        memcpy(&queued_preview, message, sizeof queued_preview); preview_queued = 1;
    }
    if (queue == s_preview_returns) {
        assert(!preview_return_queued);
        memcpy(&queued_preview_return, message, sizeof queued_preview_return); preview_return_queued = 1;
    }
    if (queue == s_camera_frames) {
        ++camera_puts;
        if (camera_queue_blocked || camera_frame_queued) return osErrorResource;
        memcpy(&queued_camera_frame, message, sizeof queued_camera_frame);
        camera_frame_queued = 1;
    }
    if (queue == s_camera_returns) { ++camera_returns; }
    if (queue == s_gesture_observations) { ++observation_puts; memcpy(&observed_observation, message, sizeof observed_observation); }
    if (queue == s_gesture_commands) { ++command_puts; }
    return osOK;
}
osStatus_t osMessageQueueReset(osMessageQueueId_t queue) { assert(queue); return osOK; }
uint32_t osMessageQueueGetCount(osMessageQueueId_t queue)
{
    assert(queue);
    if (queue == s_gesture_observations) { return 0U; }
    return 0U;
}
size_t xPortGetFreeHeapSize(void) { return 2048; }
size_t xPortGetMinimumEverFreeHeapSize(void) { return 2048; }

void gs_port_init(void) { ++port_calls; HAL_Delay(5); assert(kernel == osKernelRunning); }
gs_port_status_t gs_port_camera_poll(gs_port_frame_t *frame)
{
    if (camera_poll_pending) { *frame = injected_frame; camera_poll_pending = 0; return GS_PORT_OK; }
    return GS_PORT_ERROR;
}
void gs_port_camera_release(const gs_port_frame_t *frame) { (void)frame; ++raw_releases; }
gs_port_status_t gs_port_gui_render(const gs_ui_t *ui, const gs_preview_frame_t *preview)
{ if (preview) consumed_preview = *preview; assert(ui->initialized); return GS_PORT_OK; }
void gs_port_gui_set_status(const gs_ui_live_status_t *status) { observed_live = *status; }
void MX_USB_DEVICE_Init(void)
{ ++usb_calls; if (!usb_initialized || usb_starts) return; ++usb_starts; }
gs_port_status_t gs_port_storage_step(void)
{
    assert(current == &threads[GS_TASK_STORAGE + 1]);
    usb_initialized = 1; MX_USB_DEVICE_Init(); return GS_PORT_OK;
}
const gs_ai_backend_t *gs_port_model_backend(void) { return NULL; }
void gs_port_watchdog_refresh(void) { ++watchdog_feeds; }
bool gs_content_init(gs_content_context_t *context, const gs_content_package_t *package)
{
    if (context == NULL || package == NULL) { return false; }
    memset(context, 0, sizeof *context); context->package = package; return true;
}
void gs_content_step(gs_content_context_t *context, uint32_t byte_budget)
{ assert(context == &g_gs_content && byte_budget == 1024U); }
const gs_content_image_t *gs_content_find_image(const gs_content_context_t *context,
    uint16_t collection, uint16_t page)
{ (void)context; (void)collection; (void)page; return NULL; }
#if defined(GS_STATIC_TEST_BACKEND) && GS_STATIC_TEST_BACKEND
gs_ai_status_t gs_static_test_execute(const int8_t *input, size_t count,
    int8_t *output, size_t output_count, float *output_scale,
    int32_t *output_zero_point, gs_int8_progress_fn progress, void *context)
{
    static const int8_t logits[GS_STATIC_CLASS_COUNT] = {-80, -70, -60, 90, -50, -40};
    uint32_t layer;
    if (input == NULL || output == NULL || output_scale == NULL || output_zero_point == NULL ||
        count != GS_AI_INPUT_SIZE || output_count != GS_STATIC_CLASS_COUNT) {
        return GS_AI_INVALID_ARGUMENT;
    }
    for (layer = 0U; layer < 29U; ++layer) {
        uint32_t outputs = layer == 28U ? GS_STATIC_CLASS_COUNT : 64U;
        if (progress != NULL && !progress(context, layer, outputs)) {
            return GS_AI_BACKEND_FAILURE;
        }
    }
    memcpy(output, logits, sizeof logits);
    *output_scale = 0.08847017586231232f;
    *output_zero_point = -6;
    return GS_AI_OK;
}
#endif
#ifndef GS_TEST_REAL_PREVIEW
gs_preview_result_t gs_preview_pool_init(gs_preview_pool_t *pool, void *a, size_t ca, void *b, size_t cb)
{
    assert(a && b && ca && cb);
    pool->initialized = !module_fail; return module_fail ? GS_PREVIEW_INVALID : GS_PREVIEW_OK;
}
gs_preview_result_t gs_preview_publish(gs_preview_pool_t *pool, const int8_t *source, size_t count,
    uint32_t id, uint32_t ms, gs_preview_frame_t *frame)
{ (void)pool; (void)source; (void)count; (void)id; (void)ms; (void)frame; return GS_PREVIEW_BUSY; }
gs_preview_result_t gs_preview_publish_rgb565(gs_preview_pool_t *pool, const gs_rgb565_frame_t *source,
    uint32_t id, uint32_t ms, gs_preview_frame_t *frame)
{ (void)pool; (void)source; (void)id; (void)ms; (void)frame; return GS_PREVIEW_BUSY; }
gs_preview_result_t gs_preview_release(gs_preview_pool_t *pool, gs_preview_ticket_t ticket)
{ (void)pool; (void)ticket; return GS_PREVIEW_OK; }
#endif

static void start_scheduler(void)
{
    assert(kernel == osKernelReady && thread_count == 1 && basepri == 0x50U);
    nesting = basepri = 0; kernel = osKernelRunning; current = &threads[0];
    StartDefaultTask(NULL);
}
static void expect_bootstrap_failure(uint32_t fatal)
{
    int trap = setjmp(scenario_jump);
    if (trap == 0) { MX_FREERTOS_Init(); start_scheduler(); assert(0); }
    assert(trap == TRAP_FATAL && g_gs_diag.fatal_code == fatal);
    assert(task_runs == 0 && bootstrap_exits == 0 && g_gs_bootstrap_stack_free_bytes == 0);
}

static void test_trace_fault_reason_accounting(void)
{
    gs_gesture_t gesture;
    gs_gesture_observation_t observation;
    gs_ui_command_t command;
    gs_timing_trace_payload_t trace;
    uint32_t reason;
    unsigned i;
    assert(gs_gesture_init(&gesture, NULL));
    gs_gesture_set_enabled(&gesture, true);
    gesture.have_frame = true;
    gesture.last_frame_id = 10U;
    gesture.last_capture_ms = 0U;
    gesture.last_receive_ms = 0U;
    memset(&observation, 0, sizeof observation);
    observation.frame_id = 11U;
    observation.capture_ms = 50U;
    observation.valid = true;
    for (i = 0U; i < GS_CLASS_COUNT; ++i) { observation.scores[i] = 0.0f; }
    observation.scores[GS_CLASS_UNKNOWN] = 1.0f;
    reason = trace_reason_before_process(&gesture, &observation, 351U);
    assert((reason & GS_TIMING_OUTCOME_FAULT_GAP) != 0U);
    assert((reason & GS_TIMING_OUTCOME_FAULT_AGE) != 0U);
    memset(&trace, 0, sizeof trace);
    trace.outcome_flags = reason;
    trace.fault_count_before = gesture.fault_count;
    assert(!gs_gesture_process(&gesture, &observation, 351U, 1U, &command));
    trace_finalize_fault(&trace, gesture.fault_count);
    assert(trace.fault_count_after - trace.fault_count_before == 2U);
    assert((trace.outcome_flags & GS_TIMING_OUTCOME_FAULT) != 0U);
    assert((trace.outcome_flags & GS_TIMING_OUTCOME_FAULT_UNATTRIBUTED) == 0U);
    memset(&trace, 0, sizeof trace);
    trace.fault_count_before = 7U;
    trace_finalize_fault(&trace, 8U);
    assert((trace.outcome_flags & GS_TIMING_OUTCOME_FAULT_UNATTRIBUTED) != 0U);
}

int main(void)
{
    uint32_t scenarios = 0;
    test_trace_fault_reason_accounting();
    reset_model();
    int trap = setjmp(scenario_jump);
    if (trap == 0) {
        MX_FREERTOS_Init();
        assert(port_calls == 0 && thread_count == 1 && basepri == 0x50U && nesting == 0xAAAAAAAAU);
        /* Replay the old call location's first BSP delay before scheduler start. */
        gs_port_init(); assert(0);
    }
    assert(trap == TRAP_BLOCKED_TICK && tick == 0); ++scenarios;

    reset_model(); trap = setjmp(scenario_jump);
    if (trap == 0) { gs_app_init(); assert(0); }
    assert(trap == TRAP_FATAL && g_gs_diag.fatal_code == GS_FATAL_INIT_CONTEXT && port_calls == 0);
    ++scenarios;

    reset_model(); default_fail = 1; expect_bootstrap_failure(0x20U); ++scenarios;
    reset_model(); module_fail = 1; expect_bootstrap_failure(GS_FATAL_MODULE_INIT); ++scenarios;
    for (uint32_t i = 1; i <= 7; ++i) {
        reset_model(); queue_fail = i; expect_bootstrap_failure(GS_FATAL_QUEUE_INIT); ++scenarios;
    }
    for (uint32_t i = 1; i <= GS_TASK_COUNT; ++i) {
        reset_model(); task_fail = i;
        expect_bootstrap_failure(GS_FATAL_THREAD_INIT_BASE + i - 1); ++scenarios;
        assert(restore_calls == 0 && kernel == osKernelLocked);
    }
    reset_model(); lock_failure = -1; expect_bootstrap_failure(GS_FATAL_TASK_START_GATE); ++scenarios;
    reset_model(); lock_failure = 1; expect_bootstrap_failure(GS_FATAL_TASK_START_GATE); ++scenarios;
    reset_model(); restore_failure = 1; expect_bootstrap_failure(GS_FATAL_TASK_START_GATE); ++scenarios;

    reset_model(); trap = setjmp(scenario_jump);
    if (trap == 0) { MX_FREERTOS_Init(); start_scheduler(); }
    assert(trap == 0 && port_calls == 1 && thread_count == 7 && task_runs == 6);
    assert(lock_calls == 1 && restore_calls == 1 && nesting == 0 && basepri == 0 && tick > 5);
    assert(signal_calls == 1 && bootstrap_exits == 1 && g_gs_bootstrap_stack_free_bytes == 640);
    assert(usb_calls == 2 && usb_starts == 1 && watchdog_feeds == 1);
    assert(g_gs_diag.heartbeat_seen_mask == 0x3FU && g_gs_diag.healthy == 1 && g_gs_diag.fatal_code == 0);
    ++scenarios;
    printf("Startup regression passed: %u scenarios; actual bootstrap/app C; synthetic scheduler only\n", scenarios);
    return 0;
}
