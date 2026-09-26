# GestureScreen v1.0.1

This release keeps the validated firmware and Gesture Studio executable from
v1.0.0, and narrows the public source to the final deployed model and its
relevant tools. The undeployed research and five-class reference weights have
been removed from the current source tree.

## Download

- `GestureStudio.exe`: self-contained Windows x64 application. Windows 11 was
  tested; Windows 10 remains an untested support target. SHA-256:
  `37b710f9588a1a96ff9d27ff65e353177b31f50aa582852c6e4f49a8574bea56`.
- The final firmware HEX with matching AXF/map, the six-class checkpoint, and
  source are in this tag. See `SHA256SUMS` for file hashes.

## Final model and measured speed

The six-class MobileNetV1 0.25 × 96 RGB model was trained with supervised
labels. The frozen deployed int8 TFLite model scored **293/361 (81.16%)** on
the owner's private validation split and **294/350 (84.00%)** on the private
test split in offline top-1 classification.

With this final firmware on the STM32F429 board, **72 complete inferences took
153–182 ms each** in wall time (median **158 ms**, 95th percentile **176 ms**).
Image preprocessing took another **25–40 ms**. The original 100 ms inference
target was not met. These finite-window timings are not a measurement of
gesture-action accuracy.

## Privacy and license

The dataset was recorded by the owner and contains personal imagery. No
dataset, raw frames, recording sessions, sample images, or annotations are
published. Original project work is MIT licensed; bundled third-party files
retain their own licenses. See `PRIVACY.md` and `THIRD_PARTY.md`.
