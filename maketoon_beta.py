
import sys
import json
import base64
from pathlib import Path
from collections import deque

from PySide6.QtCore import Qt, QPoint, QRect, QBuffer, QIODevice, QTimer, Signal
from PySide6.QtGui import (
    QColor, QImage, QPainter, QPen, QPixmap, QIcon, QKeySequence,
    QShortcut, QPolygon, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QSpinBox, QColorDialog,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QInputDialog, QSplitter,
    QScrollArea, QToolButton, QDialog, QDialogButtonBox, QLineEdit,
    QDoubleSpinBox, QFormLayout, QStackedWidget, QComboBox
)

APP = "MakeToons"
VERSION = "0.4 Beta"
DEFAULT_W, DEFAULT_H = 960, 540
DEFAULT_FRAMES = 24
PROJECT_DIR = Path.home() / "MakeToonsProjects"
SETTINGS_FILE = Path.home() / ".maketoon_settings.json"


def blank(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def encode(img):
    b = QBuffer()
    b.open(QIODevice.WriteOnly)
    img.save(b, "PNG")
    return base64.b64encode(bytes(b.data())).decode()


def decode(s):
    img = QImage()
    img.loadFromData(base64.b64decode(s))
    return img


class Layer:
    def __init__(self, name, w, h, frames=DEFAULT_FRAMES, background=False):
        self.name = name
        self.visible = True
        self.locked = background
        self.background = background
        self.frames = [blank(w, h) for _ in range(frames)]


class ColorDialog(QDialog):
    def __init__(self, app, initial):
        super().__init__(app)
        self.setWindowTitle("MakeToons Color Picker")
        self.resize(440, 440)
        self.result_color = initial
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(90, 90)
        top.addWidget(self.preview)
        title = QLabel("COLOR\nRGB + HSL")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        top.addWidget(title)
        top.addStretch()
        root.addLayout(top)

        form = QFormLayout()
        self.r = QSpinBox(); self.r.setRange(0, 255)
        self.g = QSpinBox(); self.g.setRange(0, 255)
        self.b = QSpinBox(); self.b.setRange(0, 255)
        self.h = QSpinBox(); self.h.setRange(0, 359)
        self.s = QSpinBox(); self.s.setRange(0, 255)
        self.l = QSpinBox(); self.l.setRange(0, 255)
        form.addRow("Red (R)", self.r)
        form.addRow("Green (G)", self.g)
        form.addRow("Blue (B)", self.b)
        form.addRow("Hue (H)", self.h)
        form.addRow("Saturation (S)", self.s)
        form.addRow("Lightness (L)", self.l)
        root.addLayout(form)

        native = QPushButton("Open Advanced Color Picker")
        native.clicked.connect(self.native_picker)
        root.addWidget(native)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for box in (self.r, self.g, self.b):
            box.valueChanged.connect(self.rgb_changed)
        for box in (self.h, self.s, self.l):
            box.valueChanged.connect(self.hsl_changed)

        self.set_rgb(initial.red(), initial.green(), initial.blue())

    def update_preview(self):
        self.preview.setStyleSheet(
            f"background:{self.result_color.name()};"
            "border-radius:45px;border:2px solid #68758c;"
        )

    def set_rgb(self, r, g, b):
        for box, value in ((self.r, r), (self.g, g), (self.b, b)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        c = QColor(r, g, b)
        h, s, l, _ = c.getHsl()
        for box, value in ((self.h, max(0, h)), (self.s, s), (self.l, l)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        self.result_color = c
        self.update_preview()

    def rgb_changed(self):
        self.set_rgb(self.r.value(), self.g.value(), self.b.value())

    def hsl_changed(self):
        c = QColor.fromHsl(self.h.value(), self.s.value(), self.l.value())
        self.set_rgb(c.red(), c.green(), c.blue())

    def native_picker(self):
        c = QColorDialog.getColor(self.result_color, self, "Advanced Color Picker")
        if c.isValid():
            self.set_rgb(c.red(), c.green(), c.blue())


class NewProjectDialog(QDialog):
    PRESETS = {
        "YouTube 16:9 — 1920 × 1080": (1920, 1080),
        "TikTok 9:16 — 1080 × 1920": (1080, 1920),
        "Instagram Post 1:1 — 1080 × 1080": (1080, 1080),
        "3:4 — 1080 × 1440": (1080, 1440),
        "HD 16:9 — 1280 × 720": (1280, 720),
        "Custom": None,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New MakeToons Project")
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit("My Animation")
        self.preset = QComboBox()
        self.preset.addItems(self.PRESETS.keys())
        self.width = QSpinBox(); self.width.setRange(64, 8000); self.width.setValue(DEFAULT_W)
        self.height = QSpinBox(); self.height.setRange(64, 8000); self.height.setValue(DEFAULT_H)
        self.frames = QSpinBox(); self.frames.setRange(1, 1000); self.frames.setValue(DEFAULT_FRAMES)
        self.duration = QDoubleSpinBox(); self.duration.setRange(0.01, 10.0)
        self.duration.setDecimals(2); self.duration.setValue(0.10); self.duration.setSuffix(" s")

        form.addRow("Project name:", self.name)
        form.addRow("Canvas preset:", self.preset)
        form.addRow("Width:", self.width)
        form.addRow("Height:", self.height)
        form.addRow("Starting frames:", self.frames)
        form.addRow("Frame duration:", self.duration)
        root.addLayout(form)

        self.preset.currentTextChanged.connect(self.apply_preset)
        self.apply_preset(self.preset.currentText())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def apply_preset(self, text):
        size = self.PRESETS[text]
        custom = size is None
        self.width.setEnabled(custom)
        self.height.setEnabled(custom)
        if size:
            self.width.setValue(size[0])
            self.height.setValue(size[1])

    def values(self):
        return {
            "name": self.name.text().strip() or "My Animation",
            "w": self.width.value(),
            "h": self.height.value(),
            "frames": self.frames.value(),
            "duration": self.duration.value(),
        }


class ExportDialog(QDialog):
    def __init__(self, parent, title="Export PNG"):
        super().__init__(parent)
        self.setWindowTitle(title)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Transparent PNG?"))

        self.toggle = QPushButton("ON — Transparent")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.clicked.connect(self.update_button)
        root.addWidget(self.toggle)

        note = QLabel(
            "ON keeps transparent pixels. OFF puts the exported image over "
            "the current canvas background color."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.update_button()

    def update_button(self):
        if self.toggle.isChecked():
            self.toggle.setText("ON — Transparent")
            self.toggle.setStyleSheet(
                "background:#20a85a;color:white;border-radius:7px;padding:9px;"
            )
        else:
            self.toggle.setText("OFF — Opaque")
            self.toggle.setStyleSheet(
                "background:#c52d35;color:white;border-radius:7px;padding:9px;"
            )

    @property
    def transparent(self):
        return self.toggle.isChecked()


class Canvas(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.zoom = 1.0
        self.tool = "pencil"
        self.size = 8
        self.color = QColor("white")
        self.last = None
        self.drawing = False
        self.panning = False
        self.pan_start = QPoint()
        self.view_offset = QPoint(0, 0)
        self.lasso_points = []
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(400, 250)

    def image_rect(self):
        w = int(self.app.canvas_w * self.zoom)
        h = int(self.app.canvas_h * self.zoom)
        x = (self.width() - w) // 2 + self.view_offset.x()
        y = (self.height() - h) // 2 + self.view_offset.y()
        return QRect(x, y, w, h)

    def image_pos(self, p):
        r = self.image_rect()
        if not r.contains(p):
            return None
        return QPoint(
            max(0, min(self.app.canvas_w - 1, int((p.x() - r.x()) / self.zoom))),
            max(0, min(self.app.canvas_h - 1, int((p.y() - r.y()) / self.zoom))),
        )

    def wheelEvent(self, e):
        old = self.zoom
        new = max(
            0.10,
            min(8.0, old * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15)),
        )
        if new == old:
            return
        cursor = e.position().toPoint()
        before = self.image_pos(cursor)
        self.zoom = new
        if before:
            r = self.image_rect()
            target = QPoint(
                int(r.left() + before.x() * self.zoom),
                int(r.top() + before.y() * self.zoom),
            )
            self.view_offset += cursor - target
        self.app.update_zoom_label()
        self.update()

    def mousePressEvent(self, e):
        mods = QApplication.keyboardModifiers()

        if e.button() == Qt.MiddleButton or (
            e.button() == Qt.LeftButton
            and mods & Qt.KeyboardModifier.SpaceModifier
        ):
            self.panning = True
            self.pan_start = e.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            return

        p = self.image_pos(e.position().toPoint())

        # Left AND right click can draw. Middle click remains the pan button.
        if e.button() not in (Qt.LeftButton, Qt.RightButton) or p is None:
            return

        if self.tool == "picker":
            self.color = self.app.composite().pixelColor(p)
            self.app.color_preview()
            self.app.set_tool("pencil")
            return

        if self.tool == "lasso":
            self.lasso_points = [p]
            self.drawing = True
            return

        if self.tool == "bucket":
            self.app.bucket_fill(p)
            return

        layer = self.app.layer()
        if not layer or layer.locked:
            return

        self.drawing = True
        self.last = p
        self.stroke_to(p)

    def mouseMoveEvent(self, e):
        p2 = e.position().toPoint()

        if self.panning:
            delta = p2 - self.pan_start
            self.view_offset += delta
            self.pan_start = p2
            self.update()
            return

        if not self.drawing:
            return

        p = self.image_pos(p2)
        if p is None:
            return

        if self.tool == "lasso":
            if (
                not self.lasso_points
                or (p - self.lasso_points[-1]).manhattanLength() > 3
            ):
                self.lasso_points.append(p)
                self.update()
            return

        if self.tool not in ("pencil", "eraser"):
            return

        layer = self.app.layer()
        if not layer or layer.locked:
            return

        self.stroke_to(p)
        self.last = p

    def mouseReleaseEvent(self, e):
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            if (
                self.tool == "lasso"
                and self.drawing
                and len(self.lasso_points) >= 3
            ):
                self.app.make_selection(self.lasso_points)

            self.drawing = False
            self.last = None

        if e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self.panning = False
            self.unsetCursor()

    def stroke_to(self, p):
        layer = self.app.layer()
        if not layer:
            return

        img = layer.frames[self.app.frame]
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self.tool == "eraser":
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            pen = QPen(
                Qt.transparent,
                self.size,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        else:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(
                self.color,
                self.size,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )

        painter.setPen(pen)
        if self.last is None:
            painter.drawPoint(p)
        else:
            painter.drawLine(self.last, p)
        painter.end()

        self.app.dirty = True
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#080d15"))
        r = self.image_rect()

        self.app.paint_background(p, r)

        # Onion skin uses user-selected colors.
        if self.app.onion:
            for d in range(self.app.prev_onion, 0, -1):
                i = self.app.frame - d
                if i >= 0:
                    tinted = self.app.tinted_composite(
                        self.app.drawing_composite(i),
                        self.app.onion_prev_color,
                    )
                    p.save()
                    p.setOpacity(max(0.08, 0.30 / d))
                    p.drawImage(r, tinted)
                    p.restore()

            for d in range(1, self.app.next_onion + 1):
                i = self.app.frame + d
                if i < self.app.frames:
                    tinted = self.app.tinted_composite(
                        self.app.drawing_composite(i),
                        self.app.onion_next_color,
                    )
                    p.save()
                    p.setOpacity(max(0.08, 0.30 / d))
                    p.drawImage(r, tinted)
                    p.restore()

        p.drawImage(r, self.app.composite())

        if len(self.lasso_points) >= 2:
            pen = QPen(QColor("#ffd34e"), 2, Qt.DashLine)
            pts = [
                QPoint(
                    r.left() + int(x.x() * self.zoom),
                    r.top() + int(x.y() * self.zoom),
                )
                for x in self.lasso_points
            ]
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygon(pts))

        if self.app.selection_path is not None:
            p.save()
            p.setPen(QPen(QColor("#ffd34e"), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            scaled = QPainterPath()
            path = self.app.selection_path
            if not path.isEmpty():
                points = self.app.selection_points
                if points:
                    scaled.moveTo(
                        r.left() + points[0].x() * self.zoom,
                        r.top() + points[0].y() * self.zoom,
                    )
                    for pt in points[1:]:
                        scaled.lineTo(
                            r.left() + pt.x() * self.zoom,
                            r.top() + pt.y() * self.zoom,
                        )
                    scaled.closeSubpath()
                    p.drawPath(scaled)
            p.restore()

        p.setPen(QPen(QColor("#65738b"), 2))
        p.drawRect(r)
        p.end()


class Timeline(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        head = QHBoxLayout()
        head.addWidget(QLabel("Timeline"))
        self.frame_label = QLabel()
        head.addWidget(self.frame_label)
        head.addStretch()

        for text, fn in [
            ("+ Frame", app.add_frame),
            ("Duplicate", app.duplicate_frame),
            ("Delete", app.delete_frame),
        ]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            head.addWidget(b)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(app.toggle_play)
        head.addWidget(self.play_btn)

        head.addWidget(QLabel("Frame duration:"))
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.01, 10.0)
        self.duration.setDecimals(2)
        self.duration.setSingleStep(0.01)
        self.duration.setValue(0.10)
        self.duration.setSuffix(" s")
        self.duration.valueChanged.connect(app.set_frame_duration)
        head.addWidget(self.duration)

        self.fps_label = QLabel("10 FPS")
        head.addWidget(self.fps_label)
        root.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setSpacing(2)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll)

    def rebuild(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.grid.addWidget(QLabel("Layer"), 0, 0)
        for f in range(self.app.frames):
            q = QLabel(str(f + 1))
            q.setAlignment(Qt.AlignCenter)
            q.setMinimumWidth(36)
            self.grid.addWidget(q, 0, f + 1)

        for row, layer in enumerate(self.app.layers, 1):
            name = QLabel(layer.name)
            name.setMinimumWidth(125)
            self.grid.addWidget(name, row, 0)

            for f in range(self.app.frames):
                b = QToolButton()
                b.setFixedSize(36, 28)
                occupied = layer.background or self.app.has_pixels_fast(layer.frames[f])
                b.setText("●" if occupied else "·")
                active = f == self.app.frame
                b.setStyleSheet(
                    f"QToolButton{{background:"
                    f"{'#713cff' if active else '#152238'};"
                    f"color:{'#fff' if occupied else '#65738b'};"
                    "border:1px solid #31405a;border-radius:3px;}}"
                )
                b.clicked.connect(lambda _, i=f: self.app.set_frame(i))
                self.grid.addWidget(b, row, f + 1)

        self.frame_label.setText(
            f"Frame {self.app.frame + 1} / {self.app.frames}"
        )


class SettingsDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("MakeToons Settings")
        self.resize(580, 600)
        root = QVBoxLayout(self)

        tabs = QStackedWidget()
        root.addWidget(tabs)

        appearance = QWidget()
        a = QFormLayout(appearance)

        self.bg_mode = QComboBox()
        self.bg_mode.addItems([
            "Light Transparent Checker",
            "Dark Transparent Checker",
            "Solid Color",
        ])
        self.bg_mode.setCurrentText(app.bg_mode)
        self.bg_mode.currentTextChanged.connect(self.bg_mode_changed)
        a.addRow("Canvas background:", self.bg_mode)

        self.bg_color = QPushButton("Pick Any Background Color")
        self.bg_color.clicked.connect(self.choose_bg)
        a.addRow("", self.bg_color)

        self.prev_color = QPushButton("Pick Previous-Frame Onion Color")
        self.prev_color.clicked.connect(
            lambda: self.choose_onion("prev")
        )
        a.addRow("Onion skin:", self.prev_color)

        self.next_color = QPushButton("Pick Next-Frame Onion Color")
        self.next_color.clicked.connect(
            lambda: self.choose_onion("next")
        )
        a.addRow("", self.next_color)

        tabs.addWidget(appearance)

        shortcuts = QWidget()
        s = QFormLayout(shortcuts)
        self.edits = {}
        for key, label in [
            ("pencil", "Pencil"),
            ("eraser", "Eraser"),
            ("picker", "Color Picker"),
            ("bucket", "Bucket"),
            ("lasso", "Lasso"),
            ("play", "Play/Pause"),
            ("save", "Save"),
        ]:
            edit = QLineEdit(app.shortcuts.get(key, ""))
            self.edits[key] = edit
            s.addRow(label + ":", edit)
        tabs.addWidget(shortcuts)

        nav = QHBoxLayout()
        for text, index in [("Appearance", 0), ("Shortcuts", 1)]:
            b = QPushButton(text)
            b.clicked.connect(
                lambda _, i=index: tabs.setCurrentIndex(i)
            )
            nav.addWidget(b)
        root.insertLayout(0, nav)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def bg_mode_changed(self, text):
        self.app.bg_mode = text
        self.app.canvas.update()

    def choose_bg(self):
        c = QColorDialog.getColor(
            self.app.bg_color, self, "Canvas Background Color"
        )
        if c.isValid():
            self.app.bg_color = c
            self.app.canvas.update()

    def choose_onion(self, which):
        initial = (
            self.app.onion_prev_color
            if which == "prev"
            else self.app.onion_next_color
        )
        c = QColorDialog.getColor(
            initial, self, f"{which.title()} Onion Color"
        )
        if c.isValid():
            if which == "prev":
                self.app.onion_prev_color = c
            else:
                self.app.onion_next_color = c
            self.app.canvas.update()

    def apply(self):
        for key, edit in self.edits.items():
            if edit.text().strip():
                self.app.shortcuts[key] = edit.text().strip()
        self.app.save_settings()
        self.app.setup_shortcuts()
        self.app.apply_theme()
        self.accept()


class HomePage(QWidget):
    newProject = Signal()
    openProject = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        root = QVBoxLayout(self)
        root.setContentsMargins(50, 35, 50, 35)

        top = QHBoxLayout()
        logo = QLabel()
        path = Path(__file__).with_name("MakeToons_logo_full.png")
        if path.exists():
            logo.setPixmap(
                QPixmap(str(path)).scaled(
                    620, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        else:
            logo.setText("MAKE TOONS")
        top.addWidget(logo)
        top.addStretch()

        settings = QPushButton("⚙ Settings")
        settings.clicked.connect(app.open_settings)
        top.addWidget(settings)
        root.addLayout(top)

        title = QLabel("My Projects")
        title.setStyleSheet(
            "font-size:25px;font-weight:bold;margin-top:18px;"
        )
        root.addWidget(title)

        self.projects = QListWidget()
        self.projects.setViewMode(QListWidget.IconMode)
        self.projects.setResizeMode(QListWidget.Adjust)
        self.projects.setSpacing(16)
        self.projects.itemDoubleClicked.connect(
            lambda item: self.openProject.emit(item.data(Qt.UserRole))
        )
        root.addWidget(self.projects, 1)

        buttons = QHBoxLayout()
        new = QPushButton("+ New Project")
        new.setMinimumHeight(45)
        new.clicked.connect(self.newProject.emit)

        openb = QPushButton("Open Project")
        openb.clicked.connect(self.open_file)

        buttons.addWidget(new)
        buttons.addWidget(openb)
        root.addLayout(buttons)
        self.refresh()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open MakeToons Project", "",
            "MakeToons Project (*.maketoon)"
        )
        if path:
            self.openProject.emit(path)

    def refresh(self):
        self.projects.clear()
        PROJECT_DIR.mkdir(exist_ok=True)
        for p in sorted(
            PROJECT_DIR.glob("*.maketoon"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            item = QListWidgetItem(p.stem)
            item.setData(Qt.UserRole, str(p))
            self.projects.addItem(item)


class MakeToons(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP} {VERSION}")
        self.resize(1500, 920)

        self.canvas_w = DEFAULT_W
        self.canvas_h = DEFAULT_H
        self.frames = DEFAULT_FRAMES
        self.frame = 0
        self.frame_duration = 0.10
        self.playing = False
        self.dirty = False
        self.project_path = None

        self.onion = True
        self.prev_onion = 2
        self.next_onion = 2
        self.onion_prev_color = QColor("#ff5b7f")
        self.onion_next_color = QColor("#4dc9ff")

        self.bg_mode = "Dark Transparent Checker"
        self.bg_color = QColor("#ffffff")
        self.accent = QColor("#713cff")

        self.shortcuts = {
            "pencil": "B",
            "eraser": "E",
            "picker": "I",
            "bucket": "G",
            "lasso": "L",
            "play": "Space",
            "save": "Ctrl+S",
        }

        self.selection_path = None
        self.selection_points = []

        self.load_settings()

        self.layers = [
            Layer("Character", self.canvas_w, self.canvas_h, self.frames),
            Layer("Sketch", self.canvas_w, self.canvas_h, self.frames),
            Layer(
                "Background",
                self.canvas_w,
                self.canvas_h,
                self.frames,
                True,
            ),
        ]

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = HomePage(self)
        self.home.newProject.connect(self.new_project)
        self.home.openProject.connect(self.load_project_path)
        self.stack.addWidget(self.home)

        self.build_editor()

        self.timer = QTimer(self)
        self.timer.timeout.connect(
            lambda: self.set_frame((self.frame + 1) % self.frames)
        )
        self.update_timer_interval()
        self.setup_shortcuts()
        self.apply_theme()

    def build_editor(self):
        root = QWidget()
        main = QVBoxLayout(root)
        main.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        home = QPushButton("← Projects")
        home.clicked.connect(self.go_home)
        header.addWidget(home)

        logo = QLabel("MAKE TOONS")
        logo.setStyleSheet(
            "font-size:20px;font-weight:bold;letter-spacing:2px;"
        )
        header.addWidget(logo)
        header.addStretch()

        settings = QPushButton("⚙ Settings")
        settings.clicked.connect(self.open_settings)
        header.addWidget(settings)

        save = QPushButton("Save")
        save.clicked.connect(self.save_project)
        header.addWidget(save)
        main.addLayout(header)

        outer = QSplitter(Qt.Horizontal)

        # Scrollable tools/layers panel.
        left_content = QWidget()
        ll = QVBoxLayout(left_content)

        tools = QGroupBox("Tools")
        tg = QGridLayout(tools)

        self.pencil = QPushButton("✎ Pencil")
        self.eraser = QPushButton("⌫ Eraser")
        self.picker = QPushButton("● Picker")
        self.bucket = QPushButton("🪣 Bucket")
        self.lasso = QPushButton("Lasso")

        for i, b in enumerate([
            self.pencil, self.eraser, self.picker, self.bucket, self.lasso
        ]):
            tg.addWidget(b, i // 2, i % 2)

        self.pencil.clicked.connect(lambda: self.set_tool("pencil"))
        self.eraser.clicked.connect(lambda: self.set_tool("eraser"))
        self.picker.clicked.connect(lambda: self.set_tool("picker"))
        self.bucket.clicked.connect(lambda: self.set_tool("bucket"))
        self.lasso.clicked.connect(lambda: self.set_tool("lasso"))

        clear_sel = QPushButton("Clear Selected")
        clear_sel.clicked.connect(self.clear_selected)
        clear_out = QPushButton("Clear Outside")
        clear_out.clicked.connect(self.clear_outside)
        tg.addWidget(clear_sel, 3, 0)
        tg.addWidget(clear_out, 3, 1)
        ll.addWidget(tools)

        brush = QGroupBox("Brush / Color")
        bl = QVBoxLayout(brush)

        row = QHBoxLayout()
        row.addWidget(QLabel("Pencil size"))
        self.size = QSpinBox()
        self.size.setRange(1, 200)
        self.size.setValue(8)
        self.size.valueChanged.connect(
            lambda v: setattr(self.canvas, "size", v)
        )
        row.addWidget(self.size)
        bl.addLayout(row)

        self.choose = QPushButton("●  Choose Color")
        self.choose.clicked.connect(self.choose_color)
        bl.addWidget(self.choose)

        self.preview = QLabel()
        self.preview.setFixedHeight(28)
        bl.addWidget(self.preview)
        ll.addWidget(brush)

        onion = QGroupBox("Onion Skin")
        od = QGridLayout(onion)

        self.on = QCheckBox("Enable")
        self.on.setChecked(True)
        self.on.toggled.connect(self.set_onion)
        od.addWidget(self.on, 0, 0, 1, 2)

        od.addWidget(QLabel("Previous frames"), 1, 0)
        self.prev = QSpinBox()
        self.prev.setRange(0, 8)
        self.prev.setValue(2)
        self.prev.valueChanged.connect(self.onion_settings)
        od.addWidget(self.prev, 1, 1)

        od.addWidget(QLabel("Next frames"), 2, 0)
        self.next = QSpinBox()
        self.next.setRange(0, 8)
        self.next.setValue(2)
        self.next.valueChanged.connect(self.onion_settings)
        od.addWidget(self.next, 2, 1)
        ll.addWidget(onion)

        layers_box = QGroupBox("Layers")
        lb = QVBoxLayout(layers_box)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(
            lambda _: self.update_layer_info()
        )
        lb.addWidget(self.list)

        grid = QGridLayout()
        for i, (text, fn) in enumerate([
            ("+ New", self.add_layer),
            ("Delete", self.delete_layer),
            ("Rename", self.rename_layer),
            ("↑ Up", lambda: self.move_layer(-1)),
            ("↓ Down", lambda: self.move_layer(1)),
        ]):
            b = QPushButton(text)
            b.clicked.connect(fn)
            grid.addWidget(b, i // 2, i % 2)
        lb.addLayout(grid)
        ll.addWidget(layers_box)
        ll.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_content)
        outer.addWidget(left_scroll)

        center = QSplitter(Qt.Vertical)

        canvas_panel = QWidget()
        cp = QVBoxLayout(canvas_panel)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Canvas"))
        bar.addStretch()

        minus = QPushButton("−")
        plus = QPushButton("+")
        fit = QPushButton("Fit")
        self.zoom_label = QLabel("100%")

        minus.clicked.connect(
            lambda: self.set_zoom(self.canvas.zoom / 1.15)
        )
        plus.clicked.connect(
            lambda: self.set_zoom(self.canvas.zoom * 1.15)
        )
        fit.clicked.connect(self.fit_canvas)

        for b in [minus, self.zoom_label, plus, fit]:
            bar.addWidget(b)
        cp.addLayout(bar)

        self.canvas = Canvas(self)
        cp.addWidget(self.canvas, 1)
        center.addWidget(canvas_panel)

        self.timeline = Timeline(self)
        center.addWidget(self.timeline)
        center.setSizes([620, 260])
        outer.addWidget(center)

        right = QWidget()
        rl = QVBoxLayout(right)

        props = QGroupBox("Layer")
        pr = QVBoxLayout(props)
        self.layer_name = QLabel()
        pr.addWidget(self.layer_name)

        self.visible = QCheckBox("Visible")
        self.lock = QCheckBox("Locked")
        self.visible.toggled.connect(self.toggle_visible)
        self.lock.toggled.connect(self.toggle_lock)
        pr.addWidget(self.visible)
        pr.addWidget(self.lock)

        rn = QPushButton("Rename")
        rn.clicked.connect(self.rename_layer)
        pr.addWidget(rn)
        rl.addWidget(props)

        frame = QGroupBox("Frame / Export")
        fr = QVBoxLayout(frame)

        for text, fn in [
            ("◀ Previous", lambda: self.set_frame(self.frame - 1)),
            ("Next ▶", lambda: self.set_frame(self.frame + 1)),
            ("Clear Current Frame", self.clear_frame),
            ("Save Frame as PNG", self.save_frame_png),
            ("Save Selected Layer as PNG", self.save_layer_png),
        ]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            fr.addWidget(b)
        rl.addWidget(frame)

        sel = QGroupBox("Lasso Selection")
        sl = QVBoxLayout(sel)
        self.selection_label = QLabel("No selection")
        sl.addWidget(self.selection_label)

        clear = QPushButton("Clear Selection")
        clear.clicked.connect(self.clear_selection)
        sl.addWidget(clear)
        rl.addWidget(sel)

        helpb = QGroupBox("Controls")
        hb = QVBoxLayout(helpb)
        t = QLabel(
            "Draw: Left or Right mouse\n"
            "Pan: Middle mouse or Space + mouse\n"
            "Zoom: Wheel / + / −\n"
            "Lasso: draw around an area\n"
            "Bucket: fills only the active layer and respects outlines above it\n"
            "Settings: background, onion colors and shortcuts"
        )
        t.setWordWrap(True)
        hb.addWidget(t)
        rl.addWidget(helpb)
        rl.addStretch()

        outer.addWidget(right)
        outer.setSizes([310, 880, 290])
        main.addWidget(outer, 1)

        self.editor = root
        self.stack.addWidget(root)

        self.refresh_layers()
        self.color_preview()
        self.set_tool("pencil")

    def layer(self):
        i = self.list.currentRow()
        return self.layers[i] if 0 <= i < len(self.layers) else None

    def refresh_layers(self):
        row = max(0, self.list.currentRow()) if hasattr(self, "list") else 0
        self.list.blockSignals(True)
        self.list.clear()

        for x in self.layers:
            self.list.addItem(
                ("👁 " if x.visible else "○ ")
                + ("🔒 " if x.locked else "")
                + x.name
            )

        self.list.blockSignals(False)

        if self.layers:
            self.list.setCurrentRow(min(row, len(self.layers) - 1))

        self.update_layer_info()
        self.timeline.rebuild()
        self.canvas.update()

    def update_layer_info(self):
        if not hasattr(self, "layer_name"):
            return
        x = self.layer()
        if not x:
            return
        self.layer_name.setText(x.name)
        self.visible.blockSignals(True)
        self.lock.blockSignals(True)
        self.visible.setChecked(x.visible)
        self.lock.setChecked(x.locked)
        self.visible.blockSignals(False)
        self.lock.blockSignals(False)

    def add_layer(self):
        name, ok = QInputDialog.getText(
            self, "New Layer", "Layer name:", text="New Layer"
        )
        if ok and name.strip():
            self.layers.insert(
                0,
                Layer(
                    name.strip(),
                    self.canvas_w,
                    self.canvas_h,
                    self.frames,
                ),
            )
            self.refresh_layers()
            self.list.setCurrentRow(0)
            self.dirty = True

    def delete_layer(self):
        x = self.layer()
        if not x or x.background:
            QMessageBox.information(
                self, APP, "The Background layer cannot be deleted."
            )
            return

        if len(self.layers) <= 1:
            return

        if QMessageBox.question(
            self,
            "Delete Layer",
            f'Delete "{x.name}"?',
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self.layers.pop(self.list.currentRow())
            self.refresh_layers()
            self.dirty = True

    def rename_layer(self):
        x = self.layer()
        if not x:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Layer", "New name:", text=x.name
        )
        if ok and name.strip():
            x.name = name.strip()
            self.refresh_layers()
            self.dirty = True

    def move_layer(self, delta):
        i = self.list.currentRow()
        j = i + delta

        if not (0 <= i < len(self.layers) and 0 <= j < len(self.layers)):
            return

        if self.layers[i].background or self.layers[j].background:
            return

        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        self.refresh_layers()
        self.list.setCurrentRow(j)
        self.dirty = True

    def toggle_visible(self, value):
        x = self.layer()
        if x:
            x.visible = value
            self.canvas.update()

    def toggle_lock(self, value):
        x = self.layer()
        if x:
            x.locked = value
            self.refresh_layers()

    def set_tool(self, tool):
        self.canvas.tool = tool
        self.statusBar().showMessage(
            "Tool: " + tool.title(), 2500
        )

    def choose_color(self):
        d = ColorDialog(self, self.canvas.color)
        if d.exec() == QDialog.Accepted:
            self.canvas.color = d.result_color
            self.color_preview()

    def color_preview(self):
        if hasattr(self, "preview"):
            self.preview.setStyleSheet(
                f"background:{self.canvas.color.name()};"
                "border-radius:14px;border:1px solid #6b7890;"
            )

    def set_onion(self, value):
        self.onion = value
        self.canvas.update()

    def onion_settings(self):
        self.prev_onion = self.prev.value()
        self.next_onion = self.next.value()
        self.canvas.update()

    def set_frame(self, index):
        self.frame = max(0, min(index, self.frames - 1))
        self.timeline.rebuild()
        self.canvas.update()

    def has_pixels_fast(self, img):
        step_y = max(16, self.canvas_h // 24)
        step_x = max(16, self.canvas_w // 24)

        for y in range(0, self.canvas_h, step_y):
            for x in range(0, self.canvas_w, step_x):
                if img.pixelColor(x, y).alpha() > 10:
                    return True
        return False

    def add_frame(self):
        at = self.frame + 1

        for layer in self.layers:
            if layer.background:
                layer.frames.insert(at, layer.frames[self.frame].copy())
            else:
                layer.frames.insert(
                    at, blank(self.canvas_w, self.canvas_h)
                )

        self.frames += 1
        self.frame = at
        self.timeline.rebuild()
        self.canvas.update()
        self.dirty = True

    def duplicate_frame(self):
        at = self.frame + 1

        for layer in self.layers:
            layer.frames.insert(
                at, layer.frames[self.frame].copy()
            )

        self.frames += 1
        self.frame = at
        self.timeline.rebuild()
        self.canvas.update()
        self.dirty = True

    def delete_frame(self):
        if self.frames <= 1:
            return

        for layer in self.layers:
            del layer.frames[self.frame]

        self.frames -= 1
        self.frame = min(self.frame, self.frames - 1)
        self.timeline.rebuild()
        self.canvas.update()
        self.dirty = True

    def clear_frame(self):
        x = self.layer()

        if x and not x.locked:
            if x.background:
                x.frames[self.frame].fill(Qt.transparent)
            else:
                x.frames[self.frame].fill(Qt.transparent)

            self.timeline.rebuild()
            self.canvas.update()
            self.dirty = True

    def drawing_composite(self, frame=None):
        f = self.frame if frame is None else frame
        out = blank(self.canvas_w, self.canvas_h)
        p = QPainter(out)

        for x in reversed(self.layers):
            if x.visible and not x.background:
                p.drawImage(0, 0, x.frames[f])

        p.end()
        return out

    def composite(self, frame=None):
        f = self.frame if frame is None else frame
        out = blank(self.canvas_w, self.canvas_h)
        p = QPainter(out)

        for x in reversed(self.layers):
            if x.visible:
                p.drawImage(0, 0, x.frames[f])

        p.end()
        return out

    def tinted_composite(self, img, color):
        out = blank(self.canvas_w, self.canvas_h)
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(out.rect(), color)
        p.end()
        return out

    def paint_background(self, p, r):
        if self.bg_mode == "Solid Color":
            p.fillRect(r, self.bg_color)
            return

        if self.bg_mode == "Light Transparent Checker":
            c1, c2 = QColor("#eeeeee"), QColor("#ffffff")
        else:
            c1, c2 = QColor("#252525"), QColor("#111111")

        cell = max(8, int(18 * min(1.5, self.canvas.zoom)))

        for y in range(r.top(), r.bottom(), cell):
            for x in range(r.left(), r.right(), cell):
                p.fillRect(
                    QRect(x, y, cell, cell),
                    c1 if ((x // cell + y // cell) % 2 == 0) else c2,
                )

    def bucket_fill(self, start):
        layer = self.layer()

        if not layer or layer.locked:
            QMessageBox.information(
                self, APP, "Select an unlocked layer for the Bucket tool."
            )
            return

        w, h = self.canvas_w, self.canvas_h
        img = layer.frames[self.frame]

        # Everything ABOVE the active layer becomes a boundary.
        idx = self.layers.index(layer)
        barrier = QImage(w, h, QImage.Format_Alpha8)
        barrier.fill(0)

        bp = QPainter(barrier)

        for upper in reversed(self.layers[:idx]):
            if upper.visible:
                bp.drawImage(0, 0, upper.frames[self.frame])

        bp.end()

        if barrier.pixelColor(start).value() > 25:
            return

        # The active layer's own opaque pixels are also boundaries.
        def passable(x, y):
            if x < 0 or y < 0 or x >= w or y >= h:
                return False

            if barrier.pixelColor(x, y).value() > 25:
                return False

            return img.pixelColor(x, y).alpha() < 20

        q = deque([(start.x(), start.y())])
        seen = set(q)

        while q:
            x, y = q.popleft()

            for nx, ny in (
                (x + 1, y),
                (x - 1, y),
                (x, y + 1),
                (x, y - 1),
            ):
                if (nx, ny) not in seen and passable(nx, ny):
                    seen.add((nx, ny))
                    q.append((nx, ny))

        if not seen:
            return

        painter = QPainter(img)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.canvas.color)

        # Convert the flood-fill result to horizontal runs.
        rows = {}
        for x, y in seen:
            rows.setdefault(y, []).append(x)

        for y, xs in rows.items():
            xs.sort()
            start_x = previous = xs[0]

            for x in xs[1:]:
                if x != previous + 1:
                    painter.drawRect(
                        start_x, y, previous - start_x + 1, 1
                    )
                    start_x = x
                previous = x

            painter.drawRect(
                start_x, y, previous - start_x + 1, 1
            )

        painter.end()

        self.dirty = True
        self.canvas.update()
        self.timeline.rebuild()

    def make_selection(self, points):
        if len(points) < 3:
            return

        path = QPainterPath()
        path.moveTo(points[0])

        for pt in points[1:]:
            path.lineTo(pt)

        path.closeSubpath()

        self.selection_path = path
        self.selection_points = list(points)
        self.selection_label.setText("Lasso selection active")
        self.canvas.update()

    def clear_selection(self):
        self.selection_path = None
        self.selection_points = []
        self.canvas.lasso_points = []
        self.selection_label.setText("No selection")
        self.canvas.update()

    def clear_selected(self):
        layer = self.layer()

        if (
            not layer
            or layer.locked
            or self.selection_path is None
        ):
            return

        img = layer.frames[self.frame]
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setClipPath(self.selection_path)
        p.fillRect(img.rect(), Qt.transparent)
        p.end()

        self.dirty = True
        self.canvas.update()

    def clear_outside(self):
        layer = self.layer()

        if (
            not layer
            or layer.locked
            or self.selection_path is None
        ):
            return

        img = layer.frames[self.frame]
        kept = blank(self.canvas_w, self.canvas_h)

        kp = QPainter(kept)
        kp.setClipPath(self.selection_path)
        kp.drawImage(0, 0, img)
        kp.end()

        layer.frames[self.frame] = kept
        self.dirty = True
        self.canvas.update()

    def save_frame_png(self):
        d = ExportDialog(self, "Save Frame as PNG")

        if d.exec() != QDialog.Accepted:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Frame PNG",
            f"frame_{self.frame + 1:04d}.png",
            "PNG Image (*.png)",
        )

        if not path:
            return

        img = self.composite()

        if not d.transparent:
            bg = QImage(
                self.canvas_w,
                self.canvas_h,
                QImage.Format_RGB32,
            )
            bg.fill(self.bg_color)

            p = QPainter(bg)
            p.drawImage(0, 0, img)
            p.end()
            img = bg

        img.save(path, "PNG")

    def save_layer_png(self):
        layer = self.layer()

        if not layer:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Selected Layer as Transparent PNG",
            f"{layer.name}_frame_{self.frame + 1:04d}.png",
            "PNG Image (*.png)",
        )

        if path:
            layer.frames[self.frame].save(path, "PNG")

    def set_zoom(self, zoom):
        self.canvas.zoom = max(0.10, min(8.0, zoom))
        self.update_zoom_label()
        self.canvas.update()

    def update_zoom_label(self):
        if hasattr(self, "zoom_label"):
            self.zoom_label.setText(
                f"{int(self.canvas.zoom * 100)}%"
            )

    def fit_canvas(self):
        aw = max(100, self.canvas.width() - 30)
        ah = max(100, self.canvas.height() - 30)
        self.set_zoom(
            min(
                aw / self.canvas_w,
                ah / self.canvas_h,
            )
        )
        self.canvas.view_offset = QPoint(0, 0)

    def set_frame_duration(self, value):
        self.frame_duration = float(value)
        self.timeline.fps_label.setText(
            f"{1 / self.frame_duration:.2f} FPS"
        )
        self.update_timer_interval()

    def update_timer_interval(self):
        if hasattr(self, "timer"):
            self.timer.setInterval(
                max(10, int(self.frame_duration * 1000))
            )

    def toggle_play(self):
        self.playing = not self.playing

        if self.playing:
            self.timer.start()
            self.timeline.play_btn.setText("⏸ Pause")
        else:
            self.timer.stop()
            self.timeline.play_btn.setText("▶ Play")

    def open_settings(self):
        SettingsDialog(self).exec()

    def load_settings(self):
        if not SETTINGS_FILE.exists():
            return

        try:
            d = json.loads(
                SETTINGS_FILE.read_text(encoding="utf-8")
            )

            self.shortcuts.update(d.get("shortcuts", {}))
            self.bg_mode = d.get("bg_mode", self.bg_mode)
            self.bg_color = QColor(
                d.get("bg_color", self.bg_color.name())
            )
            self.onion_prev_color = QColor(
                d.get(
                    "onion_prev_color",
                    self.onion_prev_color.name(),
                )
            )
            self.onion_next_color = QColor(
                d.get(
                    "onion_next_color",
                    self.onion_next_color.name(),
                )
            )
            self.accent = QColor(
                d.get("accent", self.accent.name())
            )
        except Exception:
            pass

    def save_settings(self):
        SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "shortcuts": self.shortcuts,
                    "bg_mode": self.bg_mode,
                    "bg_color": self.bg_color.name(),
                    "onion_prev_color": self.onion_prev_color.name(),
                    "onion_next_color": self.onion_next_color.name(),
                    "accent": self.accent.name(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def apply_theme(self):
        a = self.accent.name()

        self.setStyleSheet(
            f"""
            QWidget {{
                background:#0b1018;
                color:#e8ecf5;
                font-family:Segoe UI;
                font-size:13px;
            }}
            QGroupBox {{
                border:1px solid #28344a;
                border-radius:8px;
                margin-top:10px;
                padding:8px;
                font-weight:bold;
            }}
            QPushButton,QToolButton {{
                background:#15223a;
                border:1px solid #2c3b55;
                border-radius:6px;
                padding:8px;
            }}
            QPushButton:hover,QToolButton:hover {{
                background:#243453;
            }}
            QListWidget {{
                background:#0f1623;
                border:1px solid #28344a;
                border-radius:6px;
            }}
            QListWidget::item {{
                padding:9px;
            }}
            QListWidget::item:selected {{
                background:{a};
            }}
            QSpinBox,QDoubleSpinBox,QLineEdit,QComboBox {{
                background:#121b2b;
                border:1px solid #30405a;
                padding:5px;
            }}
            QScrollArea {{
                border:1px solid #28344a;
            }}
            QSplitter::handle {{
                background:#33415a;
            }}
            """
        )

        self.canvas.update()

    def setup_shortcuts(self):
        for shortcut in getattr(self, "_shortcuts", []):
            shortcut.deleteLater()

        self._shortcuts = []

        actions = {
            "pencil": lambda: self.set_tool("pencil"),
            "eraser": lambda: self.set_tool("eraser"),
            "picker": lambda: self.set_tool("picker"),
            "bucket": lambda: self.set_tool("bucket"),
            "lasso": lambda: self.set_tool("lasso"),
            "play": self.toggle_play,
            "save": self.save_project,
        }

        for key, fn in actions.items():
            seq = self.shortcuts.get(key, "")

            if seq:
                try:
                    shortcut = QShortcut(
                        QKeySequence(seq), self
                    )
                    shortcut.activated.connect(fn)
                    self._shortcuts.append(shortcut)
                except Exception:
                    pass

    def save_project(self):
        PROJECT_DIR.mkdir(exist_ok=True)

        if self.project_path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save MakeToons Project",
                str(PROJECT_DIR / "My Animation.maketoon"),
                "MakeToons Project (*.maketoon)",
            )

            if not path:
                return

            self.project_path = Path(path)

        data = {
            "app": APP,
            "version": VERSION,
            "canvas_w": self.canvas_w,
            "canvas_h": self.canvas_h,
            "frames": self.frames,
            "current": self.frame,
            "frame_duration": self.frame_duration,
            "layers": [],
        }

        for layer in self.layers:
            data["layers"].append(
                {
                    "name": layer.name,
                    "visible": layer.visible,
                    "locked": layer.locked,
                    "background": layer.background,
                    "frames": [
                        encode(image) for image in layer.frames
                    ],
                }
            )

        self.project_path.write_text(
            json.dumps(data),
            encoding="utf-8",
        )

        self.dirty = False
        self.home.refresh()
        self.statusBar().showMessage(
            f"Saved: {self.project_path.name}", 3000
        )

    def load_project_path(self, path):
        if not path:
            return

        try:
            d = json.loads(
                Path(path).read_text(encoding="utf-8")
            )

            self.canvas_w = int(
                d.get("canvas_w", DEFAULT_W)
            )
            self.canvas_h = int(
                d.get("canvas_h", DEFAULT_H)
            )
            self.frames = int(d["frames"])
            self.frame = max(
                0,
                min(
                    int(d.get("current", 0)),
                    self.frames - 1,
                ),
            )
            self.frame_duration = float(
                d.get("frame_duration", 0.10)
            )

            self.layers = []

            for z in d["layers"]:
                layer = Layer(
                    z["name"],
                    self.canvas_w,
                    self.canvas_h,
                    self.frames,
                    bool(z.get("background", False)),
                )
                layer.visible = bool(
                    z.get("visible", True)
                )
                layer.locked = bool(
                    z.get("locked", layer.background)
                )
                layer.frames = [
                    decode(image)
                    for image in z["frames"]
                ]
                self.layers.append(layer)

            self.project_path = Path(path)
            self.dirty = False
            self.selection_path = None
            self.selection_points = []

            self.timeline.duration.blockSignals(True)
            self.timeline.duration.setValue(
                self.frame_duration
            )
            self.timeline.duration.blockSignals(False)

            self.update_timer_interval()
            self.show_editor()

        except Exception as e:
            QMessageBox.critical(
                self,
                APP,
                f"Could not open project:\n{e}",
            )

    def show_editor(self):
        self.stack.setCurrentWidget(self.editor)
        self.refresh_layers()
        self.fit_canvas()

    def go_home(self):
        if (
            self.dirty
            and QMessageBox.question(
                self,
                APP,
                "This project has unsaved changes. Go back anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        self.playing = False
        self.timer.stop()
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def new_project(self):
        d = NewProjectDialog(self)

        if d.exec() != QDialog.Accepted:
            return

        v = d.values()

        self.canvas_w = v["w"]
        self.canvas_h = v["h"]
        self.frames = v["frames"]
        self.frame = 0
        self.frame_duration = v["duration"]

        self.layers = [
            Layer(
                "Character",
                self.canvas_w,
                self.canvas_h,
                self.frames,
            ),
            Layer(
                "Sketch",
                self.canvas_w,
                self.canvas_h,
                self.frames,
            ),
            Layer(
                "Background",
                self.canvas_w,
                self.canvas_h,
                self.frames,
                True,
            ),
        ]

        self.project_path = PROJECT_DIR / (
            v["name"] + ".maketoon"
        )
        self.dirty = True
        self.selection_path = None
        self.selection_points = []

        self.timeline.duration.setValue(
            self.frame_duration
        )
        self.show_editor()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Left:
            self.set_frame(self.frame - 1)
        elif e.key() == Qt.Key_Right:
            self.set_frame(self.frame + 1)
        elif e.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.set_zoom(self.canvas.zoom * 1.15)
        elif e.key() == Qt.Key_Minus:
            self.set_zoom(self.canvas.zoom / 1.15)
        else:
            super().keyPressEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    logo = Path(__file__).with_name("MakeToons_logo_full.png")
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))

    window = MakeToons()
    window.show()
    sys.exit(app.exec())
