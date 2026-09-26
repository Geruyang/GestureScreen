#include "gs_content.h"
#include "gs_ui_render.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WIDTH 800U
#define HEIGHT 480U
#define PIXELS (WIDTH * HEIGHT)

static uint16_t full[PIXELS];
static uint16_t clipped[PIXELS];

static void screenshot(const char *name, const gs_ui_t *ui, int hint_class)
{
    gs_ui_live_status_t live;
    FILE *output;
    memset(&live, 0, sizeof(live));
    live.control_enabled = 1U;
    live.gesture_state = GS_GESTURE_READY;
    if (hint_class >= 0) { live.hint_valid = 1U; live.hint_class = (uint32_t)hint_class; }
    assert(gs_ui_render_dashboard_rgb565(ui, &live, full, PIXELS,
        WIDTH, HEIGHT, WIDTH, NULL) == GS_UI_RENDER_OK);
    assert(fopen_s(&output, name, "wb") == 0 && output != NULL);
    assert(fwrite(full, sizeof(full[0]), PIXELS, output) == PIXELS);
    assert(fclose(output) == 0);
}

int main(void)
{
    gs_ui_t ui;
    gs_ui_command_t command;
    gs_ui_live_status_t live;
    gs_ui_render_region_t region = {0U, 422U, 800U, 58U};
    uint32_t generation;
    size_t i;
    const gs_content_package_t *package = &g_gs_content_builtin_package;
    assert(package->collection_count == 3U);
    assert(package->collections[0].page_count > 1U);
    assert(gs_ui_init(&ui, package->collections, package->collection_count, 3000U));
    assert(ui.mode == GS_UI_DIRECTORY && ui.selected == 0U);
    assert(!gs_ui_action_available(&ui, GS_UI_PREVIOUS));
    assert(!gs_ui_action_available(&ui, GS_UI_HOME));
    screenshot("reader-shelf.rgb565", &ui, -1);
    assert(full[171U * WIDTH + 34U] == 0xFFDFU);
    assert(full[171U * WIDTH + 281U] != 0xFFDFU);

    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 1U) == GS_UI_APPLIED);
    assert(ui.selected == 1U);
    screenshot("reader-shelf-selected2.rgb565", &ui, -1);
    assert(full[171U * WIDTH + 281U] == 0xFFDFU);
    assert(full[171U * WIDTH + 34U] != 0xFFDFU);
    assert(gs_ui_local_action(&ui, GS_UI_PREVIOUS, 2U) == GS_UI_APPLIED);
    assert(ui.selected == 0U);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 3U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_CATALOG && ui.chapter == 0U);
    screenshot("reader-catalog.rgb565", &ui, -1);
    assert(full[147U * WIDTH + 306U] == 0x2C8CU);
    assert(full[201U * WIDTH + 306U] == 0xFFDFU);
    screenshot("reader-hint.rgb565", &ui, GS_STATIC_V_SIGN);
    screenshot("reader-direction-left.rgb565", &ui, GS_STATIC_POINT_LEFT);

    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 4U) == GS_UI_APPLIED);
    assert(ui.chapter == 1U);
    screenshot("reader-catalog-selected2.rgb565", &ui, -1);
    assert(full[147U * WIDTH + 306U] == 0xFFDFU);
    assert(full[201U * WIDTH + 306U] == 0x2C8CU);
    screenshot("reader-direction-right.rgb565", &ui, GS_STATIC_POINT_RIGHT);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 5U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_READER && ui.page == 1U);
    screenshot("reader-reading.rgb565", &ui, -1);
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 6U) == GS_UI_APPLIED);
    assert(ui.page == 2U);
    assert(gs_ui_local_action(&ui, GS_UI_PREVIOUS, 7U) == GS_UI_APPLIED);
    assert(ui.page == 1U);
    generation = ui.generation;
    assert(!gs_ui_tick(&ui, 100000U));
    assert(ui.generation == generation && ui.page == 1U);

    memset(&command, 0, sizeof(command));
    command.action = GS_UI_UP;
    command.sequence = 1U;
    command.ui_generation = ui.generation;
    assert(gs_ui_execute(&ui, &command, 8U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_CATALOG && ui.chapter == 1U);
    assert(gs_ui_execute(&ui, &command, 9U) == GS_UI_REJECTED_DUPLICATE);
    command.sequence = 2U;
    assert(gs_ui_execute(&ui, &command, 10U) == GS_UI_REJECTED_STALE);
    command.sequence = 3U;
    command.ui_generation = ui.generation;
    assert(gs_ui_execute(&ui, &command, 11U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_DIRECTORY);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 12U) == GS_UI_APPLIED);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 13U) == GS_UI_APPLIED);
    assert(gs_ui_local_action(&ui, GS_UI_HOME, 14U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_DIRECTORY);

    memset(&live, 0, sizeof(live));
    live.control_enabled = 1U;
    live.gesture_state = GS_GESTURE_READY;
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, full, PIXELS,
        WIDTH, HEIGHT, WIDTH, NULL) == GS_UI_RENDER_OK);
    memcpy(clipped, full, sizeof(full));
    live.gesture_state = GS_GESTURE_WAIT_CLEAR;
    assert(gs_ui_render_dashboard_regions_rgb565(&ui, &live, clipped, PIXELS,
        WIDTH, HEIGHT, WIDTH, NULL, &region, 1U) == GS_UI_RENDER_OK);
    assert(gs_ui_render_dashboard_rgb565(&ui, &live, full, PIXELS,
        WIDTH, HEIGHT, WIDTH, NULL) == GS_UI_RENDER_OK);
    for (i = 0U; i < PIXELS; ++i) { assert(full[i] == clipped[i]); }
    puts("PASS: reader navigation, generation/dedup, no autoplay, clipped footer and frames");
    return 0;
}
