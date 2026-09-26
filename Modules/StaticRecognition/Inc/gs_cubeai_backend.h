#ifndef GS_CUBEAI_BACKEND_H
#define GS_CUBEAI_BACKEND_H
#include "gs_ai_int8_backend.h"
/* Single Vision task owner. Progress is at complete original-layer boundaries,
 * unlike the reference executor's 64-element chunks. False aborts before the
 * next layer; no partial result is published. */
bool gs_cubeai_layer_done(size_t layer, uint32_t outputs);
gs_ai_status_t gs_cubeai_execute(const int8_t *input, size_t count, int8_t *output,
                               size_t output_count, float *output_scale,
                               int32_t *output_zero_point,
                               gs_int8_progress_fn progress, void *context);
gs_ai_status_t gs_cubeai_contract_status(void);
#endif
