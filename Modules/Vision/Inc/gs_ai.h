#ifndef GS_AI_H
#define GS_AI_H

#include <stddef.h>
#include <stdint.h>

#include "gs_preprocess.h"

#ifdef __cplusplus
extern "C" {
#endif

#define GS_AI_CLASS_COUNT 6U
#define GS_AI_CONTRACT_VERSION 1U

/* 索引顺序属于模型包契约，不能直接沿用原始模型的标签顺序。 */
typedef enum {
    GS_AI_POINT_LEFT = 0,
    GS_AI_POINT_RIGHT,
    GS_AI_FIST,
    GS_AI_PALM,
    GS_AI_V_SIGN,
    GS_AI_UNKNOWN
} gs_ai_class_t;

typedef enum {
    GS_AI_OUTPUT_INT8_LOGITS = 0,
    GS_AI_OUTPUT_INT8_PROBABILITIES = 1
} gs_ai_output_kind_t;

typedef enum {
    GS_AI_OK = 0,
    GS_AI_UNAVAILABLE,
    GS_AI_INVALID_ARGUMENT,
    GS_AI_CONTRACT_MISMATCH,
    GS_AI_BACKEND_FAILURE,
    GS_AI_INVALID_OUTPUT
} gs_ai_status_t;

typedef struct {
    uint32_t contract_version;
    const char *model_id;
    const char *preprocess_version;
    uint16_t input_shape[4]; /* 形状为 [1,96,96,3]；推理回调的输入和输出均为 int8。 */
    float input_scale;
    int32_t input_zero_point;
    uint32_t output_count;
    const char *labels[GS_AI_CLASS_COUNT];
    gs_ai_output_kind_t output_kind;
    float output_scale;
    int32_t output_zero_point;
    /* 实际六类模型包通过文档规定的资源、预处理、校准和业务事件验收后才可置位。
     * 此字段是发布门槛声明，本身不自动证明模型准确率。 */
    uint8_t validated_for_business;
} gs_ai_metadata_t;

typedef gs_ai_status_t (*gs_ai_infer_fn)(void *context, const int8_t *input,
    size_t input_count, int8_t *output, size_t output_count);

typedef struct {
    const gs_ai_metadata_t *metadata;
    gs_ai_infer_fn infer;
    void *context;
} gs_ai_backend_t;

typedef struct {
    const gs_ai_backend_t *backend;
    uint8_t ready;
} gs_ai_t;

typedef struct {
    /* 用于类别比较的归一化分数，并非经过独立校准的真实概率。
     * logits 只执行一次稳定 Softmax；概率输出不再执行 Softmax。 */
    float scores[GS_AI_CLASS_COUNT];
    gs_ai_class_t top_index;
    float top_score;
    float margin;
    uint8_t valid;
} gs_ai_result_t;

const gs_ai_backend_t *gs_ai_default_backend(void);
gs_ai_status_t gs_ai_validate_metadata(const gs_ai_metadata_t *metadata);
/* ai 使用期间，后端及其元数据必须保持只读且存活。
 * backend 为 NULL 时选用不可用占位后端；调用失败会清除 result.valid。 */
gs_ai_status_t gs_ai_init(gs_ai_t *ai, const gs_ai_backend_t *backend);
gs_ai_status_t gs_ai_run(gs_ai_t *ai, const int8_t *input, size_t input_count,
                         gs_ai_result_t *result);

#ifdef __cplusplus
}
#endif
#endif
