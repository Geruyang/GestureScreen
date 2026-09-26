#include "gs_ai_int8_backend.h"

#include <limits.h>
#include <string.h>

#if defined(_MSC_VER)
#define GS_INT8_NOINLINE __declspec(noinline)
#else
#define GS_INT8_NOINLINE __attribute__((noinline))
#endif

/* 定点乘法：高32位乘积四舍五入，再按2的幂舍入。
 * 与TFLite默认双舍入整数参考路径对照；不用浮点反量化卷积。 */
static int32_t gs_int8_scale(int32_t value, int32_t multiplier, int8_t shift)
{
    int32_t high;
    int64_t wide = value;
    if (shift > 0) {
        wide *= (int64_t)1 << shift;
        if (wide > INT32_MAX) { wide = INT32_MAX; }
        if (wide < INT32_MIN) { wide = INT32_MIN; }
    }
    /* After the optional saturation, this operand is always int32. State the
       bound in its type so ARM emits a 32x32 long multiply, not a 64x32 product. */
    value = (int32_t)wide;
    /* For nonnegative multiplier: original signed nudge plus truncation
       is exactly floor((product + 2^30)/2^31), including negative ties.
       ARMClang/MSVC implement signed >> as arithmetic (verified by tests). */
    high = (int32_t)(((int64_t)value * multiplier + (INT64_C(1) << 30)) >> 31);
    if (shift < 0) {
        uint32_t exponent = (uint32_t)(-(int32_t)shift);
        /* magnitude <= 2^31; adding a half divisor (<= 2^30) fits uint32.
           The second rounding remains half away from zero, unlike high multiply. */
        uint32_t magnitude = high < 0 ? (uint32_t)(-(int64_t)high) : (uint32_t)high;
        uint32_t rounded = (magnitude + (UINT32_C(1) << (exponent - 1U))) >> exponent;
        high = high < 0 ? -(int32_t)rounded : (int32_t)rounded;
    }
    return high;
}

/* Four raw signed-int8 products. Cortex-M4's existing DSP instructions need
   no runtime library. Caller checks four-byte alignment for the word loads;
   SXTB16 selects bytes 0/2 and the rotated word selects 1/3 on the target's
   little-endian memory. Host tests emulate the packed path. */
static uint32_t gs_int8_even(int32_t word)
{
#if defined(__ARM_FEATURE_DSP)
    return (uint32_t)__builtin_arm_sxtb16(word);
#else
    uint32_t value = (uint32_t)word;
    return (uint16_t)(int16_t)(int8_t)value |
        ((uint32_t)(uint16_t)(int16_t)(int8_t)(value >> 16) << 16);
#endif
}
static int32_t gs_int8_dual(uint32_t a, uint32_t b, int32_t accumulator)
{
#if defined(__ARM_FEATURE_DSP)
    return __builtin_arm_smlad((int32_t)a, (int32_t)b, accumulator);
#else
    return accumulator + (int16_t)a * (int16_t)b +
        (int16_t)(a >> 16) * (int16_t)(b >> 16);
#endif
}
static int32_t gs_int8_dot4(const int8_t *input, const int8_t *weights, int32_t accumulator)
{
#if defined(__ARM_FEATURE_DSP) || defined(GS_INT8_TEST_DSP)
    uint32_t a, b;
    memcpy(&a, input, sizeof a); memcpy(&b, weights, sizeof b);
    accumulator = gs_int8_dual(gs_int8_even((int32_t)a), gs_int8_even((int32_t)b), accumulator);
    a = (a >> 8) | (a << 24); b = (b >> 8) | (b << 24);
    return gs_int8_dual(gs_int8_even((int32_t)a), gs_int8_even((int32_t)b), accumulator);
#else
    return accumulator + input[0] * weights[0] + input[1] * weights[1] +
        input[2] * weights[2] + input[3] * weights[3];
#endif
}

static int8_t gs_int8_clamp(int32_t value, const gs_int8_layer_t *layer)
{
    if (value < layer->activation_min) { value = layer->activation_min; }
    if (value > layer->activation_max) { value = layer->activation_max; }
    return (int8_t)value;
}

static int8_t gs_int8_finish(int32_t accumulator, uint32_t channel, const gs_int8_layer_t *layer)
{
    /* Only the completed accumulator may bypass finish. Validated nonnegative
       multiplier and any legal shift preserve <=0; biased activation min is0. */
    if (accumulator <= 0 && layer->output_zero == -128 && layer->activation_min == -128) { return -128; }
    int32_t minimum = layer->activation_min - layer->output_zero;
    int32_t maximum = layer->activation_max - layer->output_zero;
    accumulator = gs_int8_scale(accumulator, layer->multipliers[channel], layer->shifts[channel]);
    /* Validated activation bounds are a subset of int8. Clamp once before
       zero-point addition; this subsumes the former int8-then-activation clamp. */
    if (accumulator < minimum) { accumulator = minimum; }
    if (accumulator > maximum) { accumulator = maximum; }
    return (int8_t)(accumulator + layer->output_zero);
}

static bool gs_int8_advance(gs_int8_progress_fn progress, void *context,
                           size_t index, uint32_t completed)
{
    return (completed & 63U) != 0U || progress == NULL || progress(context, index, completed);
}

typedef struct { int32_t multiplier, shift, zero, minimum, maximum; } gs_int8_quant_t;
static gs_int8_quant_t gs_int8_quant(const gs_int8_layer_t *layer, uint32_t channel)
{
    gs_int8_quant_t q = {layer->multipliers[channel], layer->shifts[channel],
        layer->output_zero, layer->activation_min - layer->output_zero, layer->activation_max - layer->output_zero};
    return q;
}
static int8_t gs_int8_quant_finish(int32_t accumulator, const gs_int8_quant_t *q)
{
    accumulator = gs_int8_scale(accumulator, q->multiplier, (int8_t)q->shift);
    if (accumulator < q->minimum) { accumulator = q->minimum; }
    if (accumulator > q->maximum) { accumulator = q->maximum; }
    return (int8_t)(accumulator + q->zero);
}
static uint32_t gs_int8_pair(int16_t low, int16_t high)
{
    return (uint16_t)low | ((uint32_t)(uint16_t)high << 16U);
}

/* Two corrected q15 input columns, in 0/2,1/3 order, reused across all output
 * channels. Four accumulators reuse both columns and both weight rows. The
 * dispatch bound proves every intermediate fits int32, including paired MACs. */
static GS_INT8_NOINLINE gs_ai_status_t gs_int8_pointwise_full(const gs_int8_layer_t *layer,
    const int8_t *input, int8_t *output, gs_int8_progress_fn progress, void *context, size_t index)
{
    int16_t columns[2][256];
    uint32_t pixels = (uint32_t)layer->output_h * layer->output_w, completed = 0U;
    for (uint32_t pixel = 0U; pixel < pixels; pixel += 2U) {
        bool second_pixel = true;
        for (uint32_t p = 0U; p < (second_pixel ? 2U : 1U); ++p) {
            const int8_t *sample = input + (size_t)(pixel + p) * layer->input_c;
            for (uint32_t ic = 0U; ic < layer->input_c; ic += 4U) {
                columns[p][ic] = (int16_t)((int32_t)sample[ic] - layer->input_zero);
                columns[p][ic + 1U] = (int16_t)((int32_t)sample[ic + 2U] - layer->input_zero);
                columns[p][ic + 2U] = (int16_t)((int32_t)sample[ic + 1U] - layer->input_zero);
                columns[p][ic + 3U] = (int16_t)((int32_t)sample[ic + 3U] - layer->input_zero);
            }
        }
        for (uint32_t oc = 0U; oc < layer->output_c; oc += 2U) {
            bool second_channel = true;
            const int8_t *w0 = layer->weights + (size_t)oc * layer->input_c;
            const int8_t *w1 = second_channel ? w0 + layer->input_c : w0;
            int32_t a00 = layer->bias[oc], a01 = a00;
            int32_t a10 = layer->bias[second_channel ? oc + 1U : oc], a11 = a10;
            gs_int8_quant_t q0 = gs_int8_quant(layer, oc);
            gs_int8_quant_t q1 = gs_int8_quant(layer, second_channel ? oc + 1U : oc);
            #if defined(__clang__)
            #pragma clang loop unroll(disable)
            #endif
            for (uint32_t ic = 0U; ic < layer->input_c; ic += 4U) {
                uint32_t x0e, x0o, x1e = 0U, x1o = 0U, w0word, w1word;
                memcpy(&x0e, columns[0] + ic, 4U); memcpy(&x0o, columns[0] + ic + 2U, 4U);
                if (second_pixel) { memcpy(&x1e, columns[1] + ic, 4U); memcpy(&x1o, columns[1] + ic + 2U, 4U); }
                memcpy(&w0word, w0 + ic, 4U); memcpy(&w1word, w1 + ic, 4U);
                uint32_t w0e = gs_int8_even((int32_t)w0word), w1e = gs_int8_even((int32_t)w1word);
                uint32_t w0o = gs_int8_even((int32_t)((w0word >> 8U) | (w0word << 24U)));
                uint32_t w1o = gs_int8_even((int32_t)((w1word >> 8U) | (w1word << 24U)));
                a00 = gs_int8_dual(x0e, w0e, a00); a00 = gs_int8_dual(x0o, w0o, a00);
                if (second_channel) { a10 = gs_int8_dual(x0e, w1e, a10); a10 = gs_int8_dual(x0o, w1o, a10); }
                if (second_pixel) {
                    a01 = gs_int8_dual(x1e, w0e, a01); a01 = gs_int8_dual(x1o, w0o, a01);
                    if (second_channel) { a11 = gs_int8_dual(x1e, w1e, a11); a11 = gs_int8_dual(x1o, w1o, a11); }
                }
            }
            size_t at = (size_t)pixel * layer->output_c + oc;
            output[at] = gs_int8_quant_finish(a00, &q0);
            if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
            if (second_channel) {
                output[at + 1U] = gs_int8_quant_finish(a10, &q1);
                if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
            }
            if (second_pixel) {
                output[at + layer->output_c] = gs_int8_quant_finish(a01, &q0);
                if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
                if (second_channel) {
                    output[at + layer->output_c + 1U] = gs_int8_quant_finish(a11, &q1);
                    if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
                }
            }
        }
    }
    if ((completed & 63U) != 0U && progress != NULL && !progress(context, index, completed)) { return GS_AI_BACKEND_FAILURE; }
    return GS_AI_OK;
}

static GS_INT8_NOINLINE gs_ai_status_t gs_int8_pointwise_tail(const gs_int8_layer_t *layer,
    const int8_t *input, int8_t *output, gs_int8_progress_fn progress, void *context, size_t index)
{
    int16_t columns[2][256];
    uint32_t pixels = (uint32_t)layer->output_h * layer->output_w, completed = 0U;
    for (uint32_t pixel = 0U; pixel < pixels; pixel += 2U) {
        bool second_pixel = pixel + 1U < pixels;
        for (uint32_t p = 0U; p < (second_pixel ? 2U : 1U); ++p) {
            const int8_t *sample = input + (size_t)(pixel + p) * layer->input_c;
            for (uint32_t ic = 0U; ic < layer->input_c; ic += 4U) {
                columns[p][ic] = (int16_t)((int32_t)sample[ic] - layer->input_zero);
                columns[p][ic + 1U] = (int16_t)((int32_t)sample[ic + 2U] - layer->input_zero);
                columns[p][ic + 2U] = (int16_t)((int32_t)sample[ic + 1U] - layer->input_zero);
                columns[p][ic + 3U] = (int16_t)((int32_t)sample[ic + 3U] - layer->input_zero);
            }
        }
        for (uint32_t oc = 0U; oc < layer->output_c; oc += 2U) {
            bool second_channel = oc + 1U < layer->output_c;
            const int8_t *w0 = layer->weights + (size_t)oc * layer->input_c;
            const int8_t *w1 = second_channel ? w0 + layer->input_c : w0;
            int32_t a00 = layer->bias[oc], a01 = a00;
            int32_t a10 = layer->bias[second_channel ? oc + 1U : oc], a11 = a10;
            gs_int8_quant_t q0 = gs_int8_quant(layer, oc);
            gs_int8_quant_t q1 = gs_int8_quant(layer, second_channel ? oc + 1U : oc);
            #if defined(__clang__)
            #pragma clang loop unroll(disable)
            #endif
            for (uint32_t ic = 0U; ic < layer->input_c; ic += 4U) {
                uint32_t x0e, x0o, x1e = 0U, x1o = 0U, w0word, w1word;
                memcpy(&x0e, columns[0] + ic, 4U); memcpy(&x0o, columns[0] + ic + 2U, 4U);
                if (second_pixel) { memcpy(&x1e, columns[1] + ic, 4U); memcpy(&x1o, columns[1] + ic + 2U, 4U); }
                memcpy(&w0word, w0 + ic, 4U); memcpy(&w1word, w1 + ic, 4U);
                uint32_t w0e = gs_int8_even((int32_t)w0word), w1e = gs_int8_even((int32_t)w1word);
                uint32_t w0o = gs_int8_even((int32_t)((w0word >> 8U) | (w0word << 24U)));
                uint32_t w1o = gs_int8_even((int32_t)((w1word >> 8U) | (w1word << 24U)));
                a00 = gs_int8_dual(x0e, w0e, a00); a00 = gs_int8_dual(x0o, w0o, a00);
                if (second_channel) { a10 = gs_int8_dual(x0e, w1e, a10); a10 = gs_int8_dual(x0o, w1o, a10); }
                if (second_pixel) {
                    a01 = gs_int8_dual(x1e, w0e, a01); a01 = gs_int8_dual(x1o, w0o, a01);
                    if (second_channel) { a11 = gs_int8_dual(x1e, w1e, a11); a11 = gs_int8_dual(x1o, w1o, a11); }
                }
            }
            size_t at = (size_t)pixel * layer->output_c + oc;
            output[at] = gs_int8_quant_finish(a00, &q0);
            if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
            if (second_channel) {
                output[at + 1U] = gs_int8_quant_finish(a10, &q1);
                if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
            }
            if (second_pixel) {
                output[at + layer->output_c] = gs_int8_quant_finish(a01, &q0);
                if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
                if (second_channel) {
                    output[at + layer->output_c + 1U] = gs_int8_quant_finish(a11, &q1);
                    if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
                }
            }
        }
    }
    if ((completed & 63U) != 0U && progress != NULL && !progress(context, index, completed)) { return GS_AI_BACKEND_FAILURE; }
    return GS_AI_OK;
}

static gs_ai_status_t gs_int8_pointwise_tile(const gs_int8_layer_t *layer,
    const int8_t *input, int8_t *output, gs_int8_progress_fn progress, void *context, size_t index)
{
    if ((((uint32_t)layer->output_h * layer->output_w | layer->output_c) & 1U) == 0U)
        return gs_int8_pointwise_full(layer, input, output, progress, context, index);
    return gs_int8_pointwise_tail(layer, input, output, progress, context, index);
}
/* First-layer C1 convolution: gather corrected inputs/valid positions once per
 * pixel, then share packed inputs across channels. High-side partial padding is
 * preserved, including 96->48 K3/S2/pad0's final row/column. */
static gs_ai_status_t gs_int8_conv3_c1(const gs_int8_layer_t *layer,
    const int8_t *input, int8_t *output, gs_int8_progress_fn progress, void *context, size_t index)
{
    uint32_t packed_weights[16][4], completed = 0U;
    gs_int8_quant_t quant[16];
    for (uint32_t oc = 0U; oc < layer->output_c; ++oc) {
        const int8_t *w = layer->weights + oc * 9U;
        for (uint32_t t = 0U; t < 4U; ++t) { packed_weights[oc][t] = gs_int8_pair(w[t * 2U], w[t * 2U + 1U]); }
        quant[oc] = gs_int8_quant(layer, oc);
    }
    for (uint32_t oy = 0U; oy < layer->output_h; ++oy) for (uint32_t ox = 0U; ox < layer->output_w; ++ox) {
        int16_t samples[9]; uint8_t filter[9]; uint32_t count = 0U;
        for (uint32_t ky = 0U; ky < 3U; ++ky) {
            int32_t iy = (int32_t)(oy * layer->stride_h + ky) - layer->pad_h;
            if (iy < 0 || iy >= layer->input_h) { continue; }
            for (uint32_t kx = 0U; kx < 3U; ++kx) {
                int32_t ix = (int32_t)(ox * layer->stride_w + kx) - layer->pad_w;
                if (ix < 0 || ix >= layer->input_w) { continue; }
                samples[count] = (int16_t)((int32_t)input[(size_t)iy * layer->input_w + (size_t)ix] - layer->input_zero);
                filter[count++] = (uint8_t)(ky * 3U + kx);
            }
        }
        uint32_t pairs[4] = {0U, 0U, 0U, 0U};
        if (count == 9U) { for (uint32_t t = 0U; t < 4U; ++t) { pairs[t] = gs_int8_pair(samples[t * 2U], samples[t * 2U + 1U]); } }
        for (uint32_t oc = 0U; oc < layer->output_c; ++oc) {
            int32_t accumulator = layer->bias[oc];
            const int8_t *w = layer->weights + oc * 9U;
            if (count == 9U) {
                accumulator = gs_int8_dual(pairs[0], packed_weights[oc][0], accumulator);
                accumulator = gs_int8_dual(pairs[1], packed_weights[oc][1], accumulator);
                accumulator = gs_int8_dual(pairs[2], packed_weights[oc][2], accumulator);
                accumulator = gs_int8_dual(pairs[3], packed_weights[oc][3], accumulator);
                accumulator += samples[8] * w[8];
            } else {
                for (uint32_t t = 0U; t < count; ++t) { accumulator += samples[t] * w[filter[t]]; }
            }
            output[((size_t)oy * layer->output_w + ox) * layer->output_c + oc] = gs_int8_quant_finish(accumulator, &quant[oc]);
            if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
        }
    }
    if ((completed & 63U) != 0U && progress != NULL && !progress(context, index, completed)) { return GS_AI_BACKEND_FAILURE; }
    return GS_AI_OK;
}

/* A pointwise channel reuses its weights and zero-point correction across
   all pixels. No scratch allocation and no change to NHWC output layout. */
static gs_ai_status_t gs_int8_pointwise(const gs_int8_layer_t *layer,
    const int8_t *input, int8_t *output, gs_int8_progress_fn progress, void *context, size_t index)
{
    uint32_t oc, pixel, ic, completed = 0U;
    uint32_t pixels = (uint32_t)layer->output_h * layer->output_w;
    for (oc = 0U; oc < layer->output_c; ++oc) {
        const int8_t *weights = layer->weights + (size_t)oc * layer->input_c;
        int32_t correction = layer->bias[oc], sum = 0;
        bool packed = (((uintptr_t)input | (uintptr_t)weights) & 3U) == 0U &&
                      (layer->input_c & 3U) == 0U;
        for (ic = 0U; ic < layer->input_c; ++ic) { sum += weights[ic]; }
        correction -= layer->input_zero * sum;
        for (pixel = 0U; pixel < pixels; ++pixel) {
            const int8_t *sample = input + (size_t)pixel * layer->input_c;
            int32_t accumulator = correction;
            ic = 0U;
            if (packed) {
                for (; ic + 4U <= layer->input_c; ic += 4U) {
                    accumulator = gs_int8_dot4(sample + ic, weights + ic, accumulator);
                }
            }
            for (; ic < layer->input_c; ++ic) { accumulator += sample[ic] * weights[ic]; }
            output[(size_t)pixel * layer->output_c + oc] = gs_int8_finish(accumulator, oc, layer);
            if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
        }
    }
    if ((completed & 63U) != 0U && progress != NULL && !progress(context, index, completed)) {
        return GS_AI_BACKEND_FAILURE;
    }
    return GS_AI_OK;
}


typedef struct { int32_t multiplier; uint32_t exponent, half; } gs_int8_negative_quant_t;
static int8_t gs_int8_negative_relu(int32_t accumulator, const gs_int8_negative_quant_t *q)
{
    /* Existing validation guarantees multiplier>=0. Actual negative-shift
       ReLU domain: nonpositive accumulator stays nonpositive after both rounds. */
    if (accumulator <= 0) { return -128; }
    int32_t high = (int32_t)(((int64_t)accumulator * q->multiplier + (INT64_C(1)<<30))>>31);
    uint32_t rounded = ((uint32_t)high + q->half) >> q->exponent;
    if (rounded > 255U) { rounded = 255U; }
    return (int8_t)((int32_t)rounded - 128);
}
static int32_t gs_int8_low_mac(uint32_t a, uint32_t b, int32_t accumulator)
{
#if defined(__ARM_FEATURE_DSP)
    return __builtin_arm_smlabb((int32_t)a,(int32_t)b,accumulator);
#else
    return accumulator + (int16_t)a * (int16_t)b;
#endif
}
static int32_t gs_int8_high_mac(uint32_t a, uint32_t b, int32_t accumulator)
{
#if defined(__ARM_FEATURE_DSP)
    return __builtin_arm_smlatt((int32_t)a,(int32_t)b,accumulator);
#else
    return accumulator + (int16_t)(a>>16) * (int16_t)(b>>16);
#endif
}
static GS_INT8_NOINLINE void gs_int8_dw4_dot(const int8_t *const p[9],
    const uint8_t *packed_weights, uint32_t oc, const int32_t *correction, int32_t result[4])
{
    int32_t a0=correction[oc],a1=correction[oc+1U],a2=correction[oc+2U],a3=correction[oc+3U];
#if defined(__clang__)
    #pragma clang loop unroll(disable)
#endif
    for (uint32_t t=0U;t<9U;++t) {
        uint32_t raw; memcpy(&raw,p[t]+oc,4U);
        uint32_t x02=gs_int8_even((int32_t)raw);
        uint32_t x13=gs_int8_even((int32_t)((raw>>8U)|(raw<<24U)));
        uint32_t w02,w13;
        const uint8_t *at=packed_weights+((size_t)t*64U+oc/4U)*8U;
        /* Workspace is declared byte storage. Typed memcpy locals preserve its
           aliasing contract; do not dereference a uint32/struct cast into it. */
        memcpy(&w02,at,4U);memcpy(&w13,at+4U,4U);
        a0=gs_int8_low_mac(x02,w02,a0);a2=gs_int8_high_mac(x02,w02,a2);
        a1=gs_int8_low_mac(x13,w13,a1);a3=gs_int8_high_mac(x13,w13,a3);
    }
    result[0]=a0;result[1]=a1;result[2]=a2;result[3]=a3;
}
/* Boundary/padding decisions and input offsets are shared by all channels
   of one depthwise pixel instead of repeating nine coordinate calculations. */
/* Do not inline this 1KiB correction cache into the dispatcher's frame: it is
 * mutually exclusive with pointwise's 1KiB columns, not simultaneous scratch. */
static GS_INT8_NOINLINE gs_ai_status_t gs_int8_depthwise3(const gs_int8_layer_t *layer,
    const int8_t *input, int8_t *output, gs_int8_progress_fn progress, void *context, size_t index,
    uint8_t *scratch, size_t scratch_size)
{
    uint32_t oy, ox, oc, ky, kx, count, tap, completed = 0U;
    const int8_t *samples[9], *weights[9];
    int32_t correction[256];
    /* Current output slot's unused tail. Scratch is per invocation and disjoint
       from output/previous tensor, so independent workspaces remain reentrant. */
    bool cache = scratch != NULL && scratch_size >= 7680U && ((uintptr_t)scratch & 3U) == 0U;
    bool packed, negative_relu = cache && layer->output_c <= 256U && layer->output_zero == -128 &&
        layer->activation_min == -128 && layer->activation_max == 127;
    bool corrected = layer->output_c <= 256U;
    int64_t bound = INT32_MAX - 9 * INT64_C(32768);
    for (oc = 0U; oc < layer->output_c; ++oc) {
        if ((int64_t)layer->bias[oc] < -bound || (int64_t)layer->bias[oc] > bound) { corrected = false; }
    }
    if (corrected) {
        for (oc = 0U; oc < layer->output_c; ++oc) {
            int32_t sum = 0;
            for (tap = 0U; tap < 9U; ++tap) { sum += layer->weights[(size_t)tap * layer->output_c + oc]; }
            correction[oc] = layer->bias[oc] - layer->input_zero * sum;
        }
    }
    packed = cache && corrected && (layer->output_c & 3U) == 0U &&
        layer->input_c == layer->output_c &&
        (((uintptr_t)input | (uintptr_t)layer->weights) & 3U) == 0U;
    if (packed) {
        for (tap=0U;tap<9U;++tap) for (oc=0U;oc<layer->output_c;oc+=4U) {
            uint32_t raw; memcpy(&raw,layer->weights+(size_t)tap*layer->output_c+oc,4U);
            uint32_t even=gs_int8_even((int32_t)raw);
            uint32_t odd=gs_int8_even((int32_t)((raw>>8U)|(raw<<24U)));
            uint8_t *at=scratch+((size_t)tap*64U+oc/4U)*8U;
            memcpy(at,&even,4U);memcpy(at+4U,&odd,4U);
        }
    }
    for (oc=0U;oc<layer->output_c;++oc) { if(layer->shifts[oc]>=0) { negative_relu=false; } }
    if(negative_relu) for (oc=0U;oc<layer->output_c;++oc) {
        gs_int8_negative_quant_t q;
        q.multiplier=layer->multipliers[oc];
        q.exponent=(uint32_t)(-(int32_t)layer->shifts[oc]);
        q.half=UINT32_C(1)<<(q.exponent-1U);
        memcpy(scratch+4608U+(size_t)oc*sizeof q,&q,sizeof q);
    }
    for (oy = 0U; oy < layer->output_h; ++oy) {
        for (ox = 0U; ox < layer->output_w; ++ox) {
            count = 0U;
            for (ky = 0U; ky < 3U; ++ky) {
                int32_t iy = (int32_t)(oy * layer->stride_h + ky) - layer->pad_h;
                if (iy < 0 || iy >= layer->input_h) { continue; }
                for (kx = 0U; kx < 3U; ++kx) {
                    int32_t ix = (int32_t)(ox * layer->stride_w + kx) - layer->pad_w;
                    if (ix < 0 || ix >= layer->input_w) { continue; }
                    samples[count] = input + ((size_t)iy * layer->input_w + (size_t)ix) * layer->input_c;
                    weights[count] = layer->weights + ((size_t)ky * 3U + kx) * layer->output_c;
                    ++count;
                }
            }
            for (oc = 0U; oc < layer->output_c; ++oc) {
                if (packed && count==9U) {
                    int32_t values[4];
                    gs_int8_dw4_dot(samples,scratch,oc,correction,values);
                    size_t at=((size_t)oy*layer->output_w+ox)*layer->output_c+oc;
                    for(uint32_t channel=0U;channel<4U;++channel) {
                        if(negative_relu) {
                            gs_int8_negative_quant_t q;
                            memcpy(&q,scratch+4608U+(size_t)(oc+channel)*sizeof q,sizeof q);
                            output[at+channel]=gs_int8_negative_relu(values[channel],&q);
                        } else { output[at+channel]=gs_int8_finish(values[channel],oc+channel,layer); }
                        if(!gs_int8_advance(progress,context,index,++completed)) return GS_AI_BACKEND_FAILURE;
                    }
                    oc+=3U;continue;
                }
                int32_t accumulator = layer->bias[oc];
                if (corrected && count == 9U) {
                    accumulator = correction[oc];
                    accumulator += samples[0][oc] * weights[0][oc];
                    accumulator += samples[1][oc] * weights[1][oc];
                    accumulator += samples[2][oc] * weights[2][oc];
                    accumulator += samples[3][oc] * weights[3][oc];
                    accumulator += samples[4][oc] * weights[4][oc];
                    accumulator += samples[5][oc] * weights[5][oc];
                    accumulator += samples[6][oc] * weights[6][oc];
                    accumulator += samples[7][oc] * weights[7][oc];
                    accumulator += samples[8][oc] * weights[8][oc];
                } else for (tap = 0U; tap < count; ++tap) {
                    accumulator += ((int32_t)samples[tap][oc] - layer->input_zero) * weights[tap][oc];
                }
                if(negative_relu) {
                    gs_int8_negative_quant_t q;
                    memcpy(&q,scratch+4608U+(size_t)oc*sizeof q,sizeof q);
                    output[((size_t)oy * layer->output_w + ox) * layer->output_c + oc]=gs_int8_negative_relu(accumulator,&q);
                } else {
                    output[((size_t)oy * layer->output_w + ox) * layer->output_c + oc]=gs_int8_finish(accumulator,oc,layer);
                }
                if (!gs_int8_advance(progress, context, index, ++completed)) { return GS_AI_BACKEND_FAILURE; }
            }
        }
    }
    if ((completed & 63U) != 0U && progress != NULL && !progress(context, index, completed)) {
        return GS_AI_BACKEND_FAILURE;
    }
    return GS_AI_OK;
}

static gs_ai_status_t gs_int8_layer_run(const gs_int8_layer_t *layer,
                                       const int8_t *input, int8_t *output,
                                       gs_int8_progress_fn progress, void *context, size_t index,
                                       uint8_t *scratch, size_t scratch_size)
{
    uint32_t oy, ox, oc, ky, kx, ic, completed = 0U;
    if (layer->operation != GS_INT8_AVERAGE &&
        (layer->weights == NULL || layer->bias == NULL ||
         layer->multipliers == NULL || layer->shifts == NULL)) {
        return GS_AI_BACKEND_FAILURE;
    }
    if (layer->operation != GS_INT8_AVERAGE) {
        for (oc = 0U; oc < layer->output_c; ++oc) {
            if (layer->shifts[oc] < -31 || layer->shifts[oc] > 30 || layer->multipliers[oc] < 0) {
                return GS_AI_BACKEND_FAILURE;
            }
        }
    }
    if (layer->operation == GS_INT8_CONV && layer->kernel_h == 1U && layer->kernel_w == 1U &&
        layer->stride_h == 1U && layer->stride_w == 1U && layer->pad_h == 0U && layer->pad_w == 0U &&
        layer->input_h == layer->output_h && layer->input_w == layer->output_w) {
        bool safe = true;
        /* Reordering zero-point correction is only allowed when all intermediate
           sums fit int32; unusual huge biases keep the original accumulation. */
        int64_t bound = INT32_MAX - (int64_t)layer->input_c * 32768;
        for (oc = 0U; oc < layer->output_c; ++oc) {
            if ((int64_t)layer->bias[oc] < -bound || (int64_t)layer->bias[oc] > bound) { safe = false; }
        }
        if (safe) {
            if (layer->input_c <= 256U && (layer->input_c & 3U) == 0U && ((uintptr_t)layer->weights & 3U) == 0U) {
                return gs_int8_pointwise_tile(layer, input, output, progress, context, index);
            }
            return gs_int8_pointwise(layer, input, output, progress, context, index);
        }
    }
    if (layer->operation == GS_INT8_CONV && layer->kernel_h == 3U && layer->kernel_w == 3U &&
        layer->input_c == 1U && layer->output_c <= 16U) {
        bool safe = true;
        int64_t bound = INT32_MAX - 9 * INT64_C(32768);
        for (oc = 0U; oc < layer->output_c; ++oc) {
            if ((int64_t)layer->bias[oc] < -bound || (int64_t)layer->bias[oc] > bound) { safe = false; }
        }
        if (safe) { return gs_int8_conv3_c1(layer, input, output, progress, context, index); }
    }
    if (layer->operation == GS_INT8_DEPTHWISE && layer->kernel_h == 3U && layer->kernel_w == 3U) {
        return gs_int8_depthwise3(layer, input, output, progress, context, index, scratch, scratch_size);
    }
    for (oy = 0U; oy < layer->output_h; ++oy) {
        for (ox = 0U; ox < layer->output_w; ++ox) {
            for (oc = 0U; oc < layer->output_c; ++oc) {
                int32_t accumulator = layer->operation == GS_INT8_AVERAGE ? 0 : layer->bias[oc];
                uint32_t count = 0U;
                for (ky = 0U; ky < layer->kernel_h; ++ky) {
                    int32_t iy = (int32_t)(oy * layer->stride_h + ky) - layer->pad_h;
                    if (iy < 0 || iy >= layer->input_h) { continue; }
                    for (kx = 0U; kx < layer->kernel_w; ++kx) {
                        int32_t ix = (int32_t)(ox * layer->stride_w + kx) - layer->pad_w;
                        size_t base;
                        if (ix < 0 || ix >= layer->input_w) { continue; }
                        base = ((size_t)iy * layer->input_w + (size_t)ix) * layer->input_c;
                        if (layer->operation == GS_INT8_AVERAGE) {
                            accumulator += input[base + oc];
                            ++count;
                        } else if (layer->operation == GS_INT8_DEPTHWISE) {
                            size_t filter = ((size_t)ky * layer->kernel_w + kx) * layer->output_c + oc;
                            accumulator += ((int32_t)input[base + oc] - layer->input_zero) * layer->weights[filter];
                        } else {
                            size_t filter = (((size_t)oc * layer->kernel_h + ky) * layer->kernel_w + kx) * layer->input_c;
                            for (ic = 0U; ic < layer->input_c; ++ic) {
                                accumulator += ((int32_t)input[base + ic] - layer->input_zero) * layer->weights[filter + ic];
                            }
                        }
                    }
                }
                if (layer->operation == GS_INT8_AVERAGE) {
                    if (count == 0U) { return GS_AI_BACKEND_FAILURE; }
                    accumulator = (accumulator + (accumulator >= 0 ? (int32_t)(count / 2U) : -(int32_t)(count / 2U))) / (int32_t)count;
                } else {
                    accumulator = gs_int8_scale(accumulator, layer->multipliers[oc], layer->shifts[oc]);
                    /* 先饱和到int8有效偏移范围，避免输出zero point相加溢出。 */
                    if (accumulator < -128 - layer->output_zero) { accumulator = -128 - layer->output_zero; }
                    if (accumulator > 127 - layer->output_zero) { accumulator = 127 - layer->output_zero; }
                    accumulator += layer->output_zero;
                }
                output[((size_t)oy * layer->output_w + ox) * layer->output_c + oc] = gs_int8_clamp(accumulator, layer);
                ++completed;
                if ((completed & 63U) == 0U && progress != NULL &&
                    !progress(context, index, completed)) {
                    return GS_AI_BACKEND_FAILURE;
                }
            }
        }
    }
    if ((completed & 63U) != 0U && progress != NULL && !progress(context, index, completed)) {
        return GS_AI_BACKEND_FAILURE;
    }
    return GS_AI_OK;
}

gs_ai_status_t gs_int8_execute_progress(const gs_int8_model_t *model,
    const int8_t *input, size_t input_size, int8_t *output, size_t output_size,
    int8_t *workspace, size_t workspace_size, gs_int8_progress_fn progress, void *context)
{
    size_t index, previous_size = input_size;
    const int8_t *previous = input;
    if (model == NULL || model->layers == NULL || model->layer_count == 0U ||
        input == NULL || output == NULL || workspace == NULL ||
        input_size != model->input_size || output_size != model->output_size ||
        model->slot_size == 0U || model->slot_size > SIZE_MAX / 2U ||
        workspace_size < model->slot_size * 2U) {
        return GS_AI_INVALID_ARGUMENT;
    }
    for (index = 0U; index < model->layer_count; ++index) {
        const gs_int8_layer_t *layer = &model->layers[index];
        size_t required = (size_t)layer->output_h * layer->output_w * layer->output_c;
        int8_t *next = workspace + (index & 1U) * model->slot_size;
        uint8_t *scratch = NULL;
        size_t scratch_size = 0U;
        gs_ai_status_t status;
        if (layer->input_h > 1024U || layer->input_w > 1024U || layer->input_c > 1024U ||
            layer->output_h > 1024U || layer->output_w > 1024U || layer->output_c > 1024U ||
            layer->kernel_h > 96U || layer->kernel_w > 96U || layer->stride_h > 96U || layer->stride_w > 96U ||
            layer->input_zero < -128 || layer->input_zero > 127 || layer->output_zero < -128 || layer->output_zero > 127 ||
            (size_t)layer->input_h * layer->input_w * layer->input_c != previous_size ||
            required == 0U || required > model->slot_size || layer->kernel_h == 0U || layer->kernel_w == 0U ||
            layer->stride_h == 0U || layer->stride_w == 0U ||
            layer->activation_min < -128 || layer->activation_max > 127 ||
            layer->activation_min > layer->activation_max ||
            layer->operation < GS_INT8_CONV || layer->operation > GS_INT8_AVERAGE ||
            (layer->operation != GS_INT8_CONV && layer->input_c != layer->output_c)) {
            return GS_AI_BACKEND_FAILURE;
        }
        /* All tensor sizes have now been validated. Avoid required+3 overflow:
           subtract remaining space first, then consume at most three pad bytes. */
        size_t remaining = model->slot_size - required;
        size_t pad = ((uintptr_t)0 - (uintptr_t)(next + required)) & 3U;
        if (remaining >= pad && remaining - pad >= 7680U) {
            scratch = (uint8_t *)(next + required + pad);
            scratch_size = remaining - pad;
        }
        status = gs_int8_layer_run(layer, previous, next, progress, context, index, scratch, scratch_size);
        if (status != GS_AI_OK) { return status; }
        previous = next;
        previous_size = required;
    }
    if (previous_size != output_size) { return GS_AI_BACKEND_FAILURE; }
    memcpy(output, previous, output_size);
    return GS_AI_OK;
}

gs_ai_status_t gs_int8_execute(const gs_int8_model_t *model,
    const int8_t *input, size_t input_size, int8_t *output, size_t output_size,
    int8_t *workspace, size_t workspace_size)
{
    return gs_int8_execute_progress(model, input, input_size, output, output_size,
                                    workspace, workspace_size, NULL, NULL);
}

gs_ai_status_t gs_int8_backend_infer(void *context, const int8_t *input,
    size_t input_size, int8_t *output, size_t output_size)
{
    gs_int8_context_t *runtime = context;
    if (runtime == NULL || input_size != GS_AI_INPUT_SIZE || output_size != GS_AI_CLASS_COUNT) {
        return GS_AI_INVALID_ARGUMENT;
    }
    return gs_int8_execute(runtime->model, input, input_size, output, output_size,
                           runtime->workspace, runtime->workspace_size);
}
