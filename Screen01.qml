/*
This is a UI file (.ui.qml) that is intended to be edited in Qt Design Studio only.
It is supposed to be strictly declarative and only uses a subset of QML. If you edit
this file manually, you might introduce QML code that is not supported by Qt Design Studio.
Check out https://doc.qt.io/qtcreator/creator-quick-ui-forms.html for details on .ui.qml files.
*/

import QtQuick
import QtQuick.Controls
import QtGraphs


Rectangle {
    id: rectangle67
    anchors.fill: parent
    color: "#ffffff"
    border.color: "#293555"
    border.width: 0
    enabled: true

 Item {
    id: screen01
    anchors.fill: parent

    // Получаем ссылку на главное окно для доступа к функции смены экрана
    property var mainWindow: ApplicationWindow.window ? ApplicationWindow.window : null

    // IR spectrum on main screen
    property bool cachedIsConnected: false

    function _updateDashedVerticalMarker(markerSegments, xVal, yLo, yHi, xMin, xMax, tag) {
        if (!markerSegments || markerSegments.length === 0) return
        // всегда чистим старые сегменты
        for (var c = 0; c < markerSegments.length; c++) {
            try { if (markerSegments[c].clear) markerSegments[c].clear() } catch (e0) {}
        }
        if (!isFinite(xVal) || isNaN(xVal) || !isFinite(yLo) || !isFinite(yHi) || yHi <= yLo || xVal < xMin || xVal > xMax) {
            console.log("[IR] Screen01: marker(" + tag + ") out of X range:", xVal, "range=", xMin, xMax)
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
                console.log("[IR] Screen01: marker(" + tag + ") append failed:", i, xVal, ys, ye, e1)
            }
        }
    }

    function updateIrGraphMain(payload) {
        console.log("[IR] Screen01 updateIrGraphMain payload=", payload)
        if (!payload) {
            console.log("[IR] Screen01: payload is null/undefined")
            return
        }

        // Предпочитаем payload.data_json (самый надежный способ получить массив чисел в QML)
        var ys = null
        if (payload.data_json !== undefined && payload.data_json !== null && payload.data_json !== "") {
            try {
                ys = JSON.parse(payload.data_json)
            } catch (ejson) {
                console.log("[IR] Screen01: JSON.parse(data_json) failed:", ejson, payload.data_json)
                ys = payload.data
            }
        } else {
            ys = payload.data
        }
        if (!ys || ys.length === 0) {
            console.log("[IR] Screen01: no data to draw", payload.data, payload.points)
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
        irAxisXMain.min = x0
        irAxisXMain.max = x1
        irAxisXMain.tickAnchor = x0
        var n = ys.length
        // Шаг вычисляется как (x_max - x_min) / status, где status из регистра 400
        // Формула: dx = (x_max - x_min) / status, x[i] = x_min + dx * i
        var status = Number(payload.status)
        var dx = (status > 0 && isFinite(status)) ? ((x1 - x0) / status) : ((n > 1) ? ((x1 - x0) / (n - 1)) : 0.0)

        // Ось Y берём из метаданных устройства: y_min (405-406), y_max (407-408)
        var y0 = Number(payload.y_min)
        var y1 = Number(payload.y_max)
        if (!isFinite(y0) || !isFinite(y1) || y0 === y1) {
            // Fallback: если метаданные невалидны, вычисляем из данных
            y0 = Number(ys[0])
            y1 = Number(ys[0])
            for (var j = 1; j < n; j++) {
                var yv = Number(ys[j])
                if (isNaN(yv)) continue
                if (yv < y0) y0 = yv
                if (yv > y1) y1 = yv
            }
        }
        if (y1 < y0) { var tmp = y0; y0 = y1; y1 = tmp }
        if (y1 === y0) { y1 = y0 + 1.0 }
        // Добавляем небольшой паддинг для лучшей видимости
        var rangeY = y1 - y0
        var padY = rangeY * 0.05
        if (padY < 0.1) padY = 0.1
        irAxisYMain.min = y0 - padY
        irAxisYMain.max = y1 + padY
        
        // Вычисляем min/max из данных для логирования
        var minY = Number(ys[0])
        var maxY = Number(ys[0])
        for (var j = 1; j < n; j++) {
            var yv = Number(ys[j])
            if (isNaN(yv)) continue
            if (yv < minY) minY = yv
            if (yv > maxY) maxY = yv
        }

        // Собираем все валидные точки в массив координат
        // Растягиваем все точки на весь диапазон от x0 до x1, чтобы последняя точка была на x1
        // Используем status для вычисления шага, но распределяем точки равномерно на весь диапазон
        var pointsToAdd = []
        var validPoints = 0
        for (var i = 0; i < n; i++) {
            // Формула: x[i] = x0 + (x1 - x0) * i / (n-1) - растягивает на весь диапазон
            var x = (n > 1) ? (x0 + (x1 - x0) * i / (n - 1)) : x0
            var y = Number(ys[i])
            if (isFinite(x) && isFinite(y) && !isNaN(x) && !isNaN(y)) {
                pointsToAdd.push({x: x, y: y})
                validPoints++
            }
        }
        
        console.log("[IR] Screen01: prepared", validPoints, "valid points out of", n, "total, first=", 
                   pointsToAdd.length > 0 ? (pointsToAdd[0].x + "," + pointsToAdd[0].y) : "none",
                   "last=", pointsToAdd.length > 0 ? (pointsToAdd[pointsToAdd.length-1].x + "," + pointsToAdd[pointsToAdd.length-1].y) : "none")
        
        // Очищаем серию перед добавлением новых точек
        try {
            if (splineSeries1.clear) {
                splineSeries1.clear()
            }
        } catch (e) {
            console.log("[IR] Screen01: splineSeries1.clear() failed:", e)
        }
        
        // Добавляем все точки быстро в одном блоке
        // QtGraphs будет пересчитывать сплайн только после завершения функции
        var added = 0
        for (var j = 0; j < pointsToAdd.length; j++) {
            try {
                if (splineSeries1.append) {
                    splineSeries1.append(pointsToAdd[j].x, pointsToAdd[j].y)
                    added++
                }
            } catch (e2) {
                console.log("[IR] Screen01: append failed at", j, pointsToAdd[j].x, pointsToAdd[j].y, e2)
            }
        }
        
        console.log("[IR] Screen01: added", added, "points out of", pointsToAdd.length, "prepared, series count=", (splineSeries1.count !== undefined ? splineSeries1.count : "unknown"))

        // Две "палки" (вертикальные маркеры) из метаданных:
        // - res_freq = регистры 409-410
        // - freq     = регистры 411-412
        var resX = Number(payload.res_freq)
        var freqX = Number(payload.freq)
        var yLo = irAxisYMain.min
        var yHi = irAxisYMain.max
        var xMin = irAxisXMain.min
        var xMax = irAxisXMain.max
        // пунктир делаем набором коротких сегментов (QtGraphs LineSeries не умеет DashLine)
        screen01._updateDashedVerticalMarker(spline1.resMarkerSegments, resX, yLo, yHi, xMin, xMax, "res")
        screen01._updateDashedVerticalMarker(spline1.freqMarkerSegments, freqX, yLo, yHi, xMin, xMax, "freq")

        // Диагностика: где заканчиваются ненулевые значения
        var lastNonZero = -1
        for (var k = n - 1; k >= 0; k--) {
            if (Number(ys[k]) !== 0) { lastNonZero = k; break }
        }
        var xLastNonZero = (lastNonZero >= 0) ? (x0 + dx * lastNonZero) : null
        console.log("[IR] Screen01: n=", n, "dx=", dx, "points added =", added, "x0=", x0, "x_last=", (x0 + dx * (n - 1)),
                    "axisY=[" + (y0 - padY) + "," + (y1 + padY) + "] (from payload y_min=" + payload.y_min + " y_max=" + payload.y_max + ") dataY=[" + minY + "," + maxY + "]",
                    "res_freq=", resX, "freq=", freqX,
                    "lastNonZeroIdx=", lastNonZero, "xLastNonZero=", xLastNonZero,
                    "tail=", ys.slice(Math.max(0, n - 6)))
    }

    Connections {
        target: modbusManager
        function onConnectionStatusChanged(connected) {
            screen01.cachedIsConnected = connected
            if (connected && modbusManager) {
                Qt.callLater(function() { modbusManager.requestIrSpectrum() })
            }
        }
        function onIrSpectrumChanged(payload) {
            screen01.updateIrGraphMain(payload)
        }
    }

    Timer {
        id: irRetryTimer
        interval: 2000
        repeat: true
        running: screen01.cachedIsConnected
        onTriggered: {
            if (modbusManager) modbusManager.requestIrSpectrum()
        }
    }

    Button {
        id: modeButton
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
            color: modeButton.down ? "#979797" : "#979797"
        }

        // Optional: Customize text color
        contentItem: Text {
            text: modeButton.text
            font: modeButton.font
            color: "#ffffff" // White text for contrast
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        onClicked: {
            // Переходим на Clinicalmode
            if (mainWindow) {
                mainWindow.changeScreen("Clinicalmode");
            }
        }
    }
}

    Button {
        id: button2
        anchors.right: parent.right
        anchors.rightMargin: 20
        anchors.top: parent.top
        anchors.topMargin: 28
        width: 155
        height: 50
        text: qsTr("InLet Fan - 3")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button2.checked ? button2.pressedColor : button2.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(2, button2.checked)  // InLet Fan - 3
            }
        }
        
        // Синхронизация состояния с Modbus (только для обратной связи с устройством)
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 2) {
                    // Обновляем только если состояние отличается (для синхронизации)
                    if (button2.checked !== state) {
                        button2.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button3
        anchors.right: button2.left
        anchors.rightMargin: 7
        anchors.top: parent.top
        anchors.topMargin: 28
        width: 155
        height: 50
        text: qsTr("InLet Fan - 2")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button3.checked ? button3.pressedColor : button3.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(1, button3.checked)  // InLet Fan - 2
            }
        }
        
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 1) {
                    if (button3.checked !== state) {
                        button3.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button4
        anchors.right: button3.left
        anchors.rightMargin: 7
        anchors.top: parent.top
        anchors.topMargin: 28
        width: 155
        height: 50
        text: qsTr("InLet Fan - 1")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button4.checked ? button4.pressedColor : button4.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(0, button4.checked)  // InLet Fan - 1
            }
        }
        
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 0) {
                    if (button4.checked !== state) {
                        button4.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button5
        x: 1745
        y: 84
        width: 155
        height: 50
        text: qsTr("OutLet Fan - 2")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button5.checked ? button5.pressedColor : button5.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(5, button5.checked)  // OutLet Fan - 2
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 5) {
                    if (button5.checked !== state) {
                        button5.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button6
        x: 1583
        y: 84
        width: 155
        height: 50
        text: qsTr("OutLet Fan - 1")
        font.pointSize: 22
        rotation: 0
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button6.checked ? button6.pressedColor : button6.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(4, button6.checked)  // OutLet Fan - 1
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 4) {
                    if (button6.checked !== state) {
                        button6.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button7
        x: 1421
        y: 84
        width: 155
        height: 50
        text: qsTr("InLet Fan - 4")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button7.checked ? button7.pressedColor : button7.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(3, button7.checked)  // InLet Fan - 4
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 3) {
                    if (button7.checked !== state) {
                        button7.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button8
        x: 1745
        y: 140
        width: 155
        height: 50
        text: qsTr("OpCell Fan - 3")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button8.checked ? button8.pressedColor : button8.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(8, button8.checked)  // OpCell Fan - 3
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 8) {
                    if (button8.checked !== state) {
                        button8.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button9
        x: 1583
        y: 140
        width: 155
        height: 50
        text: qsTr("OpCell Fan - 2")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button9.checked ? button9.pressedColor : button9.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(7, button9.checked)  // OpCell Fan - 2
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 7) {
                    if (button9.checked !== state) {
                        button9.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button10
        x: 1421
        y: 140
        width: 155
        height: 50
        text: qsTr("OpCell Fan - 1")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button10.checked ? button10.pressedColor : button10.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(6, button10.checked)  // OpCell Fan - 1
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 6) {
                    if (button10.checked !== state) {
                        button10.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button11
        x: 1745
        y: 196
        width: 155
        height: 50
        text: qsTr("Laser PSU")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button11.checked ? button11.pressedColor : button11.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setLaserPSU, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setLaserPSU(button11.checked)
            }
        }
        
        Connections {
            target: modbusManager
            function onLaserPSUStateChanged(state) {
                // Обновляем только если состояние отличается (для синхронизации)
                if (button11.checked !== state) {
                    button11.checked = state
                }
            }
        }
    }

    Button {
        id: button12
        x: 1583
        y: 196
        width: 155
        height: 50
        text: qsTr("Laser Fans")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button12.checked ? button12.pressedColor : button12.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(10, button12.checked)  // Laser Fans
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 10) {
                    if (button12.checked !== state) {
                        button12.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button13
        x: 1421
        y: 196
        width: 155
        height: 50
        text: qsTr("OpCell Fan - 4")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button13.checked ? button13.pressedColor : button13.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setFan, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setFan(9, button13.checked)  // OpCell Fan - 4
            }
        }
        Connections {
            target: modbusManager
            function onFanStateChanged(fanIndex, state) {
                if (fanIndex === 9) {
                    if (button13.checked !== state) {
                        button13.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button14
        x: 1745
        y: 252
        width: 155
        height: 50
        text: qsTr("Magnet PSU")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button14.checked ? button14.pressedColor : button14.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setMagnetPSU, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setMagnetPSU(button14.checked)
            }
        }
        
        Connections {
            target: modbusManager
            function onMagnetPSUStateChanged(state) {
                // Обновляем только если состояние отличается (для синхронизации)
                if (button14.checked !== state) {
                    button14.checked = state
                }
            }
        }
    }

    Button {
        id: button15
        x: 1583
        y: 252
        width: 155
        height: 50
        text: qsTr("PID Controller")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button15.checked ? button15.pressedColor : button15.normalColor
            radius: 5
        }
        
        onClicked: {
            // Проверка подключения выполняется внутри setPIDController, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setPIDController(button15.checked)
            }
        }
        
        Connections {
            target: modbusManager
            function onPidControllerStateChanged(state) {
                // Обновляем только если состояние отличается (для синхронизации)
                if (button15.checked !== state) {
                    button15.checked = state
                }
            }
        }
    }

    Button {
        id: button16
        x: 1421
        y: 252
        width: 155
        height: 50
        text: qsTr("Water Chiller")
        font.pointSize: 22
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button16.checked ? button16.pressedColor : button16.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setWaterChiller, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setWaterChiller(button16.checked)
            }
        }
        
        Connections {
            target: modbusManager
            function onWaterChillerStateChanged(state) {
                // Обновляем только если состояние отличается (для синхронизации)
                if (button16.checked !== state) {
                    button16.checked = state
                }
            }
        }
    }

    Button {
        id: button17
        x: 1746
        y: 308
        width: 155
        height: 50
        text: qsTr("Reserve")
        font.pointSize: 22
        topPadding: 6
        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#979797"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button17.checked ? button17.pressedColor : button17.normalColor
            radius: 5
        }

    }

    Button {
        id: button18
        x: 1584
        y: 308
        width: 155
        height: 50
        text: qsTr("Vacuum Gauge")
        font.pointSize: 21
        icon.color: "#7a7a7a"
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button18.checked ? button18.pressedColor : button18.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setVacuumGauge, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setVacuumGauge(button18.checked)
            }
        }
        
        Connections {
            target: modbusManager
            function onVacuumGaugeStateChanged(state) {
                // Обновляем только если состояние отличается (для синхронизации)
                if (button18.checked !== state) {
                    button18.checked = state
                }
            }
        }
    }

    Button {
        id: button19
        x: 1422
        y: 308
        width: 155
        height: 50
        text: qsTr("Vacuum Pump")
        font.pointSize: 22
        icon.color: "#7a7a7a"
        topPadding: 6

        // Делаем кнопку переключаемой
        checkable: true

        // Свойства для настройки цветов
        property color normalColor: "#979797"  // Обычный цвет (исходный)
        property color pressedColor: "#38691e"     // Цвет при нажатии (можно менять на любой HEX)

        // Фон кнопки, который меняется в зависимости от состояния checked
        background: Rectangle {
            color: button19.checked ? button19.pressedColor : button19.normalColor
            radius: 5
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setVacuumPump, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setVacuumPump(button19.checked)
            }
        }
        
        Connections {
            target: modbusManager
            function onVacuumPumpStateChanged(state) {
                // Обновляем только если состояние отличается (для синхронизации)
                if (button19.checked !== state) {
                    button19.checked = state
                }
            }
        }
    }

    Rectangle {
        id: rectangle
        anchors.left: parent.left
        anchors.leftMargin: 204
        anchors.right: button4.left
        anchors.rightMargin: 20
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
            background: Rectangle {
                color: connectionButton.hovered ? "#888888" : (modbusManager && modbusManager.isConnected ? "#2d5a2d" : "#7a7a7a")
                border.color: modbusManager && modbusManager.isConnected ? "#00ff00" : "#888888"
                border.width: 1
                radius: 4
            }
            
            // Стилизация текста
            contentItem: Text {
                text: connectionButton.text
                font: connectionButton.font
                color: modbusManager && modbusManager.isConnected ? "#00ff00" : "#ffffff"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            
            // Обработчик клика
            onClicked: {
                console.log("Кнопка подключения нажата, текущий статус:", modbusManager ? modbusManager.isConnected : "modbusManager не доступен")
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
            text: modbusManager ? modbusManager.statusText : qsTr("Disconnected")
            font.pointSize: 24
            font.styleName: "Regular"
            
            Connections {
                target: modbusManager
                function onStatusTextChanged(statusText) {
                    label.text = statusText
                }
            }
            clip: false
            layer.enabled: false
            font.capitalization: Font.MixedCase
        }
    }

    Rectangle {
        id: rectangle1
        anchors.right: parent.right
        anchors.rightMargin: 19
        anchors.top: rectangle.bottom
        anchors.topMargin: 308
        width: 520
        height: 33
        color: "#979797"
    }

    Text {
        id: text2
        anchors.centerIn: rectangle1
        color: "#ffffff"
        text: qsTr("NMR spectrum")
        font.pixelSize: 20
    }

    GraphsView {
        id: spline
        anchors.right: parent.right
        anchors.rightMargin: 19
        anchors.top: rectangle1.bottom
        anchors.topMargin: 16
        width: 520
        height: 289
        SplineSeries {
            id: splineSeries
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
        id: rectangle2
        anchors.right: parent.right
        anchors.rightMargin: 19
        anchors.top: spline.bottom
        anchors.topMargin: 19
        width: 520
        height: 33
        color: "#979797"
    }

    GraphsView {
        id: spline1
        anchors.right: parent.right
        anchors.rightMargin: 19
        anchors.top: rectangle2.bottom
        anchors.topMargin: 16
        // Растягиваем график влево и вниз (как на скрине: там есть свободное место)
        width: 520
        height: 320
        axisX: irAxisXMain
        axisY: irAxisYMain
        // Убираем лишние внутренние отступы (по умолчанию ~20px) — больше места под plotArea и подписи
        marginLeft: 0
        marginRight: 0
        marginTop: 0
        marginBottom: 0
        // Тема для сетки/подписей (безопасно настраиваем через try/catch в onCompleted)
        GraphsTheme { id: irThemeMain }
        theme: irThemeMain

        property var resMarkerSegments: []
        property var freqMarkerSegments: []

        Component.onCompleted: {
            resMarkerSegments = [
                irMarkerResFreqMain0, irMarkerResFreqMain1, irMarkerResFreqMain2, irMarkerResFreqMain3, irMarkerResFreqMain4, irMarkerResFreqMain5,
                irMarkerResFreqMain6, irMarkerResFreqMain7, irMarkerResFreqMain8, irMarkerResFreqMain9, irMarkerResFreqMain10, irMarkerResFreqMain11
            ]
            freqMarkerSegments = [
                irMarkerFreqMain0, irMarkerFreqMain1, irMarkerFreqMain2, irMarkerFreqMain3, irMarkerFreqMain4, irMarkerFreqMain5,
                irMarkerFreqMain6, irMarkerFreqMain7, irMarkerFreqMain8, irMarkerFreqMain9, irMarkerFreqMain10, irMarkerFreqMain11
            ]
            // Сетка тёмно-синяя, подписи/оси — светлые
            try { irThemeMain.grid.mainColor = "#102a66" } catch (e1) {}
            try { irThemeMain.grid.subColor = "#0b1a3a" } catch (e2) {}
            try { irThemeMain.axisX.mainColor = "#102a66" } catch (e3) {}
            try { irThemeMain.axisX.subColor = "#0b1a3a" } catch (e4) {}
            try { irThemeMain.axisX.labelTextColor = "#ffffff" } catch (e5) {}
            try { irThemeMain.axisY.mainColor = "#102a66" } catch (e6) {}
            try { irThemeMain.axisY.subColor = "#0b1a3a" } catch (e7) {}
            try { irThemeMain.axisY.labelTextColor = "#ffffff" } catch (e8) {}
        }

        ValueAxis {
            id: irAxisXMain
            min: 792
            max: 798
            tickAnchor: 792
            tickInterval: 0.5
        }
        ValueAxis { id: irAxisYMain; min: 0; max: 1 }
        LineSeries {
            id: splineSeries1
            // Линия спектра — красная, без сглаживания
            color: "#ff0000"
            width: 2
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
        LineSeries { id: irMarkerResFreqMain0; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain1; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain2; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain3; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain4; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain5; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain6; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain7; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain8; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain9; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain10; color: "#ffd400"; width: 2 }
        LineSeries { id: irMarkerResFreqMain11; color: "#ffd400"; width: 2 }

        // 2) freq — белый
        LineSeries { id: irMarkerFreqMain0; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain1; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain2; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain3; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain4; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain5; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain6; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain7; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain8; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain9; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain10; color: "#ffffff"; width: 2 }
        LineSeries { id: irMarkerFreqMain11; color: "#ffffff"; width: 2 }
    }

    Text {
        id: text3
        anchors.centerIn: rectangle2
        color: "#ffffff"
        text: qsTr("IR spectrum")
        font.pixelSize: 20
    }

    Rectangle {
        id: rectangle3
        x: 166
        y: 205
        width: 150
        height: 75
        color: "#381b6b"
        radius: 12

        Text {
            id: text30
            x: 65
            y: 8
            color: "#ffffff"
            text: qsTr("N2")
            font.pixelSize: 15
        }

        // Поле ввода с стрелками (как у Xenon)
        Rectangle {
            x: 38
            y: 47
            width: 100
            height: 25
            color: "transparent"
            border.width: 0
            radius: 3
            
            // Отдельный Rectangle для белого края
            Rectangle {
                x: 2
                y: 0
                width: parent.width - 28
                height: parent.height
                color: "transparent"
                border.color: "transparent"
                border.width: 0
                radius: 3
            }
            
            Row {
                anchors.fill: parent
                anchors.margins: 2
                anchors.rightMargin: 17
                spacing: -3
                
                // Поле ввода для значения
                TextInput {
                    id: textInput3
                    width: parent.width - 48
                    height: parent.height
                    color: "#ffffff"
                    text: {
                        if (modbusManager && modbusManager.n2Setpoint !== undefined) {
                            return (modbusManager.n2Setpoint / 1000.0).toFixed(3)
                        } else {
                            return "0.000"
                        }
                    }
                    font.pixelSize: 15
                    selectByMouse: true
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 5
                    inputMethodHints: Qt.ImhDigitsOnly
                    
                    validator: IntValidator {
                        bottom: 0
                        top: 1000
                    }
                    
                    Connections {
                        target: modbusManager
                        function onN2SetpointChanged(setpoint) {
                            if (!textInput3.activeFocus) {
                                var currentText = parseFloat(textInput3.text)
                                if (isNaN(currentText) || Math.abs(currentText - setpoint / 1000.0) > 0.001) {
                                    textInput3.text = (setpoint / 1000.0).toFixed(3)
                                }
                            }
                        }
                    }
                    
                    onEditingFinished: {
                        if (modbusManager) {
                            var textValue = text.trim()
                            var value = parseFloat(textValue)
                            if (!isNaN(value) && value >= 0) {
                                modbusManager.setN2SetpointValue(value)
                                if (modbusManager.isConnected) {
                                    modbusManager.setN2Pressure(value)
                                }
                            } else {
                                text = modbusManager ? modbusManager.n2Setpoint.toFixed(2) : "0.00"
                            }
                        }
                    }
                    
                    onTextChanged: {
                        var cleaned = text.replace(/[^\d.-]/g, '')
                        if (cleaned !== text) {
                            var cursorPos = cursorPosition
                            text = cleaned
                            cursorPosition = Math.min(cursorPos, text.length)
                        }
                        
                        if (modbusManager && text.trim() !== "") {
                            var value = parseFloat(text)
                            if (!isNaN(value) && value >= 0) {
                                // Умножаем на 1000 для сравнения с внутренним значением
                                var deviceValue = value * 1000.0
                                var currentSetpoint = modbusManager.n2Setpoint
                                if (Math.abs(deviceValue - currentSetpoint) > 1.0) {
                                    modbusManager.setN2SetpointValue(deviceValue)
                                }
                            }
                        }
                    }
                    
                    Keys.onReturnPressed: {
                        editingFinished()
                    }
                    Keys.onEnterPressed: {
                        editingFinished()
                    }
                }
                
                // Контейнер для стрелок
                Column {
                    width: 16
                    height: parent.height
                    spacing: 0
                    
                    Button {
                        id: n2TempUpButton
                        width: parent.width
                        height: parent.height / 2
                        text: "+"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: n2TempUpButton.text
                            color: "#ffffff"
                            font: n2TempUpButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            var textValue = textInput3.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.n2Setpoint / 1000.0
                            }
                            
                            // Вычисляем новое значение (увеличиваем на 0.001)
                            var newValue = currentValue + 0.001
                            textInput3.text = newValue.toFixed(3)
                            // Умножаем на 1000 для отправки на устройство
                            modbusManager.setN2SetpointValue(newValue * 1000.0)
                        }
                    }
                    
                    Button {
                        id: n2TempDownButton
                        width: parent.width
                        height: parent.height / 2
                        text: "-"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: n2TempDownButton.text
                            color: "#ffffff"
                            font: n2TempDownButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            var textValue = textInput3.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.n2Setpoint / 1000.0
                            }
                            
                            // Вычисляем новое значение (уменьшаем на 0.001)
                            var newValue = currentValue - 0.001
                            if (newValue < 0) newValue = 0  // Не позволяем отрицательные значения
                            textInput3.text = newValue.toFixed(3)
                            // Умножаем на 1000 для отправки на устройство
                            modbusManager.setN2SetpointValue(newValue * 1000.0)
                        }
                    }
                }
            }
            
            // Кнопка "set"
            Button {
                id: n2SetButton
                width: 30
                height: parent.height - 4
                anchors.right: parent.right
                anchors.rightMargin: 25
                anchors.verticalCenter: parent.verticalCenter
                text: "set"
                font.pixelSize: 10
                
                background: Rectangle {
                    color: n2SetButton.pressed ? "#555555" : "transparent"
                    radius: 2
                }
                
                contentItem: Text {
                    text: n2SetButton.text
                    color: "#ffffff"
                    font: n2SetButton.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                
                onClicked: {
                    if (modbusManager && modbusManager.isConnected) {
                        var value = parseFloat(textInput3.text)
                        if (!isNaN(value) && value >= 0) {
                            // Умножаем на 1000 для отправки на устройство
                            var deviceValue = value * 1000.0
                            modbusManager.setN2SetpointValue(deviceValue)
                            modbusManager.setN2Pressure(deviceValue)
                        }
                    }
                }
            }
        }

        Label {
            id: label2
            x: 43
            y: 27
            width: 77
            height: 18
            color: "#ffffff"
            text: modbusManager ? ((modbusManager.n2Pressure / 1000.0).toFixed(3) + " Torr") : qsTr("--")
            font.pointSize: 15
            
            Connections {
                target: modbusManager
                function onN2PressureChanged(pressure) {
                    label2.text = (pressure / 1000.0).toFixed(3) + " Torr"
                }
            }
        }
    }

    Rectangle {
        id: rectangle4
        x: 404
        y: 312
        width: 150
        height: 75
        color: "#467a28"
        radius: 12

        Text {
            id: text33
            x: 34
            y: 9
            color: "#ffffff"
            text: qsTr("Magnet PSU")
            font.pixelSize: 15
        }

        Label {
            id: label5
            x: 51
            y: 30
            color: "#ffffff"
            text: modbusManager ? (modbusManager.magnetPSUCurrent.toFixed(2) + "A") : qsTr("--")
            font.pointSize: 15
            
            Connections {
                target: modbusManager
                function onMagnetPSUCurrentChanged(current) {
                    label5.text = current.toFixed(2) + "A"
                }
            }
        }

        // Поле ввода с стрелками (как у Water Chiller)
        Rectangle {
            x: 47
            y: 47
            width: 100
            height: 25
            color: "transparent"
            border.width: 0
            radius: 3
            
            // Отдельный Rectangle для белого края
            Rectangle {
                x: 2
                y: 0
                width: parent.width - 28
                height: parent.height
                color: "transparent"
                border.color: "transparent"
                border.width: 0
                radius: 3
            }
            
            Row {
                anchors.fill: parent
                anchors.margins: 2
                anchors.rightMargin: 17
                spacing: -3
                
                // Поле ввода для значения
                TextInput {
                    id: textInput5
                    width: parent.width - 48
                    height: parent.height
                    color: "#ffffff"
                    text: {
                        if (modbusManager && modbusManager.magnetPSUSetpoint !== undefined) {
                            return modbusManager.magnetPSUSetpoint.toFixed(3)
                        } else {
                            return "0.000"
                        }
                    }
                    font.pixelSize: 15
                    selectByMouse: true
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 5
                    inputMethodHints: Qt.ImhDigitsOnly
                    
                    validator: IntValidator {
                        bottom: 0
                        top: 100
                    }
                    
                    Connections {
                        target: modbusManager
                        function onMagnetPSUSetpointChanged(setpoint) {
                            if (!textInput5.activeFocus) {
                                var currentText = parseFloat(textInput5.text)
                                if (isNaN(currentText) || Math.abs(currentText - setpoint) > 0.001) {
                                    textInput5.text = setpoint.toFixed(3)
                                }
                            }
                        }
                    }
                    
                    onEditingFinished: {
                        if (modbusManager) {
                            var textValue = text.trim()
                            var value = parseFloat(textValue)
                            if (!isNaN(value) && value >= 0) {
                                modbusManager.setMagnetPSUSetpointValue(value)
                                if (modbusManager.isConnected) {
                                    modbusManager.setMagnetPSUTemperature(value)
                                }
                            } else {
                                text = modbusManager ? modbusManager.magnetPSUSetpoint.toFixed(3) : "0.000"
                            }
                        }
                    }
                    
                    onTextChanged: {
                        var cleaned = text.replace(/[^\d.-]/g, '')
                        if (cleaned !== text) {
                            var cursorPos = cursorPosition
                            text = cleaned
                            cursorPosition = Math.min(cursorPos, text.length)
                        }
                        
                        if (modbusManager && text.trim() !== "") {
                            var value = parseFloat(text)
                            if (!isNaN(value) && value >= 0) {
                                var currentSetpoint = modbusManager.magnetPSUSetpoint
                                if (Math.abs(value - currentSetpoint) > 0.001) {
                                    modbusManager.setMagnetPSUSetpointValue(value)
                                }
                            }
                        }
                    }
                    
                    Keys.onReturnPressed: {
                        editingFinished()
                    }
                    Keys.onEnterPressed: {
                        editingFinished()
                    }
                }
                
                // Контейнер для стрелок
                Column {
                    width: 16
                    height: parent.height
                    spacing: 0
                    
                    Button {
                        id: magnetPSUTempUpButton
                        width: parent.width
                        height: parent.height / 2
                        text: "+"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: magnetPSUTempUpButton.text
                            color: "#ffffff"
                            font: magnetPSUTempUpButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            var textValue = textInput5.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.magnetPSUSetpoint
                            }
                            
                            // Вычисляем новое значение (увеличиваем на 0.01)
                            var newValue = currentValue + 0.01
                            textInput5.text = newValue.toFixed(2)
                            modbusManager.setMagnetPSUSetpointValue(newValue)
                        }
                    }
                    
                    Button {
                        id: magnetPSUTempDownButton
                        width: parent.width
                        height: parent.height / 2
                        text: "-"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: magnetPSUTempDownButton.text
                            color: "#ffffff"
                            font: magnetPSUTempDownButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            var textValue = textInput5.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.magnetPSUSetpoint
                            }
                            
                            // Вычисляем новое значение (уменьшаем на 0.001)
                            var newValue = currentValue - 0.001
                            if (newValue < 0) newValue = 0  // Не позволяем отрицательные значения
                            textInput5.text = newValue.toFixed(3)
                            modbusManager.setMagnetPSUSetpointValue(newValue)
                        }
                    }
                }
            }
            
            // Кнопка "set"
            Button {
                id: magnetPSUSetButton
                width: 30
                height: parent.height - 4
                anchors.right: parent.right
                anchors.rightMargin: 25
                anchors.verticalCenter: parent.verticalCenter
                text: "set"
                font.pixelSize: 10
                
                background: Rectangle {
                    color: magnetPSUSetButton.pressed ? "#555555" : "transparent"
                    radius: 2
                }
                
                contentItem: Text {
                    text: magnetPSUSetButton.text
                    color: "#ffffff"
                    font: magnetPSUSetButton.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                
                onClicked: {
                    if (modbusManager && modbusManager.isConnected) {
                        var value = parseFloat(textInput5.text)
                        if (!isNaN(value) && value >= 0) {
                            modbusManager.setMagnetPSUSetpointValue(value)
                            modbusManager.setMagnetPSUTemperature(value)
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle5
        x: 404
        y: 468
        width: 150
        height: 75
        color: "#467a28"
        radius: 12

        Text {
            id: text34
            x: 41
            y: 8
            color: "#ffffff"
            text: qsTr("Laser PSU")
            font.pixelSize: 15
        }

        Label {
            id: label6
            x: 51
            y: 29
            color: "#ffffff"
            text: modbusManager ? (modbusManager.laserPSUCurrent.toFixed(2) + "A") : qsTr("--")
            font.pointSize: 15
            
            Connections {
                target: modbusManager
                function onLaserPSUCurrentChanged(current) {
                    label6.text = current.toFixed(2) + "A"
                }
            }
        }

        // Поле ввода с стрелками (как у Magnet PSU)
        Rectangle {
            x: 45
            y: 49
            width: 100
            height: 25
            color: "transparent"
            border.width: 0
            radius: 3
            
            // Отдельный Rectangle для белого края
            Rectangle {
                x: 2
                y: 0
                width: parent.width - 28
                height: parent.height
                color: "transparent"
                border.color: "transparent"
                border.width: 0
                radius: 3
            }
            
            Row {
                anchors.fill: parent
                anchors.margins: 2
                anchors.rightMargin: 17
                spacing: -3
                
                // Поле ввода для значения
                TextInput {
                    id: textInput6
                    width: parent.width - 48
                    height: parent.height
                    color: "#ffffff"
                    text: {
                        if (modbusManager && modbusManager.laserPSUSetpoint !== undefined) {
                            return modbusManager.laserPSUSetpoint.toFixed(2)
                        } else {
                            return "0.00"
                        }
                    }
                    font.pixelSize: 15
                    selectByMouse: true
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 5
                    inputMethodHints: Qt.ImhDigitsOnly
                    
                    validator: IntValidator {
                        bottom: 0
                        top: 100
                    }
                    
                    Connections {
                        target: modbusManager
                        function onLaserPSUSetpointChanged(setpoint) {
                            if (!textInput6.activeFocus) {
                                var currentText = parseFloat(textInput6.text)
                                if (isNaN(currentText) || Math.abs(currentText - setpoint) > 0.01) {
                                    textInput6.text = setpoint.toFixed(2)
                                }
                            }
                        }
                    }
                    
                    onEditingFinished: {
                        if (modbusManager) {
                            var textValue = text.trim()
                            var value = parseFloat(textValue)
                            if (!isNaN(value) && value >= 0) {
                                modbusManager.setLaserPSUSetpointValue(value)
                                if (modbusManager.isConnected) {
                                    modbusManager.setLaserPSUTemperature(value)
                                }
                            } else {
                                text = modbusManager ? modbusManager.laserPSUSetpoint.toFixed(2) : "0.00"
                            }
                        }
                    }
                    
                    onTextChanged: {
                        var cleaned = text.replace(/[^\d.-]/g, '')
                        if (cleaned !== text) {
                            var cursorPos = cursorPosition
                            text = cleaned
                            cursorPosition = Math.min(cursorPos, text.length)
                        }
                        
                        if (modbusManager && text.trim() !== "") {
                            var value = parseFloat(text)
                            if (!isNaN(value) && value >= 0) {
                                var currentSetpoint = modbusManager.laserPSUSetpoint
                                if (Math.abs(value - currentSetpoint) > 0.01) {
                                    modbusManager.setLaserPSUSetpointValue(value)
                                }
                            }
                        }
                    }
                    
                    Keys.onReturnPressed: {
                        editingFinished()
                    }
                    Keys.onEnterPressed: {
                        editingFinished()
                    }
                }
                
                // Контейнер для стрелок
                Column {
                    width: 16
                    height: parent.height
                    spacing: 0
                    
                    Button {
                        id: laserPSUTempUpButton
                        width: parent.width
                        height: parent.height / 2
                        text: "+"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: laserPSUTempUpButton.text
                            color: "#ffffff"
                            font: laserPSUTempUpButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            var textValue = textInput6.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.laserPSUSetpoint
                            }
                            
                            // Вычисляем новое значение (увеличиваем на 0.01)
                            var newValue = currentValue + 0.01
                            textInput6.text = newValue.toFixed(2)
                            modbusManager.setLaserPSUSetpointValue(newValue)
                        }
                    }
                    
                    Button {
                        id: laserPSUTempDownButton
                        width: parent.width
                        height: parent.height / 2
                        text: "-"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: laserPSUTempDownButton.text
                            color: "#ffffff"
                            font: laserPSUTempDownButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            var textValue = textInput6.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.laserPSUSetpoint
                            }
                            
                            // Вычисляем новое значение (уменьшаем на 0.01)
                            var newValue = currentValue - 0.01
                            if (newValue < 0) newValue = 0  // Не позволяем отрицательные значения
                            textInput6.text = newValue.toFixed(2)
                            modbusManager.setLaserPSUSetpointValue(newValue)
                        }
                    }
                }
            }
            
            // Кнопка "set"
            Button {
                id: laserPSUSetButton
                width: 30
                height: parent.height - 4
                anchors.right: parent.right
                anchors.rightMargin: 25
                anchors.verticalCenter: parent.verticalCenter
                text: "set"
                font.pixelSize: 10
                
                background: Rectangle {
                    color: laserPSUSetButton.pressed ? "#555555" : "transparent"
                    radius: 2
                }
                
                contentItem: Text {
                    text: laserPSUSetButton.text
                    color: "#ffffff"
                    font: laserPSUSetButton.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                
                onClicked: {
                    if (modbusManager && modbusManager.isConnected) {
                        var value = parseFloat(textInput6.text)
                        if (!isNaN(value) && value >= 0) {
                            modbusManager.setLaserPSUSetpointValue(value)
                            modbusManager.setLaserPSUTemperature(value)
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle6
        x: 166
        y: 567
        width: 150
        height: 75
        color: "#9f1e0d"
        radius: 12

        Text {
            id: text31
            x: 53
            y: 8
            color: "#ffffff"
            text: qsTr("Xenon")
            font.pixelSize: 15
        }

        Label {
            id: label3
            x: 42
            y: 28
            color: "#ffffff"
            text: modbusManager ? (modbusManager.xenonPressure.toFixed(2) + " Torr") : qsTr("--")
            font.pointSize: 15
            
            Connections {
                target: modbusManager
                function onXenonPressureChanged(pressure) {
                    label3.text = pressure.toFixed(2) + " Torr"
                }
            }
        }

        // Поле ввода с стрелками (как у Water Chiller и SEOP Cell)
        Rectangle {
            x: 39
            y: 47
            width: 100
            height: 25
            color: "transparent"  // Прозрачный фон
            border.width: 0  // Убираем border из основного Rectangle
            radius: 3
            
            // Отдельный Rectangle для белого края (сдвигаем только его)
            Rectangle {
                x: 2  // Сдвинули влево еще на 3 пикселя (было 5, теперь 2)
                y: 0
                width: parent.width - 28  // Увеличили еще на 7 пикселей (было -35, теперь -28)
                height: parent.height
                color: "transparent"
                border.color: "transparent"
                border.width: 0
                radius: 3
            }
            
            Row {
                anchors.fill: parent
                anchors.margins: 2
                anchors.rightMargin: 17  // Освобождаем место справа для кнопки "set" (30px - 15px сдвиг = 15px, + 2px margin)
                spacing: -3  // Отрицательный spacing сдвигает стрелки влево (было -4, теперь -3, т.е. сдвинули вправо на 1px)
                
                // Поле ввода для значения
                TextInput {
                    id: textInput4
                    width: parent.width - 48  // Освобождаем место для стрелок (16px) и кнопки "set" (30px) + отступы
                    height: parent.height
                    color: "#ffffff"
                    text: {
                        if (modbusManager && modbusManager.xenonSetpoint !== undefined) {
                            return (modbusManager.xenonSetpoint / 1000.0).toFixed(3)
                        } else {
                            return "0.000"
                        }
                    }
                    font.pixelSize: 15
                    selectByMouse: true
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 5
                    inputMethodHints: Qt.ImhDigitsOnly  // Только цифры
                    
                    // Валидация ввода - только цифры
                    validator: IntValidator {
                        bottom: 0
                        top: 1000  // Максимальное давление (можно изменить)
                    }
                    
                    // Обновление значения при изменении на устройстве
                    Connections {
                        target: modbusManager
                        function onXenonSetpointChanged(setpoint) {
                            // Обновляем только если поле не в фокусе (чтобы не прерывать ввод)
                            // и только если значение действительно изменилось
                            if (!textInput4.activeFocus) {
                                var currentText = parseFloat(textInput4.text)
                                if (isNaN(currentText) || Math.abs(currentText - setpoint / 1000.0) > 0.001) {
                                    textInput4.text = (setpoint / 1000.0).toFixed(3)
                                }
                            }
                        }
                    }
                    
                    // Обработка завершения редактирования (Enter или потеря фокуса)
                    onEditingFinished: {
                        if (modbusManager) {
                            var textValue = text.trim()
                            var value = parseFloat(textValue)
                            if (!isNaN(value) && value >= 0) {
                                // Умножаем на 1000 для отправки на устройство
                                var deviceValue = value * 1000.0
                                // Обновляем внутреннее значение (чтобы стрелки работали с актуальным значением)
                                modbusManager.setXenonSetpointValue(deviceValue)
                                // Отправляем на устройство только если подключены
                                if (modbusManager.isConnected) {
                                    modbusManager.setXenonPressure(deviceValue)
                                }
                            } else {
                                // Если ввод некорректный, восстанавливаем предыдущее значение
                                text = modbusManager ? (modbusManager.xenonSetpoint / 1000.0).toFixed(3) : "0.000"
                            }
                        }
                    }
                    
                    // Обработка изменения текста для валидации и обновления внутреннего значения
                    onTextChanged: {
                        // Удаляем все нецифровые символы (кроме минуса в начале)
                        var cleaned = text.replace(/[^\d.-]/g, '')
                        if (cleaned !== text) {
                            var cursorPos = cursorPosition
                            text = cleaned
                            cursorPosition = Math.min(cursorPos, text.length)
                        }
                        
                        // Обновляем внутреннее значение setpoint сразу при вводе (без отправки на устройство)
                        // Это нужно для того, чтобы стрелки работали с актуальным значением
                        // НЕ обновляем если текст пустой или только пробелы, чтобы избежать binding loop
                        if (modbusManager && text.trim() !== "") {
                            var value = parseFloat(text)
                            if (!isNaN(value) && value >= 0) {
                                // Умножаем на 1000 для сравнения с внутренним значением
                                var deviceValue = value * 1000.0
                                // Обновляем только если значение действительно изменилось
                                var currentSetpoint = modbusManager.xenonSetpoint
                                if (Math.abs(deviceValue - currentSetpoint) > 1.0) {
                                    modbusManager.setXenonSetpointValue(deviceValue)
                                }
                            }
                        }
                    }
                    
                    // Обработка нажатия Enter
                    Keys.onReturnPressed: {
                        editingFinished()
                    }
                    Keys.onEnterPressed: {
                        editingFinished()
                    }
                }
                
                // Контейнер для стрелок (между полем ввода и кнопкой "set")
                Column {
                    width: 16
                    height: parent.height
                    spacing: 0
                        
                    // Кнопка вверх (увеличить давление)
                    Button {
                        id: xenonTempUpButton
                        width: parent.width
                        height: parent.height / 2
                        text: "+"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: xenonTempUpButton.text
                            color: "#ffffff"
                            font: xenonTempUpButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            // Берем текущее значение из поля ввода
                            var textValue = textInput4.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            // Если не удалось распарсить или значение некорректное, пробуем взять из внутреннего состояния
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.xenonSetpoint / 1000.0
                            }
                            
                            // Вычисляем новое значение (увеличиваем на 0.001 Torr)
                            var newValue = currentValue + 0.001
                            
                            // Сразу обновляем текст в поле ввода для мгновенной обратной связи
                            textInput4.text = newValue.toFixed(3)
                            
                            // Обновляем только внутреннее значение (без отправки на устройство)
                            // Запись на устройство произойдет только при нажатии на кнопку "set"
                            modbusManager.setXenonSetpointValue(newValue * 1000.0)
                        }
                    }
                    
                    // Кнопка вниз (уменьшить давление)
                    Button {
                        id: xenonTempDownButton
                        width: parent.width
                        height: parent.height / 2
                        text: "-"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: xenonTempDownButton.text
                            color: "#ffffff"
                            font: xenonTempDownButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            // Берем текущее значение из поля ввода
                            var textValue = textInput4.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            // Если не удалось распарсить или значение некорректное, пробуем взять из внутреннего состояния
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.xenonSetpoint / 1000.0
                            }
                            
                            // Вычисляем новое значение (уменьшаем на 0.001 Torr)
                            var newValue = currentValue - 0.001
                            if (newValue < 0) newValue = 0  // Не позволяем отрицательные значения
                            
                            // Сразу обновляем текст в поле ввода для мгновенной обратной связи
                            textInput4.text = newValue.toFixed(3)
                            
                            // Обновляем только внутреннее значение (без отправки на устройство)
                            // Запись на устройство произойдет только при нажатии на кнопку "set"
                            modbusManager.setXenonSetpointValue(newValue * 1000.0)
                        }
                    }
                }
            }
            
            // Кнопка "set" на всю высоту справа (позиционируется абсолютно относительно Rectangle)
            Button {
                id: xenonSetButton
                width: 30
                height: parent.height - 4  // Учитываем margins родителя
                anchors.right: parent.right
                anchors.rightMargin: 25  // Сдвигаем кнопку влево на 25 пикселей (было 20, теперь 25)
                anchors.verticalCenter: parent.verticalCenter
                text: "set"
                font.pixelSize: 10
                
                background: Rectangle {
                    color: xenonSetButton.pressed ? "#555555" : "transparent"
                    radius: 2
                }
                
                contentItem: Text {
                    text: xenonSetButton.text
                    color: "#ffffff"
                    font: xenonSetButton.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                
                onClicked: {
                    if (modbusManager && modbusManager.isConnected) {
                        var value = parseFloat(textInput4.text)
                        if (!isNaN(value) && value >= 0) {
                            // Умножаем на 1000 для отправки на устройство
                            var deviceValue = value * 1000.0
                            // Сначала обновляем внутреннее значение
                            modbusManager.setXenonSetpointValue(deviceValue)
                            // Затем отправляем на устройство
                            modbusManager.setXenonPressure(deviceValue)
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle7
        x: 166
        y: 769
        width: 150
        height: 75
        color: "#E5BE01"
        radius: 12

        Text {
            id: text32
            x: 48
            y: 17
            color: "#ffffff"
            text: qsTr("Vacuum")
            font.pixelSize: 15
        }

        Label {
            id: label4
            x: 42
            y: 43
            color: "#ffffff"
            text: modbusManager ? (modbusManager.vacuumPressure.toFixed(2) + " mTorr") : qsTr("--")
            font.pointSize: 15
            
            Connections {
                target: modbusManager
                function onVacuumPressureChanged(pressure) {
                    label4.text = pressure.toFixed(2) + " mTorr"
                }
            }
        }
    }

    Rectangle {
        id: rectangle8
        x: 562
        y: 389
        width: 150
        height: 75
        color: "#0c63ac"
        radius: 12

        Text {
            id: text35
            x: 33
            y: 9
            color: "#ffffff"
            text: qsTr("Water Chiller")
            font.pixelSize: 15

            Label {
                id: label7
                x: 17
                y: 19
                color: "#ffffff"
                text: modbusManager ? (modbusManager.waterChillerTemperature.toFixed(1) + "°C") : qsTr("--")
                font.pointSize: 15
                
                Connections {
                    target: modbusManager
                    function onWaterChillerTemperatureChanged(temperature) {
                        label7.text = temperature.toFixed(1) + "°C"
                    }
                }
            }
        }

        // Поле ввода с стрелками (как на изображении)
        Rectangle {
            x: 43
            y: 47
            width: 100
            height: 25
            color: "transparent"  // Прозрачный фон
            border.width: 0  // Убираем border из основного Rectangle
            radius: 3
            
            // Отдельный Rectangle для белого края (сдвигаем только его)
            Rectangle {
                x: 2  // Сдвинули влево еще на 3 пикселя (было 5, теперь 2)
                y: 0
                width: parent.width - 28  // Увеличили еще на 7 пикселей (было -35, теперь -28)
                height: parent.height
                color: "transparent"
                border.color: "transparent"
                border.width: 0
                radius: 3
            }
            
            Row {
                anchors.fill: parent
                anchors.margins: 2
                anchors.rightMargin: 17  // Освобождаем место справа для кнопки "set" (30px - 15px сдвиг = 15px, + 2px margin)
                spacing: -3  // Отрицательный spacing сдвигает стрелки влево (было -4, теперь -3, т.е. сдвинули вправо на 1px)
                
                // Поле ввода для значения
                TextInput {
                    id: textInput7
                    width: parent.width - 48  // Освобождаем место для стрелок (16px) и кнопки "set" (30px) + отступы
                    height: parent.height
                    color: "#ffffff"
                    text: modbusManager ? modbusManager.waterChillerSetpoint.toFixed(1) : qsTr("--")
                    font.pixelSize: 15
                    selectByMouse: true
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 5
                    inputMethodHints: Qt.ImhDigitsOnly  // Только цифры
                    
                    // Валидация ввода - только цифры
                    validator: IntValidator {
                        bottom: 0
                        top: 100  // Максимальная температура (можно изменить)
                    }
                    
                    // Обновление значения при изменении на устройстве
                    Connections {
                        target: modbusManager
                        function onWaterChillerSetpointChanged(setpoint) {
                            // Обновляем только если поле не в фокусе (чтобы не прерывать ввод)
                            // и только если значение действительно изменилось
                            if (!textInput7.activeFocus) {
                                var currentText = parseFloat(textInput7.text)
                                if (isNaN(currentText) || Math.abs(currentText - setpoint) > 0.01) {
                                    textInput7.text = setpoint.toFixed(1)
                                }
                            }
                        }
                    }
                    
                    // Обработка завершения редактирования (Enter или потеря фокуса)
                    onEditingFinished: {
                        if (modbusManager) {
                            var textValue = text.trim()
                            var value = parseFloat(textValue)
                            if (!isNaN(value) && value >= 0) {
                                // Обновляем внутреннее значение (чтобы стрелки работали с актуальным значением)
                                modbusManager.setWaterChillerSetpointValue(value)
                                // Отправляем на устройство только если подключены
                                if (modbusManager.isConnected) {
                                    modbusManager.setWaterChillerTemperature(value)
                                }
                            } else {
                                // Если ввод некорректный, восстанавливаем предыдущее значение
                                text = modbusManager ? modbusManager.waterChillerSetpoint.toFixed(1) : "0.0"
                            }
                        }
                    }
                    
                    // Обработка изменения текста для валидации и обновления внутреннего значения
                    onTextChanged: {
                        // Удаляем все нецифровые символы (кроме минуса в начале)
                        var cleaned = text.replace(/[^\d.-]/g, '')
                        if (cleaned !== text) {
                            var cursorPos = cursorPosition
                            text = cleaned
                            cursorPosition = Math.min(cursorPos, text.length)
                        }
                        
                        // Обновляем внутреннее значение setpoint сразу при вводе (без отправки на устройство)
                        // Это нужно для того, чтобы стрелки работали с актуальным значением
                        // НЕ обновляем если текст пустой или только пробелы, чтобы избежать binding loop
                        if (modbusManager && text.trim() !== "") {
                            var value = parseFloat(text)
                            if (!isNaN(value) && value >= 0) {
                                // Обновляем только если значение действительно изменилось
                                var currentSetpoint = modbusManager.waterChillerSetpoint
                                if (Math.abs(value - currentSetpoint) > 0.01) {
                                    modbusManager.setWaterChillerSetpointValue(value)
                                }
                            }
                        }
                    }
                    
                    // Обработка нажатия Enter
                    Keys.onReturnPressed: {
                        editingFinished()
                    }
                    Keys.onEnterPressed: {
                        editingFinished()
                    }
                }
                
                // Контейнер для стрелок (между полем ввода и кнопкой "set")
                Column {
                    width: 16
                    height: parent.height
                    spacing: 0
                        
                        // Кнопка вверх (увеличить температуру)
                    Button {
                        id: tempUpButton
                        width: parent.width
                        height: parent.height / 2
                        text: "+"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: tempUpButton.text
                            color: "#ffffff"
                            font: tempUpButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            // Берем текущее значение из поля ввода
                            var textValue = textInput7.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            // Если не удалось распарсить или значение некорректное, пробуем взять из внутреннего состояния
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.waterChillerSetpoint
                            }
                            
                            // Вычисляем новое значение (увеличиваем на 0.1)
                            var newValue = currentValue + 0.1
                            
                            // Сразу обновляем текст в поле ввода для мгновенной обратной связи
                            textInput7.text = newValue.toFixed(1)
                            
                            // Обновляем только внутреннее значение (без отправки на устройство)
                            // Запись на устройство произойдет только при нажатии на кнопку "set"
                            modbusManager.setWaterChillerSetpointValue(newValue)
                        }
                    }
                    
                    // Кнопка вниз (уменьшить температуру)
                    Button {
                        id: tempDownButton
                        width: parent.width
                        height: parent.height / 2
                        text: "-"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: tempDownButton.text
                            color: "#ffffff"
                            font: tempDownButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            // Берем текущее значение из поля ввода
                            var textValue = textInput7.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            // Если не удалось распарсить или значение некорректное, пробуем взять из внутреннего состояния
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.waterChillerSetpoint
                            }
                            
                            // Вычисляем новое значение (уменьшаем на 0.1)
                            var newValue = currentValue - 0.1
                            
                            // Сразу обновляем текст в поле ввода для мгновенной обратной связи
                            textInput7.text = newValue.toFixed(1)
                            
                            // Обновляем только внутреннее значение (без отправки на устройство)
                            // Запись на устройство произойдет только при нажатии на кнопку "set"
                            modbusManager.setWaterChillerSetpointValue(newValue)
                        }
                    }
                }
                
            }
            
            // Кнопка "set" на всю высоту справа (позиционируется абсолютно относительно Rectangle)
            Button {
                id: setButton
                width: 30
                height: parent.height - 4  // Учитываем margins родителя
                anchors.right: parent.right
                anchors.rightMargin: 25  // Сдвигаем кнопку влево на 25 пикселей (было 20, теперь 25)
                anchors.verticalCenter: parent.verticalCenter
                text: "set"
                font.pixelSize: 10
                
                background: Rectangle {
                    color: setButton.pressed ? "#555555" : "transparent"
                    radius: 2
                }
                
                contentItem: Text {
                    text: setButton.text
                    color: "#ffffff"
                    font: setButton.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                
                onClicked: {
                    if (modbusManager && modbusManager.isConnected) {
                        var value = parseFloat(textInput7.text)
                        if (!isNaN(value) && value >= 0) {
                            // Сначала обновляем внутреннее значение
                            modbusManager.setWaterChillerSetpointValue(value)
                            // Затем отправляем на устройство
                            modbusManager.setWaterChillerTemperature(value)
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle9
        x: 724
        y: 389
        width: 150
        height: 75
        color: "#5596a0"
        radius: 12

        Text {
            id: text36
            x: 42
            y: 9
            color: "#ffffff"
            text: qsTr("SEOP Cell")
            font.pixelSize: 15
        }

        Label {
            id: label8
            x: 50
            y: 28
            color: "#ffffff"
            text: modbusManager ? (modbusManager.seopCellTemperature.toFixed(1) + "°C") : qsTr("--")
            font.pointSize: 15
            
            Connections {
                target: modbusManager
                function onSeopCellTemperatureChanged(temperature) {
                    label8.text = temperature.toFixed(1) + "°C"
                }
            }
        }

        // Поле ввода с стрелками (как у Water Chiller)
        Rectangle {
            x: 43
            y: 47
            width: 100
            height: 25
            color: "transparent"  // Прозрачный фон
            border.width: 0  // Убираем border из основного Rectangle
            radius: 3
            
            // Отдельный Rectangle для белого края (сдвигаем только его)
            Rectangle {
                x: 2  // Сдвинули влево еще на 3 пикселя (было 5, теперь 2)
                y: 0
                width: parent.width - 28  // Увеличили еще на 7 пикселей (было -35, теперь -28)
                height: parent.height
                color: "transparent"
                border.color: "transparent"
                border.width: 0
                radius: 3
            }
            
            Row {
                anchors.fill: parent
                anchors.margins: 2
                anchors.rightMargin: 17  // Освобождаем место справа для кнопки "set" (30px - 15px сдвиг = 15px, + 2px margin)
                spacing: -3  // Отрицательный spacing сдвигает стрелки влево (было -4, теперь -3, т.е. сдвинули вправо на 1px)
                
                // Поле ввода для значения
                TextInput {
                    id: textInput8
                    width: parent.width - 48  // Освобождаем место для стрелок (16px) и кнопки "set" (30px) + отступы
                    height: parent.height
                    color: "#ffffff"
                    text: modbusManager ? modbusManager.seopCellSetpoint.toFixed(1) : qsTr("--")
                    font.pixelSize: 15
                    selectByMouse: true
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 5
                    inputMethodHints: Qt.ImhDigitsOnly  // Только цифры
                    
                    // Валидация ввода - только цифры
                    validator: IntValidator {
                        bottom: 0
                        top: 100  // Максимальная температура (можно изменить)
                    }
                    
                    // Обновление значения при изменении на устройстве
                    Connections {
                        target: modbusManager
                        function onSeopCellSetpointChanged(setpoint) {
                            // Обновляем только если поле не в фокусе (чтобы не прерывать ввод)
                            // и только если значение действительно изменилось
                            if (!textInput8.activeFocus) {
                                var currentText = parseFloat(textInput8.text)
                                if (isNaN(currentText) || Math.abs(currentText - setpoint) > 0.01) {
                                    textInput8.text = setpoint.toFixed(1)
                                }
                            }
                        }
                    }
                    
                    // Обработка завершения редактирования (Enter или потеря фокуса)
                    onEditingFinished: {
                        if (modbusManager) {
                            var textValue = text.trim()
                            var value = parseFloat(textValue)
                            if (!isNaN(value) && value >= 0) {
                                // Обновляем внутреннее значение (чтобы стрелки работали с актуальным значением)
                                modbusManager.setSeopCellSetpointValue(value)
                                // Отправляем на устройство только если подключены
                                if (modbusManager.isConnected) {
                                    modbusManager.setSeopCellTemperature(value)
                                }
                            } else {
                                // Если ввод некорректный, восстанавливаем предыдущее значение
                                text = modbusManager ? modbusManager.seopCellSetpoint.toFixed(1) : "0.0"
                            }
                        }
                    }
                    
                    // Обработка изменения текста для валидации и обновления внутреннего значения
                    onTextChanged: {
                        // Удаляем все нецифровые символы (кроме минуса в начале)
                        var cleaned = text.replace(/[^\d.-]/g, '')
                        if (cleaned !== text) {
                            var cursorPos = cursorPosition
                            text = cleaned
                            cursorPosition = Math.min(cursorPos, text.length)
                        }
                        
                        // Обновляем внутреннее значение setpoint сразу при вводе (без отправки на устройство)
                        // Это нужно для того, чтобы стрелки работали с актуальным значением
                        // НЕ обновляем если текст пустой или только пробелы, чтобы избежать binding loop
                        if (modbusManager && text.trim() !== "") {
                            var value = parseFloat(text)
                            if (!isNaN(value) && value >= 0) {
                                // Обновляем только если значение действительно изменилось
                                var currentSetpoint = modbusManager.seopCellSetpoint
                                if (Math.abs(value - currentSetpoint) > 0.01) {
                                    modbusManager.setSeopCellSetpointValue(value)
                                }
                            }
                        }
                    }
                    
                    // Обработка нажатия Enter
                    Keys.onReturnPressed: {
                        editingFinished()
                    }
                    Keys.onEnterPressed: {
                        editingFinished()
                    }
                }
                
                // Контейнер для стрелок (между полем ввода и кнопкой "set")
                Column {
                    width: 16
                    height: parent.height
                    spacing: 0
                        
                    // Кнопка вверх (увеличить температуру)
                    Button {
                        id: seopTempUpButton
                        width: parent.width
                        height: parent.height / 2
                        text: "+"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: seopTempUpButton.text
                            color: "#ffffff"
                            font: seopTempUpButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            // Берем текущее значение из поля ввода
                            var textValue = textInput8.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            // Если не удалось распарсить или значение некорректное, пробуем взять из внутреннего состояния
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.seopCellSetpoint
                            }
                            
                            // Вычисляем новое значение (увеличиваем на 0.1)
                            var newValue = currentValue + 0.1
                            
                            // Сразу обновляем текст в поле ввода для мгновенной обратной связи
                            textInput8.text = newValue.toFixed(1)
                            
                            // Обновляем только внутреннее значение (без отправки на устройство)
                            // Запись на устройство произойдет только при нажатии на кнопку "set"
                            modbusManager.setSeopCellSetpointValue(newValue)
                        }
                    }
                    
                    // Кнопка вниз (уменьшить температуру)
                    Button {
                        id: seopTempDownButton
                        width: parent.width
                        height: parent.height / 2
                        text: "-"
                        font.pixelSize: 14
                        
                        background: Rectangle {
                            color: "transparent"
                        }
                        
                        contentItem: Text {
                            text: seopTempDownButton.text
                            color: "#ffffff"
                            font: seopTempDownButton.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        
                        onClicked: {
                            if (!modbusManager) {
                                return
                            }
                            
                            // Берем текущее значение из поля ввода
                            var textValue = textInput8.text.trim()
                            var currentValue = parseFloat(textValue)
                            
                            // Если не удалось распарсить или значение некорректное, пробуем взять из внутреннего состояния
                            if (isNaN(currentValue) || currentValue < 0 || textValue === "") {
                                currentValue = modbusManager.seopCellSetpoint
                            }
                            
                            // Вычисляем новое значение (уменьшаем на 0.1)
                            var newValue = currentValue - 0.1
                            
                            // Сразу обновляем текст в поле ввода для мгновенной обратной связи
                            textInput8.text = newValue.toFixed(1)
                            
                            // Обновляем только внутреннее значение (без отправки на устройство)
                            // Запись на устройство произойдет только при нажатии на кнопку "set"
                            modbusManager.setSeopCellSetpointValue(newValue)
                        }
                    }
                }
            }
            
            // Кнопка "set" на всю высоту справа (позиционируется абсолютно относительно Rectangle)
            Button {
                id: seopSetButton
                width: 30
                height: parent.height - 4  // Учитываем margins родителя
                anchors.right: parent.right
                anchors.rightMargin: 25  // Сдвигаем кнопку влево на 25 пикселей (было 20, теперь 25)
                anchors.verticalCenter: parent.verticalCenter
                text: "set"
                font.pixelSize: 10
                
                background: Rectangle {
                    color: seopSetButton.pressed ? "#555555" : "transparent"
                    radius: 2
                }
                
                contentItem: Text {
                    text: seopSetButton.text
                    color: "#ffffff"
                    font: seopSetButton.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                
                onClicked: {
                    if (modbusManager && modbusManager.isConnected) {
                        var value = parseFloat(textInput8.text)
                        if (!isNaN(value) && value >= 0) {
                            // Сначала обновляем внутреннее значение
                            modbusManager.setSeopCellSetpointValue(value)
                            // Затем отправляем на устройство
                            modbusManager.setSeopCellTemperature(value)
                        }
                    }
                }
            }
        }
    }

    Button {
        id: button20
        x: 315
        y: 389
        width: 70
        height: 75
        text: checked ? "10" : "X10"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#293555"
            radius: 25
            border.color: button20.checked ? "#fb0000" : "#676767"
            border.width: button20.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button20.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(9, button20.checked)  // Valve X10 (индекс 9)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 9) {
                    if (button20.checked !== state) {
                        button20.checked = state
                    }
                }
            }
        }
    }


    Button {
        id: button21
        x: 886
        y: 389
        width: 70
        height: 75
        text: checked ? "8" : "X8"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#293555"
            radius: 25
            border.color: button21.checked ? "#fb0000" : "#676767"
            border.width: button21.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button21.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(7, button21.checked)  // Valve X8 (индекс 7)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 7) {
                    if (button21.checked !== state) {
                        button21.checked = state
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle35
        x: 345
        y: 246
        width: 10
        height: 143
        color: "#b7b5b5"
        border.width: 0
        rotation: 0
    }

    Rectangle {
        id: rectangle12
        x: 90
        y: 205
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text4
            x: 0
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle13
        x: 90
        y: 567
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text5
            x: 0
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle14
        x: 433
        y: 205
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text6
            x: 1
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle15
        x: 686
        y: 205
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text7
            x: -1
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Button {
        id: button26
        x: 886
        y: 206
        width: 70
        height: 75
        text: checked ? "X9" : "9"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#38691e"
            radius: 25
            border.color: button26.checked ? "#fb0000" : "#676767"
            border.width: button26.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button26.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(8, button26.checked)  // Valve X9 (индекс 8)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 8) {
                    if (button26.checked !== state) {
                        button26.checked = state
                    }
                }
            }
        }
    }


    Rectangle {
        id: rectangle17
        x: 540
        y: 205
        width: 109
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text11
            x: 0
            y: 24
            width: 109
            height: 27
            color: "#ffffff"
            text: qsTr("O2 filter")
            font.pixelSize: 22
            horizontalAlignment: Text.AlignHCenter
        }
    }


    Button {
        id: button22
        x: 1049
        y: 389
        width: 70
        height: 75
        text: checked ? "6" : "X6"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#293555"
            radius: 25
            border.color: button22.checked ? "#fb0000" : "#676767"
            border.width: button22.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button22.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(5, button22.checked)  // Valve X6 (индекс 5)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 5) {
                    if (button22.checked !== state) {
                        button22.checked = state
                    }
                }
            }
        }
    }
    Rectangle {
        id: rectangle19
        x: 1136
        y: 388
        width: 100
        height: 75
        color: "#5596a0"
        radius: 25
        border.width: 0

        TextInput {
            id: textInput1
            x: 0
            y: 28
            width: 100
            height: 20
            color: "#ffffff"
            text: qsTr("RB filter")
            font.pixelSize: 22
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle20
        x: 1253
        y: 388
        width: 100
        height: 75
        color: "#965b5b"
        radius: 25
        border.width: 0

        TextInput {
            id: textInput2
            x: 0
            y: 28
            width: 100
            height: 20
            color: "#ffffff"
            text: qsTr("Collection")
            font.pixelSize: 22
            horizontalAlignment: Text.AlignHCenter
        }

    }

    Button {
        id: button23
        x: 315
        y: 650
        width: 70
        height: 75
        text: checked ? "11" : "X11"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#293555"
            radius: 25
            border.color: button23.checked ? "#fb0000" : "#676767"
            border.width: button23.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button23.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(10, button23.checked)  // Valve X11 (индекс 10)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 10) {
                    if (button23.checked !== state) {
                        button23.checked = state
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle22
        x: 433
        y: 567
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text8
            x: 0
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle23
        x: 540
        y: 567
        width: 109
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text10
            x: 0
            y: 24
            width: 109
            height: 27
            color: "#ffffff"
            text: qsTr("O2 filter")
            font.pixelSize: 22
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle24
        x: 686
        y: 567
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"

        Text {
            id: text9
            x: 0
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Button {
        id: button24
        x: 886
        y: 568
        width: 70
        height: 75
        text: checked ? "12" : "X12"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#293555"
            radius: 25
            border.color: button24.checked ? "#fb0000" : "#676767"
            border.width: button24.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button24.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(11, button24.checked)  // Valve X12 (индекс 11)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 11) {
                    if (button24.checked !== state) {
                        button24.checked = state
                    }
                }
            }
        }
    }

    Button {
        id: button25
        x: 969
        y: 650
        width: 70
        height: 75
        text: checked ? "7" : "X7"

        // Делаем кнопку переключаемой
        checkable: true

        // Стилизация кнопки как круга
        background: Rectangle {
            color: "#293555"
            radius: 25
            border.color: button25.checked ? "#fb0000" : "#676767"
            border.width: button25.checked ? 5 : 1
        }

        // Стилизация текста
        contentItem: Text {
            text: button25.text
            color: "#ffffff"
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        
        onClicked: {
            // Мгновенное обновление UI - не ждем ответа от устройства
            // Проверка подключения выполняется внутри setValve, UI обновляется мгновенно
            if (modbusManager) {
                modbusManager.setValve(6, button25.checked)  // Valve X7 (индекс 6)
            }
        }
        Connections {
            target: modbusManager
            function onValveStateChanged(valveIndex, state) {
                if (valveIndex === 6) {
                    if (button25.checked !== state) {
                        button25.checked = state
                    }
                }
            }
        }
    }

    Rectangle {
        id: rectangle27
        x: 316
        y: 238
        width: 117
        height: 10
        color: "#b7b5b5"
        border.width: 0
    }

    Rectangle {
        id: rectangle28
        x: 503
        y: 238
        width: 37
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle29
        x: 649
        y: 238
        width: 37
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle30
        x: 756
        y: 238
        width: 130
        height: 10
        color: "#b7b5b5"
        border.width: 0
    }

    Rectangle {
        id: rectangle31
        x: 316
        y: 600
        width: 117
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle32
        x: 503
        y: 600
        width: 37
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle33
        x: 649
        y: 600
        width: 37
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle34
        x: 756
        y: 600
        width: 130
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle36
        x: 345
        y: 464
        width: 10
        height: 143
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle37
        x: 345
        y: 507
        width: 10
        height: 143
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle38
        x: 241
        y: 152
        width: 553
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle39
        x: 794
        y: 152
        width: 10
        height: 86
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle40
        x: 236
        y: 152
        width: 10
        height: 53
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle41
        x: 236
        y: 642
        width: 10
        height: 105
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle42
        x: 241
        y: 737
        width: 553
        height: 10
        color: "#b7b5b5"
        border.width: 0
    }

    Rectangle {
        id: rectangle43
        x: 794
        y: 610
        width: 10
        height: 137
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle44
        x: 554
        y: 343
        width: 240
        height: 10
        color: "#467a28"
    }

    Rectangle {
        id: rectangle45
        x: 794
        y: 343
        width: 10
        height: 46
        color: "#467a28"
        rotation: 0
    }

    Rectangle {
        id: rectangle46
        x: 794
        y: 464
        width: 10
        height: 46
        color: "#467a28"
        rotation: 0
    }

    Rectangle {
        id: rectangle47
        x: 554
        y: 500
        width: 240
        height: 10
        color: "#467a28"
    }

    Rectangle {
        id: rectangle48
        x: 712
        y: 422
        width: 12
        height: 10
        color: "#0c63ac"
        border.width: 0
    }

    Rectangle {
        id: rectangle49
        x: 874
        y: 422
        width: 12
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle50
        x: 1236
        y: 421
        width: 17
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle51
        x: 1119
        y: 421
        width: 17
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle52
        x: 999
        y: 239
        width: 10
        height: 411
        color: "#b7b5b5"
        rotation: 0
    }

    Rectangle {
        id: rectangle54
        x: 956
        y: 421
        width: 43
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle55
        x: 956
        y: 600
        width: 43
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle56
        x: 1009
        y: 421
        width: 40
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle57
        x: 956
        y: 239
        width: 43
        height: 10
        color: "#b7b5b5"
    }

    Rectangle {
        id: rectangle53
        x: 316
        y: 802
        width: 683
        height: 10
        color: "#E5BE01"
    }

    Rectangle {
        id: rectangle58
        x: 999
        y: 725
        width: 10
        height: 87
        color: "#E5BE01"
        rotation: 0
    }

    Rectangle {
        id: rectangle59
        x: 345
        y: 725
        width: 10
        height: 87
        color: "#E5BE01"
        rotation: 0
    }


    Rectangle {
        id: rectangle60
        x: 25
        y: 903
        width: 1376
        height: 157
        color: "#ffffff"
        radius: 12
        border.width: 5

        Text {
            id: text13
            x: 21
            y: 101
            text: qsTr("Normally Closed (opened)")
            font.pixelSize: 22
        }

        Text {
            id: text14
            x: 350
            y: 101
            text: qsTr("Normally Closed (closed)")
            font.pixelSize: 22
        }

        Text {
            id: text15
            x: 638
            y: 101
            text: qsTr("Normally Open (closed)")
            font.pixelSize: 22
        }

        Text {
            id: text16
            x: 911
            y: 101
            text: qsTr("Normally Open (opened)")
            font.pixelSize: 22
        }

        Text {
            id: text17
            x: 1201
            y: 101
            text: qsTr("Manual Valve")
            font.pixelSize: 22
        }
    }

    Rectangle {
        id: rectangle61
        x: 131
        y: 925
        width: 70
        height: 75
        color: "#293555"
        radius: 25
        border.color: "#fb0000"
        border.width: 5

        Text {
            id: text21
            x: 0
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("10")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle62
        x: 461
        y: 925
        width: 70
        height: 75
        color: "#293555"
        radius: 25
        border.color: "#676767"

        Text {
            id: text20
            x: 1
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("X10")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle63
        x: 741
        y: 925
        width: 70
        height: 75
        color: "#467a28"
        radius: 25
        border.color: "#ff0000"
        border.width: 5

        Text {
            id: text19
            x: -1
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("X9")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle64
        x: 1015
        y: 925
        width: 70
        height: 75
        color: "#467a28"
        radius: 25
        border.color: "#676767"

        Text {
            id: text18
            x: 2
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("9")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle65
        x: 1253
        y: 925
        width: 70
        height: 75
        color: "#676767"
        radius: 25
        border.color: "#676767"
        Text {
            id: text12
            x: 0
            y: 17
            width: 70
            height: 58
            color: "#ffffff"
            text: qsTr("M")
            font.pixelSize: 30
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Rectangle {
        id: rectangle66
        anchors.left: parent.left
        anchors.leftMargin: 25
        anchors.top: parent.top
        anchors.topMargin: 28
        width: 160
        height: 59
        color: "#545454"

        Text {
            id: text29
            anchors.centerIn: parent
            color: "#fafafa"
            text: qsTr("Research")
            font.pixelSize: 22
        }
    }



}
