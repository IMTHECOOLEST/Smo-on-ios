# DualSense layer

Status: **written, not yet wired in, and the Objective-C file has not been compiled by its author.** The `objc-syntax` CI job compiles it against the iOS SDK; treat a green run as the first real check.

## What is here

| File | What it does | Verified how |
| --- | --- | --- |
| `dm_ds_core.[ch]` | Pure C: DualSense buttons to Switch npad bits (Pro layout, position-based), stick scaling, HD-rumble to Core Haptics mapping | Unit tests (`tests/test_ds_core.c`) with sanitizers |
| `DMDualSense.[hm]` | GameController + Core Haptics glue: finds a DualSense, exposes polled state (buttons, sticks, gyro, accel), drives rumble on the left/right handle motors, sets the light bar | `objc-syntax` CI job only |

## What iOS already gives you

nxnative's README says a connected game controller hides the touch controls and keeps every button, so basic DualSense input should already work through GameController. This layer adds what that does not: **rumble, gyro, light bar.** Adaptive triggers and the touchpad are deliberately left out (the Switch has no equivalent).

## Wiring it in (the part that needs evidence)

Each run of the *Build IPA* workflow uploads `diagnostics/dualsense-integration-report.md`: a grep of the nxnative commit it built for controller code, HID vibration, six-axis and npad writes. Use it to place three hooks in nxnative's iOS shell and host:

1. At startup: `DMDualSenseStart();`
2. Where the host fills npad state each frame: `DMDualSenseGetState(&s)`, then use `s.buttons`, the four stick axes and (if the game reads six-axis) `s.accel` / `s.gyro`.
3. In the HID vibration handler: `DMDualSenseSetRumble(ampLow, freqLow, ampHigh, freqHigh);`

Add `DMDualSense.m` and `dm_ds_core.c` to the iOS target (XcodeGen config) and link `GameController` and `CoreHaptics`.

## To verify on a device

- **Gyro and accel units/axes** are passed through unconverted (G and rad/s, GameController axes). The host's six-axis state may expect different units or axis order.
- **Sharpness curve** (log scale over 40 to 1252 Hz) is a design choice, and the sharpness control is sent as an offset from the event's 0.5; check it feels right.
- **Button layout** is position-based (Cross to B, Circle to A). If nxnative already remaps GameController buttons, wire only rumble/gyro to avoid double mapping.
