#ifndef GS_DEBUG_H
#define GS_DEBUG_H
#include <stdint.h>
typedef struct {
    uint32_t reset_flags, sysclk_hz, hclk_hz, pclk1_hz, pclk2_hz, pll48_hz;
    uint32_t fault_kind, cfsr, hfsr, dfsr, afsr, mmfar, bfar, shcsr;
    uint32_t msp, psp, ipsr, primask;
} gs_debug_diag_t;
extern volatile gs_debug_diag_t g_gs_debug_diag;
void gs_debug_boot_init(void);
/* Register evidence only. MSP/PSP are sampled inside this function and are
 * not advertised as the raw exception frame; unwind it with fireDAP/debugger. */
void gs_debug_fault(uint32_t kind);
#endif
