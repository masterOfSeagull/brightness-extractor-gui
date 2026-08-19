import math
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2


VIDEO_TYPES = [
    ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.m4v *.ts *.mts *.flv"),
    ("All files", "*.*"),
]


def parse_time(value: str) -> float:
    """Parse seconds, MM:SS, or HH:MM:SS into seconds."""
    text = value.strip()
    if not text:
        raise ValueError("Time value is empty")

    parts = text.split(":")
    if len(parts) == 1:
        seconds = float(parts[0])
    elif len(parts) == 2:
        minutes = int(parts[0])
        seconds = minutes * 60.0 + float(parts[1])
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = hours * 3600.0 + minutes * 60.0 + float(parts[2])
    else:
        raise ValueError("Use seconds, MM:SS, or HH:MM:SS")

    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Time must be a finite non-negative value")
    return seconds


def format_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    return f"{minutes:02d}:{secs:06.3f}"


class FrameSamplerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Frame Sampler")
        self.root.geometry("720x440")
        self.root.minsize(640, 400)

        self.video_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.start_var = tk.StringVar(value="0")
        self.end_var = tk.StringVar(value="")
        self.period_var = tk.StringVar(value="1.0")
        self.format_var = tk.StringVar(value="PNG")
        self.status_var = tk.StringVar(value="Choose a video to begin.")
        self.meta_var = tk.StringVar(value="")
        self.estimate_var = tk.StringVar(value="")

        self.duration_seconds = None
        self.fps = None
        self.total_frames = None
        self.worker = None
        self.cancel_event = threading.Event()

        self._build_ui()

        for var in (self.start_var, self.end_var, self.period_var):
            var.trace_add("write", lambda *_: self._refresh_estimate())

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text="Video").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(outer, textvariable=self.video_var).grid(row=0, column=1, sticky="ew", padx=(10, 8), pady=6)
        ttk.Button(outer, text="Browse…", command=self._choose_video).grid(row=0, column=2, pady=6)

        ttk.Label(outer, text="Output folder").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(outer, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=(10, 8), pady=6)
        ttk.Button(outer, text="Browse…", command=self._choose_output).grid(row=1, column=2, pady=6)

        self.meta_label = ttk.Label(outer, textvariable=self.meta_var, foreground="#666666")
        self.meta_label.grid(row=2, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=(0, 10))

        range_box = ttk.LabelFrame(outer, text="Sampling", padding=12)
        range_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 10))
        for col in range(4):
            range_box.columnconfigure(col, weight=1)

        ttk.Label(range_box, text="Start time").grid(row=0, column=0, sticky="w")
        ttk.Label(range_box, text="End time").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(range_box, text="Sampling period (s)").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Label(range_box, text="Format").grid(row=0, column=3, sticky="w", padx=(12, 0))

        ttk.Entry(range_box, textvariable=self.start_var).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Entry(range_box, textvariable=self.end_var).grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        ttk.Entry(range_box, textvariable=self.period_var).grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(4, 0))
        ttk.Combobox(
            range_box,
            textvariable=self.format_var,
            values=("PNG", "JPEG"),
            state="readonly",
            width=8,
        ).grid(row=1, column=3, sticky="ew", padx=(12, 0), pady=(4, 0))

        ttk.Label(
            range_box,
            text="Times accept seconds, MM:SS, or HH:MM:SS. Empty end time means end of video.",
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Label(outer, textvariable=self.estimate_var).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        ttk.Label(outer, textvariable=self.status_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )

        button_row = ttk.Frame(outer)
        button_row.grid(row=7, column=0, columnspan=3, sticky="e")
        self.cancel_button = ttk.Button(button_row, text="Cancel", command=self._cancel, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.RIGHT, padx=(8, 0))
        self.extract_button = ttk.Button(button_row, text="Extract Frames", command=self._start_extract)
        self.extract_button.pack(side=tk.RIGHT)

    def _choose_video(self):
        path = filedialog.askopenfilename(title="Choose video", filetypes=VIDEO_TYPES)
        if not path:
            return
        self.video_var.set(path)

        stem = Path(path).stem
        self.output_var.set(str(Path(path).parent / f"{stem}_sampled_frames"))
        self._load_metadata(path)

    def _choose_output(self):
        initial = self.output_var.get().strip() or os.getcwd()
        path = filedialog.askdirectory(title="Choose output folder", initialdir=initial)
        if path:
            self.output_var.set(path)

    def _load_metadata(self, path: str):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            self.duration_seconds = None
            self.meta_var.set("Could not read video metadata.")
            return

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()

        duration = (frame_count / fps) if fps > 0 and frame_count > 0 else None
        self.fps = fps if fps > 0 else None
        self.total_frames = frame_count if frame_count > 0 else None
        self.duration_seconds = duration

        if duration is not None:
            self.end_var.set(format_time(duration))
            self.meta_var.set(
                f"Duration {format_time(duration)}  ·  {fps:.3f} fps  ·  {frame_count:,} frames"
            )
        else:
            self.meta_var.set("Video opened; duration metadata is unavailable.")
        self._refresh_estimate()

    def _refresh_estimate(self):
        try:
            start = parse_time(self.start_var.get())
            period = float(self.period_var.get())
            if not math.isfinite(period) or period <= 0:
                raise ValueError
            end_text = self.end_var.get().strip()
            end = parse_time(end_text) if end_text else self.duration_seconds
            if end is None or end < start:
                raise ValueError
            count = int(math.floor((end - start) / period + 1e-9)) + 1
            suffix = ""
            if self.fps and period < (1.0 / self.fps) * 0.999:
                suffix = f"  ·  period is below one source frame ({1.0 / self.fps:.4f} s)"
            self.estimate_var.set(
                f"Estimated output: {count:,} image{'s' if count != 1 else ''} from "
                f"{format_time(start)} to {format_time(end)}{suffix}"
            )
        except Exception:
            self.estimate_var.set("")

    def _validate(self):
        video_path = self.video_var.get().strip()
        if not video_path or not os.path.isfile(video_path):
            raise ValueError("Choose a valid video file.")

        output_dir = self.output_var.get().strip()
        if not output_dir:
            raise ValueError("Choose an output folder.")

        start = parse_time(self.start_var.get())
        end_text = self.end_var.get().strip()
        end = parse_time(end_text) if end_text else self.duration_seconds
        if end is None:
            raise ValueError("End time is required when video duration is unavailable.")
        if end <= start:
            raise ValueError("End time must be greater than start time.")
        if self.duration_seconds is not None:
            end = min(end, self.duration_seconds)
            if start >= self.duration_seconds:
                raise ValueError("Start time is outside the video duration.")

        period = float(self.period_var.get())
        if not math.isfinite(period) or period <= 0:
            raise ValueError("Sampling period must be greater than zero.")
        if self.fps:
            min_period = 1.0 / self.fps
            if period < min_period * 0.999:
                raise ValueError(
                    f"Sampling period is shorter than one source frame. "
                    f"For {self.fps:.3f} fps, use at least {min_period:.6f} seconds."
                )

        return video_path, output_dir, start, end, period, self.format_var.get()

    def _start_extract(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            args = self._validate()
        except Exception as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self.cancel_event.clear()
        self.progress["value"] = 0
        self.extract_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.status_var.set("Starting extraction…")

        self.worker = threading.Thread(target=self._extract_worker, args=args, daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_event.set()
        self.status_var.set("Cancelling…")

    def _extract_worker(self, video_path, output_dir, start, end, period, image_format):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            self._finish_error("Could not open the video.")
            return

        try:
            os.makedirs(output_dir, exist_ok=True)

            # One seek to the requested start. From there we decode forward so long
            # GOP-compressed recordings do not pay the random-seek cost for every sample.
            cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)

            fps = float(cap.get(cv2.CAP_PROP_FPS) or self.fps or 30.0)
            frame_interval = 1.0 / max(fps, 1e-9)
            next_sample = start
            estimated = int(math.floor((end - start) / period + 1e-9)) + 1
            saved = 0
            frame_index_after_seek = 0

            extension = ".png" if image_format == "PNG" else ".jpg"
            write_params = [] if image_format == "PNG" else [cv2.IMWRITE_JPEG_QUALITY, 95]

            while not self.cancel_event.is_set() and next_sample <= end + 1e-9:
                # Decode forward until reaching the next requested sample time.
                # grab() avoids materializing every skipped frame as a BGR image.
                reached = False
                while not self.cancel_event.is_set():
                    ok = cap.grab()
                    if not ok:
                        break
                    frame_index_after_seek += 1
                    pos_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
                    current_time = pos_ms / 1000.0

                    # Some OpenCV backends report POS_MSEC poorly. Fall back to an
                    # FPS-based estimate relative to the requested starting point.
                    if current_time <= 0.0:
                        current_time = start + frame_index_after_seek * frame_interval

                    if current_time + frame_interval * 0.5 >= next_sample:
                        reached = True
                        break
                    if current_time > end + frame_interval:
                        break

                if not reached:
                    break

                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break

                timestamp_ms = int(round(next_sample * 1000.0))
                filename = f"frame_{saved:06d}_t{timestamp_ms:012d}ms{extension}"
                output_path = os.path.join(output_dir, filename)
                if not cv2.imwrite(output_path, frame, write_params):
                    raise RuntimeError(f"Failed to write {output_path}")

                saved += 1
                progress = min(100.0, saved * 100.0 / max(estimated, 1))
                self.root.after(
                    0,
                    self._update_progress,
                    progress,
                    f"Saved {saved:,} / about {estimated:,} frames  ·  {format_time(next_sample)}",
                )
                next_sample = start + saved * period

            if self.cancel_event.is_set():
                self.root.after(0, self._finish_cancelled, saved, output_dir)
            else:
                self.root.after(0, self._finish_success, saved, output_dir)
        except Exception as exc:
            self._finish_error(str(exc))
        finally:
            cap.release()

    def _update_progress(self, value: float, text: str):
        self.progress["value"] = value
        self.status_var.set(text)

    def _finish_success(self, saved: int, output_dir: str):
        self.progress["value"] = 100
        self.extract_button.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)
        self.status_var.set(f"Done. Saved {saved:,} frames to {output_dir}")
        messagebox.showinfo("Extraction complete", f"Saved {saved:,} frames to:\n{output_dir}")

    def _finish_cancelled(self, saved: int, output_dir: str):
        self.extract_button.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)
        self.status_var.set(f"Cancelled after {saved:,} frames. Existing files were kept.")

    def _finish_error(self, text: str):
        self.root.after(0, self._finish_error_ui, text)

    def _finish_error_ui(self, text: str):
        self.extract_button.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)
        self.status_var.set("Extraction failed.")
        messagebox.showerror("Extraction failed", text)


def main():
    root = tk.Tk()
    FrameSamplerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
