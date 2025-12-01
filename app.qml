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

    // Свойство для управления текущим экраном
    property string currentScreen: "Screen01"

    // Функция для смены экрана
    function changeScreen(screenName) {
        currentScreen = screenName;
    }

    // Загрузчик для отображения текущего экрана
    Loader {
        id: screenLoader
        anchors.fill: parent
        source: currentScreen + ".qml"
    }
}