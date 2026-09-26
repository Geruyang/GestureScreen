# Retained checkpoints

- `student-96rgb-best.pt` is the source training checkpoint for the final six-class MobileNetV1 0.25 × 96 RGB model. The filename is historical: this model used supervised labels only, with no teacher outputs or knowledge distillation.
- `teacher-224rgb-best.pt` is a separate, larger research checkpoint. It was not used to train the deployed checkpoint and was not deployed.

For the final **deployed int8** model's validation and test accuracy and the exact offline scoring method, see [Models/README.md](../Models/README.md). The checkpoint files contain weights, not underlying camera frames. The owner-recorded dataset remains private.
