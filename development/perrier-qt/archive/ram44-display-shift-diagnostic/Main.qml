import QtQuick

Item {
    id: root
    width: 1280
    height: 800
    property real rawX: 640
    property real rawY: 400
    property real mappedX: 640
    property real alternativeX: 639
    property int centerX: 640
    property int displayShiftX: 0
    property string touchTransform: "direct offset 0 px"
    property bool touched: false
    property int reports: 0
    property int secondsLeft: 50

    // The panel scanout wraps horizontally. Render two adjacent copies so a
    // measured shift can rotate the complete scene without a blank seam.
    Component {
      id: visualContent
      Item {
        width: root.width
        height: root.height
    Rectangle { anchors.fill: parent; color: "#132031" }
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
        x: root.centerX - 20; y: 380
        width: 40; height: 40; radius: 20
        color: "transparent"; border.color: "#ffe34d"; border.width: 3
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.bottom
            color: "#ffe34d"; font.pixelSize: 19
            text: "CENTER " + root.centerX
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
            text: "Red: " + root.touchTransform + "   Cyan: other   reports " + root.reports
                  + "   raw " + Math.round(root.rawX) + "," + Math.round(root.rawY)
                  + (root.secondsLeft < 0 ? "   live" : "   " + root.secondsLeft + " s")
        }
    }
    Rectangle {
        visible: root.touched
        x: root.mappedX - 22; y: root.rawY - 22
        width: 44; height: 44; radius: 22
        color: "#ef4242"; border.color: "white"; border.width: 3
    }
    Rectangle {
        visible: root.touched
        x: root.alternativeX - 22; y: root.rawY - 22
        width: 44; height: 44; radius: 22
        color: "#35d3de"; border.color: "white"; border.width: 3
    }
      }
    }
    Loader {
        x: root.displayShiftX
        sourceComponent: visualContent
    }
    Loader {
        active: root.displayShiftX < 0
        x: root.displayShiftX + root.width
        sourceComponent: visualContent
    }
    Loader {
        active: root.displayShiftX > 0
        x: root.displayShiftX - root.width
        sourceComponent: visualContent
    }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: if (root.secondsLeft > 0) root.secondsLeft--
    }
}
