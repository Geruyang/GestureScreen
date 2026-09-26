"""安装经哈希校验的七类候选到Keil自动扫描目录；不更改业务验收标志。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from dataset import LABELS


def install(candidate: Path, project: Path, *, integrate: bool = True):
    candidate, project = candidate.resolve(), project.resolve()
    report = json.loads((candidate / "c_export_report.json").read_text(encoding="utf-8"))
    contract = json.loads((candidate / "candidate_contract.json").read_text(encoding="utf-8"))
    if (not re.fullmatch(r"[0-9a-f]{64}", str(report.get("model_sha256", "")))
            or report.get("output_count") != 7 or report.get("reference_five_class_only") is not False
            or report.get("validated_for_business") is not False
            or contract.get("validated_for_business") is not False
            or contract.get("output", {}).get("labels") != LABELS
            or report.get("model_sha256") != contract.get("model_sha256")):
        raise ValueError("requires consistent seven-class unaccepted candidate; five-class/reference cannot be installed")
    destinations = {
        "gs_model_weights.c": project / "Modules/Vision/Src/gs_model_weights.c",
        "gs_model_weights.h": project / "Modules/Vision/Inc/gs_model_weights.h",
        "gs_model_metadata_candidate.h": project / "Modules/Vision/Inc/gs_model_metadata_candidate.h",
    }
    hashes = report.get("generated_files_sha256", {})
    for filename in destinations:
        expected = hashes.get(filename)
        actual = hashlib.sha256((candidate / filename).read_bytes()).hexdigest()
        if not expected or expected != actual:
            raise ValueError(f"generated artifact SHA-256 mismatch: {filename}")
    if not (project / "Modules/Vision/Inc/gs_model_selected.h").is_file():
        raise ValueError("target is not a GestureScreen project with stable model selector")
    # 保留上一次源码便于回退；只处理明确命名的模型产物，不删除目录。
    previous = project / "Build/model-selection-backup"
    previous.mkdir(parents=True, exist_ok=True)
    selector = project / "Modules/Vision/Src/gs_model_selected.c"
    for destination in [*destinations.values(), selector]:
        if destination.exists():
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()[:12]
            shutil.copyfile(destination, previous / f"{destination.name}.{digest}.backup")
    for filename, destination in destinations.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate / filename, destination)
    selector.write_text('#include "gs_model_selected.h"\n#include "gs_model_weights.h"\n\n'
                        f'/* Candidate model SHA-256: {report["model_sha256"]}; business gate remains closed. */\n'
                        'const gs_ai_backend_t *gs_model_selected_backend(void)\n{\n    return gs_model_candidate_backend();\n}\n', encoding="utf-8")
    active = project / "Models/Active"
    active.mkdir(parents=True, exist_ok=True)
    for name in ("c_export_report.json", "candidate_contract.json", "tflite_audit.json", "PRETRAINED_LICENSE.txt"):
        if (candidate / name).is_file():
            shutil.copyfile(candidate / name, active / name)
        elif (active / name).is_file():
            stale = active / name
            digest = hashlib.sha256(stale.read_bytes()).hexdigest()[:12]
            shutil.copyfile(stale, previous / f"{name}.{digest}.backup")
            stale.unlink()  # 仅移除明确命名且已备份的旧模型资料，防止许可/审计串包。
    if integrate:
        subprocess.run([sys.executable, str(project / "Tools/integrate.py")], cwd=project, check=True)
    return dict(model_sha256=report["model_sha256"], installed_sources=[str(p) for p in destinations.values()],
                selected_backend="gs_model_candidate_backend", validated_for_business=False, integrated=integrate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.candidate, args.project), indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Candidate installation failed: {error}\n")


if __name__ == "__main__":
    main()
