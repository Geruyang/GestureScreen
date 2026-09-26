/* Reuse the existing scheduler/port model; directly include actual App C.
   Numeric tests separately run the actual model. No target access occurs. */
#define main startup_regression_main
#include "test_startup.c"
#undef main
static uint8_t raw_frame[320U * 240U * 2U];
int main(void)
{
    gs_static_result_t terminal = {GS_STATIC_IDENTIFIED, GS_STATIC_PALM, 7, 100, 90, 980, 960};
    gs_static_result_t next = {GS_STATIC_RUNNING, 0, 8, 220, 0, 0, 0};
    unsigned i;
    reset_model(); MX_FREERTOS_Init(); start_scheduler(); s_camera_fault_seen = 0;
    tick = 200; static_publish(&terminal); gui_render_and_return_preview();
    assert(observed_live.recognition.status == GS_STATIC_IDENTIFIED && !observed_live.processing);
    static_begin_display(&next); tick = 240; gui_render_and_return_preview();
    assert(observed_live.processing && observed_live.recognition.frame_id == 7);
    assert(observed_live.recognition.capture_ms == 100 && observed_live.recognition.class_index == GS_STATIC_PALM);
    tick = 1601; gui_render_and_return_preview();
    assert(observed_live.processing && observed_live.recognition.status == GS_STATIC_STALE && !observed_live.recognition.confidence_permille);
    next.status = GS_STATIC_INFERENCE_ERROR; static_publish(&next); gui_render_and_return_preview();
    assert(!observed_live.processing && observed_live.recognition.status == GS_STATIC_INFERENCE_ERROR && !observed_live.recognition.confidence_permille);
    tick = 260; s_camera_fault_seen = 1; s_camera_fault_ms = 230;
    terminal.capture_ms = 220; static_publish(&terminal); gui_render_and_return_preview();
    assert(observed_live.recognition.status == GS_STATIC_CAMERA_ERROR);
    terminal.capture_ms = 240; static_publish(&terminal); gui_render_and_return_preview();
    assert(observed_live.recognition.status == GS_STATIC_IDENTIFIED);
    s_camera_fault_ms = UINT32_MAX - 10U; tick = 20; terminal.capture_ms = UINT32_MAX - 20U;
    static_publish(&terminal); gui_render_and_return_preview(); assert(observed_live.recognition.status == GS_STATIC_CAMERA_ERROR);
    s_camera_fault_ms = 100; tick = 0x80000080U; terminal.capture_ms = tick - 10;
    static_publish(&terminal); gui_render_and_return_preview(); assert(observed_live.recognition.status == GS_STATIC_IDENTIFIED);
    s_camera_fault_seen = 0;
    memset(&injected_frame, 0, sizeof injected_frame);
    tick = 1000; injected_frame.capture_ms = 699; injected_frame.frame_id = 10; injected_frame_pending = 1;
    camera_returns = 0; run_task(&threads[GS_TASK_VISION + 1]);
    assert(g_gs_static_diag.stale_inputs == 1 && camera_returns == 1 && !injected_frame_pending);
    assert(g_gs_deadline_admission_drops == 0U);
    /* Admission is strictly newer than the existing >300 stale gate, uses
       unsigned tick arithmetic, and never publishes a result or input fault. */
    assert(vision_deadline_admit(900U,1000U));
    assert(!vision_deadline_admit(899U,1000U));
    assert(!vision_deadline_admit(700U,1000U));
    assert(vision_deadline_admit(UINT32_MAX-79U,20U));
    assert(!vision_deadline_admit(UINT32_MAX-80U,20U));
    s_recognition_enabled=0U; assert(vision_deadline_admit(700U,1000U));
    s_recognition_enabled=1U;
    {
        gs_static_result_t before_result=s_static_snapshot;
        uint32_t before_observations=observation_puts, before_signals=signal_calls;
        uint32_t before_frames=g_gs_diag.vision_frames;
        injected_frame.capture_ms=899U; injected_frame.frame_id=11U;
        injected_frame_pending=1; tick=1000U;
        run_task(&threads[GS_TASK_VISION + 1]);
        assert(g_gs_deadline_admission_drops==1U && camera_returns==2U);
        assert(g_gs_static_diag.stale_inputs==1U && !injected_frame_pending);
        assert(observation_puts==before_observations && signal_calls==before_signals);
        assert(g_gs_diag.vision_frames==before_frames && !s_static_busy);
        assert(memcmp(&s_static_snapshot,&before_result,sizeof before_result)==0);
        g_gs_deadline_admission_drops=UINT32_MAX;
        injected_frame.capture_ms=899U; injected_frame_pending=1;
        run_task(&threads[GS_TASK_VISION + 1]);
        assert(g_gs_deadline_admission_drops==UINT32_MAX && camera_returns==3U);
    }
    g_gs_deadline_admission_drops=0U;
    current = &threads[GS_TASK_VISION + 1]; allow_delay_return = 1;
    injected_frame.image.data = raw_frame; injected_frame.image.data_size = sizeof raw_frame;
    injected_frame.image.width = 320; injected_frame.image.height = 240; injected_frame.image.stride_bytes = 640;
    injected_frame.image.byte_order = GS_RGB565_MSB_FIRST;
    injected_frame.capture_ms = tick; memset(raw_frame, 0, sizeof raw_frame);
    vision_process_frame(&injected_frame, tick); gui_render_and_return_preview();
    assert(observed_live.recognition.status == GS_STATIC_BAD_QUALITY && !observed_live.processing);
    for (i = 0; i < sizeof raw_frame; i += 2) { raw_frame[i] = 0x84; raw_frame[i + 1] = 0x10; }
    assert(!vision_preprocess_deadline_expired(921U,1000U,GS_PREPROCESS_OK));
    assert(!vision_preprocess_deadline_expired(920U,1000U,GS_PREPROCESS_OK));
    assert(vision_preprocess_deadline_expired(919U,1000U,GS_PREPROCESS_OK));
    assert(!vision_preprocess_deadline_expired(UINT32_MAX-59U,20U,GS_PREPROCESS_OK));
    assert(vision_preprocess_deadline_expired(UINT32_MAX-60U,20U,GS_PREPROCESS_OK));
    assert(!vision_preprocess_deadline_expired(919U,1000U,GS_PREPROCESS_INVALID_ARGUMENT));
    s_recognition_enabled=0U;
    assert(!vision_preprocess_deadline_expired(919U,1000U,GS_PREPROCESS_OK));
    s_recognition_enabled=1U;
    {
        gs_static_result_t before_result=s_static_snapshot;
        uint32_t before_returns=camera_returns, before_observations=observation_puts;
        uint32_t before_signals=signal_calls, before_frames=g_gs_diag.vision_frames;
        uint32_t before_chunks=g_gs_static_diag.progress_chunks;
        injected_frame.capture_ms=tick-81U; injected_frame.frame_id=12U;
        vision_process_frame(&injected_frame,tick-81U);
        assert(camera_returns==before_returns+1U);
        assert(g_gs_deadline_admission_drops==1U &&
            g_gs_preprocess_admission_drops==1U);
        assert(observation_puts==before_observations && signal_calls==before_signals);
        assert(g_gs_diag.vision_frames==before_frames &&
            g_gs_static_diag.progress_chunks==before_chunks && !s_static_busy);
        assert(memcmp(&s_static_snapshot,&before_result,sizeof before_result)==0);
        g_gs_deadline_admission_drops=UINT32_MAX;
        g_gs_preprocess_admission_drops=UINT32_MAX;
        vision_process_frame(&injected_frame,tick-81U);
        assert(camera_returns==before_returns+2U);
        assert(g_gs_deadline_admission_drops==UINT32_MAX &&
            g_gs_preprocess_admission_drops==UINT32_MAX);
    }
    g_gs_deadline_admission_drops=1U;
    g_gs_preprocess_admission_drops=1U;
    injected_frame.capture_ms = tick; tick_step = 25;
    vision_process_frame(&injected_frame, tick); tick_step = 0; gui_render_and_return_preview();
    assert(g_gs_static_diag.timeouts == 1 && observed_live.recognition.status == GS_STATIC_TIMEOUT);
    assert(g_gs_static_diag.progress_chunks > 0 && !observed_live.processing);
    assert(observation_puts == 2 && !observed_observation.valid && !command_puts && s_model_ready);
    g_gs_static_diag.progress_chunks = 0; late_completion_deadline = 1;
    injected_frame.capture_ms = tick;
    vision_process_frame(&injected_frame, tick); gui_render_and_return_preview();
    assert(!late_completion_deadline && g_gs_static_diag.progress_chunks == 29U);
    assert(g_gs_static_diag.timeouts == 2 && !g_gs_static_diag.completed);
    assert(observed_live.recognition.status == GS_STATIC_TIMEOUT && !observed_live.recognition.confidence_permille);
    assert(g_gs_static_diag.current_layer == 28U && g_gs_static_diag.current_outputs == GS_STATIC_CLASS_COUNT);
    assert(g_gs_static_diag.current_frame_id == injected_frame.frame_id);
    injected_frame.capture_ms = tick;
    vision_process_frame(&injected_frame, tick); gui_render_and_return_preview();
    assert(g_gs_static_diag.completed == 1U && g_gs_static_diag.errors == 0U &&
        g_gs_static_diag.timeouts == 2U);
    assert(observed_live.recognition.status == GS_STATIC_IDENTIFIED && !observed_live.processing);
    assert(observed_observation.valid && observed_observation.scores[GS_STATIC_PALM] > 0.99f);
    assert(!command_puts && s_model_ready);
    {
        static_progress_t p = {tick,tick,tick,tick,UINT32_MAX,false,0U,0U,0U};
        uint32_t start=tick;
        tick=start+4U; assert(static_progress(&p,0U,64U));
        assert(g_gs_static_diag.layer_ms[0]==4U);
        tick=start+9U; assert(static_progress(&p,0U,128U));
        assert(g_gs_static_diag.layer_ms[0]==9U);
        tick=start+15U; assert(static_progress(&p,1U,64U));
        assert(g_gs_static_diag.layer_ms[1]==6U && g_gs_static_diag.current_layer==1U);
    }
    {
        assert(sizeof(gs_static_diagnostics_t)==364U);
        assert(g_gs_static_diag.profile_frame_id==injected_frame.frame_id);
        g_gs_static_diag.yield_count=g_gs_static_diag.yield_wait_ms=0;
        tick=UINT32_MAX-5U;delay_extra_ms=7;
        static_progress_t p={tick,tick,tick-11U,tick,UINT32_MAX,false,0U,0U,0U};
        assert(static_progress(&p,0,64));
        assert(g_gs_static_diag.yield_count==1U && g_gs_static_diag.yield_wait_ms==8U);
        assert(tick==2U); /* Actual ready/peer delay included, wrap-safe. */
        delay_extra_ms=0;
        assert(static_progress(&p,0,128));
        assert(g_gs_static_diag.yield_count==1U && g_gs_static_diag.yield_wait_ms==8U);
    }
    {
        void *vision=&threads[GS_TASK_VISION+1], *gui=&threads[GS_TASK_GUI+1];
        uint32_t before, start;
        gs_mock_dwt.CTRL=DWT_CTRL_NOCYCCNT_Msk; mock_cycle_step=1U;
        vision_cycle_init(vision); assert(!g_gs_static_diag.cycles_available);
        gs_mock_dwt.CTRL=0U; mock_cycle_step=0U;
        vision_cycle_init(vision); assert(!g_gs_static_diag.cycles_available); /* frozen counter */
        mock_cycle_step=1U; vision_cycle_init(vision);
        assert(g_gs_static_diag.cycles_available && (gs_mock_core_debug.DEMCR & CoreDebug_DEMCR_TRCENA_Msk));
        mock_cycle_step=0U; before=vision_cycle_snapshot();
        gs_mock_dwt.CYCCNT+=100U; assert(vision_cycle_snapshot()-before==100U);
        gs_vision_profile_switched_out(vision);
        gs_mock_dwt.CYCCNT+=900U; gs_vision_profile_switched_in(gui);
        gs_mock_dwt.CYCCNT+=700U; gs_vision_profile_switched_out(gui);
        assert(vision_cycle_snapshot()-before==100U); /* peer cycles excluded */
        gs_mock_dwt.CYCCNT=UINT32_MAX-7U; gs_vision_profile_switched_in(vision);
        gs_mock_dwt.CYCCNT=12U; gs_vision_profile_switched_out(vision);
        assert(vision_cycle_snapshot()-before==120U); /* counter wrap adds20 */
        gs_vision_profile_switched_out(vision); assert(vision_cycle_snapshot()-before==120U);
        s_cycle_total=UINT32_MAX-3U; gs_vision_profile_switched_in(vision);
        start=vision_cycle_snapshot(); gs_mock_dwt.CYCCNT+=10U;
        assert(vision_cycle_snapshot()-start==10U); /* accumulator wrap */
        before=vision_cycle_snapshot();
        static_progress_t p={tick,tick,tick,tick,UINT32_MAX,false,before,before,before};
        gs_mock_dwt.CYCCNT+=120U; assert(static_progress(&p,0U,64U));
        assert(g_gs_static_diag.scheduled_cycles==120U && g_gs_static_diag.layer_cycles[0]==120U);
        gs_vision_profile_switched_out(vision); gs_mock_dwt.CYCCNT+=10000U;
        gs_vision_profile_switched_in(vision); gs_mock_dwt.CYCCNT+=30U;
        assert(static_progress(&p,1U,64U));
        assert(g_gs_static_diag.scheduled_cycles==150U && g_gs_static_diag.layer_cycles[1]==30U);
        injected_frame.frame_id=90U; injected_frame.capture_ms=tick;
        vision_process_frame(&injected_frame, tick);
        assert(g_gs_static_diag.profile_frame_id==90U && g_gs_static_diag.terminal_cycle_frame_id==90U);
        assert(!g_gs_static_diag.terminal_scheduled_cycles); /* no artificial CPU progress */
        g_gs_static_diag.terminal_scheduled_cycles=12345U;
        static_begin_display(&next);
        assert(g_gs_static_diag.terminal_cycle_frame_id==90U && g_gs_static_diag.terminal_scheduled_cycles==12345U);
        puts("PASS: task-attributed cycles exclude peers, retain ISR attribution, counter/accumulator wrap, unavailable fallback, actual App profile/terminal identity.");
    }
    puts("PASS: App single six-class inference feeds UI and business observation, with expiry, camera cutoff, lease, quality and timeout guards; no target access.");
    return 0;
}
