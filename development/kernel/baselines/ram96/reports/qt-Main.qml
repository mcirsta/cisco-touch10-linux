import QtQuick

Item {
    id: root
    width: 1280
    height: 800
    property real rawX: 640
    property real rawY: 400
    property real mappedX: 640
    property string touchTransform: "direct offset 0 px"
    property bool touched: false
    property int reports: 0
    property int secondsLeft: 50
    property bool brightnessAvailable: false
    property int brightnessLevel: 4
    property int sliderLeft: 300
    property int sliderRight: 980
    property int sliderTop: 535
    property int sliderBottom: 680
    property bool keypadReady: false
    property int volumeLevel: 50
    property bool muted: false
    property bool muteLedsAvailable: false
    property int repeatEvents: 0
    property int mutePresses: 0
    property int volumeSliderLeft: 300
    property int volumeSliderRight: 980
    property int volumeSliderTop: 275
    property int volumeSliderBottom: 365
    property int muteLeft: 1020
    property int muteRight: 1240
    property int muteTop: 218
    property int muteBottom: 368
    property string cpuTemperature: "unavailable"
    property string boardTemperature: "unavailable"
    property var powerReadings: []
    property bool whiteLedAvailable: false
    property bool whiteLedOn: false
    property string rtcValue: "unavailable"
    property string gpioValue: "unavailable"

    Rectangle { anchors.fill: parent; color: "#132031" }
    Rectangle {
        x: 30; y: 218; width: 220; height: 432; radius: 16
        color: "#1b3041"; border.color: "#a1d6e4"; border.width: 2
        Text { x: 14; y: 20; text: "Power monitors"; color: "white"; font.pixelSize: 23 }
        Text { x: 14; y: 55; text: "Voltage / current"; color: "#d5e7f0"; font.pixelSize: 16 }
        Repeater {
            model: root.powerReadings
            Text {
                required property string modelData
                required property int index
                x: 14; y: 100 + index * 48
                text: modelData; color: "white"; font.pixelSize: 16
            }
        }
    }
    Rectangle {
        x: 1020; y: 578; width: 220; height: 72; radius: 14
        color: root.whiteLedOn ? "#61758a" : "#1b3041"
        border.color: "#a1d6e4"; border.width: 2
        Text {
            anchors.centerIn: parent; color: "white"; font.pixelSize: 19
            text: root.whiteLedAvailable ? "White LED: " + (root.whiteLedOn ? "ON" : "OFF") : "White LED unavailable"
        }
    }
    Repeater {
        model: 4
        Rectangle { x: (index + 1) * 256; width: 2; height: 800; color: "#41566a" }
    }
    Repeater {
        model: 4
        Rectangle { y: (index + 1) * 160; width: 1280; height: 2; color: "#41566a" }
    }
    Repeater {
        model: [
            { x: 90, y: 130, name: "UL" },
            { x: 1190, y: 130, name: "UR" },
            { x: 90, y: 710, name: "LL" },
            { x: 1190, y: 710, name: "LR" }
        ]
        Rectangle {
            id: target
            required property var modelData
            x: modelData.x - 20; y: modelData.y - 20
            width: 40; height: 40; radius: 20
            color: "transparent"; border.color: "#ffffff"; border.width: 3
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.bottom
                color: "white"; font.pixelSize: 19
                text: target.modelData.name
            }
        }
    }
    Rectangle {
        id: centerTarget
        anchors.centerIn: parent
        width: 40; height: 40; radius: 20
        color: "transparent"; border.color: "#ffe34d"; border.width: 3
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.bottom
            color: "#ffe34d"; font.pixelSize: 19
            text: "CENTER"
        }
    }
    Rectangle {
        x: 20; y: 14; width: 1240; height: 105; radius: 12; color: "#d9182535"
        Text {
            x: 24; y: 10; color: "white"; font.pixelSize: 27
            text: "Touch 10 calibration · touch the white targets and drag"
        }
        Text {
            x: 24; y: 53; color: "#e8ecf3"; font.pixelSize: 22
            text: "Red: " + root.touchTransform + "   reports " + root.reports
                  + "   raw " + Math.round(root.rawX) + "," + Math.round(root.rawY)
                  + (root.secondsLeft < 0 ? "   live" : "   " + root.secondsLeft + " s")
        }
    }
    Rectangle {
        x: 270; y: 218; width: 740; height: 150; radius: 16
        color: "#e51b3044"; border.color: "#a7d9ee"; border.width: 2
        Text {
            x: 30; y: 13; color: "white"; font.pixelSize: 26
            text: "Volume " + root.volumeLevel + "% · hold bezel + / −"
        }
        Text {
            x: 30; y: 49; color: "#d4e5ef"; font.pixelSize: 18
            text: (root.keypadReady ? "Keypad ready" : "Keypad unavailable")
                  + " · repeat events " + root.repeatEvents
                  + " · tap or drag this slider"
        }
        Rectangle {
            id: volumeTrack
            x: 30; y: 100; width: 680; height: 18; radius: 9
            color: "#476177"
        }
        Rectangle {
            x: volumeTrack.x; y: volumeTrack.y
            width: volumeTrack.width * root.volumeLevel / 100
            height: volumeTrack.height; radius: 9
            color: root.muted ? "#8195a6" : "#69e3a1"
        }
        Rectangle {
            x: volumeTrack.x + volumeTrack.width * root.volumeLevel / 100 - 15
            y: volumeTrack.y - 6; width: 30; height: 30; radius: 15
            color: "white"; border.color: "#14283b"; border.width: 2
        }
    }
    Rectangle {
        x: 1020; y: 218; width: 220; height: 150; radius: 16
        color: root.muted ? "#b44758" : "#226c68"
        border.color: "#ffffff"; border.width: 2
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 25; color: "white"; font.bold: true; font.pixelSize: 28
            text: root.muted ? "MUTED" : "SOUND ON"
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 72; color: "white"; font.pixelSize: 18
            text: (root.muteLedsAvailable ? "LED ready · " : "") + "presses " + root.mutePresses
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 104; color: "#e3eef2"; font.pixelSize: 16
            text: "bezel mute or tap"
        }
    }
    Rectangle {
        x: 1020; y: 385; width: 220; height: 170; radius: 16
        color: "#e51b3044"; border.color: "#a7d9ee"; border.width: 2
        Text {
            x: 20; y: 12; color: "white"; font.pixelSize: 26
            text: "Temperatures"
        }
        Text {
            x: 20; y: 59; color: "#d4e5ef"; font.pixelSize: 20
            text: "CPU  " + root.cpuTemperature
        }
        Text {
            x: 20; y: 108; color: "#d4e5ef"; font.pixelSize: 20
            text: "Board  " + root.boardTemperature
        }
    }
    Rectangle {
        x: 270; y: 525; width: 740; height: 160; radius: 16
        color: "#e51b3044"; border.color: "#a7d9ee"; border.width: 2
        opacity: root.brightnessAvailable ? 1 : 0.55
        Text {
            x: 30; y: 13; color: "white"; font.pixelSize: 25
            text: root.brightnessAvailable
                  ? "Backlight " + (root.brightnessLevel * 25) + "% · drag to test touch"
                  : "Backlight slider available in ram51"
        }
        Text {
            x: 30; y: 49; color: "#d4e5ef"; font.pixelSize: 18
            text: "25%"
        }
        Text {
            x: 667; y: 49; color: "#d4e5ef"; font.pixelSize: 18
            text: "100%"
        }
        Rectangle {
            id: sliderTrack
            x: 30; y: 105; width: 680; height: 18; radius: 9
            color: "#476177"
        }
        Rectangle {
            x: sliderTrack.x; y: sliderTrack.y
            width: sliderTrack.width * (root.brightnessLevel - 1) / 3
            height: sliderTrack.height; radius: 9; color: "#55d4ef"
        }
        Repeater {
            model: 4
            Rectangle {
                x: sliderTrack.x + index * sliderTrack.width / 3 - 16
                y: sliderTrack.y - 7; width: 32; height: 32; radius: 16
                color: index + 1 === root.brightnessLevel ? "#ffffff" : "#7d9bb1"
                border.color: "#14283b"; border.width: 2
            }
        }
    }
    Rectangle {
        x: 270; y: 704; width: 350; height: 82; radius: 14
        color: "#1b3041"; border.color: "#a7d9ee"; border.width: 2
        Text { x: 20; y: 9; text: "RTC"; color: "white"; font.pixelSize: 20 }
        Text { x: 20; y: 44; text: root.rtcValue; color: "#d4e5ef"; font.pixelSize: 18 }
    }
    Rectangle {
        x: 640; y: 704; width: 370; height: 82; radius: 14
        color: "#1b3041"; border.color: "#a7d9ee"; border.width: 2
        Text { x: 20; y: 9; text: "GPIO expander (as-is)"; color: "white"; font.pixelSize: 20 }
        Text { x: 20; y: 44; text: root.gpioValue; color: "#d4e5ef"; font.pixelSize: 20 }
    }
    Rectangle {
        visible: root.touched
        x: root.mappedX - 22; y: root.rawY - 22
        width: 44; height: 44; radius: 22
        color: "#ef4242"; border.color: "white"; border.width: 3
    }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: if (root.secondsLeft > 0) root.secondsLeft--
    }
}
