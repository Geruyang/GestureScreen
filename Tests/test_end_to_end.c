/* 使用合成相机数据和模型输出验证完整软件链路。
 * 仅验证模块集成和渲染，不验证硬件或识别准确率。 */
#include "gs_ai.h"
#include "gs_camera_pool.h"
#include "gs_display_swap.h"
#include "gs_gesture.h"
#include "gs_preprocess.h"
#include "gs_preview.h"
#include "gs_ui.h"
#include "gs_ui_render.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define TEST_FRAME_BYTES (GS_CAMERA_WIDTH * GS_CAMERA_HEIGHT * 2U)
#define TEST_LCD_WIDTH 320U
#define TEST_LCD_HEIGHT 240U
#define TEST_LCD_PIXELS (TEST_LCD_WIDTH * TEST_LCD_HEIGHT)
#define TEST_LCD_BYTES (TEST_LCD_PIXELS * 2U)

static uint32_t camera_buffer0[TEST_FRAME_BYTES / 4U];
static uint32_t camera_buffer1[TEST_FRAME_BYTES / 4U];
static uint32_t display_buffer0[TEST_LCD_BYTES / 4U];
static uint32_t display_buffer1[TEST_LCD_BYTES / 4U];
static int8_t model_input[GS_AI_INPUT_SIZE];
static int8_t preview_input[GS_PREVIEW_SOURCE_BYTES];
static uint32_t preview_buffer0[GS_PREVIEW_BYTES / 4U];
static uint32_t preview_buffer1[GS_PREVIEW_BYTES / 4U];

typedef struct {
    gs_ai_class_t selected;
    uint32_t calls;
} synthetic_model_t;

static gs_ai_status_t synthetic_infer(void *context, const int8_t *input,
    size_t input_count, int8_t *output, size_t output_count)
{
    synthetic_model_t *model = (synthetic_model_t *)context;
    size_t index;
    assert(input != NULL && input_count == GS_AI_INPUT_SIZE);
    assert(output != NULL && output_count == GS_AI_CLASS_COUNT);
    for (index = 0U; index < output_count; ++index) {
        output[index] = -80;
    }
    output[model->selected] = 80;
    ++model->calls;
    return GS_AI_OK;
}

static const gs_ui_page_t test_pages0[] = {
    {"START", "SOFTWARE PIPELINE READY"}, {"NEXT", "SECOND PAGE"}
};
static const gs_ui_page_t test_pages1[] = {
    {"LAB", "INTEGRATION TEST"}, {"DONE", "RENDER COMPLETE"}
};
static const gs_ui_collection_t test_collections[] = {
    {"QUICK START", 2U, test_pages0}, {"LAB STEPS", 2U, test_pages1}
};

static uint32_t checksum(const uint16_t *pixels, size_t count)
{
    uint32_t value = UINT32_C(2166136261);
    size_t index;
    for (index = 0U; index < count; ++index) {
        value ^= pixels[index];
        value *= UINT32_C(16777619);
    }
    return value;
}

static gs_gesture_observation_t capture_and_infer(
    gs_camera_pool_t *camera, gs_ai_t *ai, synthetic_model_t *model,
    gs_ai_class_t selected, uint32_t capture_ms)
{
    gs_camera_ticket_t ticket;
    gs_camera_frame_t camera_frame;
    gs_rgb565_frame_t image;
    gs_ai_result_t result;
    gs_gesture_observation_t observation;
    void *destination = NULL;
    uint16_t *pixel;
    size_t index;

    assert(gs_camera_begin(camera, &ticket, &destination) == GS_CAMERA_OK);
    pixel = (uint16_t *)destination;
    for (index = 0U; index < TEST_FRAME_BYTES / 2U; ++index) {
        pixel[index] = 0x8410U; /* 中灰 RGB565 图像可通过调试质量阈值。 */
    }
    assert(gs_camera_report(camera, ticket,
        GS_CAMERA_EVENT_FRAME_END | GS_CAMERA_EVENT_DMA_DONE,
        TEST_FRAME_BYTES, 0U) == GS_CAMERA_OK);
    assert(gs_camera_finish_quiesced(camera, ticket, capture_ms, 0U) == GS_CAMERA_OK);
    assert(gs_camera_acquire_latest(camera, &camera_frame) == GS_CAMERA_OK);

    image.data = camera_frame.data;
    image.data_size = camera_frame.bytes;
    image.width = GS_CAMERA_WIDTH;
    image.height = GS_CAMERA_HEIGHT;
    image.stride_bytes = GS_CAMERA_WIDTH * 2U;
    image.byte_order = GS_RGB565_LSB_FIRST;
    assert(gs_preprocess_rgb565(&image, model_input, sizeof(model_input),
                                NULL, NULL) == GS_PREPROCESS_OK);
    assert(gs_camera_release(camera, camera_frame.ticket) == GS_CAMERA_OK);

    model->selected = selected;
    assert(gs_ai_run(ai, model_input, sizeof(model_input), &result) == GS_AI_OK);
    memset(&observation, 0, sizeof(observation));
    observation.frame_id = camera_frame.frame_id;
    observation.capture_ms = camera_frame.timestamp_ms;
    memcpy(observation.scores, result.scores, sizeof(observation.scores));
    observation.valid = result.valid != 0U;
    return observation;
}

static uint32_t render_and_swap(gs_display_swap_t *display, const gs_ui_t *ui)
{
    gs_display_composition_t composition;
    const void *pending = NULL;
    assert(gs_display_begin(display, &composition));
    memcpy(composition.back, composition.front, composition.bytes);
    assert(gs_display_copy_complete(display, composition.token));
    assert(gs_ui_render_rgb565(ui, (uint16_t *)composition.back,
        TEST_LCD_PIXELS, TEST_LCD_WIDTH, TEST_LCD_HEIGHT, TEST_LCD_WIDTH,
        NULL) == GS_UI_RENDER_OK);
    assert(gs_display_submit(display, composition.token, &pending));
    assert(pending == composition.back);
    assert(gs_display_reload_confirm(display, composition.token, pending));
    return checksum((const uint16_t *)pending, TEST_LCD_PIXELS);
}

int main(void)
{
    gs_camera_pool_t camera;
    gs_display_swap_t display;
    gs_gesture_t gesture;
    gs_ui_t ui;
    gs_ui_command_t command;
    gs_gesture_observation_t observation;
    synthetic_model_t model = { GS_AI_UNKNOWN, 0U };
    const gs_ai_metadata_t metadata = {
        GS_AI_CONTRACT_VERSION, "synthetic-integration-only", GS_PREPROCESS_VERSION,
        {1U,96U,96U,3U}, 1.0f, -128, GS_AI_CLASS_COUNT,
        {"POINT_LEFT","POINT_RIGHT","FIST","PALM","V_SIGN","UNKNOWN"},
        GS_AI_OUTPUT_INT8_LOGITS, 0.1f, 0, 1U
    };
    const gs_ai_backend_t backend = { &metadata, synthetic_infer, &model };
    gs_ai_t ai;
    gs_preview_pool_t preview_pool;
    gs_preview_frame_t preview;
    uint32_t before;
    uint32_t after;
    uint32_t time;

    memset(display_buffer0, 0, sizeof(display_buffer0));
    memset(display_buffer1, 0, sizeof(display_buffer1));
    assert(gs_camera_pool_init(&camera, camera_buffer0, sizeof(camera_buffer0),
        camera_buffer1, sizeof(camera_buffer1), TEST_FRAME_BYTES) == GS_CAMERA_OK);
    assert(gs_display_swap_init(&display, display_buffer0, sizeof(display_buffer0),
        display_buffer1, sizeof(display_buffer1), TEST_LCD_BYTES));
    assert(gs_gesture_init(&gesture, NULL));
    gs_gesture_set_enabled(&gesture, true);
    assert(gs_ui_init(&ui, test_collections, 2U, 1000U));
    assert(gs_ai_init(&ai, &backend) == GS_AI_OK);
    assert(gs_preview_pool_init(&preview_pool, preview_buffer0,
        sizeof(preview_buffer0), preview_buffer1,
        sizeof(preview_buffer1)) == GS_PREVIEW_OK);
    memset(preview_input, 3, sizeof preview_input); /* 0x8410 的灰度预览为 131。 */

    before = render_and_swap(&display, &ui);
    /* Full repaint must not depend on copying the previous framebuffer. */
    memset(display_buffer0, 0xa5, sizeof(display_buffer0));
    memset(display_buffer1, 0x5a, sizeof(display_buffer1));
    assert(gs_ui_render_rgb565(&ui, (uint16_t *)display_buffer0,
        TEST_LCD_PIXELS, TEST_LCD_WIDTH, TEST_LCD_HEIGHT, TEST_LCD_WIDTH,
        NULL) == GS_UI_RENDER_OK);
    assert(gs_ui_render_rgb565(&ui, (uint16_t *)display_buffer1,
        TEST_LCD_PIXELS, TEST_LCD_WIDTH, TEST_LCD_HEIGHT, TEST_LCD_WIDTH,
        NULL) == GS_UI_RENDER_OK);
    assert(memcmp(display_buffer0, display_buffer1, sizeof(display_buffer0)) == 0);
    for (time = 0U; time <= 600U; time += 200U) {
        observation = capture_and_infer(&camera, &ai, &model, GS_AI_UNKNOWN, time);
        assert(gs_preview_publish(&preview_pool, preview_input, sizeof(preview_input),
                                  observation.frame_id, observation.capture_ms,
                                  &preview) == GS_PREVIEW_OK);
        assert(preview.bytes == GS_PREVIEW_BYTES && preview.pixels[0] == 131U);
        assert(gs_ui_render_preview_rgb565((uint16_t *)display_buffer0,
            TEST_LCD_PIXELS, TEST_LCD_WIDTH, TEST_LCD_HEIGHT, TEST_LCD_WIDTH,
            &preview) == GS_UI_RENDER_OK);
        assert(gs_preview_release(&preview_pool, preview.ticket) == GS_PREVIEW_OK);
        assert(!gs_gesture_process(&gesture, &observation, time,
                                   ui.generation, &command));
    }
    assert(gesture.state == GS_GESTURE_READY);
    for (time = 800U; time <= 1200U; time += 200U) {
        observation = capture_and_infer(&camera, &ai, &model,
                                        GS_AI_POINT_LEFT, time);
        assert(gs_preview_publish(&preview_pool, preview_input, sizeof(preview_input),
                                  observation.frame_id, observation.capture_ms,
                                  &preview) == GS_PREVIEW_OK);
        assert(gs_preview_release(&preview_pool, preview.ticket) == GS_PREVIEW_OK);
        if (time < 1200U) {
            assert(!gs_gesture_process(&gesture, &observation, time,
                                       ui.generation, &command));
        } else {
            assert(gs_gesture_process(&gesture, &observation, time,
                                      ui.generation, &command));
        }
    }
    assert(command.action == GS_UI_NEXT);
    assert(gs_ui_execute(&ui, &command, 1200U) == GS_UI_APPLIED);
    assert(ui.selected == 1U);
    after = render_and_swap(&display, &ui);
    assert(before != after);
    assert(model.calls == 7U);
    assert(gs_preview_release(&preview_pool, preview.ticket) == GS_PREVIEW_STALE);

    assert(gs_ui_render_rgb565(&ui, (uint16_t *)display_buffer0,
        TEST_LCD_PIXELS - 1U, TEST_LCD_WIDTH, TEST_LCD_HEIGHT, TEST_LCD_WIDTH,
        NULL) == GS_UI_RENDER_BUFFER_TOO_SMALL);
    puts("end-to-end: camera ownership, preprocess, AI gate, gesture, UI, render and display swap passed");
    return 0;
}
