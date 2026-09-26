# GestureScreen

**An offline gesture-controlled reader on STM32F429, with a Windows capture and review tool.**

GestureScreen combines an OV2640 camera, an 800 × 480 RGB display, an on-device six-class gesture model, a small classical-text reader, and Gesture Studio for USB/Ethernet frame capture. The firmware source, CubeMX and Keil projects, model artifacts, verification tools, and final firmware are available here. The [Windows executable is in Releases](https://github.com/Geruyang/GestureScreen/releases).

[简体中文说明](README.zh-CN.md) · [Downloads](https://github.com/Geruyang/GestureScreen/releases) · [Privacy](PRIVACY.md) · [Third-party licenses](THIRD_PARTY.md)

## What it does

| Gesture | Reader action |
| --- | --- |
| Point left | Next book, article, or page |
| Point right | Previous book, article, or page |
| V sign | Open the selection |
| Open palm | Go up one level |
| Fist | Return to the bookshelf |

The bookshelf highlights the selection; the table of contents uses a dark selection with white text. The display shows reader content, not the camera feed. The sample library contains three public-domain classical Chinese works across 15 text pages.

The model classes are `POINT_LEFT`, `POINT_RIGHT`, `FIST`, `PALM`, `V_SIGN`, and `UNKNOWN`. The application uses a 90% score threshold, 20% margin, 400 ms hold, and three frames for actions. `UNKNOWN` at 95% for 600 ms and four frames is a neutral reset; it is not a physical hand-withdrawal detector.

## Hardware and software

- **Board:** EmbedFire/野火 STM32F429IGT6 Challenger V1. This is not the ALIENTEK Apollo board.
- **Peripherals:** OV2640, 800 × 480 RGB display, 8 MiB SDRAM, 16 MiB W25Q128 flash; HSE 25 MHz and 168 MHz system clock.
- **Capture:** native USB CDC on the board's J38 connector by default. The Ethernet/lwIP path remains in source and can be selected in `BSP/Inc/gs_capture_config.h`.
- **Firmware tools:** STM32CubeMX 6.18.1 with STM32CubeF4 1.28.3, Keil MDK 5.43 / Arm Compiler 6.24. Local installation and licenses are required; the vendor IDEs are not included.
- **Studio:** Windows 11 x64 was tested. Windows 10 x64 is a support target, but was not tested on a physical Windows 10 machine.

## Download and run

1. Download `GestureStudio.exe` from [the latest release](https://github.com/Geruyang/GestureScreen/releases). It is a self-contained Windows executable; no Python installation is needed for normal use. Verify its SHA-256 against the release notes.
2. If you have the specified Challenger V1 hardware, use `firmware/GestureScreen.hex`. Verify your board revision, connections, and target identity before programming it. The matching `.axf` and `.map` are included for debugging this exact image.
3. Connect the board's native USB port. Do not confuse its CDC port with the fireDAP debug probe's virtual COM port. Gesture Studio creates an empty `captures` directory next to the executable on first run. Observing does not save images; recording does.
4. Save a session to history to keep it. Normal close or a new session clears temporary recordings, while saved history remains. Exports are uncleaned recordings and are **not** training-ready data.

For source use, install the dependencies in `HostTools/requirements-studio.txt` with Python 3.12, then run `python HostTools/studio_client.py`. `python HostTools/capture_server.py --list-usb` lists ports without opening one. See [HostTools](HostTools/README.md) for the development workflow.

## Source map

| Path | Purpose |
| --- | --- |
| `GestureScreen.ioc`, `MDK-ARM/GestureScreen.uvprojx` | Sole CubeMX configuration and Keil target |
| `App/`, `Modules/`, `BSP/` | Reader behavior, gesture decisions, capture, board integration |
| `Core/`, `Drivers/`, `Middlewares/`, `USB_DEVICE/` | Generated and vendor-supplied firmware dependencies |
| `Assets/content/` | Public-domain sample text and provenance |
| `HostTools/` | Gesture Studio, browser UI, USB/HTTP capture, bundled model and licenses |
| `Models/`, `checkpoints/` | Training/export tools and the retained student/teacher checkpoints |
| `firmware/` | The final HEX and matching debug artifacts |
| `Tools/`, `Tests/` | Build, integration, host verification, and debug helpers |

Build from the repository root with `./Tools/build.ps1 -UV4 <path-to-UV4.exe>`. A CubeMX regeneration also needs `python Tools/integrate.py` afterward. Tool defaults reflect the original Windows development environment, so pass your own installed tool paths. The 121 file paths referenced by the Keil project were checked in this public source tree. See [DEPENDENCIES.md](DEPENDENCIES.md) and [THIRD_PARTY.md](THIRD_PARTY.md) for component licenses.

## Model and verification status

The deployed student is MobileNetV1 0.25 × 96 RGB. On a private 361-image validation split it scored **292/361 (80.89%)** in its best run; the mean of three seeds was **77.65%**. The retained 1.0 × 224 RGB teacher scored **336/361 (93.07%)** and was **not deployed**. These are validation results, not measured accuracy for all users or on the board. The 350-image test split was not scored. The dataset totals 2,671 images and is withheld for privacy.

The final firmware was programmed and passed a limited on-board health window. Host builds and tests, on-board health, classification quality, gesture holding, and reader actions are different checks. The original 100 ms inference target was **not met**. The user's later gesture testing and Windows 10 physical-machine test are not claimed here.

| Artifact | SHA-256 |
| --- | --- |
| `firmware/GestureScreen.hex` | `2a654ebc9243906abf8466266a79af1c5233e05d978654d0dcfa2ae3cbb9327f` |
| `firmware/GestureScreen.axf` | `bdc9ccc2e146f41243b00b66cd271dcfcfee46b42df33dae48a80693c1fc35bc` |
| `checkpoints/student-96rgb-best.pt` | `72db45f37036530652ef07e19ad20e6ce94552027d0fc81a9987c074f6c5c4be` |
| `checkpoints/teacher-224rgb-best.pt` | `5b0356d957aec7155d5cd24c51d7267d411200017e7d20ab4705a2a57990756f` |

The Studio release executable's SHA-256 is `37b710f9588a1a96ff9d27ff65e353177b31f50aa582852c6e4f49a8574bea56`.

## Privacy, license, and contributions

The gesture dataset was **recorded by the project owner** and includes personal imagery. No dataset, raw capture, session, or test image is published. The model artifacts are supplied without that data; see [PRIVACY.md](PRIVACY.md).

The owner's original work is MIT licensed. Bundled ST, Arm, FreeRTOS, lwIP, Qt, font, and other third-party components retain their own terms; see [THIRD_PARTY.md](THIRD_PARTY.md). Issues and pull requests are welcome under [CONTRIBUTING.md](CONTRIBUTING.md). If this project helps your STM32 camera or gesture UI work, a Star helps others find it.
