#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "../dualsense/dm_ds_core.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

int main(void) {
    dm_ds_buttons b;

    /* Nothing pressed -> 0, NULL -> 0. */
    memset(&b, 0, sizeof b);
    CHECK(dm_ds_buttons_to_npad(&b) == 0);
    CHECK(dm_ds_buttons_to_npad(NULL) == 0);

    /* Each button sets exactly its own bit. */
    struct { size_t off; uint32_t bit; } map[] = {
        { offsetof(dm_ds_buttons, cross),      DM_NPAD_B },
        { offsetof(dm_ds_buttons, circle),     DM_NPAD_A },
        { offsetof(dm_ds_buttons, square),     DM_NPAD_Y },
        { offsetof(dm_ds_buttons, triangle),   DM_NPAD_X },
        { offsetof(dm_ds_buttons, l1),         DM_NPAD_L },
        { offsetof(dm_ds_buttons, r1),         DM_NPAD_R },
        { offsetof(dm_ds_buttons, l2),         DM_NPAD_ZL },
        { offsetof(dm_ds_buttons, r2),         DM_NPAD_ZR },
        { offsetof(dm_ds_buttons, l3),         DM_NPAD_STICKL },
        { offsetof(dm_ds_buttons, r3),         DM_NPAD_STICKR },
        { offsetof(dm_ds_buttons, options),    DM_NPAD_PLUS },
        { offsetof(dm_ds_buttons, create),     DM_NPAD_MINUS },
        { offsetof(dm_ds_buttons, dpad_up),    DM_NPAD_UP },
        { offsetof(dm_ds_buttons, dpad_down),  DM_NPAD_DOWN },
        { offsetof(dm_ds_buttons, dpad_left),  DM_NPAD_LEFT },
        { offsetof(dm_ds_buttons, dpad_right), DM_NPAD_RIGHT },
    };
    uint32_t seen = 0;
    for (size_t i = 0; i < sizeof map / sizeof map[0]; i++) {
        memset(&b, 0, sizeof b);
        *(bool *)((char *)&b + map[i].off) = true;
        CHECK(dm_ds_buttons_to_npad(&b) == map[i].bit);
        CHECK((seen & map[i].bit) == 0); /* no two buttons share a bit */
        seen |= map[i].bit;
    }
    CHECK(seen == 0xFFFFu); /* all 16 npad bits used exactly once */

    /* Known libnx bit positions. */
    CHECK(DM_NPAD_A == 1u && DM_NPAD_ZR == 0x200u && DM_NPAD_PLUS == 0x400u && DM_NPAD_DOWN == 0x8000u);

    /* Axes. */
    CHECK(dm_ds_axis_to_s32(0.0f) == 0);
    CHECK(dm_ds_axis_to_s32(1.0f) == 32767);
    CHECK(dm_ds_axis_to_s32(-1.0f) == -32767);
    CHECK(dm_ds_axis_to_s32(5.0f) == 32767);
    CHECK(dm_ds_axis_to_s32(-5.0f) == -32767);
    CHECK(dm_ds_axis_to_s32(NAN) == 0);
    CHECK(dm_ds_axis_to_s32(0.5f) == 16384);

    /* Rumble mapping. */
    float i, s, s_prev = -1.0f;
    dm_ds_rumble_to_haptic(0.75f, 160.0f, &i, &s);
    CHECK(fabsf(i - 0.75f) < 1e-6f);
    CHECK(s > 0.0f && s < 1.0f);
    dm_ds_rumble_to_haptic(2.0f, 40.0f, &i, &s);
    CHECK(i == 1.0f && s == 0.0f);
    dm_ds_rumble_to_haptic(-1.0f, 5000.0f, &i, &s);
    CHECK(i == 0.0f && s == 1.0f);
    dm_ds_rumble_to_haptic(NAN, NAN, &i, &s);
    CHECK(i == 0.0f && s == 0.0f);
    for (float f = 40.0f; f <= 1252.0f; f += 51.0f) { /* monotonic in frequency */
        dm_ds_rumble_to_haptic(1.0f, f, &i, &s);
        CHECK(s >= s_prev);
        s_prev = s;
    }
    dm_ds_rumble_to_haptic(0.5f, 100.0f, NULL, NULL); /* NULL outputs are tolerated */

    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("dm_ds_core: all tests passed\n");
    return 0;
}
