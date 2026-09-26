/* Unified six-class display and business observation decoder. */
#include "gs_static_recognition.h"
#include <float.h>
#include <math.h>
#include <string.h>
#if defined(GS_STATIC_USE_CUBEAI) && GS_STATIC_USE_CUBEAI
#include "gs_cubeai_backend.h"
#elif defined(GS_STATIC_TEST_BACKEND) && GS_STATIC_TEST_BACKEND
gs_ai_status_t gs_static_test_execute(const int8_t *input, size_t count,
    int8_t *output, size_t output_count, float *output_scale,
    int32_t *output_zero_point, gs_int8_progress_fn progress, void *context);
#endif
gs_ai_status_t gs_static_decode_logits(const int8_t logits[GS_STATIC_CLASS_COUNT],
    float output_scale, int32_t output_zero_point, gs_static_result_t *result)
{
    float scores[GS_STATIC_CLASS_COUNT], sum = 0.0f, best = -1.0f, second = -1.0f;
    int32_t maximum = -128;
    uint32_t i, top = 0;
    if (result == NULL || logits == NULL || output_scale <= 0.0f ||
        output_scale > FLT_MAX || output_zero_point < -128 || output_zero_point > 127) {
        return GS_AI_INVALID_ARGUMENT;
    }
    result->status = GS_STATIC_INFERENCE_ERROR;
    result->confidence_permille = result->margin_permille = 0;
    result->scores_valid = 0U;
    memset(result->scores, 0, sizeof result->scores);
    for (i = 0; i < GS_STATIC_CLASS_COUNT; ++i) { if (logits[i] > maximum) { maximum = logits[i]; } }
    for (i = 0; i < GS_STATIC_CLASS_COUNT; ++i) {
        /* Subtracting the maximum cancels the shared output zero point. */
        scores[i] = expf(((float)logits[i] - (float)maximum) * output_scale);
        sum += scores[i];
    }
    if (!isfinite(sum) || sum <= 0.0f) { return GS_AI_INVALID_OUTPUT; }
    for (i = 0; i < GS_STATIC_CLASS_COUNT; ++i) {
        scores[i] /= sum;
        result->scores[i] = scores[i];
        if (scores[i] > best) { second = best; best = scores[i]; top = i; }
        else if (scores[i] > second) { second = scores[i]; }
    }
    result->scores_valid = 1U;
    result->class_index = top;
    result->confidence_permille = (uint32_t)(best * 1000.0f + 0.5f);
    result->margin_permille = (uint32_t)((best - second) * 1000.0f + 0.5f);
    if (best < GS_STATIC_MIN_SCORE || best - second < GS_STATIC_MIN_MARGIN) {
        result->status = GS_STATIC_UNCERTAIN;
    } else {
        result->status = top == GS_STATIC_UNKNOWN ? GS_STATIC_NO_TARGET : GS_STATIC_IDENTIFIED;
    }
    return GS_AI_OK;
}

gs_ai_status_t gs_static_model_status(void)
{
#if defined(GS_STATIC_USE_CUBEAI) && GS_STATIC_USE_CUBEAI
    return gs_cubeai_contract_status();
#elif defined(GS_STATIC_TEST_BACKEND) && GS_STATIC_TEST_BACKEND
    return GS_AI_OK;
#else
    return GS_AI_UNAVAILABLE;
#endif
}
gs_ai_status_t gs_static_recognize(const int8_t *input, size_t count,
    gs_int8_progress_fn progress, void *context, gs_static_result_t *result)
{
    int8_t logits[GS_STATIC_CLASS_COUNT];
    float output_scale = 0.0f;
    int32_t output_zero_point = 0;
    gs_ai_status_t status;
    if (result == NULL) { return GS_AI_INVALID_ARGUMENT; }
    result->status = GS_STATIC_INFERENCE_ERROR;
    result->confidence_permille = result->margin_permille = 0;
    result->scores_valid = 0U;
    memset(result->scores, 0, sizeof result->scores);
#if defined(GS_STATIC_USE_CUBEAI) && GS_STATIC_USE_CUBEAI
    status = gs_cubeai_execute(input, count, logits, sizeof logits,
        &output_scale, &output_zero_point, progress, context);
#elif defined(GS_STATIC_TEST_BACKEND) && GS_STATIC_TEST_BACKEND
    status = gs_static_test_execute(input, count, logits, sizeof logits,
        &output_scale, &output_zero_point, progress, context);
#else
    (void)input; (void)count; (void)progress; (void)context;
    status = GS_AI_UNAVAILABLE;
#endif
    if (status == GS_AI_OK) {
        status = gs_static_decode_logits(logits, output_scale, output_zero_point, result);
    }
    return status;
}
void gs_static_expire(gs_static_result_t *result, uint32_t now_ms)
{
    if (result != NULL && result->frame_id != 0 &&
        now_ms - result->capture_ms > GS_STATIC_RESULT_TTL_MS) {
        result->status = GS_STATIC_STALE;
        result->confidence_permille = result->margin_permille = 0;
        result->scores_valid = 0U;
        memset(result->scores, 0, sizeof result->scores);
    }
}
