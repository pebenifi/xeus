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
                params: ["External Relays", "IR Spectrometer", "NMR Spectrometer", "PID Controller", "Alicats", "Laser", "Power Supply", "Vacuum Controller", "Water Chiller", "Valves and Fans"] 
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
            "IR Spectrometer": { id: 102, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "NMR Spectrometer": { id: 103, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "PID Controller": { id: 104, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Alicats": { id: 105, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Laser": { id: 106, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Power Supply": { id: 107, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Vacuum Controller": { id: 108, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Water Chiller": { id: 109, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" },
            "Valves and Fans": { id: 110, type: "CMD", units: "", defaultValue: "", min: "", max: "", dtype: "DT_NONE" }
        })
    }
    
    // Состояние для отслеживания раскрытых групп и активного параметра
    property string expandedMenuItem: ""
    property string activeParam: ""
    property string activeParamGroup: ""

    // При смене активного параметра выключаем опрос реле, если закрываем External Relays
    onActiveParamChanged: {
        if (activeParam !== "External Relays" && modbusManager) {
            modbusManager.disableRelayPolling()
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

                    // Список реле для External Relays
                    Column {
                        id: relayButtonsColumn
                        width: parent.width
                        spacing: 12
                        visible: false

                        Button {
                            id: relayWaterChiller
                            width: parent.width
                            height: 50
                            text: "Water Chiller"
                            font.pointSize: 18
                            checkable: true
                            property color normalColor: "#979797"
                            property color pressedColor: "#38691e"
                            background: Rectangle {
                                color: relayWaterChiller.checked ? relayWaterChiller.pressedColor : relayWaterChiller.normalColor
                                radius: 5
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

                        Button {
                            id: relayMagnetPSU
                            width: parent.width
                            height: 50
                            text: "Magnet PSU"
                            font.pointSize: 18
                            checkable: true
                            property color normalColor: "#979797"
                            property color pressedColor: "#38691e"
                            background: Rectangle {
                                color: relayMagnetPSU.checked ? relayMagnetPSU.pressedColor : relayMagnetPSU.normalColor
                                radius: 5
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

                        Button {
                            id: relayLaserPSU
                            width: parent.width
                            height: 50
                            text: "Laser PSU"
                            font.pointSize: 18
                            checkable: true
                            property color normalColor: "#979797"
                            property color pressedColor: "#38691e"
                            background: Rectangle {
                                color: relayLaserPSU.checked ? relayLaserPSU.pressedColor : relayLaserPSU.normalColor
                                radius: 5
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

                        Button {
                            id: relayVacuumPump
                            width: parent.width
                            height: 50
                            text: "Vacuum Pump"
                            font.pointSize: 18
                            checkable: true
                            property color normalColor: "#979797"
                            property color pressedColor: "#38691e"
                            background: Rectangle {
                                color: relayVacuumPump.checked ? relayVacuumPump.pressedColor : relayVacuumPump.normalColor
                                radius: 5
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

                        Button {
                            id: relayVacuumGauge
                            width: parent.width
                            height: 50
                            text: "Vacuum Gauge"
                            font.pointSize: 18
                            checkable: true
                            property color normalColor: "#979797"
                            property color pressedColor: "#38691e"
                            background: Rectangle {
                                color: relayVacuumGauge.checked ? relayVacuumGauge.pressedColor : relayVacuumGauge.normalColor
                                radius: 5
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

                        Button {
                            id: relayPIDController
                            width: parent.width
                            height: 50
                            text: "PID Controller"
                            font.pointSize: 18
                            checkable: true
                            property color normalColor: "#979797"
                            property color pressedColor: "#38691e"
                            background: Rectangle {
                                color: relayPIDController.checked ? relayPIDController.pressedColor : relayPIDController.normalColor
                                radius: 5
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
                                            
                                            // Специальная обработка для External Relays - показываем кнопки реле
                                            if (modelData === "External Relays") {
                                                // Включаем опрос реле (регистр 1021) по требованию
                                                if (modbusManager) {
                                                    modbusManager.enableRelayPolling()
                                                }
                                                // Показываем список реле вместо таблицы параметров
                                                relayButtonsColumn.visible = true
                                                paramGrid.visible = false
                                                infoTitle.text = "External Relays"
                                                infoSubtitle.text = menuItemContainer.groupData.label
                                                infoContent.text = "Control external relay devices"
                                            } else {
                                                // Для остальных параметров - стандартная таблица
                                                if (modbusManager && activeParam === "External Relays") {
                                                    // Если закрываем External Relays - выключаем опрос реле
                                                    modbusManager.disableRelayPolling()
                                                }
                                                relayButtonsColumn.visible = false
                                                
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
