#include "gs_content.h"
#include <string.h>
gs_content_context_t g_gs_content;
bool gs_content_init(gs_content_context_t *c,const gs_content_package_t *p)
{
    uint32_t i,j;
    if (!c) { return false; }
    memset(c,0,sizeof(*c));
    if (!p || !p->version || !p->collections || !p->collection_count || p->collection_count>8U ||
        p->image_count>GS_CONTENT_MAX_IMAGES || (p->image_count && !p->images)) { return false; }
    for (i=0;i<p->collection_count;++i) {
        if (!p->collections[i].title || !p->collections[i].pages || !p->collections[i].page_count || p->collections[i].page_count>32U) { return false; }
        for (j=0;j<p->collections[i].page_count;++j) {
            if (!p->collections[i].pages[j].title || !p->collections[i].pages[j].body) { return false; }
        }
    }
    c->package=p; c->crc=UINT32_MAX; return true;
}
static bool image_valid(const gs_content_package_t *p,const gs_content_image_t *im)
{
    return im->collection<p->collection_count && im->page<p->collections[im->collection].page_count &&
        im->rgb565_be && im->width && im->width<=320U && im->height && im->height<=180U &&
        im->bytes==(uint32_t)im->width*im->height*2U;
}
void gs_content_step(gs_content_context_t *c,uint32_t budget)
{
    static const uint32_t lut[16]={0,0x1db71064,0x3b6e20c8,0x26d930ac,0x76dc4190,0x6b6b51f4,0x4db26158,0x5005713c,
        0xedb88320,0xf00f9344,0xd6d6a3e8,0xcb61b38c,0x9b64c2b0,0x86d3d2d4,0xa00ae278,0xbdbdf21c};
    const gs_content_image_t *im;
    uint32_t n,crc;
    if (!c || !c->package || c->index>=c->package->image_count || !budget) { return; }
    if (budget>4096U) { budget=4096U; }
    im=&c->package->images[c->index];
    if (!image_valid(c->package,im)) {
        ++c->errors; ++c->checked; c->states[c->index++]=GS_CONTENT_CORRUPT;
        c->offset=0; c->crc=UINT32_MAX; return;
    }
    n=im->bytes-c->offset; if (n>budget) { n=budget; }
    crc=c->crc;
    while (n--) { crc^=im->rgb565_be[c->offset++];crc=(crc>>4)^lut[crc&15U];crc=(crc>>4)^lut[crc&15U]; }
    c->crc=crc;
    if (c->offset==im->bytes) {
        uint32_t state=(crc^UINT32_MAX)==im->crc32?GS_CONTENT_READY:GS_CONTENT_CORRUPT;
        ++c->checked; if (state==GS_CONTENT_CORRUPT) { ++c->errors; }
        c->states[c->index++]=state; c->offset=0;c->crc=UINT32_MAX;
    }
}
const gs_content_image_t *gs_content_find_image(const gs_content_context_t *c,uint16_t collection,uint16_t page)
{
    uint32_t i;
    if (!c || !c->package) { return NULL; }
    for (i=0;i<c->package->image_count;++i) {
        const gs_content_image_t *im=&c->package->images[i];
        if (im->collection==collection && im->page==page && c->states[i]==GS_CONTENT_READY) { return im; }
    }
    return NULL;
}
