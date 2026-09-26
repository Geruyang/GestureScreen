# Tool and test status

| Area | Entry points | Requirements |
| --- | --- | --- |
| Firmware build | `build.ps1`, `integrate.py` | Windows, matching Keil/CubeMX toolchain and its license. Pass `-UV4`, set `KEIL_UV4`, or put UV4.exe on PATH. |
| Static analysis | `analyze.py` | Arm Compiler 6. Pass `--compiler`, set `ARMCLANG`, or put armclang on PATH. |
| Host capture tests | `../Tests/test_capture_client.py`, `test_capture_server.py`, `test_managed_capture.py` | Python 3.12 and `../HostTools/requirements-usb.txt`; synthetic files only. Run via the CI commands in `../.github/workflows/ci.yml`. |
| Device/debug helpers | `firedap.ps1`, `debug_firedap.ps1`, `snapshot_firedap.ps1` and `../Debug/` | Correct Challenger V1 board and probe. These scripts can affect a connected target; read them before use. |
| Final model deployment scripts | `deploy_v12_*`, `../HostTools/model/` | These preserve the final conversion and deployment procedure; rerunning the original export requires the private dataset and removed build intermediates. The frozen model, preprocessing source, and runtime library used by Studio are included. |
| Reader content and timing | `build_reader_content.py`, `deploy_v5_content.py`, `deploy_v5_content_check.py`, `timing_release_layout.py` | The `deploy_v5_content*` filenames predate the final reader, but these scripts produce or verify its content package. The timing checker binds a layout to its exact AXF. |
| Historical fixture-based checks | Parts of `../Tests/` | Private or generated `Tests/fixtures/` files are deliberately absent. The CI job runs only the listed synthetic capture tests. |

The public repository preserves final source and tools, not the private training dataset or a universal build environment. Do not substitute invented fixture images for the original evaluation data, and do not interpret a host test as proof of real-board timing or gesture accuracy.
