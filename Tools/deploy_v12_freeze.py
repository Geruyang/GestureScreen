"""Freeze reviewed build and source snapshots without touching a target."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'Build/deployment-v12-20260922'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    release=WORK/'release'
    if release.exists():raise RuntimeError('Refusing to overwrite a frozen release')
    log=(ROOT/'Build/keil-build.log').read_text(errors='replace')
    assert '0 Error(s), 0 Warning(s)' in log
    for name in ('production-check','preprocess-check'):
        report=json.loads((WORK/f'host/{name}.json').read_text())
        for path,digest in report['source_sha256'].items():assert sha(Path(path))==digest,path
    baseline=ROOT/'Build/deployment-new-model-20260920/release/source-manifest.json'
    paths={entry['path'] for entry in json.loads(baseline.read_text())['files']}
    missing={p for p in paths if not (ROOT/p).is_file()}
    assert missing=={'MDK-ARM/GestureScreen.ioc','content/README.md','content/package.json','content/roi.png'},missing
    # v7 snapshot included relocated .ioc and presentation assets; bind current
    # root .ioc and actual built-in content source/package instead.
    paths-=missing
    paths|={'GestureScreen.ioc','Assets/content/package.json','Modules/Content/Src/gs_content_builtin.json'}
    assert all((ROOT/p).is_file() for p in paths)
    source_manifest=[]
    for relative in sorted(paths):
        source=ROOT/relative;target=release/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        assert sha(target)==sha(source)
        source_manifest.append(dict(path=relative,sha256=sha(target),bytes=target.stat().st_size))
    artifacts=[]
    for name in ('GestureScreen.axf','GestureScreen.hex','GestureScreen.map'):
        src=ROOT/'MDK-ARM/Objects'/name;dst=release/name;shutil.copy2(src,dst)
        assert sha(src)==sha(dst);artifacts.append(dict(path=name,sha256=sha(dst),bytes=dst.stat().st_size))
    validation=release/'validation';validation.mkdir()
    shutil.copy2(ROOT/'Build/keil-build.log',validation/'keil-build.log')
    for folder,name in [('model','conversion.json'),('host','comparison.json'),('host','production-check.json'),('host','preprocess-check.json')]:
        shutil.copy2(WORK/folder/name,validation/name)
    (release/'source-manifest.json').write_text(json.dumps(dict(self_contained=False,file_count=len(source_manifest),files=source_manifest),indent=2),encoding='utf-8')
    record=dict(generated_at=datetime.now(timezone.utc).isoformat(),status='frozen_for_board_test_not_business_accepted',
        selected_weights_sha256='72db45f37036530652ef07e19ad20e6ce94552027d0fc81a9987c074f6c5c4be',
        model_sha256=sha(WORK/'model/gesture_v12_int8.tflite'),source_file_count=len(source_manifest),artifacts=artifacts,
        source_manifest_sha256=sha(release/'source-manifest.json'),old_snapshot_relocated_assets=sorted(missing),unknown_semantics='User approved stable UNKNOWN neutral rearm; not physical hand absence',
        source_tools_sha256={p.name:sha(p) for p in ROOT.glob('Tools/deploy_v12_*.py')})
    (release/'freeze-manifest.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
