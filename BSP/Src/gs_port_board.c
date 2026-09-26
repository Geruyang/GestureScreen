#include "gs_port.h"
#include "gs_board.h"
#include "gs_memory_map.h"
#include "gs_camera_pool.h"
#include "gs_display_swap.h"
#include "gs_ui_render.h"
#include "gs_ethernet.h"
#include "gs_capture_config.h"
#include "gs_usb_capture.h"
#include "gs_model_selected.h"
#include "main.h"
#include "dcmi.h"
#include "fmc.h"
#include "i2c.h"
#include "ltdc.h"
#include "spi.h"
#include "iwdg.h"
#include <string.h>
#include "gs_ov2640_regs.h"

#if GS_BOARD_SDRAM_BYTES != GS_SDRAM_CAPACITY_BYTES
#error "Board profile and SDRAM layout must both target Challenger V1 8 MiB"
#endif

volatile gs_board_diag_t g_gs_board_diag;
static gs_camera_pool_t camera_pool;
static gs_display_swap_t display_swap;
static gs_camera_ticket_t camera_ticket;
static volatile uint32_t camera_active, camera_events, camera_errors, camera_frame_ms;
static uint32_t camera_start_ms;
static volatile uint32_t reload_token, reload_done_token, reload_address;
static uint32_t reload_start_ms;
static uint32_t network_attempted;
static uint8_t preview_pixels[GS_PREVIEW_BYTES];
static gs_preview_frame_t preview_copy;
static bool preview_valid;
static bool display_preview_visible;
static uint32_t display_preview_id, display_preview_ms;
static gs_ui_live_status_t live_status, display_live_status;
static bool display_live_status_valid;
static gs_display_refresh_t display_refresh;

void gs_port_gui_set_status(const gs_ui_live_status_t *status)
{
    if (status != NULL) { live_status = *status; }
}

void gs_board_early_init(void)
{
    /* Called from MX_ETH_Init USER CODE 0, after .ioc-generated GPIO levels.
       LAN8720 reference clock must exist before HAL_ETH_Init's software reset. */
    HAL_Delay(5);
    HAL_GPIO_WritePin(ETH_PHY_RESET_GPIO_Port, ETH_PHY_RESET_Pin, GPIO_PIN_SET);
    HAL_Delay(5);
}

void gs_board_sdram_init(void)
{
    FMC_SDRAM_CommandTypeDef cmd = {0};
    volatile uint32_t *mem = (volatile uint32_t *)GS_SDRAM_BASE_ADDR;
    uint32_t i;
    g_gs_board_diag.board_profile = GS_BOARD_PROFILE_EMBEDFIRE_F429_CHALLENGER_V1;
    g_gs_board_diag.expected_hse_hz = GS_BOARD_HSE_HZ;
    g_gs_board_diag.expected_sdram_bytes = GS_BOARD_SDRAM_BYTES;
    cmd.CommandTarget = FMC_SDRAM_CMD_TARGET_BANK2;
    cmd.AutoRefreshNumber = 1;
    cmd.CommandMode = FMC_SDRAM_CMD_CLK_ENABLE;
    if (HAL_SDRAM_SendCommand(&hsdram1, &cmd, 10) != HAL_OK) { Error_Handler(); }
    HAL_Delay(1);
    cmd.CommandMode = FMC_SDRAM_CMD_PALL;
    if (HAL_SDRAM_SendCommand(&hsdram1, &cmd, 10) != HAL_OK) { Error_Handler(); }
    cmd.CommandMode = FMC_SDRAM_CMD_AUTOREFRESH_MODE;
    cmd.AutoRefreshNumber = 8;
    if (HAL_SDRAM_SendCommand(&hsdram1, &cmd, 10) != HAL_OK) { Error_Handler(); }
    cmd.CommandMode = FMC_SDRAM_CMD_LOAD_MODE;
    cmd.ModeRegisterDefinition = 0x0231U; /* burst 2, sequential, CAS 3, single write */
    if (HAL_SDRAM_SendCommand(&hsdram1, &cmd, 10) != HAL_OK ||
        HAL_SDRAM_ProgramRefreshRate(&hsdram1, 1292U) != HAL_OK) { Error_Handler(); }
    /* All SDRAM is unowned at boot. Address-dependent full 8 MiB test catches aliasing. */
    for (uint32_t pass = 0; pass < 2U; ++pass) {
        /* Complement also toggles upper data bits that address-only testing
         * left fixed. No other subsystem owns SDRAM before this hook returns. */
        uint32_t pattern = pass == 0U ? 0xA55A0000U : ~0xA55A0000U;
        for (i = 0; i < GS_SDRAM_CAPACITY_BYTES / 4U; ++i) { mem[i] = pattern ^ i; }
        __DSB();
        for (i = 0; i < GS_SDRAM_CAPACITY_BYTES / 4U; ++i) {
            uint32_t actual = mem[i];
            if (actual != (pattern ^ i)) {
                g_gs_board_diag.sdram_fail_addr = GS_SDRAM_BASE_ADDR + i * 4U;
                g_gs_board_diag.sdram_fail_expected = pattern ^ i;
                g_gs_board_diag.sdram_fail_actual = actual;
                Error_Handler();
            }
        }
    }
    for (i = 0; i < GS_SDRAM_CAPACITY_BYTES / 4U; ++i) { mem[i] = 0; }
    __DSB();
    g_gs_board_diag.sdram_ready = 1;
}

static bool sensor_write(uint8_t reg, uint8_t value)
{
    return HAL_I2C_Mem_Write(&hi2c1, 0x60, reg, I2C_MEMADD_SIZE_8BIT, &value, 1, 10) == HAL_OK;
}
static bool sensor_read(uint8_t reg, uint8_t *value)
{
    /* SCCB read uses separate write and read transfers (STOP between phases). */
    return HAL_I2C_Master_Transmit(&hi2c1, 0x60, &reg, 1, 10) == HAL_OK &&
           HAL_I2C_Master_Receive(&hi2c1, 0x60, value, 1, 10) == HAL_OK;
}
static bool sensor_init(void)
{
    uint8_t pid = 0, ver = 0;
    size_t i;
    HAL_GPIO_WritePin(CAM_PWDN_GPIO_Port, CAM_PWDN_Pin, GPIO_PIN_RESET);
    HAL_Delay(5);
    HAL_GPIO_WritePin(CAM_RESET_GPIO_Port, CAM_RESET_Pin, GPIO_PIN_SET);
    HAL_Delay(20);
    if (!sensor_write(0xff, 1) || !sensor_read(0x0a, &pid) || !sensor_read(0x0b, &ver) ||
        pid != 0x26 || (ver != 0x40 && ver != 0x41 && ver != 0x42)) { return false; }
    if (!sensor_write(0x12, 0x80)) { return false; }
    HAL_Delay(10);
    for (i = 0; i < sizeof(gs_ov2640_qvga) / sizeof(gs_ov2640_qvga[0]); ++i) {
        if (!sensor_write(gs_ov2640_qvga[i][0], gs_ov2640_qvga[i][1])) { return false; }
    }
    /* ST table ends in low-byte-first 0x09; explicitly request high-byte-first.
       On-board color-bar acceptance must verify this sensor revision's byte order. */
    if (!sensor_write(0xff, 0) || !sensor_write(0xda, 0x08)) { return false; }
    HAL_Delay(50);
    return true;
}

void gs_port_init(void)
{
    uint8_t cmd = 0x9f, id[3] = {0};
    if (!g_gs_board_diag.sdram_ready) { return; }
    /* The Cube.AI activation arena is the only CCM resident. Its scatter
       region is UNINIT, so enable and verify the clock before the backend's
       first explicit memset. DMA-visible buffers remain in SDRAM/SRAM. */
    __HAL_RCC_CCMDATARAMEN_CLK_ENABLE();
    if (!__HAL_RCC_CCMDATARAMEN_IS_CLK_ENABLED()) { Error_Handler(); }
    __DSB();
    if (gs_camera_pool_init(&camera_pool, (void *)GS_CAMERA_BUFFER0_ADDR, GS_SDRAM_CAMERA_FRAME_BYTES,
                           (void *)GS_CAMERA_BUFFER1_ADDR, GS_SDRAM_CAMERA_FRAME_BYTES,
                           GS_SDRAM_CAMERA_FRAME_BYTES) != GS_CAMERA_OK) { Error_Handler(); }
    if (!gs_display_swap_init(&display_swap, (void *)GS_LCD_BUFFER0_ADDR, GS_SDRAM_LCD_FRAME_BYTES,
                             (void *)GS_LCD_BUFFER1_ADDR, GS_SDRAM_LCD_FRAME_BYTES,
                             GS_SDRAM_LCD_FRAME_BYTES)) { Error_Handler(); }
    g_gs_board_diag.camera_ready = sensor_init() ? 1U : 0U;
    g_gs_board_diag.lcd_ready = 1;
    HAL_GPIO_WritePin(FLASH_CS_GPIO_Port, FLASH_CS_Pin, GPIO_PIN_RESET);
    if (HAL_SPI_Transmit(&hspi5, &cmd, 1, 5) == HAL_OK && HAL_SPI_Receive(&hspi5, id, 3, 5) == HAL_OK) {
        g_gs_board_diag.flash_jedec = ((uint32_t)id[0] << 16) | ((uint32_t)id[1] << 8) | id[2];
        g_gs_board_diag.flash_profile_match =
            (g_gs_board_diag.flash_jedec == GS_BOARD_W25Q128_JEDEC) ? 1U : 0U;
    }
    HAL_GPIO_WritePin(FLASH_CS_GPIO_Port, FLASH_CS_Pin, GPIO_PIN_SET);
    g_gs_board_diag.watchdog_started = 1;
    MX_IWDG_Init(); /* deferred main call: start after camera/Flash bring-up */
    (void)HAL_IWDG_Refresh(&hiwdg);
}

/* IRQ hooks never touch pool states or RTOS services. NVIC priorities are identical.
   Ticket stays unchanged until both engines stop, flags clear and pending IRQs drain. */
void gs_board_dma_irq(void)
{
    if (!camera_active) { return; }
    if (__HAL_DMA_GET_FLAG(hdcmi.DMA_Handle, DMA_FLAG_TCIF1_5) != RESET &&
        __HAL_DMA_GET_IT_SOURCE(hdcmi.DMA_Handle, DMA_IT_TC) != RESET) {
        camera_events |= GS_CAMERA_EVENT_DMA_DONE;
    }
    /* Match HAL's enabled-source policy; raw FEIF with FEIE=0 is not a fault.
       FEIE is in FCR, while TC/TE/DME enables are in CR: check each separately. */
    if ((__HAL_DMA_GET_FLAG(hdcmi.DMA_Handle, DMA_FLAG_TEIF1_5) != RESET &&
         __HAL_DMA_GET_IT_SOURCE(hdcmi.DMA_Handle, DMA_IT_TE) != RESET) ||
        (__HAL_DMA_GET_FLAG(hdcmi.DMA_Handle, DMA_FLAG_DMEIF1_5) != RESET &&
         __HAL_DMA_GET_IT_SOURCE(hdcmi.DMA_Handle, DMA_IT_DME) != RESET) ||
        (__HAL_DMA_GET_FLAG(hdcmi.DMA_Handle, DMA_FLAG_FEIF1_5) != RESET &&
         __HAL_DMA_GET_IT_SOURCE(hdcmi.DMA_Handle, DMA_IT_FE) != RESET)) {
        camera_errors |= 1U;
    }
}
void HAL_DCMI_FrameEventCallback(DCMI_HandleTypeDef *handle)
{
    if (handle == &hdcmi && camera_active) {
        camera_frame_ms = HAL_GetTick();
        camera_events |= GS_CAMERA_EVENT_FRAME_END;
    }
}
void HAL_DCMI_ErrorCallback(DCMI_HandleTypeDef *handle)
{
    if (handle == &hdcmi && camera_active) { camera_errors |= 2U | handle->ErrorCode; }
}

static bool camera_quiesce(uint32_t *events, uint32_t *errors, uint32_t *received, uint32_t *stamp)
{
    uint32_t mask = __get_PRIMASK();
    /* Do not call HAL_DCMI_Stop with IRQs masked: it contains a tick-based wait.
       Snapshot has already ended, or clear CAPTURE and request DMA disable then poll next tick. */
    CLEAR_BIT(hdcmi.Instance->CR, DCMI_CR_CAPTURE);
    __HAL_DMA_DISABLE(hdcmi.DMA_Handle);
    if ((hdcmi.DMA_Handle->Instance->CR & DMA_SxCR_EN) != 0U) { return false; }
    __disable_irq();
    *events = camera_events;
    *errors = camera_errors | hdcmi.ErrorCode;
    if ((hdcmi.Instance->RISR & (DCMI_RISR_OVR_RIS | DCMI_RISR_ERR_RIS)) != 0) { *errors |= 4U; }
    *received = (38400U - __HAL_DMA_GET_COUNTER(hdcmi.DMA_Handle)) * 4U;
    *stamp = camera_frame_ms;
    __HAL_DCMI_DISABLE(&hdcmi);
    __HAL_DCMI_DISABLE_IT(&hdcmi, DCMI_IT_FRAME | DCMI_IT_OVR | DCMI_IT_ERR | DCMI_IT_VSYNC | DCMI_IT_LINE);
    __HAL_DCMI_CLEAR_FLAG(&hdcmi, DCMI_FLAG_FRAMERI | DCMI_FLAG_OVRRI | DCMI_FLAG_ERRRI | DCMI_FLAG_VSYNCRI | DCMI_FLAG_LINERI);
    __HAL_DMA_CLEAR_FLAG(hdcmi.DMA_Handle, DMA_FLAG_TCIF1_5 | DMA_FLAG_HTIF1_5 | DMA_FLAG_TEIF1_5 | DMA_FLAG_DMEIF1_5 | DMA_FLAG_FEIF1_5);
    HAL_NVIC_ClearPendingIRQ(DCMI_IRQn);
    HAL_NVIC_ClearPendingIRQ(DMA2_Stream1_IRQn);
    camera_active = 0;
    hdcmi.State = HAL_DCMI_STATE_READY;
    hdcmi.Lock = HAL_UNLOCKED;
    hdcmi.DMA_Handle->State = HAL_DMA_STATE_READY;
    hdcmi.DMA_Handle->Lock = HAL_UNLOCKED;
    __set_PRIMASK(mask);
    __DSB();
    return true;
}

gs_port_status_t gs_port_camera_poll(gs_port_frame_t *frame)
{
    gs_camera_frame_t completed;
    uint32_t now = HAL_GetTick(), events, errors, received, stamp;
    void *buffer;
    if (frame == NULL) { return GS_PORT_ERROR; }
    memset(frame, 0, sizeof(*frame));
    if (!g_gs_board_diag.camera_ready) { return GS_PORT_UNAVAILABLE; }
    if (camera_active && (camera_errors || camera_events == 3U || now - camera_start_ms >= 500U)) {
        bool timeout = now - camera_start_ms >= 500U;
        if (!camera_quiesce(&events, &errors, &received, &stamp)) { return GS_PORT_BUSY; }
        if (timeout) { ++g_gs_board_diag.camera_timeouts; errors |= 8U; }
        (void)gs_camera_report(&camera_pool, camera_ticket, events, received, errors);
        if (gs_camera_finish_quiesced(&camera_pool, camera_ticket, stamp, errors) != GS_CAMERA_OK) {
            ++g_gs_board_diag.camera_errors;
            g_gs_board_diag.camera_last_error = errors;
            /* App clears gesture evidence on a real acquisition fault. Retry next poll. */
            return GS_PORT_ERROR;
        }
    }
    if (gs_camera_acquire_latest(&camera_pool, &completed) == GS_CAMERA_OK) {
        frame->image.data = completed.data;
        frame->image.data_size = completed.bytes;
        frame->image.width = 320; frame->image.height = 240;
        frame->image.stride_bytes = 640; frame->image.byte_order = GS_RGB565_MSB_FIRST;
        frame->frame_id = completed.frame_id; frame->capture_ms = completed.timestamp_ms;
        frame->lease_token = completed.ticket.token; frame->slot = completed.ticket.slot;
        ++g_gs_board_diag.camera_frames;
#if GS_ENABLE_USB_CAPTURE
        (void)gs_usb_capture_offer(completed.data, completed.bytes, completed.frame_id, completed.timestamp_ms);
#elif GS_ENABLE_ETHERNET
        (void)gs_ethernet_offer_frame(completed.data, completed.bytes, completed.frame_id, completed.timestamp_ms);
#endif
        return GS_PORT_OK;
    }
    if (!camera_active && gs_camera_begin(&camera_pool, &camera_ticket, &buffer) == GS_CAMERA_OK) {
        camera_events = 0; camera_errors = 0; camera_frame_ms = 0;
        hdcmi.ErrorCode = HAL_DCMI_ERROR_NONE;
        __HAL_DCMI_ENABLE_IT(&hdcmi, DCMI_IT_OVR | DCMI_IT_ERR);
        camera_start_ms = now; camera_active = 1;
        if (HAL_DCMI_Start_DMA(&hdcmi, DCMI_MODE_SNAPSHOT, (uint32_t)buffer, 38400U) != HAL_OK) {
            camera_errors |= 16U; /* next poll stops hardware before recycling */
        }
    }
    return GS_PORT_BUSY;
}
void gs_port_camera_release(const gs_port_frame_t *frame)
{
    if (frame != NULL) {
        gs_camera_ticket_t ticket = {frame->lease_token, (uint8_t)frame->slot};
        (void)gs_camera_release(&camera_pool, ticket);
    }
}

void HAL_LTDC_ReloadEventCallback(LTDC_HandleTypeDef *handle)
{
    if (handle == &hltdc && reload_token != 0U) {
        reload_address = LTDC_Layer1->CFBAR;
        __DMB();
        reload_done_token = reload_token;
    }
}
void HAL_LTDC_ErrorCallback(LTDC_HandleTypeDef *handle)
{
    if (handle == &hltdc) { ++g_gs_board_diag.display_errors; }
}

/* GS_GUI_INCREMENTAL_BEGIN: test export includes the helpers and render path. */
#define GS_DISPLAY_LAYOUT_VERSION 2U
typedef struct {
    uint32_t display_errors, inference_errors, inference_timeouts;
    uint32_t content_checked, content_errors;
    bool preview_visible, healthy, control_enabled, camera_fault;
    bool display_stalled, inference_fault, result_stale;
} gs_display_critical_key_t;
typedef struct {
    uint32_t status, class_index, confidence_permille, processing;
    uint32_t neutral_gesture_state;
} gs_display_recognition_key_t;
typedef struct {
    uint32_t visible, age_ms, inference_ms;
} gs_display_result_age_key_t;
typedef struct {
    uint32_t visible, age_ms;
} gs_display_preview_age_key_t;
typedef struct {
    uint32_t kind, values[8];
    uintptr_t pointers[2];
} gs_display_detail_key_t;
typedef struct {
    uint32_t control_enabled, business_validated, seven_class_ready;
    uint32_t gesture_state, gesture_progress;
} gs_display_gesture_key_t;
typedef struct {
    uint32_t layout_version, generation, preview_id, preview_capture_ms;
    gs_display_critical_key_t critical;
    gs_display_recognition_key_t recognition;
    gs_display_result_age_key_t result_age;
    gs_display_preview_age_key_t preview_age;
    gs_display_detail_key_t detail;
    gs_display_gesture_key_t gesture;
    uint32_t hint_valid, hint_class;
    bool valid, preview_visible;
} gs_display_buffer_history_t;
static gs_display_buffer_history_t display_buffer_history[2];

static gs_display_critical_key_t gs_display_critical_key(
    const gs_display_refresh_input_t *input)
{
    gs_display_critical_key_t key;
    key.display_errors = input->display_errors;
    key.inference_errors = input->inference_errors;
    key.inference_timeouts = input->inference_timeouts;
    key.content_checked = input->content_checked;
    key.content_errors = input->content_errors;
    key.preview_visible = input->preview_visible;
    key.healthy = input->healthy;
    key.control_enabled = input->control_enabled;
    key.camera_fault = input->camera_fault;
    key.display_stalled = input->display_stalled;
    key.inference_fault = input->inference_fault;
    key.result_stale = input->result_stale;
    return key;
}

static bool gs_display_critical_equal(const gs_display_critical_key_t *left,
                                      const gs_display_critical_key_t *right)
{
    return left->display_errors == right->display_errors &&
        left->inference_errors == right->inference_errors &&
        left->inference_timeouts == right->inference_timeouts &&
        left->content_checked == right->content_checked &&
        left->content_errors == right->content_errors &&
        left->preview_visible == right->preview_visible &&
        left->healthy == right->healthy &&
        left->control_enabled == right->control_enabled &&
        left->camera_fault == right->camera_fault &&
        left->display_stalled == right->display_stalled &&
        left->inference_fault == right->inference_fault &&
        left->result_stale == right->result_stale;
}

static gs_display_recognition_key_t gs_display_recognition_key(
    const gs_ui_live_status_t *status)
{
    gs_static_result_t result = status->recognition;
    gs_display_recognition_key_t key;
    /* Keep the key aligned with gs_static_expire without coupling the BSP
       export tests to the recognition implementation object. */
    if (result.frame_id != 0U &&
        status->now_ms - result.capture_ms > GS_STATIC_RESULT_TTL_MS) {
        result.status = GS_STATIC_STALE;
        result.confidence_permille = 0U;
    }
    key.status = result.status;
    key.class_index = result.class_index;
    key.confidence_permille = result.confidence_permille;
    key.processing = status->processing;
    key.neutral_gesture_state = result.status == GS_STATIC_NO_TARGET &&
        result.class_index == GS_STATIC_UNKNOWN ? status->gesture_state : 0U;
    return key;
}

static bool gs_display_recognition_equal(const gs_display_recognition_key_t *left,
                                         const gs_display_recognition_key_t *right)
{
    return left->status == right->status &&
        left->class_index == right->class_index &&
        left->confidence_permille == right->confidence_permille &&
        left->processing == right->processing &&
        left->neutral_gesture_state == right->neutral_gesture_state;
}

static gs_display_result_age_key_t gs_display_result_age_key(
    const gs_ui_live_status_t *status)
{
    gs_display_result_age_key_t key;
    key.visible = status->recognition.frame_id != 0U;
    key.age_ms = key.visible ? status->now_ms - status->recognition.capture_ms : 0U;
    key.inference_ms = key.visible ? status->recognition.inference_ms : 0U;
    return key;
}

static gs_display_preview_age_key_t gs_display_preview_age_key(
    const gs_ui_live_status_t *status, bool preview_visible)
{
    gs_display_preview_age_key_t key;
    key.visible = preview_visible;
    key.age_ms = preview_visible ? status->preview_age_ms : 0U;
    return key;
}

static gs_display_detail_key_t gs_display_detail_key(const gs_ui_t *ui,
                                                      const gs_ui_live_status_t *status)
{
    gs_display_detail_key_t key;
    const gs_ui_collection_t *collection = NULL;
    memset(&key, 0, sizeof key);
    key.values[0] = ui->playing;
    if (ui->mode == GS_UI_DIRECTORY || ui->collection_count == 0U) {
        key.kind = GS_UI_DIRECTORY;
        return key;
    }
    collection = &ui->collections[ui->selected];
    key.kind = (uint32_t)collection->kind + 1U;
    if (collection->kind == GS_UI_COLLECTION_DIAGNOSTICS) {
        key.kind += ui->page << 8;
        if (ui->page == 0U) {
            key.values[1] = (status->camera_fps_milli + 500U) / 1000U;
            key.values[2] = (status->vision_fps_milli + 500U) / 1000U;
            key.values[3] = status->recognition.inference_ms;
            key.values[4] = status->vision_age_ms;
        } else if (ui->page == 1U) {
            key.values[1] = status->camera_errors;
            key.values[2] = status->camera_drops;
            key.values[3] = status->inference_errors;
            key.values[4] = status->inference_timeouts;
            key.values[5] = status->quality_rejects;
            key.values[6] = status->preview_drops;
        } else {
            key.values[1] = status->heap_free_bytes;
            key.values[2] = status->heap_min_free_bytes;
            key.values[3] = status->stack_min_free_bytes;
            key.values[4] = status->content_checked;
            key.values[5] = status->content_total;
            key.values[6] = status->content_errors;
            key.pointers[0] = (uintptr_t)status->content_version;
        }
    } else if (collection->kind == GS_UI_COLLECTION_SETTINGS) {
        key.kind += ui->page << 8;
        if (ui->page == 0U) { key.values[1] = ui->recognition_enabled; }
        else if (ui->page == 1U) { key.values[1] = status->business_validated; }
    } else if (collection->kind == GS_UI_COLLECTION_CONTENT) {
        key.pointers[0] = (uintptr_t)status->content_rgb565_be;
        key.values[1] = status->content_image_bytes;
        key.values[2] = status->content_image_width;
        key.values[3] = status->content_image_height;
    }
    return key;
}

static gs_display_gesture_key_t gs_display_gesture_key(
    const gs_ui_live_status_t *status)
{
    gs_display_gesture_key_t key;
    key.control_enabled = status->control_enabled;
    key.business_validated = status->business_validated;
    key.seven_class_ready = status->seven_class_ready;
    key.gesture_state = status->gesture_state;
    key.gesture_progress = status->gesture_progress;
    return key;
}

static bool gs_display_gesture_equal(const gs_display_gesture_key_t *left,
                                     const gs_display_gesture_key_t *right)
{
    return left->control_enabled == right->control_enabled &&
        left->business_validated == right->business_validated &&
        left->seven_class_ready == right->seven_class_ready &&
        left->gesture_state == right->gesture_state &&
        left->gesture_progress == right->gesture_progress;
}

static gs_display_buffer_history_t *gs_display_history_for(void *buffer)
{
    if (buffer == display_swap.buffers[0]) { return &display_buffer_history[0]; }
    if (buffer == display_swap.buffers[1]) { return &display_buffer_history[1]; }
    return NULL;
}

gs_port_status_t gs_port_gui_render(const gs_ui_t *ui, const gs_preview_frame_t *preview)
{
    static const gs_ui_render_region_t recognition_region = {620U, 436U, 180U, 44U};
    static const gs_ui_render_region_t gesture_region = {0U, 436U, 800U, 44U};
    static const gs_ui_render_region_t hint_region = {490U, 0U, 310U, 68U};
    gs_ui_render_region_t dirty_regions[5];
    size_t dirty_region_count = 0U;
    gs_display_composition_t draw;
    gs_display_buffer_history_t *history;
    gs_display_buffer_history_t staged_history;
    gs_display_critical_key_t critical_key;
    gs_display_refresh_input_t refresh_input;
    const void *pending;
    uint32_t irq_mask;
    uint32_t render_start;
    bool preview_visible;
    bool full_render;
    bool hint_changed;
    HAL_StatusTypeDef reload_status;
    if (!g_gs_board_diag.lcd_ready) { return GS_PORT_UNAVAILABLE; }
    if (ui == NULL) { return GS_PORT_ERROR; }
    /* Copy even while a reload is pending. Caller returns its preview lease on exit. */
    if (preview != NULL && preview->pixels != NULL && preview->bytes == GS_PREVIEW_BYTES &&
        preview->width == GS_PREVIEW_WIDTH && preview->height == GS_PREVIEW_HEIGHT) {
        memcpy(preview_pixels, preview->pixels, sizeof(preview_pixels));
        preview_copy = *preview;
        preview_copy.pixels = preview_pixels;
        preview_valid = true;
        ++g_gs_preview_diag.copied;
        g_gs_preview_diag.copied_id = preview_copy.frame_id;
        g_gs_preview_diag.copied_capture_ms = preview_copy.capture_ms;
    }
    if (display_swap.state == GS_DISPLAY_PENDING) {
        if (reload_done_token == reload_token && reload_token != 0U) {
            __DMB();
            if (!gs_display_reload_confirm(&display_swap, reload_done_token, (const void *)reload_address)) {
                return GS_PORT_ERROR;
            }
            reload_token = 0; reload_done_token = 0;
            ++g_gs_board_diag.display_frames;
            /* Saved submit identity belongs to this confirmed token, even if
               the incoming preview just replaced the GUI's private cache. */
            if (display_preview_visible && display_preview_id != 0U &&
                display_preview_id != g_gs_preview_diag.confirmed_id) {
                ++g_gs_preview_diag.confirmed_unique;
                g_gs_preview_diag.confirmed_id = display_preview_id;
                g_gs_preview_diag.confirmed_capture_ms = display_preview_ms;
                g_gs_preview_diag.confirmed_age_ms = HAL_GetTick() - display_preview_ms;
            }
            HAL_GPIO_WritePin(LCD_DISP_GPIO_Port, LCD_DISP_Pin, GPIO_PIN_SET);
            HAL_GPIO_WritePin(LCD_BL_GPIO_Port, LCD_BL_Pin, GPIO_PIN_SET);
        } else {
            if (HAL_GetTick() - reload_start_ms > 500U) { g_gs_board_diag.display_stalled = 1; }
            return GS_PORT_BUSY; /* keep pending buffers read-only on lost reload */
        }
    }
    live_status.preview_frame_id = preview_valid ? preview_copy.frame_id : 0U;
    live_status.preview_age_ms = preview_valid ? HAL_GetTick() - preview_copy.capture_ms : 0U;
    /* Camera sampling and its lease return continue, but reader pages have no
       image window; preview frames do not drive display refresh or overlay. */
    preview_visible = false;
    /* Compare displayed meanings, not cumulative camera counters or every GUI
       tick. Stable previews set the actual refresh cadence; live-only changes
       are coalesced with the next preview or a bounded no-preview fallback. */
    gs_ui_live_status_t status_key;
    memset(&status_key, 0, sizeof status_key);
    status_key.control_enabled = live_status.control_enabled;
    status_key.gesture_state = live_status.gesture_state;
    status_key.recognition.status = live_status.recognition.status;
    status_key.hint_valid = live_status.hint_valid;
    status_key.hint_class = live_status.hint_class;
    hint_changed = !display_live_status_valid ||
        display_live_status.hint_valid != status_key.hint_valid ||
        (status_key.hint_valid && display_live_status.hint_class != status_key.hint_class);
    memset(&refresh_input, 0, sizeof refresh_input);
    refresh_input.now_ms = live_status.now_ms;
    refresh_input.generation = ui->generation;
    refresh_input.preview_visible = preview_visible;
    refresh_input.preview_id = preview_visible ? preview_copy.frame_id : 0U;
    refresh_input.preview_capture_ms = preview_visible ? preview_copy.capture_ms : 0U;
    refresh_input.healthy = live_status.healthy != 0U;
    refresh_input.control_enabled = live_status.control_enabled != 0U;
    refresh_input.camera_fault = live_status.recognition.status == GS_STATIC_CAMERA_ERROR;
    refresh_input.display_errors = g_gs_board_diag.display_errors;
    refresh_input.display_stalled = g_gs_board_diag.display_stalled != 0U;
    refresh_input.inference_errors = live_status.inference_errors;
    refresh_input.inference_timeouts = live_status.inference_timeouts;
    refresh_input.inference_fault =
        live_status.recognition.status == GS_STATIC_INFERENCE_ERROR ||
        live_status.recognition.status == GS_STATIC_TIMEOUT;
    refresh_input.result_stale = live_status.recognition.status == GS_STATIC_STALE;
    refresh_input.content_checked = live_status.content_checked;
    refresh_input.content_errors = live_status.content_errors;
    refresh_input.ordinary_changed = !display_live_status_valid ||
        memcmp(&display_live_status, &status_key, sizeof status_key) != 0;
    critical_key = gs_display_critical_key(&refresh_input);
    /* observe only latches ordinary dirty time. A skipped/BUSY/error draw is
       not committed, so every new preview and critical edge remains pending. */
    if (gs_display_refresh_observe(&display_refresh, &refresh_input) ==
        GS_DISPLAY_REFRESH_NONE && !hint_changed) {
        return GS_PORT_OK;
    }
    if (!gs_display_begin(&display_swap, &draw)) { return GS_PORT_BUSY; }
    history = gs_display_history_for(draw.back);
    if (history == NULL) {
        (void)gs_display_cancel_quiesced(&display_swap, draw.token);
        return GS_PORT_ERROR;
    }
    full_render = !history->valid ||
        history->layout_version != GS_DISPLAY_LAYOUT_VERSION ||
        history->generation != ui->generation ||
        !gs_display_critical_equal(&history->critical, &critical_key);
    staged_history.layout_version = GS_DISPLAY_LAYOUT_VERSION;
    staged_history.generation = ui->generation;
    staged_history.preview_id = preview_visible ? preview_copy.frame_id : 0U;
    staged_history.preview_capture_ms = preview_visible ? preview_copy.capture_ms : 0U;
    staged_history.critical = critical_key;
    staged_history.recognition = gs_display_recognition_key(&live_status);
    staged_history.result_age = gs_display_result_age_key(&live_status);
    staged_history.preview_age = gs_display_preview_age_key(&live_status, preview_visible);
    staged_history.detail = gs_display_detail_key(ui, &live_status);
    staged_history.gesture = gs_display_gesture_key(&live_status);
    staged_history.hint_valid = live_status.hint_valid;
    staged_history.hint_class = live_status.hint_class;
    staged_history.valid = true;
    staged_history.preview_visible = preview_visible;
    if (!full_render) {
        if (!gs_display_recognition_equal(&history->recognition, &staged_history.recognition)) {
            dirty_regions[dirty_region_count++] = recognition_region;
        }
        if (!gs_display_gesture_equal(&history->gesture, &staged_history.gesture)) {
            dirty_regions[dirty_region_count++] = gesture_region;
        }
        if (history->hint_valid != staged_history.hint_valid ||
            (staged_history.hint_valid && history->hint_class != staged_history.hint_class)) {
            dirty_regions[dirty_region_count++] = hint_region;
        }
    }
    render_start = HAL_GetTick();
    if (!gs_display_copy_complete(&display_swap, draw.token)) {
        history->valid = false;
        (void)gs_display_cancel_quiesced(&display_swap, draw.token);
        return GS_PORT_ERROR;
    }
    /* From this point a failure leaves mixed pixels in this physical buffer.
       Invalidate before the first write so a retry cannot use stale metadata. */
    history->valid = false;
    if ((full_render && gs_ui_render_dashboard_rgb565(ui, &live_status,
            (uint16_t *)draw.back, draw.bytes / 2U, 800, 480, 800, NULL) != GS_UI_RENDER_OK) ||
        (!full_render && dirty_region_count != 0U &&
         gs_ui_render_dashboard_regions_rgb565(ui, &live_status, (uint16_t *)draw.back,
            draw.bytes / 2U, 800, 480, 800, NULL, dirty_regions,
            dirty_region_count) != GS_UI_RENDER_OK)) {
        (void)gs_display_cancel_quiesced(&display_swap, draw.token); return GS_PORT_ERROR;
    }
    uint32_t render_ms = HAL_GetTick() - render_start;
    if (render_ms > g_gs_board_diag.display_max_render_ms) {
        g_gs_board_diag.display_max_render_ms = render_ms;
    }
    __DSB();
    if (!gs_display_submit(&display_swap, draw.token, &pending)) {
        (void)gs_display_cancel_quiesced(&display_swap, draw.token);
        return GS_PORT_ERROR;
    }
    /* ConfigLayer's initial immediate reload can leave RRIF set while RRIE is off.
       Never attach that old event to a new token: clear it before arming this VBR.
       These HAL setters do not poll or wait; the critical section is register-only. */
    irq_mask = __get_PRIMASK();
    __disable_irq();
    __HAL_LTDC_DISABLE_IT(&hltdc, LTDC_IT_RR);
    __HAL_LTDC_CLEAR_FLAG(&hltdc, LTDC_FLAG_RR);
    HAL_NVIC_ClearPendingIRQ(LTDC_IRQn);
    reload_done_token = 0; reload_token = 0;
    reload_status = HAL_LTDC_SetAddress_NoReload(&hltdc, (uint32_t)pending, 0);
    if (reload_status == HAL_OK) {
        reload_token = draw.token; reload_start_ms = HAL_GetTick();
        reload_status = HAL_LTDC_Reload(&hltdc, LTDC_RELOAD_VERTICAL_BLANKING);
    }
    if (reload_status != HAL_OK) {
        /* No reload is armed. Clear the published token before interrupts can
           observe it; the exact pending buffer is rolled back below. */
        reload_token = 0U;
        reload_done_token = 0U;
    }
    __DSB();
    __set_PRIMASK(irq_mask);
    if (reload_status != HAL_OK) {
        /* No VBR request was armed. Return the exact frozen back buffer to
           IDLE; refresh state is deliberately not committed, so the same
           preview/critical edge is retried on the next 20 ms GUI service. */
        if (!gs_display_submit_abort_unarmed(&display_swap, draw.token, pending)) {
            ++g_gs_board_diag.display_errors; return GS_PORT_ERROR;
        }
        ++g_gs_board_diag.display_errors; return GS_PORT_ERROR;
    }
    *history = staged_history;
    display_live_status = status_key; display_live_status_valid = true;
    display_preview_visible = preview_visible;
    display_preview_id = preview_copy.frame_id; display_preview_ms = preview_copy.capture_ms;
    gs_display_refresh_commit(&display_refresh, &refresh_input);
    return GS_PORT_OK;
}

gs_port_status_t gs_port_storage_step(void)
{
    if (!g_gs_board_diag.sdram_ready) { return GS_PORT_UNAVAILABLE; }
    if (!network_attempted) {
        network_attempted = 1;
#if GS_ENABLE_USB_CAPTURE
        gs_usb_capture_init();
#elif GS_ENABLE_ETHERNET
        (void)gs_ethernet_init();
#endif
    }
#if GS_ENABLE_USB_CAPTURE
    gs_usb_capture_step(HAL_GetTick());
#elif GS_ENABLE_ETHERNET
    gs_ethernet_step(HAL_GetTick());
#endif
    return GS_PORT_OK;
}
const gs_ai_backend_t *gs_port_model_backend(void) { return gs_model_selected_backend(); }
void gs_port_watchdog_refresh(void)
{
    if (g_gs_board_diag.watchdog_started) { (void)HAL_IWDG_Refresh(&hiwdg); }
}
