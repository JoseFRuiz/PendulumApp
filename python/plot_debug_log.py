"""Plot a pendulum_debug_log.csv pulled from the device (see PendulumDebugLogger.kt).

Pull it first:
  adb pull /sdcard/Android/data/com.pendulumapp/files/pendulum_debug_log.csv

Each row pairs one control-loop tick's live sensor reading with the video's own recorded
angle at whatever position was playing at that instant -- see PendulumSpeedController's
TickInfo for what each column means. Gaps (empty realHere/error/localSlope fields) mark
ticks where the controller was coasting -- no live angle yet, or the video's local slope
was too flat to steer by -- and are plotted as breaks in the line, not zeros.
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

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

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
ax3.set_xlabel("Time since tracking started (s)")
ax3.set_title("Applied playback speed multiplier")
ax3.grid(alpha=0.3)

fig.tight_layout()
out_path = os.path.splitext(args.csv_file)[0] + "_plot.png"
fig.savefig(out_path, dpi=150)
print(f"Saved: {out_path}")
