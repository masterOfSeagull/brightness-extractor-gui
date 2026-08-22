import threading
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from brightness_extractor.core import ExtractorConfig
from brightness_extractor.presets import PRESET_VERSION, load_preset, save_preset
from brightness_extractor.queue import BatchQueue


def test_preset_round_trip_and_bad_values_do_not_load(tmp_path):
    path = tmp_path / "preset.json"
    config = ExtractorConfig(threshold_low=.12, working_space="linear_rgb", restarts=2)
    save_preset(path, 6, config)
    count, restored = load_preset(path)
    assert count == 6 and restored == config
    path.write_text('{"format":"brightness-extractor-preset", "version":99}', encoding="utf-8")
    with pytest.raises(ValueError): load_preset(path)


def test_presets_reject_palette_counts_above_the_operational_limit(tmp_path):
    path = tmp_path / "too-many.json"
    with pytest.raises(ValueError, match="256"):
        save_preset(path, 257, ExtractorConfig())
    path.write_text('{"format":"brightness-extractor-preset", "version":2, "color_count":257, "config":{}}', encoding="utf-8")
    with pytest.raises(ValueError, match="256"):
        load_preset(path)


def test_first_item_is_seeded_and_later_items_clone_first_current_config(tmp_path):
    paths = [tmp_path / "one.png", tmp_path / "two.png", tmp_path / "three.png"]
    queue = BatchQueue(ExtractorConfig(threshold_low=.11), 4)
    queue.add_paths([paths[0]])
    assert queue.items[0].color_count == 4 and queue.items[0].config.threshold_low == .11
    queue.items[0].color_count = 7
    queue.items[0].config = replace(queue.items[0].config, threshold_low=.31)
    queue.add_paths(paths[1:])
    assert [(item.color_count, item.config.threshold_low) for item in queue.items[1:]] == [(7, .31), (7, .31)]
    queue.items[1].config = replace(queue.items[1].config, threshold_low=.8)
    assert queue.items[2].config.threshold_low == .31
    assert len(queue.add_paths([paths[0]])) == 0


def test_mixed_batch_continues_and_output_names_do_not_collide(tmp_path):
    valid = tmp_path / "same.png"
    valid2dir = tmp_path / "second"; valid2dir.mkdir()
    valid2 = valid2dir / "same.png"
    Image.fromarray(np.array([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)).save(valid)
    Image.fromarray(np.array([[[0, 0, 255], [255, 255, 0]]], dtype=np.uint8)).save(valid2)
    bad = tmp_path / "bad.png"; bad.write_text("not an image", encoding="utf-8")
    queue = BatchQueue(ExtractorConfig(restarts=1, max_iterations=5, threshold_low=0, threshold_high=.01), 2)
    output_root = tmp_path / "output"; output_root.mkdir()
    queue.add_paths([valid, bad, valid2])
    run = queue.run(output_root)
    assert [item.status for item in queue.items] == ["완료", "실패", "완료"]
    assert queue.items[0].result_dir.name != queue.items[2].result_dir.name
    assert queue.items[0].result_dir.parent.name == "same"
    assert {"original.png", "asset_alpha_linear_k.png", "asset_alpha_srgb_k.png", "brightness_k_linear.png", "brightness_k_srgb.png", "labels.png", "reconstruction_original_alpha.png", "reconstruction_original_alpha_centroid.png"} <= {path.name for path in queue.items[0].result_dir.iterdir()}
    assert run.is_dir()


def test_cancellation_stops_before_next_item(tmp_path):
    one, two = tmp_path / "one.png", tmp_path / "two.png"
    array = np.full((40, 40, 3), [255, 0, 0], dtype=np.uint8)
    Image.fromarray(array).save(one); Image.fromarray(array).save(two)
    queue = BatchQueue(ExtractorConfig(restarts=1, max_iterations=100, threshold_low=0, threshold_high=.01), 1)
    queue.add_paths([one, two])
    cancel = threading.Event(); cancel.set()
    queue.run(tmp_path, cancel)
    assert [item.status for item in queue.items] == ["대기", "대기"]


def test_save_failure_clears_nonexistent_result_paths(tmp_path, monkeypatch):
    source = tmp_path / "input.png"
    Image.fromarray(np.array([[[255, 0, 0]]], dtype=np.uint8)).save(source)
    queue = BatchQueue(ExtractorConfig(restarts=1, max_iterations=3, threshold_low=0, threshold_high=.01), 1)
    queue.add_paths([source])

    class FailedResult:
        def save(self, *_args, **_kwargs):
            raise OSError("simulated write failure")

    monkeypatch.setattr("brightness_extractor.queue.extract_brightness", lambda *_args, **_kwargs: FailedResult())
    queue.run(tmp_path)
    item = queue.items[0]
    assert item.status == "실패"
    assert item.result_dir is None and item.result_preview is None
    assert "simulated write failure" in item.error
