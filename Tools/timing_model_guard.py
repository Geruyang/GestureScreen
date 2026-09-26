"""Read-only hash gate for the timing-only candidate against its frozen baseline."""
import argparse
import hashlib
import json
from pathlib import Path


def protected(path):
    return (path.startswith("Middlewares/ST/AI/")
            or path.startswith("Modules/StaticRecognition/")
            or path.startswith("Modules/Gesture/")
            or path.startswith("Modules/Vision/"))


def check(baseline, candidate):
    manifest = json.loads((baseline / "source-manifest.json").read_text(encoding="utf-8-sig"))
    rows = []
    for item in manifest["files"]:
        if not protected(item["path"]):
            continue
        source = baseline / "source" / item["path"]
        target = candidate / item["path"]
        original = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
        current = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        rows.append({"path": item["path"], "expected": item["sha256"],
                     "baseline_actual": original, "candidate_actual": current,
                     "passed": original == current == item["sha256"]})
    return {"baseline": str(baseline.resolve()), "candidate": str(candidate.resolve()),
            "scope": "Frozen model, official runtime, preprocessing, classification and gesture policy files; scheduling reviewed separately",
            "passed": bool(rows) and all(row["passed"] for row in rows),
            "checked_files": len(rows), "files": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = check(args.baseline, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
