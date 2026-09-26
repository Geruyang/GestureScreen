# Licensing scope and third-party notices

The root [MIT license](LICENSE) covers the project owner's original code,
documentation, and trained artifacts to the extent the owner holds those
rights. It does **not** relicense third-party files. Keep each component's
original copyright and license notices when copying or redistributing it.

| Component | Location | License/notice |
| --- | --- | --- |
| STM32F4 HAL, CMSIS, FreeRTOS, lwIP, STM32 USB Device library and STM32Cube.AI generated/runtime components | `Drivers/`, `Middlewares/`, `USB_DEVICE/`, generated files | `Package_license.md`, `DEPENDENCIES.md`, and licenses beside each component. Some ST components have hardware-specific terms. |
| Noto Sans SC font and generated glyph subset | `Assets/fonts/`, `Modules/Ui/Inc/` | SIL Open Font License 1.1 in `Assets/fonts/OFL.txt`. |
| Gesture Studio's bundled Python, Qt, Chromium, LiteRT and other dependencies | Source manifests and Windows release executable | `HostTools/licenses/README.md` and the files in that directory; original notices are included in the executable. |
| Three classical Chinese texts | `Assets/content/` | Public-domain original works, credited in `DEPENDENCIES.md` and `Assets/content/reader_source.json`. |

The Windows executable is built with PyInstaller and bundles third-party
libraries under their own terms. Its included license inventory gives source
locations and notices. This table is a navigation aid, not a replacement for
the actual license texts.
