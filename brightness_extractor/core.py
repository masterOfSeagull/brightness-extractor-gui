"""Version-3 weighted K-lines extraction core with explicit output contracts."""
from __future__ import annotations

import json
import math
import shutil
import uuid
from io import BytesIO
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal, Mapping

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

WorkingSpace = Literal["linear_rgb", "srgb"]
BrightnessSpace = Literal["srgb", "working"]
BrightnessMetric = Literal["max", "luminance"]
FitMode = Literal["atmosphere", "equal_hue", "rgb_mse"]
ProgressCallback = Callable[[str, float], None]
MAX_PALETTE_SIZE = 256


def _srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


class ExtractionCancelled(RuntimeError):
    """The GUI requested cooperative cancellation."""


@dataclass(frozen=True)
class ImageLoadInfo:
    source_bit_depth: int
    processing_bit_depth: int
    input_profile_status: str
    color_conversion_applied: bool


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
        values = dict(values)
        # Version-2 settings exposed this misleading switch. PNG maps and alpha
        # are always clipped at save time; retain raw coefficients internally.
        values.pop("clamp_brightness", None)
        if set(values) - set(cls.__dataclass_fields__):
            raise ValueError("unknown extractor setting")
        config = cls(**values)
        config.validate()
        return config


@dataclass
class ExtractionResult:
    palette_working: np.ndarray
    palette_linear: np.ndarray
    palette_srgb: np.ndarray
    labels: np.ndarray
    threshold_mask: np.ndarray
    input_alpha: np.ndarray
    k_linear_raw: np.ndarray
    k_srgb_raw: np.ndarray
    main_color_map_working: np.ndarray
    config: ExtractorConfig
    statistics: dict[str, object] = field(default_factory=dict)
    source_bit_depth: int = 8
    processing_bit_depth: int = 8
    input_profile_status: str = "untagged_assumed_srgb"
    color_conversion_applied: bool = False

    @property
    def valid_mask(self) -> np.ndarray: return self.labels >= 0
    @property
    def palette(self) -> np.ndarray: return self.palette_working
    @property
    def main_color_map(self) -> np.ndarray: return self.main_color_map_working
    @property
    def soft_mask(self) -> np.ndarray: return self.threshold_mask * self.input_alpha

    def _asset_alpha(self, coefficient: np.ndarray) -> np.ndarray:
        return np.clip(self.input_alpha * self.effective_threshold_factor * coefficient * self.valid_mask, 0, 1).astype(np.float32)

    @property
    def effective_threshold_factor(self) -> np.ndarray | float:
        """The one threshold term shared by every Version-3 output equation."""
        return self.threshold_mask if self.config.apply_soft_mask_to_output else 1.0

    def linear_asset_alpha(self) -> np.ndarray: return self._asset_alpha(self.k_linear_raw)
    def srgb_asset_alpha(self) -> np.ndarray: return self._asset_alpha(self.k_srgb_raw)

    def reconstruction_working(self) -> np.ndarray:
        coefficient = self.k_linear_raw if self.config.working_space == "linear_rgb" else self.k_srgb_raw
        rgb = self.main_color_map_working * coefficient[..., None]
        rgb *= np.asarray(self.effective_threshold_factor)[..., None] if self.config.apply_soft_mask_to_output else 1.0
        return np.clip(rgb, 0, 1)

    def reconstruction_original_alpha_rgba(self) -> np.ndarray:
        rgb = self.reconstruction_working()
        if self.config.working_space == "linear_rgb": rgb = _linear_to_srgb(rgb)
        alpha = np.where(self.valid_mask, self.input_alpha, 0).astype(np.float32)
        rgb[alpha == 0] = 0
        return np.dstack((_to_u8(rgb), _to_u8(alpha)))

    def reconstruction(self) -> np.ndarray:
        """Compatibility view: configured-working-space reconstruction."""
        return self.reconstruction_working()

    def save(self, output_dir: str | Path, source_path: str | Path | None = None,
             cancel: Callable[[], bool] | None = None, progress: Callable[[str, float], None] | None = None) -> dict[str, Path]:
        """Save a self-contained extraction bundle with concise, stable asset names."""
        final_target = Path(output_dir)
        if final_target.exists(): raise FileExistsError(f"result directory already exists: {final_target}")
        temporary = final_target.parent / f".{final_target.name}.partial-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True)
        target = temporary
        paths = {"main_color": target / "main_color.png", "labels": target / "labels.png",
                 "threshold_mask": target / "threshold_mask.png", "input_alpha": target / "input_alpha.png",
                 "brightness_k_linear": target / "brightness_k_linear.png", "brightness_k_srgb": target / "brightness_k_srgb.png",
                 "asset_alpha_linear_k": target / "asset_alpha_linear_k.png", "asset_alpha_srgb_k": target / "asset_alpha_srgb_k.png",
                 "reconstruction_original_alpha": target / "reconstruction_original_alpha.png", "palette": target / "palette.json"}
        if source_path is not None:
            source = Path(source_path)
            if source.is_file():
                paths["original"] = target / f"original{source.suffix.lower()}"
        completed_steps = 0
        total_steps = 11 + (1 if "original" in paths else 0)
        def write(name: str, action: Callable[[], None]) -> None:
            nonlocal completed_steps
            _check_cancel(cancel); action(); _check_cancel(cancel)
            completed_steps += 1
            if progress: progress(name, completed_steps / total_steps)
        try:
            write("threshold_mask.png", lambda: _save_gray16(paths["threshold_mask"], self.threshold_mask))
            write("input_alpha.png", lambda: _save_gray16(paths["input_alpha"], self.input_alpha))
            write("brightness_k_linear.png", lambda: _save_gray16(paths["brightness_k_linear"], np.where(self.valid_mask, self.k_linear_raw, 0)))
            write("brightness_k_srgb.png", lambda: _save_gray16(paths["brightness_k_srgb"], np.where(self.valid_mask, self.k_srgb_raw, 0)))
            write("labels.png", lambda: Image.fromarray(np.where(self.valid_mask, self.labels + 1, 0).astype(np.uint16)).save(paths["labels"]))
            if "original" in paths: write(paths["original"].name, lambda: shutil.copy2(source_path, paths["original"]))
            valid = self.valid_mask
            color_srgb = np.zeros((*self.labels.shape, 3), dtype=np.float32)
            if np.any(valid): color_srgb[valid] = self.palette_srgb[self.labels[valid]]
            color_u8 = _to_u8(color_srgb)
            write("main_color.png", lambda: _save_srgb_rgba(paths["main_color"], np.dstack((color_u8, np.where(valid, 255, 0).astype(np.uint8)))))
            write("asset_alpha_linear_k.png", lambda: _save_srgb_rgba(paths["asset_alpha_linear_k"], np.dstack((color_u8, _to_u8(self.linear_asset_alpha())))))
            write("asset_alpha_srgb_k.png", lambda: _save_srgb_rgba(paths["asset_alpha_srgb_k"], np.dstack((color_u8, _to_u8(self.srgb_asset_alpha())))))
            write("reconstruction_original_alpha.png", lambda: _save_srgb_rgba(paths["reconstruction_original_alpha"], self.reconstruction_original_alpha_rgba()))
            metadata = {"format_version": 3, "fit_working_space": self.config.working_space, "input_color_profile": self.input_profile_status,
                    "processing_input_space": "sRGB", "output_color_profile": "sRGB IEC61966-2.1",
                    "input_alpha_representation": "straight", "null_label_in_memory": -1,
                    "null_label_in_png": 0, "png_palette_labels": "1..N correspond to JSON palette entries 0..N-1",
                    "config": asdict(self.config), "palette_working_rgb": self.palette_working.astype(float).tolist(),
                    "palette_linear_rgb": self.palette_linear.astype(float).tolist(), "palette_srgb": self.palette_srgb.astype(float).tolist(),
                    "threshold_factor": {"enabled": self.config.apply_soft_mask_to_output, "definition": "T_eff = threshold_mask if enabled, otherwise 1"},
                    "outputs": {"asset_alpha_linear_k.png": {"rgb": "palette_srgb", "alpha": "clip(input_alpha * T_eff * k_linear_raw, 0, 1)", "intended_compositing": "linear-light source-over"},
                                "asset_alpha_srgb_k.png": {"rgb": "palette_srgb", "alpha": "clip(input_alpha * T_eff * k_srgb_raw, 0, 1)", "intended_compositing": "encoded-srgb compatibility"},
                                "reconstruction_original_alpha.png": {"rgb": "encode_if_needed(clip(T_eff * k_working_raw * representative_working, 0, 1))", "alpha": "input_alpha for valid pixels; otherwise 0"}},
                    "statistics": _json_safe({**self.statistics, "source_bit_depth": self.source_bit_depth,
                                                 "processing_bit_depth": self.processing_bit_depth,
                                                 "color_conversion_applied": self.color_conversion_applied})}
            write("palette.json", lambda: paths["palette"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"))
            _check_cancel(cancel)
            final_paths = {name: final_target / path.name for name, path in paths.items()}
            temporary.replace(final_target)
            if progress: progress("published", 1.0)
            return final_paths
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise


def load_image(path: str | Path, *, with_info: bool = False) -> tuple[np.ndarray, int] | tuple[np.ndarray, ImageLoadInfo]:
    """Load path input as normalized RGBA without an implicit 16-bit downcast."""
    try:
        with Image.open(path) as opened:
            orientation = int(opened.getexif().get(274, 1))
            profile = opened.info.get("icc_profile")
            source_depth = 16 if np.asarray(opened).dtype.itemsize > 1 else 8
            if profile:
                source_profile = ImageCms.ImageCmsProfile(BytesIO(profile))
                transform_input = ImageOps.exif_transpose(opened)
                if transform_input.mode not in ("RGB", "RGBA"):
                    transform_input = transform_input.convert("RGBA" if "transparency" in transform_input.info or transform_input.mode in ("P", "LA") else "RGB")
                converted = ImageCms.profileToProfile(transform_input, source_profile, ImageCms.createProfile("sRGB"), outputMode="RGBA")
                rgba = _array_to_rgba(np.asarray(converted.copy()))
                info = ImageLoadInfo(source_depth, 8, "embedded_icc_converted_to_srgb", True)
                return (rgba, info) if with_info else (rgba, info.processing_bit_depth)
        decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if decoded is not None and decoded.ndim in (2, 3):
            if decoded.ndim == 3 and decoded.shape[2] == 3: decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
            elif decoded.ndim == 3 and decoded.shape[2] == 4: decoded = cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGBA)
            decoded = _orient_array(decoded, orientation)
            rgba, depth = _array_to_rgba(decoded), 16 if decoded.dtype.itemsize > 1 else 8
            info = ImageLoadInfo(depth, depth, "untagged_assumed_srgb", False)
            return (rgba, info) if with_info else (rgba, depth)
        with Image.open(path) as opened:
            rgba = _array_to_rgba(np.asarray(ImageOps.exif_transpose(opened).copy()))
            info = ImageLoadInfo(8, 8, "untagged_assumed_srgb", False)
            return (rgba, info) if with_info else (rgba, 8)
    except (OSError, ValueError, ImageCms.PyCMSError, cv2.error) as error:
        raise ValueError(f"이미지를 읽을 수 없습니다: {Path(path).name} ({error})") from error


def brightness_threshold_candidates(path: str | Path, config: ExtractorConfig,
                                  top_percentages: tuple[int, ...] = (60, 45, 30, 20, 10, 8, 6, 5, 3, 1)) -> list[tuple[int, float]]:
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
                       cancel: Callable[[], bool] | None = None, source_bit_depth: int = 8,
                       processing_bit_depth: int | None = None, input_profile_status: str = "untagged_assumed_srgb",
                       color_conversion_applied: bool = False) -> ExtractionResult:
    cfg = config or ExtractorConfig(); _validate_config(cfg, color_count); _check_cancel(cancel); _report(progress, "load", 0)
    if isinstance(image, (str, Path)):
        rgba, info = load_image(image, with_info=True)
        srgb, input_alpha = rgba[..., :3], rgba[..., 3]
        source_bit_depth, processing_bit_depth = info.source_bit_depth, info.processing_bit_depth
        input_profile_status, color_conversion_applied = info.input_profile_status, info.color_conversion_applied
    else:
        srgb, input_alpha = _load_image(image)
    processing_bit_depth = processing_bit_depth or source_bit_depth
    height, width, _ = srgb.shape
    working = _srgb_to_linear(srgb) if cfg.working_space == "linear_rgb" else srgb
    brightness_source = srgb if cfg.brightness_space == "srgb" else working
    brightness = _pixel_brightness(brightness_source, cfg.brightness_metric)
    threshold_mask = _smoothstep(cfg.threshold_low, cfg.threshold_high, brightness)
    effective_mask = (threshold_mask * input_alpha).astype(np.float32)
    pixels, flat_brightness, flat_mask = working.reshape(-1, 3), brightness.reshape(-1), effective_mask.reshape(-1)
    norms = np.linalg.norm(pixels, axis=1); valid_indices = np.flatnonzero((threshold_mask.reshape(-1) > 0) & (input_alpha.reshape(-1) > 0) & (norms > 1e-12))
    if not valid_indices.size: raise ValueError("No pixels survive the threshold. Lower threshold_low/threshold_high or check the input image.")
    if color_count > valid_indices.size: raise ValueError(f"color_count={color_count} exceeds the {valid_indices.size} retained pixels.")
    rng = np.random.default_rng(cfg.random_seed)
    sample_indices = np.sort(rng.choice(valid_indices, size=cfg.fit_sample_limit, replace=False)) if cfg.fit_sample_limit > 0 and valid_indices.size > cfg.fit_sample_limit else valid_indices
    sample_pixels = pixels[sample_indices].astype(np.float64, copy=False); sample_norms = np.linalg.norm(sample_pixels, axis=1)
    sample_directions = sample_pixels / sample_norms[:, None]
    fit_weights = _fitting_weights(cfg, flat_mask[sample_indices].astype(np.float64), flat_brightness[sample_indices].astype(np.float64), sample_norms)
    _report(progress, "fit", .05)
    palette_units, objective, iterations, best_restart = _fit_k_lines(sample_directions, fit_weights, color_count, cfg, rng, lambda done: _report(progress, "fit", done / cfg.restarts), cancel)
    palette_working = np.clip(palette_units / np.max(palette_units, axis=1, keepdims=True), 0, 1).astype(np.float32)
    palette_srgb = _linear_to_srgb(palette_working) if cfg.working_space == "linear_rgb" else palette_working.copy()
    palette_linear = palette_working.copy() if cfg.working_space == "linear_rgb" else _srgb_to_linear(palette_working)
    labels_flat = np.full(pixels.shape[0], -1, dtype=np.int32)
    k_linear_raw = np.zeros(pixels.shape[0], dtype=np.float32); k_srgb_raw = np.zeros(pixels.shape[0], dtype=np.float32)
    cluster_weight_sums = np.zeros(color_count, dtype=np.float64); _report(progress, "classify", 0)
    flat_srgb = srgb.reshape(-1, 3); flat_linear = _srgb_to_linear(srgb).reshape(-1, 3)
    for start in range(0, valid_indices.size, cfg.chunk_size):
        _check_cancel(cancel); end = min(start + cfg.chunk_size, valid_indices.size); idx = valid_indices[start:end]
        chunk = pixels[idx].astype(np.float64, copy=False); directions = chunk / np.linalg.norm(chunk, axis=1, keepdims=True)
        chunk_labels, _ = _best_labels_scores(directions, palette_units); labels_flat[idx] = chunk_labels
        chunk_weights = _fitting_weights(cfg, flat_mask[idx].astype(np.float64), flat_brightness[idx].astype(np.float64), norms[idx])
        cluster_weight_sums += np.bincount(chunk_labels, weights=chunk_weights, minlength=color_count)
        selected_linear = palette_linear[chunk_labels].astype(np.float64, copy=False)
        selected_srgb = palette_srgb[chunk_labels].astype(np.float64, copy=False)
        p_linear, p_srgb = flat_linear[idx], flat_srgb[idx]
        k_linear_raw[idx] = np.maximum(np.sum(p_linear * selected_linear, axis=1) / np.sum(selected_linear * selected_linear, axis=1), 0).astype(np.float32)
        k_srgb_raw[idx] = np.maximum(np.sum(p_srgb * selected_srgb, axis=1) / np.sum(selected_srgb * selected_srgb, axis=1), 0).astype(np.float32)
        _report(progress, "classify", end / valid_indices.size)
    colors = np.zeros_like(pixels, dtype=np.float32); colors[valid_indices] = palette_working[labels_flat[valid_indices]]
    reconstruction_working = colors[valid_indices] * (k_linear_raw[valid_indices, None] if cfg.working_space == "linear_rgb" else k_srgb_raw[valid_indices, None])
    if cfg.apply_soft_mask_to_output: reconstruction_working *= threshold_mask.reshape(-1)[valid_indices, None]
    cluster_sizes = np.bincount(labels_flat[valid_indices], minlength=color_count).astype(int)
    cluster_statistics = []
    assigned_labels = labels_flat[valid_indices]
    for cluster in range(color_count):
        members = assigned_labels == cluster
        raw_linear, raw_srgb = k_linear_raw[valid_indices][members], k_srgb_raw[valid_indices][members]
        cluster_statistics.append({"assigned_pixel_count": int(cluster_sizes[cluster]), "weight_sum": float(cluster_weight_sums[cluster]),
            "k_linear_raw": _coefficient_summary(raw_linear), "k_srgb_raw": _coefficient_summary(raw_srgb),
            "representative_working_rgb": palette_working[cluster].astype(float).tolist(),
            "representative_linear_rgb": palette_linear[cluster].astype(float).tolist(),
            "representative_srgb": palette_srgb[cluster].astype(float).tolist()})
    statistics = {"image_width": width, "image_height": height, "total_pixels": int(width * height), "retained_pixels": int(valid_indices.size),
                  "fit_sample_pixels": int(sample_indices.size), "cluster_pixel_counts": cluster_sizes.tolist(),
                  "cluster_pixel_fractions": (cluster_sizes / valid_indices.size).tolist(), "weighted_angular_fit_objective": float(objective),
                  "raw_projection_mse_linear_rgb": float(np.mean((flat_linear[valid_indices] - palette_linear[labels_flat[valid_indices]] * k_linear_raw[valid_indices, None]) ** 2)),
                  "raw_projection_mse_srgb": float(np.mean((flat_srgb[valid_indices] - palette_srgb[labels_flat[valid_indices]] * k_srgb_raw[valid_indices, None]) ** 2)),
                  "final_reconstruction_mse_working": float(np.mean((pixels[valid_indices] - reconstruction_working) ** 2)),
                  "k_linear_over_one_count": int(np.count_nonzero(k_linear_raw[valid_indices] > 1)),
                  "k_srgb_over_one_count": int(np.count_nonzero(k_srgb_raw[valid_indices] > 1)),
                  "best_restart_zero_based": int(best_restart), "best_restart_iterations": int(iterations),
                  "cluster_statistics": cluster_statistics,
                  "near_duplicate_palette_pairs_zero_based": _find_duplicate_palette_pairs(palette_units)}
    _report(progress, "done", 1)
    return ExtractionResult(palette_working, palette_linear, palette_srgb, labels_flat.reshape(height, width), threshold_mask.astype(np.float32), input_alpha.astype(np.float32),
                            k_linear_raw.reshape(height, width), k_srgb_raw.reshape(height, width), colors.reshape(height, width, 3), cfg, statistics,
                            source_bit_depth, processing_bit_depth, input_profile_status, color_conversion_applied)


def _fit_k_lines(directions, weights, color_count, config, rng, progress, cancel):
    best_centers, best_objective, best_iterations, best_restart = None, math.inf, 0, -1
    for restart in range(config.restarts):
        _check_cancel(cancel); centers = _k_lines_plus_plus(directions, weights, color_count, rng); previous_labels, previous_objective = None, math.inf
        for iteration in range(1, config.max_iterations + 1):
            _check_cancel(cancel); labels, scores = _best_labels_scores(directions, centers); centers = _update_centers(directions, weights, labels, centers, rng)
            _, scores = _best_labels_scores(directions, centers); residuals = np.maximum(1 - scores, 0); objective = float(np.sum(weights * residuals) / np.sum(weights))
            unchanged = previous_labels is not None and np.array_equal(labels, previous_labels)
            relative = abs(previous_objective - objective) / max(abs(previous_objective), 1e-15) if math.isfinite(previous_objective) else math.inf
            previous_labels = labels
            if unchanged or (math.isfinite(previous_objective) and relative <= config.convergence_tolerance): break
            previous_objective = objective
        _, scores = _best_labels_scores(directions, centers); residuals = np.maximum(1 - scores, 0); objective = float(np.sum(weights * residuals) / np.sum(weights))
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
        _, best_scores = _best_labels_scores(directions, old)
        candidate = weights * np.maximum(1 - best_scores, 0); used = set()
        for cluster in empty:
            available = candidate.copy()
            if used: available[np.fromiter(used, dtype=np.int64)] = -1
            chosen = int(np.argmax(available))
            if available[chosen] <= 1e-15:
                choices = np.array([i for i in range(directions.shape[0]) if i not in used]); chosen = int(rng.choice(choices)) if choices.size else int(rng.integers(directions.shape[0]))
            updated[cluster] = directions[chosen]; used.add(chosen)
    return updated


def _best_labels_scores(directions: np.ndarray, centers: np.ndarray, center_block_size: int = 32) -> tuple[np.ndarray, np.ndarray]:
    """Classify without ever allocating a pixel-count × palette-count matrix."""
    labels = np.zeros(directions.shape[0], dtype=np.int32)
    scores = np.full(directions.shape[0], -np.inf, dtype=np.float64)
    for start in range(0, centers.shape[0], center_block_size):
        block_scores = (directions @ centers[start:start + center_block_size].T) ** 2
        local_labels = np.argmax(block_scores, axis=1)
        local_scores = block_scores[np.arange(block_scores.shape[0]), local_labels]
        better = local_scores > scores
        scores[better] = local_scores[better]
        labels[better] = start + local_labels[better]
    return labels, scores


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
    if orientation == 7: return np.flipud(np.fliplr(np.swapaxes(array, 0, 1)))
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
def _save_gray16(path, value): Image.fromarray(np.round(np.clip(value, 0, 1) * 65535).astype(np.uint16)).save(path)
def _save_srgb_rgba(path, rgba): Image.fromarray(rgba, mode="RGBA").save(path, icc_profile=_srgb_profile_bytes())
def _to_u8(value): return np.round(np.clip(value, 0, 1) * 255).astype(np.uint8)
def _find_duplicate_palette_pairs(palette, cosine_threshold=.99999): return [[a, b] for a in range(palette.shape[0]) for b in range(a + 1, palette.shape[0]) if float(np.dot(palette[a], palette[b])) >= cosine_threshold]
def _coefficient_summary(values):
    if not values.size: return {"minimum": None, "maximum": None, "mean": None, "over_one_count": 0, "over_one_fraction": 0.0}
    return {"minimum": float(np.min(values)), "maximum": float(np.max(values)), "mean": float(np.mean(values)),
            "over_one_count": int(np.count_nonzero(values > 1)), "over_one_fraction": float(np.mean(values > 1))}
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
    if not 1 <= color_count <= MAX_PALETTE_SIZE: raise ValueError(f"color_count must be between 1 and {MAX_PALETTE_SIZE}")
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
