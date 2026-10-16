"""Plot a pendulum_debug_log.csv pulled from the device (see PendulumDebugLogger.kt).

Pull it first:
  adb pull /sdcard/Android/data/com.pendulumapp/files/pendulum_debug_log.csv

Each row pairs one control-loop tick's live sensor reading with the video's own recorded
angle at whatever position was playing at that instant -- see PendulumSpeedController's
TickInfo for what each column means. Gaps (empty realHere/error/localSlope fields) mark
ticks where the controller was coasting -- no live angle yet, or the video's local slope
was too flat to steer by -- and are plotted as breaks in the line, not zeros.

Also plots the *raw* per-axis gravity/gyroscope values, if present (logs from before this
was added won't have them). Use these to calibrate PendulumTiltSensor's axis/invertSign
against real hardware instead of guessing: at rest, whichever of gravityX/Y/Z sits near
+-9.8 is "down" in device coordinates; whichever of the other two changes the most as the
phone swings is the actual swing-plane axis.
"""

import argparse
import csv
import os

import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description="Plot a pulled pendulum_debug_log.csv")
parser.add_argument("csv_file", nargs="?", default="pendulum_debug_log.csv",
                    help="Path to the pulled CSV (default: pendulum_debug_log.csv)")
args = parser.parse_args()

if not os.path.isfile(args.csv_file):
    raise FileNotFoundError(
        f"Could not find {args.csv_file}. Pull it first with:\n"
        "  adb pull /sdcard/Android/data/com.pendulumapp/files/pendulum_debug_log.csv"
    )

with open(args.csv_file, newline="") as f:
    rows = list(csv.DictReader(f))

if not rows:
    raise SystemExit(f"{args.csv_file} has no data rows.")

has_raw_axes = "gravityX" in rows[0]


def col(key):
    out = []
    for r in rows:
        v = r.get(key, "")
        out.append(float(v) if v not in ("", None) else float("nan"))
    return out


t_sec         = [v / 1000.0 for v in col("tMs")]
live_angle    = col("liveAngleDeg")
target_deg    = col("targetDeg")
real_here     = col("realHereDeg")
error         = col("errorDeg")
rate          = col("rate")

coasting_frac = sum(1 for v in error if v != v) / len(error)  # v != v <=> NaN
print(f"{len(rows)} rows, {coasting_frac * 100:.1f}% of ticks coasting (no error/realHere)")


def correlation(a, b):
    """Pearson correlation over rows where both a and b are valid (not NaN)."""
    pairs = [(x, y) for x, y in zip(a, b) if x == x and y == y]
    if len(pairs) < 2:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx > 0 and dy > 0 else None


# Sign check: target and realHere should be POSITIVELY correlated -- that's what "the
# controller is steering realHere toward target" looks like. A negative correlation means
# it's pushing the wrong direction on average (an invertSign-class bug in PendulumTiltSensor,
# not just a tuning/convergence issue) -- see that class's doc comment for how this was found
# and fixed once already.
sign_corr = correlation(target_deg, real_here)
if sign_corr is not None:
    verdict = "OK (steering the right direction)" if sign_corr > 0 else \
        "BACKWARDS -- check PendulumTiltSensor's invertSign" if sign_corr < 0 else "flat/inconclusive"
    print(f"corr(targetDeg, realHereDeg) = {sign_corr:+.3f}  -> {verdict}")

n_panels = 4 if has_raw_axes else 3
fig, axes = plt.subplots(n_panels, 1, figsize=(11, 3 * n_panels), sharex=True)
ax1, ax2, ax3 = axes[0], axes[1], axes[2]

ax1.plot(t_sec, live_angle, label="live sensor angle", color="#d94f4f", linewidth=1.2)
ax1.plot(t_sec, target_deg, label="target (-live angle)", color="#4f7fd9",
          linewidth=1.2, linestyle="--")
ax1.plot(t_sec, real_here, label="video's recorded angle (realHere)", color="#3fa34d",
          linewidth=1.2)
ax1.axhline(0, color="gray", linewidth=0.8, linestyle=":")
ax1.set_ylabel("degrees")
ax1.set_title("Live sensor vs. video's recorded angle at the playing position")
ax1.legend(loc="upper right", fontsize=8)
ax1.grid(alpha=0.3)

ax2.plot(t_sec, error, color="#a34dbb", linewidth=1.2)
ax2.axhline(0, color="gray", linewidth=0.8, linestyle=":")
ax2.set_ylabel("error (deg)")
ax2.set_title("Tracking error = target - realHere (gaps = coasting)")
ax2.grid(alpha=0.3)

ax3.plot(t_sec, rate, color="#d98a2f", linewidth=1.2)
ax3.axhline(1.0, color="gray", linewidth=0.8, linestyle=":")
ax3.set_ylabel("playback rate")
if not has_raw_axes:
    ax3.set_xlabel("Time since tracking started (s)")
ax3.set_title("Applied playback speed multiplier")
ax3.grid(alpha=0.3)

if has_raw_axes:
    gx, gy, gz = col("gravityX"), col("gravityY"), col("gravityZ")

    def stats(name, values):
        import math
        valid = [v for v in values if v == v]  # drop NaN
        mean = sum(valid) / len(valid)
        spread = max(valid) - min(valid)
        print(f"  {name}: mean={mean:+6.2f}  range=[{min(valid):+6.2f}, {max(valid):+6.2f}]  "
              f"spread={spread:5.2f}{'  <- near +-9.8 at rest: likely DOWN axis' if abs(mean) > 7 else ''}")

    print("\nRaw gravity axis summary (m/s^2) -- for PendulumTiltSensor axis/invertSign calibration:")
    stats("gravityX", gx)
    stats("gravityY", gy)
    stats("gravityZ", gz)

    ax4 = axes[3]
    ax4.plot(t_sec, gx, label="gravityX", color="#d94f4f", linewidth=1.0)
    ax4.plot(t_sec, gy, label="gravityY", color="#3fa34d", linewidth=1.0)
    ax4.plot(t_sec, gz, label="gravityZ", color="#4f7fd9", linewidth=1.0)
    ax4.axhline(0, color="gray", linewidth=0.8, linestyle=":")
    ax4.set_ylabel("m/s^2")
    ax4.set_xlabel("Time since tracking started (s)")
    ax4.set_title("Raw gravity vector per device axis (whichever swings most IS the swing axis)")
    ax4.legend(loc="upper right", fontsize=8)
    ax4.grid(alpha=0.3)

fig.tight_layout()
out_path = os.path.splitext(args.csv_file)[0] + "_plot.png"
fig.savefig(out_path, dpi=150)
print(f"Saved: {out_path}")
