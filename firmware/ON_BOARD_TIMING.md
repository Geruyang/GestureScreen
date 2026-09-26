# Final firmware on-board timing

The 2026-09-22 limited health window for the **final programmed firmware**
(`GestureScreen.hex`, SHA-256
`2a654ebc9243906abf8466266a79af1c5233e05d978654d0dcfa2ae3cbb9327f`)
contained 72 distinct, complete inference records. The private debug trace
was decoded with the matching AXF and timing layout; only aggregate timings
are published here.

| Stage, wall time per frame | Minimum | Median | 95th percentile | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Model inference | 153 ms | 158 ms | 176 ms | 182 ms |
| RGB565 preprocessing | 25 ms | 26 ms | 32 ms | 40 ms |

The inference interval is measured from inference begin to inference end. It
is separate from preprocessing, capture, temporal gesture holding, and page
updates. The finite window supports the observed **153–182 ms** inference
range; it does not establish a worst-case timing guarantee. The original
100 ms inference target was not met. These timings do not measure gesture
classification or user-action accuracy.
