/* Actual BSP hook/callback/quiesce/poll C is extracted verbatim at build time.
 * Actual camera pool is linked; only peripheral operations are synthetic. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "camera_irq_mocks.h"
#pragma warning(push)
#pragma warning(disable: 4311 4302)
#include "camera_irq_actual.inc"
#pragma warning(pop)
static uint32_t buffers[2][38400];
static unsigned cases;
static gs_port_frame_t frame;
static void begin(void)
{
    memset((void *)&g_gs_board_diag, 0, sizeof g_gs_board_diag);
    memset(&stream, 0, sizeof stream); memset(&dcmi, 0, sizeof dcmi);
    hdma.ErrorCode = hdcmi.ErrorCode = 0;
    camera_active = camera_events = camera_errors = camera_frame_ms = 0;
    tick = 100; primask = raw_flags = starts = pending_clears = barriers = start_failure = disable_delayed = 0;
    stream.FCR = 7; g_gs_board_diag.camera_ready = 1;
    assert(gs_camera_pool_init(&camera_pool, buffers[0], sizeof buffers[0], buffers[1], sizeof buffers[1], sizeof buffers[0]) == GS_CAMERA_OK);
    assert(gs_port_camera_poll(&frame) == GS_PORT_BUSY && starts == 1 && camera_active);
}
static void done(uint32_t flags, uint32_t extra_ie)
{
    stream.NDTR = 0; stream.FCR |= extra_ie; raw_flags = flags;
    gs_board_dma_irq(); tick = 120; HAL_DCMI_FrameEventCallback(&hdcmi);
}
static void reject(void)
{
    uint32_t token = camera_ticket.token;
    assert(gs_port_camera_poll(&frame) == GS_PORT_ERROR);
    assert(g_gs_board_diag.camera_frames == 0 && g_gs_board_diag.camera_errors == 1);
    assert(!camera_active && !raw_flags && primask == 0 && pending_clears == 2 && barriers == 1);
    assert(camera_pool.slots[camera_ticket.slot].state == GS_CAMERA_FREE);
    assert(gs_port_camera_poll(&frame) == GS_PORT_BUSY && camera_ticket.token > token && starts == 2);
    ++cases;
}
static void accept(void)
{
    assert(gs_port_camera_poll(&frame) == GS_PORT_OK);
    assert(frame.image.data_size == 153600 && frame.capture_ms == 120 && frame.frame_id == 1);
    assert(g_gs_board_diag.camera_frames == 1 && !g_gs_board_diag.camera_errors);
    assert(camera_pool.slots[frame.slot].state == GS_CAMERA_PROCESSING && !camera_active && !raw_flags);
    gs_port_camera_release(&frame);
    assert(gs_port_camera_poll(&frame) == GS_PORT_BUSY && camera_ticket.token == 2 && starts == 2);
    ++cases;
}
int main(int argc, char **argv)
{
    unsigned i, j;
    const uint32_t flags[] = { DMA_FLAG_TCIF1_5, DMA_FLAG_TEIF1_5, DMA_FLAG_DMEIF1_5, DMA_FLAG_FEIF1_5 };
    const uint32_t enables[] = { DMA_IT_TC, DMA_IT_TE, DMA_IT_DME, DMA_IT_FE };
    begin(); done(DMA_FLAG_TCIF1_5 | DMA_FLAG_FEIF1_5, 0);
    if (argc == 2 && strcmp(argv[1], "--expect-legacy") == 0) {
        assert(camera_events == 3 && camera_errors == 1 && hdma.ErrorCode == 0 && hdcmi.ErrorCode == 0);
        reject(); puts("PASS: old production hook drops full dual-event FEIE=0 frame; no hardware."); return 0;
    }
    assert(camera_errors == 0); accept();
    begin(); done(DMA_FLAG_TCIF1_5, 0); accept();
    begin(); done(DMA_FLAG_TCIF1_5 | DMA_FLAG_FEIF1_5, DMA_IT_FE); reject();
    begin(); done(DMA_FLAG_TCIF1_5 | DMA_FLAG_TEIF1_5, 0); reject();
    begin(); done(DMA_FLAG_TCIF1_5 | DMA_FLAG_DMEIF1_5, 0); reject();
    /* Orthogonal IE/flag matrix checks every flag against each CR/FCR IE.
       FCR gets a decoy TC/TE/DME bit and CR a decoy FE bit: wrong register must not match. */
    for (i = 0; i < 4; ++i) for (j = 0; j < 4; ++j) {
        begin(); stream.CR = DMA_IT_FE; stream.FCR = DMA_IT_TC | DMA_IT_TE | DMA_IT_DME;
        if (j == 3) { stream.FCR |= enables[j]; } else { stream.CR |= enables[j]; }
        raw_flags = flags[i]; gs_board_dma_irq();
        assert(camera_events == ((i == 0 && j == 0) ? GS_CAMERA_EVENT_DMA_DONE : 0));
        assert(camera_errors == ((i != 0 && i == j) ? 1U : 0U)); ++cases;
    }
    begin(); camera_active = 0; raw_flags = 0xF40; stream.FCR |= DMA_IT_FE;
    gs_board_dma_irq(); assert(!camera_events && !camera_errors); ++cases;
    begin(); gs_board_dma_irq(); assert(!camera_events && !camera_errors); ++cases;
    begin(); stream.NDTR = 0; raw_flags = DMA_FLAG_TCIF1_5; gs_board_dma_irq();
    assert(gs_port_camera_poll(&frame) == GS_PORT_BUSY && !g_gs_board_diag.camera_frames);
    tick = 120; HAL_DCMI_FrameEventCallback(&hdcmi); accept();
    begin(); done(DMA_FLAG_TCIF1_5, 0); stream.NDTR = 1; reject();
    begin(); done(DMA_FLAG_TCIF1_5, 0); dcmi.RISR = DCMI_RISR_OVR_RIS; reject();
    begin(); done(DMA_FLAG_TCIF1_5, 0); dcmi.RISR = DCMI_RISR_ERR_RIS; reject();
    begin(); done(DMA_FLAG_TCIF1_5, 0); hdcmi.ErrorCode = 1; HAL_DCMI_ErrorCallback(&hdcmi); reject();
    begin(); done(DMA_FLAG_TCIF1_5, 0); HAL_DCMI_ErrorCallback(&hdcmi); reject();
    begin(); stream.NDTR = 0; raw_flags = DMA_FLAG_TCIF1_5; gs_board_dma_irq(); tick = 600;
    reject(); assert(g_gs_board_diag.camera_timeouts == 1 && g_gs_board_diag.camera_last_error == 8);
    begin(); tick = 600; reject(); assert(g_gs_board_diag.camera_timeouts == 1);
    begin(); done(DMA_FLAG_TCIF1_5, 0); disable_delayed = 1;
    assert(gs_port_camera_poll(&frame) == GS_PORT_BUSY && camera_active && !pending_clears);
    disable_delayed = 0; accept();
    begin(); assert(gs_port_camera_poll(NULL) == GS_PORT_ERROR);
    g_gs_board_diag.camera_ready = 0; assert(gs_port_camera_poll(&frame) == GS_PORT_UNAVAILABLE); ++cases;
    printf("PASS: %u camera IRQ/state scenarios, actual BSP C and pool; synthetic registers only.\n", cases);
    return 0;
}
