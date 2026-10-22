#include "dm_ds_core.h"

#include <math.h>

#define DM_DS_FREQ_MIN 40.0f
#define DM_DS_FREQ_MAX 1252.0f

static float clamp01(float v) {
    if (isnan(v)) return 0.0f;
    if (v < 0.0f) return 0.0f;
    if (v > 1.0f) return 1.0f;
    return v;
}

uint32_t dm_ds_buttons_to_npad(const dm_ds_buttons *b) {
    uint32_t m = 0;
    if (!b) return 0;
    if (b->cross)      m |= DM_NPAD_B;
    if (b->circle)     m |= DM_NPAD_A;
    if (b->square)     m |= DM_NPAD_Y;
    if (b->triangle)   m |= DM_NPAD_X;
    if (b->l1)         m |= DM_NPAD_L;
    if (b->r1)         m |= DM_NPAD_R;
    if (b->l2)         m |= DM_NPAD_ZL;
    if (b->r2)         m |= DM_NPAD_ZR;
    if (b->l3)         m |= DM_NPAD_STICKL;
    if (b->r3)         m |= DM_NPAD_STICKR;
    if (b->options)    m |= DM_NPAD_PLUS;
    if (b->create)     m |= DM_NPAD_MINUS;
    if (b->dpad_up)    m |= DM_NPAD_UP;
    if (b->dpad_down)  m |= DM_NPAD_DOWN;
    if (b->dpad_left)  m |= DM_NPAD_LEFT;
    if (b->dpad_right) m |= DM_NPAD_RIGHT;
    return m;
}

int32_t dm_ds_axis_to_s32(float v) {
    if (isnan(v)) return 0;
    if (v > 1.0f) v = 1.0f;
    if (v < -1.0f) v = -1.0f;
    return (int32_t)lrintf(v * 32767.0f);
}

void dm_ds_rumble_to_haptic(float amp, float freq_hz, float *intensity, float *sharpness) {
    float f = isnan(freq_hz) ? DM_DS_FREQ_MIN : freq_hz;
    if (f < DM_DS_FREQ_MIN) f = DM_DS_FREQ_MIN;
    if (f > DM_DS_FREQ_MAX) f = DM_DS_FREQ_MAX;
    if (intensity) *intensity = clamp01(amp);
    if (sharpness) *sharpness = clamp01(log2f(f / DM_DS_FREQ_MIN) / log2f(DM_DS_FREQ_MAX / DM_DS_FREQ_MIN));
}
