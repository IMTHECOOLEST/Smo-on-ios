/* GameController / Core Haptics glue for the DualSense on iOS.
 *
 * C API for the nxnative host. The host polls DMDualSenseGetState() for input
 * and calls DMDualSenseSetRumble() from its HID vibration handler. See
 * dualsense/README.md for how to wire it in. */
#ifndef DM_DUALSENSE_H
#define DM_DUALSENSE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t buttons;      /* DM_NPAD_* mask in the Switch Pro layout (dm_ds_core.h) */
    int32_t  left_x;       /* -32767..32767 */
    int32_t  left_y;       /* positive = up */
    int32_t  right_x;
    int32_t  right_y;
    float    accel[3];     /* gravitational units (G), GameController axes, unconverted */
    float    gyro[3];      /* radians per second, GameController axes, unconverted */
    bool     has_motion;
} DMDualSenseState;

/* Begin watching for controllers. Safe to call more than once. */
void DMDualSenseStart(void);

/* Stop vibration and forget the controller. */
void DMDualSenseStop(void);

/* True while a DualSense is connected. */
bool DMDualSenseIsConnected(void);

/* Fill *out from the connected DualSense. Returns false if none is connected. */
bool DMDualSenseGetState(DMDualSenseState *out);

/* Switch HD-rumble values: amplitude 0..1 and frequency in Hz for the low and
 * high bands. Low drives the left motor, high the right. */
void DMDualSenseSetRumble(float ampLow, float freqLow, float ampHigh, float freqHigh);

/* Light bar colour, components 0..1. */
void DMDualSenseSetLightbar(float r, float g, float b);

#ifdef __cplusplus
}
#endif
#endif /* DM_DUALSENSE_H */
