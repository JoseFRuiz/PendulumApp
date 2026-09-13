import argparse
import cv2
import math
import numpy as np
import os

from floor_detection import detect_sequence, fill_gaps, render_curve_panel

Y_PLOT_MIN = -60.0  # angle axis lower bound for the side curve panel (degrees)
Y_PLOT_MAX =  60.0  # angle axis upper bound

# Tune these constants to adjust the simulation layout
AMPLITUDE_DEG = 27.0    # max swing angle from vertical, in degrees
PERIOD_SEC    = 1.87     # full oscillation period in seconds
SCREEN_SCALE  = 0.35     # scale factor applied to the video frame before compositing
                        # (with CANVAS_W/H_MULT=2 this makes the canvas = original video resolution)
CANVAS_W_MULT = 3       # canvas width  = scaled_frame_width  × this
CANVAS_H_MULT = 3       # canvas height = scaled_frame_height × this
ARM_RATIO     = 1.0    # arm length as a fraction of canvas height

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(description="Simulate a video playing on a pendulum-mounted screen.")
parser.add_argument("input_file", nargs="?", default="baile_pendulo_modified.mp4",
                    help="Input video filename in the same folder (default: baile_pendulo.mp4)")
parser.add_argument("--amplitude", type=float, default=AMPLITUDE_DEG,
                    help=f"Max swing amplitude in degrees; always drives the simulated pendulum "
                         f"swing (default: {AMPLITUDE_DEG})")
parser.add_argument("--period", type=float, default=PERIOD_SEC,
                    help=f"Oscillation period in seconds; always drives the simulated pendulum "
                         f"swing (default: {PERIOD_SEC})")
parser.add_argument("--start", type=float, default=0.0,
                    help="Start offset in seconds. Positive: skip that many seconds from the video. "
                         "Negative: prepend that many seconds of fully white frames before the video.")
parser.add_argument("--catchup-sec", type=float, default=0.6,
                    help="Seconds to close a video/pendulum position error via proportional "
                         "correction (default: 0.6). Smaller = snappier correction (risk of "
                         "overshoot); larger = smoother but slower to lock in.")
parser.add_argument("--min-rate", type=float, default=0.25,
                    help="Minimum video playback speed multiplier (default: 0.25).")
parser.add_argument("--max-rate", type=float, default=3.0,
                    help="Maximum video playback speed multiplier (default: 3.0).")
parser.add_argument("--max-accel", type=float, default=0.04,
                    help="Maximum change in playback speed per output frame (default: 0.04); "
                         "bounds how fast the video can speed up or slow down.")
args = parser.parse_args()

amplitude_rad = math.radians(args.amplitude)
amplitude_deg = args.amplitude
period        = args.period
start_sec     = args.start
min_rate      = max(0.01, args.min_rate)  # must stay strictly positive: guarantees loop termination
max_rate      = max(min_rate, args.max_rate)
max_accel     = max(0.0, args.max_accel)
catchup_sec   = max(0.01, args.catchup_sec)
MIN_SLOPE_DEG = 0.05  # local slope (deg/source-frame) below which we treat the signal as flat

input_path        = os.path.join(SCRIPT_DIR, args.input_file)
stem              = os.path.splitext(os.path.basename(args.input_file))[0]
output_path       = os.path.join(SCRIPT_DIR, f"{stem}_pendulum.mp4")
output_path_clean = os.path.join(SCRIPT_DIR, f"{stem}_pendulum_clean.mp4")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vh           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# --- Offline pass: detect the real floor-edge swing angle (and the edge line
# itself) for every source frame, before any frame is composited onto the
# swinging screen. ---
print("Detecting floor edge angle (offline pass)...")
detections   = detect_sequence(cap, progress_label="detect")
raw_angles   = [a for a, _ in detections]
lines_raw    = [l for _, l in detections]
angle_filled = fill_gaps(raw_angles)
use_fallback = all(a is None for a in angle_filled)
if use_fallback:
    print("  No floor edge detected anywhere in the video; the video-speed "
          "controller will run at 1x (normal speed) throughout.")

cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # rewind for the compositing pass below

# Scaled screen dimensions and canvas
sw = int(vw * SCREEN_SCALE)   # screen width on canvas
sh = int(vh * SCREEN_SCALE)   # screen height on canvas
canvas_w = sw * CANVAS_W_MULT  # with SCREEN_SCALE=0.5 + MULT=2 → canvas = original video size
canvas_h = sh * CANVAS_H_MULT
pivot_x  = canvas_w // 2
arm_len  = min(canvas_h * ARM_RATIO, canvas_h - sh / 2)  # keep screen bottom inside canvas

# Output width capped at 80% of the source video's width; the rendered canvas
# is downscaled to fit, keeping its aspect ratio. The curve panel sits below it,
# matching its width, with its own smaller height.
out_w = round(vw * 0.8)
out_h = round(canvas_h * out_w / canvas_w)
panel_w = out_w
panel_h = round(out_h * 0.35)

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out       = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h + panel_h))
out_clean = cv2.VideoWriter(output_path_clean, fourcc, fps, (out_w, out_h))

start_frame_idx = round(start_sec * fps) if start_sec > 0 else 0
if start_sec > 0:
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame_idx)

n_white = round(abs(start_sec) * fps) if start_sec < 0 else 0
output_total_frames = n_white + max(0, total_frames - start_frame_idx)  # estimate; grown below if exceeded

# Two curves feed the side panel: the idealized simulation angle (a clean,
# constant sine wave from --amplitude/--period that always drives the arm), and
# the real floor-edge detection sampled at whatever source position the video-
# speed controller is currently displaying (breaks wherever that frame had no
# valid detection, and absent entirely during the white pre-roll, since there's
# no video there to measure).
sim_angle_history   = []  # degrees, one entry per output frame
floor_angle_history = []  # degrees or None, one entry per output frame

# Online video-speed controller state: vpos is the virtual (fractional) source
# frame position, monotonic non-decreasing so the video only ever plays forward
# (never seeks backward); rate is the current playback speed multiplier. Each
# video frame, vpos is nudged so that the real detected angle at that position
# tracks the ideal pendulum's current angle (see the crossing-search below),
# reusing play_video.py's two-frame blend window for smooth sub-frame playback.
vpos = float(start_frame_idx)
rate = 1.0
ret, frame_a = cap.read(); frame_a = frame_a if ret else None
ret, frame_b = cap.read(); frame_b = frame_b if ret else None
next_src_idx = start_frame_idx + 1


def compose_canvas(screen_img):
    """Rotate/position one screen image onto a fresh canvas. Geometry (M_rot,
    attach points, paste bounds) is identical for the clean and debug screen
    variants each frame, since it depends only on theta, not screen content --
    only this function's `screen_img` argument differs between the two calls.
    """
    rotated = cv2.warpAffine(screen_img, M_rot, (sw, sh), flags=cv2.INTER_LINEAR)
    canvas_img = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    cv2.line(canvas_img, (pivot_x, 0), (attach_x, attach_y), (180, 180, 180), 3)
    cv2.circle(canvas_img, (pivot_x, 0), 8, (255, 255, 255), -1)
    if cx2 > cx1 and cy2 > cy1:
        canvas_img[cy1:cy2, cx1:cx2] = rotated[fy1:fy2, fx1:fx2]
    return canvas_img


def draw_angle_label(img, theta_rad):
    label = f"{math.degrees(theta_rad):+.1f} deg"
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2
    cv2.putText(img, label, (10, 40), font, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(img, label, (10, 40), font, scale, (255, 255, 255), thick, cv2.LINE_AA)

frame_number = 0
while True:
    t = frame_number / fps
    sim_theta = amplitude_rad * math.sin(2 * math.pi * t / period)

    if frame_number < n_white:
        # Pre-roll: white content inside the green-bordered screen (no line to
        # draw, so the clean and debug screens are identical here)
        screen_clean = np.full((sh, sw, 3), 255, dtype=np.uint8)
        cv2.rectangle(screen_clean, (0, 0), (sw - 1, sh - 1), (0, 255, 0), 6)
        screen_debug = screen_clean
        floor_angle_history.append(None)
    else:
        # --- Online rate control: retime video playback so the real detected
        # angle at the displayed frame OPPOSES the ideal pendulum's angle. The
        # screen's own rotation (theta, applied below) adds to whatever tilt is
        # already baked into the displayed video frame, so for the arm to visually
        # *compensate* the floor's recorded tilt (rather than double it), we need
        # the video's real angle to be -theta, not +theta.
        #
        # The needed playback rate is computed directly from the real signal's
        # local slope plus a proportional position-error correction (feedforward
        # + P control), rather than searching forward for a future value match:
        # a forward search fails whenever the real signal has already passed the
        # target locally and won't recross it (same direction) until a full
        # period later, which is common since the video's phase drifts relative
        # to the ideal pendulum's.
        target_deg   = -math.degrees(sim_theta)
        target_deriv = -amplitude_deg * (2 * math.pi / period) * math.cos(2 * math.pi * t / period)  # deg/sec

        i = int(vpos)
        if use_fallback or i + 1 >= len(angle_filled):
            desired_rate = 1.0
        else:
            frac        = vpos - i
            real_here   = angle_filled[i] + frac * (angle_filled[i + 1] - angle_filled[i])
            local_slope = angle_filled[i + 1] - angle_filled[i]  # degrees per source-frame
            if abs(local_slope) < MIN_SLOPE_DEG:
                desired_rate = 1.0  # flat/gap region: no reliable local direction, just coast
            else:
                error = target_deg - real_here
                desired_d_real_dt = target_deriv + error / catchup_sec  # deg/sec
                desired_rate = desired_d_real_dt / (local_slope * fps)

        rate += max(-max_accel, min(max_accel, desired_rate - rate))
        rate  = max(min_rate, min(max_rate, rate))
        vpos  = max(start_frame_idx, min(total_frames - 1, vpos + rate))

        src_int = int(vpos)
        alpha   = vpos - src_int
        while next_src_idx - 1 < src_int and frame_b is not None:
            frame_a = frame_b
            ret, frame_b = cap.read()
            frame_b = frame_b if ret else None
            next_src_idx += 1

        if frame_a is None:
            break  # source exhausted early

        frame = (cv2.addWeighted(frame_a, 1.0 - alpha, frame_b, alpha, 0)
                  if (alpha > 0 and frame_b is not None) else frame_a.copy())

        idx = min(src_int, len(angle_filled) - 1)
        # Resize to screen dimensions and add green border (the clean variant)
        screen_clean = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA)
        cv2.rectangle(screen_clean, (0, 0), (sw - 1, sh - 1), (0, 255, 0), 6)

        # Debug variant additionally shows the detected floor edge, drawn on a
        # full-res copy before it's scaled down and rotated, so the line visibly
        # swings along with the screen.
        detected_line = lines_raw[idx] if idx < len(lines_raw) else None
        if detected_line is not None:
            frame_debug = frame.copy()
            lx1, ly1, lx2, ly2 = detected_line
            cv2.line(frame_debug, (lx1, ly1), (lx2, ly2), (0, 0, 255), 4)
            screen_debug = cv2.resize(frame_debug, (sw, sh), interpolation=cv2.INTER_AREA)
            cv2.rectangle(screen_debug, (0, 0), (sw - 1, sh - 1), (0, 255, 0), 6)
        else:
            screen_debug = screen_clean
        # Negated to match sign convention with sim_angle_history: the arm compensates
        # the floor's tilt (target_deg above is -theta), so plotting -real_angle here
        # lets the two curves visually overlap when the controller is tracking well.
        real_angle = raw_angles[idx] if idx < len(raw_angles) else None
        floor_angle_history.append(-real_angle if real_angle is not None else None)

    theta = sim_theta  # the arm always follows the ideal pendulum, never the real detection

    # Position of the screen center on the canvas
    screen_cx = pivot_x + arm_len * math.sin(theta)
    screen_cy = arm_len * math.cos(theta)

    # Rotate screen frame around its own center.
    # Positive angle: top of screen moves toward pivot (upper-left when theta>0), matching pendulum physics.
    M_rot = cv2.getRotationMatrix2D((sw / 2.0, sh / 2.0), math.degrees(theta), 1.0)

    # Arm attaches at the top edge of the screen (sh/2 closer to pivot than screen center)
    attach_x = int(pivot_x + (arm_len - sh / 2) * math.sin(theta))
    attach_y = int((arm_len - sh / 2) * math.cos(theta))

    # Paste rotated screen centered at screen center, clipped to canvas bounds
    x1 = int(round(screen_cx - sw / 2));  x2 = x1 + sw
    y1 = int(round(screen_cy - sh / 2));  y2 = y1 + sh

    cx1 = max(0, x1);  cx2 = min(canvas_w, x2)
    cy1 = max(0, y1);  cy2 = min(canvas_h, y2)

    fx1 = cx1 - x1;  fx2 = fx1 + (cx2 - cx1)
    fy1 = cy1 - y1;  fy2 = fy1 + (cy2 - cy1)

    canvas_clean = cv2.resize(compose_canvas(screen_clean), (out_w, out_h), interpolation=cv2.INTER_AREA)
    draw_angle_label(canvas_clean, theta)
    out_clean.write(canvas_clean)

    canvas_debug = cv2.resize(compose_canvas(screen_debug), (out_w, out_h), interpolation=cv2.INTER_AREA)
    draw_angle_label(canvas_debug, theta)

    sim_angle_history.append(math.degrees(sim_theta))
    output_total_frames = max(output_total_frames, frame_number + 1)  # grow the estimate if exceeded
    curve_panel = render_curve_panel(
        [
            {"history": sim_angle_history,   "color": (30, 120, 220), "label": "simulation angle", "thickness": 1},
            {"history": floor_angle_history, "color": (60, 170, 0),   "label": "floor edge angle",  "thickness": 1},
        ],
        fps, output_total_frames, panel_w, panel_h, y_min=Y_PLOT_MIN, y_max=Y_PLOT_MAX)
    combined = np.concatenate([canvas_debug, curve_panel], axis=0)

    out.write(combined)
    frame_number += 1

    if frame_number % int(fps) == 0:
        pct = 100 * frame_number // output_total_frames if output_total_frames > 0 else 0
        print(f"  {frame_number}/{output_total_frames} frames  ({pct}%)")

    if frame_number >= n_white and vpos >= total_frames - 1:
        break  # the last frame of the source video has now been rendered once

cap.release()
out.release()
out_clean.release()
print(f"\nDone. Saved to:\n  {output_path}\n  {output_path_clean}")
