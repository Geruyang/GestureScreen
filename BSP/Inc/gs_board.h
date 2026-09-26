#ifndef GS_BOARD_H
#define GS_BOARD_H
#include <stdint.h>

#if !defined(STM32F429xx)
#error "GestureScreen board profile requires STM32F429xx"
#endif

/* 固定目标：野火 STM32F429 挑战者 V1。调试器可直接核对这些期望值。 */
#define GS_BOARD_PROFILE_EMBEDFIRE_F429_CHALLENGER_V1  0x45424631UL /* "EBF1" */
#define GS_BOARD_HSE_HZ                                 25000000UL
#define GS_BOARD_SDRAM_BYTES                            0x00800000UL
#define GS_BOARD_W25Q128_JEDEC                          0x00EF4018UL

/* Debugger-readable evidence, never a substitute for a hardware acceptance test. */
typedef struct {
    uint32_t board_profile, expected_hse_hz, expected_sdram_bytes;
    uint32_t sdram_ready, camera_ready, lcd_ready, flash_jedec;
    uint32_t flash_profile_match;
    uint32_t sdram_fail_addr, sdram_fail_expected, sdram_fail_actual;
    uint32_t camera_frames, camera_errors, camera_timeouts, camera_last_error;
    uint32_t display_frames, display_errors, display_stalled, display_max_render_ms;
    uint32_t watchdog_started;
} gs_board_diag_t;
extern volatile gs_board_diag_t g_gs_board_diag;
/* Called from ETH_Init USER CODE 0: release PHY clock after generated GPIO setup. */
void gs_board_early_init(void);
void gs_board_sdram_init(void);
/* Called by USER CODE IRQ hooks; immutable in-flight ticket is latched in BSP. */
void gs_board_dma_irq(void);
#endif
