#ifndef GS_UI_H
#define GS_UI_H

#include "gs_gesture.h"

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    const char *title;
    const char *body;
} gs_ui_page_t;

typedef enum {
    GS_UI_COLLECTION_CONTENT = 0,
    GS_UI_COLLECTION_SETTINGS,
    GS_UI_COLLECTION_DIAGNOSTICS
} gs_ui_collection_kind_t;

typedef struct {
    const char *title;
    uint16_t page_count;
    /* 只读页面正文；阅读器的目录/正文绘制需要非 NULL。 */
    const gs_ui_page_t *pages;
    /* Author appears below each book title in the reader. */
    gs_ui_collection_kind_t kind;
    const char *author;
} gs_ui_collection_t;

typedef enum {
    GS_UI_DIRECTORY = 0, /* 书架首页 */
    GS_UI_CATALOG,       /* 当前书籍的篇目目录 */
    GS_UI_READER
} gs_ui_mode_t;

typedef enum {
    GS_UI_APPLIED = 0,
    GS_UI_REJECTED_DUPLICATE,
    GS_UI_REJECTED_STALE,
    GS_UI_REJECTED_UNAVAILABLE,
    GS_UI_BAD_ARGUMENT
} gs_ui_result_t;

typedef struct {
    const gs_ui_collection_t *collections;
    uint16_t collection_count;
    uint16_t selected;
    uint16_t chapter;
    uint16_t page;
    gs_ui_mode_t mode;
    uint32_t generation;
    uint32_t last_command_sequence;
    uint32_t autoplay_interval_ms;
    uint32_t last_advance_ms;
    bool playing;
    bool recognition_enabled;
    bool initialized;
    bool have_command_sequence;
} gs_ui_t;

/* 集合与可选页面内容必须保持只读，且生命周期覆盖此上下文。
 * 允许空目录；业务模型不持有渲染对象或图像缓冲。 */
bool gs_ui_init(gs_ui_t *ui, const gs_ui_collection_t *collections,
                uint16_t collection_count, uint32_t autoplay_interval_ms);
bool gs_ui_action_available(const gs_ui_t *ui, gs_ui_action_t action);
/* 这些 API 仅由 GuiTask 调用，将代际检查、操作可用性检查和业务更新串行执行。
 * 返回 STALE 时通知手势任务要求撤手；禁止修改旧命令代际后重放。
 * 每个 UI 实例只接收一条手势命令流。重初始化生产者时，
 * 必须一并重置/清空队列和 UI 序号状态。 */
gs_ui_result_t gs_ui_execute(gs_ui_t *ui, const gs_ui_command_t *command,
                             uint32_t now_ms);
/* 触摸/按键备用输入绕过手势命令序号，但会更新界面代际，
 * 使旧代际的候选手势和已排队命令失效。 */
gs_ui_result_t gs_ui_local_action(gs_ui_t *ui, gs_ui_action_t action,
                                  uint32_t now_ms);
/* 阅读器不自动翻页；保留此入口供现有 GUI 调度调用。 */
bool gs_ui_tick(gs_ui_t *ui, uint32_t now_ms);

#endif
