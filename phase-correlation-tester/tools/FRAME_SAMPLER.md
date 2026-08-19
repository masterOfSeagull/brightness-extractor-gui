# Video Frame Sampler

Standalone helper GUI for extracting periodically sampled frames from a video without loading the whole recording into memory.

## Inputs

- Video file
- Output folder
- Start time
- End time
- Sampling period in seconds
- PNG or JPEG output

Time fields accept raw seconds, `MM:SS`, or `HH:MM:SS`. Choosing a video fills the end time from its metadata automatically.

## Run on Windows

Install the one Python dependency once:

```powershell
py -m pip install -r requirements-frame-sampler.txt
```

Then double-click:

```text
run_frame_sampler.bat
```

or run directly:

```powershell
py frame_sampler_gui.py
```

## Extraction behavior

The utility seeks once to the requested start time and then decodes forward sequentially. Frames between requested samples are grabbed without materializing them as full BGR images; only requested samples are retrieved and written to disk. This avoids repeatedly performing expensive random seeks on long GOP-compressed screen recordings.

Output names include both an ordinal and requested timestamp, for example:

```text
frame_000000_t000012500ms.png
frame_000001_t000013500ms.png
frame_000002_t000014500ms.png
```

The GUI shows the estimated output count, progress, and supports cancellation. Existing extracted images are kept if extraction is cancelled.
