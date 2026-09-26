/* 手势状态机：有效输入 → UNKNOWN 中性区间 → 就绪 → 持势 → 发出一次命令 → 再次中性区间。
 * 时间和帧数必须同时达标；故障、超龄与界面代际变化会使已有证据失效。 */
#include "gs_gesture.h"

#include <stddef.h>
#include <string.h>

#define GS_HALF_RANGE UINT32_C(0x80000000)

/* 无符号差值允许 32 位回绕；只接受半个计数周期内严格前进的序号。 */
static bool gs_sequence_is_newer(uint32_t newer, uint32_t older)
{
    uint32_t delta = newer - older;
    return delta != 0U && delta < GS_HALF_RANGE;
}

static void gs_reset_evidence(gs_gesture_t *gesture)
{
    gesture->evidence_frames = 0U;
    gesture->evidence_start_ms = 0U;
    gesture->evidence_last_ms = 0U;
    gesture->candidate = GS_CLASS_UNKNOWN;
}

static bool gs_score_in_unit_interval(float value)
{
    /* 这两个比较同时拒绝 NaN、正无穷和负无穷。 */
    return value >= 0.0f && value <= 1.0f;
}

static bool gs_config_valid(const gs_gesture_config_t *config)
{
    return config->candidate_ms > 0U && config->candidate_ms < GS_HALF_RANGE &&
           config->clear_ms > 0U && config->clear_ms < GS_HALF_RANGE &&
           config->max_gap_ms > 0U && config->max_gap_ms < GS_HALF_RANGE &&
           config->max_age_ms > 0U && config->max_age_ms < GS_HALF_RANGE &&
           config->candidate_frames >= 2U && config->clear_frames >= 2U &&
           gs_score_in_unit_interval(config->target_score) && config->target_score > 0.5f &&
           gs_score_in_unit_interval(config->target_margin) && config->target_margin > 0.0f &&
           gs_score_in_unit_interval(config->neutral_score) && config->neutral_score > 0.5f;
}

gs_gesture_config_t gs_gesture_default_config(void)
{
    gs_gesture_config_t config;
    config.candidate_ms = 400U;
    config.clear_ms = 600U;
    config.max_gap_ms = 350U;
    config.max_age_ms = 300U;
    config.candidate_frames = 3U;
    config.clear_frames = 4U;
    config.target_score = 0.90f;
    config.target_margin = 0.20f;
    config.neutral_score = 0.95f;
    return config;
}

bool gs_gesture_init(gs_gesture_t *gesture,
                     const gs_gesture_config_t *config)
{
    gs_gesture_config_t selected;
    if (gesture == NULL) {
        return false;
    }
    selected = config != NULL ? *config : gs_gesture_default_config();
    memset(gesture, 0, sizeof(*gesture));
    if (!gs_config_valid(&selected)) {
        return false;
    }
    gesture->config = selected;
    gesture->state = GS_GESTURE_DISABLED;
    gesture->candidate = GS_CLASS_UNKNOWN;
    gesture->next_sequence = 1U;
    gesture->initialized = true;
    return true;
}

void gs_gesture_set_enabled(gs_gesture_t *gesture, bool enabled)
{
    if (gesture == NULL || !gesture->initialized || gesture->enabled == enabled) {
        return;
    }
    gesture->enabled = enabled;
    /* 收到新鲜有效图像后才进入等待中性证据状态。保留帧身份记录，
     * 防止反复启停识别时重复统计同一图像。 */
    gesture->state = GS_GESTURE_DISABLED;
    gs_reset_evidence(gesture);
}

void gs_gesture_report_fault(gs_gesture_t *gesture)
{
    if (gesture == NULL || !gesture->initialized) {
        return;
    }
    gesture->state = GS_GESTURE_DISABLED;
    gs_reset_evidence(gesture);
    if (gesture->fault_count != UINT32_MAX) {
        ++gesture->fault_count;
    }
}

void gs_gesture_require_clear(gs_gesture_t *gesture)
{
    if (gesture == NULL || !gesture->initialized) {
        return;
    }
    gs_reset_evidence(gesture);
    if (gesture->enabled && gesture->state != GS_GESTURE_DISABLED) {
        gesture->state = GS_GESTURE_WAIT_CLEAR;
    }
}

void gs_gesture_tick(gs_gesture_t *gesture, uint32_t now_ms,
                     uint32_t ui_generation)
{
    if (gesture == NULL || !gesture->initialized || !gesture->enabled) {
        return;
    }
    if (gesture->have_frame && !gesture->gap_fault_latched &&
        now_ms - gesture->last_receive_ms > gesture->config.max_gap_ms) {
        gesture->gap_fault_latched = true;
        gs_gesture_report_fault(gesture);
    }
    if (gesture->state == GS_GESTURE_CANDIDATE &&
        gesture->candidate_generation != ui_generation) {
        gs_gesture_require_clear(gesture);
    }
}

static bool gs_classify(const gs_gesture_observation_t *observation,
                       gs_gesture_class_t *best, float *margin)
{
    unsigned int index;
    float top = -1.0f;
    float second = -1.0f;
    float sum = 0.0f;
    *best = GS_CLASS_UNKNOWN;
    for (index = 0U; index < (unsigned int)GS_CLASS_COUNT; ++index) {
        float score = observation->scores[index];
        if (!gs_score_in_unit_interval(score)) {
            return false;
        }
        sum += score;
        if (score > top) {
            second = top;
            top = score;
            *best = (gs_gesture_class_t)index;
        } else if (score > second) {
            second = score;
        }
    }
    *margin = top - second;
    /* 容许浮点舍入误差，同时拒绝未归一化 logits 和异常分数向量。 */
    return sum >= 0.99f && sum <= 1.01f;
}

static void gs_add_evidence(gs_gesture_t *gesture, uint32_t capture_ms)
{
    if (gesture->evidence_frames == 0U) {
        gesture->evidence_start_ms = capture_ms;
    }
    gesture->evidence_last_ms = capture_ms;
    if (gesture->evidence_frames != UINT16_MAX) {
        ++gesture->evidence_frames;
    }
}

static bool gs_evidence_complete(const gs_gesture_t *gesture,
                                uint32_t duration_ms, uint16_t frames)
{
    return gesture->evidence_frames >= frames &&
           gesture->evidence_last_ms - gesture->evidence_start_ms >= duration_ms;
}

static bool gs_action_for_target(gs_gesture_class_t target, gs_ui_action_t *action)
{
    switch (target) {
    case GS_CLASS_POINT_LEFT:  *action = GS_UI_NEXT; return true;
    case GS_CLASS_POINT_RIGHT: *action = GS_UI_PREVIOUS; return true;
    case GS_CLASS_FIST:        *action = GS_UI_HOME; return true;
    case GS_CLASS_PALM:        *action = GS_UI_UP; return true;
    case GS_CLASS_V_SIGN:      *action = GS_UI_ENTER; return true;
    default: return false; /* UNKNOWN 永不导航。 */
    }
}

bool gs_gesture_process(gs_gesture_t *gesture,
                        const gs_gesture_observation_t *observation,
                        uint32_t now_ms, uint32_t ui_generation,
                        gs_ui_command_t *command)
{
    gs_gesture_class_t best;
    float margin;
    bool gap;
    bool target;
    if (gesture == NULL || !gesture->initialized || observation == NULL ||
        command == NULL || !gesture->enabled) {
        return false;
    }
    gs_gesture_tick(gesture, now_ms, ui_generation);
    /* 先拒绝未来时间戳和超龄帧，避免污染有效时基。
     * 重复帧也可能已过期，因此有效性检查必须早于去重。 */
    if (now_ms - observation->capture_ms > gesture->config.max_age_ms ||
        !observation->valid || !gs_classify(observation, &best, &margin)) {
        gs_gesture_report_fault(gesture);
        return false;
    }
    if (gesture->have_frame && observation->frame_id == gesture->last_frame_id) {
        if (gesture->duplicate_count != UINT32_MAX) {
            ++gesture->duplicate_count;
        }
        return false;
    }
    if (gesture->have_frame &&
        (!gs_sequence_is_newer(observation->frame_id, gesture->last_frame_id) ||
         !gs_sequence_is_newer(observation->capture_ms, gesture->last_capture_ms))) {
        gs_gesture_report_fault(gesture);
        return false;
    }
    gap = gesture->have_frame &&
          (observation->capture_ms - gesture->last_capture_ms >
               gesture->config.max_gap_ms ||
           now_ms - gesture->last_receive_ms > gesture->config.max_gap_ms);
    gesture->have_frame = true;
    gesture->last_frame_id = observation->frame_id;
    gesture->last_capture_ms = observation->capture_ms;
    gesture->last_receive_ms = now_ms;
    gesture->gap_fault_latched = false;
    if (gap) {
        gs_gesture_report_fault(gesture);
        return false;
    }
    if (gesture->state == GS_GESTURE_DISABLED) {
        gesture->state = GS_GESTURE_WAIT_CLEAR;
        gs_reset_evidence(gesture);
    }
    if (gesture->state == GS_GESTURE_WAIT_CLEAR) {
        if (best == GS_CLASS_UNKNOWN &&
            observation->scores[best] >= gesture->config.neutral_score) {
            gs_add_evidence(gesture, observation->capture_ms);
            if (gs_evidence_complete(gesture, gesture->config.clear_ms,
                                     gesture->config.clear_frames)) {
                gesture->state = GS_GESTURE_READY;
                gs_reset_evidence(gesture);
            }
        } else {
            gs_reset_evidence(gesture);
        }
        return false;
    }
    target = best <= GS_CLASS_V_SIGN &&
             observation->scores[best] >= gesture->config.target_score &&
             margin >= gesture->config.target_margin;
    if (gesture->state == GS_GESTURE_CANDIDATE &&
        (!target || best != gesture->candidate)) {
        gesture->state = GS_GESTURE_READY;
        gs_reset_evidence(gesture);
        return false;
    }
    if (!target) {
        return false;
    }
    if (gesture->state == GS_GESTURE_READY) {
        gesture->state = GS_GESTURE_CANDIDATE;
        gesture->candidate = best;
        gesture->candidate_generation = ui_generation;
    }
    gs_add_evidence(gesture, observation->capture_ms);
    if (!gs_evidence_complete(gesture, gesture->config.candidate_ms,
                              gesture->config.candidate_frames)) {
        return false;
    }
    if (gesture->candidate_generation != ui_generation) {
        gs_gesture_require_clear(gesture);
        return false;
    }
    if (!gs_action_for_target(gesture->candidate, &command->action)) {
        gs_gesture_require_clear(gesture);
        return false;
    }
    command->sequence = gesture->next_sequence;
    command->ui_generation = gesture->candidate_generation;
    ++gesture->next_sequence;
    if (gesture->next_sequence == 0U) {
        gesture->next_sequence = 1U;
    }
    gs_gesture_require_clear(gesture);
    return true;
}

uint16_t gs_gesture_progress(const gs_gesture_t *gesture)
{
    uint32_t duration;
    uint32_t elapsed;
    uint16_t required;
    uint32_t time_progress;
    uint32_t frame_progress;
    if (gesture == NULL || !gesture->initialized || gesture->evidence_frames == 0U ||
        (gesture->state != GS_GESTURE_WAIT_CLEAR &&
         gesture->state != GS_GESTURE_CANDIDATE)) {
        return 0U;
    }
    duration = gesture->state == GS_GESTURE_WAIT_CLEAR ?
               gesture->config.clear_ms : gesture->config.candidate_ms;
    required = gesture->state == GS_GESTURE_WAIT_CLEAR ?
               gesture->config.clear_frames : gesture->config.candidate_frames;
    elapsed = gesture->evidence_last_ms - gesture->evidence_start_ms;
    /* 用 uint64_t 计算乘积，避免调用者设置较长时间参数时溢出。 */
    time_progress = elapsed >= duration ? 1000U :
                    (uint32_t)(((uint64_t)elapsed * 1000U) / duration);
    frame_progress = gesture->evidence_frames >= required ? 1000U :
                     ((uint32_t)gesture->evidence_frames * 1000U) / required;
    return (uint16_t)(time_progress < frame_progress ? time_progress : frame_progress);
}
