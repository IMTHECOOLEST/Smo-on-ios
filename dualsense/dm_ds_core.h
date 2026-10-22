/* Pure-C DualSense -> Switch (Horizon npad) mapping. No Apple headers, so it
 * is unit-tested on any machine (tests/test_ds_core.c). */
#ifndef DM_DS_CORE_H
#define DM_DS_CORE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Switch npad button bits (libnx HidNpadButton layout). */
enum {
    DM_NPAD_A      = 1u << 0,
    DM_NPAD_B      = 1u << 1,
    DM_NPAD_X      = 1u << 2,
    DM_NPAD_Y      = 1u << 3,
    DM_NPAD_STICKL = 1u << 4,
    DM_NPAD_STICKR = 1u << 5,
    DM_NPAD_L      = 1u << 6,
    DM_NPAD_R      = 1u << 7,
    DM_NPAD_ZL     = 1u << 8,
    DM_NPAD_ZR     = 1u << 9,
    DM_NPAD_PLUS   = 1u << 10,
    DM_NPAD_MINUS  = 1u << 11,
    DM_NPAD_LEFT   = 1u << 12,
    DM_NPAD_UP     = 1u << 13,
    DM_NPAD_RIGHT  = 1u << 14,
    DM_NPAD_DOWN   = 1u << 15
};

/* Physical DualSense inputs, named by their position on the pad. */
typedef struct {
    bool cross, circle, square, triangle; /* bottom, right, left, top */
    bool l1, r1, l2, r2, l3, r3;
    bool options, create;
    bool dpad_up, dpad_down, dpad_left, dpad_right;
} dm_ds_buttons;

/* Position-based mapping to the Switch Pro layout:
 *   cross(bottom)->B  circle(right)->A  square(left)->Y  triangle(top)->X
 *   L1/R1->L/R  L2/R2->ZL/ZR  L3/R3->stick clicks  Options->+  Create->-  */
uint32_t dm_ds_buttons_to_npad(const dm_ds_buttons *b);

/* Stick axis in [-1, 1] -> Switch range [-32767, 32767]. Clamps; NaN -> 0. */
int32_t dm_ds_axis_to_s32(float v);

/* Switch HD-rumble band (amplitude 0..1, frequency in Hz) -> Core Haptics
 * intensity and sharpness, both 0..1. The frequency curve is a design choice
 * (log scale over 40..1252 Hz), not a platform spec. */
void dm_ds_rumble_to_haptic(float amp, float freq_hz, float *intensity, float *sharpness);

#ifdef __cplusplus
}
#endif
#endif /* DM_DS_CORE_H */
