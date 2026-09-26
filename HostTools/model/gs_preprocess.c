/* 固定预处理：320×240 RGB565 → 中心 192×192 ROI → RGB 位复制
 * → 各通道 2×2 均值 → 96×96×3 NHWC int8。质量统计保留原亮度算法。 */
#include "gs_preprocess.h"

#include <stdint.h>
#include <string.h>

gs_quality_config_t gs_quality_default_config(void)
{
    gs_quality_config_t config;
    config.dark_y_max = 16U;
    config.bright_y_min = 240U;
    config.max_dark_permille = 800U;
    config.max_bright_permille = 800U;
    return config;
}

static void gs_rgb565_channels(const uint8_t *source,
                               gs_rgb565_byte_order_t byte_order,
                               uint8_t rgb[3])
{
    uint16_t pixel;
    uint32_t r5, g6, b5;
    if (byte_order == GS_RGB565_MSB_FIRST) {
        pixel = (uint16_t)(((uint16_t)source[0] << 8U) | source[1]);
    } else {
        pixel = (uint16_t)(((uint16_t)source[1] << 8U) | source[0]);
    }
    /* 拆出 RGB565 分量，并通过高位补齐扩展到 8 位。 */
    r5 = (pixel >> 11U) & 31U;
    g6 = (pixel >> 5U) & 63U;
    b5 = pixel & 31U;
    rgb[0] = (uint8_t)((r5 << 3U) | (r5 >> 2U));
    rgb[1] = (uint8_t)((g6 << 2U) | (g6 >> 4U));
    rgb[2] = (uint8_t)((b5 << 3U) | (b5 >> 2U));
}

static uint8_t gs_rgb_y(const uint8_t rgb[3])
{
    /* 用总和为 256 的整数权重近似亮度，加 128 后右移实现四舍五入。 */
    return (uint8_t)((77U * rgb[0] + 150U * rgb[1] + 29U * rgb[2] + 128U) >> 8U);
}

static void gs_accumulate_quality(gs_quality_stats_t *stats,
                                  const gs_quality_config_t *config,
                                  uint8_t y, uint32_t *sum)
{
    ++stats->pixel_count;
    *sum += y;
    if (y <= config->dark_y_max) {
        ++stats->dark_pixels;
    }
    if (y >= config->bright_y_min) {
        ++stats->bright_pixels;
    }
    if (y < stats->min_y) {
        stats->min_y = y;
    }
    if (y > stats->max_y) {
        stats->max_y = y;
    }
}

gs_preprocess_status_t gs_preprocess_rgb565(
    const gs_rgb565_frame_t *frame, int8_t *output, size_t output_capacity,
    const gs_quality_config_t *quality_config, gs_quality_stats_t *stats)
{
    gs_quality_config_t defaults = gs_quality_default_config();
    const gs_quality_config_t *config = quality_config != NULL ? quality_config : &defaults;
    gs_quality_stats_t measured;
    size_t required_size;
    uint32_t total_y = 0U;
    uint32_t row, col, dy, dx;

    if (stats != NULL) {
        memset(stats, 0, sizeof(*stats));
    }
    if (frame == NULL || frame->data == NULL || output == NULL ||
        config->dark_y_max >= config->bright_y_min ||
        config->max_dark_permille > 1000U || config->max_bright_permille > 1000U) {
        return GS_PREPROCESS_INVALID_ARGUMENT;
    }
    if (frame->width != GS_CAMERA_WIDTH || frame->height != GS_CAMERA_HEIGHT ||
        (frame->byte_order != GS_RGB565_MSB_FIRST &&
         frame->byte_order != GS_RGB565_LSB_FIRST) ||
        frame->stride_bytes < (size_t)GS_CAMERA_WIDTH * 2U) {
        return GS_PREPROCESS_INVALID_FRAME;
    }
    /* 校验整个帧的容量，而不只是 ROI；先防止 size_t 算术溢出。
     * 末行像素必须完整，但不要求末行后还保留填充字节。 */
    if (frame->stride_bytes > (SIZE_MAX - (size_t)GS_CAMERA_WIDTH * 2U) /
                              (GS_CAMERA_HEIGHT - 1U)) {
        return GS_PREPROCESS_INVALID_FRAME;
    }
    required_size = frame->stride_bytes * (GS_CAMERA_HEIGHT - 1U) +
                    (size_t)GS_CAMERA_WIDTH * 2U;
    if (frame->data_size < required_size) {
        return GS_PREPROCESS_INVALID_FRAME;
    }
    if (output_capacity < GS_AI_INPUT_SIZE) {
        return GS_PREPROCESS_OUTPUT_TOO_SMALL;
    }

    memset(&measured, 0, sizeof(measured));
    measured.min_y = 255U;
    for (row = 0U; row < GS_AI_INPUT_HEIGHT; ++row) {
        for (col = 0U; col < GS_AI_INPUT_WIDTH; ++col) {
            uint32_t block_rgb[3] = {0U, 0U, 0U};
            for (dy = 0U; dy < 2U; ++dy) {
                const uint8_t *source = frame->data +
                    (GS_ROI_Y + 2U * row + dy) * frame->stride_bytes +
                    (GS_ROI_X + 2U * col) * 2U;
                for (dx = 0U; dx < 2U; ++dx) {
                    uint8_t rgb[3];
                    gs_rgb565_channels(source + dx * 2U, frame->byte_order, rgb);
                    block_rgb[0] += rgb[0];
                    block_rgb[1] += rgb[1];
                    block_rgb[2] += rgb[2];
                    gs_accumulate_quality(&measured, config, gs_rgb_y(rgb), &total_y);
                }
            }
            /* 与训练端 rgb192_to_rgb96 相同：先 RGB565 位复制，再逐通道
             * ((sum+2)//4)，最后按 scale=1、zero_point=-128 排列为 NHWC。 */
            {
                size_t at = ((size_t)row * GS_AI_INPUT_WIDTH + col) * GS_AI_INPUT_CHANNELS;
                uint32_t channel;
                for (channel = 0U; channel < GS_AI_INPUT_CHANNELS; ++channel) {
                    output[at + channel] = (int8_t)((int32_t)((block_rgb[channel] + 2U) / 4U) - 128);
                }
            }
        }
    }
    measured.dark_permille = (uint16_t)(measured.dark_pixels * 1000U / measured.pixel_count);
    measured.bright_permille = (uint16_t)(measured.bright_pixels * 1000U / measured.pixel_count);
    measured.mean_y = (uint8_t)((total_y + measured.pixel_count / 2U) / measured.pixel_count);
    /* 直接交叉相乘比较精确比例，避免显示用千分比截断影响阈值判断。 */
    measured.acceptable = (uint8_t)(
        measured.dark_pixels * 1000U <= (uint32_t)config->max_dark_permille * measured.pixel_count &&
        measured.bright_pixels * 1000U <= (uint32_t)config->max_bright_permille * measured.pixel_count);
    if (stats != NULL) {
        *stats = measured;
    }
    return measured.acceptable != 0U ? GS_PREPROCESS_OK : GS_PREPROCESS_BAD_QUALITY;
}
