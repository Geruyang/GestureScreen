"""Move unused generated import candidates out of the final dataset, recoverably."""
import json
import shutil
import sys
from pathlib import Path

root=Path(sys.argv[1]).resolve()
expected=Path(__file__).resolve().parents[1]/"Datasets"/"gesture-800-v1"
if root!=expected.resolve():
    raise ValueError("only the generated gesture-800-v1 output is in scope")
manifest=json.loads((root/"dataset_manifest.json").read_text(encoding="utf-8"))
if len(manifest["samples"])!=800:
    raise ValueError("expected the completed 800-row manifest")
keep={str((root/row[field]).resolve()) for row in manifest["samples"] for field in ("file","preview_file")}
archive=root.parent/(root.name+"-unused-imports")
moved=[]
for path in (root/"external").rglob("*"):
    if path.is_file() and path.suffix in (".rgb565",".png") and str(path.resolve()) not in keep:
        relative=path.resolve().relative_to(root)
        target=archive/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise ValueError(f"refusing to overwrite archive {target}")
        shutil.move(str(path),str(target))
        moved.append(relative.as_posix())
(root/"unused_candidates_moved.json").write_text(json.dumps({"archive":str(archive),"moved":moved},indent=2),encoding="utf-8")
print(json.dumps({"raw_frames":len(list(root.rglob("*.rgb565"))),"moved_files":len(moved),"recoverable_archive":str(archive)}))
