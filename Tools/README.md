# Tool and test status

| Area | Entry points | Requirements |
| --- | --- | --- |
| Firmware build | `build.ps1`, `integrate.py` | Windows, matching Keil/CubeMX toolchain and its license. Pass `-UV4`, set `KEIL_UV4`, or put UV4.exe on PATH. |
| Static analysis | `analyze.py` | Arm Compiler 6. Pass `--compiler`, set `ARMCLANG`, or put armclang on PATH. |
| Host capture tests | `../Tests/test_capture_client.py`, `test_capture_server.py`, `test_managed_capture.py` | Python 3.12 and `../HostTools/requirements-usb.txt`; synthetic files only. Run via the CI commands in `../.github/workflows/ci.yml`. |
| Device/debug helpers | `firedap.ps1`, `debug_firedap.ps1`, `snapshot_firedap.ps1` and `../Debug/` | Correct Challenger V1 board and probe. These scripts can affect a connected target; read them before use. |
| Historical model/deployment scripts | `deploy_v5_*`, `deploy_v12_*`, `deploy_candidate_*`, `../Models/` | Many require the private dataset, removed build intermediates, or modules in the private `custom_dataset/tools` tree. They are research records and are not runnable end-to-end from this public checkout. |
| Historical fixture-based checks | Parts of `../Tests/` | Private or generated `Tests/fixtures/` files are deliberately absent. The CI job runs only the listed synthetic capture tests. |

The public repository preserves final source and tools, not the private training dataset or a universal build environment. Do not substitute invented fixture images for the original evaluation data, and do not interpret a host test as proof of real-board timing or gesture accuracy.
