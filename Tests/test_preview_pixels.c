/* Actual preview-only sampler vs unchanged actual inference preprocessing.
 * Optional argv paths are saved raw files, never live camera/USB/probe inputs. */
#define _CRT_SECURE_NO_WARNINGS
#include "gs_preview.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
static uint8_t raw[240U*648U];
static uint32_t buffers[2][GS_PREVIEW_BYTES/4U];
static gs_preview_pool_t pool;
static gs_rgb565_frame_t image;
static uint32_t random_state=20260917U;
static unsigned vectors;
static uint32_t reference_y(unsigned x, unsigned y)
{
    size_t at = (GS_ROI_Y + y) * image.stride_bytes + (GS_ROI_X + x) * 2U;
    uint16_t pixel = image.byte_order == GS_RGB565_MSB_FIRST ?
        (uint16_t)(((uint16_t)raw[at] << 8U) | raw[at + 1U]) :
        (uint16_t)(((uint16_t)raw[at + 1U] << 8U) | raw[at]);
    uint32_t r5 = (pixel >> 11U) & 31U, g6 = (pixel >> 5U) & 63U, b5 = pixel & 31U;
    uint32_t r8 = (r5 << 3U) | (r5 >> 2U), g8 = (g6 << 2U) | (g6 >> 4U), b8 = (b5 << 3U) | (b5 >> 2U);
    return (77U * r8 + 150U * g8 + 29U * b8 + 128U) >> 8U;
}
static void compare(void)
{
    gs_preview_frame_t preview;
    assert(gs_preview_publish_rgb565(&pool,&image,++vectors,123,&preview)==GS_PREVIEW_OK);
    for(unsigned i=0;i<GS_PREVIEW_BYTES;++i) {
        unsigned x=(i%96U)*2U,y=(i/96U)*2U;
        uint32_t total=reference_y(x,y)+reference_y(x+1U,y)+reference_y(x,y+1U)+reference_y(x+1U,y+1U);
        assert(preview.pixels[i]==(uint8_t)((total+2U)/4U));
    }
    assert(gs_preview_release(&pool,preview.ticket)==GS_PREVIEW_OK);
}
int main(int argc,char **argv)
{
    gs_preview_frame_t output, sentinel;
    unsigned i,v;
    assert(sizeof(gs_preview_diagnostics_t)==48);
    assert(gs_preview_pool_init(&pool,buffers[0],sizeof buffers[0],buffers[1],sizeof buffers[1])==GS_PREVIEW_OK);
    image.data=raw; image.data_size=153600; image.width=320;image.height=240;image.stride_bytes=640;
    image.byte_order=GS_RGB565_MSB_FIRST;
    for(v=0;v<50;++v) {
        for(i=0;i<sizeof raw;++i) { random_state=random_state*1664525U+1013904223U;raw[i]=(uint8_t)(random_state>>24); }
        image.stride_bytes=(v%2?647:640);image.data_size=image.stride_bytes*239U+640U;
        image.byte_order=(v%3?GS_RGB565_MSB_FIRST:GS_RGB565_LSB_FIRST); compare();
    }
    /* Every one of the 65536 RGB565 colors, tiled across full ROI blocks.
       Both byte orders must preserve expansion/rounding exactly. */
    image.stride_bytes=640;image.data_size=153600;
    for(v=0;v<8;++v) {
        for(i=0;i<GS_PREVIEW_BYTES;++i) {
            uint16_t color=(uint16_t)(v*GS_PREVIEW_BYTES+i);
            for(unsigned dy=0;dy<2;++dy) for(unsigned dx=0;dx<2;++dx) {
                size_t at=(GS_ROI_Y+(i/96)*2U+dy)*640U+(GS_ROI_X+(i%96)*2U+dx)*2U;
                raw[at]=(uint8_t)(color>>8); raw[at+1]=(uint8_t)color;
            }
        }
        image.byte_order=GS_RGB565_MSB_FIRST; compare();
        for(i=0;i<153600;i+=2) { uint8_t t=raw[i];raw[i]=raw[i+1];raw[i+1]=t; }
        image.byte_order=GS_RGB565_LSB_FIRST; compare();
    }
    for(v=0;v<2;++v) { memset(raw,v?0xFF:0,sizeof raw);compare(); }
    memset(&sentinel,0x5A,sizeof sentinel);output=sentinel;
    uint32_t token=pool.next_token;
    image.data_size=153599; assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_INVALID);
    image.data_size=153600;image.stride_bytes=SIZE_MAX;
    assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_INVALID);
    image.stride_bytes=639;assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_INVALID);
    image.stride_bytes=640;image.byte_order=(gs_rgb565_byte_order_t)9;
    assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_INVALID);
    image.byte_order=GS_RGB565_MSB_FIRST;image.width=319;
    assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_INVALID);
    image.width=320;assert(gs_preview_publish_rgb565(&pool,&image,0,1,&output)==GS_PREVIEW_INVALID);
    assert(!memcmp(&output,&sentinel,sizeof output) && pool.next_token==token && !pool.slots[0].in_use);
    image.data=(const uint8_t *)buffers[0];
    assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_INVALID);image.data=raw;
    pool.next_token=0;assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_TOKEN_EXHAUSTED);pool.next_token=token;
    image.byte_order=GS_RGB565_MSB_FIRST; /* Saved BSP raw frames use high byte first. */
    for(int n=1;n<argc;++n) {
        FILE *file=fopen(argv[n],"rb");assert(file);
        assert(fread(raw,1,153600,file)==153600 && fgetc(file)==EOF);fclose(file);
        compare();printf("PASS saved raw pixels: %s\n",argv[n]);
    }
    /* Host-only sampler cost; not a Cortex-M4 timing estimate. */
    const unsigned runs=150;
    clock_t start=clock();
    for(i=0;i<runs;++i) {
        assert(gs_preview_publish_rgb565(&pool,&image,1,1,&output)==GS_PREVIEW_OK);
        assert(gs_preview_release(&pool,output.ticket)==GS_PREVIEW_OK);
    }
    double new_ms=(double)(clock()-start)*1000.0/CLOCKS_PER_SEC/runs;
    printf("HOST_ONLY /O2 sampler %.4f ms; NOT MCU timing\n",new_ms);
    printf("PASS: %u actual sampler vectors including all65536 colors, 50 synthetic, order/stride/rounding/bounds/lease\n",vectors);
    return 0;
}
