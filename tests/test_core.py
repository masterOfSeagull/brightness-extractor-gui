import json

import numpy as np
import pytest
from PIL import Image
import cv2

from brightness_extractor.core import (
    ExtractorConfig,
    brightness_threshold_candidates,
    extract_brightness,
    load_image,
    save_result_bundle,
)


def test_defaults_match_the_supplied_extractor_configuration():
    assert ExtractorConfig() == ExtractorConfig(
        threshold_low=.04, threshold_high=.14, brightness_metric="max", brightness_space="srgb",
        working_space="linear_rgb", fit_mode="atmosphere", atmosphere_weight_floor=.20,
        atmosphere_weight_power=.50, apply_soft_mask_to_output=True,
        restarts=16, max_iterations=100, convergence_tolerance=1e-7, random_seed=7,
        fit_sample_limit=250_000, chunk_size=500_000,
    )


def test_exact_color_rays_reconstruct_and_palette_are_consistent(tmp_path):
    rays = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    coefficients = np.array([[.2, .4, .7], [.8, .5, .3]])
    image = (rays[None, :, :] * coefficients[:, :, None]).astype(np.float32)
    result = extract_brightness(image, 3, ExtractorConfig(restarts=3, max_iterations=50, threshold_low=0, threshold_high=.01, random_seed=9, working_space="srgb"))
    assert result.palette.shape == (3, 3)
    assert np.max(np.abs(result.reconstruction() - image)) < 0.01
    source = tmp_path / "synthetic.png"
    Image.fromarray(np.round(image * 255).astype(np.uint8), mode="RGB").save(source)
    folder = save_result_bundle(result, tmp_path / "bundle", source, 3, ExtractorConfig())
    assert {"original.png", "main_color.png", "labels.png", "threshold_mask.png", "input_alpha.png", "brightness_k_linear.png", "brightness_k_srgb.png", "asset_alpha_linear_k.png", "asset_alpha_srgb_k.png", "reconstruction_original_alpha.png", "palette.json"} <= {p.name for p in folder.iterdir()}
    palette = json.loads((folder / "palette.json").read_text(encoding="utf-8"))
    assert len(palette["palette_srgb"]) == 3


def test_version_three_exports_keep_input_alpha_separate_from_threshold_and_assets(tmp_path):
    image = np.array([[[1, 0, 0, .5], [.01, .01, .01, 1]]], dtype=np.float32)
    config = ExtractorConfig(threshold_low=.02, threshold_high=.03, restarts=1, max_iterations=10)
    result = extract_brightness(image, 1, config)
    source = tmp_path / "input.png"
    Image.fromarray(np.round(image * 255).astype(np.uint8), mode="RGB").save(source)
    saved = result.save(tmp_path / "bundle", source)
    reconstruction = np.asarray(Image.open(saved["reconstruction_original_alpha"]).convert("RGBA"))
    input_alpha = np.asarray(Image.open(saved["input_alpha"]))
    threshold = np.asarray(Image.open(saved["threshold_mask"]))
    assert reconstruction[0, 0, 3] in range(126, 130)
    assert reconstruction[0, 1].tolist() == [0, 0, 0, 0]
    assert input_alpha[0, 0] in range(32760, 32780)
    assert threshold[0, 0] == 65535
    assert not (tmp_path / "bundle" / "reconstruction_green.png").exists()


def test_brightness_threshold_candidates_use_the_requested_percentages_and_color_space(tmp_path):
    source = tmp_path / "gradient.png"
    Image.fromarray(np.array([[[0, 0, 0], [64, 64, 64], [128, 128, 128], [255, 255, 255]]], dtype=np.uint8)).save(source)
    candidates = dict(brightness_threshold_candidates(source, ExtractorConfig(working_space="srgb", brightness_space="srgb", brightness_metric="max")))
    linear_candidates = dict(brightness_threshold_candidates(source, ExtractorConfig(working_space="linear_rgb", brightness_space="working", brightness_metric="max")))
    assert list(candidates) == [60, 45, 30, 20, 10, 8, 6, 5, 3, 1]
    assert all(candidates[left] <= candidates[right] for left, right in zip([60, 45, 30, 20, 10, 8, 6, 5, 3], [45, 30, 20, 10, 8, 6, 5, 3, 1]))
    assert linear_candidates[10] < candidates[10]


def test_alpha_and_threshold_pixels_are_excluded():
    image = np.array([[[1, 0, 0, 1], [.01, .01, .01, 1]], [[0, 1, 0, 0], [0, 0, 1, 1]]], dtype=np.float32)
    result = extract_brightness(image, 2, ExtractorConfig(threshold_low=.02, threshold_high=.03, restarts=1, max_iterations=10))
    assert (result.soft_mask > 0).tolist() == [[True, False], [False, True]]
    assert result.labels[0, 1] == -1 and result.labels[1, 0] == -1
    assert result.main_color_map[1, 0].tolist() == [0, 0, 0]


def test_seeded_fit_is_deterministic():
    rng = np.random.default_rng(5)
    image = rng.random((30, 20, 3), dtype=np.float32)
    config = ExtractorConfig(random_seed=31, restarts=2, max_iterations=15)
    left = extract_brightness(image, 4, config)
    right = extract_brightness(image, 4, config)
    assert np.array_equal(left.labels, right.labels)
    assert np.allclose(left.palette, right.palette)


@pytest.mark.parametrize("count,config", [(0, ExtractorConfig()), (4, ExtractorConfig(threshold_low=.9, threshold_high=.95))])
def test_invalid_count_or_retained_pixels_are_rejected(count, config):
    image = np.full((1, 2, 3), .1, dtype=np.float32)
    with pytest.raises(ValueError):
        extract_brightness(image, count, config)


def test_loads_8_and_16_bit_without_16_bit_downcast(tmp_path):
    eight = tmp_path / "eight.png"
    sixteen = tmp_path / "sixteen.png"
    Image.fromarray(np.array([[0, 255]], dtype=np.uint8), "L").save(eight)
    rgb16_bgr = np.array([[[0, 0, 0], [0, 0, 4096]]], dtype=np.uint16)
    assert cv2.imwrite(str(sixteen), rgb16_bgr)
    image8, depth8 = load_image(eight)
    image16, depth16 = load_image(sixteen)
    assert depth8 == 8 and depth16 == 16
    assert image8[0, 1, 0] == pytest.approx(1)
    # 4096 is deliberately not an 8-bit multiple: it catches an implicit 16->8 decode.
    assert image16[0, 1, 0] == pytest.approx(4096 / 65535, abs=1e-6)
    assert image16.dtype == np.float32
