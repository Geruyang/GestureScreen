# Final model and evaluation

The six-class final deployed model is MobileNetV1 0.25 × 96 RGB, trained with supervised labels. Its frozen int8 TFLite form is `../HostTools/model/gesture_v12_int8.tflite` (SHA-256 `9cc300884c79aed938dba492c7e5b536a1ab064b5f59c14d40c3628b7b7e4f4f`). Its source training checkpoint is `../checkpoints/final-96rgb-best.pt`.

| Frozen deployed int8 model | Correct / total | Top-1 accuracy |
| --- | ---: | ---: |
| Validation | 293 / 361 | 81.16% |
| Test | 294 / 350 | 84.00% |

The owner scored these private, source-isolated splits once after the final model had been frozen. Each RGB565 frame was checked against its private manifest SHA-256, passed through the bundled `HostTools/model/preprocess.dll` RGB565 → center 192 × 192 ROI → 96 × 96 RGB int8 pipeline, and classified by the pinned LiteRT 2.2.0 reference interpreter using the published TFLite file. All 711 evaluation frames passed the preprocessing quality check. The table counts the top-logit class against the private label for every frame. It does not apply confidence, margin, temporal hold, or UI action rules. The board's Cube.AI backend may differ numerically; no on-board accuracy study is claimed. The private images and per-frame predictions were not published.

Some captured hands appear small or ambiguous. They may lower this dataset score relative to some use conditions, but actual-use accuracy has not been measured systematically. Validation data was used during model selection, so the test result is the more relevant final split; neither result establishes accuracy across new people or settings.

The matching model and preprocessing used by Gesture Studio are in `../HostTools/model/`; final deployment scripts are in `../Tools/deploy_v12_*`. Recreating the original training or export requires the owner's private dataset and removed build intermediates. Use your own consented data. See [privacy](../PRIVACY.md) and [tool status](../Tools/README.md).
