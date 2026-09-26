#ifndef GS_CONTENT_H
#define GS_CONTENT_H
#include "gs_ui.h"
#include <stddef.h>
#define GS_CONTENT_MAX_IMAGES 16U
typedef struct {
    uint16_t collection, page, width, height;
    const uint8_t *rgb565_be;
    uint32_t bytes, crc32;
} gs_content_image_t;
typedef struct {
    const char *version;
    const gs_ui_collection_t *collections;
    uint16_t collection_count, image_count;
    const gs_content_image_t *images;
} gs_content_package_t;
typedef enum { GS_CONTENT_PENDING=0, GS_CONTENT_READY, GS_CONTENT_CORRUPT } gs_content_state_t;
typedef struct {
    const gs_content_package_t *package;
    uint32_t index, offset, crc;
    volatile uint32_t checked, errors;
    volatile uint32_t states[GS_CONTENT_MAX_IMAGES];
} gs_content_context_t;
/* Initialize before task creation. StorageTask is the sole step writer. GUI
 * reads only immutable resources whose atomic status has become READY. */
extern gs_content_context_t g_gs_content;
extern const gs_content_package_t g_gs_content_builtin_package;
bool gs_content_init(gs_content_context_t *context, const gs_content_package_t *package);
void gs_content_step(gs_content_context_t *context, uint32_t byte_budget);
const gs_content_image_t *gs_content_find_image(const gs_content_context_t *context,
                                               uint16_t collection, uint16_t page);
#endif
