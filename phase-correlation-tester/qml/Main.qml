import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    width: 1360
    height: 860
    minimumWidth: 1050
    minimumHeight: 700
    visible: true
    title: "Phase Correlation Tester"
    color: "#111317"

    property color panel: "#191c22"
    property color panel2: "#20242c"
    property color border: "#303640"
    property color textMain: "#f2f4f7"
    property color textMuted: "#9aa3af"
    property color accent: "#7db7ff"

    FileDialog {
        id: imageADialog
        title: "Choose Image A"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)", "All files (*)"]
        onAccepted: correlationEngine.setImageA(selectedFile)
    }

    FileDialog {
        id: imageBDialog
        title: "Choose Image B"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)", "All files (*)"]
        onAccepted: correlationEngine.setImageB(selectedFile)
    }

    component Card: Rectangle {
        radius: 10
        color: root.panel
        border.color: root.border
        border.width: 1
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                spacing: 2
                Text {
                    text: "Phase Correlation Tester"
                    color: root.textMain
                    font.pixelSize: 24
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Inspect global motion hypotheses instead of collapsing the result to one shift."
                    color: root.textMuted
                    font.pixelSize: 13
                }
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Analyze"
                enabled: correlationEngine.imageAUrl.length > 0 && correlationEngine.imageBUrl.length > 0
                onClicked: correlationEngine.analyze()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 240
                    spacing: 14

                    Card {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8

                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "Image A"; color: root.textMain; font.weight: Font.DemiBold }
                                Item { Layout.fillWidth: true }
                                Button { text: "Load"; onClicked: imageADialog.open() }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 7
                                color: "#0d0f13"
                                clip: true

                                Image {
                                    anchors.fill: parent
                                    anchors.margins: 5
                                    source: correlationEngine.imageAUrl
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                }
                            }
                        }
                    }

                    Card {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8

                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "Image B"; color: root.textMain; font.weight: Font.DemiBold }
                                Item { Layout.fillWidth: true }
                                Button { text: "Load"; onClicked: imageBDialog.open() }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 7
                                color: "#0d0f13"
                                clip: true

                                Image {
                                    anchors.fill: parent
                                    anchors.margins: 5
                                    source: correlationEngine.imageBUrl
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                }
                            }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "Correlation surface"
                                color: root.textMain
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                visible: correlationEngine.hasResult
                                text: correlationEngine.runtimeMs.toFixed(2) + " ms"
                                color: root.textMuted
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 7
                            color: "#090b0e"
                            clip: true

                            Image {
                                anchors.fill: parent
                                anchors.margins: 8
                                source: correlationEngine.heatmapUrl
                                fillMode: Image.PreserveAspectFit
                                cache: false
                                asynchronous: true
                            }

                            Text {
                                anchors.centerIn: parent
                                visible: !correlationEngine.hasResult
                                text: "Load two same-sized images and run Analyze"
                                color: root.textMuted
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "White cross = zero shift. White numbered rings = ranked peaks. Heat intensity shows positive phase-correlation strength."
                            color: root.textMuted
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            Card {
                Layout.preferredWidth: 330
                Layout.fillHeight: true

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 14
                    clip: true

                    ColumnLayout {
                        width: parent.width
                        spacing: 12

                        Text {
                            text: "Analysis settings"
                            color: root.textMain
                            font.pixelSize: 17
                            font.weight: Font.DemiBold
                        }

                        CheckBox {
                            text: "Apply Hann window"
                            checked: correlationEngine.hannWindow
                            onToggled: correlationEngine.hannWindow = checked
                        }

                        CheckBox {
                            id: limitSearchBox
                            text: "Limit translation search"
                            checked: correlationEngine.limitSearch
                            onToggled: correlationEngine.limitSearch = checked
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            rowSpacing: 7
                            columnSpacing: 8
                            enabled: limitSearchBox.checked
                            opacity: enabled ? 1.0 : 0.45

                            Label { text: "± X px" }
                            TextField {
                                Layout.fillWidth: true
                                text: correlationEngine.maxDx.toString()
                                validator: IntValidator { bottom: 0; top: 16384 }
                                onEditingFinished: correlationEngine.maxDx = parseInt(text || "0")
                            }

                            Label { text: "± Y px" }
                            TextField {
                                Layout.fillWidth: true
                                text: correlationEngine.maxDy.toString()
                                validator: IntValidator { bottom: 0; top: 16384 }
                                onEditingFinished: correlationEngine.maxDy = parseInt(text || "0")
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            rowSpacing: 7
                            columnSpacing: 8

                            Label { text: "Peaks" }
                            SpinBox {
                                Layout.fillWidth: true
                                from: 1
                                to: 20
                                value: correlationEngine.peakCount
                                onValueModified: correlationEngine.peakCount = value
                            }

                            Label { text: "Suppress radius" }
                            SpinBox {
                                Layout.fillWidth: true
                                from: 1
                                to: 512
                                value: correlationEngine.suppressionRadius
                                onValueModified: correlationEngine.suppressionRadius = value
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: root.border
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "Detected peaks"
                                color: root.textMain
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: correlationEngine.peaks.length.toString()
                                color: root.textMuted
                            }
                        }

                        Repeater {
                            model: correlationEngine.peaks

                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: 82
                                radius: 8
                                color: root.panel2
                                border.color: root.border

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 4

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "#" + modelData.rank
                                            color: modelData.rank === 1 ? root.accent : root.textMain
                                            font.weight: Font.Bold
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: (modelData.relative * 100).toFixed(1) + "% of peak 1"
                                            color: root.textMuted
                                            font.pixelSize: 12
                                        }
                                    }

                                    Text {
                                        text: "dx " + Number(modelData.dx).toFixed(2) + " px    dy " + Number(modelData.dy).toFixed(2) + " px"
                                        color: root.textMain
                                    }

                                    Text {
                                        text: "raw strength " + Number(modelData.strength).toExponential(4)
                                        color: root.textMuted
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }

                        Item { Layout.preferredHeight: 4 }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 42
            radius: 8
            color: root.panel2
            border.color: root.border

            Text {
                anchors.fill: parent
                anchors.margins: 11
                verticalAlignment: Text.AlignVCenter
                text: correlationEngine.statusMessage
                color: root.textMuted
                elide: Text.ElideRight
            }
        }
    }
}
