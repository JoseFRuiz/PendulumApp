import argparse
import cv2
import math
import numpy as np
import os

# Tune these constants to adjust the simulation layout
AMPLITUDE_DEG = 30.0    # max swing angle from vertical, in degrees
PERIOD_SEC    = 2.0     # full oscillation period in seconds
SCREEN_SCALE  = 0.5     # scale factor applied to the video frame before compositing
                        # (with CANVAS_W/H_MULT=2 this makes the canvas = original video resolution)
CANVAS_W_MULT = 2       # canvas width  = scaled_frame_width  × this
CANVAS_H_MULT = 2       # canvas height = scaled_frame_height × this
ARM_RATIO     = 0.50    # arm length as a fraction of canvas height

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(description="Simulate a video playing on a pendulum-mounted screen.")
parser.add_argument("input_file", nargs="?", default="baile_pendulo_modified.mp4",
                    help="Input video filename in the same folder (default: baile_pendulo.mp4)")
parser.add_argument("--amplitude", type=float, default=AMPLITUDE_DEG,
                    help=f"Max swing amplitude in degrees (default: {AMPLITUDE_DEG})")
parser.add_argument("--period", type=float, default=PERIOD_SEC,
                    help=f"Oscillation period in seconds (default: {PERIOD_SEC})")
parser.add_argument("--start", type=float, default=0.0,
                    help="Start offset in seconds. Positive: skip that many seconds from the video. "
                         "Negative: prepend that many seconds of fully white frames before the video.")
args = parser.parse_args()

amplitude_rad = math.radians(args.amplitude)
period        = args.period
start_sec     = args.start

input_path  = os.path.join(SCRIPT_DIR, args.input_file)
stem        = os.path.splitext(os.path.basename(args.input_file))[0]
output_path = os.path.join(SCRIPT_DIR, f"{stem}_pendulum.mp4")

cap = cv2.VideoCapture(input_path)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open: {input_path}")

fps          = cap.get(cv2.CAP_PROP_FPS) or 30
vw           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vh           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# Scaled screen dimensions and canvas
sw = int(vw * SCREEN_SCALE)   # screen width on canvas
sh = int(vh * SCREEN_SCALE)   # screen height on canvas
canvas_w = sw * CANVAS_W_MULT  # with SCREEN_SCALE=0.5 + MULT=2 → canvas = original video size
canvas_h = sh * CANVAS_H_MULT
pivot_x  = canvas_w // 2
arm_len  = canvas_h * ARM_RATIO

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(output_path, fourcc, fps, (canvas_w, canvas_h))

if start_sec > 0:
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(start_sec * fps))

n_white = round(abs(start_sec) * fps) if start_sec < 0 else 0

frame_number = 0
while True:
    if frame_number < n_white:
        # Pre-roll: white content inside the green-bordered screen
        screen = np.full((sh, sw, 3), 255, dtype=np.uint8)
        cv2.rectangle(screen, (0, 0), (sw - 1, sh - 1), (0, 255, 0), 6)
    else:
        ret, frame = cap.read()
        if not ret:
            break
        # Resize to screen dimensions and add green border
        screen = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA)
        cv2.rectangle(screen, (0, 0), (sw - 1, sh - 1), (0, 255, 0), 6)

    t     = frame_number / fps
    theta = amplitude_rad * math.sin(2 * math.pi * t / period)

    # Position of the screen center on the canvas
    screen_cx = pivot_x + arm_len * math.sin(theta)
    screen_cy = arm_len * math.cos(theta)

    # Rotate screen frame around its own center.
    # Positive angle: top of screen moves toward pivot (upper-left when theta>0), matching pendulum physics.
    M_rot   = cv2.getRotationMatrix2D((sw / 2.0, sh / 2.0), math.degrees(theta), 1.0)
    rotated = cv2.warpAffine(screen, M_rot, (sw, sh), flags=cv2.INTER_LINEAR)

    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

    # Arm attaches at the top edge of the screen (sh/2 closer to pivot than screen center)
    attach_x = int(pivot_x + (arm_len - sh / 2) * math.sin(theta))
    attach_y = int((arm_len - sh / 2) * math.cos(theta))

    # Draw arm first so the screen covers the lower portion of the arm
    cv2.line(canvas, (pivot_x, 0), (attach_x, attach_y), (180, 180, 180), 3)
    cv2.circle(canvas, (pivot_x, 0), 8, (255, 255, 255), -1)

    # Paste rotated screen centered at screen center, clipped to canvas bounds
    x1 = int(round(screen_cx - sw / 2));  x2 = x1 + sw
    y1 = int(round(screen_cy - sh / 2));  y2 = y1 + sh

    cx1 = max(0, x1);  cx2 = min(canvas_w, x2)
    cy1 = max(0, y1);  cy2 = min(canvas_h, y2)

    if cx2 > cx1 and cy2 > cy1:
        fx1 = cx1 - x1;  fx2 = fx1 + (cx2 - cx1)
        fy1 = cy1 - y1;  fy2 = fy1 + (cy2 - cy1)
        canvas[cy1:cy2, cx1:cx2] = rotated[fy1:fy2, fx1:fx2]

    out.write(canvas)
    frame_number += 1

    if frame_number % int(fps) == 0:
        pct = 100 * frame_number // total_frames if total_frames > 0 else 0
        print(f"  {frame_number}/{total_frames} frames  ({pct}%)")

cap.release()
out.release()
print(f"\nDone. Saved to:\n  {output_path}")
