"""Complete the reader release source snapshot and bind diagnostics to its AXF."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import timing_release_layout

root = Path(__file__).resolve().parents[1]
work = root / "Build/reader-20260922"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--release-name", default="release")
parser.add_argument("--review", default="firmware/manifest.json",
                    help="Worker review path relative to the reader bundle")
parser.add_argument("--source-baseline", default="Build/deployment-v12-20260922/release/source-manifest.json",
                    help="Prior source manifest path relative to GestureScreen")
parser.add_argument("--validation", default="9 affected host suites, Keil 0 errors 0 warnings, content validation; not hardware acceptance")
args = parser.parse_args()
release = (work / args.release_name).resolve()
review_path = (work / args.review).resolve()
assert release.parent == work.resolve(), "Release must be a direct child of the reader bundle"
assert review_path.is_relative_to(work.resolve()), "Review must stay in the reader bundle"
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert not (release / "source").exists(), "Refusing to overwrite frozen source snapshot"
review = json.loads(review_path.read_text(encoding="utf-8"))
for name, value in review["source_files"].items():
    assert sha(root/name) == value["sha256"], name
for name, value in review["artifact_files"].items():
    assert sha(work/name) == value["sha256"], name
baseline = json.loads((root / args.source_baseline).read_text())
paths = {row["path"] for row in baseline["files"]} | set(review["source_files"])
paths.add("Tools/freeze_reader_sources.py")
rows = []
for name in sorted(paths):
    source, target = root/name, release/"source"/name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    assert sha(source) == sha(target)
    rows.append(dict(path=name, sha256=sha(target), bytes=target.stat().st_size))
(release/"source-manifest.json").write_text(json.dumps(dict(self_contained=False,
    file_count=len(rows), files=rows), indent=2), encoding="utf-8")
# Contract changed in v12: six logits and 96x96 RGB, not legacy seven/gray.
timing_release_layout.SIZES.update(s_ai_input=27648, g_gs_static_diag=364)
layout_path, layout = timing_release_layout.generate(release)
record = dict(status="offline_reader_candidate_not_flashed", source_file_count=len(rows),
              source_manifest_sha256=sha(release/"source-manifest.json"),
              worker_review_sha256=sha(review_path),
              hex_sha256=sha(release/"GestureScreen.hex"), axf_sha256=sha(release/"GestureScreen.axf"),
              layout_sha256=sha(layout_path), model_unchanged_from="deployment-v12-20260922",
              validation=args.validation)
(release/"freeze-manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record, indent=2))
