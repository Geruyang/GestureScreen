# Gesture Studio and capture tools

The [release executable](https://github.com/Geruyang/GestureScreen/releases)
is the simplest way to use Gesture Studio on Windows. The final portable
version was tested on Windows 11 x64. It is a single file and creates an
empty `captures` directory beside itself when first run. Windows 10 x64 is a
support target without a physical-machine verification claim.

## Source workflow

Use Python 3.12 on Windows. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r HostTools\requirements-studio.txt
.\.venv\Scripts\python.exe HostTools\studio_client.py
```

To inspect serial ports without opening them:

```powershell
.\.venv\Scripts\python.exe HostTools\capture_server.py --list-usb
```

The service normally binds only to `127.0.0.1`. For the optional Ethernet
path, configure the addresses in `BSP/Inc/gs_ethernet.h`, select Ethernet in
`BSP/Inc/gs_capture_config.h`, and explicitly launch the server with
`--bind 0.0.0.0` on a trusted network. USB and Ethernet firmware source are
both present; USB is the default.

The client observes live color frames without saving them. Recording saves
complete frames, including repeated or dark frames, as original data/PNG/AVI.
The model's suggestion and the recording intent do not certify training
quality. Save a session to history to retain it. Normal close and new-session
actions clear temporary data; saved history is retained.

The model, preprocessing bridge, browser UI, and third-party license
inventory are in `model/`, `web/`, and `licenses/`. `studio.spec` describes the
one-file build. The source build requires installed dependencies; the final
EXE's rebuild environment was removed from the private development tree after
delivery, so the exact binary reproduction is not asserted from this checkout.

No recording session or original image from the project owner's private
dataset is included. See [privacy](../PRIVACY.md).
