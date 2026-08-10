from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Event
import copy
import os

from PySide6.QtCore import QObject, Property, QSettings, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .core import ExtractorConfig, brightness_threshold_candidates
from .presets import load_preset, save_preset
from .queue import BatchQueue, QueueItem


class Worker(QThread):
    changed = Signal()
    finishedRun = Signal(str)
    fatal = Signal(str)
    criticalError = Signal(str)

    def __init__(self, queue: BatchQueue, output_root: str):
        super().__init__()
        self.queue, self.output_root, self.cancel_event = queue, output_root, Event()

    def run(self) -> None:
        try:
            folder = self.queue.run(self.output_root, self.cancel_event, self._queue_updated)
            self.finishedRun.emit(str(folder))
        except Exception as error:
            self.fatal.emit(str(error))

    def _queue_updated(self, _index: int, item: QueueItem) -> None:
        self.changed.emit()
        if item.status == "실패":
            self.criticalError.emit(f"{item.path.name}\n\n{item.error}")


class AppController(QObject):
    queueChanged = Signal()
    selectedChanged = Signal()
    outputRootChanged = Signal()
    runningChanged = Signal()
    geometryChanged = Signal()
    message = Signal(str)
    criticalError = Signal(str)
    runFinished = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = QSettings("BrightnessExtractor", "BrightnessExtractorGUI")
        config_data = self.settings.value("firstConfig", None)
        try:
            seed_config = ExtractorConfig.from_dict(config_data) if isinstance(config_data, dict) else ExtractorConfig()
        except ValueError:
            seed_config = ExtractorConfig()
        stored_count = self.settings.value("firstN", None)
        default_version = int(self.settings.value("colorCountDefaultVersion", 0))
        # Version 1 shipped with 3 as the implicit value. Migrate only that old implicit value;
        # any other stored count is an intentional user setting and remains untouched.
        if stored_count is None:
            seed_count = 1
        elif default_version < 2 and int(stored_count) == 3:
            seed_count = 1
            self.settings.setValue("firstN", seed_count)
        else:
            seed_count = int(stored_count)
        if default_version < 2:
            self.settings.setValue("colorCountDefaultVersion", 2)
        self.queue = BatchQueue(seed_config, seed_count)
        self._selected = -1
        self._output_root = str(self.settings.value("outputRoot", ""))
        self.worker: Worker | None = None
        self._brightness_candidate_cache: dict[tuple, list[dict[str, object]]] = {}

    @Property("QVariantList", notify=queueChanged)
    def items(self):
        return [{"path": str(item.path), "name": item.path.name, "n": item.color_count, "status": item.status,
                 "progress": item.progress, "error": item.error, "resultDir": str(item.result_dir or ""),
                 "resultPreview": str(item.result_preview or "")}
                for item in self.queue.items]

    @Property(int, notify=selectedChanged)
    def selectedIndex(self): return self._selected

    @Property("QVariantMap", notify=selectedChanged)
    def selectedSettings(self):
        if not (0 <= self._selected < len(self.queue.items)):
            count, config = self.queue.first_config()
        else:
            item = self.queue.items[self._selected]
            count, config = item.color_count, item.config
        return {"n": count, **asdict(config)}

    @Property(str, notify=outputRootChanged)
    def outputRoot(self): return self._output_root

    @Property("QVariantList", notify=selectedChanged)
    def selectedBrightnessCandidates(self):
        if not (0 <= self._selected < len(self.queue.items)):
            return []
        item = self.queue.items[self._selected]
        try:
            stat = item.path.stat()
            key = (str(item.path), stat.st_mtime_ns, stat.st_size, item.config.brightness_metric,
                   item.config.brightness_space, item.config.working_space)
            if key not in self._brightness_candidate_cache:
                self._brightness_candidate_cache[key] = [
                    {"topPercent": percent, "threshold": f"{value:.4f}"}
                    for percent, value in brightness_threshold_candidates(item.path, item.config)
                ]
            return self._brightness_candidate_cache[key]
        except (OSError, ValueError):
            return []

    @Property(int, notify=geometryChanged)
    def windowWidth(self): return max(1040, int(self.settings.value("windowWidth", 1600)))

    @Property(int, notify=geometryChanged)
    def windowHeight(self): return max(680, int(self.settings.value("windowHeight", 900)))

    @Property(int, notify=geometryChanged)
    def windowX(self): return int(self.settings.value("windowX", -1))

    @Property(int, notify=geometryChanged)
    def windowY(self): return int(self.settings.value("windowY", -1))

    @Property(bool, notify=runningChanged)
    def running(self): return self.worker is not None and self.worker.isRunning()

    def _persist_first(self) -> None:
        count, config = self.queue.first_config()
        self.settings.setValue("firstN", count)
        self.settings.setValue("firstConfig", config.to_dict())
        self.settings.setValue("outputRoot", self._output_root)

    @Slot("QVariantList")
    def addFiles(self, urls):
        paths = []
        for url in urls:
            if isinstance(url, QUrl):
                path = url.toLocalFile()
            else:
                value = str(url)
                path = QUrl(value).toLocalFile() if value.startswith("file:") else value
            if path:
                paths.append(path)
        added = self.queue.add_paths(paths)
        if added and self._selected < 0:
            self._selected = 0
            self.selectedChanged.emit()
        if added and not self._output_root:
            first_folder = added[0].path.parent
            if first_folder.is_dir():
                self._output_root = str(first_folder)
                self.outputRootChanged.emit()
        self._persist_first(); self.queueChanged.emit()

    @Slot(int)
    def select(self, index):
        if 0 <= index < len(self.queue.items):
            self._selected = index
            self.selectedChanged.emit()

    @Slot(int)
    def remove(self, index):
        if self.running or not (0 <= index < len(self.queue.items)): return
        self.queue.remove(index)
        self._selected = min(self._selected, len(self.queue.items) - 1)
        self._persist_first(); self.queueChanged.emit(); self.selectedChanged.emit()

    @Slot(int, int)
    def move(self, index, destination):
        if self.running or not (0 <= index < len(self.queue.items)): return
        self.queue.move(index, destination)
        self._persist_first(); self.queueChanged.emit()

    @Slot(int, int)
    def setColorCount(self, index, count):
        if self.running or not (0 <= index < len(self.queue.items)):
            return
        if not 1 <= count <= 65_534:
            self.message.emit("N은 1에서 65,534 사이여야 합니다.")
            return
        self.queue.items[index].color_count = count
        self._persist_first(); self.queueChanged.emit(); self.selectedChanged.emit()

    @Slot("QVariantMap")
    def updateSelected(self, values):
        try:
            count = int(values.get("n", 1))
            config = ExtractorConfig.from_dict({key: values[key] for key in ExtractorConfig.__dataclass_fields__})
            if count < 1: raise ValueError("N은 1 이상이어야 합니다.")
        except (KeyError, TypeError, ValueError) as error:
            self.message.emit(f"설정 오류: {error}"); return
        if 0 <= self._selected < len(self.queue.items):
            self.queue.items[self._selected].color_count, self.queue.items[self._selected].config = count, config
        else:
            self.queue.seed_count, self.queue.seed_config = count, config
        self._persist_first(); self.queueChanged.emit(); self.selectedChanged.emit()

    @Slot(str)
    def setOutputRoot(self, path):
        self._output_root = path
        self._persist_first(); self.outputRootChanged.emit()

    @Slot(int, int, int, int)
    def saveWindowGeometry(self, width, height, x, y):
        self.settings.setValue("windowWidth", max(1040, width))
        self.settings.setValue("windowHeight", max(680, height))
        if x >= 0: self.settings.setValue("windowX", x)
        if y >= 0: self.settings.setValue("windowY", y)

    @Slot(str)
    def savePreset(self, path):
        try:
            count, config = self.queue.first_config() if self._selected < 0 else self.queue.items[self._selected].clone_config()
            save_preset(path, count, config); self.message.emit("사전 설정을 저장했습니다.")
        except Exception as error: self.message.emit(str(error))

    @Slot(str)
    def loadPreset(self, path):
        try:
            count, config = load_preset(path)
            if 0 <= self._selected < len(self.queue.items):
                self.queue.items[self._selected].color_count, self.queue.items[self._selected].config = count, config
            else:
                self.queue.seed_count, self.queue.seed_config = count, config
            self._persist_first(); self.queueChanged.emit(); self.selectedChanged.emit(); self.message.emit("사전 설정을 불러왔습니다.")
        except Exception as error: self.message.emit(str(error))

    @Slot()
    def runQueue(self):
        if self.running: return
        if not self.queue.items:
            self.message.emit("처리할 이미지를 추가하세요."); return
        if not Path(self._output_root).is_dir():
            self.message.emit("유효한 출력 폴더를 선택하세요."); return
        self.worker = Worker(self.queue, self._output_root)
        self.worker.changed.connect(self.queueChanged)
        self.worker.fatal.connect(self.message)
        self.worker.fatal.connect(self.criticalError)
        self.worker.criticalError.connect(self.criticalError)
        self.worker.finishedRun.connect(self._finished)
        self.worker.start(); self.runningChanged.emit(); self.queueChanged.emit()

    @Slot()
    def cancel(self):
        if self.worker: self.worker.cancel_event.set()

    @Slot(str)
    def openFolder(self, folder):
        if folder and Path(folder).is_dir(): QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot()
    def openSelectedResult(self):
        if 0 <= self._selected < len(self.queue.items): self.openFolder(str(self.queue.items[self._selected].result_dir or ""))

    def _finished(self, folder):
        self.queueChanged.emit(); self.runningChanged.emit(); self.runFinished.emit(folder)
