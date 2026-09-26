/* Unmodified round8 production implementation, isolated from the candidate.
   Its original software divide and loop order remain an independent oracle. */
#define gs_int8_execute gs_round8_execute
#define gs_int8_execute_progress gs_round8_execute_progress
#define gs_int8_backend_infer gs_round8_backend_infer
#include "fixtures/int8_backend_round8.c"
int32_t gs_round8_scale(int32_t value, int32_t multiplier, int8_t shift)
{ return gs_int8_scale(value, multiplier, shift); }
