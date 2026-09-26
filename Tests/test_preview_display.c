/* Actual BSP render function + actual display swap lifecycle. Peripheral calls
 * and canvas paint are synthetic. No LCD/USB/probe access occurs. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define STM32F429xx
#include "gs_board.h"
#include "gs_port.h"
#include "gs_display_swap.h"
#include "gs_ui_render.h"
/* Target addresses are 32-bit; restore the corresponding host pointer only
 * after checking the hardware-model low 32 address against the actual buffer. */
#define gs_display_reload_confirm actual_reload_confirm
#include "../Modules/Display/Src/gs_display_swap.c"
#undef gs_display_reload_confirm
static uint32_t tick, confirm_failure, paint_failure, set_address_failure, reload_failure, primask;
static uint32_t painted_preview_id, gpio_calls, full_paints, partial_paints;
static uint32_t partial_region_total, last_region_count, preview_paints;
static gs_ui_render_region_t last_regions[5];
volatile gs_board_diag_t g_gs_board_diag;
volatile gs_preview_diagnostics_t g_gs_preview_diag;
static gs_display_swap_t display_swap;
static volatile uint32_t reload_token, reload_done_token, reload_address;
static uint32_t reload_start_ms;
static uint8_t preview_pixels[GS_PREVIEW_BYTES];
static gs_preview_frame_t preview_copy;
static bool preview_valid, display_preview_visible;
static uint32_t display_preview_id, display_preview_ms;
static gs_ui_live_status_t live_status, display_live_status;
static bool display_live_status_valid;
static gs_display_refresh_t display_refresh;
static uint32_t buffers[2][800U*480U/2U];
static uint8_t source_pixels[GS_PREVIEW_BYTES];
static gs_ui_t fixture_ui;
static uint32_t hltdc;
typedef unsigned HAL_StatusTypeDef;
#define HAL_OK 0U
#define LCD_DISP_GPIO_Port 0U
#define LCD_DISP_Pin 4U
#define LCD_BL_GPIO_Port 0U
#define LCD_BL_Pin 7U
#define GPIO_PIN_SET 1U
#define LTDC_IT_RR 1U
#define LTDC_FLAG_RR 1U
#define LTDC_IRQn 88U
#define LTDC_RELOAD_VERTICAL_BLANKING 2U
#define __DMB() ((void)0)
#define __DSB() ((void)0)
#define __HAL_LTDC_DISABLE_IT(h, i) ((void)(h), (void)(i))
#define __HAL_LTDC_CLEAR_FLAG(h, f) ((void)(h), (void)(f))
static uint32_t HAL_GetTick(void) { return tick; }
static uint32_t __get_PRIMASK(void) { return primask; }
static void __disable_irq(void) { primask=1; }
static void __set_PRIMASK(uint32_t mask) { primask=mask; }
static void HAL_NVIC_ClearPendingIRQ(unsigned irq) { assert(irq==LTDC_IRQn); }
static void HAL_GPIO_WritePin(unsigned port,unsigned pin,unsigned value)
{ (void)port; assert((pin==4 || pin==7) && value==1); ++gpio_calls; }
static HAL_StatusTypeDef HAL_LTDC_SetAddress_NoReload(uint32_t *handle,uint32_t addr,unsigned layer)
{ assert(handle==&hltdc && layer==0); reload_address=addr; return set_address_failure; }
static HAL_StatusTypeDef HAL_LTDC_Reload(uint32_t *handle,unsigned reload)
{ assert(handle==&hltdc && reload==LTDC_RELOAD_VERTICAL_BLANKING); return reload_failure; }
bool gs_display_reload_confirm(gs_display_swap_t *swap,uint32_t token,const void *address)
{
    const uint8_t *pending=swap->buffers[swap->front_index^1U];
    if (confirm_failure || (uint32_t)(uintptr_t)address!=(uint32_t)(uintptr_t)pending) return false;
    return actual_reload_confirm(swap,token,pending);
}
gs_ui_render_status_t gs_ui_render_dashboard_rgb565(const gs_ui_t *state,const gs_ui_live_status_t *status,
    uint16_t *pixels,size_t capacity,uint16_t width,uint16_t height,size_t stride,const gs_ui_render_theme_t *theme)
{
    (void)status;(void)theme;
    assert(state==&fixture_ui && capacity==800U*480U && width==800 && height==480 && stride==800);
    ++full_paints; if(paint_failure) return GS_UI_RENDER_INVALID_ARGUMENT;
    memset(pixels,0x22,capacity*2U); return GS_UI_RENDER_OK;
}
gs_ui_render_status_t gs_ui_render_dashboard_regions_rgb565(const gs_ui_t *state,const gs_ui_live_status_t *status,
    uint16_t *pixels,size_t capacity,uint16_t width,uint16_t height,size_t stride,const gs_ui_render_theme_t *theme,
    const gs_ui_render_region_t *regions,size_t region_count)
{
    assert(regions && region_count>0U && region_count<=5U);
    ++partial_paints; partial_region_total+=(uint32_t)region_count;
    last_region_count=(uint32_t)region_count;
    memcpy(last_regions,regions,region_count*sizeof regions[0]);
    (void)status;(void)theme;
    assert(state==&fixture_ui && capacity==800U*480U && width==800 && height==480 && stride==800);
    if(paint_failure) return GS_UI_RENDER_INVALID_ARGUMENT;
    memset(pixels,0x33,capacity*2U); return GS_UI_RENDER_OK;
}
gs_ui_render_status_t gs_ui_render_preview_rgb565(uint16_t *pixels,size_t capacity,uint16_t width,uint16_t height,
    size_t stride,const gs_preview_frame_t *preview)
{
    (void)pixels;(void)capacity;(void)width;(void)height;(void)stride;
    painted_preview_id=preview->frame_id; ++preview_paints; return GS_UI_RENDER_OK;
}
#pragma warning(push)
#pragma warning(disable: 4311 4302 4312)
#include "preview_display_actual.inc"
#pragma warning(pop)
static void begin(void)
{
    memset((void *)&g_gs_board_diag,0,sizeof g_gs_board_diag);
    memset((void *)&g_gs_preview_diag,0,sizeof g_gs_preview_diag);
    memset(&live_status,0,sizeof live_status); memset(&preview_copy,0,sizeof preview_copy);
    memset(&fixture_ui,0,sizeof fixture_ui); memset(source_pixels,0x44,sizeof source_pixels);
    preview_valid=display_preview_visible=display_live_status_valid=false;
    display_preview_id=display_preview_ms=0;
    memset(&display_refresh,0,sizeof display_refresh);
    memset(display_buffer_history,0,sizeof display_buffer_history);
    reload_token=reload_done_token=reload_address=reload_start_ms=0;
    tick=100; confirm_failure=paint_failure=set_address_failure=reload_failure=primask=painted_preview_id=gpio_calls=0;
    full_paints=partial_paints=partial_region_total=last_region_count=preview_paints=0;
    memset(last_regions,0,sizeof last_regions);
    g_gs_board_diag.lcd_ready=1;
    assert(gs_display_swap_init(&display_swap,buffers[0],sizeof buffers[0],buffers[1],sizeof buffers[1],sizeof buffers[0]));
}
static gs_port_status_t incoming(uint32_t id,uint32_t capture)
{
    gs_preview_frame_t preview={{1,0},source_pixels,sizeof source_pixels,96,96,id,capture};
    return gs_port_gui_render(&fixture_ui,&preview);
}
static void complete(void) { assert(reload_token); reload_done_token=reload_token; }
int main(void)
{
    begin();
    assert(incoming(1U, 80U) == GS_PORT_OK);
    assert(full_paints == 1U && preview_paints == 0U);
    assert(g_gs_preview_diag.copied_id == 1U && !g_gs_preview_diag.confirmed_unique);
    assert(incoming(2U, 90U) == GS_PORT_BUSY);
    assert(g_gs_preview_diag.copied_id == 2U);
    complete(); tick = 120U;
    assert(incoming(3U, 110U) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_IDLE && g_gs_board_diag.display_frames == 1U);
    assert(g_gs_preview_diag.copied_id == 3U && !g_gs_preview_diag.confirmed_unique);
    assert(preview_paints == 0U && full_paints == 1U);

    ++fixture_ui.generation;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(full_paints == 2U && display_swap.state == GS_DISPLAY_PENDING);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_IDLE);

    live_status.gesture_state = GS_GESTURE_READY;
    live_status.now_ms = 130U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_IDLE);
    live_status.now_ms = 380U; tick = 380U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(full_paints == 3U && partial_paints == 0U);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    live_status.gesture_state = GS_GESTURE_CANDIDATE;
    live_status.now_ms = 390U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    live_status.now_ms = 640U; tick = 640U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(partial_paints == 1U && preview_paints == 0U);
    assert(last_region_count == 1U && last_regions[0].x == 0U &&
        last_regions[0].y == 436U && last_regions[0].width == 800U &&
        last_regions[0].height == 44U);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_IDLE);

    /* A display-only qualified target changes the header immediately,
       independent of the 250 ms ordinary-status coalescing grace. */
    live_status.hint_valid = 1U;
    live_status.hint_class = GS_STATIC_V_SIGN;
    live_status.now_ms = 650U; tick = 650U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_PENDING && partial_paints == 2U);
    assert(last_region_count >= 1U);
    {
        size_t index; bool header_found = false;
        for (index = 0U; index < last_region_count; ++index) {
            if (last_regions[index].x == 490U && last_regions[index].y == 0U &&
                last_regions[index].width == 310U && last_regions[index].height == 68U) {
                header_found = true;
            }
        }
        assert(header_found);
    }
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    live_status.hint_class = GS_STATIC_FIST;
    live_status.now_ms = 670U; tick = 670U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_PENDING && partial_paints == 3U);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    live_status.hint_valid = 0U;
    live_status.now_ms = 690U; tick = 690U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(display_swap.state == GS_DISPLAY_PENDING && partial_paints == 4U);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);

    begin(); paint_failure = 1U;
    assert(incoming(4U, 90U) == GS_PORT_ERROR);
    assert(display_swap.state == GS_DISPLAY_IDLE);
    paint_failure = 0U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    ++fixture_ui.generation; set_address_failure = 1U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_ERROR);
    assert(display_swap.state == GS_DISPLAY_IDLE && !reload_token);
    set_address_failure = 0U;
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    complete();
    assert(gs_port_gui_render(&fixture_ui, NULL) == GS_PORT_OK);
    assert(!primask);
    puts("PASS: reader BSP hides preview, preserves lease-copy diagnostics, commits LCD reload and clips status refresh");
    return 0;
}
