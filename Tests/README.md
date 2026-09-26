# Tests

The CI workflow runs three synthetic, privacy-safe capture suites: `test_capture_client.py`, `test_capture_server.py`, and `test_managed_capture.py`. They exercise host behavior without personal images or a board. Other tests document historical verification and can require private/generated `fixtures`, a licensed Keil installation, a particular build artifact, or connected hardware. Therefore `pytest Tests/` is not a supported all-tests command for a fresh public clone.

From the repository root with Python 3.12 and `HostTools/requirements-usb.txt` installed, use the exact commands in [CI](../.github/workflows/ci.yml). The final firmware's prior board health check, model classification, hold timing, and page actions remain separate validation scopes.
