"""Render production UI with synthetic status for visual review, not board evidence."""
from pathlib import Path
import subprocess,struct
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'Build/deployment-v5/ui-preview';out.mkdir(parents=True,exist_ok=True)
source=out/'preview.c'
source.write_text(r'''
#include "gs_ui_render.h"
#include "gs_content.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>
static uint16_t pixels[800*480];
static const gs_ui_page_t extra[]={{"Settings","Runtime controls"},{"Model","Approved student"},{"Input","Fixed ROI"}};
int main(void){
 gs_ui_collection_t groups[5];gs_ui_t ui;gs_ui_live_status_t live;
 const char *names[]={"directory","content","settings","diagnostics"};unsigned i;
 memcpy(groups,g_gs_content_builtin_package.collections,3*sizeof(groups[0]));
 groups[3]=(gs_ui_collection_t){"Settings",3,extra,GS_UI_COLLECTION_SETTINGS};
 groups[4]=(gs_ui_collection_t){"Diagnostics",3,extra,GS_UI_COLLECTION_DIAGNOSTICS};
 assert(gs_ui_init(&ui,groups,5,5000));memset(&live,0,sizeof(live));
 live.now_ms=1000;live.recognition.capture_ms=900;live.recognition.frame_id=12;
 live.recognition.status=GS_STATIC_IDENTIFIED;live.recognition.class_index=GS_STATIC_PALM;
 live.recognition.confidence_permille=975;live.recognition.inference_ms=180;
 live.healthy=live.seven_class_ready=live.control_enabled=1;live.gesture_state=GS_GESTURE_READY;
 live.camera_fps_milli=7200;live.vision_fps_milli=4300;live.max_inference_ms=214;
 live.heap_free_bytes=10176;live.heap_min_free_bytes=9040;live.stack_min_free_bytes=860;
 live.content_version=g_gs_content_builtin_package.version;live.content_checked=1;
 live.content_rgb565_be=g_gs_content_builtin_package.images[0].rgb565_be;
 live.content_image_bytes=g_gs_content_builtin_package.images[0].bytes;
 live.content_image_width=160;live.content_image_height=72;
 for(i=0;i<4;i++){
  char name[100];FILE *f;ui.mode=i?GS_UI_READER:GS_UI_DIRECTORY;ui.selected=i>1?i+1:0;ui.page=0;
  assert(gs_ui_render_dashboard_rgb565(&ui,&live,pixels,800*480,800,480,800,0)==GS_UI_RENDER_OK);
  sprintf(name,"%s.rgb565",names[i]);f=fopen(name,"wb");assert(f);fwrite(pixels,2,800*480,f);fclose(f);
 }
 return 0;
}
''')
gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
sources=['Modules/UI/Src/gs_ui.c','Modules/UI/Src/gs_ui_render.c','Modules/Content/Src/gs_content_builtin.c','Modules/StaticRecognition/Src/gs_static_recognition.c','Modules/StaticRecognition/Src/gs_static_weights.c','Modules/Vision/Src/gs_ai_int8_backend.c']
args=[str(gcc),'-std=c99','-O2']+['-I'+str(p) for p in (ROOT/'Modules').glob('*/Inc')]+[str(source)]+[str(ROOT/p) for p in sources]+['-lm','-o',str(out/'preview.exe')]
subprocess.run(args,check=True);subprocess.run([str(out/'preview.exe')],cwd=out,check=True)
for path in out.glob('*.rgb565'):
 raw=path.read_bytes();rgb=bytearray()
 for (value,) in struct.iter_unpack('<H',raw):
  r=(value>>11)&31;g=(value>>5)&63;b=value&31;rgb.extend(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2)))
 Image.frombytes('RGB',(800,480),bytes(rgb)).save(path.with_suffix('.png'))
print(out)
