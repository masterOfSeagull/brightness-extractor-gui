# Brightness Extractor GUI

RGB/RGBA 래스터 이미지를 K-lines 색상 레이와 밝기 계수로 분해하는 한국어 PySide6/QML 데스크톱 도구입니다.

## 실행

`run.bat`을 실행하면 프로젝트 전용 가상 환경을 만들고 필요한 패키지를 설치한 뒤 앱을 시작합니다.

## 테스트

```powershell
.\.venv\Scripts\python -m pytest
```

결과는 `출력 루트/원본파일명(확장자 제외)/실행시각/`에 저장됩니다. 각 실행 폴더에는 원본 복사본 `original.<확장자>`, `asset_rgba.png`, `brightness.png`, `main_color.png`, `labels.png`, `soft_mask.png`, 녹색 배경의 `reconstruction_green.png`, `palette.json`이 포함됩니다.
