"""Test normal packaged-window close with its independent service still alive."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time,urllib.request
project=Path(__file__).resolve().parents[1]
release=project/'Build/reader-clean-exit-20260923'
area=release/'validation/clean-exit'
area.mkdir(parents=True,exist_ok=True)
results=[]
for run in range(2):
 folder=area/f'only-exe-{run+1}'
 folder.mkdir()
 exe=folder/'GestureStudio.exe'
 shutil.copy2(release/'dist/GestureStudio.exe',exe)
 assert list(folder.iterdir())==[exe], 'Must begin with only the executable'
 temporary=area/f'temp-{run+1}'
 temporary.mkdir()
 report_file=area/f'close-{run+1}.json'
 env=dict(os.environ,TEMP=str(temporary),TMP=str(temporary))
 p=subprocess.Popen([str(exe),'--no-usb','--self-test-close-report',str(report_file)],
                    cwd=str(project.parent),env=env)
 try:
  code=p.wait(timeout=45)
  assert code==0,code
  details=json.loads(report_file.read_text(encoding='utf-8'))
  assert details['close_success'] and details['server_alive_after_window_close'],details
  assert Path(details['data_root'])==folder/'captures'
  assert (folder/'captures').is_dir()
  assert not Path(details['gui_extraction']).exists(), 'GUI extraction not removed'
  def state():
   try:
    with urllib.request.urlopen(f"http://127.0.0.1:{details['port']}/api/state",timeout=1) as r: return json.load(r)
   except OSError: return None
  live=state()
  assert live and live['total']==0 and live['history_total']==0 and live.get('model')
  deadline=time.monotonic()+45
  while time.monotonic()<deadline and (state() is not None or list(temporary.glob('_MEI*'))): time.sleep(.25)
  remaining=list(temporary.glob('_MEI*'))
  assert state() is None and not remaining,[str(x) for x in remaining]
  results.append({'run':run+1,'exit_code':code,'only_exe_initially':True,'captures_created':True,
                  'gui_extraction_removed_while_server_alive':True,'server_survived_gui_close':True,
                  'background_idle_exit':True,'all_owned_extractions_removed':True})
  print(json.dumps(results[-1]),flush=True)
 finally:
  if p.poll() is None:
   subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
report={'ok':True,'exe_sha256':hashlib.sha256((release/'dist/GestureStudio.exe').read_bytes()).hexdigest(),'runs':results}
(release/'validation/clean-exit-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
