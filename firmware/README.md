# Final programmed firmware

`GestureScreen.hex` is the final reader selection build programmed on
2026-09-22 for the EmbedFire STM32F429IGT6 Challenger V1. The `.axf` and
`.map` files correspond to this **same** image; use them when interpreting
its RAM layout or debugging. Do not pair it with a different build's map.

The image includes the v12 six-class supervised model and defaults to native USB
capture. The Ethernet source remains in the project, selectable at build
time. Confirm board revision and target identity before programming the HEX.
The board's health passed a limited observation window; the 100 ms inference
target was not met. See the root README for validation boundaries.
