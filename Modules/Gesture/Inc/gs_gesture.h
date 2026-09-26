#ifndef GS_GESTURE_H
#define GS_GESTURE_H

#include <stdbool.h>
#include <stdint.h>

/* 项目六类标签的固定顺序；公开的五类基线模型与此接口不兼容。 */
typedef enum {
    GS_CLASS_POINT_LEFT = 0,
    GS_CLASS_POINT_RIGHT,
    GS_CLASS_FIST,
    GS_CLASS_PALM,
    GS_CLASS_V_SIGN,
    GS_CLASS_UNKNOWN,
    GS_CLASS_COUNT
} gs_gesture_class_t;

typedef enum {
    GS_UI_PREVIOUS = 0,
    GS_UI_NEXT,
    GS_UI_ENTER,
    GS_UI_UP,
    GS_UI_HOME
} gs_ui_action_t;

typedef struct {
    gs_ui_action_t action;
    uint32_t sequence;      /* 命令序号，用于拒绝重放；0 保留为无效值。 */
    uint32_t ui_generation; /* 候选手势开始时的界面代际，提交时必须仍匹配。 */
} gs_ui_command_t;

typedef struct {
    uint32_t frame_id;
    uint32_t capture_ms;
    /* 来自六类模型的归一化分数，不能传入原始 logits。 */
    float scores[GS_CLASS_COUNT];
    /* 相机、图像质量或模型契约检查失败时置为 false。 */
    bool valid;
} gs_gesture_observation_t;

typedef struct {
    uint32_t candidate_ms;     /* 连续持势最短时间。 */
    uint32_t clear_ms;         /* 连续 UNKNOWN 中性区间最短时间。 */
    uint32_t max_gap_ms;       /* 最大连续帧/接收间隔，超出即报停帧故障。 */
    uint32_t max_age_ms;       /* 从采集到处理允许的最大帧年龄。 */
    uint16_t candidate_frames; /* 持势同时需要满足的最少帧数。 */
    uint16_t clear_frames;     /* 中性区间同时需要满足的最少帧数。 */
    float target_score;        /* 目标类别的最低分数。 */
    float target_margin;       /* 第一名与第二名分数的最小差值。 */
    float neutral_score;       /* UNKNOWN 的最低分数；不证明画面无人手。 */
} gs_gesture_config_t;

typedef enum {
    GS_GESTURE_DISABLED = 0, /* 关闭或故障后等待新的有效帧。 */
    GS_GESTURE_WAIT_CLEAR,   /* 累计 UNKNOWN 中性证据，防止同一手势重复触发。 */
    GS_GESTURE_READY,        /* 中性证据满足，允许开始下一次手势。 */
    GS_GESTURE_CANDIDATE     /* 累计同类持势证据，满足时间和帧数后发命令。 */
} gs_gesture_state_t;

typedef struct {
    gs_gesture_config_t config;
    gs_gesture_state_t state;
    gs_gesture_class_t candidate;
    uint32_t evidence_start_ms;
    uint32_t evidence_last_ms;
    uint32_t candidate_generation;
    uint32_t last_frame_id;
    uint32_t last_capture_ms;
    uint32_t last_receive_ms;
    uint32_t next_sequence;
    uint32_t fault_count;
    uint32_t duplicate_count;
    uint16_t evidence_frames;
    bool enabled;
    bool initialized;
    bool have_frame;
    bool gap_fault_latched;
} gs_gesture_t;

gs_gesture_config_t gs_gesture_default_config(void);
bool gs_gesture_init(gs_gesture_t *gesture,
                     const gs_gesture_config_t *config);
void gs_gesture_set_enabled(gs_gesture_t *gesture, bool enabled);
/* 相机故障即使没有产生推理结果，也必须向状态机报告。 */
void gs_gesture_report_fault(gs_gesture_t *gesture);
/* 命令过期或投递丢失后，由手势所属任务调用；GUI 通过任务通知提出请求。 */
void gs_gesture_require_clear(gs_gesture_t *gesture);
/* 必须周期调用，即使相机或推理流水线已经停止，仍需检测停帧故障。 */
void gs_gesture_tick(gs_gesture_t *gesture, uint32_t now_ms,
                     uint32_t ui_generation);
/* 每次手势被接受时只返回一次 true。命令入队失败也必须重新取得 UNKNOWN 证据；
 * 不能回滚状态机或换新序号重试同一手势。帧号和采集时间必须前进，
 * 支持无符号 32 位回绕；所有时钟使用统一毫秒时基，间隔小于 2^31 ms。
 * 状态机由单个任务独占，其他任务的命令和故障通知必须串行处理。 */
bool gs_gesture_process(gs_gesture_t *gesture,
                        const gs_gesture_observation_t *observation,
                        uint32_t now_ms, uint32_t ui_generation,
                        gs_ui_command_t *command);
/* 进度为 0..1000，仅根据接受的新鲜帧计算，不能由 GUI 刷新时间推动。 */
uint16_t gs_gesture_progress(const gs_gesture_t *gesture);

#endif
