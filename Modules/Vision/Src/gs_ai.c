/* 模型适配层：检查六类契约 → int8 推理 → 反量化 → 归一化 → 提取首位类别与分差。
 * 模型缺失或契约不匹配时返回不可用；不能用原始五类模型触发业务。 */
#include "gs_ai.h"

#include <float.h>
#include <math.h>
#include <string.h>

static const char *const gs_expected_labels[GS_AI_CLASS_COUNT] = {
    "POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "UNKNOWN"
};

static int gs_float_finite(float value)
{
    return value == value && value <= FLT_MAX && value >= -FLT_MAX;
}

static gs_ai_status_t gs_unavailable_infer(void *context, const int8_t *input,
    size_t input_count, int8_t *output, size_t output_count)
{
    (void)context;
    (void)input;
    (void)input_count;
    (void)output;
    (void)output_count;
    return GS_AI_UNAVAILABLE;
}

const gs_ai_backend_t *gs_ai_default_backend(void)
{
    static const gs_ai_backend_t backend = { NULL, gs_unavailable_infer, NULL };
    return &backend;
}

gs_ai_status_t gs_ai_validate_metadata(const gs_ai_metadata_t *metadata)
{
    uint32_t i;
    if (metadata == NULL) {
        return GS_AI_UNAVAILABLE;
    }
    if (metadata->contract_version != GS_AI_CONTRACT_VERSION ||
        metadata->model_id == NULL || metadata->model_id[0] == '\0' ||
        metadata->preprocess_version == NULL ||
        strcmp(metadata->preprocess_version, GS_PREPROCESS_VERSION) != 0 ||
        metadata->input_shape[0] != 1U || metadata->input_shape[1] != GS_AI_INPUT_HEIGHT ||
        metadata->input_shape[2] != GS_AI_INPUT_WIDTH || metadata->input_shape[3] != GS_AI_INPUT_CHANNELS ||
        metadata->input_scale != 1.0f || metadata->input_zero_point != -128 ||
        metadata->output_count != GS_AI_CLASS_COUNT ||
        !gs_float_finite(metadata->output_scale) || metadata->output_scale <= 0.0f ||
        metadata->output_zero_point < -128 || metadata->output_zero_point > 127 ||
        (metadata->output_kind != GS_AI_OUTPUT_INT8_LOGITS &&
         metadata->output_kind != GS_AI_OUTPUT_INT8_PROBABILITIES) ||
        metadata->validated_for_business != 1U) {
        return GS_AI_CONTRACT_MISMATCH;
    }
    if (metadata->output_kind == GS_AI_OUTPUT_INT8_PROBABILITIES &&
        metadata->output_scale > 1.0f) {
        return GS_AI_CONTRACT_MISMATCH;
    }
    for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
        if (metadata->labels[i] == NULL ||
            strcmp(metadata->labels[i], gs_expected_labels[i]) != 0) {
            return GS_AI_CONTRACT_MISMATCH;
        }
    }
    return GS_AI_OK;
}

gs_ai_status_t gs_ai_init(gs_ai_t *ai, const gs_ai_backend_t *backend)
{
    gs_ai_status_t status;
    if (ai == NULL) {
        return GS_AI_INVALID_ARGUMENT;
    }
    memset(ai, 0, sizeof(*ai));
    ai->backend = backend != NULL ? backend : gs_ai_default_backend();
    if (ai->backend->infer == NULL) {
        return GS_AI_UNAVAILABLE;
    }
    status = gs_ai_validate_metadata(ai->backend->metadata);
    ai->ready = (uint8_t)(status == GS_AI_OK);
    return status;
}

gs_ai_status_t gs_ai_run(gs_ai_t *ai, const int8_t *input, size_t input_count,
                         gs_ai_result_t *result)
{
    int8_t raw[GS_AI_CLASS_COUNT];
    float values[GS_AI_CLASS_COUNT];
    float sum = 0.0f, max_value = -FLT_MAX, second = -1.0f;
    gs_ai_status_t status;
    const gs_ai_metadata_t *metadata;
    uint32_t i, top = 0U;
    if (result != NULL) {
        memset(result, 0, sizeof(*result));
    }
    if (ai == NULL || input == NULL || result == NULL || input_count != GS_AI_INPUT_SIZE) {
        return GS_AI_INVALID_ARGUMENT;
    }
    if (ai->ready == 0U || ai->backend == NULL || ai->backend->infer == NULL) {
        return GS_AI_UNAVAILABLE;
    }
    metadata = ai->backend->metadata;
    status = gs_ai_validate_metadata(metadata);
    if (status != GS_AI_OK) {
        ai->ready = 0U;
        return status;
    }
    status = ai->backend->infer(ai->backend->context, input, input_count,
                               raw, GS_AI_CLASS_COUNT);
    if (status != GS_AI_OK) {
        return status == GS_AI_UNAVAILABLE ? GS_AI_UNAVAILABLE : GS_AI_BACKEND_FAILURE;
    }
    for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
        values[i] = ((float)raw[i] - (float)metadata->output_zero_point) * metadata->output_scale;
        if (!gs_float_finite(values[i])) {
            return GS_AI_INVALID_OUTPUT;
        }
        if (values[i] > max_value) {
            max_value = values[i];
        }
    }
    if (metadata->output_kind == GS_AI_OUTPUT_INT8_LOGITS) {
        for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
            /* 相减负溢出可能得到 -inf；此处允许 exp(-inf)=0。 */
            values[i] = expf(values[i] - max_value);
            sum += values[i];
        }
    } else {
        float tolerance = 0.5f * metadata->output_scale;
        float sum_tolerance = 3.5f * metadata->output_scale + 0.00001f;
        if (sum_tolerance > 0.05f) {
            sum_tolerance = 0.05f;
        }
        for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
            if (values[i] < -tolerance || values[i] > 1.0f + tolerance) {
                return GS_AI_INVALID_OUTPUT;
            }
            if (values[i] < 0.0f) {
                values[i] = 0.0f;
            } else if (values[i] > 1.0f) {
                values[i] = 1.0f;
            }
            sum += values[i];
        }
        if (fabsf(sum - 1.0f) > sum_tolerance) {
            return GS_AI_INVALID_OUTPUT;
        }
    }
    if (!gs_float_finite(sum) || sum <= 0.0f) {
        return GS_AI_INVALID_OUTPUT;
    }
    for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
        /* 归一化也修正概率输出的小幅量化总和误差，
         * 概率输出不能再次执行 Softmax。 */
        result->scores[i] = values[i] / sum;
        if (result->scores[i] > result->scores[top]) {
            top = i;
        }
    }
    for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
        if (i != top && result->scores[i] > second) {
            second = result->scores[i];
        }
    }
    result->top_index = (gs_ai_class_t)top;
    result->top_score = result->scores[top];
    result->margin = result->top_score - second;
    result->valid = 1U;
    return GS_AI_OK;
}
