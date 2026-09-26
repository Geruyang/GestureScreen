#ifndef GS_PREPROCESS_H
#define GS_PREPROCESS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GS_CAMERA_WIDTH 320U
#define GS_CAMERA_HEIGHT 240U
#define GS_ROI_X 64U
#define GS_ROI_Y 24U
#define GS_ROI_WIDTH 192U
#define GS_ROI_HEIGHT 192U
#define GS_AI_INPUT_WIDTH 96U
#define GS_AI_INPUT_HEIGHT 96U
#define GS_AI_INPUT_CHANNELS 3U
#define GS_AI_INPUT_SIZE (GS_AI_INPUT_WIDTH * GS_AI_INPUT_HEIGHT * GS_AI_INPUT_CHANNELS)
#define GS_PREPROCESS_VERSION "rgb565-roi192-rgb96-box2-v1"

typedef enum {
    GS_RGB565_MSB_FIRST = 0,
    GS_RGB565_LSB_FIRST = 1
} gs_rgb565_byte_order_t;

typedef struct {
    const uint8_t *data;
    size_t data_size;
    uint32_t width;
    uint32_t height;
    size_t stride_bytes;
    gs_rgb565_byte_order_t byte_order;
} gs_rgb565_frame_t;

typedef enum {
    GS_PREPROCESS_OK = 0,
    GS_PREPROCESS_INVALID_ARGUMENT,
    GS_PREPROCESS_INVALID_FRAME,
    GS_PREPROCESS_OUTPUT_TOO_SMALL,
    GS_PREPROCESS_BAD_QUALITY
} gs_preprocess_status_t;

/* 仅供调试的默认阈值，须使用独立的真实 OV2640 采集数据校准。
 * 比例单位为千分比 [0,1000]，恰好等于阈值时允许通过。
 * 质量统计基于均值缩小前全部 192×192 个源亮度样本。 */
typedef struct {
    uint8_t dark_y_max;       /* Y 小于等于该阈值时计为暗像素。 */
    uint8_t bright_y_min;     /* Y 大于等于该阈值时计为过曝像素。 */
    uint16_t max_dark_permille;
    uint16_t max_bright_permille;
} gs_quality_config_t;

typedef struct {
    uint32_t pixel_count;
    uint32_t dark_pixels;
    uint32_t bright_pixels;
    uint16_t dark_permille;
    uint16_t bright_permille;
    uint8_t mean_y;
    uint8_t min_y;
    uint8_t max_y;
    uint8_t acceptable;
} gs_quality_stats_t;

gs_quality_config_t gs_quality_default_config(void);

/* 输入必须是完整且由 CPU 持有的帧；本函数不负责确认 DMA 完成、新鲜度或所有权。
 * 输入输出缓冲不得重叠。不分配堆内存，输出恰为 GS_AI_INPUT_SIZE 个 int8 值。
 * 返回 BAD_QUALITY 时仍生成像素和统计信息，仅供诊断；不得用于业务推理，
 * 也不能作为 UNKNOWN 或恢复识别的中性证据。参数校验失败时不修改 output，
 * 非空 stats 会被清零。quality_config 为 NULL 时使用文档说明的调试默认值。 */
gs_preprocess_status_t gs_preprocess_rgb565(
    const gs_rgb565_frame_t *frame,
    int8_t *output,
    size_t output_capacity,
    const gs_quality_config_t *quality_config,
    gs_quality_stats_t *stats);

#ifdef __cplusplus
}
#endif
#endif
