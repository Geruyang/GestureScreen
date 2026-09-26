/* Reader composition on guarded 800x480 RGB565 buffers; no hardware. */
#include "gs_ui_render.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define W 800U
#define H 480U
#define STRIDE 804U
#define SIZE (H * STRIDE + 2U)

static uint16_t image[SIZE], expected[SIZE];
static const gs_ui_page_t pages[] = {
    {"第1页", "山不在高，有仙则名。水不在深，有龙则灵。"},
    {"第2页", "苔痕上阶绿，草色入帘青。谈笑有鸿儒。"}
};
static const gs_ui_collection_t books[] = {
    {"陋室铭", 2U, pages, GS_UI_COLLECTION_CONTENT, "刘禹锡"}
};

static void guards(void)
{
    unsigned y, x;
    assert(image[0] == 0xA5A5U && image[SIZE - 1U] == 0xA5A5U);
    for (y = 0U; y < H; ++y) for (x = W; x < STRIDE; ++x) {
        assert(image[1U + y * STRIDE + x] == 0xA5A5U);
    }
}

int main(void)
{
    gs_ui_t ui;
    gs_ui_live_status_t live;
    gs_ui_render_theme_t theme = gs_ui_render_default_theme();
    gs_ui_render_region_t footer = {0U, 436U, W, 44U};
    gs_ui_render_region_t header = {490U, 0U, 310U, 68U};
    gs_ui_hint_cache_t cache = {0};
    gs_static_result_t result = {0};
    uint16_t old_header_pixel;
    assert(gs_ui_init(&ui, books, 1U, 3000U));
    memset(&live, 0, sizeof(live));
    live.control_enabled = 1U;
    live.gesture_state = GS_GESTURE_READY;
    memset(image, 0xA5, sizeof(image));
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    guards();
    assert(image[1U] == theme.surface);
    assert(image[1U + 70U * STRIDE] == theme.background);
    /* Even at the first-book boundary RIGHT remains a qualified recognition;
       the header describes the boundary without implying navigation ran. */
    old_header_pixel = image[1U + 12U * STRIDE + 510U];
    live.hint_valid = 1U; live.hint_class = GS_STATIC_POINT_RIGHT;
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    assert(image[1U + 12U * STRIDE + 510U] != old_header_pixel);
    live.hint_valid = 0U;
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    memcpy(expected, image, sizeof(image));
    live.camera_frames = 9999U;
    live.preview_frame_id = 42U;
    live.recognition.confidence_permille = 999U;
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    assert(memcmp(image, expected, sizeof(image)) == 0);

    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 1U) == GS_UI_APPLIED);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    assert(memcmp(image, expected, sizeof(image)) != 0);
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 2U) == GS_UI_APPLIED);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 3U) == GS_UI_APPLIED);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    guards();
    memcpy(expected, image, sizeof(image));

    live.gesture_state = GS_GESTURE_WAIT_CLEAR;
    assert(gs_ui_render_dashboard_regions_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL, &footer, 1U) == GS_UI_RENDER_OK);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, expected + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    assert(memcmp(image, expected, sizeof(image)) == 0);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE - 5U, W, H, STRIDE, NULL) == GS_UI_RENDER_BUFFER_TOO_SMALL);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, W - 1U, NULL) == GS_UI_RENDER_INVALID_ARGUMENT);
    assert(gs_ui_render_dashboard_regions_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL, NULL, 1U) == GS_UI_RENDER_INVALID_ARGUMENT);
    /* A completed qualified target appears; RUNNING retains it only while
       fresh. Terminal UNKNOWN/uncertain clears immediately and expiry is
       independent of the recognition module's longer diagnostic TTL. */
    result.status = GS_STATIC_IDENTIFIED;
    result.class_index = GS_STATIC_POINT_RIGHT;
    result.frame_id = 5U; result.capture_ms = 1000U;
    result.confidence_permille = 950U; result.margin_permille = 250U;
    gs_ui_hint_update(&cache, &result, 1100U, 1U, &live);
    assert(live.hint_valid && live.hint_class == GS_STATIC_POINT_RIGHT);
    old_header_pixel = image[1U + 12U * STRIDE + 510U];
    memcpy(expected, image, sizeof(image));
    assert(gs_ui_render_dashboard_regions_rgb565(&ui, &live, image + 1U,
        H * STRIDE, W, H, STRIDE, NULL, &header, 1U) == GS_UI_RENDER_OK);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, expected + 1U,
        H * STRIDE, W, H, STRIDE, NULL) == GS_UI_RENDER_OK);
    assert(memcmp(image, expected, sizeof(image)) == 0);
    assert(image[1U + 12U * STRIDE + 510U] != old_header_pixel);
    result.status = GS_STATIC_RUNNING; result.frame_id = 6U;
    gs_ui_hint_update(&cache, &result, 1200U, 1U, &live);
    assert(live.hint_valid && live.hint_class == GS_STATIC_POINT_RIGHT);
    result.status = GS_STATIC_IDENTIFIED; result.class_index = GS_STATIC_FIST;
    result.confidence_permille = 920U; result.margin_permille = 220U;
    gs_ui_hint_update(&cache, &result, 1210U, 1U, &live);
    assert(live.hint_valid && live.hint_class == GS_STATIC_FIST);
    result.status = GS_STATIC_NO_TARGET; result.class_index = GS_STATIC_UNKNOWN; result.frame_id = 7U;
    gs_ui_hint_update(&cache, &result, 1220U, 1U, &live);
    assert(!live.hint_valid);
    result.status = GS_STATIC_IDENTIFIED; result.class_index = GS_STATIC_FIST;
    result.frame_id = 8U; result.capture_ms = 1250U;
    result.confidence_permille = 990U; result.margin_permille = 100U;
    gs_ui_hint_update(&cache, &result, 1260U, 1U, &live);
    assert(!live.hint_valid);
    result.margin_permille = 300U; result.frame_id = 9U;
    gs_ui_hint_update(&cache, &result, 1270U, 1U, &live);
    assert(live.hint_valid && live.hint_class == GS_STATIC_FIST);
    gs_ui_hint_update(&cache, &result, 1551U, 1U, &live);
    assert(!live.hint_valid);
    puts("PASS: Chinese reader, 4-bit hint pixels, fresh/new/expired/UNKNOWN gates, stride guards and clipped regions");
    return 0;
}
