#if defined(GS_STATIC_USE_CUBEAI) && GS_STATIC_USE_CUBEAI
#include "gs_cubeai_backend.h"
#include "gs_network.h"
#include <string.h>

#define GS_APPROVED_MODEL_SIGNATURE UINT64_C(0xddc721ed9c76cc82)
#define GS_CCM_BASE UINT32_C(0x10000000)
#define GS_CCM_BYTES UINT32_C(0x00010000)

static uint8_t network[STAI_GS_NETWORK_CONTEXT_SIZE]
    __attribute__((aligned(STAI_GS_NETWORK_CONTEXT_ALIGNMENT)));
static uint8_t arena[STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES]
    __attribute__((section(".bss.ccm.ai_arena"),
                   aligned(STAI_GS_NETWORK_ACTIVATION_1_ALIGNMENT)));
static int8_t logits[STAI_GS_NETWORK_OUT_SIZE_BYTES]
    __attribute__((aligned(STAI_GS_NETWORK_OUT_1_ALIGNMENT)));
typedef char gs_cubeai_arena_must_fit_ccm[
    STAI_GS_NETWORK_ACTIVATIONS_SIZE_BYTES <= GS_CCM_BYTES ? 1 : -1];
static gs_int8_progress_fn active_progress;
static void *active_context;
static bool busy;
/* Ordinary SRAM ZI. The CCM arena is an UNINIT scatter region, so this flag
 * cannot share its section and is the sole guard for the first explicit clear. */
static bool arena_initialized;

bool gs_cubeai_layer_done(size_t layer, uint32_t outputs)
{
    return active_progress == NULL || active_progress(active_context, layer, outputs);
}

gs_ai_status_t gs_cubeai_contract_status(void)
{
    if (STAI_GS_NETWORK_IN_NUM != 1 || STAI_GS_NETWORK_OUT_NUM != 1 ||
        STAI_GS_NETWORK_IN_1_SIZE != 27648 ||
        STAI_GS_NETWORK_IN_1_HEIGHT != 96 ||
        STAI_GS_NETWORK_IN_1_WIDTH != 96 ||
        STAI_GS_NETWORK_IN_1_CHANNEL != 3 ||
        STAI_GS_NETWORK_IN_1_FORMAT != STAI_FORMAT_S8 ||
        STAI_GS_NETWORK_IN_1_SCALE != 1.0f ||
        STAI_GS_NETWORK_IN_1_ZERO_POINT != -128 ||
        (uint64_t)STAI_GS_NETWORK_MODEL_SIGNATURE != GS_APPROVED_MODEL_SIGNATURE ||
        STAI_GS_NETWORK_OUT_1_FORMAT != STAI_FORMAT_S8 ||
        STAI_GS_NETWORK_OUT_1_SIZE != 6 ||
        STAI_GS_NETWORK_OUT_SIZE_BYTES < STAI_GS_NETWORK_OUT_1_SIZE_BYTES ||
        STAI_GS_NETWORK_OUT_1_SCALE <= 0.0f ||
        STAI_GS_NETWORK_OUT_1_ZERO_POINT < -128 ||
        STAI_GS_NETWORK_OUT_1_ZERO_POINT > 127) {
        return GS_AI_CONTRACT_MISMATCH;
    }
#if defined(__ARMCC_VERSION)
    /* Target-only placement gate. Host parity builds use a native address. */
    if ((uintptr_t)arena < GS_CCM_BASE ||
        (uintptr_t)arena + sizeof(arena) > GS_CCM_BASE + GS_CCM_BYTES) {
        return GS_AI_CONTRACT_MISMATCH;
    }
#endif
    return GS_AI_OK;
}

gs_ai_status_t gs_cubeai_execute(const int8_t *input, size_t count, int8_t *output,
                               size_t output_count, float *output_scale,
                               int32_t *output_zero_point,
                               gs_int8_progress_fn progress, void *context)
{
    stai_ptr inputs[1], outputs[1], activations[1];
    stai_return_code rc;
    gs_ai_status_t contract = gs_cubeai_contract_status();
    if (contract != GS_AI_OK) { return contract; }
    if (input == NULL || output == NULL || output_scale == NULL || output_zero_point == NULL ||
        count != 27648U || output_count != 6U || ((uintptr_t)input & 3U)) {
        return GS_AI_INVALID_ARGUMENT;
    }
    if (busy) { return GS_AI_BACKEND_FAILURE; }
    busy = true;
    if (!arena_initialized) {
        /* gs_port_init enables CCM before VisionTask can call this backend.
         * Explicit initialization is required because the linker region is
         * UNINIT and the C runtime intentionally does not touch it. */
        memset(arena, 0, sizeof(arena));
        arena_initialized = true;
    }
    active_progress = progress;
    active_context = context;
    inputs[0] = (stai_ptr)input;
    outputs[0] = (stai_ptr)logits;
    activations[0] = (stai_ptr)arena;
    /* Reinitialize after every run, including early cancellation. */
    rc = stai_gs_network_init(network);
    if (rc == STAI_SUCCESS) { rc = stai_gs_network_set_activations(network, activations, 1); }
    if (rc == STAI_SUCCESS) { rc = stai_gs_network_set_inputs(network, inputs, 1); }
    if (rc == STAI_SUCCESS) { rc = stai_gs_network_set_outputs(network, outputs, 1); }
    if (rc == STAI_SUCCESS) { rc = stai_gs_network_run(network, STAI_MODE_SYNC); }
    if (rc == STAI_SUCCESS) {
        memcpy(output, logits, 6U);
        *output_scale = STAI_GS_NETWORK_OUT_1_SCALE;
        *output_zero_point = STAI_GS_NETWORK_OUT_1_ZERO_POINT;
    }
    active_progress = NULL;
    active_context = NULL;
    busy = false;
    return rc == STAI_SUCCESS ? GS_AI_OK : GS_AI_BACKEND_FAILURE;
}
#endif
