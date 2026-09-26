# 公开预训练主干 → 本人采集 → 七类模型

## 当前实际完成状态（2026-09-15）

已在本机 **Python 3.12.14 / TensorFlow 2.16.1 / tf_keras 2.16.0** 成功加载原公开 SavedModel，实际提取 96×96×1 → 1×1×256 的 MobileNet 特征主干。主干含 218,400 个参数（包括 BatchNorm 非训练状态），原五类分类头和原训练包装器的随机翻转均被移除。原始资产及 MIT 许可仍保存在项目 `artifacts/model_audit/arm_openmv/`，未重写原文件。

公开预训练来自 [ArmDeveloperEcosystem 示例](https://github.com/ArmDeveloperEcosystem/ml-image-classification-example-for-openmv)，固定来源见项目 `research/a5-open-models/selection.md` 与 `artifacts/model_audit/arm_openmv/source_manifest.json`。原 Notebook 使用 Kaggle `imsparsh/gesture-recognition` 的图像，经作者重标约 14,000 张为五类；本轮复用作者已经训练的真实权重，**未重新下载该图像全集或重训原五类任务**。它不能直接识别本项目左右指向、V_SIGN 和真实 EMPTY；七类头须用准确标注的数据训练。左右滑动视频不等于静态左右指向，no-gesture 不等于无人手空场。

本轮没有本人数据和已验收七类权重。七类训练、微调、全 int8 导出、真实 Interpreter 执行已经用明确标记的临时合成夹具跑通；该测试只检查程序执行路径，所有临时权重已经销毁，未保留可被误接入固件的“演示模型”。

## 1. 环境

已创建的隔离解释器：

```powershell
$modelPython = '.\Build\model-training-venv\Scripts\python.exe'
```

重建可用任意 Python 3.12：

```powershell
python -m venv GestureScreen/Build/model-training-venv
& GestureScreen/Build/model-training-venv/Scripts/python.exe -m pip install -r GestureScreen/Models/requirements-training.txt
```

顶层版本固定在 `requirements-training.txt`；本机完整解析版本记录在 `validation/requirements-windows-py312.lock`。全局 Python 未安装这些训练依赖。旧 SavedModel 使用 `tf_keras` 加载，并在导入 TensorFlow 前设置 `TF_USE_LEGACY_KERAS=1`，不让 Keras 3 直接加载旧 SavedModel。模型训练头和 Dropout 显式设置整数随机 seed，规避该旧 Keras 路径对 Python 3.12 的默认随机 seed 不兼容。

## 2. 板端采集与数据清单

PC 接收端应保存未经 JPEG 压缩的完整 **320×240 RGB565** 原图，再输出 [dataset_manifest.example.json](dataset_manifest.example.json) 对应的清单。所有文件路径相对清单目录；清单外的路径被拒绝。

每张图必须记录：

| 字段 | 要求 |
|---|---|
| `file` / `sha256` | 原始二进制文件及真实文件 SHA-256 |
| `session` | 完整采集会话 ID；同一会话不能横跨 split |
| `label` | 固定顺序 `POINT_LEFT,POINT_RIGHT,FIST,PALM,V_SIGN,OTHER,EMPTY` 中一个 |
| `split` | `train`、`validation`、`calibration` 或 `test` |
| `sensor_profile` / `exposure_profile` | 传感器寄存器/曝光策略版本和采集状态 |
| `capture_ms` | 实际采集时间；非 PC 收包时间 |
| `width` / `height` | `320` / `240` |
| `stride_bytes` | 通常 `640`；允许带行填充，末行像素必须完整 |
| `byte_order` | `msb_first` 或 `lsb_first`，须用实际色条核对 |

`EMPTY` 必须来自人工确认无人手的真实图像。`OTHER` 收集模糊/非目标手势；不可将无法确定的标注自动变成 OTHER。保持不同距离、背景、光照和独立采集会话。一个连续视频的相邻帧不能随机分到训练与测试两边。

```powershell
# 采集早期：核对已有样本，不要求四个 split 都收齐七类。
& $modelPython GestureScreen/Models/dataset.py Captures/manifest.json --allow-incomplete --report Captures/audit.json
# 训练前：四个 split 必须各有七类；这只是完整性门槛，不代表样本量充足。
& $modelPython GestureScreen/Models/dataset.py Captures/manifest.json --report Captures/audit.json
```

检查项包括原图/张量哈希、全帧长度、正确标签、整会话隔离及重复帧。即使原图字节不同（如只改变 ROI 外像素），相同预处理张量也不能跨 split。PC 质量统计采用当前 C 调试门槛；训练脚本遇到质量失败先停止，要求复查曝光和样本，不能把黑屏作为 EMPTY。阈值尚待实物校准。

## 3. 七类微调及 int8 导出

```powershell
& $modelPython GestureScreen/Models/train.py Captures/manifest.json `
  --model-id ov2640-personal-v1 `
  --output GestureScreen/Build/models/personal-v1
```

流程：

1. 使用已下载的真实公开预训练主干，新建七类 1×1 Conv 分类头。
2. 冻结主干训练新头；可选择解冻最后若干层微调，BatchNorm 保持冻结。
3. 只对训练批次做水平翻转，并同步交换 LEFT/RIGHT；不继承源 Notebook 的无条件翻转。
4. 用 `validation` 选择最佳 epoch；若微调未改善 validation loss，恢复训练头阶段的最佳权重。
5. 量化代表集只从 `train` 选取；`calibration` 留给后续拒识/时间状态机阈值校准。
6. 强制 `TFLITE_BUILTINS_INT8`，读回实际 I/O 类型、形状、scale/zero_point。固定输入必须满足 scale=1、zero_point=-128；不满足时保存真实训练报告并拒绝候选包，不能涂改导出量化值。
7. 最后才使用封存 `test`，输出七类混淆矩阵。离线分类准确率不能代表完整时间状态机或本人实机体验。

候选输出包括 `saved_model/`、`gesture_seven.int8.tflite`、`training_report.json`、`tflite_audit.json`、`candidate_contract.json`、`gs_model_metadata_candidate.h` 和自动生成的 `c_backend/`。默认公开预训练资产的 MIT 许可也保留在输出中。输出目录必须为空，避免覆盖旧实验。所有候选均为 `validated_for_business=false/0`。

只检查实际模型也可运行：

```powershell
& $modelPython GestureScreen/Models/model_package.py path/to/model.tflite --report model-audit.json
```

原五类模型实际审计在 `validation/source_five_class_audit.json`；其七类契约检查按预期失败。

## 4. 自包含 C int8 后端与 Keil 安装

`Modules/Vision/Src/gs_ai_int8_backend.c` 是可编译的标量整数执行器，无堆、HAL、ISR 或第三方 AI 运行库依赖。`export_c.py` 读取真实 TFLite 图、权重、偏置和量化参数，生成 `gs_model_weights.c/.h`、逐通道定点乘数/移位及候选元数据。支持 batch1 NHWC Conv2D、depth_multiplier=1 的 DepthwiseConv2D、AveragePool2D、零拷贝 reshape；支持 SAME/VALID 和 NONE/RELU/RELU6。未知算子、分支、扩张卷积、可变/稀疏张量及不匹配量化明确拒绝。导出时计算累加器和左移的保守溢出上界。

```powershell
# train.py 自动生成 c_backend/；也可单独导出真实七类TFLite。
& $modelPython GestureScreen/Models/export_c.py path/to/model.tflite --output path/to/c_backend --model-id personal-v1
# 校验生成文件SHA后安装到Modules/Vision，并自动调用现有integrate.py。
& $modelPython GestureScreen/Models/install_model.py path/to/c_backend
# 也可在train.py或export_c.py末尾加--install，完成导出后自动安装。
```

稳定板级入口是 `gs_model_selected_backend()`。默认选择器返回 NULL；安装器把权重复制到 `Modules/Vision/Src/gs_model_weights.c`，把权重/候选头复制到 `Inc/`，再将选择器切到 `gs_model_candidate_backend()`。`gs_port_model_backend()` 调用稳定入口；重新生成工程时权重属于自定义目录，`integrate.py` 自动纳入 Keil 分组。安装记录/许可在 `Models/Active/`，覆盖前的源码副本在 `Build/model-selection-backup/`。

回调为 `gs_int8_backend_infer()`，输入 9216 个 int8，输出完整 7 个 int8。双槽工作区独占，不在 ISR 推理。安装器不更改候选 `validated_for_business=0`，`gs_ai_init()` 仍拒绝未验收候选；生成文件哈希只核对产物完整性，不证明标签真实或识别准确。原五类仅能用 `--reference-five-class` 导出数值诊断入口，不生成业务后端，也不能安装。

原五类真实权重的资源证据：工作区 **73,728 B**，加输入 9,216 B 共 **81 KiB**；C 常量数组 233,405 B。AC6.24/Cortex-M4 独立编译后，权重对象 RO=234,949 B、ZI=73,728 B；执行器对象 Code=1,232 B、RO=16 B。它们是独立对象结果，完整固件仍包括调用者和编译器辅助函数，最终以 Keil map 为准。

标量后端已经通过数值对照与 AC6 编译，**未测 F429 时延，不能保证120ms / 连续5fps目标**。若实测不达标，可用 ST Edge AI/Cube.AI 或 CMSIS-NN 优化，当前已无需等待这些工具即可获得可编译推理源码。现有 Sign2Voice 的另一套 RGB64×64/float/五类生成接口不复用。

## 5. 真实模型发布验收

至少 50 张真实原图对照 PC/C 张量；实板核对性能、拒识、EMPTY 撤手和完整 GUI 事件后，才发布通过验收的后端。候选头中的 `0U` 是有意保留的发布门槛；本工具没有将它自动设为 1 的参数。

还须按最终 Keil map 核对模型320KiB / 新增运行库160KiB / 全AI RAM112KiB预算，测量真实新帧率和GUI并发性能。原五类与临时七类夹具不代表真实七类权重已训练或本人实机体验达标。

## 验证证据与边界

```powershell
# MSVC 编译实际 C 预处理为临时 DLL；运行 7 项工具测试。
GestureScreen/Models/test.ps1
# 原五类真实权重：生成C、MSVC编译并比较50个整数数值向量。
GestureScreen/Models/test_c_backend.ps1
# 在隔离 TensorFlow 环境验证训练→微调→导出→推理程序；合成权重随后销毁。
& $modelPython GestureScreen/Models/tests/smoke_training.py
```

- `test.ps1`：7 项通过，含 50 帧合成输入与实际 C 的逐字节对照，两种字节序和多种 stride；全部质量统计一致。**不是 50 张真实相机验收。**
- `validation/training_smoke.json`：真实公开主干成功加载，临时七类训练/微调/全 int8 与C导出软件路径通过；输入 `[1,96,96,1]`、输出 `[1,7]`，张量类型仅 int8/int32。
- `validation/c_backend_numeric.json` / `c_backend_seven_fixture.json`：真实五类与临时七类分别50个数值向量，对照 TFLite `BUILTIN_REF` 最大 int8 误差均为0；过小工作区拒绝，未验收候选的 `gs_ai_init()` 也实际拒绝。七类生成源码/执行器通过 AC6.24/C99/Cortex-M4 的 `-Wall -Wextra -Werror` 编译。
- TensorFlow 旧 API deprecation 和 converter 的 `quantized input statistics expected` / ignored option 警告保留在 Build 日志。该测试实际回读 I/O 量化满足契约，不能把警告忽略后推断所有其他模型也会通过。
- 没有真实七类数据训练结果、携带真实七类权重的完整固件链接结果或板端推理时延。

实现参考：[TensorFlow 迁移学习说明](https://www.tensorflow.org/guide/keras/transfer_learning)、[全整数量化说明](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_integer_quant)。这些是 API 使用依据，项目验证以本地日志和产物为准。
