#ifndef CAMERA_IRQ_MOCKS_H
#define CAMERA_IRQ_MOCKS_H
/* Memory-only register model. GET_IT_SOURCE is extracted from the real HAL. */
#define STM32F429xx
#define GS_ENABLE_USB_CAPTURE 0
#define GS_ENABLE_ETHERNET 0
#include <stdint.h>
#include "gs_port.h"
#include "gs_board.h"
#include "gs_camera_pool.h"
#define RESET 0U
#define DMA_FLAG_FEIF1_5 0x40U
#define DMA_FLAG_DMEIF1_5 0x100U
#define DMA_FLAG_TEIF1_5 0x200U
#define DMA_FLAG_HTIF1_5 0x400U
#define DMA_FLAG_TCIF1_5 0x800U
#define DMA_IT_TC 0x10U
#define DMA_IT_TE 4U
#define DMA_IT_DME 2U
#define DMA_IT_FE 0x80U
#define DMA_SxCR_EN 1U
#define DCMI_CR_CAPTURE 1U
#define DCMI_RISR_OVR_RIS 2U
#define DCMI_RISR_ERR_RIS 4U
#define DCMI_IT_FRAME 1U
#define DCMI_IT_OVR 2U
#define DCMI_IT_ERR 4U
#define DCMI_IT_VSYNC 8U
#define DCMI_IT_LINE 16U
#define DCMI_FLAG_FRAMERI 1U
#define DCMI_FLAG_OVRRI 2U
#define DCMI_FLAG_ERRRI 4U
#define DCMI_FLAG_VSYNCRI 8U
#define DCMI_FLAG_LINERI 16U
#define HAL_DCMI_STATE_READY 1U
#define HAL_DMA_STATE_READY 1U
#define HAL_UNLOCKED 0U
#define HAL_DCMI_ERROR_NONE 0U
#define DCMI_MODE_SNAPSHOT 2U
#define DCMI_IRQn 78U
#define DMA2_Stream1_IRQn 57U
#define HAL_OK 0U
typedef struct { uint32_t CR, NDTR, FCR; } mock_stream_t;
typedef struct { mock_stream_t *Instance; uint32_t ErrorCode, State, Lock; } DMA_HandleTypeDef;
typedef struct { uint32_t CR, RISR, IER; } mock_dcmi_t;
typedef struct { mock_dcmi_t *Instance; DMA_HandleTypeDef *DMA_Handle; uint32_t ErrorCode, State, Lock; } DCMI_HandleTypeDef;
static uint32_t raw_flags, tick, primask, starts, pending_clears, barriers, start_failure, disable_delayed;
static mock_stream_t stream;
static mock_dcmi_t dcmi;
static DMA_HandleTypeDef hdma = { &stream, 0, 0, 0 };
static DCMI_HandleTypeDef hdcmi = { &dcmi, &hdma, 0, 0, 0 };
static gs_camera_pool_t camera_pool;
static gs_camera_ticket_t camera_ticket;
static volatile uint32_t camera_active, camera_events, camera_errors, camera_frame_ms;
static uint32_t camera_start_ms;
volatile gs_board_diag_t g_gs_board_diag;
#define __HAL_DMA_GET_FLAG(h, f) (raw_flags & (f))
#define __HAL_DMA_GET_COUNTER(h) ((h)->Instance->NDTR)
#define __HAL_DMA_DISABLE(h) do { if (!disable_delayed) { (h)->Instance->CR &= ~DMA_SxCR_EN; } } while (0)
#define __HAL_DMA_CLEAR_FLAG(h, f) (raw_flags &= ~(f))
#define __HAL_DCMI_DISABLE(h) ((h)->Instance->CR = 0)
#define __HAL_DCMI_DISABLE_IT(h, f) ((h)->Instance->IER &= ~(f))
#define __HAL_DCMI_ENABLE_IT(h, f) ((h)->Instance->IER |= (f))
#define __HAL_DCMI_CLEAR_FLAG(h, f) ((h)->Instance->RISR &= ~(f))
#define CLEAR_BIT(r, f) ((r) &= ~(f))
static uint32_t HAL_GetTick(void) { return tick; }
static uint32_t __get_PRIMASK(void) { return primask; }
static void __disable_irq(void) { primask = 1; }
static void __set_PRIMASK(uint32_t value) { primask = value; }
static void __DSB(void) { ++barriers; }
static void HAL_NVIC_ClearPendingIRQ(uint32_t irq) { assert(irq == DCMI_IRQn || irq == DMA2_Stream1_IRQn); ++pending_clears; }
static uint32_t HAL_DCMI_Start_DMA(DCMI_HandleTypeDef *h, uint32_t mode, uint32_t address, uint32_t words)
{
    assert(h == &hdcmi && mode == DCMI_MODE_SNAPSHOT && words == 38400U);
    (void)address; /* Production truncates a target address; host never dereferences it. */
    ++starts;
    if (start_failure) { return 1; }
    raw_flags = 0; hdma.ErrorCode = 0;
    stream.NDTR = words; stream.CR |= DMA_SxCR_EN | DMA_IT_TC | DMA_IT_TE | DMA_IT_DME;
    dcmi.CR |= DCMI_CR_CAPTURE;
    return HAL_OK;
}
#endif
