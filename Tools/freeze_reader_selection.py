"""Freeze the reader selection-visibility firmware after host and Keil checks."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "Build"
RELEASE = BUILD / "reader-selection-20260922" / "firmware"
BASELINE = BUILD / "reader-direction-20260922" / "firmware" / "manifest.json"
CHANGED = {
    "Modules/Ui/Inc/gs_ui_font_aa_subset.h",
    "Modules/Ui/Src/gs_ui_render.c",
    "Tests/test_reader_ui.c",
    "Tools/export_reader_screenshots.py",
}


def digest(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def run_check(script: Path, output: Path) -> None:
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    output.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode or "PASS:" not in result.stdout:
        raise RuntimeError(f"Validation failed: {script}")


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert digest(BUILD / "reader-direction-20260922/firmware/GestureScreen.hex")["sha256"] == \
        "9319a6863117359af1a49f7aadd0ba429dcdc8a60d6b7d24fa24830d37de23d9"
    source_files = {name: digest(ROOT / name) for name in baseline["source_files"]}
    changed = {name for name in source_files
               if source_files[name]["sha256"] != baseline["source_files"][name]["sha256"]}
    if changed != CHANGED:
        raise RuntimeError(f"Unexpected source delta against direction release: {sorted(changed)}")
    source_files["Tools/freeze_reader_selection.py"] = digest(Path(__file__))

    RELEASE.mkdir(parents=True, exist_ok=True)
    validation = RELEASE / "validation"
    validation.mkdir(exist_ok=True)
    for name, source in (("GestureScreen.axf", ROOT / "MDK-ARM/Objects/GestureScreen.axf"),
                         ("GestureScreen.hex", ROOT / "MDK-ARM/Objects/GestureScreen.hex"),
                         ("GestureScreen.map", ROOT / "MDK-ARM/Objects/GestureScreen.map"),
                         ("keil-build.log", BUILD / "keil-build.log"),
                         ("source/App/Inc/gs_timing_trace.h", ROOT / "App/Inc/gs_timing_trace.h")):
        copy(source, RELEASE / name)
    keil = (RELEASE / "keil-build.log").read_text(encoding="utf-8", errors="replace")
    if "0 Error(s), 0 Warning(s)" not in keil:
        raise RuntimeError("Keil log is not 0E/0W")

    run_check(ROOT / "Tools/verify.py", validation / "source-verify.log")
    run_check(ROOT / "Tests/check_reader_pagination.py", validation / "pagination-check.log")

    suites = re.findall(r"Name = '(test_[a-z0-9_]+)'", (ROOT / "Tools/test_host.ps1").read_text(encoding="utf-8"))
    if len(suites) != 17 or len(set(suites)) != 17:
        raise RuntimeError(f"Expected 17 host suites, got {suites}")
    host_logs = validation / "host-tests"
    host_logs.mkdir(exist_ok=True)
    for suite in suites:
        for suffix in ("build", "run"):
            copy(BUILD / "host" / f"{suite}-{suffix}.log", host_logs / f"{suite}-{suffix}.log")
        if "PASS" not in (host_logs / f"{suite}-run.log").read_text(encoding="utf-8") and \
                "passed" not in (host_logs / f"{suite}-run.log").read_text(encoding="utf-8"):
            raise RuntimeError(f"No PASS marker: {suite}")
    (validation / "host-suite-summary.json").write_text(json.dumps({
        "suite_count": len(suites), "passed": True, "suites": suites}, indent=2), encoding="utf-8")

    unchanged_model = json.loads((BUILD / "reader-direction-20260922/firmware/validation/source-diff-vs-reader-polish.json")
                                 .read_text(encoding="utf-8"))["model_preprocess_and_other_gesture_files_unchanged"]
    model_hashes = {name: digest(ROOT / name) for name in unchanged_model}
    (validation / "model-preprocess-hashes.json").write_text(json.dumps(model_hashes, indent=2), encoding="utf-8")
    (validation / "source-diff-vs-reader-direction.json").write_text(json.dumps({
        "baseline": str(BASELINE.relative_to(ROOT)).replace("\\", "/"),
        "changed_source_files": sorted(changed),
        "unchanged_baseline_files": sorted(set(source_files) - changed - {"Tools/freeze_reader_selection.py"}),
        "model_preprocess_file_count": len(model_hashes),
    }, indent=2), encoding="utf-8")

    sys.path.insert(0, str(ROOT / "Tools"))
    import timing_release_layout
    timing_release_layout.SIZES.update(s_ai_input=27648, g_gs_static_diag=364)
    _, layout = timing_release_layout.generate(RELEASE)
    map_text = (RELEASE / "GestureScreen.map").read_text(encoding="utf-8", errors="replace")
    layout_bytes = {}
    for name in ("ER_IROM1", "RW_CCM_AI", "RW_IRAM1"):
        match = re.search(r"Execution Region " + name + r" .*?Size: 0x([0-9a-fA-F]+)", map_text, re.S)
        if not match:
            raise RuntimeError(f"Missing map region {name}")
        layout_bytes[name] = int(match.group(1), 16)
    if layout_bytes["ER_IROM1"] > 0x100000 or layout_bytes["RW_CCM_AI"] > 0x10000 or \
            layout_bytes["RW_IRAM1"] > 0x30000:
        raise RuntimeError(f"Memory budget exceeded: {layout_bytes}")

    screenshots = sorted((RELEASE / "screenshots").glob("*.png"))
    if len(screenshots) != 8:
        raise RuntimeError(f"Expected eight real C-rendered screenshots, got {len(screenshots)}")
    artifact_files = {str(path.relative_to(BUILD / "reader-selection-20260922")).replace("\\", "/"): digest(path)
                      for path in sorted(RELEASE.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    manifest = {
        "identity": "reader-selection-20260922-host-frozen",
        "hardware_flashing": False,
        "baseline_hex_sha256": baseline["artifact_files"]["firmware/GestureScreen.hex"]["sha256"],
        "source_files": source_files,
        "artifact_files": artifact_files,
        "layout_bytes": layout_bytes,
        "validation": {"keil": "0 errors, 0 warnings", "host_suites": "all 17 passed",
                       "pagination": "all 15 pages <=4 conservative lines of 6",
                       "timing_layout": f"{len(layout['symbols'])} exact ELF symbols and AXF/HEX/map hashes verified",
                       "screenshot_count": len(screenshots)},
        "scope": "Selected shelf book and catalog row contrast only; gesture actions, model and thresholds unchanged.",
        "bounds": "host-only software checks; no hardware action or actual gesture test",
    }
    (RELEASE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"hex_sha256": digest(RELEASE / "GestureScreen.hex")["sha256"],
                      "axf_sha256": digest(RELEASE / "GestureScreen.axf")["sha256"],
                      "changed": sorted(changed), "layout_bytes": layout_bytes,
                      "host_suites": len(suites), "screenshots": len(screenshots)}, indent=2))


if __name__ == "__main__":
    main()
