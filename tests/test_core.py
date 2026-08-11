import json

import numpy as np
import pytest
from PIL import Image, ImageCms
import cv2

from brightness_extractor.core import (
    ExtractorConfig,
    ExtractionCancelled,
    brightness_threshold_candidates,
    extract_brightness,
    load_image,
    save_result_bundle,
)
from brightness_extractor.core import _fitting_weights, _pixel_brightness, _smoothstep


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
    Image.fromarray(np.round(image * 255).astype(np.uint8)).save(source)
    folder = save_result_bundle(result, tmp_path / "bundle", source, 3, ExtractorConfig())
    assert {"original.png", "main_color.png", "labels.png", "threshold_mask.png", "input_alpha.png", "brightness_k_linear.png", "brightness_k_srgb.png", "asset_alpha_linear_k.png", "asset_alpha_srgb_k.png", "reconstruction_original_alpha.png", "palette.json"} <= {p.name for p in folder.iterdir()}
    palette = json.loads((folder / "palette.json").read_text(encoding="utf-8"))
    assert len(palette["palette_srgb"]) == 3


def test_version_three_exports_keep_input_alpha_separate_from_threshold_and_assets(tmp_path):
    image = np.array([[[1, 0, 0, .5], [.01, .01, .01, 1]]], dtype=np.float32)
    config = ExtractorConfig(threshold_low=.02, threshold_high=.03, restarts=1, max_iterations=10)
    result = extract_brightness(image, 1, config)
    source = tmp_path / "input.png"
    Image.fromarray(np.round(image[..., :3] * 255).astype(np.uint8)).save(source)
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


def test_version_three_threshold_factor_and_raw_coefficient_clamping_order(tmp_path):
    image = np.array([[[1.0, 0, 0, .8]]], dtype=np.float32)
    enabled = ExtractorConfig(threshold_low=.0, threshold_high=.8, apply_soft_mask_to_output=True, restarts=1, max_iterations=4)
    disabled = ExtractorConfig(threshold_low=.0, threshold_high=.8, apply_soft_mask_to_output=False, restarts=1, max_iterations=4)
    with_fade = extract_brightness(image, 1, enabled)
    without_fade = extract_brightness(image, 1, disabled)
    # Brightness 1 has T=1 here.  Replace the threshold only to assert that
    # final-alpha clamping happens after all three factors are multiplied.
    with_fade.threshold_mask[:] = .5
    with_fade.k_srgb_raw[:] = 1.5
    assert with_fade.srgb_asset_alpha()[0, 0] == pytest.approx(.6)
    assert without_fade.effective_threshold_factor == 1.0
    saved = with_fade.save(tmp_path / "bundle")
    metadata = json.loads(saved["palette"].read_text(encoding="utf-8"))
    assert metadata["threshold_factor"] == {"enabled": True, "definition": "T_eff = threshold_mask if enabled, otherwise 1"}
    assert "T_eff" in metadata["outputs"]["asset_alpha_srgb_k.png"]["alpha"]


def test_linear_and_srgb_coefficients_are_projected_independently():
    result = extract_brightness(np.array([[[.5, 0, 0, .4]]], dtype=np.float32), 1,
                                ExtractorConfig(threshold_low=0, threshold_high=.01, working_space="srgb", restarts=1, max_iterations=4))
    assert result.k_srgb_raw[0, 0] == pytest.approx(.5, abs=.002)
    assert result.k_linear_raw[0, 0] == pytest.approx(.214041, abs=.002)
    assert result.srgb_asset_alpha()[0, 0] == pytest.approx(.2, abs=.002)
    assert result.linear_asset_alpha()[0, 0] == pytest.approx(.085616, abs=.002)


def test_rgb_outputs_embed_srgb_profile_and_excluded_pixels_are_transparent_black(tmp_path):
    image = np.array([[[1., 0, 0, 1], [0, 0, 0, 1]]], dtype=np.float32)
    result = extract_brightness(image, 1, ExtractorConfig(threshold_low=.01, threshold_high=.02, restarts=1, max_iterations=4))
    saved = result.save(tmp_path / "bundle")
    for name in ("main_color", "asset_alpha_linear_k", "asset_alpha_srgb_k", "reconstruction_original_alpha"):
        with Image.open(saved[name]) as output:
            assert output.info.get("icc_profile")
            rgba = np.asarray(output.convert("RGBA"))
            assert rgba[0, 1].tolist() == [0, 0, 0, 0]


def test_embedded_input_profile_is_converted_and_recorded(tmp_path):
    source = tmp_path / "tagged.png"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(np.array([[[255, 0, 0]]], dtype=np.uint8)).save(source, icc_profile=profile)
    rgba, _ = load_image(source)
    result = extract_brightness(source, 1, ExtractorConfig(threshold_low=0, threshold_high=.01, restarts=1, max_iterations=4))
    metadata = json.loads(result.save(tmp_path / "bundle", source)["palette"].read_text(encoding="utf-8"))
    assert rgba[0, 0, 0] == pytest.approx(1)
    assert metadata["input_color_profile"] == "embedded_icc_converted_to_srgb"
    assert metadata["statistics"]["color_conversion_applied"] is True


def test_tagged_palette_png_preserves_transparency_during_icc_conversion(tmp_path):
    source = tmp_path / "palette.png"
    image = Image.new("P", (2, 1))
    image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
    image.putdata([0, 1])
    image.info["transparency"] = 0
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(source, icc_profile=profile)
    rgba, info = load_image(source, with_info=True)
    assert info.input_profile_status == "embedded_icc_converted_to_srgb"
    assert rgba[0, 0, 3] == 0
    assert rgba[0, 1, 3] == 1


def test_malformed_icc_profile_uses_friendly_image_load_error(tmp_path):
    source = tmp_path / "bad-profile.png"
    Image.new("RGB", (1, 1), "red").save(source, icc_profile=b"not an ICC profile")
    with pytest.raises(ValueError, match=source.name):
        load_image(source)


def test_tagged_16_bit_input_records_the_documented_8_bit_processing_policy(tmp_path):
    source = tmp_path / "tagged-16.png"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(np.array([[0, 4096, 65535]], dtype=np.uint16)).save(source, icc_profile=profile)
    _, info = load_image(source, with_info=True)
    assert info.source_bit_depth == 16
    assert info.processing_bit_depth == 8
    assert info.color_conversion_applied is True


def test_palette_size_is_bounded():
    with pytest.raises(ValueError, match="256"):
        ExtractorConfig().validate(257)


def test_cluster_weight_statistics_use_all_classified_pixels_when_fitting_is_sampled():
    image = np.array([[[1., 0, 0], [0, 1., 0], [1., .2, 0], [0, .3, 1.]]], dtype=np.float32)
    config = ExtractorConfig(threshold_low=0, threshold_high=.01, fit_sample_limit=2, restarts=1, max_iterations=4, random_seed=3)
    result = extract_brightness(image, 2, config)
    brightness = _pixel_brightness(image, config.brightness_metric).reshape(-1)
    mask = _smoothstep(config.threshold_low, config.threshold_high, brightness)
    weights = _fitting_weights(config, mask, brightness, np.linalg.norm(image.reshape(-1, 3), axis=1))
    expected = np.bincount(result.labels.reshape(-1), weights=weights, minlength=2)
    actual = np.array([item["weight_sum"] for item in result.statistics["cluster_statistics"]])
    assert np.allclose(actual, expected)


def test_fitting_sample_limit_smaller_than_retained_pixels_completes():
    image = np.full((20, 20, 3), [1., .1, .05], dtype=np.float32)
    result = extract_brightness(image, 1, ExtractorConfig(threshold_low=0, threshold_high=.01, fit_sample_limit=7, restarts=1, max_iterations=3))
    assert result.statistics["retained_pixels"] == 400
    assert result.statistics["fit_sample_pixels"] == 7


def test_default_sample_limit_handles_501_by_500_fully_retained_image():
    image = np.full((501, 500, 3), [1., .1, .05], dtype=np.float32)
    result = extract_brightness(image, 1, ExtractorConfig(threshold_low=0, threshold_high=.01, restarts=1, max_iterations=2))
    assert result.statistics["retained_pixels"] == 250_500
    assert result.statistics["fit_sample_pixels"] == 250_000
    assert sum(item["assigned_pixel_count"] for item in result.statistics["cluster_statistics"]) == 250_500


def test_cancellation_during_bundle_save_leaves_no_complete_or_partial_result(tmp_path):
    result = extract_brightness(np.array([[[1., 0, 0]]], dtype=np.float32), 1,
                                ExtractorConfig(threshold_low=0, threshold_high=.01, restarts=1, max_iterations=4))
    checks = iter((False, True))
    with pytest.raises(ExtractionCancelled):
        result.save(tmp_path / "bundle", cancel=lambda: next(checks, True))
    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".bundle.partial-*"))


def test_save_progress_reaches_one_only_after_atomic_publication(tmp_path):
    result = extract_brightness(np.array([[[1., 0, 0]]], dtype=np.float32), 1,
                                ExtractorConfig(threshold_low=0, threshold_high=.01, restarts=1, max_iterations=4))
    updates = []
    target = tmp_path / "bundle"
    result.save(target, progress=lambda name, value: updates.append((name, value, target.exists())))
    assert all(left[1] <= right[1] for left, right in zip(updates, updates[1:]))
    assert all(value < 1 and not published for _, value, published in updates[:-1])
    assert updates[-1] == ("published", 1.0, True)


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
