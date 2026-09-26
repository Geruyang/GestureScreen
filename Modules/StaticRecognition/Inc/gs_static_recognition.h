#ifndef GS_STATIC_RECOGNITION_H
#define GS_STATIC_RECOGNITION_H
#include "gs_ai_int8_backend.h"
#define GS_STATIC_CLASS_COUNT 6U
#define GS_STATIC_RESULT_TTL_MS 1500U
/* Debug rejection thresholds, not calibrated accuracy guarantees. */
#define GS_STATIC_MIN_SCORE 0.90f
#define GS_STATIC_MIN_MARGIN 0.20f
typedef enum {
    GS_STATIC_WAITING = 0, GS_STATIC_RUNNING, GS_STATIC_IDENTIFIED,
    GS_STATIC_NO_TARGET, GS_STATIC_UNCERTAIN, GS_STATIC_BAD_QUALITY,
    GS_STATIC_INFERENCE_ERROR, GS_STATIC_TIMEOUT, GS_STATIC_STALE, GS_STATIC_CAMERA_ERROR
} gs_static_status_t;
typedef enum {
    GS_STATIC_POINT_LEFT = 0, GS_STATIC_POINT_RIGHT, GS_STATIC_FIST,
    GS_STATIC_PALM, GS_STATIC_V_SIGN, GS_STATIC_UNKNOWN
} gs_static_class_t;
typedef struct {
    uint32_t status, class_index, frame_id, capture_ms, inference_ms;
    uint32_t confidence_permille, margin_permille;
    /* One normalized six-class result drives both the dashboard and the
     * gesture state machine. It must never be populated by a second run. */
    float scores[GS_STATIC_CLASS_COUNT];
    uint32_t scores_valid;
} gs_static_result_t;
/* Sole VisionTask caller. Cube.AI uses its generated activation size and
 * whole-layer progress. Business actions remain gated in App/Gesture. */
gs_ai_status_t gs_static_recognize(const int8_t *input, size_t count,
    gs_int8_progress_fn progress, void *context, gs_static_result_t *result);
gs_ai_status_t gs_static_decode_logits(const int8_t logits[GS_STATIC_CLASS_COUNT],
    float output_scale, int32_t output_zero_point, gs_static_result_t *result);
gs_ai_status_t gs_static_model_status(void);
void gs_static_expire(gs_static_result_t *result, uint32_t now_ms);
#endif
