# 六类静态手势识别适配

生产固件只运行一次官方 STM32Cube.AI `gs_network`。固定输出顺序为
`POINT_LEFT, POINT_RIGHT, FIST, PALM, V_SIGN, UNKNOWN`；同一次输出的
Softmax 分数同时供仪表盘和页面动作状态机使用，不再运行旧五类展示模型。

输入为 96×96×3 NHWC int8，scale 1、zero point -128；输出有效 logits 为 6 个。
RGB565 中心 192×192 ROI 按位复制还原 RGB888，各通道做 2×2 `(sum+2)/4`
整数均值后减 128。亮度质量检查保留旧算法与阈值。
适配层从生成的 `gs_network.h` 读取输出缓冲尺寸、量化参数和对齐要求，并检查
批准的网络签名。目标手势仍使用 score≥0.90、margin≥0.20；UNKNOWN
不发页面动作。连续 UNKNOWN≥0.95、≥600 ms 且≥4 张新帧后允许下一次动作，
但其合并旧 OTHER/EMPTY，不证明物理撤手。推理总预算保持 1000 ms，29 个层结束回调负责心跳、让出和
可取消执行，中止结果不发布。

`GS_RECOGNITION_REQUESTED=1` 与 `GS_UNKNOWN_NEUTRAL_REARM=1` 表示用户授权
按稳定非目标区间重新允许页面动作，
`GS_MODEL_VALIDATED_FOR_BUSINESS=0` 表示尚未通过实板业务验收。模型契约 ready、
联调授权和正式验收是三个独立状态。

历史五类参考权重仍留在 `gs_static_weights.c` 供数值回归，`Tools/integrate.py`
明确不把它链接进生产固件。主机测试和 Keil 构建不能代替 Cortex-M4 时延、
用户五动作准确率、屏幕可读性或长期稳定验收。
