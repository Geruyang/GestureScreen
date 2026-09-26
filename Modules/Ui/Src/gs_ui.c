/* 阅读器状态：书架、书籍目录、阅读页，不依赖实际显示驱动。
 * 成功操作更新 generation，使旧界面上形成的手势不能误作用于新界面。 */
#include "gs_ui.h"

#include <stddef.h>
#include <string.h>

bool gs_ui_init(gs_ui_t *ui, const gs_ui_collection_t *collections,
                uint16_t collection_count, uint32_t autoplay_interval_ms)
{
    uint16_t index;
    if (ui == NULL) {
        return false;
    }
    memset(ui, 0, sizeof(*ui));
    if ((collection_count != 0U && collections == NULL) ||
        autoplay_interval_ms == 0U || autoplay_interval_ms >= UINT32_C(0x80000000)) {
        return false;
    }
    for (index = 0U; index < collection_count; ++index) {
        if (collections[index].title == NULL || collections[index].page_count == 0U) {
            return false;
        }
        if (collections[index].kind > GS_UI_COLLECTION_DIAGNOSTICS) {
            return false;
        }
        if (collections[index].pages != NULL) {
            uint16_t page;
            for (page = 0U; page < collections[index].page_count; ++page) {
                if (collections[index].pages[page].title == NULL ||
                    collections[index].pages[page].body == NULL) {
                    return false;
                }
            }
        }
    }
    ui->collections = collections;
    ui->collection_count = collection_count;
    ui->mode = GS_UI_DIRECTORY;
    ui->generation = 1U;
    ui->autoplay_interval_ms = autoplay_interval_ms;
    ui->recognition_enabled = true;
    ui->initialized = true;
    return true;
}

bool gs_ui_action_available(const gs_ui_t *ui, gs_ui_action_t action)
{
    if (ui == NULL || !ui->initialized || ui->collection_count == 0U) {
        return false;
    }
    switch (action) {
    case GS_UI_PREVIOUS:
        return ui->mode == GS_UI_DIRECTORY ? ui->selected > 0U :
            ui->mode == GS_UI_CATALOG ? ui->chapter > 0U : ui->page > 0U;
    case GS_UI_NEXT:
        return ui->mode == GS_UI_DIRECTORY ?
               ui->selected + 1U < ui->collection_count :
               ui->mode == GS_UI_CATALOG ?
               ui->chapter + 1U < ui->collections[ui->selected].page_count :
               ui->page + 1U < ui->collections[ui->selected].page_count;
    case GS_UI_ENTER:
        return ui->mode != GS_UI_READER;
    case GS_UI_UP:
        return ui->mode != GS_UI_DIRECTORY;
    case GS_UI_HOME:
        return ui->mode != GS_UI_DIRECTORY;
    default:
        return false;
    }
}

gs_ui_result_t gs_ui_local_action(gs_ui_t *ui, gs_ui_action_t action,
                                  uint32_t now_ms)
{
    if (ui == NULL || !ui->initialized) {
        return GS_UI_BAD_ARGUMENT;
    }
    if (!gs_ui_action_available(ui, action)) {
        return GS_UI_REJECTED_UNAVAILABLE;
    }
    switch (action) {
    case GS_UI_PREVIOUS:
        if (ui->mode == GS_UI_DIRECTORY) {
            --ui->selected;
        } else if (ui->mode == GS_UI_CATALOG) {
            --ui->chapter;
        } else {
            --ui->page;
        }
        break;
    case GS_UI_NEXT:
        if (ui->mode == GS_UI_DIRECTORY) {
            ++ui->selected;
        } else if (ui->mode == GS_UI_CATALOG) {
            ++ui->chapter;
        } else {
            ++ui->page;
        }
        break;
    case GS_UI_ENTER:
        if (ui->mode == GS_UI_DIRECTORY) {
            ui->mode = GS_UI_CATALOG;
            ui->chapter = 0U;
        } else {
            ui->mode = GS_UI_READER;
            ui->page = ui->chapter;
        }
        break;
    case GS_UI_UP:
        if (ui->mode == GS_UI_READER) {
            ui->mode = GS_UI_CATALOG;
            ui->chapter = ui->page;
        } else {
            ui->mode = GS_UI_DIRECTORY;
        }
        break;
    case GS_UI_HOME:
        ui->mode = GS_UI_DIRECTORY;
        break;
    default:
        return GS_UI_REJECTED_UNAVAILABLE;
    }
    ui->last_advance_ms = now_ms;
    ++ui->generation;
    return GS_UI_APPLIED;
}

gs_ui_result_t gs_ui_execute(gs_ui_t *ui, const gs_ui_command_t *command,
                             uint32_t now_ms)
{
    uint32_t delta;
    if (ui == NULL || !ui->initialized || command == NULL || command->sequence == 0U) {
        return GS_UI_BAD_ARGUMENT;
    }
    delta = command->sequence - ui->last_command_sequence;
    if (ui->have_command_sequence &&
        (delta == 0U || delta >= UINT32_C(0x80000000))) {
        return GS_UI_REJECTED_DUPLICATE;
    }
    /* 被拒绝的命令也消耗序号，防止重试时改变其原本含义。 */
    ui->last_command_sequence = command->sequence;
    ui->have_command_sequence = true;
    if (command->ui_generation != ui->generation) {
        return GS_UI_REJECTED_STALE;
    }
    return gs_ui_local_action(ui, command->action, now_ms);
}

bool gs_ui_tick(gs_ui_t *ui, uint32_t now_ms)
{
    (void)ui;
    (void)now_ms;
    return false; /* 阅读器没有自动翻页，握拳手势回书架。 */
}
