# Retained model checkpoints

- `student-96rgb-best.pt`: deployed MobileNetV1 0.25 × 96 RGB training
  checkpoint. Best validation run: 292/361 (80.89%); three-seed mean: 77.65%.
- `teacher-224rgb-best.pt`: MobileNetV1 1.0 × 224 RGB teacher checkpoint.
  Validation: 336/361 (93.07%). It was not deployed on the board.

The deployed int8 TFLite form is at `../HostTools/model/gesture_v12_int8.tflite`.
The training dataset was recorded by the owner and is withheld for privacy.
These checkpoint files contain weights, not the underlying camera frames.
The separate 350-image test split was not scored. See [PRIVACY.md](../PRIVACY.md).
