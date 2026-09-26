#ifndef GS_VISION_PROFILE_H
#define GS_VISION_PROFILE_H
#include <stdint.h>
/* Optional scheduled-cycle diagnostic. No RTOS API from the switch hooks.
 * ISR/PendSV cycles belong to the task active between these trace points;
 * this is not exclusive instruction CPU time. No kernel/clock changes. */
#ifndef GS_VISION_CYCLE_PROFILE
#define GS_VISION_CYCLE_PROFILE 1
#endif
void gs_vision_profile_switched_in(void *task);
void gs_vision_profile_switched_out(void *task);
#endif
