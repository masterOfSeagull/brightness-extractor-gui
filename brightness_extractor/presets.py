from __future__ import annotations

import json
from pathlib import Path

from .core import ExtractorConfig

PRESET_VERSION = 2


def save_preset(path: str | Path, color_count: int, config: ExtractorConfig) -> None:
    if not isinstance(color_count, int) or color_count < 1:
        raise ValueError("N must be a positive integer")
    config.validate()
    Path(path).write_text(json.dumps({"format": "brightness-extractor-preset", "version": PRESET_VERSION,
                                      "color_count": color_count, "config": config.to_dict()}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_preset(path: str | Path) -> tuple[int, ExtractorConfig]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("사전 설정 파일을 읽을 수 없습니다.") from error
    if not isinstance(data, dict) or data.get("format") != "brightness-extractor-preset":
        raise ValueError("올바른 밝기 추출 사전 설정이 아닙니다.")
    if data.get("version") not in (1, PRESET_VERSION):
        raise ValueError("지원하지 않는 사전 설정 버전입니다.")
    color_count = data.get("color_count")
    if not isinstance(color_count, int) or color_count < 1:
        raise ValueError("사전 설정의 N 값이 올바르지 않습니다.")
    return color_count, ExtractorConfig.from_dict(data.get("config"))
