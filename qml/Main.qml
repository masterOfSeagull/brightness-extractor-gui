import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Qt.labs.platform as Platform

ApplicationWindow {
    id: root
    visible: true
    width: backend.windowWidth; height: backend.windowHeight
    x: backend.windowX; y: backend.windowY
    minimumWidth: 1040; minimumHeight: 680
    title: "Brightness Extractor"
    flags: Qt.FramelessWindowHint | Qt.Window
    color: "#f5f0e8"
    property color ink: "#252222"
    property color burgundy: "#7b2232"
    property color cream: "#f5f0e8"
    property color line: "#dfd5c9"
    property color muted: "#857c75"
    property bool advanced: false
    property var setting: backend.selectedSettings

    component CompactCheckBox: CheckBox {
        id: compactCheck
        implicitHeight: 24
        leftPadding: 0
        rightPadding: 0
        indicator: Rectangle {
            x: 0
            y: Math.round((compactCheck.height - height) / 2)
            width: 16; height: 16; radius: 3
            color: compactCheck.checked ? root.burgundy : "#fffaf2"
            border.color: compactCheck.checked ? root.burgundy : "#aa9e94"
            border.width: 1
            Label { anchors.centerIn: parent; visible: compactCheck.checked; text: "✓"; color: "white"; font.family: pretendardBold.name; font.pixelSize: 12 }
        }
        contentItem: Label {
            text: compactCheck.text
            leftPadding: 23
            color: root.ink
            font.family: pretendard.name
            font.pixelSize: 10
            verticalAlignment: Text.AlignVCenter
        }
    }

    component ZoomableImage: Flickable {
        id: zoomView
        property url imageSource: ""
        property real zoom: 1
        readonly property real minimumZoom: 0.5
        readonly property real maximumZoom: 128
        readonly property real fittedImageWidth: previewImage.sourceSize.width > 0 && previewImage.sourceSize.height > 0
                                                ? Math.min(width, height * previewImage.sourceSize.width / previewImage.sourceSize.height)
                                                : width
        readonly property real fittedImageHeight: previewImage.sourceSize.width > 0 && previewImage.sourceSize.height > 0
                                                 ? Math.min(height, width * previewImage.sourceSize.height / previewImage.sourceSize.width)
                                                 : height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: Math.max(width, previewImage.width)
        contentHeight: Math.max(height, previewImage.height)
        Canvas {
            width: zoomView.contentWidth; height: zoomView.contentHeight
            onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
            onPaint: {
                var context = getContext("2d"), size = 14
                context.fillStyle = "#eee7dd"; context.fillRect(0, 0, width, height)
                context.fillStyle = "#d8cec3"
                for (var y = 0; y < height; y += size)
                    for (var x = (Math.floor(y / size) % 2) * size; x < width; x += size * 2)
                        context.fillRect(x, y, size, size)
            }
        }
        function limit(value, low, high) { return Math.max(low, Math.min(high, value)) }
        function setZoomAt(factor, pointerX, pointerY) {
            var oldWidth = previewImage.width
            var oldHeight = previewImage.height
            var relativeX = oldWidth > 0 ? limit((contentX + pointerX - previewImage.x) / oldWidth, 0, 1) : 0.5
            var relativeY = oldHeight > 0 ? limit((contentY + pointerY - previewImage.y) / oldHeight, 0, 1) : 0.5
            zoom = limit(zoom * factor, minimumZoom, maximumZoom)
            var targetX = relativeX * previewImage.width + previewImage.x - pointerX
            var targetY = relativeY * previewImage.height + previewImage.y - pointerY
            contentX = limit(targetX, 0, Math.max(0, contentWidth - width))
            contentY = limit(targetY, 0, Math.max(0, contentHeight - height))
        }
        Image {
            id: previewImage
            x: (zoomView.contentWidth - width) / 2
            y: (zoomView.contentHeight - height) / 2
            width: Math.max(1, zoomView.fittedImageWidth * zoomView.zoom)
            height: Math.max(1, zoomView.fittedImageHeight * zoomView.zoom)
            source: zoomView.imageSource
            fillMode: Image.Stretch
            smooth: zoomView.zoom < 8
            mipmap: false
            antialiasing: false
        }
        WheelHandler {
            acceptedModifiers: Qt.ControlModifier
            onWheel: function(wheel) {
                var pointerX = zoomView.width / 2
                var pointerY = zoomView.height / 2
                if (wheel.x !== undefined && wheel.y !== undefined) {
                    pointerX = wheel.x
                    pointerY = wheel.y
                }
                var delta = wheel.angleDelta.y
                if (delta !== 0)
                    zoomView.setZoomAt(Math.pow(1.2, delta / 120), pointerX, pointerY)
                wheel.accepted = true
            }
        }
    }

    Timer { id: geometrySave; interval: 400; repeat: false; onTriggered: backend.saveWindowGeometry(root.width, root.height, root.x, root.y) }
    onWidthChanged: geometrySave.restart()
    onHeightChanged: geometrySave.restart()
    onXChanged: geometrySave.restart()
    onYChanged: geometrySave.restart()

    FontLoader { id: pretendard; source: "fonts/Pretendard-Regular.otf" }
    FontLoader { id: pretendardMedium; source: "fonts/Pretendard-Medium.otf" }
    FontLoader { id: pretendardBold; source: "fonts/Pretendard-Bold.otf" }
    font.family: pretendard.name

    function syncSettings() { setting = backend.selectedSettings }
    function brightnessSpaceLabel() {
        if (setting.brightness_space === "srgb") return "sRGB"
        return setting.working_space === "linear_rgb" ? "Linear RGB 작업 색공간" : "sRGB 작업 색공간"
    }
    function brightnessMetricLabel() {
        return setting.brightness_metric === "luminance" ? "상대 휘도" : "max(R,G,B)"
    }
    Connections {
        target: backend
        function onSelectedChanged() { root.syncSettings(); inputPreviewImage.zoom = 1; reconstructionPreviewImage.zoom = 1 }
        function onQueueChanged() { root.syncSettings() }
        function onMessage(text) { toast.show(text) }
        function onCriticalError(text) { toast.show("처리 오류: " + text); criticalErrorDialog.showError(text) }
        function onRunFinished(folder) { toast.show("결과 저장 완료") }
    }

    FileDialog { id: inputDialog; title: "이미지 추가"; fileMode: FileDialog.OpenFiles
        nameFilters: ["이미지 파일 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)", "모든 파일 (*)"]
        onAccepted: backend.addFiles(selectedFiles)
    }
    FolderDialog { id: folderDialog; title: "출력 루트 선택"; onAccepted: backend.setOutputRoot(selectedFolder.toLocalFile()) }
    FileDialog { id: savePresetDialog; title: "사전 설정 저장"; fileMode: FileDialog.SaveFile; defaultSuffix: "json"; nameFilters: ["JSON (*.json)"]
        onAccepted: backend.savePreset(selectedFile.toLocalFile()) }
    FileDialog { id: loadPresetDialog; title: "사전 설정 불러오기"; fileMode: FileDialog.OpenFile; nameFilters: ["JSON (*.json)"]
        onAccepted: backend.loadPreset(selectedFile.toLocalFile()) }
    Popup { id: criticalErrorDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 440
        height: contentItem.implicitHeight
        padding: 0
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        property string errorDetails: ""
        function showError(details) { errorDetails = details; open() }
        background: Rectangle { color: root.cream; radius: 6; border.color: "#6b625d"; border.width: 1 }
        contentItem: Item {
            width: criticalErrorDialog.availableWidth
            implicitHeight: errorTitleBar.height + errorBody.implicitHeight + errorFooter.height
            Rectangle { id: errorTitleBar; width: parent.width; height: 44; color: root.ink; radius: 5
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 5; color: root.ink }
                RowLayout { anchors.fill: parent; anchors.leftMargin: 15; anchors.rightMargin: 7
                    Label { text: "처리 오류"; color: root.cream; font.family: pretendardMedium.name; font.pixelSize: 13 }
                    Item { Layout.fillWidth: true }
                    ToolButton { id: errorCloseButton; Layout.preferredWidth: 30; Layout.preferredHeight: 30; hoverEnabled: true; onClicked: criticalErrorDialog.close()
                        background: Rectangle { color: errorCloseButton.hovered ? root.burgundy : "transparent"; radius: 3 }
                        contentItem: Label { anchors.fill: parent; text: "×"; color: root.cream; font.family: pretendardMedium.name; font.pixelSize: 17; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
            ColumnLayout { id: errorBody; anchors.top: errorTitleBar.bottom; anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 18; spacing: 9
                RowLayout { Layout.fillWidth: true; spacing: 11
                    Rectangle { Layout.preferredWidth: 28; Layout.preferredHeight: 28; radius: 14; color: root.burgundy
                        Label { anchors.centerIn: parent; text: "!"; color: "white"; font.family: pretendardBold.name; font.pixelSize: 18 }
                    }
                    ColumnLayout { Layout.fillWidth: true; spacing: 2
                        Label { text: "작업 중 오류가 발생했습니다"; color: root.ink; font.family: pretendardMedium.name; font.pixelSize: 13 }
                        Label { text: "아래 내용을 확인한 뒤 다시 시도하세요."; color: root.muted; font.pixelSize: 10 }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.line }
                TextArea { id: errorDetailsText
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(124, Math.max(58, contentHeight + topPadding + bottomPadding))
                    text: criticalErrorDialog.errorDetails
                    readOnly: true
                    selectByMouse: true
                    color: root.ink
                    font.family: pretendard.name
                    font.pixelSize: 11
                    wrapMode: TextEdit.Wrap
                    background: Rectangle { color: "#f1ebe3"; radius: 4; border.color: root.line }
                }
            }
            Rectangle { id: errorFooter; anchors.top: errorBody.bottom; width: parent.width; height: 54; color: "#eee7de"; radius: 5
                Rectangle { anchors.top: parent.top; width: parent.width; height: 5; color: "#eee7de" }
                RowLayout { anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 8
                    Button { Layout.preferredWidth: 126; Layout.preferredHeight: 30; text: "오류 내용 복사"; onClicked: { errorDetailsText.selectAll(); errorDetailsText.copy(); toast.show("오류 내용을 클립보드에 복사했습니다.") }
                        background: Rectangle { color: parent.down ? "#ddd1c4" : "#d8cec3"; radius: 4 }
                        contentItem: Label { text: parent.text; color: root.ink; font.family: pretendardMedium.name; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                    Item { Layout.fillWidth: true }
                    Button { Layout.preferredWidth: 90; Layout.preferredHeight: 30; text: "확인"; onClicked: criticalErrorDialog.close()
                        background: Rectangle { color: parent.down ? "#682031" : root.burgundy; radius: 4 }
                        contentItem: Label { text: parent.text; color: "white"; font.family: pretendardMedium.name; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
        }
    }

    header: Rectangle {
        height: 52; color: root.ink
        RowLayout { anchors.fill: parent; anchors.leftMargin: 22; anchors.rightMargin: 8
            Label { text: "B"; font.family: pretendardBold.name; font.pixelSize: 20; color: root.cream; Layout.preferredWidth: 25 }
            Label { text: "BRIGHTNESS EXTRACTOR"; font.family: pretendardMedium.name; font.letterSpacing: 1.2; color: root.cream; font.pixelSize: 13 }
            Item { Layout.fillWidth: true }
            Label { text: "K-LINES / RGB RAYS"; color: "#b5aaa1"; font.pixelSize: 11; font.letterSpacing: 1 }
            ToolButton { id: minimizeButton; Layout.preferredWidth: 40; Layout.preferredHeight: 40; hoverEnabled: true; onClicked: root.showMinimized()
                background: Rectangle { color: minimizeButton.hovered ? "#4a4542" : "transparent"; radius: 3 }
                contentItem: Item { Rectangle { anchors.centerIn: parent; anchors.verticalCenterOffset: 1; width: 12; height: 1; color: root.cream } }
            }
            ToolButton { id: closeButton; Layout.preferredWidth: 40; Layout.preferredHeight: 40; hoverEnabled: true; onClicked: root.close()
                background: Rectangle { color: closeButton.hovered ? root.burgundy : "transparent"; radius: 3 }
                contentItem: Label { anchors.fill: parent; text: "×"; color: root.cream; font.family: pretendardMedium.name; font.pixelSize: 20; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            }
        }
        DragHandler { onActiveChanged: if (active) root.startSystemMove() }
    }

    RowLayout { anchors.fill: parent; spacing: 0
        Rectangle { // navigation rail
            Layout.fillHeight: true; Layout.preferredWidth: 86; color: root.ink
            Column { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 24; spacing: 22
                Repeater { model: [["▦", "대기열"], ["◈", "분해"], ["◌", "결과"]]
                    delegate: Column { width: 72; spacing: 5
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[0]; color: index === 0 ? "#ffffff" : "#9e958d"; font.pixelSize: 21 }
                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; color: index === 0 ? "#ffffff" : "#9e958d"; font.pixelSize: 10 }
                    }
                }
            }
            Label { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 20; text: "v1.0"; color: "#756d67"; font.pixelSize: 10 }
        }

        Rectangle { // queue
            Layout.fillHeight: true; Layout.preferredWidth: 315; color: "#302c2b"
            ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 14
                Label { text: "이미지 대기열"; color: root.cream; font.family: pretendardBold.name; font.pixelSize: 19 }
                Label { text: backend.items.length + "개 항목 · 순차 처리"; color: "#aaa19b"; font.pixelSize: 11 }
                Button { Layout.fillWidth: true; text: "+ 이미지 추가"; onClicked: inputDialog.open()
                    background: Rectangle { color: parent.down ? "#682031" : root.burgundy; radius: 4 }
                    contentItem: Label { text: parent.text; color: "white"; font.family: pretendardMedium.name; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                }
                Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "#272424"; radius: 5; border.color: "#49413e"; border.width: 1
                    ListView { id: queueList; anchors.fill: parent; anchors.margins: 6; model: backend.items; clip: true; spacing: 5
                        delegate: Rectangle { required property var modelData; required property int index
                            width: queueList.width; height: 86; radius: 4; color: backend.selectedIndex === index ? "#513a3b" : "#383332"
                            border.color: backend.selectedIndex === index ? "#c78383" : "transparent"
                            MouseArea { anchors.fill: parent; onClicked: backend.select(index) }
                            Row { anchors.fill: parent; anchors.margins: 8; spacing: 8
                                Rectangle { width: 48; height: 68; color: "#211f1e"; clip: true
                                    Image { anchors.fill: parent; fillMode: Image.PreserveAspectCrop; source: "file:///" + modelData.path }
                                }
                                Column { width: 90; spacing: 3
                                    Label { text: modelData.name; width: parent.width; elide: Text.ElideRight; color: "#fbf8f2"; font.pixelSize: 12 }
                                    Label { text: "N " + modelData.n + " · " + modelData.status; color: modelData.status === "실패" ? "#ff9f9f" : "#b9afa8"; font.pixelSize: 10 }
                                    ProgressBar { width: parent.width; height: 4; from: 0; to: 1; value: modelData.progress; visible: modelData.status === "처리 중"
                                        background: Rectangle { color: "#5a514e" }
                                        contentItem: Item { Rectangle { width: parent.visualPosition * parent.width; height: parent.height; color: "#c06c70" } }
                                    }
                                    Label { text: modelData.error; width: parent.width; elide: Text.ElideRight; visible: modelData.error.length > 0; color: "#ff9f9f"; font.pixelSize: 9 }
                                }
                                Column { width: 56; spacing: 3
                                    Label { text: "색상 수 N"; color: "#b9afa8"; font.pixelSize: 9 }
                                    TextField { id: rowN; text: String(modelData.n); width: 56; height: 32; enabled: !backend.running; selectByMouse: true
                                        color: "#ffffff"; font.family: pretendardBold.name; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                        validator: IntValidator { bottom: 1; top: 65534 }
                                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                                        onEditingFinished: backend.setColorCount(index, parseInt(text))
                                        background: Rectangle { radius: 3; color: "#292423"; border.color: rowN.activeFocus ? "#c78383" : "#736661" }
                                    }
                                }
                                ToolButton { width: 18; text: "×"; visible: !backend.running; onClicked: backend.remove(index)
                                    background: Rectangle { color: "transparent" }
                                    contentItem: Label { text: parent.text; color: "#c4b8b0"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                }
                            }
                        }
                        footer: Label { width: queueList.width; visible: backend.items.length === 0; text: "파일을 끌어 놓거나\n이미지를 추가하세요"; color: "#928781"; horizontalAlignment: Text.AlignHCenter; topPadding: 46; font.pixelSize: 12; lineHeight: 1.5 }
                    }
                    DropArea { anchors.fill: parent; onDropped: function(drop) { backend.addFiles(drop.urls) } }
                }
                RowLayout { Layout.fillWidth: true
                    Button { text: "설정 불러오기"; onClicked: loadPresetDialog.open(); Layout.fillWidth: true }
                    Button { text: "설정 저장"; onClicked: savePresetDialog.open(); Layout.fillWidth: true }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: root.cream
            ScrollView { id: settingsScroll; anchors.fill: parent; clip: true
                contentWidth: availableWidth
                ScrollBar.vertical.policy: ScrollBar.AsNeeded
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                Item { id: settingsContent; width: settingsScroll.availableWidth; height: settingsColumn.implicitHeight + 52
            ColumnLayout { id: settingsColumn; x: 26; y: 26; width: parent.width - 52; spacing: 16
                RowLayout { Layout.fillWidth: true
                    ColumnLayout { spacing: 2
                        Label { text: backend.selectedIndex >= 0 ? backend.items[backend.selectedIndex].name : "추출 설정"; color: root.ink; font.family: pretendardBold.name; font.pixelSize: 25 }
                        Label { text: "색상 레이와 밝기 계수를 독립적으로 구성합니다"; color: root.muted; font.pixelSize: 12 }
                    }
                    Item { Layout.fillWidth: true }
                    ColumnLayout { Layout.maximumWidth: 475; spacing: 2
                        Button { text: "출력 폴더 선택"; onClicked: folderDialog.open() }
                        Label { text: "원하는 출력 폴더 안으로 진입한 후, 하단의 폴더 열기 버튼을 누르시면 출력 위치가 선택됩니다"; color: root.muted; font.pixelSize: 10; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Label { text: backend.outputRoot.length ? backend.outputRoot : "선택된 출력 폴더 없음"; color: backend.outputRoot.length ? root.burgundy : root.muted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideLeft }
                    }
                }
                Button { Layout.fillWidth: true; text: root.advanced ? "고급 추출 설정 닫기  ▲" : "고급 추출 설정  ▾"; onClicked: root.advanced = !root.advanced
                    background: Rectangle { color: "transparent"; border.color: root.line; radius: 4 }
                    contentItem: Label { text: parent.text; leftPadding: 13; color: root.ink; verticalAlignment: Text.AlignVCenter; font.family: pretendardMedium.name }
                }
                Rectangle { visible: root.advanced; Layout.fillWidth: true; Layout.preferredHeight: visible ? (settingsContent.width < 930 ? 560 : 330) : 0; color: "#ebe3d8"; radius: 6
                    GridLayout { id: settingsAdvancedLayout; anchors.fill: parent; anchors.margins: 14; columns: settingsContent.width < 930 ? 1 : 2; rowSpacing: 16; columnSpacing: 16
                        Rectangle { Layout.preferredWidth: settingsAdvancedLayout.columns === 1 ? 0 : 430; Layout.maximumWidth: settingsAdvancedLayout.columns === 1 ? 10000 : 430; Layout.fillWidth: settingsAdvancedLayout.columns === 1; Layout.fillHeight: true; Layout.preferredHeight: settingsAdvancedLayout.columns === 1 ? 278 : -1; color: "#f5f0e8"; radius: 5; border.color: "#ddd2c5"
                            ColumnLayout { anchors.fill: parent; anchors.margins: 11; spacing: 7
                                RowLayout { Layout.fillWidth: true
                                    Label { text: "설정 값"; color: root.ink; font.family: pretendardMedium.name; font.pixelSize: 12 }
                                    Item { Layout.fillWidth: true }
                                    Label { text: "값을 수정하면 즉시 저장됩니다"; color: root.muted; font.pixelSize: 10 }
                                }
                                GridLayout { Layout.fillWidth: true; columns: 2; rowSpacing: 5; columnSpacing: 12
                                    Repeater { model: [
                                        ["하한 임계값", "threshold_low", "이 값 이하의 픽셀은 마스크에서 제외됩니다."], ["상한 임계값", "threshold_high", "이 값 이상은 마스크 값 1로 완전히 유지됩니다."],
                                        ["가중치 바닥", "atmosphere_weight_floor", "atmosphere 모드에서 어두운 색조에도 남기는 최소 맞춤 비중입니다."], ["가중치 지수", "atmosphere_weight_power", "atmosphere 모드의 밝기 편향 정도입니다."],
                                        ["재시작", "restarts", "초기값을 달리해 K-lines 맞춤을 반복하는 횟수입니다."], ["최대 반복", "max_iterations", "재시작 하나가 수행할 최대 최적화 횟수입니다."],
                                        ["수렴 기준", "convergence_tolerance", "목적함수 변화가 이 값 이하이면 해당 재시작을 멈춥니다."], ["난수 시드", "random_seed", "같은 입력과 값에서 같은 초기값을 재현합니다."],
                                        ["표본 한도", "fit_sample_limit", "0이면 유지된 모든 픽셀, 그 외에는 무작위 표본만 맞춤에 사용합니다."], ["청크 크기", "chunk_size", "맞춤 후 전체 픽셀을 분류할 때 한 번에 처리하는 수입니다."]]
                                        delegate: RowLayout { required property var modelData; Layout.fillWidth: true; spacing: 6
                                            Label { text: modelData[0]; Layout.fillWidth: true; color: root.ink; font.pixelSize: 10; elide: Text.ElideRight }
                                            TextField { text: String(root.setting[modelData[1]]); Layout.preferredWidth: 72; Layout.minimumWidth: 72; Layout.maximumWidth: 72; Layout.preferredHeight: 25; selectByMouse: true; font.pixelSize: 10; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                                                ToolTip.visible: hovered; ToolTip.text: modelData[2]
                                                onEditingFinished: { root.setting[modelData[1]] = (modelData[1] === "threshold_low" || modelData[1] === "threshold_high" || modelData[1] === "atmosphere_weight_floor" || modelData[1] === "atmosphere_weight_power" || modelData[1] === "convergence_tolerance") ? Number(text) : parseInt(text); backend.updateSelected(root.setting) }
                                            }
                                        }
                                    }
                                }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#ded4c8" }
                                GridLayout { Layout.fillWidth: true; columns: 2; rowSpacing: 5; columnSpacing: 12
                                    RowLayout { Layout.fillWidth: true
                                        Label { text: "맞춤 방식"; Layout.fillWidth: true; color: root.ink; font.pixelSize: 10 }
                                        ComboBox { Layout.preferredWidth: 146; Layout.preferredHeight: 25; model: ["atmosphere", "equal_hue", "rgb_mse"]; currentIndex: model.indexOf(root.setting.fit_mode)
                                            onActivated: { root.setting.fit_mode = currentText; backend.updateSelected(root.setting) }
                                            ToolTip.visible: hovered; ToolTip.text: "atmosphere: 밝기 편향, equal_hue: 색상 방향을 동등하게, rgb_mse: 에너지 큰 픽셀을 더 중시"
                                        }
                                    }
                                    RowLayout { Layout.fillWidth: true
                                        Label { text: "작업 색공간"; Layout.fillWidth: true; color: root.ink; font.pixelSize: 10 }
                                        ComboBox { Layout.preferredWidth: 110; Layout.preferredHeight: 25; model: ["linear_rgb", "srgb"]; currentIndex: model.indexOf(root.setting.working_space)
                                            onActivated: { root.setting.working_space = currentText; backend.updateSelected(root.setting) }
                                            ToolTip.visible: hovered; ToolTip.text: "K-lines 방향과 투영 계수를 계산할 색공간"
                                        }
                                    }
                                    RowLayout { Layout.fillWidth: true
                                        Label { text: "밝기 측정"; Layout.fillWidth: true; color: root.ink; font.pixelSize: 10 }
                                        ComboBox { Layout.preferredWidth: 146; Layout.preferredHeight: 25; model: ["max", "luminance"]; currentIndex: model.indexOf(root.setting.brightness_metric)
                                            onActivated: { root.setting.brightness_metric = currentText; backend.updateSelected(root.setting) }
                                            ToolTip.visible: hovered; ToolTip.text: "max: 최대 RGB 채널, luminance: 0.2126R + 0.7152G + 0.0722B"
                                        }
                                    }
                                    RowLayout { Layout.fillWidth: true
                                        Label { text: "측정 색공간"; Layout.fillWidth: true; color: root.ink; font.pixelSize: 10 }
                                        ComboBox { Layout.preferredWidth: 110; Layout.preferredHeight: 25; model: ["srgb", "working"]; currentIndex: model.indexOf(root.setting.brightness_space)
                                            onActivated: { root.setting.brightness_space = currentText; backend.updateSelected(root.setting) }
                                            ToolTip.visible: hovered; ToolTip.text: "밝기 B를 sRGB 또는 작업 색공간에서 측정"
                                        }
                                    }
                                }
                                RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 24; spacing: 14
                                    CompactCheckBox { text: "출력에 임계값 페이드 적용"; checked: root.setting.apply_soft_mask_to_output; onToggled: { root.setting.apply_soft_mask_to_output = checked; backend.updateSelected(root.setting) } }
                                    Label { text: "PNG 알파는 항상 0~1로 안전하게 저장됩니다."; color: root.muted; font.pixelSize: 9 }
                                }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: settingsAdvancedLayout.columns === 1 ? 230 : -1; color: "#e3d8ca"; radius: 5
                            ColumnLayout { anchors.fill: parent; anchors.margins: 13; spacing: 6
                                Label { text: "내부 동작 · 현재 기본값 기준"; color: root.ink; font.family: pretendardMedium.name; font.pixelSize: 12 }
                                Label { Layout.fillWidth: true; text: "1. 밝기 B를 구합니다. ‘측정 색공간’이 sRGB이면 원본 sRGB에서, working이면 작업 색공간에서 계산합니다. 작업 색공간이 linear_rgb이면 먼저 Linear RGB로 변환합니다. 기본값은 sRGB의 B = max(R, G, B)이며, luminance는 0.2126R + 0.7152G + 0.0722B입니다. 아래 후보 표도 이 현재 설정을 그대로 씁니다."; color: root.ink; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.18 }
                                Label { Layout.fillWidth: true; text: "2. T = smoothstep(하한, 상한, B)는 임계값 마스크이고, A는 원본 알파입니다(RGB 입력은 A = 1). 유효 픽셀은 T > 0, A > 0, RGB 크기 > 0을 모두 만족합니다. 두 알파 자산은 A × T × k를, 재구성 이미지는 A를 그대로 알파로 쓰고 밝기는 RGB에 구워 넣습니다."; color: root.ink; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.18 }
                                Label { Layout.fillWidth: true; text: "3. atmosphere 맞춤의 실제 가중치는 W = M × [F + (1 − F) × B^P]입니다. F는 가중치 바닥, P는 가중치 지수입니다. 0 < B < 1에서 P가 작을수록 어두운·중간 픽셀의 비중이 커지고, P가 클수록 밝은 픽셀 쪽으로 더 기웁니다."; color: root.ink; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.18 }
                                Label { Layout.fillWidth: true; text: "4. 유지된 RGB를 작업 색공간에서 단위 방향으로 정규화해 K-lines로 색상 레이를 찾습니다. 각 픽셀은 가장 가까운 레이를 고르고, 밝기 계수 k = dot(pixel, ray) / dot(ray, ray)로 투영합니다. 마스크 적용을 켜면 저장 밝기는 k × M입니다."; color: root.ink; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.18 }
                                Label { Layout.fillWidth: true; text: "참고: equal_hue는 W = M, rgb_mse는 W = M × ||RGB||²입니다. 0–1 제한은 k와 저장값을 잘라 PNG 범위 안에 둡니다."; color: root.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.15 }
                            }
                        }
                    }
                }
                RowLayout { Layout.fillWidth: true; Layout.preferredHeight: root.advanced ? 345 : 420; Layout.minimumHeight: 220; spacing: 16
                    Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "#e8ded1" ; radius: 6
                        ColumnLayout { anchors.fill: parent; anchors.margins: 13; spacing: 8
                            RowLayout { Layout.fillWidth: true
                                Label { text: "입력 미리보기"; color: root.ink; font.family: pretendardMedium.name; font.pixelSize: 12 }
                                Item { Layout.fillWidth: true }
                                Label { text: "Ctrl + 스크롤: 포인터 기준 확대/축소 · 최대 128×"; color: root.muted; font.pixelSize: 9 }
                            }
                            ZoomableImage { id: inputPreviewImage; Layout.fillWidth: true; Layout.fillHeight: true; imageSource: backend.selectedIndex >= 0 ? "file:///" + backend.items[backend.selectedIndex].path : "" }
                            Rectangle { id: brightnessCandidateTable; Layout.fillWidth: true; Layout.preferredHeight: visible ? candidateGrid.implicitHeight + 35 : 0; visible: backend.selectedBrightnessCandidates.length > 0; color: "#f3ece3"; radius: 4; border.color: root.line
                                Label { anchors.left: parent.left; anchors.right: parent.right; anchors.leftMargin: 8; anchors.rightMargin: 8; anchors.top: parent.top; anchors.topMargin: 6; text: "상위 밝기 비율 → B 절단값 (하한 후보 · 현재 " + root.brightnessSpaceLabel() + " / " + root.brightnessMetricLabel() + ")"; elide: Text.ElideRight; color: root.muted; font.pixelSize: 9 }
                                GridLayout { id: candidateGrid; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 6; columns: brightnessCandidateTable.width > 500 ? 5 : 3; rowSpacing: 4; columnSpacing: 4
                                    Repeater { model: backend.selectedBrightnessCandidates
                                        delegate: Rectangle { required property var modelData; implicitWidth: 76; implicitHeight: 27; color: "#fffaf2"; radius: 3
                                            RowLayout { anchors.fill: parent; anchors.leftMargin: 5; anchors.rightMargin: 5; spacing: 2
                                                Label { text: "상위 " + modelData.topPercent + "%"; color: root.muted; font.pixelSize: 8; Layout.fillWidth: true }
                                                Label { text: modelData.threshold; color: root.ink; font.family: pretendardMedium.name; font.pixelSize: 9 }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "#e8ded1"; radius: 6
                        ColumnLayout { anchors.fill: parent; anchors.margins: 13; spacing: 8
                            RowLayout { Layout.fillWidth: true
                                Label { text: "재구성 결과"; color: root.ink; font.family: pretendardMedium.name; font.pixelSize: 12 }
                                Item { Layout.fillWidth: true }
                                Label { text: "Ctrl + 스크롤: 포인터 기준 확대/축소 · 최대 128×"; color: root.muted; font.pixelSize: 9 }
                            }
                            ZoomableImage { id: reconstructionPreviewImage; Layout.fillWidth: true; Layout.fillHeight: true; imageSource: backend.selectedIndex >= 0 && backend.items[backend.selectedIndex].resultPreview.length ? "file:///" + backend.items[backend.selectedIndex].resultPreview : "" }
                        }
                    }
                }
                RowLayout { Layout.fillWidth: true
                    Button { text: "결과 폴더 열기"; enabled: backend.selectedIndex >= 0 && backend.items[backend.selectedIndex].resultDir.length > 0; onClicked: backend.openSelectedResult() }
                    Item { Layout.fillWidth: true }
                    Button { text: backend.running ? "처리 취소" : "대기열 추출 시작"; Layout.preferredWidth: 210; onClicked: backend.running ? backend.cancel() : backend.runQueue()
                        background: Rectangle { color: parent.enabled ? root.burgundy : "#b7ada5"; radius: 4 }
                        contentItem: Label { text: parent.text; color: "white"; font.family: pretendardBold.name; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
                }
            }
        }
    }
    Rectangle { id: toast; property string textValue: ""; width: 220; height: 40; radius: 4; color: root.ink; opacity: 0; anchors.right: parent.right; anchors.rightMargin: 26; anchors.top: parent.top; anchors.topMargin: 66; z: 10
        function show(text) { textValue = text; opacity = 1; timer.restart() }
        Label { anchors.fill: parent; anchors.margins: 12; text: toast.textValue; color: "#fffaf2"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
        Timer { id: timer; interval: 4200; onTriggered: toast.opacity = 0 }
        Behavior on opacity { NumberAnimation { duration: 160 } }
    }
}
