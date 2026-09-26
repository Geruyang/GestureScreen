"""Exercise the content CRC loader, corruption fallback and bounded work."""
from pathlib import Path
import subprocess,json,importlib.util,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'Build/reader-20260922/content-check';out.mkdir(parents=True,exist_ok=True)
c=out/'test.c'
c.write_text(r'''
#include "gs_content.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
 gs_content_context_t c;
 gs_content_package_t p=g_gs_content_builtin_package;
 static const unsigned char pixels[10000]={0};
 gs_content_image_t im={0,0,100,50,pixels,sizeof pixels,0x4d3bca2eU};
 unsigned calls=0;
 assert(gs_content_init(&c,&p));
 assert(!gs_content_find_image(&c,0,0));
 assert(p.image_count==0 && p.images==0);
 gs_content_step(&c,0xffffffffU); assert(c.checked==0 && c.errors==0);
 p.images=&im; p.image_count=1;
 assert(gs_content_init(&c,&p));
 gs_content_step(&c,0); assert(c.offset==0);
 gs_content_step(&c,0xffffffffU); assert(c.offset==4096);
 while(!c.checked) { gs_content_step(&c,100); assert(++calls<240); }
 assert(c.errors==0 && gs_content_find_image(&c,0,0));
 assert(!gs_content_find_image(&c,99,99));
 gs_content_step(&c,100);assert(c.checked==1);
 p.images=&im; im.crc32^=1;
 assert(gs_content_init(&c,&p));
 while(!c.checked)gs_content_step(&c,4096);
 assert(c.errors==1 && !gs_content_find_image(&c,0,0));
 im.width=321;im.rgb565_be=(const unsigned char*)1;
 assert(gs_content_init(&c,&p));gs_content_step(&c,1);
 assert(c.errors==1 && c.checked==1 && !gs_content_find_image(&c,0,0));
 im.width=100;im.rgb565_be=pixels;im.bytes=sizeof pixels-1U;
 assert(gs_content_init(&c,&p));gs_content_step(&c,1);assert(c.errors==1);
 p.image_count=17;assert(!gs_content_init(&c,&p));
 assert(!gs_content_init(0,&p));assert(!gs_content_init(&c,0));
 gs_content_step(0,1);assert(!gs_content_find_image(0,0,0));
 puts("content: bounded CRC, valid image, corruption, metadata and null checks passed");
 return 0;
}
''')
gcc=ROOT.parent/'STAI/4.0/Utilities/windows/mingw64/bin/gcc.exe'
args=[str(gcc),'-std=c99','-Wall','-Wextra','-Werror']
args += ['-I'+str(p) for p in (ROOT/'Modules').glob('*/Inc')]
args += [str(c),str(ROOT/'Modules/Content/Src/gs_content.c'),str(ROOT/'Modules/Content/Src/gs_content_builtin.c'),'-o',str(out/'test.exe')]
subprocess.run(args,check=True);r=subprocess.run([str(out/'test.exe')],check=True,text=True,capture_output=True)
(out/'result.json').write_text(json.dumps({'passed':True,'output':r.stdout},indent=2));print(r.stdout)
spec=importlib.util.spec_from_file_location('compiler',ROOT/'Tools/deploy_v5_content.py')
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
source=out/'conflict.json';source.write_text((ROOT/'Assets/content/package.json').read_text(encoding='utf-8'),encoding='utf-8')
before=hashlib.sha256(source.read_bytes()).hexdigest()
try:compiler.compile_content(source,out/'conflict.c')
except ValueError:pass
else:raise AssertionError('Source/manifest collision was accepted')
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
source.write_text('{"schema_version":1,"schema_version":2}',encoding='utf-8')
try:compiler.compile_content(source,out/'other.c')
except ValueError:pass
else:raise AssertionError('Duplicate JSON keys were accepted')
source.write_text(json.dumps({'schema_version':1,'version':'test','collections':[{'title':'test','pages':[{'title':'a','body':'b','image':'../escape.png'}]}]}),encoding='utf-8')
try:compiler.compile_content(source,out/'other.c')
except ValueError:pass
else:raise AssertionError('Image path escape was accepted')
(out/'converter-result.json').write_text(json.dumps({'source_preservation':True,'duplicate_keys_rejected':True,'path_escape_rejected':True},indent=2))
print('converter: source preservation, duplicate keys and path escape checks passed')
