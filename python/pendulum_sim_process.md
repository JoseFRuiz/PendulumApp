# The Compensating Pendulum — How `pendulum_sim.py` Works

*A process report, written to inform porting this idea into the Android app (`app/`),
which will eventually run this on a real swinging pendulum rather than a simulated one.*

## 1. The piece, in one sentence

A video of a dancer, originally filmed by a camera that was itself mounted on a
swinging pendulum, is played back on a screen mounted on a *new* swinging pendulum —
and the video is subtly sped up and slowed down, moment to moment, so that its own
recorded tilt cancels out the screen's live physical tilt. Seen from outside, the
screen swings back and forth like any pendulum, but the recorded floor inside it
stays level — a stationary world glimpsed through a moving window.

That cancellation — not the swinging itself — is the actual work being simulated.
The swinging is the given; the compensation is the art.

## 2. The constraint that shapes everything

In the real installation, the pendulum is a physical object. Once built, its rhythm
is dictated by gravity and the geometry of the arm — nothing in software can make it
swing faster or slower moment to moment. The one thing that *can* be steered, freely
and continuously, is **which moment of the pre-recorded video is being shown on the
screen right now** — in other words, the video's playback speed.

Every design decision in the simulation follows from that one constraint: the
pendulum is a given; the video is the dial.

## 3. Two phases: remembering, then following

The process splits cleanly into two phases that happen one after the other.

### Phase 1 — Reading the video's own memory (done once, ahead of time)

Before anything is composited, the whole source video is scanned once, frame by
frame, to measure how tilted the *recorded* floor was at every single moment. This
produces a timeline: "at this point in the footage, the world was tilted by this
many degrees." It's a transcript of the camera's own swinging history, written down
once so it can be consulted instantly, in any order, later.

This phase doesn't touch the pendulum simulation at all — it's pure archaeology on
the footage itself.

### Phase 2 — Following the swing, live (continuous, incremental)

With that transcript in hand, the simulation then imagines an idealized pendulum —
perfectly regular, like a metronome, with a fixed amplitude and period, standing in
for "however the real arm will actually swing." Frame by frame, as this idealized
pendulum's angle changes, the simulation decides *which point in the pre-recorded
footage to show right now* so that the footage's own recorded tilt is the opposite
of the idealized pendulum's current tilt. When both are combined — the screen's
physical rotation and the footage's baked-in tilt — they cancel, and the floor reads
as level.

Critically, this decision is made **incrementally, one small step at a time**, using
only "where things are right now," not by planning the whole video's timing in
advance. That's a deliberate choice: the real installation will eventually make this
same decision live, from a sensor reading, with no ability to see into the future —
so the simulation is built to work the same way, even though (for now) it has the
whole video sitting in memory and could technically cheat.

## 4. The steering itself — a gentle, continuous correction

At every frame, the system effectively asks three questions:

1. Where does the idealized pendulum say the screen should be pointing right now,
   and which way is it currently swinging?
2. Given where we are in the footage right now, is its recorded tilt ahead of or
   behind what's needed — and, just as important, which way and how fast is that
   recorded tilt *already* changing from moment to moment?
3. Given both of those, should the video speed up a little, slow down a little, or
   hold steady, to close the gap?

That correction is applied gently: two separate limits keep it from ever looking
like a jump-cut. One caps how *fast* the video is allowed to play at all (it can
speed up or slow down, but only so much). The other caps how *quickly the speed
itself is allowed to change* — so a big correction happens as a smooth acceleration
over a second or so, not an instant snap. There's also a single "how many seconds
should it take to close a gap" dial that governs how aggressively the system
corrects itself: too aggressive and it overshoots and hunts back and forth each
swing; too gentle and it never quite catches up.

## 5. Two renders, for two different audiences

The process produces two videos from the same run:

- A **diagnostic** version — the detected floor line drawn on top of the footage,
  a running number showing the arm's current angle, and a live side-by-side graph
  plotting the idealized pendulum's angle against the video's own recorded angle
  over time. This exists purely to answer the question "is the steering actually
  working?" — if the two lines on the graph track each other, it is.
- A **clean** version — just the swinging screen and its content, nothing overlaid.
  This is what an audience would actually see.

Keeping both was a deliberate choice: the diagnostic version is how you catch bugs
in the steering logic; the clean version is how you judge the actual art.

## 6. How this was actually arrived at — the design's history

The process didn't arrive at the above in a straight line, and the detours are
informative for anyone adapting this to the real hardware:

- **First attempt: the screen followed the recording directly.** The screen's
  rotation was driven straight from the video's own recorded tilt — literally
  re-enacting the original camera's motion. This works as a visual, but it leaves
  no room to control playback speed at all, since the screen and the footage are
  locked together by construction. It had to be abandoned once the actual goal —
  *controlling video speed* — was made explicit, since that goal requires the
  screen's motion to be independent of the footage.
- **Second attempt, and a sign error.** Once the screen was switched to swing on
  its own idealized rhythm (independent of the footage), the first version of the
  steering logic tried to match the video's recorded angle *to* the screen's angle
  directly — same sign, same direction. This is intuitive, but wrong: because the
  screen's own rotation is applied *on top of* whatever tilt is already baked into
  the footage, matching same-sign angles makes the two *add up* (the floor looks
  increasingly tilted, not level). The fix was realizing the two angles need to be
  *opposite* — the arm compensates the footage, rather than mirroring it. This was
  only caught by scrutinizing an actual rendered frame and noticing the floor line
  looked wrong, not by reasoning about it in the abstract.
- **A control loop that looked plausible but never actually engaged.** The first
  version of the live-steering logic worked by searching forward in the footage's
  timeline for the next moment its recorded angle would match what was needed. This
  reads as reasonable, but has a hidden flaw: once the footage's phase drifts out of
  sync with the idealized pendulum (which happens immediately, since they start out
  unrelated), the *next* moment the recorded signal revisits the needed angle *in
  the needed direction* is typically a full swing-cycle away — outside of how far
  ahead the search was willing to look. The search would quietly find nothing, over
  and over, and the system would silently coast at normal speed forever, never
  actually correcting. This was invisible from the output alone — the video played
  fine, just unsynchronized — and was only caught by printing the internal numbers
  frame by frame and noticing they never converged. The lesson: a feedback loop has
  to be checked against its own internal state (is the error shrinking?), not just
  "does it produce a plausible-looking video?"
- **The fix: stop searching for a moment, start reading a rate.** The steering
  logic was rewritten to stop asking "when will the footage next say the right
  thing?" and instead ask, continuously, "which way and how fast is the footage's
  recorded angle *already* changing right now, and how does that compare to what's
  needed?" This local, rate-based approach self-corrects from any starting offset,
  rather than depending on finding a specific future match — and it's what's
  described in §4 above.

## 7. What this means for the real installation (`app/`)

The two-phase structure carries over almost directly, with one formula swapped for
a sensor:

- **The idealized pendulum formula goes away.** In the simulation, "where should the
  screen be pointing right now" is a mathematical stand-in, because there's no real
  arm yet to measure. In the installation, that question has a real, physical
  answer, available live from the phone's own motion sensors — the same sensors
  `MotionDetector.kt` already reads to detect a swing. The live sensor reading
  simply replaces the formula everywhere it's used.
- **Phase 1 (reading the footage's memory) carries over unchanged in spirit.**
  Whatever video is loaded still needs its own recorded-tilt timeline measured once,
  in advance — the same kind of scan the Python prototype does before playback
  starts. Whether that scan happens on-device when a video is chosen, or is
  precomputed and shipped alongside each video asset, is an open implementation
  question, but the *need* for it doesn't change.
- **Phase 2 (live steering) becomes: read the sensor, adjust playback speed.** The
  same gentle, incremental correction — nudge the video's speed up or down, limited
  in how far and how fast it can change — maps onto continuously adjusting the
  video player's playback speed on the device, on every sensor update, rather than
  the current behavior of just starting or stopping playback.
- **A real gap worth flagging now, before implementation starts:** the sensor
  pipeline in `MotionDetector.kt` today reports a discrete *event* (a swipe crossing
  a threshold), not a continuously updated *angle*. The live-steering approach needs
  a running tilt angle at every moment, not an occasional event — which likely means
  the app needs a different or additional sensor signal (something that reports
  orientation continuously, since the linear-acceleration sensor currently used is
  deliberately gravity-free and isn't meant to give an absolute tilt) before the
  steering logic itself can be ported over.

## 8. Glossary of the tunable "feel" knobs

These are the dials that shape how the correction *feels*, described here in plain
terms since they'll need real-world equivalents on the device:

| Knob | What it controls |
|---|---|
| Amplitude / period | The idealized pendulum's swing size and rhythm — stands in for the real arm's physical amplitude/period once one exists. |
| Kp (proportional gain) | How hard the system corrects in proportion to the *current* gap between where the video is and where it needs to be. Higher = snappier but prone to overshoot; lower = smoother but slower to lock in. (This is the renamed, generalized form of what was originally called "catch-up time.") |
| Ki (integral gain) | How hard the system corrects for a gap that has *persisted* over time, rather than just the instantaneous one. This is what trims out a small, systematic bias that Kp alone settles for and never fully closes — see §9. |
| Kd (derivative gain) | How hard the system reacts to the gap *changing quickly*, as a second, independent brake on overshoot. Off by default — see §9 for why. |
| Speed limits | The slowest and fastest the video is ever allowed to play, regardless of how large the gap is. |
| Speed-change limit | How quickly the playback speed itself is allowed to ramp up or down, frame to frame — this is what keeps corrections invisible rather than jarring. |

## 9. Addendum — reframing the steering as a PID controller

After the process above was working, the natural next question was: is this
steering logic actually a known, named thing? It turns out it already was — just
not using the standard name for it. This section records that reframing and what
was learned by testing it.

**What it already was.** The correction described in §4 — "how far off are we, and
how hard should we push back" — is precisely the *proportional* term of a classic
PID (Proportional-Integral-Derivative) controller. What made it *more* than a bare
proportional controller is that it's paired with **feedforward**: because the
idealized pendulum's exact motion is known in advance (it's a formula, not a
mystery), the system doesn't need to wait for accumulated error to nudge it toward
the right general behavior — it's handed the right answer directly, and only has to
correct the *remaining* gap. Feedforward plus a proportional term, it turns out, is
usually a better fit than a plain PID for *tracking a known, moving target* — a bare
PID is really built for holding a *fixed* setpoint steady against unknown
disturbances.

**What was missing: memory of a persistent gap.** A pure proportional term reacts
only to the gap *right now* — it has no memory. If the video consistently runs a
little behind (say, because the idealized pendulum's assumed rhythm doesn't quite
match reality), a P-only correction will settle into tracking with a small,
permanent lag rather than closing it, because as the lag shrinks, so does the very
correction meant to close it. Adding an **integral term** — a running memory of the
gap, accumulated over time — fixes exactly this: even a tiny, persistent lag
eventually accumulates into a correction big enough to erase it.

**Why this matters more once this moves to real hardware.** In the simulation, the
"idealized pendulum" is a hand-picked formula (a chosen amplitude and period) doing
its best to describe recorded footage of an actual human-swung pendulum — which
was never going to be a perfect sine wave to begin with. Once this runs on the real
installation, the exact same kind of gap reappears in a new form: whatever rhythm
the phone's live sensor reports will never *exactly* match whatever assumptions the
control loop makes about it. An integral term is precisely the piece designed to
quietly absorb that kind of persistent, real-world mismatch — the simulation is a
good place to have already found this out.

**What testing found.** Deliberately mismatching the idealized pendulum's assumed
period from the real recorded footage's actual rhythm — a stand-in for the drift
that's guaranteed once a real, physical arm replaces the formula — the proportional
term alone left a substantial residual tracking error. Adding a modest integral term
cut that error by roughly two-thirds, with no other change. Turned up further, it
started to overcorrect and hunt — the classic integral-gain trade-off — so there is
a sensible middle setting, not "more is better." Interestingly, the same
improvement showed up even *without* a deliberate mismatch: real, human-swung motion
never perfectly matches an idealized sine wave in the first place, so the integral
term earns its keep even in the best case, not only the deliberately mismatched one.

A derivative term was also tried, on top of the tuned integral term. It helped only
marginally, and mostly at small settings — consistent with the earlier prediction
that it wasn't likely to be worth much here, since a slew-rate limit on the output
already guards against the same kind of overshoot a derivative term targets, and a
derivative term reacts to a signal that's already somewhat noisy (the detected floor
angle), which is exactly the kind of signal a derivative term tends to amplify
rather than smooth.

**Net conclusion:** feedforward + proportional + a modest integral term is the
combination worth carrying forward to the real installation; the derivative term is
available (and configurable) but not carrying its weight so far.
