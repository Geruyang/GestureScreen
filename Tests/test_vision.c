#include "gs_ai.h"
#include "gs_preprocess.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define TEST_STRIDE (GS_CAMERA_WIDTH * 2U + 8U)

static uint8_t source[GS_CAMERA_HEIGHT * TEST_STRIDE];
static int8_t output[GS_AI_INPUT_SIZE];

static gs_rgb565_frame_t frame_view(void)
{
    gs_rgb565_frame_t frame;
    frame.data = source;
    frame.data_size = sizeof(source);
    frame.width = GS_CAMERA_WIDTH;
    frame.height = GS_CAMERA_HEIGHT;
    frame.stride_bytes = TEST_STRIDE;
    frame.byte_order = GS_RGB565_MSB_FIRST;
    return frame;
}

static void set_pixel(uint32_t x, uint32_t y, uint16_t rgb,
                      gs_rgb565_byte_order_t order)
{
    uint8_t *p = &source[y * TEST_STRIDE + 2U * x];
    if (order == GS_RGB565_MSB_FIRST) {
        p[0] = (uint8_t)(rgb >> 8U);
        p[1] = (uint8_t)rgb;
    } else {
        p[0] = (uint8_t)rgb;
        p[1] = (uint8_t)(rgb >> 8U);
    }
}

static void fill_roi(uint16_t rgb, gs_rgb565_byte_order_t order)
{
    uint32_t x, y;
    for (y = GS_ROI_Y; y < GS_ROI_Y + GS_ROI_HEIGHT; ++y) {
        for (x = GS_ROI_X; x < GS_ROI_X + GS_ROI_WIDTH; ++x) {
            set_pixel(x, y, rgb, order);
        }
    }
}

static void test_colors_and_quality(void)
{
    const uint16_t colors[] = { 0x0000U, 0xffffU, 0xf800U, 0x07e0U, 0x001fU };
    const int expected_rgb[][3] = {
        {-128, -128, -128}, {127, 127, 127}, {127, -128, -128},
        {-128, 127, -128}, {-128, -128, 127}
    };
    const uint8_t expected_y[] = {0U, 255U, 77U, 149U, 29U};
    uint32_t order, c, i;
    gs_quality_stats_t stats;
    gs_rgb565_frame_t frame = frame_view();

    for (order = 0U; order < 2U; ++order) {
        frame.byte_order = (gs_rgb565_byte_order_t)order;
        for (c = 0U; c < sizeof(colors) / sizeof(colors[0]); ++c) {
            gs_preprocess_status_t status;
            /* ROI 外及行填充故意置黑，这些区域不得参与质量统计。 */
            memset(source, 0, sizeof(source));
            fill_roi(colors[c], frame.byte_order);
            status = gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, &stats);
            assert(status == (c < 2U ? GS_PREPROCESS_BAD_QUALITY : GS_PREPROCESS_OK));
            assert(stats.pixel_count == GS_ROI_WIDTH * GS_ROI_HEIGHT);
            assert(stats.mean_y == expected_y[c]);
            assert(stats.min_y == stats.mean_y && stats.max_y == stats.mean_y);
            assert(stats.dark_pixels == (c == 0U ? stats.pixel_count : 0U));
            assert(stats.bright_pixels == (c == 1U ? stats.pixel_count : 0U));
            for (i = 0U; i < GS_AI_INPUT_SIZE; ++i) {
                assert(output[i] == expected_rgb[c][i % 3U]);
            }
        }
    }
}

static void test_rounding_and_pre_average_quality(void)
{
    uint32_t x, y, i;
    gs_quality_stats_t stats;
    gs_quality_config_t config = gs_quality_default_config();
    gs_rgb565_frame_t frame = frame_view();
    memset(source, 0, sizeof(source));
    for (y = GS_ROI_Y; y < GS_ROI_Y + GS_ROI_HEIGHT; ++y) {
        for (x = GS_ROI_X; x < GS_ROI_X + GS_ROI_WIDTH; ++x) {
            set_pixel(x, y, (x & 1U) != 0U ? 0xffffU : 0U, frame.byte_order);
        }
    }
    config.max_dark_permille = 499U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), &config, &stats) ==
           GS_PREPROCESS_BAD_QUALITY);
    assert(stats.dark_permille == 500U && stats.bright_permille == 500U);
    assert(stats.mean_y == 128U && stats.acceptable == 0U);
    for (i = 0U; i < GS_AI_INPUT_SIZE; ++i) {
        assert(output[i] == 0); /* 每通道：(0 + 255 + 0 + 255 + 2) / 4 - 128。 */
    }
    config.max_dark_permille = 500U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), &config, &stats) ==
           GS_PREPROCESS_OK);

    /* 用不均匀的角落像素块暴露 ROI、行步长和行列定位错误。
     * 红、绿、蓝、白的 Y 为 77、149、29、255，均值 (510+2)/4=128。 */
    fill_roi(0xf800U, frame.byte_order);
    set_pixel(GS_ROI_X, GS_ROI_Y, 0xf800U, frame.byte_order);
    set_pixel(GS_ROI_X + 1U, GS_ROI_Y, 0x07e0U, frame.byte_order);
    set_pixel(GS_ROI_X, GS_ROI_Y + 1U, 0x001fU, frame.byte_order);
    set_pixel(GS_ROI_X + 1U, GS_ROI_Y + 1U, 0xffffU, frame.byte_order);
    set_pixel(GS_ROI_X + GS_ROI_WIDTH - 2U, GS_ROI_Y + GS_ROI_HEIGHT - 2U,
              0U, frame.byte_order);
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, &stats) ==
           GS_PREPROCESS_OK);
    assert(output[0] == 0 && output[1] == 0 && output[2] == 0);
    assert(output[3] == 127 && output[4] == -128 && output[5] == -128);
    assert(output[GS_AI_INPUT_WIDTH * 3U] == 127);
    assert(output[GS_AI_INPUT_SIZE - 3U] == 63); /* (0 + 255*3 + 2)/4 - 128。 */
    assert(output[GS_AI_INPUT_SIZE - 2U] == -128 && output[GS_AI_INPUT_SIZE - 1U] == -128);
}

static void test_validation(void)
{
    gs_rgb565_frame_t frame = frame_view();
    gs_quality_config_t config = gs_quality_default_config();
    gs_quality_stats_t stats;
    memset(output, 42, sizeof(output));
    memset(&stats, 0xff, sizeof(stats));
    assert(gs_preprocess_rgb565(NULL, output, sizeof(output), NULL, &stats) ==
           GS_PREPROCESS_INVALID_ARGUMENT);
    assert(stats.pixel_count == 0U && stats.acceptable == 0U && output[0] == 42);
    assert(gs_preprocess_rgb565(&frame, NULL, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_ARGUMENT);
    frame.width = 640U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_FRAME);
    frame = frame_view();
    frame.height = 239U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_FRAME);
    frame = frame_view();
    frame.data_size = TEST_STRIDE * (GS_CAMERA_HEIGHT - 1U) + GS_CAMERA_WIDTH * 2U - 1U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_FRAME);
    frame = frame_view();
    frame.stride_bytes = 639U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_FRAME);
    frame.stride_bytes = SIZE_MAX;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_FRAME);
    frame = frame_view();
    frame.byte_order = (gs_rgb565_byte_order_t)99;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_INVALID_FRAME);
    frame = frame_view();
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output) - 1U, NULL, NULL) ==
           GS_PREPROCESS_OUTPUT_TOO_SMALL);
    config.max_dark_permille = 1001U;
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), &config, NULL) ==
           GS_PREPROCESS_INVALID_ARGUMENT);
    assert(output[0] == 42 && output[GS_AI_INPUT_SIZE - 1U] == 42);

    /* 末行像素必须完整，末行末尾的填充字节可省略。 */
    frame.data_size = TEST_STRIDE * (GS_CAMERA_HEIGHT - 1U) + GS_CAMERA_WIDTH * 2U;
    fill_roi(0xf800U, frame.byte_order);
    assert(gs_preprocess_rgb565(&frame, output, sizeof(output), NULL, NULL) ==
           GS_PREPROCESS_OK);
}

typedef struct {
    int8_t values[GS_AI_CLASS_COUNT];
    gs_ai_status_t status;
    uint32_t calls;
} fake_backend_context_t;

static gs_ai_status_t fake_infer(void *context, const int8_t *input,
    size_t input_count, int8_t *result, size_t result_count)
{
    fake_backend_context_t *fake = (fake_backend_context_t *)context;
    assert(input != NULL && input_count == GS_AI_INPUT_SIZE);
    assert(result_count == GS_AI_CLASS_COUNT);
    ++fake->calls;
    memcpy(result, fake->values, GS_AI_CLASS_COUNT);
    return fake->status;
}

static gs_ai_metadata_t test_metadata(void)
{
    /* 仅为合成测试声明，不代表已有通过验收的真实模型。 */
    const gs_ai_metadata_t metadata = {
        GS_AI_CONTRACT_VERSION, "synthetic-test-only", GS_PREPROCESS_VERSION,
        { 1U, 96U, 96U, 3U }, 1.0f, -128, GS_AI_CLASS_COUNT,
        { "POINT_LEFT", "POINT_RIGHT", "FIST", "PALM", "V_SIGN", "UNKNOWN" },
        GS_AI_OUTPUT_INT8_LOGITS, 0.1f, 0, 1U
    };
    return metadata;
}

static void test_model_gate_and_stub(void)
{
    gs_ai_t ai;
    gs_ai_result_t result;
    gs_ai_metadata_t metadata = test_metadata();
    assert(gs_ai_init(&ai, NULL) == GS_AI_UNAVAILABLE);
    memset(&result, 0xff, sizeof(result));
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_UNAVAILABLE);
    assert(result.valid == 0U);
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_OK);
    metadata.output_count = 5U; /* OpenMV 原始五类模型必须被业务入口拒绝。 */
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.labels[5] = "no gesture";
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.input_scale = 0.5f;
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.input_zero_point = 0;
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.preprocess_version = "openmv-native-unknown";
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.validated_for_business = 0U;
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.output_scale = NAN;
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
    metadata = test_metadata();
    metadata.output_kind = (gs_ai_output_kind_t)99;
    assert(gs_ai_validate_metadata(&metadata) == GS_AI_CONTRACT_MISMATCH);
}

static void test_logits_and_probability_semantics(void)
{
    gs_ai_metadata_t metadata = test_metadata();
    fake_backend_context_t fake = { { 0 }, GS_AI_OK, 0U };
    gs_ai_backend_t backend = { &metadata, fake_infer, &fake };
    gs_ai_t ai;
    gs_ai_result_t result;
    uint32_t i;
    float sum;

    assert(gs_ai_init(&ai, &backend) == GS_AI_OK);
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_OK);
    assert(result.valid == 1U && result.top_index == GS_AI_POINT_LEFT);
    assert(fabsf(result.top_score - 1.0f / 6.0f) < 0.00001f);
    assert(result.margin == 0.0f);

    memset(fake.values, -128, sizeof(fake.values));
    fake.values[GS_AI_UNKNOWN] = 127;
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_OK);
    assert(result.top_index == GS_AI_UNKNOWN && result.top_score > 0.999f);
    sum = 0.0f;
    for (i = 0U; i < GS_AI_CLASS_COUNT; ++i) {
        sum += result.scores[i];
    }
    assert(fabsf(sum - 1.0f) < 0.00001f);

    metadata.output_kind = GS_AI_OUTPUT_INT8_PROBABILITIES;
    metadata.output_scale = 1.0f / 256.0f;
    metadata.output_zero_point = -128;
    /* 0.996 的概率归一化后为 1；若错误地再执行一次 Softmax 会得到约 0.31，
     * 因此此用例能检测输出语义是否被混淆。 */
    assert(gs_ai_init(&ai, &backend) == GS_AI_OK);
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_OK);
    assert(result.top_index == GS_AI_UNKNOWN && result.top_score == 1.0f);
    memset(fake.values, -128, sizeof(fake.values));
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_INVALID_OUTPUT);
    assert(result.valid == 0U);
    memset(fake.values, 127, sizeof(fake.values));
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_INVALID_OUTPUT);

    fake.status = GS_AI_BACKEND_FAILURE;
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_BACKEND_FAILURE);
    assert(result.valid == 0U);
    assert(gs_ai_run(&ai, output, sizeof(output) - 1U, &result) == GS_AI_INVALID_ARGUMENT);
    /* 将已初始化模型包改为原始五类模型时，应立即拒绝推理。 */
    metadata.output_count = 5U;
    i = fake.calls;
    assert(gs_ai_run(&ai, output, sizeof(output), &result) == GS_AI_CONTRACT_MISMATCH);
    assert(fake.calls == i && ai.ready == 0U);
}

int main(void)
{
    test_colors_and_quality();
    test_rounding_and_pre_average_quality();
    test_validation();
    test_model_gate_and_stub();
    test_logits_and_probability_semantics();
    puts("Vision tests passed: RGB565/RGB96 NHWC/ROI/rounding/quality/bounds/six-class gate/output semantics");
    return 0;
}
