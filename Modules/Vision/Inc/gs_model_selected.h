#ifndef GS_MODEL_SELECTED_H
#define GS_MODEL_SELECTED_H
#include "gs_ai.h"

/* 旧式选择器保留不可用占位；六类生产网络通过静态 Cube.AI 路径安装。
 * 安装候选不自动放行业务，gs_ai_init仍检查validated_for_business。 */
const gs_ai_backend_t *gs_model_selected_backend(void);

#endif
