# Run: python plot_pendulum_swing.py ../old_logs/pendulum_debug_log.csv

"""Plot the real pendulum's physical swing, as measured by the phone's live tilt
sensor, from a pulled pendulum_debug_log.csv (see PendulumDebugLogger.kt / README's
"adb pull" instructions for how to get one off the device).

Unlike plot_debug_log.py -- which focuses on the CONTROL LOOP, comparing the live
sensor against the video's recorded angle, the tracking error, and the applied
playback rate -- this focuses purely on characterizing the REAL PHYSICAL PENDULUM's
own motion: its angle and angular velocity over time, plus estimated period/
amplitude. The period/amplitude estimate uses the same method floor_edge.py already
uses for the recorded footage's floor-edge signal (FFT for period, smoothed
derivative sign-changes for peaks), so the two "Signal: period ~ ... max ~ ... min
~ ..." lines are directly comparable -- e.g. to check whether the real pendulum's
actual rhythm matches what --period/--amplitude assume in pendulum_sim.py.

Usage:
  python plot_pendulum_swing.py <path_to_pendulum_debug_log.csv>
"""

import argparse
import csv
import os

import matplotlib.pyplot as plt
import numpy as np

parser = argparse.ArgumentParser(description="Plot the real pendulum's physical swing from a pulled debug log CSV.")
parser.add_argument("csv_file", help="Path to a pendulum_debug_log.csv pulled from the device.")
args = parser.parse_args()

if not os.path.isfile(args.csv_file):
    raise FileNotFoundError(f"Could not find {args.csv_file}")

with open(args.csv_file, newline="") as f:
    rows = list(csv.DictReader(f))
if not rows:
    raise SystemExit(f"{args.csv_file} has no data rows.")

t_sec = np.array([float(r["tMs"]) / 1000.0 for r in rows])
angle = np.array([float(r["liveAngleDeg"]) for r in rows])
omega = np.array([float(r["liveAngularVelocityDegPerSec"]) for r in rows])

print(f"{len(rows)} rows, {t_sec[-1] - t_sec[0]:.1f}s span, "
      f"angle range [{angle.min():+.1f}, {angle.max():+.1f}] deg")

# Sample interval: the control loop ticks at a roughly-fixed interval (see
# PendulumTuning.TICK_INTERVAL_MS), but not perfectly -- use the actual median gap
# between logged timestamps rather than assuming that constant.
dt = float(np.median(np.diff(t_sec)))

# --- Signal statistics (period, max/min peaks) -- same method floor_edge.py uses
# for the video's detected floor edge, applied here to the live sensor instead, so
# the two are directly comparable. ---
est_period = est_max = est_min = None
if len(angle) > 10 and dt > 0:
    fft_mag = np.abs(np.fft.rfft(angle - angle.mean()))
    freqs   = np.fft.rfftfreq(len(angle), d=dt)
    peak_f  = freqs[np.argmax(fft_mag[1:]) + 1]  # [1:] skips DC
    if peak_f > 0:
        est_period = 1.0 / peak_f

    w = max(3, int(round(0.2 / dt)))  # smooth over ~0.2s
    smooth = np.convolve(angle, np.ones(w) / w, mode="same")
    d = np.diff(smooth)
    max_idx = np.where((d[:-1] > 0) & (d[1:] <= 0))[0] + 1
    min_idx = np.where((d[:-1] < 0) & (d[1:] >= 0))[0] + 1
    if len(max_idx):
        est_max = float(np.median(angle[max_idx]))
    if len(min_idx):
        est_min = float(np.median(angle[min_idx]))

parts = []
if est_period is not None: parts.append(f"period ~ {est_period:.2f} s")
if est_max    is not None: parts.append(f"max ~ {est_max:.1f} deg")
if est_min    is not None: parts.append(f"min ~ {est_min:.1f} deg")
if parts:
    print("Real pendulum signal: " + ",  ".join(parts))
else:
    print("Not enough data to estimate period/peaks.")

title = "Real pendulum swing (live sensor)"
if parts:
    title += "   |   " + "   ".join(parts)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

ax1.plot(t_sec, angle, color="#1e78d4", linewidth=1.2, label="angle")
ax1.axhline(0, color="gray", linewidth=0.8, linestyle="--")
if est_max is not None:
    ax1.axhline(est_max, color="#d94f4f", linewidth=0.9, linestyle="--",
                label=f"max peak ~ {est_max:.1f} deg")
if est_min is not None:
    ax1.axhline(est_min, color="#4f7fd9", linewidth=0.9, linestyle="--",
                label=f"min peak ~ {est_min:.1f} deg")
ax1.set_ylabel("angle (deg)")
ax1.set_title(title)
ax1.grid(True, alpha=0.3)
ax1.legend(loc="lower right", fontsize=9)

ax2.plot(t_sec, omega, color="#3fa34d", linewidth=1.0)
ax2.axhline(0, color="gray", linewidth=0.8, linestyle=":")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("angular velocity (deg/s)")
ax2.set_title("Live angular velocity (gyroscope)")
ax2.grid(True, alpha=0.3)

fig.tight_layout()
out_path = os.path.splitext(args.csv_file)[0] + "_swing_plot.png"
fig.savefig(out_path, dpi=150)
print(f"Saved: {out_path}")
