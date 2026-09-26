#ifndef GS_CAMERA_POOL_H
#define GS_CAMERA_POOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GS_CAMERA_SLOTS 2u
#define GS_CAMERA_EVENT_FRAME_END (1u << 0)
#define GS_CAMERA_EVENT_DMA_DONE  (1u << 1)

typedef enum {
    GS_CAMERA_FREE = 0,
    GS_CAMERA_CAPTURING,
    GS_CAMERA_READY,
    GS_CAMERA_PROCESSING
} gs_camera_state_t;

typedef enum {
    GS_CAMERA_OK = 0,
    GS_CAMERA_INVALID,
    GS_CAMERA_BUSY,
    GS_CAMERA_STALE,
    GS_CAMERA_INCOMPLETE,
    GS_CAMERA_ERROR,
    GS_CAMERA_TOKEN_EXHAUSTED
} gs_camera_result_t;

typedef struct {
    uint32_t token;
    uint8_t slot;
} gs_camera_ticket_t;

typedef struct {
    gs_camera_ticket_t ticket;
    const uint8_t *data;
    size_t bytes;
    uint32_t frame_id;
    uint32_t timestamp_ms;
} gs_camera_frame_t;

typedef struct {
    uint8_t *data;
    gs_camera_state_t state;
    uint32_t token;
    uint32_t events;
    uint32_t errors;
    size_t received_bytes;
    uint32_t timestamp_ms;
} gs_camera_slot_t;

typedef struct {
    gs_camera_slot_t slots[GS_CAMERA_SLOTS];
    size_t frame_bytes;
    uint32_t next_token;
    bool initialized;
} gs_camera_pool_t;

/* 所有调用（包括事件上报和租约归还）均由 CameraTask 串行执行。
 * ISR 只向有界队列投递消息，并携带本次采集开始时锁定的 ticket；
 * VisionTask 通过 CameraTask 请求获取/归还帧。队列溢出视为采集失败，
 * 必须停止硬件、清空采集事件后调用 abort_quiesced。
 * 本模块不含内部同步，任何接口都不能直接从 ISR 调用，详见 Camera/README.md。 */

/* 两块缓冲必须互不重叠、容量至少为 frame_bytes、4 字节对齐且可供 DMA 访问
 * （例如已初始化的 SDRAM，禁止 CCM）。帧池仅保存元数据。
 * 当前 DCMI 方案要求 frame_bytes 非零且为 4 的倍数。
 * 仅在硬件与消费者全部停止时初始化一次。 */
gs_camera_result_t gs_camera_pool_init(gs_camera_pool_t *pool,
                                      void *buffer0, size_t capacity0,
                                      void *buffer1, size_t capacity1,
                                      size_t frame_bytes);

/* 仅预留 FREE 槽，同一时刻最多允许一次 snapshot 采集；不覆盖 READY/PROCESSING。
 * 成功返回的缓冲是本次 DMA 唯一允许写入的目标。 */
gs_camera_result_t gs_camera_begin(gs_camera_pool_t *pool,
                                  gs_camera_ticket_t *ticket, void **buffer);

/* DMA_DONE 上报本次采集的总字节数；硬件适配层需将 NDTR 单位换算为字节。
 * 重复上报时若总长度不一致，本帧将保持错误状态。上报事件不会直接发布 READY。 */
gs_camera_result_t gs_camera_report(gs_camera_pool_t *pool,
                                   gs_camera_ticket_t ticket,
                                   uint32_t events, size_t received_bytes,
                                   uint32_t error_flags);

/* 前置条件：DCMI/DMA 已无法写入此缓冲，相关中断与采集报告均已处理，
 * 最终硬件错误标志已采样。必须同时满足帧结束、DMA 完成、长度精确和无错误
 * 才能进入 READY。失败时能回收为 FREE，也以硬件已停稳为前提。
 * timestamp_ms 是事先记录的帧结束时间，不能使用任务处理该事件的时间。 */
gs_camera_result_t gs_camera_finish_quiesced(gs_camera_pool_t *pool,
                                            gs_camera_ticket_t ticket,
                                            uint32_t timestamp_ms,
                                            uint32_t final_error_flags);

/* 超时、启动失败或溢出时，先停 DMA/DCMI 并等待空闲，
 * 清除待处理中断和采集报告，然后才能回收缓冲。 */
gs_camera_result_t gs_camera_abort_quiesced(gs_camera_pool_t *pool,
                                           gs_camera_ticket_t ticket);

/* 选择最新完成的 token，丢弃更旧的 READY 帧，不复制像素。
 * 返回的数据在 release 前保持只读；预览须在归还前复制。
 * frame_id 等于不复用的采集 token，允许因丢帧而不连续。 */
gs_camera_result_t gs_camera_acquire_latest(gs_camera_pool_t *pool,
                                           gs_camera_frame_t *frame);
gs_camera_result_t gs_camera_release(gs_camera_pool_t *pool,
                                    gs_camera_ticket_t ticket);

#ifdef __cplusplus
}
#endif
#endif
