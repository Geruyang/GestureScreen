# 依赖、来源与许可证

## 最终版本（2026-09-26）

最终 Keil Target 使用 STM32Cube.AI 运行库和六类 int8 模型；模型及生成代码位于 `HostTools/model/` 与 `Middlewares/ST/AI/Generated/`，成果哈希见 `SHA256SUMS`。Gesture Studio 使用 PySide6、PyInstaller、pyserial、NumPy、LiteRT 和 Pillow，版本见 `HostTools/requirements-studio.txt`。下列日期章节保留依赖引入时的记录，不能当作最终集成状态。

## 2026-09-17 USB增量

- USB Device CDC使用同一STM32CubeF4 1.28.3中的 `Middlewares/ST/STM32_USB_Device_Library`，由CubeMX生成并集成；保留供应商源码、版权及原始LICENSE。自编协议与发送器位于Modules/UsbCapture、BSP，USB_DEVICE接入只改USER CODE。
- USB电脑接收依赖pyserial3.5（BSD-3-Clause），精确版本在 `HostTools/requirements-usb.txt`，本机安装于 `Build/usb-venv`；普通HTTP服务仍只依赖Python标准库。
- fireDAP脚本使用本机CubeIDE自带OpenOCD（工具标示GPLv2）和GNU GDB，不将工具二进制打包进固件。新固件、自编来源和与SDK一致的USB库哈希在 `Build/usb-validation/validation.json`。

## 2026-09-15 增量

- 新增同一CubeF4 1.28.3自带lwIP，编译源与SHA-256记录在 `Build/lwip-source-manifest.json`；供应商源码未修改，NO_SYS端口为项目自编。许可保留于Middlewares/Third_Party/LwIP。
- OV2640 QVGA表提取自同SDK `Drivers/BSP/Components/ov2640/ov2640.c` V1.0.2；源哈希写在`BSP/Inc/gs_ov2640_regs.h`，原许可保留于`BSP/ThirdParty/ov2640-LICENSE.txt`。
- 当时的电脑采集工具只依赖 Python 标准库；最终 Gesture Studio 的依赖见文首。

以下是2026-09-10原框架依赖记录；“本次”仅指该历史基线。

本工程使用本机已安装的 **STM32Cube FW F4 V1.28.3** 中的 HAL、CMSIS 和 FreeRTOS。当前使用的库源码已复制到工程目录；本次没有下载新 SDK、GUI 库、AI 运行库或模型权重。版本与关键文件 SHA-256 记录在 [third_party_manifest.json](third_party_manifest.json)，核对日期为 2026-09-10。

## 工具和固件包

| 项目 | 本次配置/版本 | 本地依据 |
|---|---|---|
| STM32CubeMX | 6.18.1，数据库 DB.6.0.181 | `GestureScreen.ioc` 的 `MxCube.Version`、`MxDb.Version` |
| Keil MDK / µVision | MDK 5.43；UV4 文件版本 5.43.1.0 | `D:/Keil5/UV4/UV4.exe` 文件版本 |
| Arm Compiler | 6.24，ARMCLANG | Keil 工程 `pCCUsed` 与 `Build/GestureScreen-GestureScreen-build.log` |
| STM32CubeF4 | V1.28.3；包发布说明日期 2025-07-23 | SDK `package.xml` 为基线 1.28.0 + 补丁 1.28.3；`Release_Notes.html` |
| SDK 安装目录 | `D:/STM32CubeMX/Repository/STM32Cube_FW_F4_V1.28.3` | `.ioc` 的 `ProjectManager.CustomerFirmwarePackage` |

现有 Keil 工程使用已复制的依赖源码构建。重新运行 CubeMX 生成或 `Tools/integrate.py` 时，需要本机对应 SDK；换电脑后先安装同版本并更新 `.ioc` 的软件包目录。MDK、CubeMX 与编译器本身未打包进源码，使用其本机安装及许可配置。

## 源码组件

| 组件 | 实际版本 | 版本依据 | 许可依据 |
|---|---|---|---|
| STM32F4 HAL | 1.8.5 | `stm32f4xx_hal.c` 的版本宏；SDK SBOM | BSD-3-Clause，见包许可清单及 HAL 的原始许可证指引 |
| CMSIS 包 | 5.9.0 | SDK `Release_Notes.html` 与 `sbom_cdx.json` | Apache-2.0 |
| CMSIS Core(M) | 宏版本 5.6；`cmsis_version.h` 文件自身版本 5.0.5 | 已复制的 `Drivers/CMSIS/Include/cmsis_version.h` | Apache-2.0；这三个版本号分别指软件包、Core 接口和文件，不能互相替代 |
| STM32F4 CMSIS Device | 2.6.11 | `stm32f4xx.h` 的版本宏；SDK SBOM | Apache-2.0，见 Device 的原始许可证指引 |
| FreeRTOS kernel | 10.3.1，SDK 标记 ST modified 20230818 | `task.h`、SDK 发布说明与 `st_readme.txt` | 内核 MIT；原文件中的各方版权继续保留 |
| CMSIS-RTOS2 FreeRTOS 适配层 | 本 SDK 随带版本；ST 说明其基础为 CMSIS-FreeRTOS 10.3.0 | `cmsis_os2.c`、SDK `st_readme.txt` 2020-07-20 条目 | Apache-2.0；不能将整个 FreeRTOS 文件夹都改标为 MIT |
| FreeRTOS CM4F port | 同一 10.3.1 SDK 的 `portable/GCC/ARM_CM4F` | `port.c`、`portmacro.h` 原文件哈希 | 文件自带 MIT 版权及许可说明 |

CubeMX 的旧 MDK 生成器选择 `RVDS/ARM_CM4F`，其中旧 Arm Compiler 5 汇编语法与当前 AC6 构建路径不匹配。`Tools/integrate.py` 在生成后，复制**同一已安装 SDK** 的 `GCC/ARM_CM4F/port.c` 和 `portmacro.h`，并将 Keil 工程源码及 include 路径改指这两个文件；二者与 SDK 原文件逐字节一致。此次只是更换内核端口选项，没有改写供应商内核源码，也没有混入另一套 FreeRTOS 版本。工程仍使用 Keil 5 与 AC6；目录名 `GCC` 表示该端口采用 GNU 风格汇编。

本次 Keil AC6.24 已完成框架构建，日志为 0 errors、0 warnings；这不等于外设、模型或所有库功能已经实板验收。清单中的九个关键源码文件哈希与 SDK 对应文件一致；这是精简的来源核对清单，不声称已逐文件审计整个 SDK。

## 随工程保留的许可资料

- [STM32CubeF4 包许可原文](Package_license.md)：原样复制。文档列出整个SDK组件；当前已引入USB CDC，TouchGFX、音频、FatFs等仍未集成。
- [HAL 原始许可证指引](Drivers/STM32F4xx_HAL_Driver/LICENSE.txt)：该 SDK 的文件自身为包许可/BSD-3-Clause 指引，保留原文。
- [CMSIS Apache-2.0 原文](Drivers/CMSIS/LICENSE.txt)：同时可供本工程的 CMSIS-RTOS2 Apache 文件查阅。
- [STM32F4 Device 原始许可证指引](Drivers/CMSIS/Device/ST/STM32F4xx/LICENSE.txt)。
- [FreeRTOS MIT 原文](Middlewares/Third_Party/FreeRTOS/Source/LICENSE)。
- [ST 对 FreeRTOS 的修改记录](Licenses/STM32CubeF4-FreeRTOS-st_readme.txt) 与 [固件包版本元数据](Licenses/STM32CubeF4-package.xml)：原样复制，保留版本与版权依据。

供应商源文件中的版权与 SPDX/许可声明原样保留。上述文件描述各自组件的原始许可，不为本项目自行编写的应用模块统一指定许可证；生成代码仍保留各文件自身的 ST 声明。

## 阅读实验内容（2026-09-22）

内置古文为公有领域原作，按简体正文分页，保留作者署名；不包含现代译文与校注。来源和原始正文同时记录于 `Assets/content/reader_source.json`：

- 陶渊明：[桃花源记](https://zh.wikisource.org/zh-hans/桃花源記)。
- 柳宗元：[小石潭记](https://zh.wikisource.org/zh-hans/至小丘西小石潭記)。
- 刘禹锡：[陋室铭](https://zh.wikisource.org/zh-hans/陋室銘)。

最终 Gesture Studio 的第三方许可清单见 `HostTools/licenses/README.md`；模型评估见 `Models/README.md`，固件产物和板端测速见 `firmware/README.md`。阅读器内容改造保持该模型实现不变。
