#ifndef GS_PORT_H
#define GS_PORT_H
#include <stdint.h>
#include "gs_ai.h"
#include "gs_preview.h"
#include "gs_ui.h"
#include "gs_ui_render.h"

typedef enum {
    GS_PORT_OK = 0, GS_PORT_UNAVAILABLE, GS_PORT_BUSY, GS_PORT_ERROR
} gs_port_status_t;

typedef struct {
    gs_rgb565_frame_t image;
    uint32_t frame_id; /* 跨相机恢复保持单调递增，不能在恢复时重置为 0。 */
    uint32_t capture_ms; /* 实际完整帧完成时记录的 HAL_GetTick() 毫秒值。 */
    uint32_t camera_publish_ms; /* CameraTask 成功投递 latest mailbox 前的时间。 */
    uint32_t lease_token;
    uint32_t slot;
} gs_port_frame_t;

void gs_port_init(void);
/* 仅 CameraTask 调用，poll 必须非阻塞，只交付完整且归 CPU 持有的帧。
 * 使用 Modules/Camera 管理 FREE 到 PROCESSING 的所有权转换。
 * poll 消费带采集标识的 ISR 消息，确认硬件停止写入后才能发布 READY。
 * 错误或中止时，必须停止 DMA 并处理完相关中断，才可复用采集缓冲。
 * 禁止采集到 CCM 或 LCD 缓冲；归还租约后禁止保留原图指针。 */
gs_port_status_t gs_port_camera_poll(gs_port_frame_t *frame);
void gs_port_camera_release(const gs_port_frame_t *frame);
/* 仅 GuiTask 调用；RGB565 软件渲染器和 LTDC 双缓冲。
 * 使用 Modules/Display；局部绘制前先同步前缓冲到后缓冲，
 * 确认真实垂直消隐重载完成后才释放旧前缓冲。
 * 此调用不得阻塞等待 I/O，也不能持有任何相机原图指针。 */
/* preview 仅在本次调用期间有效；适配层必须在返回前完成绘制或复制，
 * 不能保存该指针。NULL 表示当前没有新预览。 */
gs_port_status_t gs_port_gui_render(const gs_ui_t *ui,
                                    const gs_preview_frame_t *preview);
/* GUI-only setter, copied immediately; affects dashboard repaint decisions. */
void gs_port_gui_set_status(const gs_ui_live_status_t *status);
/* 仅 StorageTask 调用；单次服务耗时有界且非阻塞，无存储卡属于正常状态。 */
gs_port_status_t gs_port_storage_step(void);
/* 由实际生成的六类模型运行时适配层提供，元数据必须保持只读。 */
const gs_ai_backend_t *gs_port_model_backend(void);
/* 仅在全部六个任务的心跳满足期限时调用；IWDG参数来自 .ioc。
 * 不能在 ISR 中无条件喂狗。 */
void gs_port_watchdog_refresh(void);
#endif
