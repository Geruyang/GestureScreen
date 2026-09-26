/* Compile the actual production packed-DSP path with portable DSP semantics.
   ARM builds use the existing SXTB16/SMLAD compiler intrinsics instead. */
#define GS_INT8_TEST_DSP 1
#define gs_int8_execute gs_packed_execute
#define gs_int8_execute_progress gs_packed_execute_progress
#define gs_int8_backend_infer gs_packed_backend_infer
#include "../Modules/Vision/Src/gs_ai_int8_backend.c"
int32_t gs_candidate_scale(int32_t value, int32_t multiplier, int8_t shift)
{ return gs_int8_scale(value, multiplier, shift); }
int32_t gs_candidate_dot4(const int8_t *a, const int8_t *b, int32_t sum)
{ return gs_int8_dot4(a, b, sum); }
int8_t gs_candidate_relu_finish(int32_t accumulator,int32_t multiplier,int8_t shift,int8_t maximum)
{
    gs_int8_layer_t layer = {0};
    layer.multipliers=&multiplier;layer.shifts=&shift;
    layer.output_zero=layer.activation_min=-128;layer.activation_max=maximum;
    return gs_int8_finish(accumulator,0U,&layer);
}
int8_t gs_candidate_negative_relu(int32_t accumulator,int32_t multiplier,int8_t shift)
{
    gs_int8_negative_quant_t q={multiplier,(uint32_t)(-(int32_t)shift),0U};
    q.half=UINT32_C(1)<<(q.exponent-1U);
    return gs_int8_negative_relu(accumulator,&q);
}
