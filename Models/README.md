# Model artifacts and tools

The deployed model is the six-class MobileNetV1 0.25 × 96 RGB student. Its
TFLite form is `../HostTools/model/gesture_v12_int8.tflite`; the saved training
checkpoint is `../checkpoints/student-96rgb-best.pt`. The larger
`../checkpoints/teacher-224rgb-best.pt` is a retained teacher, not the model in
the firmware. See the root [README](../README.md) for exact validation results
and artifact hashes.

This folder contains training, preprocessing, quantization, and C export
tools. Some scripts describe or expect the original private dataset layout;
you must supply your own consented data and adjust paths. They do not make
the withheld dataset available. Training and binary reproduction were not
re-run while preparing this public checkout.

The original v12 private dataset has 2,671 images, with 1,960 for training,
361 for validation, and 350 unscored test images. The published best-run
validation score is 292/361; the three-seed mean is 77.65%. The teacher's
validation score is 336/361. These numbers do not establish on-board or
general-user accuracy. The dataset is private for the owner's privacy; see
[PRIVACY.md](../PRIVACY.md).
