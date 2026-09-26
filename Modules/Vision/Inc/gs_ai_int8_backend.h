#ifndef GS_AI_INT8_BACKEND_H
#define GS_AI_INT8_BACKEND_H

#include "gs_ai.h"
#include <stdbool.h>
/* Model descriptors/weights and input are immutable during execution, including
 * progress callbacks. Caller exclusively owns workspace/output for this call. */

/* 串行 NHWC int8 链式网络执行器，不解释任意 TFLite 文件。
 * 最终固件使用 STM32Cube.AI 后端；此通用接口保留供主机测试。
 * 无堆、ISR、HAL和第三方运行库依赖。 */
typedef enum { GS_INT8_CONV = 1, GS_INT8_DEPTHWISE = 2, GS_INT8_AVERAGE = 3 } gs_int8_op_t;

typedef struct {
    uint16_t input_h, input_w, input_c;
    uint16_t output_h, output_w, output_c;
    uint16_t kernel_h, kernel_w, stride_h, stride_w, pad_h, pad_w;
    int16_t input_zero, output_zero, activation_min, activation_max;
    uint8_t operation;
    const int8_t *weights;
    const int32_t *bias;
    const int32_t *multipliers;
    const int8_t *shifts;
} gs_int8_layer_t;

typedef struct {
    const gs_int8_layer_t *layers;
    size_t layer_count, input_size, output_size, slot_size;
} gs_int8_model_t;

typedef struct {
    const gs_int8_model_t *model;
    int8_t *workspace;
    size_t workspace_size;
} gs_int8_context_t;

/* 工作区必须独占，容量至少2*slot_size；输入、输出、工作区不得重叠。
 * 参考执行器采用逐通道定点卷积，不承诺实板推理时延；性能须实测。 */
gs_ai_status_t gs_int8_execute(const gs_int8_model_t *model,
    const int8_t *input, size_t input_size, int8_t *output, size_t output_size,
    int8_t *workspace, size_t workspace_size);

/* Optional progress after at most 64 completed output elements (and layer end).
 * Return false to abort. The final callback for each layer includes its total.
 * Callback may yield outside interrupt/critical context; numerical work is unchanged.
 * Count means completed elements, not a contiguous NHWC prefix (pointwise may
 * visit channels first); only the complete final tensor is externally copied.
 * Caller owns deadline/error distinction; aborted output must never be published. */
typedef bool (*gs_int8_progress_fn)(void *context, size_t layer, uint32_t completed_outputs);
gs_ai_status_t gs_int8_execute_progress(const gs_int8_model_t *model,
    const int8_t *input, size_t input_size, int8_t *output, size_t output_size,
    int8_t *workspace, size_t workspace_size, gs_int8_progress_fn progress, void *context);

/* 历史参考后端仅供隔离回归；六类发布不依赖此入口。 */
gs_ai_status_t gs_int8_backend_infer(void *context, const int8_t *input,
    size_t input_size, int8_t *output, size_t output_size);

#endif
