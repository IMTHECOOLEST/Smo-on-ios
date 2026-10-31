#!/usr/bin/env bash
# Report where nxnative handles controllers, HID vibration and six-axis (current nxnative
# does a DualSense's gyro and rumble itself: see the last section).
#   scripts/inspect_nxnative_input.sh /path/to/nxnative > report.md
set -euo pipefail
NX="${1:?usage: inspect_nxnative_input.sh <nxnative checkout>}"
cd "$NX"

section() {
  printf '\n## %s\n\n' "$1"
  printf 'pattern: `%s`\n\n```\n' "$2"
  git grep -n -I -E "$2" -- 'dm/ios' 'dm/host' 2>/dev/null | head -n 60 || true
  printf '```\n'
}

printf '# nxnative input integration report\n\ncommit: %s\n' "$(git rev-parse HEAD)"
section "GameController usage (iOS shell)"        'GCController|GCExtendedGamepad|GCDualSense|GCMotion'
section "HID vibration (Horizon hid service)"     'SendVibration|VibrationValue|vibration|rumble'
section "HID six-axis sensor"                     'SixAxis|six_axis|sixaxis'
section "Npad state writes (button mask, sticks)" 'NpadState|npad|Npad'
section "Existing haptics usage"                  'CoreHaptics|CHHaptic'
section "Built-in controller slots, motion and rumble" 'pad_slots|dm_motion_attach|dm_haptics_apple|GCDeviceHaptics|GCDualSense'
