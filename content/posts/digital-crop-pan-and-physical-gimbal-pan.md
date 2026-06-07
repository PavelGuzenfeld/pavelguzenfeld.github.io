---
title: "Two Pans, One Stick: Blending a Digital Crop Pan with a Physical Gimbal"
date: 2026-06-07
draft: false
tags:
- video-processing
- IMU
- embedded
- Python
- GStreamer
- drones
keywords:
- digital pan vs optical pan
- crop window pan zoom sensor
- gimbal handoff control law
- IMU stabilization camera pan
- electronic image stabilization crop
- proportional gimbal slew deadband
cover:
  image: /images/posts/digital-and-physical-pan.svg
  alt: A cropped sensor view handing pan authority off to a physical gimbal
categories:
- deep-dive
summary: A long-range zoom camera pans two ways at once — by sliding a crop window
  across the sensor, and by physically rotating the gimbal underneath it. Here's how
  to make one joystick drive both so the operator never feels the seam, the maths of
  the handoff, and the per-axis bug that kept the gimbal rolling after the stick let go.
ShowToc: true
audio:
  pronunciation:
    FOV: F O V
    IMU: I M U
    px: pixels
    yaw: yaw
    deg: degrees
---

Point a high-resolution camera at a distant scene and ask an operator to "look slightly left," and you have two completely different ways to honour the request. You can move the **picture** — slide the cropped window the operator actually sees across the larger sensor frame, no moving parts, instant. Or you can move the **camera** — physically rotate the gimbal so the lens points somewhere new.

The first is cheap, fast, and runs out of room almost immediately. The second is slow, mechanical, and effectively unlimited. A good zoom camera uses both, and the whole trick is making them feel like a single, continuous motion under one stick. This post is about the control law that does that, and the small, nasty bug that lives in the seam between the two.

## The picture inside the picture

Start with the part that has no moving parts. The sensor delivers a big frame — say 4000×3000 px — but the operator's screen only shows a 1280×800 window into it. Zoom and pan are both just *which rectangle of the sensor we crop and rescale to the screen*:

- **Zoom** = how big the crop is. A smaller crop covers fewer sensor pixels, rescaled up to fill the same screen → things look bigger.
- **Pan** = where the crop is centred. Slide it left, and the framed scene slides right.

A minimal model is two vectors — a frame size and a crop, described by its centre and half-size:

```python
class Vec2:
    def __init__(self, x, y): self.x, self.y = float(x), float(y)
    def __add__(self, o):     return Vec2(self.x + o.x, self.y + o.y)
    def __sub__(self, o):     return Vec2(self.x - o.x, self.y - o.y)
    def __mul__(self, s):     return Vec2(self.x * s,   self.y * s)


class CropWindow:
    """A zoomable, pannable view into a large sensor frame."""
    def __init__(self, frame_w, frame_h):
        self.frame  = Vec2(frame_w, frame_h)
        self.center = self.frame * 0.5      # crop centre, in sensor pixels
        self.half   = self.frame * 0.5      # half the crop size; zoom shrinks this

    def set_zoom(self, factor):             # factor >= 1
        self.half = (self.frame * 0.5) * (1.0 / factor)

    def pan(self, delta):
        self.center = self.center + delta
        self._clamp()

    def _clamp(self):
        # the crop must stay fully inside the sensor, or we'd show black margins
        self.center.x = min(max(self.center.x, self.half.x), self.frame.x - self.half.x)
        self.center.y = min(max(self.center.y, self.half.y), self.frame.y - self.half.y)
```

This is **digital pan** — also called electronic or crop pan. It's a pure read-offset into a buffer, so it's free and instantaneous. The rescale to screen happens every frame anyway; panning just changes the source rectangle.

The catch is in `_clamp()`. At full zoom-out, the crop *is* the whole frame: `half == frame * 0.5`, and the clamp pins the centre dead-centre — there's nowhere to pan to. The room to digitally pan only opens up as you zoom in, and it's exactly the slack between the crop edge and the sensor edge:

```
zoomed in (room to pan)              zoomed out (no room)
┌──────────────────────────┐        ┌──────────────────────────┐
│  sensor frame            │        │ ┌──────────────────────┐ │
│   ┌────────────┐         │        │ │   crop == frame      │ │
│   │   crop     │ ← slack →│        │ │                      │ │
│   └────────────┘         │        │ └──────────────────────┘ │
└──────────────────────────┘        └──────────────────────────┘
```

So digital pan has a hard wall: you can only slide the crop until its edge meets the sensor edge. Push past that and you'd be cropping pixels that don't exist — black. That wall is where the second pan has to take over.

## When the picture runs out, move the camera

The **physical pan** is the gimbal: a motor that yaws (and sometimes pitches) the whole optical assembly. It has no edge — it can rotate as far as its mechanics allow — but it's heavy, slow to accelerate, and every motion is visible as a sweep. You do not want to drive it directly from the stick; a flick of the operator's thumb would whip the camera around and overshoot.

The model that works is what I think of as **head and body**:

- The **head** is the crop window. It's weightless. It moves the instant the stick moves, soaking up the operator's intent with zero lag — but only within its small range of motion (the slack above).
- The **body** is the gimbal. It's slow and powerful. It follows the head, but only when the head has strained as far as it can and is asking to go further.

Turn your head to look left and your eyes lead; your neck only rotates once your eyes hit the corner. Same idea. The head buys the responsiveness; the body buys the range.

### Measuring the strain

The body needs one number: *how hard is the head pushing against its limit?* I call it the **overshoot** — how far the *requested* view pokes past the no-black region, per axis, normalised so the control law is zoom-independent.

The requested centre is allowed to wander past the sensor edge (the operator is still pushing the stick); the **displayed** crop is that request clamped back to legal pixels. The gap between them is the overshoot:

```python
class PanController:
    def __init__(self, frame_w, frame_h):
        self.frame = Vec2(frame_w, frame_h)
        self.cmd   = self.frame * 0.5    # where the operator WANTS to look (may exceed frame)
        self.half  = self.frame * 0.5    # half crop size; set by zoom

    def displayed_center(self):
        c = Vec2(self.cmd.x, self.cmd.y)
        c.x = min(max(c.x, self.half.x), self.frame.x - self.half.x)
        c.y = min(max(c.y, self.half.y), self.frame.y - self.half.y)
        return c

    def overshoot(self):
        """Signed distance the request pokes past the in-frame region, per axis,
        normalised to the frame half-size. Zero while the crop is fully visible."""
        def axis(c, half, size):
            lo, hi = half, size - half
            if c < lo: return c - lo     # poking past the low edge
            if c > hi: return c - hi     # poking past the high edge
            return 0.0
        ox = axis(self.cmd.x, self.half.x, self.frame.x)
        oy = axis(self.cmd.y, self.half.y, self.frame.y)
        return Vec2(ox / (self.frame.x * 0.5), oy / (self.frame.y * 0.5))
```

Three properties make this the right signal to feed a motor:

1. **It's zero while there's no black to fix.** No strain → no gimbal motion. The body stays still as long as the head can do the job alone.
2. **It's proportional.** A lot of black → a big number → fast slew. As the gimbal brings the scene in, the black shrinks, the number shrinks, and the slew *decelerates on its own*. No separate ramp-down logic — the geometry is the ramp.
3. **It hits zero exactly when the view is whole again.** The body stops with no leftover black margin, at any zoom level, because the threshold is computed from the current crop half-size rather than a fixed dead-zone.

### Don't twitch — dwell first

Overshoot alone would make the gimbal flinch at every brief stick tap. Gate it behind a short **dwell**: only engage the body once the head has been pinned against its limit *continuously* for some time. A quick flick recenters before the timer fires and the gimbal never moves; a sustained push commits.

```python
def physical_command(self, now, dwell_s=0.2):
    gap = self.overshoot()

    # The gimbal here yaws on one axis only (horizontal). Vertical strain can't be
    # closed mechanically, so we never command it — otherwise it would chase a gap
    # it can never shrink and never stop.
    gx, gy = gap.x, 0.0
    straining = gx != 0.0 or gy != 0.0

    if not straining:
        self._strain_start = None
    elif self._strain_start is None:
        self._strain_start = now

    dwell_met = self._strain_start is not None and (now - self._strain_start) >= dwell_s
    return Vec2(gx, gy) if dwell_met else Vec2(0.0, 0.0)
```

Note the asymmetry in the comment: a single-axis gimbal can only ever close *one* axis of overshoot. If you naively fed it both, the axis it can't move would report a permanent non-zero gap and the controller would never reach its "done" state. Command only what the hardware can actually fix.

## The handoff: where the two pans become one

So far the head leads and the body follows. But if both keep their positions, you'd end up double-counted: the gimbal rotates left *and* the crop is still offset left, so the framed scene has lurched twice as far as the operator asked.

The reconciler is the **IMU**. As the gimbal yaws, an inertial measurement unit reports exactly how far the camera rotated. Stabilization uses that to keep the framed point fixed in space — by sliding the requested centre back *opposite* to the measured motion:

```python
def apply_stabilization(self, world_shift):
    # world_shift = how far the framed scene moved (in sensor px) due to platform/gimbal motion.
    # Push the request the other way so the same real-world point stays under the crosshair.
    self.cmd = self.cmd + world_shift
```

Now watch the full loop close. The operator holds left:

1. Head slides left to its limit → overshoot appears.
2. After the dwell, the body starts yawing left, proportional to the overshoot.
3. As the camera yaws, the IMU sees the world sweep right; stabilization pushes `cmd` back toward centre.
4. `cmd` recentering shrinks the overshoot → the body slows.
5. When `cmd` is back inside the in-frame region, overshoot is zero, the body stops — and the gimbal is now physically pointing where the operator wanted, with the crop neatly recentred and ready to digitally pan again.

The operator felt one smooth, unbounded pan. Under the hood, authority slid from a weightless crop to a heavy motor and back, and the seam never showed.

```
stick held left
   │
   ▼
 head crop ──strains──▶ overshoot ──dwell──▶ gimbal yaw (∝ overshoot)
   ▲                                              │
   │                                              ▼
   └────────── IMU stabilization ◀──── camera actually rotated
              (recenters the crop, winds the overshoot to zero)
```

## The bug in the seam: pan one axis, the other won't let go

Here's the part that cost me an afternoon, and it lives entirely in the interaction between "hold the crop steady while panning" and "two axes share one controller."

While the operator is *actively* panning, you want to **suppress stabilization** — the IMU correction would fight the deliberate motion and make the pan feel mushy. So the natural guard is: *if a pan happened recently, don't stabilize.* A single timestamp, refreshed on any stick motion:

```python
# The tempting, wrong version — ONE timer for BOTH axes.
PAN_TIMEOUT = 0.10

def on_stick(self, dx, dy, now):
    if dx != 0 or dy != 0:
        self._last_pan_time = now      # any motion, either axis, refreshes it
    self.cmd = self.cmd + Vec2(dx, dy)

def per_frame(self, now, imu_shift):
    pan_active = (now - self._last_pan_time) < PAN_TIMEOUT
    if not pan_active:
        self.apply_stabilization(imu_shift)   # ← stabilization frozen on BOTH axes
```

Play it forward. The operator pans hard left until the gimbal engages — fine. They release left but immediately start panning *up*. The up-motion keeps refreshing `_last_pan_time`, so `pan_active` stays true, so **stabilization stays suppressed on both axes** — including the horizontal axis they already let go of.

With horizontal stabilization frozen, `cmd.x` never recenters. The overshoot on X never shrinks. And so the gimbal keeps yawing left **forever**, long after the stick stopped asking for it — until you eventually release *every* axis and the global timer expires. The physical pan that should have wound down the instant the operator released left just… keeps rolling.

The fix is to recognise that "panning" is a *per-axis* fact, not a global one. Track a release timer per axis, and stabilize each axis the moment *that* axis is released — even while the other is still being driven:

```python
# The right version — release is per axis.
def on_stick(self, dx, dy, now):
    if dx != 0: self._last_pan_x = now
    if dy != 0: self._last_pan_y = now
    self.cmd = self.cmd + Vec2(dx, dy)

def per_frame(self, now, imu_shift):
    active_x = (now - self._last_pan_x) < PAN_TIMEOUT
    active_y = (now - self._last_pan_y) < PAN_TIMEOUT

    # Stabilize only the released axis; hold the one still being panned.
    if not (active_x and active_y):
        self.apply_stabilization(Vec2(0.0 if active_x else imu_shift.x,
                                       0.0 if active_y else imu_shift.y))
```

Now releasing left while still panning up applies stabilization to X only: `cmd.x` recenters, the X overshoot winds to zero, the gimbal stops yawing — all while the Y crop keeps faithfully tracking the up-pan with no IMU interference. The held axis stays crisp; the released axis lets go.

The general lesson is the one that keeps coming back in control code: **a single global flag that gates a multi-axis (or multi-channel) system will eventually freeze a channel that should have been free.** The moment two independent things share one piece of "am I busy?" state, releasing one of them stops releasing it. Split the state along the same axis the physics is split on.

## Takeaways

- **Digital pan and physical pan are different tools.** Crop pan is instant and free but bounded by the sensor edge; gimbal pan is slow and mechanical but unbounded. Use the fast one for intent and the slow one for range.
- **Let geometry be the control law.** Driving the gimbal off a normalised overshoot gives you proportional slew, automatic deceleration, and a clean stop with no black margin — without a hand-tuned ramp.
- **Gate the mechanics behind a dwell** so brief inputs stay purely digital and only sustained ones spin up the motor.
- **Close the loop with the IMU.** Stabilization is what hands authority back from the body to the head, and it's why the operator never sees the seam.
- **Suppress stabilization per axis, never globally.** The handoff is independent on each axis; the "am I panning?" state has to be too, or a released axis keeps rolling.
