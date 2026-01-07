import QtQuick
import QtQuick.Controls
import QtGraphs
import QtQuick.VirtualKeyboard

Item {
    id: root
    anchors.fill: parent
    
    // Кэшируем состояние подключения для мгновенного доступа без синхронных операций
    // Инициализируем через сигнал после загрузки компонента, чтобы не блокировать рендеринг
    property bool cachedIsConnected: false
    
    // IR spectrum: обновляем по событию подключения + по приходу данных.
    // (Не держим таймер — оба экрана всегда загружены, иначе будем дергать IR даже когда экран "сзади")
    function _updateDashedVerticalMarker(markerSegments, xVal, yLo, yHi, xMin, xMax, tag) {
        if (!markerSegments || markerSegments.length === 0) return
        // всегда чистим старые сегменты
        for (var c = 0; c < markerSegments.length; c++) {
            try { if (markerSegments[c].clear) markerSegments[c].clear() } catch (e0) {}
        }
        if (!isFinite(xVal) || isNaN(xVal) || !isFinite(yLo) || !isFinite(yHi) || yHi <= yLo || xVal < xMin || xVal > xMax) {
            console.log("[IR] Clinicalmode: marker(" + tag + ") out of X range:", xVal, "range=", xMin, xMax)
            return
        }
        var total = yHi - yLo
        var dash = total / (markerSegments.length * 2.0) // dash + gap
        if (!isFinite(dash) || dash <= 0) return
        for (var i = 0; i < markerSegments.length; i++) {
            var seg = markerSegments[i]
            var ys = yLo + (i * 2.0) * dash
            if (ys >= yHi) break
            var ye = Math.min(ys + dash, yHi)
            try {
                if (seg.append) { seg.append(xVal, ys); seg.append(xVal, ye) }
            } catch (e1) {
                console.log("[IR] Clinicalmode: marker(" + tag + ") append failed:", i, xVal, ys, ye, e1)
            }
        }
    }

    function updateIrGraph(payload) {
        console.log("[IR] Clinicalmode updateIrGraph payload=", payload)
        if (!payload) {
            console.log("[IR] Clinicalmode: payload is null/undefined")
            return
        }

        // Предпочитаем payload.data_json (самый надежный способ получить массив чисел в QML)
        var ys = null
        if (payload.data_json !== undefined && payload.data_json !== null && payload.data_json !== "") {
            try {
                ys = JSON.parse(payload.data_json)
            } catch (ejson) {
                console.log("[IR] Clinicalmode: JSON.parse(data_json) failed:", ejson, payload.data_json)
                ys = payload.data
            }
        } else {
            ys = payload.data
        }
        if (!ys || ys.length === 0) {
            console.log("[IR] Clinicalmode: no data to draw", payload.data, payload.points)
            return
        }

        // X берём из метаданных устройства: x_min (401-402), x_max (403-404)
        var x0 = Number(payload.x_min)
        var x1 = Number(payload.x_max)
        if (!isFinite(x0) || !isFinite(x1)) { x0 = 792.0; x1 = 798.0 }
        if (x1 < x0) { var tmp = x0; x0 = x1; x1 = tmp }
        if (x1 === x0) { x1 = x0 + 1.0 }
        // если диапазон близок к "792..798", снапим к шагу 0.5, чтобы ось была ровная как на приборе
        if (Math.abs((x1 - x0) - 6.0) < 1.0) {
            x0 = Math.round(x0 * 2.0) / 2.0
            x1 = Math.round(x1 * 2.0) / 2.0
        }
        // обновляем ось X (тик 0.5 остается в ValueAxis)
        irAxisX.min = x0
        irAxisX.max = x1
        irAxisX.tickAnchor = x0
        var n = ys.length
        var dx = (n > 1) ? ((x1 - x0) / (n - 1)) : 0.0

        // Ось Y по данным (принудительно приводим к Number, т.к. элементы могут быть QVariant)
        var minY = Number(ys[0])
        var maxY = Number(ys[0])
        for (var j = 1; j < n; j++) {
            var yv = Number(ys[j])
            if (isNaN(yv)) continue
            if (yv < minY) minY = yv
            if (yv > maxY) maxY = yv
        }
        if (minY === maxY) { maxY = minY + 1 }
        var rangeY = maxY - minY
        var padY = rangeY * 0.05
        if (padY < 0.1) padY = 0.1
        irAxisY.min = minY - padY
        irAxisY.max = maxY + padY

        // QtGraphs: используем API XYSeries
        try {
            if (splineSeries.clear) splineSeries.clear()
        } catch (e) {
            console.log("[IR] Clinicalmode: splineSeries.clear() failed:", e)
        }

        var added = 0
        for (var i = 0; i < n; i++) {
            var x = x0 + dx * i
            var y = Number(ys[i])
            if (isNaN(x) || isNaN(y)) continue
            try {
                if (splineSeries.append) {
                    splineSeries.append(x, y)
                    added++
                }
            } catch (e2) {
                console.log("[IR] Clinicalmode: append failed at", i, x, y, e2)
            }
        }

        // Две "палки" (вертикальные маркеры) из метаданных:
        // - res_freq = регистры 409-410
        // - freq     = регистры 411-412
        var resX = Number(payload.res_freq)
        var freqX = Number(payload.freq)
        var yLo = irAxisY.min
        var yHi = irAxisY.max
        var xMin = irAxisX.min
        var xMax = irAxisX.max
        // пунктир делаем набором коротких сегментов (QtGraphs LineSeries не умеет DashLine)
        root._updateDashedVerticalMarker(spline.resMarkerSegments, resX, yLo, yHi, xMin, xMax, "res")
        root._updateDashedVerticalMarker(spline.freqMarkerSegments, freqX, yLo, yHi, xMin, xMax, "freq")

        var lastNonZero = -1
        for (var k = n - 1; k >= 0; k--) {
            if (Number(ys[k]) !== 0) { lastNonZero = k; break }
        }
        var xLastNonZero = (lastNonZero >= 0) ? (x0 + dx * lastNonZero) : null
        console.log("[IR] Clinicalmode: n=", n, "dx=", dx, "points added =", added, "x0=", x0, "x_last=", (x0 + dx * (n - 1)),
                    "axisY=", (minY - padY), (maxY + padY),
                    "res_freq=", resX, "freq=", freqX,
                    "lastNonZeroIdx=", lastNonZero, "xLastNonZero=", xLastNonZero,
                    "tail=", ys.slice(Math.max(0, n - 6)))
    }

    // Retry: если IR не пришел (адресация/устройство занято) — будем аккуратно запрашивать
    Timer {
        id: irRetryTimer
        interval: 2000
        repeat: true
        running: root.cachedIsConnected
        onTriggered: {
            if (modbusManager) modbusManager.requestIrSpectrum()
        }
    }

    Connections {
        target: modbusManager
        function onIrSpectrumChanged(payload) {
            root.updateIrGraph(payload)
        }
    }

    // При подключении дергаем один раз IR спектр
    Connections {
        target: modbusManager
        function onConnectionStatusChanged(connected) {
            root.cachedIsConnected = connected
            if (connected && modbusManager) {
                Qt.callLater(function() { modbusManager.requestIrSpectrum() })
            }
        }
    }
    
    // Инициализируем кэш после загрузки компонента асинхронно
    Component.onCompleted: {
        // Устанавливаем начальное значение асинхронно, чтобы не блокировать рендеринг
        Qt.callLater(function() {
            if (modbusManager) {
                root.cachedIsConnected = modbusManager.isConnected
            }
        })
    }

    Rectangle {
        id: rectangle
        anchors.fill: parent
        color: "#ffffff"

    }

    Rectangle {
        id: rectangle1
        anchors.left: rectangle2.right
        anchors.leftMargin: 17
        anchors.right: valuesPanel.right
        anchors.rightMargin: 0
        anchors.top: parent.top
        anchors.topMargin: 28
        height: 37
        color: "#979797"
        radius: 8
        border.width: 0
        Text {
            id: text1
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: 71
            height: 29
            color: "#ffffff"
            text: qsTr("Status:")
            font.pixelSize: 24
            horizontalAlignment: Text.AlignLeft
            textFormat: Text.AutoText
            scale: 1
            transformOrigin: Item.Center
        }

        Button {
            id: connectionButton
            anchors.right: parent.right
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            width: 148
            height: 30
            
            // Привязываем текст к тексту кнопки подключения из modbusManager (только "Connect" или "Disconnect")
            text: modbusManager ? modbusManager.connectionButtonText : qsTr("Connect")
            font.pointSize: 20
            font.weight: Font.Normal
            
            // Делаем кнопку кликабельной и видимой
            enabled: true
            hoverEnabled: true
            
            // Стилизация кнопки с видимым фоном
            // Используем кэшированное значение для мгновенного доступа без синхронных операций
            background: Rectangle {
                color: connectionButton.hovered ? "#888888" : (root.cachedIsConnected ? "#2d5a2d" : "#7a7a7a")
                border.color: root.cachedIsConnected ? "#00ff00" : "#888888"
                border.width: 1
                radius: 4
            }
            
            // Стилизация текста
            contentItem: Text {
                text: connectionButton.text
                font: connectionButton.font
                color: root.cachedIsConnected ? "#00ff00" : "#ffffff"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            
            // Обработчик клика
            onClicked: {
                console.log("Кнопка подключения нажата, текущий статус:", root.cachedIsConnected)
                if (modbusManager) {
                    modbusManager.toggleConnection()
                } else {
                    console.log("ОШИБКА: modbusManager не доступен!")
                }
            }
        }

        Label {
            id: label
            anchors.left: text1.right
            anchors.leftMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            width: 435
            height: 30
            visible: true
            color: "#ffffff"
            text: qsTr("Label")
            layer.enabled: false
            font.styleName: "Regular"
            font.pointSize: 24
            font.capitalization: Font.MixedCase
            clip: false
        }
    }

    Rectangle {
        id: rectangle3
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.top: spline.bottom
        anchors.topMargin: 19
        width: 480
        height: 33
        color: "#979797"

        Text {
            id: text3
            anchors.centerIn: parent
            color: "#ffffff"
            text: qsTr("NMR spectrum ")
            font.pixelSize: 20
        }
    }

    Rectangle {
        id: rectangle4
        anchors.right: parent.right
        anchors.rightMargin: 20
        anchors.top: spline1.bottom
        anchors.topMargin: 19
        width: 478
        height: 33
        color: "#979797"

        Text {
            id: text4
            anchors.centerIn: parent
            color: "#ffffff"
            text: qsTr("IR spectrum ")
            font.pixelSize: 20
        }
    }

    Rectangle {
        id: rectangle5
        anchors.right: parent.right
        anchors.rightMargin: 20
        anchors.top: parent.top
        anchors.topMargin: 27
        width: 478
        height: 33
        color: "#979797"
        Text {
            id: text5
            anchors.centerIn: parent
            color: "#ffffff"
            text: qsTr("PXE Chart")
            font.pixelSize: 20
        }
    }

    Item {
        id: clinicalModeRoot
        anchors.fill: parent

        // Получаем ссылку на главное окно для доступа к функции смены экрана
        property var mainWindow: ApplicationWindow.window ? ApplicationWindow.window : null

        Button {
            id: button
            anchors.left: parent.left
            anchors.leftMargin: 25
            anchors.top: parent.top
            anchors.topMargin: 78
            width: 160
            height: 70
            text: qsTr("Mode")
            font.pointSize: 24

            // Custom background
            background: Rectangle {
                color: button.down ? "#979797" : "#979797"
            }

            onClicked: {
                // Возвращаемся на Screen01
                if (mainWindow) {
                    mainWindow.changeScreen("Screen01");
                }
            }
        }

        // Другие элементы вашего Clinicalmode.qml...
    }

    Rectangle {
        id: rectangle2
        anchors.left: parent.left
        anchors.leftMargin: 25
        anchors.top: parent.top
        anchors.topMargin: 27
        width: 160
        height: 59
        color: "#545454"
        Text {
            id: text2
            anchors.centerIn: parent
            color: "#fafafa"
            text: qsTr("Clinical")
            font.pixelSize: 22
        }
    }


    // Данные для меню
    QtObject {
        id: menuData
        property var groups: ({
            "1 Manual Mode": { 
                label: "1 Manual Mode", 
                params: ["External Relays", "Valves and Fans", "Power Supply", "PID Controller", "Water Chiller", "Alicats", "Vacuum Controller", "Laser"] 
            },
            "2 Advanced Programs List": { 
                label: "2 Advanced Programs List", 
                params: ["Measure IR Hot Field On", "Measure IR Hot Field Off", "Acquire Hot Cell Mag Off", "Measure IR Cold", "Acquire Current HP 129XE Signal", "Automated Current Sweep On HP 129XE", "Automated Current Sweep On Water", "Acquire Reference 1H Signal", "Timed Polarization Build Up", "Timed Polarization Decay", "SEOP Cell QA Study", "SEOP Initialization", "Laser Reinitialization", "SEOP Process", "HP XE Eject", "HP XE Flow", "Clinical Sequence", "Purge Cycle Initialization", "Restore Default State"] 
            },
            "3 SEOP Parameters": { 
                label: "3 SEOP Parameters", 
                params: ["Laser Max Temp", "T Laser Max", "Laser Min Temp", "T Laser Min", "SEOP Cell Max Temp", "T Cell Max", "SEOP Cell Min Temp", "T Cell Min", "Set Temp During SEOP Ramp", "T Ramp", "SEOP Temp", "T SEOP", "Cell Refill Temp", "T Refill", "SEOP Cell Temp Ramp Duration", "SEOP Loop Time", "T SEOP LP"] 
            },
            "4 Calculated Parameters": { 
                label: "4 Calculated Parameters", 
                params: ["SEOP Process Duration", "Time SEOP", "Laser Max Output Power", "P Laser Max", "Laser PSU Max Current", "I Laser Max", "XE Concentration Gas Mixture", "Conc XE MM", "Water Proton Concentration", "Conc 1H M"] 
            },
            "5 Measured Parameters": { 
                label: "5 Measured Parameters", 
                params: ["Electron Polarization", "PRB", "129XE Polarization", "PXE", "Buildup Rate", "G SEOP", "HP 129XE T1", "T1"] 
            },
            "6 Additional Parameters": { 
                label: "6 Additional Parameters", 
                params: ["Error Bar For Electron Polarization", "PRB ERR", "Error Bar For 129XE Polarization", "PXE ERR", "Error Bar For Buildup Rate", "G SEOP ERR", "Fitted 129XE Polarization Max", "PXE Max", "Fitted 129XE Polarization Max Error Bar", "PXE Max ERR", "HP 129XE T1", "T1 ERR", "Current IR Signal", "IR Hot Field On", "Cold Cell IR Signal", "IR Cold", "Hot Cell IR Signal", "IR Hot Field Off", "Water 1H NMR Ref Signal", "S 1H"] 
            },
            "7 System Settings": { 
                label: "7 System Settings", 
                params: ["Current Datetime", "Driver N", "Language", "Setpoints Save Load", "Setpoints Reset", "Show Hidden Params", "Beep Mode", "Switchboard State", "Fault Code", "Fault Str", "Test"] 
            },
            "8 Archives": { 
                label: "8 Archives", 
                params: ["Archive View", "Archive To USB", "Archive Reset", "Archive Period", "Archive Period Emergency", "Archive Period Stop", "Archives Save To USB"] 
            }
        })
        
        // Данные о параметрах (упрощенная версия, можно расширить)
        property var params: ({
            "External Relays": { id: 101, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Valves and Fans": { id: 110, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Power Supply": { id: 107, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "PID Controller": { id: 104, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Water Chiller": { id: 109, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Alicats": { id: 105, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Vacuum Controller": { id: 108, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Laser": { id: 106, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" }
        })
    }
    
    // Состояние для отслеживания раскрытых групп и активного параметра
    property string expandedMenuItem: ""
    property string activeParam: ""
    property string activeParamGroup: ""

    // При смене активного параметра выключаем опрос реле/клапанов/вентиляторов, если закрываем соответствующие меню
    onActiveParamChanged: {
        if (modbusManager) {
            if (activeParam !== "External Relays") {
                modbusManager.disableRelayPolling()
            }
            if (activeParam !== "Valves and Fans") {
                modbusManager.disableValvePolling()
                modbusManager.disableFanPolling()
            }
        }
    }

    // Область для отображения информации о параметре (справа от sidebar)
    Rectangle {
        id: infoPanel
        anchors.left: sidebar.right
        anchors.leftMargin: 15
        anchors.top: rectangle2.bottom
        anchors.topMargin: 59
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 5
        width: 500
        color: "#f5f5f5"
        border.color: "#d3d3d3"
        border.width: 1
        radius: 8

        Column {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Text {
                id: infoTitle
                width: parent.width
                font.pixelSize: 18
                font.bold: true
                color: "#000000"
                text: "Select a parameter"
            }

            Text {
                id: infoSubtitle
                width: parent.width
                font.pixelSize: 12
                color: "#666666"
                text: "no item selected"
            }

            Rectangle {
                width: parent.width
                height: 1
                color: "#d3d3d3"
            }

            ScrollView {
                width: parent.width
                height: parent.height - infoTitle.height - infoSubtitle.height - 40
                clip: true

                Column {
                    width: infoPanel.width - 32
                    spacing: 8

                    Text {
                        id: infoContent
                        width: parent.width
                        wrapMode: Text.WordWrap
                        font.pixelSize: 13
                        color: "#000000"
                        text: "Use the menu on the left to open groups and parameters."
                    }

                    Grid {
                        id: paramGrid
                        width: parent.width
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 8
                        visible: false

                        Text { text: "ID:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramId; text: ""; font.pixelSize: 12; color: "#000000" }
                        Text { text: "Type:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramType; text: ""; font.pixelSize: 12; color: "#000000" }
                        Text { text: "Units:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramUnits; text: "—"; font.pixelSize: 12; color: "#000000" }
                        Text { text: "Default:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramDefault; text: "—"; font.pixelSize: 12; color: "#000000" }
                        Text { text: "Min:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramMin; text: "—"; font.pixelSize: 12; color: "#000000" }
                        Text { text: "Max:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramMax; text: "—"; font.pixelSize: 12; color: "#000000" }
                        Text { text: "Data Type:"; font.pixelSize: 12; color: "#666666" }
                        Text { id: paramDtype; text: "—"; font.pixelSize: 12; color: "#000000" }
                    }

                    // Таблица реле для External Relays (в стиле paramGrid с кнопками on/off справа)
                    Column {
                        id: relayTableGrid
                        width: parent.width
                        spacing: 0
                        visible: false

                        // Water Chiller
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Water Chiller:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: relayWaterChiller
                                    width: 80
                                    height: 28
                                    text: relayWaterChiller.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: relayWaterChiller.checked ? relayWaterChiller.pressedColor : relayWaterChiller.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setWaterChiller(relayWaterChiller.checked)
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onWaterChillerStateChanged(state) {
                                            if (relayWaterChiller.checked !== state) relayWaterChiller.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Magnet PSU
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Magnet PSU:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: relayMagnetPSU
                                    width: 80
                                    height: 28
                                    text: relayMagnetPSU.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: relayMagnetPSU.checked ? relayMagnetPSU.pressedColor : relayMagnetPSU.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setMagnetPSU(relayMagnetPSU.checked)
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onMagnetPSUStateChanged(state) {
                                            if (relayMagnetPSU.checked !== state) relayMagnetPSU.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Laser PSU
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Laser PSU:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: relayLaserPSU
                                    width: 80
                                    height: 28
                                    text: relayLaserPSU.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: relayLaserPSU.checked ? relayLaserPSU.pressedColor : relayLaserPSU.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setLaserPSU(relayLaserPSU.checked)
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onLaserPSUStateChanged(state) {
                                            if (relayLaserPSU.checked !== state) relayLaserPSU.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Vacuum Pump
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Vacuum Pump:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: relayVacuumPump
                                    width: 80
                                    height: 28
                                    text: relayVacuumPump.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: relayVacuumPump.checked ? relayVacuumPump.pressedColor : relayVacuumPump.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setVacuumPump(relayVacuumPump.checked)
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onVacuumPumpStateChanged(state) {
                                            if (relayVacuumPump.checked !== state) relayVacuumPump.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Vacuum Gauge
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Vacuum Gauge:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: relayVacuumGauge
                                    width: 80
                                    height: 28
                                    text: relayVacuumGauge.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: relayVacuumGauge.checked ? relayVacuumGauge.pressedColor : relayVacuumGauge.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setVacuumGauge(relayVacuumGauge.checked)
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onVacuumGaugeStateChanged(state) {
                                            if (relayVacuumGauge.checked !== state) relayVacuumGauge.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // PID Controller
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "PID Controller:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: relayPIDController
                                    width: 80
                                    height: 28
                                    text: relayPIDController.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: relayPIDController.checked ? relayPIDController.pressedColor : relayPIDController.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setPIDController(relayPIDController.checked)
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onPidControllerStateChanged(state) {
                                            if (relayPIDController.checked !== state) relayPIDController.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                    }

                    // Таблица клапанов и вентиляторов для Valves and Fans (в стиле paramGrid с кнопками on/off справа)
                    Column {
                        id: valvesFansTableGrid
                        width: parent.width
                        spacing: 0
                        visible: false

                        // Valves (X6-X12)
                        Text {
                            text: "Valves:"
                            font.pixelSize: 12
                            font.bold: true
                            color: "#666666"
                            width: parent.width
                            padding: 4
                        }
                        Rectangle { width: parent.width; height: 1; color: "#d0d0d0" }

                        // X6
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X6:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX6
                                    width: 80
                                    height: 28
                                    text: valveX6.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX6.checked ? valveX6.pressedColor : valveX6.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(5, valveX6.checked)  // valveIndex 5 = X6
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 5 && valveX6.checked !== state) valveX6.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // X7
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X7:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX7
                                    width: 80
                                    height: 28
                                    text: valveX7.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX7.checked ? valveX7.pressedColor : valveX7.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(6, valveX7.checked)  // valveIndex 6 = X7
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 6 && valveX7.checked !== state) valveX7.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // X8
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X8:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX8
                                    width: 80
                                    height: 28
                                    text: valveX8.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX8.checked ? valveX8.pressedColor : valveX8.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(7, valveX8.checked)  // valveIndex 7 = X8
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 7 && valveX8.checked !== state) valveX8.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // X9
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X9:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX9
                                    width: 80
                                    height: 28
                                    text: valveX9.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX9.checked ? valveX9.pressedColor : valveX9.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(8, valveX9.checked)  // valveIndex 8 = X9
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 8 && valveX9.checked !== state) valveX9.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // X10
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X10:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX10
                                    width: 80
                                    height: 28
                                    text: valveX10.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX10.checked ? valveX10.pressedColor : valveX10.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(9, valveX10.checked)  // valveIndex 9 = X10
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 9 && valveX10.checked !== state) valveX10.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // X11
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X11:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX11
                                    width: 80
                                    height: 28
                                    text: valveX11.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX11.checked ? valveX11.pressedColor : valveX11.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(10, valveX11.checked)  // valveIndex 10 = X11
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 10 && valveX11.checked !== state) valveX11.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // X12
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "X12:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: valveX12
                                    width: 80
                                    height: 28
                                    text: valveX12.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: valveX12.checked ? valveX12.pressedColor : valveX12.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setValve(11, valveX12.checked)  // valveIndex 11 = X12
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onValveStateChanged(valveIndex, state) {
                                            if (valveIndex === 11 && valveX12.checked !== state) valveX12.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#d0d0d0" }

                        // Fans (Inlet, Outlet, OpCell, Laser)
                        Text {
                            text: "Fans:"
                            font.pixelSize: 12
                            font.bold: true
                            color: "#666666"
                            width: parent.width
                            padding: 4
                        }
                        Rectangle { width: parent.width; height: 1; color: "#d0d0d0" }

                        // Inlet Fan 1
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Inlet Fan 1:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanInlet1
                                    width: 80
                                    height: 28
                                    text: fanInlet1.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanInlet1.checked ? fanInlet1.pressedColor : fanInlet1.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(0, fanInlet1.checked)  // fanIndex 0 = Inlet Fan 1
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 0 && fanInlet1.checked !== state) fanInlet1.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Inlet Fan 2
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Inlet Fan 2:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanInlet2
                                    width: 80
                                    height: 28
                                    text: fanInlet2.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanInlet2.checked ? fanInlet2.pressedColor : fanInlet2.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(1, fanInlet2.checked)  // fanIndex 1 = Inlet Fan 2
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 1 && fanInlet2.checked !== state) fanInlet2.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Inlet Fan 3
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Inlet Fan 3:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanInlet3
                                    width: 80
                                    height: 28
                                    text: fanInlet3.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanInlet3.checked ? fanInlet3.pressedColor : fanInlet3.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(2, fanInlet3.checked)  // fanIndex 2 = Inlet Fan 3
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 2 && fanInlet3.checked !== state) fanInlet3.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Inlet Fan 4
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Inlet Fan 4:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanInlet4
                                    width: 80
                                    height: 28
                                    text: fanInlet4.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanInlet4.checked ? fanInlet4.pressedColor : fanInlet4.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(3, fanInlet4.checked)  // fanIndex 3 = Inlet Fan 4
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 3 && fanInlet4.checked !== state) fanInlet4.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Outlet Fan 1
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Outlet Fan 1:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanOutlet1
                                    width: 80
                                    height: 28
                                    text: fanOutlet1.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanOutlet1.checked ? fanOutlet1.pressedColor : fanOutlet1.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(4, fanOutlet1.checked)  // fanIndex 4 = Outlet Fan 1
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 4 && fanOutlet1.checked !== state) fanOutlet1.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Outlet Fan 2
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Outlet Fan 2:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanOutlet2
                                    width: 80
                                    height: 28
                                    text: fanOutlet2.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanOutlet2.checked ? fanOutlet2.pressedColor : fanOutlet2.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(5, fanOutlet2.checked)  // fanIndex 5 = Outlet Fan 2
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 5 && fanOutlet2.checked !== state) fanOutlet2.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // OpCell Fan 1
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "OpCell Fan 1:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanOpCell1
                                    width: 80
                                    height: 28
                                    text: fanOpCell1.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanOpCell1.checked ? fanOpCell1.pressedColor : fanOpCell1.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(6, fanOpCell1.checked)  // fanIndex 6 = OpCell Fan 1
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 6 && fanOpCell1.checked !== state) fanOpCell1.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // OpCell Fan 2
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "OpCell Fan 2:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanOpCell2
                                    width: 80
                                    height: 28
                                    text: fanOpCell2.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanOpCell2.checked ? fanOpCell2.pressedColor : fanOpCell2.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(7, fanOpCell2.checked)  // fanIndex 7 = OpCell Fan 2
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 7 && fanOpCell2.checked !== state) fanOpCell2.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // OpCell Fan 3
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "OpCell Fan 3:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanOpCell3
                                    width: 80
                                    height: 28
                                    text: fanOpCell3.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanOpCell3.checked ? fanOpCell3.pressedColor : fanOpCell3.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(8, fanOpCell3.checked)  // fanIndex 8 = OpCell Fan 3
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 8 && fanOpCell3.checked !== state) fanOpCell3.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // OpCell Fan 4
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "OpCell Fan 4:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanOpCell4
                                    width: 80
                                    height: 28
                                    text: fanOpCell4.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanOpCell4.checked ? fanOpCell4.pressedColor : fanOpCell4.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(9, fanOpCell4.checked)  // fanIndex 9 = OpCell Fan 4
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 9 && fanOpCell4.checked !== state) fanOpCell4.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#e0e0e0" }

                        // Laser Fan
                        Row {
                            width: parent.width
                            spacing: 16
                            padding: 4
                            Text { text: "Laser Fan:"; font.pixelSize: 12; color: "#666666"; anchors.verticalCenter: parent.verticalCenter; width: 120 }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Button {
                                    id: fanLaser
                                    width: 80
                                    height: 28
                                    text: fanLaser.checked ? "ON" : "OFF"
                                    font.pixelSize: 11
                                    checkable: true
                                    property color normalColor: "#979797"
                                    property color pressedColor: "#38691e"
                                    background: Rectangle {
                                        color: fanLaser.checked ? fanLaser.pressedColor : fanLaser.normalColor
                                        radius: 3
                                    }
                                    onClicked: {
                                        if (modbusManager) modbusManager.setFan(10, fanLaser.checked)  // fanIndex 10 = Laser Fan
                                    }
                                    Connections {
                                        target: modbusManager
                                        function onFanStateChanged(fanIndex, state) {
                                            if (fanIndex === 10 && fanLaser.checked !== state) fanLaser.checked = state
                                        }
                                    }
                                }
                            }
                            Rectangle { width: parent.width - parent.padding * 2 - 120 - 80 - 16; height: 0 }
                        }
                    }
                }
            }
        }
    }

    // Панель с текущими значениями параметров (справа от infoPanel)
    Rectangle {
        id: valuesPanel
        anchors.left: infoPanel.right
        anchors.leftMargin: 20
        anchors.top: rectangle2.bottom
        anchors.topMargin: 59
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 5
        width: 547
        color: "#f5f5f5"
        border.color: "#d3d3d3"
        border.width: 1
        radius: 8

        Column {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Text {
                width: parent.width
                font.pixelSize: 18
                font.bold: true
                color: "#000000"
                text: "Current Values"
            }

            Rectangle {
                width: parent.width
                height: 1
                color: "#d3d3d3"
            }

            ScrollView {
                width: parent.width
                height: parent.height - 50
                clip: true

                Column {
                    width: valuesPanel.width - 32
                    spacing: 12

                    // Cell number
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "Cell number(#317)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "034"
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#e0e0e0"
                    }

                    // Cell Refill
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "Cell Refill(#318)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "104"
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#e0e0e0"
                    }

                    // PXe (fitted value)
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "PXe(fitted value#407)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "45.3 - 2.1%"
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#e0e0e0"
                    }

                    // PXe (Most recent)
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "PXe(Most recent#402)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "34.2 - 1.9%"
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#e0e0e0"
                    }

                    // g-SEOP
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "g-SEOP(#403+#406)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "0.055 - 0.005 min⁻¹"
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#e0e0e0"
                    }

                    // T1 (Most recent)
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "T1(Most recent#409+#410)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "95.1 - 0.3 mins"
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#e0e0e0"
                    }

                    // Prb (most recent)
                    Column {
                        width: parent.width
                        spacing: 4

                        Text {
                            width: parent.width
                            font.pixelSize: 12
                            color: "#666666"
                            text: "Prb(most recent#401+#404)"
                        }

                        Text {
                            width: parent.width
                            font.pixelSize: 14
                            font.bold: true
                            color: "#000000"
                            text: "60 - 1%"
                        }
                    }
                }
            }
        }
    }

    // Sidebar с меню параметров (с выпадающими списками)
    Rectangle {
        id: sidebar
        anchors.left: parent.left
        anchors.leftMargin: 25
        anchors.top: rectangle2.bottom
        anchors.topMargin: 59
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 5
        width: 300
        color: "#ffffff"
        border.color: "#d3d3d3"
        border.width: 0

        ScrollView {
            anchors.fill: parent
            anchors.margins: 4
            clip: true

            Column {
                width: sidebar.width - 8
                spacing: 6

                Repeater {
                    model: [
                        "1 Manual Mode",
                        "2 Advanced Programs List",
                        "3 SEOP Parameters",
                        "4 Calculated Parameters",
                        "5 Measured Parameters",
                        "6 Additional Parameters",
                        "7 System Settings",
                        "8 Archives"
                    ]

                    Column {
                        id: menuItemContainer
                        width: parent.width
                        spacing: 4
                        property bool expanded: expandedMenuItem === modelData
                        property var groupData: menuData.groups[modelData]

                        Rectangle {
                            id: menuItem
                            width: parent.width - 4
                            height: 42
                            x: 0
                            radius: 8
                            color: {
                                if (menuItemContainer.expanded) return "#666666"
                                if (mouseArea.containsMouse) return "#777777"
                                return "#545454"
                            }
                            border.width: 0

                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: menuItemContainer.expanded ? "▼" : "▶"
                                    color: "#ffffff"
                                    font.pixelSize: 10
                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: "#ffffff"
                                    text: modelData
                                    font.pixelSize: 13
                                    font.bold: menuItemContainer.expanded
                                }
                            }

                            MouseArea {
                                id: mouseArea
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    // Переключаем раскрытие
                                    if (expandedMenuItem === modelData) {
                                        expandedMenuItem = ""
                                    } else {
                                        expandedMenuItem = modelData
                                    }
                                }
                            }
                        }

                        // Выпадающий список параметров
                        Column {
                            id: paramsColumn
                            width: parent.width
                            visible: menuItemContainer.expanded
                            spacing: 3

                            Repeater {
                                model: menuItemContainer.groupData && menuItemContainer.groupData.params ? menuItemContainer.groupData.params : []

                                Rectangle {
                                    id: paramItem
                                    width: parent.width - 20
                                    x: 20
                                    height: 32
                                    radius: 6
                                    property bool isActive: activeParam === modelData && activeParamGroup === menuItemContainer.groupData.label
                                    color: {
                                        if (isActive) return "#666666"
                                        if (paramMouseArea.containsMouse) return "#888888"
                                        return "#979797"
                                    }
                                    border.width: isActive ? 1 : 0
                                    border.color: "#00d1b2"

                                    Row {
                                        anchors.left: parent.left
                                        anchors.leftMargin: 12
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 8

                                        Rectangle {
                                            width: 4
                                            height: 4
                                            radius: 2
                                            color: paramItem.isActive ? "#00d1b2" : "#ffffff"
                                            anchors.verticalCenter: parent.verticalCenter
                                        }

                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: "#ffffff"
                                            text: modelData
                                            font.pixelSize: 12
                                            font.bold: paramItem.isActive
                                        }
                                    }

                                    MouseArea {
                                        id: paramMouseArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: {
                                            // Устанавливаем активный параметр
                                            activeParam = modelData
                                            activeParamGroup = menuItemContainer.groupData.label
                                            
                                            // Специальная обработка для External Relays - показываем таблицу с кнопками
                                            if (modelData === "External Relays") {
                                                // Включаем опрос реле (регистр 1021) по требованию
                                                if (modbusManager) {
                                                    modbusManager.enableRelayPolling()
                                                }
                                                // Показываем таблицу реле с кнопками on/off справа
                                                relayTableGrid.visible = true
                                                valvesFansTableGrid.visible = false
                                                paramGrid.visible = false
                                                infoTitle.text = "External Relays"
                                                infoSubtitle.text = menuItemContainer.groupData.label
                                                infoContent.text = "Control external relay devices"
                                            } else if (modelData === "Valves and Fans") {
                                                // Включаем опрос клапанов (регистр 1111) и вентиляторов (регистр 1131) по требованию
                                                if (modbusManager) {
                                                    modbusManager.enableValvePolling()
                                                    modbusManager.enableFanPolling()
                                                }
                                                // Показываем таблицу клапанов/вентиляторов с кнопками on/off справа
                                                valvesFansTableGrid.visible = true
                                                relayTableGrid.visible = false
                                                paramGrid.visible = false
                                                infoTitle.text = "Valves and Fans"
                                                infoSubtitle.text = menuItemContainer.groupData.label
                                                infoContent.text = "Control valves (X6-X12) and fans"
                                            } else if (modelData === "Alicats") {
                                                // Показываем информацию о том, что Alicats еще не реализовано
                                                relayTableGrid.visible = false
                                                valvesFansTableGrid.visible = false
                                                paramGrid.visible = true
                                                infoTitle.text = "Alicats"
                                                infoSubtitle.text = menuItemContainer.groupData.label
                                                infoContent.text = "Alicats functionality is not yet implemented. See TODO.md for details."
                                                paramId.text = "—"
                                                paramType.text = "Not implemented"
                                                paramUnits.text = "—"
                                                paramDefault.text = "—"
                                                paramMin.text = "—"
                                                paramMax.text = "—"
                                                paramDtype.text = "—"
                                            } else {
                                                // Для остальных параметров - стандартная таблица
                                                if (modbusManager) {
                                                    if (activeParam === "External Relays") {
                                                        modbusManager.disableRelayPolling()
                                                    } else if (activeParam === "Valves and Fans") {
                                                        modbusManager.disableValvePolling()
                                                        modbusManager.disableFanPolling()
                                                    }
                                                }
                                                relayTableGrid.visible = false
                                                valvesFansTableGrid.visible = false
                                                
                                                // Получаем данные о параметре
                                                var paramData = menuData.params[modelData]
                                                
                                                // Обновляем информацию о параметре
                                                infoTitle.text = modelData
                                                infoSubtitle.text = menuItemContainer.groupData.label
                                                
                                                if (paramData) {
                                                    // Показываем таблицу параметров с реальными данными
                                                    paramGrid.visible = true
                                                    paramId.text = paramData.id ? paramData.id.toString() : "—"
                                                    paramType.text = paramData.type || "—"
                                                    paramUnits.text = paramData.units || "—"
                                                    paramDefault.text = paramData.defaultValue || "—"
                                                    paramMin.text = paramData.min || "—"
                                                    paramMax.text = paramData.max || "—"
                                                    paramDtype.text = paramData.dtype || "—"
                                                    
                                                    infoContent.text = "Parameter " + modelData + " from group " + menuItemContainer.groupData.label + ".\n\nType: " + (paramData.type || "—") + ", ID: " + (paramData.id || "—")
                                                } else {
                                                    // Если данных нет, показываем упрощенную информацию
                                                    paramGrid.visible = true
                                                    paramId.text = "—"
                                                    paramType.text = "Parameter"
                                                    paramUnits.text = "—"
                                                    paramDefault.text = "—"
                                                    paramMin.text = "—"
                                                    paramMax.text = "—"
                                                    paramDtype.text = "—"
                                                    
                                                    infoContent.text = "Parameter " + modelData + " from group " + menuItemContainer.groupData.label + ".\n\nDetailed parameter information will be available after data integration."
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }


    GraphsView {
        id: spline2
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.top: rectangle3.bottom
        anchors.topMargin: 16
        width: 480
        height: 280
        SplineSeries {
            id: splineSeries2
            XYPoint {
                x: 1
                y: 1
            }

            XYPoint {
                x: 2
                y: 4
            }

            XYPoint {
                x: 4
                y: 2
            }

            XYPoint {
                x: 5
                y: 5
            }
        }
    }

    GraphsView {
        id: spline
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.top: rectangle4.bottom
        anchors.topMargin: 16
        width: 480
        height: 280
        axisX: irAxisX
        axisY: irAxisY
        marginLeft: 0
        marginRight: 0
        marginTop: 0
        marginBottom: 0

        GraphsTheme { id: irTheme }
        theme: irTheme

        property var resMarkerSegments: []
        property var freqMarkerSegments: []

        Component.onCompleted: {
            resMarkerSegments = [
                irMarkerResFreq0, irMarkerResFreq1, irMarkerResFreq2, irMarkerResFreq3, irMarkerResFreq4, irMarkerResFreq5,
                irMarkerResFreq6, irMarkerResFreq7, irMarkerResFreq8, irMarkerResFreq9, irMarkerResFreq10, irMarkerResFreq11
            ]
            freqMarkerSegments = [
                irMarkerFreq0, irMarkerFreq1, irMarkerFreq2, irMarkerFreq3, irMarkerFreq4, irMarkerFreq5,
                irMarkerFreq6, irMarkerFreq7, irMarkerFreq8, irMarkerFreq9, irMarkerFreq10, irMarkerFreq11
            ]
            // Сетка тёмно-синяя, подписи/оси — светлые
            try { irTheme.grid.mainColor = "#102a66" } catch (e1) {}
            try { irTheme.grid.subColor = "#0b1a3a" } catch (e2) {}
            try { irTheme.axisX.mainColor = "#102a66" } catch (e3) {}
            try { irTheme.axisX.subColor = "#0b1a3a" } catch (e4) {}
            try { irTheme.axisX.labelTextColor = "#ffffff" } catch (e5) {}
            try { irTheme.axisY.mainColor = "#102a66" } catch (e6) {}
            try { irTheme.axisY.subColor = "#0b1a3a" } catch (e7) {}
            try { irTheme.axisY.labelTextColor = "#ffffff" } catch (e8) {}
        }

        ValueAxis {
            id: irAxisX
            min: 792
            max: 798
            tickAnchor: 792
            tickInterval: 0.5
        }
        ValueAxis { id: irAxisY; min: 0; max: 1 }
        SplineSeries {
            id: splineSeries
            // Линия спектра — красная
            color: "#ff0000"
            XYPoint {
                x: 1
                y: 1
            }

            XYPoint {
                x: 2
                y: 4
            }

            XYPoint {
                x: 4
                y: 2
            }

            XYPoint {
                x: 5
                y: 5
            }
        }

        // Пунктирные вертикальные маркеры (делаем набором коротких сегментов)
        // 1) res_freq — жёлтый
        LineSeries { id: irMarkerResFreq0; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq1; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq2; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq3; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq4; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq5; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq6; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq7; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq8; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq9; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq10; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreq11; color: "#ffd400"; width: 2 }

        // 2) freq — белый
        LineSeries { id: irMarkerFreq0; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq1; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq2; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq3; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq4; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq5; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq6; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq7; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq8; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq9; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq10; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreq11; color: "#ffffff"; width: 2 }
    }

    GraphsView {
        id: spline1
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.top: rectangle5.bottom
        anchors.topMargin: 16
        width: 480
        height: 280
        SplineSeries {
            id: splineSeries1
            XYPoint {
                x: 1
                y: 1
            }

            XYPoint {
                x: 2
                y: 4
            }

            XYPoint {
                x: 4
                y: 2
            }

            XYPoint {
                x: 5
                y: 5
            }
        }
    }




    Rectangle {
        id: rectangle14
        anchors.left: rectangle2.right
        anchors.leftMargin: 17
        anchors.right: valuesPanel.right
        anchors.rightMargin: 0
        anchors.top: rectangle1.bottom
        anchors.topMargin: 20
        height: 39
        color: "#424242"
        radius: 15

        Text {
            id: text14
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            color: "#ffffff"
            text: qsTr("Progress: Now")
            font.pixelSize: 22
        }

        Label {
            id: label2
            anchors.left: text14.right
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            color: "#ffffff"
            text: qsTr("Label synthesis, NEXT: label synthesis")
            font.pointSize: 22
        }
    }

}

/*##^##
Designer {
    D{i:0}D{i:1;locked:true}D{i:49;locked:true}
}
##^##*/
