#include "gs_debug.h"
#include "stm32f4xx_hal.h"
volatile gs_debug_diag_t g_gs_debug_diag;
void gs_debug_boot_init(void)
{
    g_gs_debug_diag.reset_flags=RCC->CSR;
    __HAL_RCC_CLEAR_RESET_FLAGS();
    g_gs_debug_diag.sysclk_hz=HAL_RCC_GetSysClockFreq();
    g_gs_debug_diag.hclk_hz=HAL_RCC_GetHCLKFreq();
    g_gs_debug_diag.pclk1_hz=HAL_RCC_GetPCLK1Freq();
    g_gs_debug_diag.pclk2_hz=HAL_RCC_GetPCLK2Freq();
    /* Selected HSE25 PLL profile; report actual PLL48 register values. */
    uint32_t pll=RCC->PLLCFGR, m=pll&63U, n=(pll>>6)&511U, q=(pll>>24)&15U;
    uint32_t source=(pll&RCC_PLLCFGR_PLLSRC_HSE)?HSE_VALUE:HSI_VALUE;
    if (m && q) g_gs_debug_diag.pll48_hz=(uint32_t)(((uint64_t)source*n)/(m*q));
}
void gs_debug_fault(uint32_t kind)
{
    g_gs_debug_diag.fault_kind=kind;
    g_gs_debug_diag.cfsr=SCB->CFSR; g_gs_debug_diag.hfsr=SCB->HFSR;
    g_gs_debug_diag.dfsr=SCB->DFSR; g_gs_debug_diag.afsr=SCB->AFSR;
    g_gs_debug_diag.mmfar=SCB->MMFAR; g_gs_debug_diag.bfar=SCB->BFAR;
    g_gs_debug_diag.shcsr=SCB->SHCSR;
    g_gs_debug_diag.msp=__get_MSP(); g_gs_debug_diag.psp=__get_PSP();
    g_gs_debug_diag.ipsr=__get_IPSR(); g_gs_debug_diag.primask=__get_PRIMASK();
    __DSB();
}
