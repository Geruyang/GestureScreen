# Contributing

Issues and pull requests are welcome. Please include the board revision,
camera/display variant, firmware or Studio version, steps to reproduce, and
the distinction between host tests and tests on real hardware.

Do not attach personal camera frames, private training data, access tokens,
device identifiers, or logs containing them to public issues. Use synthetic
test data where possible. Keep both USB and Ethernet capture paths working;
USB is the default, and Ethernet is selected in
`BSP/Inc/gs_capture_config.h`.

For firmware changes, preserve user code in CubeMX `USER CODE` sections and
run `Tools/integrate.py` after regeneration. For model claims, report the
dataset split and sample count and distinguish desktop validation from
on-board behavior.
