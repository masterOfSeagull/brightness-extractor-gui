"""Faithful, testable GUI adaptation of the supplied brightness_extractor.py.

The K-lines configuration defaults and output format intentionally match the
source script.  The path decoder additionally preserves 16-bit RGB/RGBA data.
"""
from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal, Mapping

import cv2
import numpy as np
from PIL import Image, ImageOps

WorkingSpace = Literal["linear_rgb", "srgb"]
BrightnessSpace = Literal["srgb", "working"]
BrightnessMetric = Literal["max", "luminance"]
FitMode = Literal["atmosphere", "equal_hue", "rgb_mse"]
ProgressCallback = Callable[[str, float], None]


class ExtractionCancelled(RuntimeError):
    """The GUI requested cooperative cancellation."""


@dataclass(frozen=True)
class ExtractorConfig:
    threshold_low: float = 0.04
    threshold_high: float = 0.14
    brightness_metric: BrightnessMetric = "max"
    brightness_space: BrightnessSpace = "srgb"
    working_space: WorkingSpace = "linear_rgb"
    fit_mode: FitMode = "atmosphere"
    atmosphere_weight_floor: float = 0.20
    atmosphere_weight_power: float = 0.50
    apply_soft_mask_to_output: bool = True
    clamp_brightness: bool = True
    restarts: int = 16
    max_iterations: int = 100
    convergence_tolerance: float = 1e-7
    random_seed: int = 7
    fit_sample_limit: int = 250_000
    chunk_size: int = 500_000

    def validate(self, color_count: int = 1) -> None:
        _validate_config(self, color_count)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "ExtractorConfig":
        if not isinstance(values, dict):
            raise ValueError("settings must be an object")
        if set(values) - set(cls.__dataclass_fields__):
            raise ValueError("unknown extractor setting")
        config = cls(**values)
        config.validate()
        return config


@dataclass
class ExtractionResult:
    brightness_map: np.ndarray
    main_color_map: np.ndarray
    labels: np.ndarray
    soft_mask: np.ndarray
    palette: np.ndarray
    config: ExtractorConfig
    statistics: dict[str, object] = field(default_factory=dict)
    source_bit_depth: int = 8

    def reconstruction(self) -> np.ndarray:
        return self.main_color_map * self.brightness_map[..., None]

    def palette_srgb(self) -> np.ndarray:
        return _linear_to_srgb(self.palette) if self.config.working_space == "linear_rgb" else np.clip(self.palette, 0, 1)

    def save(self, output_dir: str | Path, source_path: str | Path | None = None) -> dict[str, Path]:
        """Save a self-contained extraction bundle with concise, stable asset names."""
        target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
        paths = {"brightness": target / "brightness.png", "main_color": target / "main_color.png",
                 "labels": target / "labels.png", "soft_mask": target / "soft_mask.png",
                 "asset_rgba": target / "asset_rgba.png", "reconstruction_green": target / "reconstruction_green.png",
                 "palette": target / "palette.json"}
        if source_path is not None:
            source = Path(source_path)
            if source.is_file():
                paths["original"] = target / f"original{source.suffix.lower()}"
                shutil.copy2(source, paths["original"])
        _save_gray16(paths["brightness"], self.brightness_map); _save_gray16(paths["soft_mask"], self.soft_mask)
        Image.fromarray(np.where(self.labels >= 0, self.labels + 1, 0).astype(np.uint16), mode="I;16").save(paths["labels"])
        palette_srgb = self.palette_srgb(); valid = self.labels >= 0
        color_srgb = np.zeros((*self.labels.shape, 3), dtype=np.float32)
        if np.any(valid): color_srgb[valid] = palette_srgb[self.labels[valid]]
        color_u8 = _to_u8(color_srgb)
        Image.fromarray(np.dstack((color_u8, np.where(valid, 255, 0).astype(np.uint8))), mode="RGBA").save(paths["main_color"])
        Image.fromarray(np.dstack((color_u8, _to_u8(self.brightness_map))), mode="RGBA").save(paths["asset_rgba"])
        reconstruction = np.clip(self.reconstruction(), 0, 1)
        if self.config.working_space == "linear_rgb": reconstruction = _linear_to_srgb(reconstruction)
        green_screen = np.zeros_like(reconstruction); green_screen[..., 1] = 1
        green_screen[valid] = reconstruction[valid]
        Image.fromarray(_to_u8(green_screen), mode="RGB").save(paths["reconstruction_green"])
        metadata = {"format_version": 2, "working_space": self.config.working_space, "null_label_in_memory": -1,
                    "null_label_in_png": 0, "png_palette_labels": "1..N correspond to JSON palette entries 0..N-1",
                    "config": asdict(self.config), "palette_working_rgb": self.palette.astype(float).tolist(),
                    "palette_srgb": palette_srgb.astype(float).tolist(), "palette_srgb_8bit": _to_u8(palette_srgb).astype(int).tolist(),
                    "statistics": _json_safe({**self.statistics, "source_bit_depth": self.source_bit_depth})}
        paths["palette"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return paths


def load_image(path: str | Path) -> tuple[np.ndarray, int]:
    """Load path input as normalized RGBA without an implicit 16-bit downcast."""
    try:
        with Image.open(path) as opened: orientation = int(opened.getexif().get(274, 1))
        decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if decoded is not None and decoded.ndim in (2, 3):
            if decoded.ndim == 3 and decoded.shape[2] == 3: decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
            elif decoded.ndim == 3 and decoded.shape[2] == 4: decoded = cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGBA)
            decoded = _orient_array(decoded, orientation)
            return _array_to_rgba(decoded), 16 if decoded.dtype.itemsize > 1 else 8
        with Image.open(path) as opened:
            return _array_to_rgba(np.asarray(ImageOps.exif_transpose(opened).copy())), 8
    except (OSError, ValueError, cv2.error) as error:
        raise ValueError(f"이미지를 읽을 수 없습니다: {Path(path).name} ({error})") from error


def brightness_threshold_candidates(path: str | Path, config: ExtractorConfig,
                                  top_percentages: tuple[int, ...] = tuple(range(10, 101, 10))) -> list[tuple[int, float]]:
    """Return B cutoffs whose retained pixels represent the requested brightest proportions."""
    rgba, _ = load_image(path)
    srgb, alpha = rgba[..., :3], rgba[..., 3]
    working = _srgb_to_linear(srgb) if config.working_space == "linear_rgb" else srgb
    brightness_source = srgb if config.brightness_space == "srgb" else working
    brightness = _pixel_brightness(brightness_source, config.brightness_metric)
    visible = brightness[alpha > 0]
    if not visible.size:
        raise ValueError("투명하지 않은 픽셀이 없습니다.")
    return [(percent, float(np.quantile(visible, 1 - percent / 100))) for percent in top_percentages]


def extract_brightness(image: str | Path | Image.Image | np.ndarray, color_count: int,
                       config: ExtractorConfig | None = None, progress: ProgressCallback | None = None,
                       cancel: Callable[[], bool] | None = None, source_bit_depth: int = 8) -> ExtractionResult:
    cfg = config or ExtractorConfig(); _validate_config(cfg, color_count); _check_cancel(cancel); _report(progress, "load", 0)
    srgb, input_alpha = _load_image(image)
    height, width, _ = srgb.shape
    working = _srgb_to_linear(srgb) if cfg.working_space == "linear_rgb" else srgb
    brightness_source = srgb if cfg.brightness_space == "srgb" else working
    brightness = _pixel_brightness(brightness_source, cfg.brightness_metric)
    soft_mask = np.clip(_smoothstep(cfg.threshold_low, cfg.threshold_high, brightness) * input_alpha, 0, 1).astype(np.float32)
    pixels, flat_brightness, flat_mask = working.reshape(-1, 3), brightness.reshape(-1), soft_mask.reshape(-1)
    norms = np.linalg.norm(pixels, axis=1); valid_indices = np.flatnonzero((flat_mask > 0) & (norms > 1e-12))
    if not valid_indices.size: raise ValueError("No pixels survive the threshold. Lower threshold_low/threshold_high or check the input image.")
    if color_count > valid_indices.size: raise ValueError(f"color_count={color_count} exceeds the {valid_indices.size} retained pixels.")
    rng = np.random.default_rng(cfg.random_seed)
    sample_indices = np.sort(rng.choice(valid_indices, size=cfg.fit_sample_limit, replace=False)) if cfg.fit_sample_limit > 0 and valid_indices.size > cfg.fit_sample_limit else valid_indices
    sample_pixels = pixels[sample_indices].astype(np.float64, copy=False); sample_norms = np.linalg.norm(sample_pixels, axis=1)
    sample_directions = sample_pixels / sample_norms[:, None]
    weights = _fitting_weights(cfg, flat_mask[sample_indices].astype(np.float64), flat_brightness[sample_indices].astype(np.float64), sample_norms)
    _report(progress, "fit", .05)
    palette_units, objective, iterations, best_restart = _fit_k_lines(sample_directions, weights, color_count, cfg, rng, lambda done: _report(progress, "fit", done / cfg.restarts), cancel)
    palette = np.clip(palette_units / np.max(palette_units, axis=1, keepdims=True), 0, 1).astype(np.float32)
    labels_flat = np.full(pixels.shape[0], -1, dtype=np.int32); k_raw = np.zeros(pixels.shape[0], dtype=np.float32); _report(progress, "classify", 0)
    for start in range(0, valid_indices.size, cfg.chunk_size):
        _check_cancel(cancel); end = min(start + cfg.chunk_size, valid_indices.size); idx = valid_indices[start:end]
        chunk = pixels[idx].astype(np.float64, copy=False); directions = chunk / np.linalg.norm(chunk, axis=1, keepdims=True)
        chunk_labels = np.argmax((directions @ palette_units.T) ** 2, axis=1); labels_flat[idx] = chunk_labels
        selected = palette[chunk_labels].astype(np.float64, copy=False)
        k_raw[idx] = np.maximum(np.sum(chunk * selected, axis=1) / np.sum(selected * selected, axis=1), 0).astype(np.float32)
        _report(progress, "classify", end / valid_indices.size)
    model_k = k_raw.copy(); over_one = int(np.count_nonzero(model_k[valid_indices] > 1))
    if cfg.clamp_brightness: np.clip(model_k, 0, 1, out=model_k)
    output_k = model_k * flat_mask if cfg.apply_soft_mask_to_output else model_k * input_alpha.reshape(-1) * (labels_flat >= 0)
    if cfg.clamp_brightness: np.clip(output_k, 0, 1, out=output_k)
    colors = np.zeros_like(pixels, dtype=np.float32); colors[valid_indices] = palette[labels_flat[valid_indices]]
    raw_reconstruction = colors[valid_indices] * k_raw[valid_indices, None]; output_reconstruction = colors[valid_indices] * output_k[valid_indices, None]
    original = pixels[valid_indices]; cluster_sizes = np.bincount(labels_flat[valid_indices], minlength=color_count).astype(int)
    statistics = {"image_width": width, "image_height": height, "total_pixels": int(width * height), "retained_pixels": int(valid_indices.size),
                  "fit_sample_pixels": int(sample_indices.size), "cluster_pixel_counts": cluster_sizes.tolist(),
                  "cluster_pixel_fractions": (cluster_sizes / valid_indices.size).tolist(), "weighted_angular_fit_objective": float(objective),
                  "raw_projection_mse_working_rgb": float(np.mean((original - raw_reconstruction) ** 2)),
                  "saved_output_mse_working_rgb": float(np.mean((original - output_reconstruction) ** 2)), "raw_projection_values_over_one": over_one,
                  "best_restart_zero_based": int(best_restart), "best_restart_iterations": int(iterations),
                  "near_duplicate_palette_pairs_zero_based": _find_duplicate_palette_pairs(palette_units)}
    _report(progress, "done", 1)
    return ExtractionResult(output_k.reshape(height, width).astype(np.float32), colors.reshape(height, width, 3), labels_flat.reshape(height, width), soft_mask, palette, cfg, statistics, source_bit_depth)


def _fit_k_lines(directions, weights, color_count, config, rng, progress, cancel):
    best_centers, best_objective, best_iterations, best_restart = None, math.inf, 0, -1
    for restart in range(config.restarts):
        _check_cancel(cancel); centers = _k_lines_plus_plus(directions, weights, color_count, rng); previous_labels, previous_objective = None, math.inf
        for iteration in range(1, config.max_iterations + 1):
            _check_cancel(cancel); labels = np.argmax((directions @ centers.T) ** 2, axis=1); centers = _update_centers(directions, weights, labels, centers, rng)
            residuals = np.maximum(1 - np.max((directions @ centers.T) ** 2, axis=1), 0); objective = float(np.sum(weights * residuals) / np.sum(weights))
            unchanged = previous_labels is not None and np.array_equal(labels, previous_labels)
            relative = abs(previous_objective - objective) / max(abs(previous_objective), 1e-15) if math.isfinite(previous_objective) else math.inf
            previous_labels = labels
            if unchanged or (math.isfinite(previous_objective) and relative <= config.convergence_tolerance): break
            previous_objective = objective
        residuals = np.maximum(1 - np.max((directions @ centers.T) ** 2, axis=1), 0); objective = float(np.sum(weights * residuals) / np.sum(weights))
        if objective < best_objective: best_centers, best_objective, best_iterations, best_restart = centers.copy(), objective, iteration, restart
        progress(restart + 1)
    if best_centers is None: raise RuntimeError("K-lines failed to produce a palette")
    return best_centers, best_objective, best_iterations, best_restart


def _k_lines_plus_plus(directions, weights, color_count, rng):
    count = directions.shape[0]; centers = np.empty((color_count, 3), dtype=np.float64); probability = weights / np.sum(weights)
    first = int(rng.choice(count, p=probability)); centers[0] = directions[first]; selected = {first}; nearest = np.ones(count, dtype=np.float64)
    for center_index in range(1, color_count):
        nearest = np.minimum(nearest, np.maximum(1 - (directions @ centers[center_index - 1]) ** 2, 0)); score = weights * nearest; total = float(np.sum(score))
        if total <= 1e-15:
            remaining = np.array([i for i in range(count) if i not in selected]); chosen = int(rng.choice(remaining)) if remaining.size else int(rng.integers(count))
        else: chosen = int(rng.choice(count, p=score / total))
        centers[center_index] = directions[chosen]; selected.add(chosen)
    return centers


def _update_centers(directions, weights, labels, old, rng):
    updated = np.empty_like(old); empty = []
    for cluster in range(old.shape[0]):
        members = labels == cluster
        if not np.any(members): empty.append(cluster); continue
        d, w = directions[members], weights[members]; values, vectors = np.linalg.eigh((d * w[:, None]).T @ d); vector = vectors[:, int(np.argmax(values))]
        if np.sum(vector) < 0: vector = -vector
        vector = np.maximum(vector, 0); norm = np.linalg.norm(vector); updated[cluster] = vector / norm if norm > 1e-15 else old[cluster]
    if empty:
        candidate = weights * np.maximum(1 - np.max((directions @ old.T) ** 2, axis=1), 0); used = set()
        for cluster in empty:
            available = candidate.copy()
            if used: available[np.fromiter(used, dtype=np.int64)] = -1
            chosen = int(np.argmax(available))
            if available[chosen] <= 1e-15:
                choices = np.array([i for i in range(directions.shape[0]) if i not in used]); chosen = int(rng.choice(choices)) if choices.size else int(rng.integers(directions.shape[0]))
            updated[cluster] = directions[chosen]; used.add(chosen)
    return updated


def _load_image(image):
    if isinstance(image, (str, Path)):
        rgba, _ = load_image(image); return rgba[..., :3], rgba[..., 3]
    if isinstance(image, Image.Image):
        rgba = _array_to_rgba(np.asarray(ImageOps.exif_transpose(image).convert("RGBA")))
        return rgba[..., :3], rgba[..., 3]
    if isinstance(image, np.ndarray):
        rgba = _array_to_rgba(image); return rgba[..., :3], rgba[..., 3]
    raise TypeError("image must be a path, PIL.Image, or NumPy array")


def _array_to_rgba(array):
    array = np.asarray(array)
    if array.dtype.kind not in "uifb": raise ValueError("unsupported image sample type")
    if array.dtype.kind in "ui": value = array.astype(np.float32) / float(np.iinfo(array.dtype).max)
    else:
        value = array.astype(np.float32)
        if not np.all(np.isfinite(value)) or np.min(value) < 0 or np.max(value) > 1: raise ValueError("floating image values must be finite and in [0,1]")
    if value.ndim == 2: return np.dstack((value, value, value, np.ones(value.shape, dtype=np.float32)))
    if value.ndim != 3 or value.shape[2] not in (3, 4): raise ValueError("image must have shape HxWx3 or HxWx4")
    return np.dstack((value, np.ones(value.shape[:2], dtype=np.float32))) if value.shape[2] == 3 else value


def _orient_array(array, orientation):
    if orientation == 2: return np.fliplr(array)
    if orientation == 3: return np.rot90(array, 2)
    if orientation == 4: return np.flipud(array)
    if orientation == 5: return np.swapaxes(array, 0, 1)
    if orientation == 6: return np.rot90(array, 3)
    if orientation == 7: return np.fliplr(np.swapaxes(array, 0, 1))
    if orientation == 8: return np.rot90(array)
    return array


def _pixel_brightness(rgb, metric):
    if metric == "max": return np.max(rgb, axis=-1).astype(np.float32)
    if metric == "luminance": return np.tensordot(rgb, np.array([.2126, .7152, .0722], dtype=np.float32), axes=([-1], [0])).astype(np.float32)
    raise ValueError(f"Unsupported brightness metric: {metric}")


def _fitting_weights(config, mask, brightness, norms):
    if config.fit_mode == "atmosphere": weights = mask * (config.atmosphere_weight_floor + (1 - config.atmosphere_weight_floor) * np.power(np.clip(brightness, 0, 1), config.atmosphere_weight_power))
    elif config.fit_mode == "equal_hue": weights = mask
    elif config.fit_mode == "rgb_mse": weights = mask * norms * norms
    else: raise ValueError(f"Unsupported fit mode: {config.fit_mode}")
    return np.maximum(weights, 1e-15).astype(np.float64)


def _smoothstep(low, high, value):
    t = np.clip((value - low) / (high - low), 0, 1); return (t * t * (3 - 2 * t)).astype(np.float32)
def _srgb_to_linear(value):
    value = np.asarray(value, dtype=np.float32); return np.where(value <= .04045, value / 12.92, np.power((value + .055) / 1.055, 2.4)).astype(np.float32)
def _linear_to_srgb(value):
    value = np.clip(np.asarray(value, dtype=np.float32), 0, 1); return np.where(value <= .0031308, 12.92 * value, 1.055 * np.power(value, 1 / 2.4) - .055).astype(np.float32)
def _save_gray16(path, value): Image.fromarray(np.round(np.clip(value, 0, 1) * 65535).astype(np.uint16), mode="I;16").save(path)
def _to_u8(value): return np.round(np.clip(value, 0, 1) * 255).astype(np.uint8)
def _find_duplicate_palette_pairs(palette, cosine_threshold=.99999): return [[a, b] for a in range(palette.shape[0]) for b in range(a + 1, palette.shape[0]) if float(np.dot(palette[a], palette[b])) >= cosine_threshold]
def _check_cancel(cancel):
    if cancel and cancel(): raise ExtractionCancelled("Extraction cancelled")
def _report(progress, stage, fraction):
    if progress: progress(stage, float(np.clip(fraction, 0, 1)))
def _json_safe(value):
    if isinstance(value, Mapping): return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    return value
def _validate_config(config, color_count):
    if not 1 <= color_count <= 65_534: raise ValueError("color_count must be between 1 and 65,534")
    if not 0 <= config.threshold_low < config.threshold_high <= 1: raise ValueError("thresholds must satisfy 0 <= low < high <= 1")
    if config.brightness_metric not in ("max", "luminance"): raise ValueError("brightness_metric must be 'max' or 'luminance'")
    if config.brightness_space not in ("srgb", "working"): raise ValueError("brightness_space must be 'srgb' or 'working'")
    if config.working_space not in ("linear_rgb", "srgb"): raise ValueError("working_space must be 'linear_rgb' or 'srgb'")
    if config.fit_mode not in ("atmosphere", "equal_hue", "rgb_mse"): raise ValueError("unsupported fit mode")
    if not 0 <= config.atmosphere_weight_floor <= 1 or config.atmosphere_weight_power < 0: raise ValueError("invalid atmosphere weighting")
    if config.restarts < 1 or config.max_iterations < 1 or config.convergence_tolerance < 0 or config.fit_sample_limit < 0 or config.chunk_size < 1: raise ValueError("invalid convergence, restart, sampling, or chunk setting")


def save_result_bundle(result: ExtractionResult, output_dir: str | Path, source_path: str | Path, color_count: int, config: ExtractorConfig) -> Path:
    """Compatibility helper for the queue's self-contained result folder."""
    result.save(output_dir, source_path)
    return Path(output_dir)
