# Brightness Extractor GUI

PySide6/QML batch application that fits one weighted K-lines palette and label map per image.

## Run and test

`run.bat` creates the project virtual environment and starts the app. Run tests with:

```powershell
.\.venv\Scripts\python -m pytest
```

## Version-3 output bundle

Each run is stored under `output root/original name/timestamp/` and contains the original copy, `main_color.png`, `labels.png`, `threshold_mask.png`, `input_alpha.png`, `brightness_k_linear.png`, `brightness_k_srgb.png`, `asset_alpha_linear_k.png`, `asset_alpha_srgb_k.png`, `reconstruction_original_alpha.png`, and `palette.json`.

Input RGB is assumed to be straight/unassociated sRGB. RGB files use input alpha `A = 1`; RGBA files retain their original alpha. `T` is the threshold-only mask. One fitted palette and label map produce both projection coefficients: `k_l` in Linear RGB and `k_s` in sRGB.

- `asset_alpha_linear_k.png`: palette RGB plus `clip(A * T * k_l)` alpha for linear-light compositing.
- `asset_alpha_srgb_k.png`: palette RGB plus `clip(A * T * k_s)` alpha for encoded-sRGB multiplication compatibility.
- `reconstruction_original_alpha.png`: fitted brightness is baked into RGB; alpha is the retained original `A`.

The metadata records the exact formulas, palette representations, and unclamped-coefficient statistics. `main_color.png` is a categorical palette/label map, not a compositing asset.
