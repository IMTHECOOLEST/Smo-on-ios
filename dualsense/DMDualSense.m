#import "DMDualSense.h"
#import "dm_ds_core.h"

#import <CoreHaptics/CoreHaptics.h>
#import <Foundation/Foundation.h>
#import <GameController/GameController.h>
#include <math.h>

#pragma mark - Haptic motor

@interface DMDSMotor : NSObject
@property (nonatomic, strong) CHHapticEngine *engine;
@property (nonatomic, strong) id<CHHapticAdvancedPatternPlayer> player;
@property (nonatomic) float lastIntensity;
@property (nonatomic) float lastSharpness;
@end

@implementation DMDSMotor
@end

#pragma mark - State

static GCController *gController;
static DMDSMotor *gLeft;
static DMDSMotor *gRight;

static NSObject *DMDSLock(void) {
    static NSObject *obj;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ obj = [NSObject new]; });
    return obj;
}

static dispatch_queue_t DMDSQueue(void) {
    static dispatch_queue_t q;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ q = dispatch_queue_create("dm.dualsense.haptics", DISPATCH_QUEUE_SERIAL); });
    return q;
}

#pragma mark - Haptics

static DMDSMotor *DMDSMakeMotor(GCDeviceHaptics *haptics, GCHapticsLocality locality) {
    if (![haptics.supportedLocalities containsObject:locality]) return nil;
    CHHapticEngine *engine = [haptics createEngineWithLocality:locality];
    if (!engine) return nil;
    NSError *error = nil;
    if (![engine startAndReturnError:&error]) return nil;

    DMDSMotor *motor = [DMDSMotor new];
    motor.engine = engine;
    engine.autoShutdownEnabled = NO;
    __weak DMDSMotor *weakMotor = motor;
    engine.resetHandler = ^{
        DMDSMotor *m = weakMotor;
        m.player = nil;
        m.lastIntensity = 0;
        NSError *e = nil;
        [m.engine startAndReturnError:&e];
    };
    engine.stoppedHandler = ^(CHHapticEngineStoppedReason reason) {
        DMDSMotor *m = weakMotor;
        m.player = nil;
        m.lastIntensity = 0;
    };
    return motor;
}

static void DMDSStopMotor(DMDSMotor *motor) {
    if (!motor) return;
    if (motor.player) {
        [motor.player stopAtTime:CHHapticTimeImmediate error:nil];
        motor.player = nil;
    }
    motor.lastIntensity = 0;
}

/* Drive one motor. Called on the haptics queue only. */
static void DMDSSetMotor(DMDSMotor *motor, float amp, float freqHz) {
    if (!motor || !motor.engine) return;

    float intensity = 0, sharpness = 0;
    dm_ds_rumble_to_haptic(amp, freqHz, &intensity, &sharpness);

    if (intensity < 0.005f) {
        DMDSStopMotor(motor);
        return;
    }
    if (motor.player &&
        fabsf(intensity - motor.lastIntensity) < 0.01f &&
        fabsf(sharpness - motor.lastSharpness) < 0.01f) {
        return; /* nothing meaningful changed; avoid flooding Core Haptics */
    }

    NSError *error = nil;
    if (!motor.player) {
        if (![motor.engine startAndReturnError:&error]) return;
        /* One long continuous event at full intensity, looped; the dynamic
         * parameters below scale it. Core Haptics events max out at 30 s. */
        CHHapticEvent *event = [[CHHapticEvent alloc]
            initWithEventType:CHHapticEventTypeHapticContinuous
                   parameters:@[
                       [[CHHapticEventParameter alloc] initWithParameterID:CHHapticEventParameterIDHapticIntensity value:1.0f],
                       [[CHHapticEventParameter alloc] initWithParameterID:CHHapticEventParameterIDHapticSharpness value:0.5f]
                   ]
                 relativeTime:0
                     duration:30.0];
        CHHapticPattern *pattern = [[CHHapticPattern alloc] initWithEvents:@[event] parameters:@[] error:&error];
        if (!pattern) return;
        id<CHHapticAdvancedPatternPlayer> player = [motor.engine createAdvancedPlayerWithPattern:pattern error:&error];
        if (!player) return;
        player.loopEnabled = YES;
        if (![player startAtTime:CHHapticTimeImmediate error:&error]) return;
        motor.player = player;
    }

    /* Intensity control scales the event (0..1). Sharpness control is added to
     * the event's 0.5, so send the offset from it. */
    CHHapticDynamicParameter *intensityParam =
        [[CHHapticDynamicParameter alloc] initWithParameterID:CHHapticDynamicParameterIDHapticIntensityControl
                                                        value:intensity
                                                 relativeTime:0];
    CHHapticDynamicParameter *sharpnessParam =
        [[CHHapticDynamicParameter alloc] initWithParameterID:CHHapticDynamicParameterIDHapticSharpnessControl
                                                        value:sharpness - 0.5f
                                                 relativeTime:0];
    if ([motor.player sendParameters:@[intensityParam, sharpnessParam] atTime:CHHapticTimeImmediate error:&error]) {
        motor.lastIntensity = intensity;
        motor.lastSharpness = sharpness;
    }
}

#pragma mark - Controller tracking

static GCController *DMDSFindDualSense(void) {
    for (GCController *c in GCController.controllers) {
        if ([c.extendedGamepad isKindOfClass:[GCDualSenseGamepad class]]) return c;
    }
    return nil;
}

static void DMDSDetach(void) {
    DMDSMotor *left = gLeft, *right = gRight;
    gController = nil;
    gLeft = nil;
    gRight = nil;
    dispatch_async(DMDSQueue(), ^{
        DMDSStopMotor(left);
        DMDSStopMotor(right);
    });
}

static void DMDSAttach(GCController *c) {
    gController = c;

    GCMotion *motion = c.motion;
    if (motion && motion.sensorsRequireManualActivation) motion.sensorsActive = YES;

    GCDeviceLight *light = c.light;
    if (light) light.color = [[GCColor alloc] initWithRed:1.0f green:0.15f blue:0.15f];

    GCDeviceHaptics *haptics = c.haptics;
    if (haptics) {
        gLeft = DMDSMakeMotor(haptics, GCHapticsLocalityLeftHandle);
        gRight = DMDSMakeMotor(haptics, GCHapticsLocalityRightHandle);
        if (!gLeft && !gRight) gLeft = DMDSMakeMotor(haptics, GCHapticsLocalityDefault); /* one combined motor */
    }
}

static void DMDSRefresh(void) {
    @synchronized (DMDSLock()) {
        GCController *found = DMDSFindDualSense();
        if (found == gController) return;
        if (gController) DMDSDetach();
        if (found) DMDSAttach(found);
    }
}

#pragma mark - Public API

void DMDualSenseStart(void) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
        [nc addObserverForName:GCControllerDidConnectNotification object:nil queue:nil
                    usingBlock:^(NSNotification *note) { DMDSRefresh(); }];
        [nc addObserverForName:GCControllerDidDisconnectNotification object:nil queue:nil
                    usingBlock:^(NSNotification *note) { DMDSRefresh(); }];
    });
    DMDSRefresh();
}

void DMDualSenseStop(void) {
    @synchronized (DMDSLock()) {
        if (gController) DMDSDetach();
    }
}

bool DMDualSenseIsConnected(void) {
    @synchronized (DMDSLock()) {
        return gController != nil;
    }
}

bool DMDualSenseGetState(DMDualSenseState *out) {
    if (!out) return false;
    GCController *c;
    @synchronized (DMDSLock()) { c = gController; }
    GCExtendedGamepad *g = c.extendedGamepad;
    if (!g) return false;

    dm_ds_buttons b;
    b.cross      = g.buttonA.pressed;
    b.circle     = g.buttonB.pressed;
    b.square     = g.buttonX.pressed;
    b.triangle   = g.buttonY.pressed;
    b.l1         = g.leftShoulder.pressed;
    b.r1         = g.rightShoulder.pressed;
    b.l2         = g.leftTrigger.pressed;
    b.r2         = g.rightTrigger.pressed;
    b.l3         = g.leftThumbstickButton.pressed;   /* nil-safe: reads NO if absent */
    b.r3         = g.rightThumbstickButton.pressed;
    b.options    = g.buttonMenu.pressed;             /* DualSense Options */
    b.create     = g.buttonOptions.pressed;          /* DualSense Create */
    b.dpad_up    = g.dpad.up.pressed;
    b.dpad_down  = g.dpad.down.pressed;
    b.dpad_left  = g.dpad.left.pressed;
    b.dpad_right = g.dpad.right.pressed;

    memset(out, 0, sizeof *out);
    out->buttons = dm_ds_buttons_to_npad(&b);
    out->left_x  = dm_ds_axis_to_s32(g.leftThumbstick.xAxis.value);
    out->left_y  = dm_ds_axis_to_s32(g.leftThumbstick.yAxis.value);
    out->right_x = dm_ds_axis_to_s32(g.rightThumbstick.xAxis.value);
    out->right_y = dm_ds_axis_to_s32(g.rightThumbstick.yAxis.value);

    GCMotion *m = c.motion;
    if (m) {
        GCAcceleration a = m.acceleration;
        if (m.hasGravityAndUserAcceleration) {
            a.x = m.gravity.x + m.userAcceleration.x;
            a.y = m.gravity.y + m.userAcceleration.y;
            a.z = m.gravity.z + m.userAcceleration.z;
        }
        out->accel[0] = (float)a.x;
        out->accel[1] = (float)a.y;
        out->accel[2] = (float)a.z;
        if (m.hasRotationRate) {
            GCRotationRate r = m.rotationRate;
            out->gyro[0] = (float)r.x;
            out->gyro[1] = (float)r.y;
            out->gyro[2] = (float)r.z;
        }
        out->has_motion = m.hasRotationRate || m.hasGravityAndUserAcceleration;
    }
    return true;
}

void DMDualSenseSetRumble(float ampLow, float freqLow, float ampHigh, float freqHigh) {
    DMDSMotor *left, *right;
    @synchronized (DMDSLock()) { left = gLeft; right = gRight; }
    if (!left && !right) return;
    dispatch_async(DMDSQueue(), ^{
        if (right) {
            DMDSSetMotor(left, ampLow, freqLow);
            DMDSSetMotor(right, ampHigh, freqHigh);
        } else {
            /* single combined motor: follow the stronger band */
            if (ampHigh > ampLow) DMDSSetMotor(left, ampHigh, freqHigh);
            else DMDSSetMotor(left, ampLow, freqLow);
        }
    });
}

void DMDualSenseSetLightbar(float r, float g, float b) {
    GCController *c;
    @synchronized (DMDSLock()) { c = gController; }
    GCDeviceLight *light = c.light;
    if (!light) return;
    float rr = fminf(fmaxf(isnan(r) ? 0 : r, 0), 1);
    float gg = fminf(fmaxf(isnan(g) ? 0 : g, 0), 1);
    float bb = fminf(fmaxf(isnan(b) ? 0 : b, 0), 1);
    light.color = [[GCColor alloc] initWithRed:rr green:gg blue:bb];
}
