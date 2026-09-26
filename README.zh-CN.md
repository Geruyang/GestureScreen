# GestureScreen：STM32F429 离线手势阅读器

本项目在**野火 STM32F429IGT6 挑战者 V1** 上实现摄像头手势阅读器：OV2640 取图、板端六类手势识别、800 × 480 RGB 屏显示书架与公版古文，并提供 Windows 采集与审阅工具 Gesture Studio。仓库公开固件源码、CubeMX/Keil 工程、模型成果、工具源码、验证脚本及最终固件。可直接运行的 Windows 程序在 [Releases](https://github.com/Geruyang/GestureScreen/releases) 下载。

[English README](README.md) · [下载](https://github.com/Geruyang/GestureScreen/releases) · [隐私说明](PRIVACY.md) · [第三方许可](THIRD_PARTY.md)

## 手势操作

| 手势 | 动作 |
| --- | --- |
| 指左 | 下一本、下一篇或下一页 |
| 指右 | 上一本、上一篇或上一页 |
| V 字 | 进入选中内容 |
| 张掌 | 返回上一级 |
| 握拳 | 返回书架 |

六类标签为 `POINT_LEFT`、`POINT_RIGHT`、`FIST`、`PALM`、`V_SIGN`、`UNKNOWN`。页面操作门限为分数 90%、领先幅度 20%、持续 400 ms/3 帧；`UNKNOWN` 的 95%、600 ms/4 帧仅用于中性复位，不能等同真正撤手。屏幕显示阅读内容，不显示摄像头画面。示例内容为三篇公版古文，共 15 页。

## 下载与使用

1. 从 [Releases](https://github.com/Geruyang/GestureScreen/releases) 下载 `GestureStudio.exe`，核对发布说明中的 SHA-256。正常使用无需安装 Python。Windows 11 x64 已实测；Windows 10 x64 是支持目标，尚未实机验收。
2. 只有在板型和接线符合时才使用 `firmware/GestureScreen.hex`。仓库同时提供与该镜像对应的 AXF 和 map，方便调试。
3. 将开发板原生 USB（J38）连接电脑。原生 USB CDC 端口与 fireDAP 虚拟串口不是同一个端口。客户端首次运行会在 EXE 旁创建空 `captures`；观察不存图，录制会保存完整帧。
4. 录制后点击“保存到历史”才长期保留。正常关窗或新建会清理临时录制，已保存的历史保留。导出数据未清洗，`training_ready=false`，不能直接当作合格训练集。

Windows 上用 Python 3.12 安装 `HostTools/requirements-studio.txt` 后，可运行 `python HostTools/studio_client.py`；`python HostTools/capture_server.py --list-usb` 只列端口，不打开设备。源码构建步骤见 [HostTools 说明](HostTools/README.md)。固件使用 STM32CubeMX 6.18.1、STM32CubeF4 1.28.3、Keil MDK 5.43 / Arm Compiler 6.24，需自行安装并取得所需许可；从仓库根目录运行 `./Tools/build.ps1 -UV4 <UV4.exe 路径>`。修改 `.ioc` 后还需运行 `python Tools/integrate.py`。默认 USB 采集；`BSP/Inc/gs_capture_config.h` 可切换到保留的以太网实现。首次公开提交是最终交付快照，不包含私人开发过程的 Git 历史。[工具与测试说明](Tools/README.md) 标明哪些脚本需要私有数据或硬件。

## 源码导航

| 路径 | 用途 |
| --- | --- |
| `GestureScreen.ioc`、`MDK-ARM/GestureScreen.uvprojx` | 唯一 CubeMX 配置与 Keil Target |
| `App/`、`Modules/`、`BSP/` | 阅读器、手势决策、采集与板级实现 |
| `Core/`、`Drivers/`、`Middlewares/`、`USB_DEVICE/` | 生成代码与厂家依赖 |
| `Assets/content/` | 公版示例内容及来源 |
| `HostTools/` | Gesture Studio、USB/HTTP 采集与本地模型 |
| `Models/`、`checkpoints/` | 模型工具、最终训练检查点及未部署的研究检查点 |
| `firmware/` | 最终 HEX 与对应调试产物 |
| `Tools/`、`Tests/` | 构建、集成、验证与调试工具 |

## 成果与边界

- 最终部署模型为 MobileNetV1 0.25 × 96 RGB 六分类，**仅用人工标签监督训练，未使用教师输出或知识蒸馏**。训练检查点文件名中的 `student` 是历史命名，保留以便核对产物。冻结的部署版 int8 TFLite 模型在私人数据上离线评估：验证集 **293/361 = 81.16%**，测试集 **294/350 = 84.00%**。数据共 2,671 张；评分使用仓库中的 RGB565 预处理和 LiteRT 参考解释器，统计单帧最高分分类，不包含手势门限、持续时间和页面动作。[评估说明](Models/README.md) 给出边界。
- 部分样本的手势很小或含糊，可能拉低数据集分数；实际使用准确率尚无系统测量，不能据此声称更高的具体数值。另有一个较大但未部署的研究检查点。仓库保留的 Arm 来源五类参考权重也不是最终 Keil Target 中的六类模型，见[第三方来源](THIRD_PARTY.md)。
- 最终固件已烧录并通过有限窗口的板端健康检查；**100 ms 推理目标未达成**。编译、主机测试、健康、分类、持势和页面动作需分别看待。

| 成果文件 | SHA-256 |
| --- | --- |
| `firmware/GestureScreen.hex` | `2a654ebc9243906abf8466266a79af1c5233e05d978654d0dcfa2ae3cbb9327f` |
| `firmware/GestureScreen.axf` | `bdc9ccc2e146f41243b00b66cd271dcfcfee46b42df33dae48a80693c1fc35bc` |
| `HostTools/model/gesture_v12_int8.tflite` | `9cc300884c79aed938dba492c7e5b536a1ab064b5f59c14d40c3628b7b7e4f4f` |
| `checkpoints/student-96rgb-best.pt`（历史文件名） | `72db45f37036530652ef07e19ad20e6ce94552027d0fc81a9987c074f6c5c4be` |

完整清单见 [SHA256SUMS](SHA256SUMS)；发布版 `GestureStudio.exe` 的 SHA-256 为 `37b710f9588a1a96ff9d27ff65e353177b31f50aa582852c6e4f49a8574bea56`。

**数据集由本人录制，包含个人隐私，因此不上传。** 仓库和发布附件均不含原始采集帧、录制会话、样本图像或标注数据；仅提供训练后的模型与工具。请用自己有授权的数据复现或适配。更多说明见 [PRIVACY.md](PRIVACY.md)。

原创部分采用 [MIT 许可证](LICENSE)。ST、Arm、Qt、字体等第三方文件继续遵循各自许可，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。欢迎按 [贡献说明](CONTRIBUTING.md) 提 issue 或 PR；如果项目有帮助，欢迎 Star，让其他 STM32 开发者更容易找到它。
