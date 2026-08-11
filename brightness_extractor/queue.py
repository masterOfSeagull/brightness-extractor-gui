from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Callable
import copy
import re

from .core import ExtractorConfig, ExtractionCancelled, extract_brightness, load_image


@dataclass
class QueueItem:
    path: Path
    color_count: int = 1
    config: ExtractorConfig = field(default_factory=ExtractorConfig)
    status: str = "대기"
    progress: float = 0.0
    error: str = ""
    result_dir: Path | None = None
    result_preview: Path | None = None

    def clone_config(self) -> tuple[int, ExtractorConfig]:
        return self.color_count, copy.deepcopy(self.config)


class BatchQueue:
    """UI-independent sequential queue; useful both to QML and tests."""
    def __init__(self, seed_config: ExtractorConfig | None = None, seed_count: int = 1):
        self.items: list[QueueItem] = []
        self.seed_config = copy.deepcopy(seed_config or ExtractorConfig())
        self.seed_count = seed_count

    def add_paths(self, paths: list[str | Path]) -> list[QueueItem]:
        known = {item.path.resolve() for item in self.items}
        added: list[QueueItem] = []
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            try:
                key = path.resolve()
            except OSError:
                key = path.absolute()
            if key in known:
                continue
            if self.items:
                count, config = self.items[0].clone_config()
            else:
                count, config = self.seed_count, copy.deepcopy(self.seed_config)
            item = QueueItem(path=key, color_count=count, config=config)
            self.items.append(item)
            known.add(key)
            added.append(item)
        return added

    def remove(self, index: int) -> None:
        del self.items[index]

    def move(self, index: int, destination: int) -> None:
        item = self.items.pop(index)
        self.items.insert(max(0, min(destination, len(self.items))), item)

    def first_config(self) -> tuple[int, ExtractorConfig]:
        if self.items:
            return self.items[0].clone_config()
        return self.seed_count, copy.deepcopy(self.seed_config)

    def run(self, output_root: str | Path, cancel: Event | None = None,
            notify: Callable[[int, QueueItem], None] | None = None) -> Path:
        root = Path(output_root)
        if not root.is_dir():
            raise ValueError("유효한 출력 폴더를 선택하세요.")
        cancel = cancel or Event()
        for index, item in enumerate(self.items):
            if cancel.is_set():
                break
            item.status, item.progress, item.error = "처리 중", 0.0, ""
            if notify:
                notify(index, item)
            try:
                image, load_info = load_image(item.path, with_info=True)
                result = extract_brightness(image, item.color_count, item.config,
                    progress=lambda stage, value: self._item_progress(item, stage, value, index, notify),
                    cancel=cancel.is_set, source_bit_depth=load_info.source_bit_depth,
                    processing_bit_depth=load_info.processing_bit_depth,
                    input_profile_status=load_info.input_profile_status,
                    color_conversion_applied=load_info.color_conversion_applied)
                source_folder = re.sub(r"[^\w.-]+", "_", item.path.stem, flags=re.UNICODE).strip("._") or "image"
                image_root = root / source_folder
                # The convenient default output root is often the source file's
                # parent. A same-named source file cannot also be its result folder.
                if image_root.exists() and not image_root.is_dir():
                    image_root = root / f"{source_folder}__results"
                image_root.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                item.result_dir = image_root / timestamp
                suffix = 2
                while item.result_dir.exists():
                    item.result_dir = image_root / f"{timestamp}-{suffix}"
                    suffix += 1
                self._item_progress(item, "prepare_output", 0, index, notify)
                self._item_progress(item, "prepare_output", 1, index, notify)
                saved = result.save(item.result_dir, item.path, cancel=cancel.is_set,
                    progress=lambda filename, value: self._item_progress(item, "metadata" if filename == "palette.json" else ("published" if filename == "published" else "save"), value, index, notify))
                item.result_preview = saved["reconstruction_original_alpha"]
                item.status, item.progress = "완료", 1.0
            except ExtractionCancelled:
                item.status, item.result_dir, item.result_preview = "취소됨", None, None
                if notify:
                    notify(index, item)
                break
            except Exception as error:  # individual invalid files do not stop the batch
                item.status, item.error, item.result_dir, item.result_preview = "실패", str(error), None, None
            if notify:
                notify(index, item)
        return root

    @staticmethod
    def _item_progress(item: QueueItem, stage: str, value: float, index: int, notify: Callable[[int, QueueItem], None] | None) -> None:
        ranges = {"load": (0.0, .05), "fit": (.05, .70), "classify": (.70, .85), "done": (.85, .85),
                  "prepare_output": (.85, .90), "save": (.90, .98), "metadata": (.98, .999), "published": (1.0, 1.0)}
        start, end = ranges.get(stage, (0.0, 1.0))
        item.progress = max(item.progress, start + (end - start) * value)
        if notify:
            notify(index, item)
