import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QGuiApplication

from brightness_extractor.controller import AppController, Worker
from brightness_extractor.core import ExtractorConfig
from brightness_extractor.queue import BatchQueue


def test_startup_restores_only_first_configuration_not_source_paths(tmp_path):
    app = QGuiApplication.instance() or QGuiApplication([])
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    settings = QSettings("BrightnessExtractor", "BrightnessExtractorGUI")
    settings.clear()
    first = AppController()
    first.addFiles([str(tmp_path / "one.png")])
    first.select(0)
    assert first.items[0]["n"] == 1
    assert first.outputRoot == str(tmp_path)
    settings_map = first.selectedSettings
    settings_map["n"] = 8
    settings_map["threshold_low"] = .27
    settings_map["threshold_high"] = .50
    first.updateSelected(settings_map)
    first.setOutputRoot(str(tmp_path))
    second = AppController()
    assert second.items == []
    assert second.selectedSettings["n"] == 8
    assert second.selectedSettings["threshold_low"] == .27
    assert second.outputRoot == str(tmp_path)


def test_color_count_is_editable_per_queue_item(tmp_path):
    first = AppController()
    first.addFiles([str(tmp_path / "one.png"), str(tmp_path / "two.png")])
    initial_n = first.items[0]["n"]
    first.setColorCount(1, 9)
    assert first.items[0]["n"] == initial_n
    assert first.items[1]["n"] == 9


def test_file_dialog_url_uses_its_local_path_and_seeds_output_folder(tmp_path):
    image_path = tmp_path / "from dialog.png"
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings("BrightnessExtractor", "BrightnessExtractorGUI").clear()
    first = AppController()

    first.addFiles([QUrl.fromLocalFile(str(image_path))])

    assert first.items[0]["path"] == str(image_path.resolve())
    assert first.items[0]["n"] == 1
    assert first.outputRoot == str(tmp_path)


def test_old_implicit_default_of_three_migrates_to_one(tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    settings = QSettings("BrightnessExtractor", "BrightnessExtractorGUI")
    settings.clear()
    settings.setValue("firstN", 3)

    controller = AppController()

    assert controller.selectedSettings["n"] == 1
    assert settings.value("firstN") == 1


def test_failed_queue_item_emits_a_critical_error_for_the_popup(tmp_path):
    bad = tmp_path / "unreadable.png"
    bad.write_text("not an image", encoding="utf-8")
    queue = BatchQueue(ExtractorConfig(restarts=1, max_iterations=1), 1)
    queue.add_paths([bad])
    worker = Worker(queue, str(tmp_path))
    messages = []
    worker.criticalError.connect(messages.append)

    worker.run()

    assert queue.items[0].status == "실패"
    assert messages and messages[0].startswith("unreadable.png\n\n이미지를 읽을 수 없습니다:")
