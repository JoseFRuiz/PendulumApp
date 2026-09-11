import argparse
import cv2
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VIDEO_FILE = "baile_pendulo_modified_pendulum.mp4"

parser = argparse.ArgumentParser(description="Play a video at variable speed.")
parser.add_argument("video", nargs="?", default=DEFAULT_VIDEO_FILE,
                    help=f"Video file to play (default: {DEFAULT_VIDEO_FILE}). "
                         "A bare filename is resolved relative to this script's directory.")
parser.add_argument("rate", nargs="?", type=float, default=1.0,
                    help="Playback speed rate (default 1.0; e.g. 0.9=slower, 1.1=faster)")
parser.add_argument("--step", action="store_true",
                    help="Frame-by-frame mode: press any key to advance one step, Q to quit.")
args = parser.parse_args()
rate = max(0.01, args.rate)

VIDEO_FILE = args.video if os.path.isabs(args.video) else os.path.join(SCRIPT_DIR, args.video)

cap = cv2.VideoCapture(VIDEO_FILE)
if not cap.isOpened():
    raise FileNotFoundError(f"Could not open video: {VIDEO_FILE}")

fps = cap.get(cv2.CAP_PROP_FPS) or 30
# Display period stays fixed; speed is controlled by how fast virtual_pos advances
delay = max(1, int(1000 / fps))

# Bootstrap: pre-read first two source frames
ret, frame_a = cap.read()
if not ret:
    cap.release()
    raise RuntimeError("Video is empty")

ret, frame_b = cap.read()
if not ret:
    frame_b = None
next_src_idx = 1  # frame_b is at this index; frame_a is at next_src_idx - 1

virtual_pos = 0.0  # real-valued position in source-frame space
done = False
while not done:
    src_int = int(virtual_pos)
    alpha = virtual_pos - src_int  # fractional part → blend weight toward frame_b

    # Advance the source window until frame_a is at src_int
    while next_src_idx - 1 < src_int:
        if frame_b is None:
            done = True
            break
        frame_a = frame_b
        ret, frame_b = cap.read()
        if not ret:
            frame_b = None
        next_src_idx += 1

    if done:
        break

    # Blend frame_a and frame_b when the virtual position falls between them
    if alpha > 0 and frame_b is not None:
        display = cv2.addWeighted(frame_a, 1.0 - alpha, frame_b, alpha, 0)
    else:
        display = frame_a.copy()  # copy so the text doesn't corrupt the source frame

    # Overlay current time (seconds + hundredths)
    time_text = f"{virtual_pos / fps:.2f}s"
    cv2.putText(display, time_text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(display, time_text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)

    cv2.imshow("baile_pendulo", display)
    wait = 0 if args.step else delay  # 0 = wait indefinitely for a key press
    # waitKeyEx returns the full extended key code (needed for arrow keys on Windows)
    key = cv2.waitKeyEx(wait)

    if key == ord("q") or key == 27:  # Q or Escape
        break

    if args.step:
        print(f"key={key}")  # temporary: shows the exact code so you can verify arrow keys
        # Left-arrow: 2424832 on Windows, 65361 on Linux/macOS. 'a' as letter fallback.
        if key == ord("a") or key == 2424832 or key == 65361:
            virtual_pos = max(0.0, virtual_pos - rate)
            # Seek the source to the new position and reload the two-frame window
            src_int_new = int(virtual_pos)
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_int_new)
            ret, frame_a = cap.read()
            if ret:
                ret2, frame_b = cap.read()
                frame_b      = frame_b if ret2 else None
                next_src_idx = src_int_new + 1
        else:
            virtual_pos += rate
    else:
        virtual_pos += rate

cap.release()
cv2.destroyAllWindows()
