#include "gs_ui_render.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
gs_ui_render_status_t baseline_ui_render_preview_rgb565(uint16_t *,size_t,uint16_t,uint16_t,size_t,const gs_preview_frame_t *);
gs_ui_render_status_t baseline_ui_render_dashboard_rgb565(const gs_ui_t *,const gs_ui_live_status_t *,uint16_t *,size_t,uint16_t,uint16_t,size_t,const gs_ui_render_theme_t *);
__declspec(align(4)) static uint16_t pixels[484U*810U+2U], oracle[484U*810U+2U];
static uint8_t gray[GS_PREVIEW_BYTES];
static const gs_ui_page_t pages[]={{"使用方式","将手放入取景框"}};
static const gs_ui_collection_t collections[]={{"使用指引",1,pages}};
int main(void)
{
    const struct {uint16_t w,h;size_t stride,offset;} cases[]={
        {800,480,800,0},{800,480,804,0},{800,480,801,0},{800,480,804,1},
        {801,481,806,0},{799,480,805,0},{320,240,325,1},{801,479,803,0}};
    gs_ui_t ui;gs_ui_live_status_t live;
    gs_preview_frame_t preview={{1,0},gray,sizeof gray,96,96,1,100};
    unsigned checks=0;
    assert(gs_ui_init(&ui,collections,1,5000));memset(&live,0,sizeof live);
    for(unsigned i=0;i<sizeof gray;++i) gray[i]=(uint8_t)(i*73U+(i/96U)*5U);
    for(unsigned c=0;c<sizeof cases/sizeof cases[0];++c) {
        for(unsigned status=0;status<=GS_STATIC_CAMERA_ERROR;++status) {
            memset(pixels,0xA5,sizeof pixels);memset(oracle,0xA5,sizeof oracle);
            live.now_ms=300;live.recognition.status=(gs_static_status_t)status;
            live.recognition.class_index=GS_STATIC_PALM;live.recognition.confidence_permille=970;
            live.recognition.frame_id=1;live.recognition.capture_ms=100;live.preview_frame_id=1;live.preview_age_ms=200;
            live.seven_class_ready=1;live.control_enabled=1;live.business_validated=0;
            gs_ui_render_status_t a=gs_ui_render_dashboard_rgb565(&ui,&live,pixels+cases[c].offset,
                sizeof pixels/2-cases[c].offset,cases[c].w,cases[c].h,cases[c].stride,NULL);
            gs_ui_render_status_t b=baseline_ui_render_dashboard_rgb565(&ui,&live,oracle+cases[c].offset,
                sizeof oracle/2-cases[c].offset,cases[c].w,cases[c].h,cases[c].stride,NULL);
            assert(a==b);
            memset(oracle,0xA5,sizeof oracle);
            assert(gs_ui_render_dashboard_rgb565(&ui,&live,oracle+cases[c].offset,
                sizeof oracle/2-cases[c].offset,cases[c].w,cases[c].h,cases[c].stride,NULL)==a);
            assert(!memcmp(pixels,oracle,sizeof pixels));
            a=gs_ui_render_preview_rgb565(pixels+cases[c].offset,sizeof pixels/2-cases[c].offset,
                cases[c].w,cases[c].h,cases[c].stride,&preview);
            b=baseline_ui_render_preview_rgb565(oracle+cases[c].offset,sizeof oracle/2-cases[c].offset,
                cases[c].w,cases[c].h,cases[c].stride,&preview);
            assert(a==b && !memcmp(pixels,oracle,sizeof pixels));++checks;
        }
    }
    assert(gs_ui_render_preview_rgb565(pixels,10,800,480,800,&preview)==GS_UI_RENDER_BUFFER_TOO_SMALL);
    const unsigned runs=100;clock_t start=clock();
    for(unsigned i=0;i<runs;++i) assert(baseline_ui_render_preview_rgb565(pixels,sizeof pixels/2,800,480,800,&preview)==GS_UI_RENDER_OK);
    double old_ms=(double)(clock()-start)*1000.0/CLOCKS_PER_SEC/runs;start=clock();
    for(unsigned i=0;i<runs;++i) assert(gs_ui_render_preview_rgb565(pixels,sizeof pixels/2,800,480,800,&preview)==GS_UI_RENDER_OK);
    double new_ms=(double)(clock()-start)*1000.0/CLOCKS_PER_SEC/runs;
    printf("HOST_ONLY /O2 preview draw old %.4f ms/new %.4f ms; NOT MCU timing\n",old_ms,new_ms);
    printf("PASS: %u deterministic seven-class dashboard checks plus frozen release5 preview oracle, aligned fixed display, odd stride, halfword offset, scale1/3, padding/guards\n",checks);
    return 0;
}
