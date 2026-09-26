from pathlib import Path
import hashlib,json,shutil,subprocess,sys,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
project=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(project/'HostTools'))
from managed_capture import ManagedCaptureStore
release=project/'Build/reader-portable-path-20260923'
area=release/'validation/portable-move'
area.mkdir(parents=True,exist_ok=True)
a=area/'位置 A'; b=area/'different location B'
assert not a.exists() and not b.exists()
a.mkdir()
shutil.copy2(release/'dist/GestureStudio.exe',a/'GestureStudio.exe')
store=ManagedCaptureStore(a/'captures',raw_capture_only=True)
try:
 store.workspace_action({'action':'open','owner':'a'*32})
 store.session_action({'action':'new','name':'synthetic portable','split':'train','sensor_profile':'synthetic','exposure_profile':'synthetic'})
 store.clip_action({'action':'start','fps':5,'label':'PALM','duration_seconds':60})
 t=store.begin({'device_id':'synthetic','frame_id':1,'capture_ms':1,'epoch':store.epoch})
 try: _,r=store.commit(t,b'\xf8\x00'*(320*240))
 finally: store.release(t)
 store.clip_action({'action':'finish'})
 end=time.monotonic()+5
 while store.state()['pending_clips'] and time.monotonic()<end: time.sleep(.02)
 assert not store.state()['pending_clips']
 store.session_action({'action':'save'})
 manifest=Path(store.export('current')['manifest'])
 record_id=r['record_id']; clip_id=next(iter(store.clips))
finally: store.close()
class Foreign(BaseHTTPRequestHandler):
 def do_GET(self):
  data=json.dumps({'capabilities':['session_workspace_v2','raw_capture_v1'],'raw_capture_only':True,'output_root':str(area/'unrelated')}).encode()
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args): pass
fixture=None
try:
 fixture=ThreadingHTTPServer(('127.0.0.1',8765),Foreign)
 threading.Thread(target=fixture.serve_forever,daemon=True).start()
except OSError:
 pass # An existing foreign service also exercises the port-conflict path.
results=[]
def exercise(folder):
 p=subprocess.Popen([str(folder/'GestureStudio.exe'),'--no-usb'],cwd=str(project.parent))
 try:
  end=time.monotonic()+45
  state=None;port=None
  while time.monotonic()<end:
   try:
    port=json.loads((folder/'captures/.studio-service.json').read_text(encoding='utf-8'))['port']
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/state',timeout=1) as response: state=json.load(response)
    if Path(state['output_root']).resolve()==(folder/'captures').resolve() and state.get('workspace_busy'): break
   except (OSError,ValueError,KeyError): pass
   time.sleep(.2)
  assert state and state.get('workspace_busy'), 'No rendered client workspace'
  assert port!=8765 and Path(state['output_root']).resolve()==(folder/'captures').resolve()
  assert state['history_total']==1 and state['total']==0
  for route in (f'/media/{record_id}.png',f'/media/{record_id}.rgb565',f'/video/{clip_id}'):
   with urllib.request.urlopen(f'http://127.0.0.1:{port}'+route,timeout=3) as response: assert len(response.read())>0
  return {'folder':str(folder),'port':port,'history_frames':state['history_total'],'default_data_folder':state['output_root'],'window_loaded':True,'image_and_video_http':True}
 finally:
  subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try: p.wait(timeout=5)
  except subprocess.TimeoutExpired: p.kill()
try:
 results.append(exercise(a))
 shutil.copytree(a,b)
 results.append(exercise(b))
 assert (b/'captures'/manifest.name).read_bytes()==manifest.read_bytes()
 report={'ok':True,'same_exe_sha256':hashlib.sha256((a/'GestureStudio.exe').read_bytes()).hexdigest(),'foreign_8765_fixture_owned':fixture is not None,'manifest_unchanged':True,'runs':results}
 (release/'validation/portable-exe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False))
finally:
 if fixture: fixture.shutdown();fixture.server_close()
