"""为临时七类软件夹具编译C导出并执行数值/业务门禁对照；不发布权重。"""
from pathlib import Path
import json
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_c import export
from install_model import install


def verify(model, output):
    project = Path(__file__).resolve().parents[2]
    export(model, output, model_id="SYNTHETIC_SOFTWARE_TEST_NOT_A_GESTURE_MODEL")
    includes = project / "Modules/Vision/Inc"
    sources = [project / "Modules/Vision/Src/gs_ai_int8_backend.c", project / "Modules/Vision/Src/gs_ai.c"]
    vcvars = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat")
    for path in [includes, *sources, vcvars, output]:
        if any(c in str(path) for c in '"%!^\r\n'):
            raise ValueError("unsafe batch compiler path")
    command = (f'cl /nologo /LD /O2 /std:c11 /utf-8 /W4 /WX /I"{includes}" '
               + " ".join(f'"{p}"' for p in sources)
               + ' gs_model_weights.c /Fe:gs_model_seven_test.dll /link /EXPORT:gs_model_raw_run /EXPORT:gs_model_network /EXPORT:gs_int8_execute /EXPORT:gs_model_candidate_backend /EXPORT:gs_ai_init')
    (output / "compile.cmd").write_text(f'@echo off\nsetlocal DisableDelayedExpansion\ncall "{vcvars}" > vcvars.log 2>&1\nif errorlevel 1 exit /b 1\nset "CL="\nset "_CL_="\n{command}\nexit /b %errorlevel%\n', encoding="utf-8")
    subprocess.run(["cmd", "/d", "/c", "compile.cmd"], cwd=output, check=True)
    subprocess.run([sys.executable, str(Path(__file__).with_name("compare_c_backend.py")), str(model),
                    str(output / "gs_model_seven_test.dll"), "--report", str(project / "Models/validation/c_backend_seven_fixture.json")], check=True)
    # 正式固件编译器独立核对；不修改现有uvprojx、不链接或下载硬件。
    compiler = Path("D:/Keil5/ARM/ARMCLANG/bin/armclang.exe")
    for source in [*sources, output / "gs_model_weights.c"]:
        subprocess.run([str(compiler), "--target=arm-arm-none-eabi", "-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16",
                        "-mfloat-abi=hard", "-std=c99", "-Wall", "-Wextra", "-Werror", "-Oz", f"-I{includes}",
                        "-c", str(source), "-o", str(output / (source.stem + "_arm.o"))], check=True)
    temporary_project = output / "temporary-install-project"
    for relative in ("Modules/Vision/Inc/gs_model_selected.h", "Modules/Vision/Src/gs_model_selected.c"):
        target = temporary_project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / relative, target)
    installed = install(output, temporary_project, integrate=False)
    assert installed["validated_for_business"] is False
    assert "gs_model_candidate_backend" in (temporary_project / "Modules/Vision/Src/gs_model_selected.c").read_text(encoding="utf-8")
    weights = output / "gs_model_weights.c"
    original = weights.read_bytes()
    try:
        weights.write_bytes(original + b"\n")
        try:
            install(output, temporary_project, integrate=False)
        except ValueError as error:
            assert "SHA-256 mismatch" in str(error)
        else:
            raise AssertionError("modified generated weights were not rejected")
    finally:
        weights.write_bytes(original)
    (project / "Models/validation/install_smoke.json").write_text(json.dumps(dict(
        scope="Temporary project only; no synthetic weights installed into actual firmware", copied_generated_artifacts=True,
        selector_changed=True, corrupted_weights_rejected=True, real_integrate_not_run_in_fixture=True,
        validated_for_business=False), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
