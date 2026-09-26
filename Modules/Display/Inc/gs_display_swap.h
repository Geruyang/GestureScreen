#ifndef GS_DISPLAY_SWAP_H
#define GS_DISPLAY_SWAP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    GS_DISPLAY_IDLE = 0,
    GS_DISPLAY_COPYING,
    GS_DISPLAY_DRAWING,
    GS_DISPLAY_PENDING
} gs_display_state_t;

typedef struct {
    uint32_t token;
    const uint8_t *front;
    uint8_t *back;
    size_t bytes;
} gs_display_composition_t;

typedef struct {
    uint8_t *buffers[2];
    size_t frame_bytes;
    uint32_t next_token;
    uint32_t active_token;
    uint8_t front_index;
    gs_display_state_t state;
    bool initialized;
} gs_display_swap_t;

/* Ordinary live status is coalesced with the next camera preview. If the
 * preview stream stops, publish the last terminal/status update within this
 * bounded grace period rather than retaining an old screen until TTL expiry. */
#define GS_DISPLAY_REFRESH_GRACE_MS 250U

enum {
    GS_DISPLAY_REFRESH_NONE = 0U,
    GS_DISPLAY_REFRESH_INITIAL = 1U << 0,
    GS_DISPLAY_REFRESH_PREVIEW = 1U << 1,
    GS_DISPLAY_REFRESH_GENERATION = 1U << 2,
    GS_DISPLAY_REFRESH_CRITICAL = 1U << 3,
    GS_DISPLAY_REFRESH_GRACE = 1U << 4
};

typedef struct {
    uint32_t now_ms;
    uint32_t generation;
    uint32_t preview_id;
    uint32_t preview_capture_ms;
    uint32_t display_errors;
    uint32_t inference_errors;
    uint32_t inference_timeouts;
    uint32_t content_checked;
    uint32_t content_errors;
    bool preview_visible;
    bool healthy;
    bool control_enabled;
    bool camera_fault;
    bool display_stalled;
    bool inference_fault;
    bool result_stale;
    bool ordinary_changed;
} gs_display_refresh_input_t;

typedef struct {
    gs_display_refresh_input_t committed;
    uint32_t ordinary_since_ms;
    bool initialized;
    bool ordinary_pending;
} gs_display_refresh_t;

/* GuiTask is the sole caller. observe may latch an ordinary pending update but
 * never consumes a reason. Call commit only after a complete frame has been
 * accepted for LTDC reload. BUSY/error paths therefore retain every edge. */
uint32_t gs_display_refresh_observe(gs_display_refresh_t *refresh,
                                   const gs_display_refresh_input_t *input);
void gs_display_refresh_commit(gs_display_refresh_t *refresh,
                               const gs_display_refresh_input_t *input);

/* 全部调用由 GuiTask 串行执行；LTDC/DMA2D ISR 只投递有界完成消息。
 * 模块没有内部锁，硬件配置由 BSP 完成。两块缓冲必须互不重叠、
 * 容量至少为 frame_bytes、4 字节对齐、已初始化且可被 LTDC/DMA2D 访问，禁止 CCM。
 * 初始化前确保 LTDC 已扫描 buffer0，或处于停止状态并配置为从 buffer0 开始。
 * 只有硬件停止后才允许重新初始化。返回 false 时不转移缓冲所有权。 */
bool gs_display_swap_init(gs_display_swap_t *swap,
                          void *buffer0, size_t capacity0,
                          void *buffer1, size_t capacity1, size_t frame_bytes);

/* 锁定后缓冲以准备合成；增量绘制先将前缓冲复制到后缓冲，
 * 等待复制完成后再调用 copy_complete。完整重绘可跳过复制并直接
 * 调用 copy_complete，但 submit 前必须覆盖整个后缓冲。 */
bool gs_display_begin(gs_display_swap_t *swap,
                      gs_display_composition_t *composition);
bool gs_display_copy_complete(gs_display_swap_t *swap, uint32_t token);

/* copy_complete 之后将全部脏区域画入后缓冲，等待绘制及 DMA2D 完成。
 * submit 将后缓冲设为只读，并返回供 LTDC 垂直消隐重载的地址；不能逐条带提交。
 * 若硬件重载请求失败，保持 PENDING，由 BSP 重试或恢复。 */
bool gs_display_submit(gs_display_swap_t *swap, uint32_t token,
                       const void **pending_front);

/* submit 已冻结后缓冲，但 BSP 尚未成功 arm 硬件 reload 时的唯一回滚入口。
 * 调用者必须传回 submit 返回的精确地址，并证明没有 reload 在飞；已经 arm 或
 * 可能完成的请求只能走 reload_confirm，不能用本函数夺回前后缓冲所有权。 */
bool gs_display_submit_abort_unarmed(gs_display_swap_t *swap, uint32_t token,
                                     const void *pending_front);

/* 仅当本次提交的 LTDC 重载已确认、实际活动帧地址也匹配时，才能释放旧前缓冲。
 * 普通 VSYNC 事件或写入影子寄存器都不能作为确认。
 * 排队的 IRQ 报告必须携带提交时固定的 token，不能在后续处理时重新读取新 token。 */
bool gs_display_reload_confirm(gs_display_swap_t *swap, uint32_t token,
                               const void *active_front);

/* 只能在 submit 前且复制/绘制引擎已空闲时取消。
 * PENDING 不可取消，因为硬件可能已经切换到新缓冲。 */
bool gs_display_cancel_quiesced(gs_display_swap_t *swap, uint32_t token);

#ifdef __cplusplus
}
#endif
#endif
