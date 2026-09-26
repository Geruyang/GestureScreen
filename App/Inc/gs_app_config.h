#ifndef GS_APP_CONFIG_H
#define GS_APP_CONFIG_H

/* 六类模型的 UNKNOWN 混合了旧 OTHER/EMPTY，不能证明物理撤手。
 * 用户已接受“稳定非目标区间”解除动作锁定；门槛保持不变。
 * 识别显示仍可独立运行，正式业务验收标记仍为 0。 */
#define GS_RECOGNITION_REQUESTED 1
#define GS_UNKNOWN_NEUTRAL_REARM 1
#define GS_MODEL_VALIDATED_FOR_BUSINESS 0
#define GS_ENABLE_DEBUG_INPUT 1
#define GS_AUTOPLAY_MS 5000U

/* 各任务轮询间隔，单位为毫秒；转换成 RTOS tick 时向上取整。 */
#define GS_CAMERA_PERIOD_MS 10U
#define GS_VISION_PERIOD_MS 5U
#define GS_GESTURE_PERIOD_MS 10U
#define GS_GUI_PERIOD_MS 20U
#define GS_STORAGE_PERIOD_MS 2U
#define GS_HEALTH_PERIOD_MS 250U
#define GS_HEALTH_DEADLINE_MS 1500U
#define GS_CAMERA_FRAME_BYTES (320U * 240U * 2U)

/* 发往 GestureTask 的任务标志；故障后必须重新取得中性证据。 */
#define GS_FLAG_REQUIRE_CLEAR (1UL << 0)
#define GS_FLAG_INPUT_FAULT (1UL << 1)

/* GestureScreen.ioc 将 RTOS 堆限制为 24 KiB；队列与任务仅在启动时分配。 */
#define GS_FRAME_QUEUE_DEPTH 1U
#define GS_RETURN_QUEUE_DEPTH 2U
#define GS_OBSERVATION_QUEUE_DEPTH 2U
#define GS_COMMAND_QUEUE_DEPTH 4U
#define GS_LOCAL_INPUT_QUEUE_DEPTH 4U
#define GS_PREVIEW_QUEUE_DEPTH 1U
#define GS_PREVIEW_RETURN_QUEUE_DEPTH 2U
#endif
