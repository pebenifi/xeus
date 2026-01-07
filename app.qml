import QtQuick
import QtQuick.Controls


Window {
    id: mainWindow
    width: 1920
    height: 1080
    minimumWidth: 1920
    minimumHeight: 1080
    maximumWidth: 1920
    maximumHeight: 1080
    visible: true
    title: "Xeus"
    flags: Qt.Window

    // Функция для смены экрана - пауза опросов первой страницы, затем мгновенное переключение через z-order
    function changeScreen(screenName) {
        console.log("⚡ changeScreen вызван:", screenName, "время:", Date.now())
        
        if (screenName === "Screen01") {
            // Возвращаемся на первый экран - возобновляем все опросы первой страницы
            if (typeof modbusManager !== 'undefined' && modbusManager) {
                modbusManager.resumePolling()
            }
            screen01Item.z = 1
            clinicalModeLoader.z = 0
            console.log("✅ Screen01 показан, время:", Date.now())
        } else if (screenName === "Clinicalmode") {
            // Переходим на второй экран - останавливаем опросы первой страницы (графики продолжают работать через QML таймеры)
            if (typeof modbusManager !== 'undefined' && modbusManager) {
                modbusManager.pausePolling()
            }
            if (clinicalModeLoader.status === Loader.Ready && clinicalModeLoader.item) {
                screen01Item.z = 0
                clinicalModeLoader.z = 1
                clinicalModeLoader.item.visible = true
                console.log("✅ Clinicalmode показан, время:", Date.now())
            } else {
                console.log("⏳ Clinicalmode еще не готов, статус:", clinicalModeLoader.status)
            }
        }
    }

    Item {
        id: screen01Item
        anchors.fill: parent
        visible: true
        enabled: true
        z: 1
        Screen01 { anchors.fill: parent }
    }

    Loader {
        id: clinicalModeLoader
        anchors.fill: parent
        source: "Clinicalmode.qml"
        active: true
        asynchronous: true
        visible: true
        enabled: true
        z: 0
        onLoaded: { if (item) item.visible = true }
    }
}
