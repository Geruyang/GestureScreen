#ifndef GS_APP_H
#define GS_APP_H
#include <stdbool.h>
#include <stdint.h>
#include "gs_gesture.h"
#include "gs_static_recognition.h"

typedef enum {
    GS_TASK_CAMERA = 0,
    GS_TASK_VISION,
    GS_TASK_GESTURE,
    GS_TASK_GUI,
    GS_TASK_STORAGE,
    GS_TASK_HEALTH,
    GS_TASK_COUNT
} gs_task_id_t;

/* 保留既有故障码，便于用调试器解读 g_gs_diag.fatal_code。 */
typedef enum {
    GS_FATAL_MODULE_INIT = 1U,          /* 业务模块或预览池初始化失败。 */
    GS_FATAL_QUEUE_INIT = 2U,           /* RTOS 队列创建失败。 */
    GS_FATAL_THREAD_INIT_BASE = 3U,     /* 此值加任务编号：对应任务创建失败。 */
    GS_FATAL_GESTURE_SIGNAL = 0x10U,    /* 手势任务通知失败。 */
    GS_FATAL_CAMERA_RETURN = 0x11U,     /* 相机租约无法投递归还。 */
    GS_FATAL_PREVIEW_RETURN = 0x12U,    /* GUI 归还的预览租约不匹配。 */
    GS_FATAL_PREVIEW_ROLLBACK = 0x13U,  /* 预览投递失败后的槽回收失败。 */
    GS_FATAL_PREVIEW_RETURN_QUEUE = 0x14U, /* 预览租约归还队列异常满。 */
    GS_FATAL_INIT_CONTEXT = 0x23U,       /* 初始化必须由运行中的启动任务调用。 */
    GS_FATAL_TASK_START_GATE = 0x24U     /* 任务创建阶段调度锁/恢复失败。 */
} gs_app_fatal_code_t;

/* 调试器诊断信息：各对齐字段分别是瞬时快照，整组字段不保证来自同一时刻。 */
typedef struct {
    uint32_t heartbeat[GS_TASK_COUNT];
    uint32_t heartbeat_seen_mask;
    uint32_t stack_free_bytes[GS_TASK_COUNT];
    uint32_t heap_free_bytes;
    uint32_t heap_min_free_bytes;
    uint32_t camera_frames;
    uint32_t camera_drops;
    uint32_t camera_errors;
    uint32_t vision_frames;
    uint32_t inference_ms;
    uint32_t vision_age_ms;
    uint32_t quality_rejects;
    uint32_t preview_frames;
    uint32_t preview_drops;
    uint32_t model_status;
    uint32_t model_ready;
    uint32_t observation_drops;
    uint32_t command_drops;
    uint32_t stale_commands;
    uint32_t gui_generation;
    uint32_t gui_mode;
    uint32_t gui_page;
    uint32_t gui_selected;
    uint32_t gui_playing;
    uint32_t gesture_state;
    uint32_t gesture_progress;
    uint32_t display_status;
    uint32_t storage_status;
    uint32_t recognition_enabled;
    uint32_t content_checked;
    uint32_t content_errors;
    uint32_t healthy;
    uint32_t fatal_code;
} gs_app_diagnostics_t;

extern volatile gs_app_diagnostics_t g_gs_diag;
/* Unified six-class diagnostics. Consumers must bind the matching AXF because
 * the result contains the normalized score vector and changed size. */
typedef struct {
    gs_static_result_t result;
    uint32_t completed, errors, timeouts, progress_chunks, max_chunk_ms, max_inference_ms, busy, stale_inputs;
    /* Round9 callback-accounted wall time (includes scheduling), not CPU cycles.
       New diagnostic layout: consumers must bind the matching frozen AXF. */
    uint32_t current_layer, current_outputs, layer_ms[29], current_frame_id, inference_start_ms;
    /* Round12 appended after the existing 192-byte prefix. Current/recent
       inference identity, block count and measured wall-clock time away from
       Vision; includes peers/interrupts, not pure RTOS sleep or CPU cost. */
    uint32_t profile_frame_id, yield_count, yield_wait_ms;
    /* Round12b: task-switch-accounted DWT cycles, with ISR attribution.
       Current layer data belong to profile_frame_id; terminal fields remain
       bound to the most recently finished/aborted inference. Read non-atomically.
       CYCCNT wrap is subtracted unsigned per switch (<25.6s at 168MHz).
       Neither halt/debug timing nor disabled counters give useful measurements. */
    uint32_t cycles_available, scheduled_cycles, layer_cycles[29];
    uint32_t terminal_cycle_frame_id, terminal_scheduled_cycles;
} gs_static_diagnostics_t;
extern volatile gs_static_diagnostics_t g_gs_static_diag;
/* Frames returned before preprocessing because capture age plus the fixed
 * remaining-work budget would exceed the unchanged terminal-age contract. */
extern volatile uint32_t g_gs_deadline_admission_drops;
/* Subset of the total above rejected after successful preprocessing and raw
 * lease return, before model start or any result/observation publication. */
extern volatile uint32_t g_gs_preprocess_admission_drops;
/* -1 表示空闲；调试器写入 0..4 可注入一次本地界面操作，不代表 AI 识别结果。 */
extern volatile int32_t g_gs_debug_action;

/* 由调度器已启动、未锁定的 bootstrap/defaultTask 调用一次。
 * BSP/模块/全部队列先就绪，再保护六任务句柄的统一发布。 */
void gs_app_init(void);
/* 供触摸/按键适配层调用；非阻塞投递，也可在允许调用 RTOS 接口的 ISR 中使用。 */
bool gs_app_post_action(gs_ui_action_t action);
void gs_app_fatal(uint32_t code);
#endif
