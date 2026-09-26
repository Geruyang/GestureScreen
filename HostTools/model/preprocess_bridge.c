#include "gs_preprocess.h"
int check_frame(const unsigned char *raw,unsigned bytes,unsigned stride,int order,signed char *out) {gs_rgb565_frame_t f={raw,bytes,320,240,stride,(gs_rgb565_byte_order_t)order};return gs_preprocess_rgb565(&f,out,GS_AI_INPUT_SIZE,0,0);}
