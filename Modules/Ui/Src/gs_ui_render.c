/* 无堆分配的 RGB565 软件渲染器：全屏阅读器与局部刷新。 */
#include "gs_ui_render.h"

#include <ctype.h>
#include <limits.h>
#include <string.h>
#include "gs_ui_font_aa_subset.h"

typedef struct {
    uint16_t *pixels;
    uint16_t width;
    uint16_t height;
    size_t stride;
    const gs_ui_render_region_t *regions;
    size_t region_count;
} gs_canvas_t;

static const uint8_t gs_font_letters[26][5] = {
    {0x7e,0x11,0x11,0x11,0x7e}, {0x7f,0x49,0x49,0x49,0x36},
    {0x3e,0x41,0x41,0x41,0x22}, {0x7f,0x41,0x41,0x22,0x1c},
    {0x7f,0x49,0x49,0x49,0x41}, {0x7f,0x09,0x09,0x09,0x01},
    {0x3e,0x41,0x49,0x49,0x7a}, {0x7f,0x08,0x08,0x08,0x7f},
    {0x00,0x41,0x7f,0x41,0x00}, {0x20,0x40,0x41,0x3f,0x01},
    {0x7f,0x08,0x14,0x22,0x41}, {0x7f,0x40,0x40,0x40,0x40},
    {0x7f,0x02,0x0c,0x02,0x7f}, {0x7f,0x04,0x08,0x10,0x7f},
    {0x3e,0x41,0x41,0x41,0x3e}, {0x7f,0x09,0x09,0x09,0x06},
    {0x3e,0x41,0x51,0x21,0x5e}, {0x7f,0x09,0x19,0x29,0x46},
    {0x46,0x49,0x49,0x49,0x31}, {0x01,0x01,0x7f,0x01,0x01},
    {0x3f,0x40,0x40,0x40,0x3f}, {0x1f,0x20,0x40,0x20,0x1f},
    {0x3f,0x40,0x38,0x40,0x3f}, {0x63,0x14,0x08,0x14,0x63},
    {0x07,0x08,0x70,0x08,0x07}, {0x61,0x51,0x49,0x45,0x43}
};

static const uint8_t gs_font_digits[10][5] = {
    {0x3e,0x51,0x49,0x45,0x3e}, {0x00,0x42,0x7f,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46}, {0x21,0x41,0x45,0x4b,0x31},
    {0x18,0x14,0x12,0x7f,0x10}, {0x27,0x45,0x45,0x45,0x39},
    {0x3c,0x4a,0x49,0x49,0x30}, {0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36}, {0x06,0x49,0x49,0x29,0x1e}
};

static const uint8_t gs_font_space[5] = {0U,0U,0U,0U,0U};
static const uint8_t gs_font_dash[5] = {0x08,0x08,0x08,0x08,0x08};
static const uint8_t gs_font_slash[5] = {0x20,0x10,0x08,0x04,0x02};
static const uint8_t gs_font_colon[5] = {0U,0x36,0x36,0U,0U};
static const uint8_t gs_font_dot[5] = {0U,0x60,0x60,0U,0U};
static const uint8_t gs_font_unknown[5] = {0x02,0x01,0x51,0x09,0x06};
static const uint8_t gs_font_percent[5] = {0x63,0x13,0x08,0x64,0x63};

static const uint8_t *gs_glyph(char value)
{
    unsigned char ch = (unsigned char)value;
    ch = (unsigned char)toupper((int)ch);
    if (ch >= (unsigned char)'A' && ch <= (unsigned char)'Z') {
        return gs_font_letters[ch - (unsigned char)'A'];
    }
    if (ch >= (unsigned char)'0' && ch <= (unsigned char)'9') {
        return gs_font_digits[ch - (unsigned char)'0'];
    }
    switch (ch) {
    case ' ': return gs_font_space;
    case '-': return gs_font_dash;
    case '/': return gs_font_slash;
    case ':': return gs_font_colon;
    case '.': return gs_font_dot;
    case '%': return gs_font_percent;
    default: return gs_font_unknown;
    }
}

static void gs_fill(gs_canvas_t *canvas, uint16_t x, uint16_t y,
                    uint16_t width, uint16_t height, uint16_t color)
{
    size_t region_index;
    if (x >= canvas->width || y >= canvas->height) {
        return;
    }
    for (region_index = 0U; region_index < (canvas->region_count != 0U ?
         canvas->region_count : 1U); ++region_index) {
        uint32_t left = x, top = y;
        uint32_t right = (uint32_t)x + width;
        uint32_t bottom = (uint32_t)y + height;
        uint32_t row;
        if (canvas->region_count != 0U) {
            const gs_ui_render_region_t *region = &canvas->regions[region_index];
            uint32_t region_right = (uint32_t)region->x + region->width;
            uint32_t region_bottom = (uint32_t)region->y + region->height;
            if (left < region->x) { left = region->x; }
            if (top < region->y) { top = region->y; }
            if (right > region_right) { right = region_right; }
            if (bottom > region_bottom) { bottom = region_bottom; }
        }
        if (right > canvas->width) { right = canvas->width; }
        if (bottom > canvas->height) { bottom = canvas->height; }
        if (left >= right || top >= bottom) { continue; }
        for (row = top; row < bottom; ++row) {
            uint16_t *destination = canvas->pixels + (size_t)row * canvas->stride + left;
            uint32_t col;
            for (col = left; col < right; ++col) { *destination++ = color; }
        }
    }
}

static void gs_character(gs_canvas_t *canvas, uint16_t x, uint16_t y,
                         char value, uint8_t scale, uint16_t color)
{
    const uint8_t *glyph = gs_glyph(value);
    uint32_t column;
    for (column = 0U; column < 5U; ++column) {
        uint32_t row;
        for (row = 0U; row < 7U; ++row) {
            if ((glyph[column] & (1U << row)) != 0U) {
                gs_fill(canvas, (uint16_t)(x + column * scale),
                        (uint16_t)(y + row * scale), scale, scale, color);
            }
        }
    }
}

static void gs_text(gs_canvas_t *canvas, uint16_t x, uint16_t y,
                    const char *text, uint8_t scale, uint16_t color,
                    uint16_t max_width)
{
    uint16_t cursor = x;
    uint16_t advance = (uint16_t)(6U * scale);
    while (*text != '\0' && (uint32_t)cursor + 5U * scale <=
           (uint32_t)x + max_width) {
        gs_character(canvas, cursor, y, *text, scale, color);
        cursor = (uint16_t)(cursor + advance);
        ++text;
    }
}

static void gs_wrapped_text(gs_canvas_t *canvas, uint16_t x, uint16_t y,
                            const char *text, uint8_t scale, uint16_t color,
                            uint16_t max_width, uint8_t max_lines)
{
    char line[64];
    size_t line_length = 0U;
    size_t max_chars = max_width / (6U * scale);
    uint8_t line_number = 0U;
    if (max_chars >= sizeof(line)) {
        max_chars = sizeof(line) - 1U;
    }
    while (*text != '\0' && line_number < max_lines) {
        size_t word_length = 0U;
        while (text[word_length] != '\0' && text[word_length] != ' ') {
            ++word_length;
        }
        if (line_length != 0U && line_length + 1U + word_length > max_chars) {
            line[line_length] = '\0';
            gs_text(canvas, x, (uint16_t)(y + line_number * (9U * scale)),
                    line, scale, color, max_width);
            ++line_number;
            line_length = 0U;
            continue;
        }
        if (line_length != 0U && line_length < max_chars) {
            line[line_length++] = ' ';
        }
        while (word_length != 0U && line_length < max_chars) {
            line[line_length++] = *text++;
            --word_length;
        }
        while (*text == ' ') {
            ++text;
        }
        if (line_length == max_chars || *text == '\0') {
            line[line_length] = '\0';
            gs_text(canvas, x, (uint16_t)(y + line_number * (9U * scale)),
                    line, scale, color, max_width);
            ++line_number;
            line_length = 0U;
        }
    }
}

static void gs_number(char *output, uint16_t value)
{
    char reverse[5];
    uint32_t count = 0U;
    do {
        reverse[count++] = (char)('0' + value % 10U);
        value = (uint16_t)(value / 10U);
    } while (value != 0U && count < sizeof(reverse));
    while (count != 0U) {
        *output++ = reverse[--count];
    }
    *output = '\0';
}

gs_ui_render_theme_t gs_ui_render_default_theme(void)
{
    gs_ui_render_theme_t theme;
    theme.background = 0xF79DU; /* warm paper */
    theme.surface = 0xFFDFU;
    theme.primary = 0x2C8CU; /* deep jade */
    theme.secondary = 0xB3C9U; /* copper */
    theme.text = 0x2946U;
    theme.muted_text = 0x7B8EU;
    return theme;
}

gs_ui_render_status_t gs_ui_render_rgb565(
    const gs_ui_t *ui, uint16_t *pixels, size_t pixel_capacity,
    uint16_t width, uint16_t height, size_t stride_pixels,
    const gs_ui_render_theme_t *selected_theme)
{
    gs_ui_render_theme_t default_theme = gs_ui_render_default_theme();
    const gs_ui_render_theme_t *theme = selected_theme != NULL ?
                                         selected_theme : &default_theme;
    gs_canvas_t canvas;
    uint8_t title_scale;
    uint8_t body_scale;
    uint16_t margin;
    uint16_t content_top;
    size_t required_pixels;
    const gs_ui_collection_t *collection;
    if (ui == NULL || pixels == NULL || width < GS_UI_RENDER_MIN_WIDTH ||
        height < GS_UI_RENDER_MIN_HEIGHT || stride_pixels < width ||
        ((uintptr_t)pixels & 1U) != 0U) {
        return GS_UI_RENDER_INVALID_ARGUMENT;
    }
    if (stride_pixels > (SIZE_MAX - width) / (height - 1U)) {
        return GS_UI_RENDER_INVALID_ARGUMENT;
    }
    required_pixels = stride_pixels * (height - 1U) + width;
    if (pixel_capacity < required_pixels) {
        return GS_UI_RENDER_BUFFER_TOO_SMALL;
    }
    if (!ui->initialized || (ui->collection_count != 0U &&
        (ui->collections == NULL || ui->selected >= ui->collection_count))) {
        return GS_UI_RENDER_INVALID_STATE;
    }
    canvas.pixels = pixels;
    canvas.width = width;
    canvas.height = height;
    canvas.stride = stride_pixels;
    canvas.regions = NULL;
    canvas.region_count = 0U;
    title_scale = (uint8_t)(width >= 640U ? 3U : 2U);
    body_scale = (uint8_t)(width >= 640U ? 2U : 1U);
    margin = (uint16_t)(width / 20U);
    content_top = (uint16_t)(height / 5U);

    gs_fill(&canvas, 0U, 0U, width, height, theme->background);
    gs_fill(&canvas, 0U, 0U, width, (uint16_t)(height / 8U), theme->surface);
    gs_fill(&canvas, 0U, (uint16_t)(height / 8U), width,
            (uint16_t)(height / 90U + 2U), theme->primary);
    gs_text(&canvas, margin, (uint16_t)(height / 24U), "GESTURE SCREEN",
            title_scale, theme->text, (uint16_t)(width - 2U * margin));

    if (ui->collection_count == 0U) {
        gs_text(&canvas, margin, content_top, "NO CONTENT INSTALLED",
                body_scale, theme->muted_text, (uint16_t)(width - 2U * margin));
    } else if (ui->mode == GS_UI_DIRECTORY) {
        uint16_t index;
        uint16_t row_height = (uint16_t)((height - content_top - height / 7U) /
                                         ui->collection_count);
        gs_text(&canvas, margin, (uint16_t)(content_top - 9U * body_scale),
                "COLLECTIONS", body_scale, theme->muted_text,
                (uint16_t)(width - 2U * margin));
        for (index = 0U; index < ui->collection_count; ++index) {
            uint16_t row_y = (uint16_t)(content_top + index * row_height);
            char pages[6];
            gs_number(pages, ui->collections[index].page_count);
            if (index == ui->selected) {
                gs_fill(&canvas, margin, (uint16_t)(row_y - 4U),
                        (uint16_t)(width - 2U * margin),
                        (uint16_t)(row_height - 6U), theme->primary);
            }
            gs_text(&canvas, (uint16_t)(margin + 12U), row_y,
                    ui->collections[index].title, body_scale, theme->text,
                    (uint16_t)(width * 3U / 5U));
            gs_text(&canvas, (uint16_t)(width * 4U / 5U), row_y, pages,
                    body_scale, theme->text, (uint16_t)(width / 10U));
        }
    } else if (ui->mode == GS_UI_READER) {
        char page_number[6];
        char page_count[6];
        uint16_t progress_width;
        collection = &ui->collections[ui->selected];
        if (ui->page >= collection->page_count) {
            return GS_UI_RENDER_INVALID_STATE;
        }
        gs_text(&canvas, margin, (uint16_t)(content_top - 9U * body_scale),
                collection->title, body_scale, theme->muted_text,
                (uint16_t)(width - 2U * margin));
        if (collection->pages != NULL) {
            const gs_ui_page_t *page = &collection->pages[ui->page];
            gs_text(&canvas, margin, content_top, page->title, title_scale,
                    theme->text, (uint16_t)(width - 2U * margin));
            gs_wrapped_text(&canvas, margin,
                            (uint16_t)(content_top + 12U * title_scale),
                            page->body, body_scale, theme->text,
                            (uint16_t)(width - 2U * margin), 4U);
        } else {
            gs_text(&canvas, margin, content_top, "CONTENT PAGE", title_scale,
                    theme->text, (uint16_t)(width - 2U * margin));
        }
        gs_number(page_number, (uint16_t)(ui->page + 1U));
        gs_number(page_count, collection->page_count);
        gs_text(&canvas, margin, (uint16_t)(height - height / 6U), "PAGE",
                body_scale, theme->muted_text, (uint16_t)(width / 8U));
        gs_text(&canvas, (uint16_t)(margin + 36U * body_scale),
                (uint16_t)(height - height / 6U), page_number, body_scale,
                theme->text, (uint16_t)(width / 12U));
        gs_text(&canvas, (uint16_t)(margin + 52U * body_scale),
                (uint16_t)(height - height / 6U), "/", body_scale,
                theme->muted_text, (uint16_t)(width / 20U));
        gs_text(&canvas, (uint16_t)(margin + 62U * body_scale),
                (uint16_t)(height - height / 6U), page_count, body_scale,
                theme->text, (uint16_t)(width / 12U));
        gs_text(&canvas, (uint16_t)(width * 3U / 4U),
                (uint16_t)(height - height / 6U),
                ui->playing ? "PLAYING" : "PAUSED", body_scale,
                ui->playing ? theme->secondary : theme->muted_text,
                (uint16_t)(width / 5U));
        progress_width = (uint16_t)(((uint32_t)(width - 2U * margin) *
                          (ui->page + 1U)) / collection->page_count);
        gs_fill(&canvas, margin, (uint16_t)(height - height / 11U),
                (uint16_t)(width - 2U * margin), 5U, theme->surface);
        gs_fill(&canvas, margin, (uint16_t)(height - height / 11U),
                progress_width, 5U, theme->secondary);
    } else {
        return GS_UI_RENDER_INVALID_STATE;
    }

    gs_text(&canvas, margin, (uint16_t)(height - height / 20U),
            "LEFT  RIGHT  FIST  PALM  V SIGN", body_scale,
            theme->muted_text, (uint16_t)(width - 2U * margin));
    return GS_UI_RENDER_OK;
}

gs_ui_render_status_t gs_ui_render_preview_rgb565(
    uint16_t *pixels, size_t pixel_capacity, uint16_t width, uint16_t height,
    size_t stride_pixels, const gs_preview_frame_t *preview)
{
    gs_canvas_t canvas;
    uint16_t x;
    uint16_t y;
    uint8_t scale;
    uint8_t fixed_display_fast_path;
    size_t required_pixels;
    uint32_t row;
    if (pixels == NULL || preview == NULL || preview->pixels == NULL ||
        width < GS_UI_RENDER_MIN_WIDTH || height < GS_UI_RENDER_MIN_HEIGHT ||
        stride_pixels < width || preview->width != GS_PREVIEW_WIDTH ||
        preview->height != GS_PREVIEW_HEIGHT ||
        preview->bytes != GS_PREVIEW_BYTES) {
        return GS_UI_RENDER_INVALID_ARGUMENT;
    }
    if (stride_pixels > (SIZE_MAX - width) / (height - 1U)) {
        return GS_UI_RENDER_INVALID_ARGUMENT;
    }
    required_pixels = stride_pixels * (height - 1U) + width;
    if (pixel_capacity < required_pixels) {
        return GS_UI_RENDER_BUFFER_TOO_SMALL;
    }
    canvas.pixels = pixels;
    canvas.width = width;
    canvas.height = height;
    canvas.stride = stride_pixels;
    canvas.regions = NULL;
    canvas.region_count = 0U;
    scale = (uint8_t)(width >= 800U && height >= 480U ? 3U : 1U);
    x = (uint16_t)(scale == 3U ? 48U : width - width / 20U - GS_PREVIEW_WIDTH);
    y = (uint16_t)(scale == 3U ? 112U : height / 5U);
    fixed_display_fast_path = (uint8_t)(
        width == 800U && height == 480U && stride_pixels == 800U &&
        ((uintptr_t)pixels & 3U) == 0U);
    if (fixed_display_fast_path != 0U) {
        /* The opaque 288x288 preview replaces every interior pixel. Paint only
           the four visible 3px edges instead of first filling all 294x294. */
        gs_fill(&canvas, (uint16_t)(x - 3U), (uint16_t)(y - 3U), 294U, 3U, 0xFFFFU);
        gs_fill(&canvas, (uint16_t)(x - 3U), (uint16_t)(y + 288U), 294U, 3U, 0xFFFFU);
        gs_fill(&canvas, (uint16_t)(x - 3U), y, 3U, 288U, 0xFFFFU);
        gs_fill(&canvas, (uint16_t)(x + 288U), y, 3U, 288U, 0xFFFFU);
    } else {
        gs_fill(&canvas, (uint16_t)(x - 3U), (uint16_t)(y - 3U),
                (uint16_t)(GS_PREVIEW_WIDTH * scale + 6U),
                (uint16_t)(GS_PREVIEW_HEIGHT * scale + 6U), 0xFFFFU);
    }
    /* Fixed 800x480 preview is fully inside the canvas. Paint each enlarged
       row once and copy its two identical rows, avoiding 9216 clipped 3x3 fills.
       Nonstandard/unaligned canvases retain the original clipping path. */
    if (scale == 3U && ((uintptr_t)pixels & 3U) == 0U && (stride_pixels & 1U) == 0U &&
        (uint32_t)x + GS_PREVIEW_WIDTH * 3U <= width &&
        (uint32_t)y + GS_PREVIEW_HEIGHT * 3U <= height) {
        for (row = 0U; row < GS_PREVIEW_HEIGHT; ++row) {
            uint16_t *out = canvas.pixels + ((size_t)y + row * 3U) * canvas.stride + x;
            uint32_t column;
            for (column = 0U; column < GS_PREVIEW_WIDTH; ++column) {
                uint8_t gray = preview->pixels[row * GS_PREVIEW_WIDTH + column];
                uint16_t color = (uint16_t)(((uint16_t)(gray >> 3U) << 11U) |
                                  ((uint16_t)(gray >> 2U) << 5U) | (uint16_t)(gray >> 3U));
                out[column * 3U] = color; out[column * 3U + 1U] = color; out[column * 3U + 2U] = color;
            }
            memcpy(out + canvas.stride, out, GS_PREVIEW_WIDTH * 3U * sizeof(*out));
            memcpy(out + canvas.stride * 2U, out, GS_PREVIEW_WIDTH * 3U * sizeof(*out));
        }
    } else for (row = 0U; row < GS_PREVIEW_HEIGHT; ++row) {
        uint32_t column;
        for (column = 0U; column < GS_PREVIEW_WIDTH; ++column) {
            uint8_t gray = preview->pixels[row * GS_PREVIEW_WIDTH + column];
            uint16_t color = (uint16_t)(((uint16_t)(gray >> 3U) << 11U) |
                              ((uint16_t)(gray >> 2U) << 5U) |
                              (uint16_t)(gray >> 3U));
            gs_fill(&canvas, (uint16_t)(x + column * scale),
                    (uint16_t)(y + row * scale), scale, scale, color);
        }
    }
    if (scale == 3U) {
        /* Thin corner guides locate the input ROI without hiding its center. */
        uint16_t end = (uint16_t)(x + 288U - 2U), bottom = (uint16_t)(y + 288U - 2U);
        gs_fill(&canvas, x, y, 22U, 2U, 0x07FFU); gs_fill(&canvas, x, y, 2U, 22U, 0x07FFU);
        gs_fill(&canvas, (uint16_t)(end - 20U), y, 22U, 2U, 0x07FFU); gs_fill(&canvas, end, y, 2U, 22U, 0x07FFU);
        gs_fill(&canvas, x, bottom, 22U, 2U, 0x07FFU); gs_fill(&canvas, x, (uint16_t)(bottom - 20U), 2U, 22U, 0x07FFU);
        gs_fill(&canvas, (uint16_t)(end - 20U), bottom, 22U, 2U, 0x07FFU); gs_fill(&canvas, end, (uint16_t)(bottom - 20U), 2U, 22U, 0x07FFU);
    }
    return GS_UI_RENDER_OK;
}

static uint32_t gs_codepoint(const char **text)
{
    const unsigned char *p = (const unsigned char *)*text;
    uint32_t value = *p++;
    if ((value & 0xE0U) == 0xC0U && p[0] != 0U && (p[0] & 0xC0U) == 0x80U) {
        value = ((value & 31U) << 6U) | (p[0] & 63U); p += 1;
    } else if ((value & 0xF0U) == 0xE0U && p[0] != 0U && p[1] != 0U &&
        (p[0] & 0xC0U) == 0x80U && (p[1] & 0xC0U) == 0x80U) {
        value = ((value & 15U) << 12U) | ((p[0] & 63U) << 6U) | (p[1] & 63U); p += 2;
    }
    *text = (const char *)p; return value;
}
void gs_ui_hint_update(gs_ui_hint_cache_t *cache,
    const gs_static_result_t *snapshot, uint32_t now_ms,
    uint32_t control_enabled, gs_ui_live_status_t *live)
{
    if (cache == NULL || snapshot == NULL || live == NULL) { return; }
    live->hint_valid = 0U;
    live->hint_class = GS_STATIC_UNKNOWN;
    if (!control_enabled) { cache->valid = 0U; return; }
    if (snapshot->status == GS_STATIC_CAMERA_ERROR ||
        snapshot->status == GS_STATIC_INFERENCE_ERROR ||
        snapshot->status == GS_STATIC_TIMEOUT) {
        cache->valid = 0U;
    } else if (snapshot->frame_id != 0U && snapshot->status != GS_STATIC_RUNNING &&
        (!cache->seen_terminal || snapshot->frame_id != cache->last_terminal_frame_id)) {
        cache->seen_terminal = 1U;
        cache->last_terminal_frame_id = snapshot->frame_id;
        cache->valid = snapshot->status == GS_STATIC_IDENTIFIED &&
            snapshot->class_index <= GS_STATIC_V_SIGN &&
            snapshot->confidence_permille >= 900U &&
            snapshot->margin_permille >= 200U &&
            now_ms - snapshot->capture_ms <= GS_UI_HINT_TTL_MS;
        if (cache->valid) { cache->qualified = *snapshot; }
    }
    if (cache->valid && now_ms - cache->qualified.capture_ms > GS_UI_HINT_TTL_MS) {
        cache->valid = 0U;
    }
    if (cache->valid) {
        live->hint_valid = 1U;
        live->hint_class = cache->qualified.class_index;
    }
}
static bool gs_line_end_punctuation(uint32_t code)
{
    return code == 0x3001U || code == 0x3002U || code == 0xFF0CU ||
        code == 0xFF1BU || code == 0xFF1AU || code == 0xFF1FU ||
        code == 0xFF01U || code == 0x201DU;
}
static const char *gs_hint_label(const gs_ui_t *ui, uint32_t cls)
{
    gs_ui_action_t action;
    switch (cls) {
    case GS_STATIC_POINT_LEFT: action = GS_UI_NEXT; break;
    case GS_STATIC_POINT_RIGHT: action = GS_UI_PREVIOUS; break;
    case GS_STATIC_FIST: action = GS_UI_HOME; break;
    case GS_STATIC_PALM: action = GS_UI_UP; break;
    case GS_STATIC_V_SIGN: action = GS_UI_ENTER; break;
    default: return NULL;
    }
    if (!gs_ui_action_available(ui, action)) {
        switch (cls) {
        case GS_STATIC_POINT_LEFT:
            return ui->mode == GS_UI_READER ? "识别 向左 · 已是末页" :
                ui->mode == GS_UI_CATALOG ? "识别 向左 · 已是末篇" : "识别 向左 · 已是末本";
        case GS_STATIC_POINT_RIGHT:
            return ui->mode == GS_UI_READER ? "识别 向右 · 已是首页" :
                ui->mode == GS_UI_CATALOG ? "识别 向右 · 已是首篇" : "识别 向右 · 已是首本";
        case GS_STATIC_FIST: return "识别 握拳 · 当前书架";
        case GS_STATIC_PALM: return "识别 张掌 · 当前书架";
        case GS_STATIC_V_SIGN: return "识别 V形 · 当前正文";
        default: return NULL;
        }
    }
    switch (cls) {
    case GS_STATIC_POINT_LEFT:
        return ui->mode == GS_UI_READER ? "识别 向左 · 下一页" :
            ui->mode == GS_UI_CATALOG ? "识别 向左 · 下一篇" : "识别 向左 · 下一本";
    case GS_STATIC_POINT_RIGHT:
        return ui->mode == GS_UI_READER ? "识别 向右 · 上一页" :
            ui->mode == GS_UI_CATALOG ? "识别 向右 · 上一篇" : "识别 向右 · 上一本";
    case GS_STATIC_FIST: return "识别 握拳 · 回书架";
    case GS_STATIC_PALM: return ui->mode == GS_UI_READER ?
        "识别 张掌 · 回目录" : "识别 张掌 · 返回";
    case GS_STATIC_V_SIGN: return ui->mode == GS_UI_DIRECTORY ?
        "识别 V形 · 打开" : "识别 V形 · 阅读";
    default: return NULL;
    }
}
static const gs_aa_glyph_24_t *gs_find24(uint32_t code)
{
    size_t lo = 0U, hi = sizeof(gs_font24) / sizeof(gs_font24[0]);
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2U;
        if (gs_font24[mid].code < code) { lo = mid + 1U; }
        else { hi = mid; }
    }
    return lo < sizeof(gs_font24) / sizeof(gs_font24[0]) && gs_font24[lo].code == code ? &gs_font24[lo] : NULL;
}
static const gs_aa_glyph_32_t *gs_find32(uint32_t code)
{
    size_t lo = 0U, hi = sizeof(gs_font32) / sizeof(gs_font32[0]);
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2U;
        if (gs_font32[mid].code < code) { lo = mid + 1U; }
        else { hi = mid; }
    }
    return lo < sizeof(gs_font32) / sizeof(gs_font32[0]) && gs_font32[lo].code == code ? &gs_font32[lo] : NULL;
}
static bool gs_visible_pixel(const gs_canvas_t *canvas, uint32_t x, uint32_t y)
{
    size_t i;
    if (x >= canvas->width || y >= canvas->height) { return false; }
    if (canvas->region_count == 0U) { return true; }
    for (i = 0U; i < canvas->region_count; ++i) {
        const gs_ui_render_region_t *r = &canvas->regions[i];
        if (x >= r->x && x < (uint32_t)r->x + r->width &&
            y >= r->y && y < (uint32_t)r->y + r->height) { return true; }
    }
    return false;
}
static void gs_aa_glyph(gs_canvas_t *canvas, uint16_t x, uint16_t y,
    const uint8_t *bitmap, uint32_t width, uint32_t height, uint16_t color)
{
    uint32_t row, col;
    uint32_t sr = (color >> 11U) & 31U, sg = (color >> 5U) & 63U, sb = color & 31U;
    for (row = 0U; row < height; ++row) for (col = 0U; col < width; ++col) {
        uint32_t index = row * width + col;
        uint32_t alpha = (index & 1U) ? (bitmap[index >> 1U] & 15U) : (bitmap[index >> 1U] >> 4U);
        uint32_t px = (uint32_t)x + col, py = (uint32_t)y + row;
        if (alpha == 0U || !gs_visible_pixel(canvas, px, py)) { continue; }
        uint16_t *dest = canvas->pixels + (size_t)py * canvas->stride + px;
        if (alpha == 15U) { *dest = color; }
        else {
            uint32_t old = *dest;
            uint32_t r = ((old >> 11U & 31U) * (15U - alpha) + sr * alpha + 7U) / 15U;
            uint32_t g = ((old >> 5U & 63U) * (15U - alpha) + sg * alpha + 7U) / 15U;
            uint32_t b = ((old & 31U) * (15U - alpha) + sb * alpha + 7U) / 15U;
            *dest = (uint16_t)((r << 11U) | (g << 5U) | b);
        }
    }
}
/* Native-size anti-aliased CJK; returns a UTF-8 suffix for caller-managed wrapping. */
static const char *gs_label(gs_canvas_t *canvas, uint16_t x, uint16_t y,
    const char *text, uint8_t scale, uint16_t color, uint16_t max_width)
{
    uint32_t cursor = x;
    if (text == NULL) { return ""; }
    while (*text != '\0') {
        /* Content JSON preserves explicit paragraphs as LF. Treat CR/LF as
         * a forced line boundary instead of handing the control byte to the
         * Latin glyph renderer (which displayed it as '?'). The caller owns
         * the next-line y coordinate and line budget. */
        if (*text == '\n') { return text + 1; }
        if (*text == '\r') {
            ++text;
            return *text == '\n' ? text + 1 : text;
        }
        const char *start = text;
        uint32_t code = gs_codepoint(&text);
        const gs_aa_glyph_24_t *small = gs_find24(code);
        const gs_aa_glyph_32_t *large = scale >= 2U ? gs_find32(code) : NULL;
        uint32_t advance = large != NULL ? large->advance : small != NULL ? small->advance : 24U;
        if (cursor + advance > (uint32_t)x + max_width) { return start; }
        if (*text != '\0' && cursor > x) {
            const char *after_next = text;
            uint32_t next_code = gs_codepoint(&after_next);
            const gs_aa_glyph_24_t *next_small = gs_find24(next_code);
            const gs_aa_glyph_32_t *next_large = scale >= 2U ? gs_find32(next_code) : NULL;
            uint32_t next_advance = next_large != NULL ? next_large->advance :
                next_small != NULL ? next_small->advance : 24U;
            if (gs_line_end_punctuation(next_code) &&
                cursor + advance + next_advance > (uint32_t)x + max_width) {
                return start;
            }
        }
        if (large != NULL) { gs_aa_glyph(canvas, (uint16_t)cursor, y, large->pixels, 32U, 38U, color); }
        else if (small != NULL) { gs_aa_glyph(canvas, (uint16_t)cursor, y, small->pixels, 24U, 28U, color); }
        cursor += advance;
    }
    return text;
}
static gs_ui_render_status_t gs_ui_render_dashboard_impl(const gs_ui_t *ui,
    const gs_ui_live_status_t *live, uint16_t *pixels, size_t capacity,
    uint16_t width, uint16_t height, size_t stride, const gs_ui_render_theme_t *selected,
    const gs_ui_render_region_t *regions, size_t region_count)
{
    gs_ui_render_theme_t fallback = gs_ui_render_default_theme();
    const gs_ui_render_theme_t *theme = selected != NULL ? selected : &fallback;
    gs_canvas_t canvas;
    uint16_t i;
    const char *status = "等待手势";
    if (ui == NULL || pixels == NULL || width < 800U || height < 480U ||
        stride < width || (region_count != 0U && regions == NULL) ||
        stride > (SIZE_MAX - width) / (height - 1U)) {
        return GS_UI_RENDER_INVALID_ARGUMENT;
    }
    if (capacity < stride * (height - 1U) + width) {
        return GS_UI_RENDER_BUFFER_TOO_SMALL;
    }
    if (!ui->initialized || ui->collection_count == 0U || ui->collections == NULL ||
        ui->selected >= ui->collection_count || ui->mode > GS_UI_READER ||
        (ui->mode != GS_UI_DIRECTORY && ui->collections[ui->selected].pages == NULL) ||
        (ui->mode == GS_UI_CATALOG && ui->chapter >= ui->collections[ui->selected].page_count) ||
        (ui->mode == GS_UI_READER && ui->page >= ui->collections[ui->selected].page_count)) {
        return GS_UI_RENDER_INVALID_STATE;
    }
    canvas.pixels = pixels; canvas.width = width; canvas.height = height;
    canvas.stride = stride; canvas.regions = regions; canvas.region_count = region_count;
    if (live != NULL) {
        if (!live->control_enabled || live->recognition.status == GS_STATIC_CAMERA_ERROR ||
            live->recognition.status == GS_STATIC_INFERENCE_ERROR ||
            live->recognition.status == GS_STATIC_TIMEOUT) {
            status = "手势暂不可用";
        } else if (live->gesture_state == GS_GESTURE_READY) {
            status = "可以操作";
        } else if (live->gesture_state == GS_GESTURE_CANDIDATE) {
            status = "保持手势";
        } else {
            status = "等待非目标手势";
        }
    }
    gs_fill(&canvas, 0U, 0U, width, height, theme->background);
    gs_fill(&canvas, 0U, 0U, width, 68U, theme->surface);
    gs_fill(&canvas, 0U, 67U, width, 1U, 0xDEBAU);
    gs_fill(&canvas, 32U, 18U, 4U, 32U, theme->secondary);
    gs_label(&canvas, 48U, 17U, "掌上书房", 2U, theme->primary, 240U);
    const char *hint = live != NULL && live->hint_valid ?
        gs_hint_label(ui, live->hint_class) : NULL;
    if (hint != NULL) {
        gs_fill(&canvas, 495U, 12U, 283U, 44U, 0xE73AU);
        gs_fill(&canvas, 495U, 12U, 3U, 44U, theme->primary);
        gs_label(&canvas, 508U, 20U, hint, 1U, theme->primary, 260U);
    } else {
        gs_label(&canvas, 638U, 23U, "静心阅读", 1U, theme->muted_text, 138U);
    }

    if (ui->mode == GS_UI_DIRECTORY) {
        uint16_t first = ui->selected >= 3U ? (uint16_t)(ui->selected - 2U) : 0U;
        gs_label(&canvas, 40U, 87U, "我的书架", 2U, theme->text, 240U);
        gs_label(&canvas, 42U, 130U, "在古文里，读一段安静时光", 1U, theme->muted_text, 550U);
        for (i = first; i < ui->collection_count && i < first + 3U; ++i) {
            uint16_t x = (uint16_t)(40U + (i - first) * 247U);
            const gs_ui_collection_t *book = &ui->collections[i];
            bool selected_book = i == ui->selected;
            uint16_t cover = i % 3U == 0U ? 0x2C8CU : i % 3U == 1U ? 0x8BCAU : 0x5B31U;
            gs_fill(&canvas, x + 5U, 181U, 222U, 239U, 0xDEBAU);
            gs_fill(&canvas, x, 176U, 222U, 239U, cover);
            gs_fill(&canvas, x + 14U, 176U, 3U, 239U, theme->secondary);
            gs_fill(&canvas, x + 30U, 201U, 160U, 1U, 0xB5D5U);
            gs_label(&canvas, x + 31U, 223U, book->title, 2U, theme->surface, 185U);
            gs_label(&canvas, x + 32U, 300U, book->author != NULL ? book->author : "古文精选",
                1U, 0xEF5DU, 172U);
            gs_fill(&canvas, x + 31U, 368U, 158U, 1U, 0xB5D5U);
            if (selected_book) {
                gs_fill(&canvas, x - 6U, 170U, 234U, 6U, theme->surface);
                gs_fill(&canvas, x - 6U, 170U, 6U, 251U, theme->surface);
                gs_fill(&canvas, x + 222U, 170U, 6U, 251U, theme->surface);
                gs_fill(&canvas, x - 6U, 415U, 234U, 6U, theme->surface);
                gs_fill(&canvas, x - 3U, 173U, 228U, 3U, theme->secondary);
                gs_fill(&canvas, x - 3U, 173U, 3U, 245U, theme->secondary);
                gs_fill(&canvas, x + 222U, 173U, 3U, 245U, theme->secondary);
                gs_fill(&canvas, x - 3U, 415U, 228U, 3U, theme->secondary);
                gs_fill(&canvas, x + 27U, 375U, 168U, 34U, theme->surface);
                gs_label(&canvas, x + 62U, 379U, "已选中", 1U, theme->primary, 100U);
            }
        }
    } else if (ui->mode == GS_UI_CATALOG) {
        const gs_ui_collection_t *book = &ui->collections[ui->selected];
        uint16_t first = ui->chapter >= 5U ? (uint16_t)(ui->chapter - 4U) : 0U;
        gs_label(&canvas, 40U, 88U, "篇目目录", 2U, theme->text, 250U);
        gs_fill(&canvas, 40U, 146U, 209U, 265U, theme->primary);
        gs_fill(&canvas, 54U, 146U, 3U, 265U, theme->secondary);
        gs_label(&canvas, 70U, 203U, book->title, 2U, theme->surface, 170U);
        gs_label(&canvas, 70U, 274U, book->author != NULL ? book->author : "古文精选",
            1U, 0xEF5DU, 168U);
        gs_fill(&canvas, 70U, 362U, 150U, 1U, 0xB5D5U);
        for (i = first; i < book->page_count && i < first + 5U; ++i) {
            uint16_t y = (uint16_t)(143U + (i - first) * 54U);
            const gs_ui_page_t *page = &book->pages[i];
            bool selected_page = i == ui->chapter;
            gs_fill(&canvas, 275U, y, 493U, 48U,
                selected_page ? theme->primary : theme->surface);
            if (selected_page) {
                gs_fill(&canvas, 275U, y, 6U, 48U, theme->secondary);
                gs_fill(&canvas, 281U, y, 487U, 2U, theme->secondary);
                gs_fill(&canvas, 281U, y + 46U, 487U, 2U, theme->secondary);
                gs_fill(&canvas, 289U, y + 20U, 8U, 8U, theme->secondary);
            }
            gs_label(&canvas, selected_page ? 307U : 294U, y + 9U,
                page->title, 1U, selected_page ? theme->surface : theme->text,
                selected_page ? 91U : 104U);
            gs_label(&canvas, 411U, y + 9U, page->body, 1U,
                selected_page ? theme->surface : theme->muted_text, 345U);
        }
    } else {
        const gs_ui_collection_t *book = &ui->collections[ui->selected];
        const gs_ui_page_t *page = &book->pages[ui->page];
        const char *remaining = page->body;
        char current[6], total[6];
        gs_label(&canvas, 40U, 85U, book->title, 1U, theme->muted_text, 350U);
        gs_label(&canvas, 622U, 85U, book->author != NULL ? book->author : "古文精选",
            1U, theme->muted_text, 145U);
        gs_label(&canvas, 40U, 115U, page->title, 2U, theme->text, 300U);
        gs_fill(&canvas, 24U, 159U, 752U, 268U, theme->surface);
        gs_fill(&canvas, 40U, 177U, 3U, 216U, theme->secondary);
        for (i = 0U; i < 6U && remaining != NULL && *remaining != '\0'; ++i) {
            remaining = gs_label(&canvas, 57U, (uint16_t)(178U + i * 37U),
                remaining, 1U, theme->text, 690U);
        }
        gs_number(current, (uint16_t)(ui->page + 1U));
        gs_number(total, book->page_count);
        gs_label(&canvas, 659U, 391U, current, 1U, theme->muted_text, 35U);
        gs_label(&canvas, 690U, 391U, "/", 1U, theme->muted_text, 18U);
        gs_label(&canvas, 714U, 391U, total, 1U, theme->muted_text, 35U);
        gs_fill(&canvas, 24U, 424U, 752U, 3U, 0xDEBAU);
        gs_fill(&canvas, 24U, 424U,
            (uint16_t)((752U * (ui->page + 1U)) / book->page_count), 3U, theme->secondary);
    }
    gs_fill(&canvas, 0U, 436U, width, 44U, theme->surface);
    if (ui->mode == GS_UI_DIRECTORY) {
        gs_label(&canvas, 40U, 446U, "向左下一本  向右上一本  V形打开", 1U, theme->muted_text, 570U);
    } else if (ui->mode == GS_UI_CATALOG) {
        gs_label(&canvas, 40U, 446U, "向左下一篇  向右上一篇  V形阅读  张掌返回", 1U, theme->muted_text, 580U);
    } else {
        gs_label(&canvas, 40U, 446U, "向左下一页  向右上一页  张掌目录  握拳首页", 1U, theme->muted_text, 580U);
    }
    gs_label(&canvas, 628U, 446U, status, 1U, theme->primary, 150U);
    return GS_UI_RENDER_OK;
}

gs_ui_render_status_t gs_ui_render_dashboard_rgb565(const gs_ui_t *ui,
    const gs_ui_live_status_t *live, uint16_t *pixels, size_t capacity,
    uint16_t width, uint16_t height, size_t stride, const gs_ui_render_theme_t *selected)
{
    return gs_ui_render_dashboard_impl(ui, live, pixels, capacity, width, height,
        stride, selected, NULL, 0U);
}

gs_ui_render_status_t gs_ui_render_dashboard_regions_rgb565(const gs_ui_t *ui,
    const gs_ui_live_status_t *live, uint16_t *pixels, size_t capacity,
    uint16_t width, uint16_t height, size_t stride, const gs_ui_render_theme_t *selected,
    const gs_ui_render_region_t *regions, size_t region_count)
{
    return gs_ui_render_dashboard_impl(ui, live, pixels, capacity, width, height,
        stride, selected, regions, region_count);
}
