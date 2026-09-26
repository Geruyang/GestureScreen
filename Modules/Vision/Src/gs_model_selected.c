#include "gs_model_selected.h"

/* 旧式模型选择接口仅作不可用占位。生产六类模型由 Cube.AI 静态路径接入；
 * 五类参考权重不得在此作为 fallback。 */
const gs_ai_backend_t *gs_model_selected_backend(void)
{
    return NULL;
}
