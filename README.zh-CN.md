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

源码开发可安装 `HostTools/requirements-studio.txt` 后运行 `python HostTools/studio_client.py`；`python HostTools/capture_server.py --list-usb` 只列端口，不打开设备。固件用 STM32CubeMX 6.18.1、STM32CubeF4 1.28.3、Keil MDK 5.43 / Arm Compiler 6.24。修改 `.ioc` 后还需运行 `python Tools/integrate.py`。默认 USB 采集；`BSP/Inc/gs_capture_config.h` 可切换到保留的以太网实现。

## 成果与边界

- 最佳已部署学生模型：MobileNetV1 0.25 × 96 RGB，私人验证集 **292/361 = 80.89%**；三种子平均 **77.65%**，不能称稳定达到 80%。
- 保留但未部署的教师模型：MobileNetV1 1.0 × 224 RGB，验证 **336/361 = 93.07%**。
- 数据总计 2,671 张，测试拆分未评分。上述验证结果不是普遍用户手势准确率，也不是实板准确率。
- 最终固件已烧录并通过有限窗口的板端健康检查；**100 ms 推理目标未达成**。编译、主机测试、健康、分类、持势和页面动作需分别看待。

**数据集由本人录制，包含个人隐私，因此不上传。** 仓库和发布附件均不含原始采集帧、录制会话、样本图像或标注数据；仅提供训练后的模型与工具。请用自己有授权的数据复现或适配。更多说明见 [PRIVACY.md](PRIVACY.md)。

原创部分采用 [MIT 许可证](LICENSE)。ST、Arm、Qt、字体等第三方文件继续遵循各自许可，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。欢迎按 [贡献说明](CONTRIBUTING.md) 提 issue 或 PR；如果项目有帮助，欢迎 Star，让其他 STM32 开发者更容易找到它。
