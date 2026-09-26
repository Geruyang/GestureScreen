/* Reader's two framebuffer histories and footer-only updates. */
#include "gs_ui_render.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define PIXELS (800U * 480U)
static uint16_t buffers[2][PIXELS], expected[PIXELS];
static const gs_ui_page_t pages[] = {
    {"第1页", "山不在高，有仙则名。水不在深，有龙则灵。"},
    {"第2页", "苔痕上阶绿，草色入帘青。谈笑有鸿儒。"}
};
static const gs_ui_collection_t books[] = {
    {"陋室铭", 2U, pages, GS_UI_COLLECTION_CONTENT, "刘禹锡"}
};
static const gs_ui_render_region_t footer = {0U, 422U, 800U, 58U};

static void full(uint16_t *buffer, const gs_ui_t *ui, const gs_ui_live_status_t *live)
{
    assert(gs_ui_render_dashboard_rgb565(ui, live, buffer, PIXELS,
        800U, 480U, 800U, NULL) == GS_UI_RENDER_OK);
}

static void partial_matches_full(uint16_t *buffer, const gs_ui_t *ui,
    const gs_ui_live_status_t *live)
{
    full(expected, ui, live);
    assert(gs_ui_render_dashboard_regions_rgb565(ui, live, buffer, PIXELS,
        800U, 480U, 800U, NULL, &footer, 1U) == GS_UI_RENDER_OK);
    assert(memcmp(buffer, expected, sizeof(expected)) == 0);
}

int main(void)
{
    gs_ui_t ui;
    gs_ui_live_status_t live;
    unsigned mode;
    assert(gs_ui_init(&ui, books, 1U, 3000U));
    memset(&live, 0, sizeof(live));
    live.control_enabled = 1U;
    for (mode = 0U; mode < 3U; ++mode) {
        unsigned state;
        if (mode == 1U || mode == 2U) {
            assert(gs_ui_local_action(&ui, GS_UI_ENTER, mode) == GS_UI_APPLIED);
        }
        live.gesture_state = GS_GESTURE_READY;
        full(buffers[0], &ui, &live);
        full(buffers[1], &ui, &live);
        for (state = 0U; state < 4U; ++state) {
            uint16_t *buffer = buffers[state % 2U];
            live.gesture_state = state % 2U ? GS_GESTURE_WAIT_CLEAR : GS_GESTURE_CANDIDATE;
            live.recognition.status = state == 3U ? GS_STATIC_TIMEOUT : GS_STATIC_IDENTIFIED;
            partial_matches_full(buffer, &ui, &live);
        }
    }
    puts("PASS: reader footer incremental composition equals full frame on both LCD buffers");
    return 0;
}
