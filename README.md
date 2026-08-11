# Brightness Extractor GUI

PySide6/QML batch application that fits one weighted K-lines palette and label map per image.

## Run and test

`run.bat` creates the project virtual environment and starts the app. Run tests with:

```powershell
.\.venv\Scripts\python -m pytest
```

## Version-3 output bundle

Each run is stored under `output root/original name/timestamp/` and contains the original copy, `main_color.png`, `labels.png`, `threshold_mask.png`, `input_alpha.png`, `brightness_k_linear.png`, `brightness_k_srgb.png`, `asset_alpha_linear_k.png`, `asset_alpha_srgb_k.png`, `reconstruction_original_alpha.png`, and `palette.json`.

Input RGB is straight/unassociated sRGB (untagged images are assumed sRGB). RGB files use input alpha `A = 1`; RGBA files retain their original alpha. RGB/RGBA output PNGs embed the sRGB IEC61966-2.1 profile. One fitted palette and label map produce both projection coefficients: `k_l` in Linear RGB and `k_s` in encoded sRGB.

`T_eff` is the sole threshold term in the output contract: it is the smooth threshold mask `T` when **출력에 임계값 페이드 적용** is enabled, otherwise `1`. Raw `k` values are retained internally, including values above 1. Only the stored 16-bit coefficient maps and final alpha/RGB values are clipped.

- `asset_alpha_linear_k.png`: palette RGB plus `clip(A * T_eff * k_l_raw, 0, 1)` alpha for linear-light compositing.
- `asset_alpha_srgb_k.png`: palette RGB plus `clip(A * T_eff * k_s_raw, 0, 1)` alpha for encoded-sRGB multiplication compatibility.
- `reconstruction_original_alpha.png`: RGB is `encode_if_needed(clip(T_eff * k_working_raw * representative_working, 0, 1))`; alpha is the retained original `A`.

The metadata records the exact formulas, threshold state, palette representations, and per-cluster unclamped-coefficient statistics. `main_color.png` is a categorical palette/label map, not a compositing asset. N is limited to 256 (1–64 is the normal operating range; 65–256 shows a performance warning).
