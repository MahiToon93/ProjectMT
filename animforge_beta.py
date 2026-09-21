# AnimForge Beta 0.1
# A prototype 2D animation + 3D model editing workspace.
#
# Install:
#   pip install PySide6 pyqtgraph PyOpenGL
#
# Run:
#   python animforge_beta.py
#
# Beta features:
# - Animate / Edit workspace switch
# - Custom UI accent color
# - Custom canvas/background color
# - 2D drawing layer with pencil/eraser
# - Frame timeline with add/delete/duplicate
# - Default articulated 3D mannequin
# - 3D model layer separate from 2D layers
# - Basic 3D transform controls
# - Import OBJ models
# - Save/load project as JSON
#
# Notes:
# - This is a beta foundation, not a finished Blender-style 3D sculpting system.
# - The "sculpt" button is intentionally a placeholder for the future sculpt editor.
# - 3D keyframes are stored as transform snapshots in this prototype.

import sys
import json
import math
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen, QBrush, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QSlider, QSpinBox,
    QColorDialog, QFileDialog, QMessageBox, QTabWidget, QComboBox,
    QDoubleSpinBox, QGroupBox, QSplitter, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QToolBar
)

try:
    import pyqtgraph.opengl as gl
    import pyqtgraph as pg
    HAS_3D = True
except Exception:
    HAS_3D = False


APP_NAME = "AnimForge Beta 0.1"


class DrawingCanvas(QGraphicsView):
    strokeFinished = Signal()

    def __init__(self):
        super().__init__()
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMinimumSize(520, 360)

        self.pen_color = QColor("#ffffff")
        self.pen_width = 6
        self.eraser = False
        self.drawing = False
        self.last_point = QPointF()

        self.set_background("#20242e")

    def set_background(self, color):
        self.scene_obj.setBackgroundBrush(QBrush(QColor(color)))

    def set_pen(self, color=None, width=None, eraser=False):
        if color is not None:
            self.pen_color = QColor(color)
        if width is not None:
            self.pen_width = width
        self.eraser = eraser

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.last_point = self.mapToScene(event.position().toPoint())

    def mouseMoveEvent(self, event):
        if not self.drawing:
            return
        point = self.mapToScene(event.position().toPoint())
        color = QColor("#20242e") if self.eraser else self.pen_color
        pen = QPen(color, self.pen_width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        self.scene_obj.addLine(
            self.last_point.x(), self.last_point.y(),
            point.x(), point.y(), pen
        )
        self.last_point = point

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = False
            self.strokeFinished.emit()

    def clear_canvas(self):
        self.scene_obj.clear()


class MannequinView(QWidget):
    transformChanged = Signal()

    def __init__(self):
        super().__init__()
        self.view = None
        self.parts = []
        self.camera_distance = 18
        self.rot_y = 0
        self.rot_x = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not HAS_3D:
            label = QLabel(
                "3D viewport unavailable.\n\n"
                "Install the beta dependencies:\n"
                "pip install PySide6 pyqtgraph PyOpenGL"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            return

        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=self.camera_distance, elevation=12, azimuth=25)
        self.view.opts["center"] = pg.Vector(0, 2.8, 0)
        layout.addWidget(self.view)

        grid = gl.GLGridItem()
        grid.setSize(16, 16)
        grid.setSpacing(1, 1)
        self.view.addItem(grid)

        self.build_mannequin()

    def sphere(self, pos, size, color=(0.75, 0.78, 0.84, 1.0)):
        md = gl.MeshData.sphere(rows=12, cols=20, radius=size)
        item = gl.GLMeshItem(
            meshdata=md,
            smooth=True,
            color=color,
            shader="shaded",
            drawEdges=False
        )
        item.translate(*pos)
        self.view.addItem(item)
        self.parts.append(item)
        return item

    def cylinder_between(self, a, b, radius=0.28,
                         color=(0.62, 0.67, 0.75, 1.0)):
        ax, ay, az = a
        bx, by, bz = b
        dx, dy, dz = bx - ax, by - ay, bz - az
        length = math.sqrt(dx*dx + dy*dy + dz*dz)

        # A cylinder aligned with local Z.
        md = gl.MeshData.cylinder(rows=10, cols=16, radius=[radius, radius],
                                  length=length)
        item = gl.GLMeshItem(
            meshdata=md,
            smooth=True,
            color=color,
            shader="shaded",
            drawEdges=False
        )

        # pyqtgraph's GLMeshItem starts along Z.
        mid = ((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2)
        item.translate(*mid)

        # Rotation from Z axis to the direction vector.
        if length > 0:
            theta = math.degrees(math.acos(max(-1, min(1, dz / length))))
            axis_x = -dy
            axis_y = dx
            axis_z = 0
            if abs(axis_x) + abs(axis_y) < 1e-7:
                axis_x, axis_y, axis_z = 1, 0, 0
            item.rotate(theta, axis_x, axis_y, axis_z)

        self.view.addItem(item)
        self.parts.append(item)
        return item

    def build_mannequin(self):
        # Simple neutral mannequin made from primitive meshes.
        # Coordinates use Y as vertical.
        head = self.sphere((0, 7.8, 0), 0.85)
        neck = self.cylinder_between((0, 6.9, 0), (0, 7.2, 0), 0.28)

        torso = self.cylinder_between((0, 4.9, 0), (0, 6.9, 0), 0.72)
        hip = self.sphere((0, 4.7, 0), 0.72)

        shoulder_l = (-1.0, 6.4, 0)
        shoulder_r = (1.0, 6.4, 0)
        elbow_l = (-1.75, 5.15, 0)
        elbow_r = (1.75, 5.15, 0)
        hand_l = (-2.0, 3.95, 0)
        hand_r = (2.0, 3.95, 0)

        self.sphere(shoulder_l, 0.38)
        self.sphere(shoulder_r, 0.38)
        self.cylinder_between(shoulder_l, elbow_l, 0.28)
        self.cylinder_between(shoulder_r, elbow_r, 0.28)
        self.sphere(elbow_l, 0.34)
        self.sphere(elbow_r, 0.34)
        self.cylinder_between(elbow_l, hand_l, 0.24)
        self.cylinder_between(elbow_r, hand_r, 0.24)
        self.sphere(hand_l, 0.28)
        self.sphere(hand_r, 0.28)

        hip_l = (-0.45, 4.1, 0)
        hip_r = (0.45, 4.1, 0)
        knee_l = (-0.55, 2.2, 0)
        knee_r = (0.55, 2.2, 0)
        foot_l = (-0.55, 0.45, 0.2)
        foot_r = (0.55, 0.45, 0.2)

        self.sphere(hip_l, 0.38)
        self.sphere(hip_r, 0.38)
        self.cylinder_between(hip_l, knee_l, 0.34)
        self.cylinder_between(hip_r, knee_r, 0.34)
        self.sphere(knee_l, 0.35)
        self.sphere(knee_r, 0.35)
        self.cylinder_between(knee_l, foot_l, 0.27)
        self.cylinder_between(knee_r, foot_r, 0.27)
        self.sphere(foot_l, 0.30)
        self.sphere(foot_r, 0.30)

    def reset_camera(self):
        if self.view:
            self.view.setCameraPosition(distance=18, elevation=12, azimuth=25)


class Timeline(QWidget):
    frameChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.current_frame = 1
        self.total_frames = 24

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Timeline</b>"))

        self.frame_label = QLabel("Frame 1 / 24")
        header.addStretch()
        header.addWidget(self.frame_label)
        layout.addLayout(header)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, self.total_frames)
        self.slider.setValue(1)
        self.slider.valueChanged.connect(self.change_frame)
        layout.addWidget(self.slider)

        self.frames = QListWidget()
        self.frames.setFlow(QListWidget.Flow.LeftToRight)
        self.frames.setWrapping(False)
        self.frames.setFixedHeight(70)

        for i in range(1, self.total_frames + 1):
            item = QListWidgetItem(str(i))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.frames.addItem(item)

        self.frames.setCurrentRow(0)
        self.frames.currentRowChanged.connect(self.list_frame_changed)
        layout.addWidget(self.frames)

        controls = QHBoxLayout()
        add = QPushButton("+ Frame")
        duplicate = QPushButton("Duplicate")
        delete = QPushButton("Delete")
        controls.addWidget(add)
        controls.addWidget(duplicate)
        controls.addWidget(delete)
        controls.addStretch()
        layout.addLayout(controls)

        add.clicked.connect(self.add_frame)
        duplicate.clicked.connect(self.duplicate_frame)
        delete.clicked.connect(self.delete_frame)

    def change_frame(self, value):
        self.current_frame = value
        self.frame_label.setText(f"Frame {value} / {self.total_frames}")
        self.frames.blockSignals(True)
        self.frames.setCurrentRow(value - 1)
        self.frames.blockSignals(False)
        self.frameChanged.emit(value)

    def list_frame_changed(self, row):
        if row >= 0:
            self.slider.setValue(row + 1)

    def add_frame(self):
        self.total_frames += 1
        self.slider.setRange(1, self.total_frames)
        self.frames.addItem(QListWidgetItem(str(self.total_frames)))
        self.slider.setValue(self.total_frames)

    def duplicate_frame(self):
        self.add_frame()

    def delete_frame(self):
        if self.total_frames <= 1:
            return
        row = self.slider.value() - 1
        item = self.frames.takeItem(row)
        del item
        self.total_frames -= 1

        for i in range(self.frames.count()):
            self.frames.item(i).setText(str(i + 1))

        self.slider.setRange(1, self.total_frames)
        self.slider.setValue(max(1, min(row + 1, self.total_frames)))


class AnimForge(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 900)

        self.accent = "#7c4dff"
        self.canvas_bg = "#20242e"
        self.current_tool = "Pencil"
        self.project_path = None

        self.build_ui()
        self.apply_theme()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top = QWidget()
        top.setObjectName("TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)

        logo = QLabel("◈  AnimForge")
        logo.setStyleSheet("font-size: 20px; font-weight: 700;")
        top_layout.addWidget(logo)

        self.animate_btn = QPushButton("🎬  Animate")
        self.edit_btn = QPushButton("▣  Edit")
        self.animate_btn.setCheckable(True)
        self.edit_btn.setCheckable(True)
        self.animate_btn.setChecked(True)
        self.animate_btn.clicked.connect(lambda: self.set_workspace("Animate"))
        self.edit_btn.clicked.connect(lambda: self.set_workspace("Edit"))

        top_layout.addSpacing(25)
        top_layout.addWidget(self.animate_btn)
        top_layout.addWidget(self.edit_btn)

        top_layout.addStretch()

        save = QPushButton("Save")
        load = QPushButton("Open")
        theme = QPushButton("Theme")
        background = QPushButton("Background")

        top_layout.addWidget(load)
        top_layout.addWidget(save)
        top_layout.addWidget(theme)
        top_layout.addWidget(background)

        root.addWidget(top)

        # Main content
        main_split = QSplitter(Qt.Orientation.Horizontal)

        # Left: tools + layers
        left = QWidget()
        left_layout = QVBoxLayout(left)

        tools_box = QGroupBox("Tools")
        tools_layout = QGridLayout(tools_box)

        tools = [
            ("Select", "select"),
            ("Move", "move"),
            ("Pencil", "pencil"),
            ("Eraser", "eraser"),
            ("3D Model", "3d"),
            ("Camera", "camera"),
        ]

        for index, (name, key) in enumerate(tools):
            button = QPushButton(name)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, k=key: self.choose_tool(k))
            tools_layout.addWidget(button, index // 2, index % 2)

        left_layout.addWidget(tools_box)

        layer_box = QGroupBox("Scene / Layers")
        layer_layout = QVBoxLayout(layer_box)

        self.layers = QListWidget()
        for name in [
            "3D Model (Mannequin)",
            "2D Character",
            "Drawing",
            "Background",
            "Effects"
        ]:
            self.layers.addItem(QListWidgetItem(name))

        self.layers.setCurrentRow(0)
        layer_layout.addWidget(self.layers)

        add_layer = QPushButton("+ Add Layer")
        add_layer.clicked.connect(self.add_layer)
        layer_layout.addWidget(add_layer)

        left_layout.addWidget(layer_box, 1)
        left.setMinimumWidth(230)

        # Center: tabs containing 2D and 3D view
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 4, 4, 4)

        self.viewport_tabs = QTabWidget()

        self.canvas = DrawingCanvas()
        self.canvas.set_background(self.canvas_bg)

        self.mannequin = MannequinView()

        self.viewport_tabs.addTab(self.canvas, "2D Canvas")
        self.viewport_tabs.addTab(self.mannequin, "3D Viewport")

        center_layout.addWidget(self.viewport_tabs)

        # Bottom timeline
        self.timeline = Timeline()
        center_layout.addWidget(self.timeline)

        # Right properties
        right = QWidget()
        right_layout = QVBoxLayout(right)

        prop_box = QGroupBox("Properties")
        prop_layout = QVBoxLayout(prop_box)

        self.model_label = QLabel("<b>3D Model</b>")
        prop_layout.addWidget(self.model_label)

        import_model = QPushButton("Import OBJ Model")
        sculpt = QPushButton("Open Sculpt Editor")
        reset = QPushButton("Reset Mannequin")

        import_model.clicked.connect(self.import_obj)
        sculpt.clicked.connect(self.sculpt_placeholder)
        reset.clicked.connect(self.reset_mannequin)

        prop_layout.addWidget(import_model)
        prop_layout.addWidget(sculpt)
        prop_layout.addWidget(reset)

        transform = QGroupBox("Transform")
        transform_layout = QGridLayout(transform)

        self.x_spin = self.make_spin()
        self.y_spin = self.make_spin()
        self.z_spin = self.make_spin()
        self.rx_spin = self.make_spin()
        self.ry_spin = self.make_spin()
        self.rz_spin = self.make_spin()
        self.scale_spin = self.make_spin(1.0)

        for row, (label, widget) in enumerate([
            ("X", self.x_spin), ("Y", self.y_spin), ("Z", self.z_spin),
            ("Rot X", self.rx_spin), ("Rot Y", self.ry_spin), ("Rot Z", self.rz_spin),
            ("Scale", self.scale_spin)
        ]):
            transform_layout.addWidget(QLabel(label), row, 0)
            transform_layout.addWidget(widget, row, 1)

        prop_layout.addWidget(transform)

        brush = QGroupBox("2D Brush")
        brush_layout = QGridLayout(brush)

        brush_layout.addWidget(QLabel("Size"), 0, 0)
        self.brush_size = QSpinBox()
        self.brush_size.setRange(1, 100)
        self.brush_size.setValue(6)
        brush_layout.addWidget(self.brush_size, 0, 1)

        brush_color = QPushButton("Choose Color")
        brush_color.clicked.connect(self.choose_brush_color)
        brush_layout.addWidget(brush_color, 1, 0, 1, 2)

        clear = QPushButton("Clear Canvas")
        clear.clicked.connect(self.canvas.clear_canvas)
        brush_layout.addWidget(clear, 2, 0, 1, 2)

        prop_layout.addWidget(brush)
        right_layout.addWidget(prop_box)
        right_layout.addStretch()

        right.setMinimumWidth(300)

        main_split.addWidget(left)
        main_split.addWidget(center)
        main_split.addWidget(right)
        main_split.setStretchFactor(1, 1)

        root.addWidget(main_split, 1)

        # Menu
        menu = self.menuBar()
        file_menu = menu.addMenu("File")
        edit_menu = menu.addMenu("Edit")
        view_menu = menu.addMenu("View")
        animation_menu = menu.addMenu("Animation")

        new_action = QAction("New Project", self)
        new_action.triggered.connect(self.new_project)
        file_menu.addAction(new_action)

        open_action = QAction("Open Project", self)
        open_action.triggered.connect(self.load_project)
        file_menu.addAction(open_action)

        save_action = QAction("Save Project", self)
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)

        export_action = QAction("Export Beta Frame", self)
        export_action.triggered.connect(self.export_frame)
        animation_menu.addAction(export_action)

        undo = QAction("Undo", self)
        undo.setShortcut("Ctrl+Z")
        edit_menu.addAction(undo)

        theme.triggered = None
        theme.clicked.connect(self.choose_theme_color)
        background.clicked.connect(self.choose_background_color)

    def make_spin(self, value=0.0):
        spin = QDoubleSpinBox()
        spin.setRange(-10000, 10000)
        spin.setDecimals(3)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        return spin

    def set_workspace(self, name):
        if name == "Animate":
            self.animate_btn.setChecked(True)
            self.edit_btn.setChecked(False)
            self.viewport_tabs.setCurrentIndex(0)
        else:
            self.animate_btn.setChecked(False)
            self.edit_btn.setChecked(True)
            self.viewport_tabs.setCurrentIndex(0)

    def choose_tool(self, key):
        if key == "pencil":
            self.canvas.set_pen(width=self.brush_size.value(), eraser=False)
            self.viewport_tabs.setCurrentIndex(0)
        elif key == "eraser":
            self.canvas.set_pen(width=self.brush_size.value(), eraser=True)
            self.viewport_tabs.setCurrentIndex(0)
        elif key == "3d":
            self.viewport_tabs.setCurrentIndex(1)
        elif key == "camera":
            self.mannequin.reset_camera()
        else:
            self.current_tool = key

    def choose_brush_color(self):
        color = QColorDialog.getColor(self.canvas.pen_color, self, "Brush Color")
        if color.isValid():
            self.canvas.set_pen(color=color.name(), width=self.brush_size.value())

    def choose_theme_color(self):
        color = QColorDialog.getColor(QColor(self.accent), self, "UI Accent Color")
        if color.isValid():
            self.accent = color.name()
            self.apply_theme()

    def choose_background_color(self):
        color = QColorDialog.getColor(QColor(self.canvas_bg), self, "Canvas Background")
        if color.isValid():
            self.canvas_bg = color.name()
            self.canvas.set_background(self.canvas_bg)

    def apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: #11151d;
                color: #e7eaf0;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 13px;
            }}
            #TopBar {{
                background: #0c1119;
                border-bottom: 1px solid #2a3140;
            }}
            QMenuBar {{
                background: #0c1119;
                color: #e7eaf0;
            }}
            QMenuBar::item:selected, QMenu::item:selected {{
                background: {self.accent};
            }}
            QPushButton {{
                background: #1a2130;
                border: 1px solid #30394b;
                border-radius: 6px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                border-color: {self.accent};
            }}
            QPushButton:checked {{
                background: {self.accent};
                color: white;
            }}
            QGroupBox {{
                border: 1px solid #2c3545;
                border-radius: 7px;
                margin-top: 10px;
                padding-top: 12px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QListWidget, QGraphicsView, QTabWidget::pane {{
                background: #171d27;
                border: 1px solid #2a3342;
            }}
            QListWidget::item:selected {{
                background: {self.accent};
            }}
            QTabBar::tab {{
                background: #151b25;
                padding: 9px 16px;
                border: 1px solid #293241;
            }}
            QTabBar::tab:selected {{
                background: {self.accent};
            }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: #303949;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                margin: -5px 0;
                background: {self.accent};
                border-radius: 7px;
            }}
        """)

    def add_layer(self):
        row = self.layers.count() + 1
        self.layers.addItem(QListWidgetItem(f"New Layer {row}"))

    def reset_mannequin(self):
        self.mannequin.reset_camera()
        for spin in [
            self.x_spin, self.y_spin, self.z_spin,
            self.rx_spin, self.ry_spin, self.rz_spin
        ]:
            spin.setValue(0)
        self.scale_spin.setValue(1)

    def import_obj(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import 3D Model",
            "",
            "OBJ Model (*.obj)"
        )
        if not path:
            return

        if not HAS_3D:
            QMessageBox.warning(self, "3D unavailable",
                                "Install PyOpenGL and pyqtgraph first.")
            return

        # Basic OBJ importer: vertices + triangular/quadrilateral faces.
        try:
            vertices = []
            faces = []

            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("v "):
                        p = line.split()
                        vertices.append([float(p[1]), float(p[2]), float(p[3])])
                    elif line.startswith("f "):
                        tokens = line.split()[1:]
                        ids = [int(t.split("/")[0]) - 1 for t in tokens]
                        if len(ids) >= 3:
                            faces.append(ids)

            if not vertices or not faces:
                raise ValueError("OBJ contains no readable vertices/faces.")

            # Triangulate polygon faces.
            tri_faces = []
            for face in faces:
                for i in range(1, len(face) - 1):
                    tri_faces.append([face[0], face[i], face[i + 1]])

            import numpy as np
            verts = np.array(vertices, dtype=float)
            fs = np.array(tri_faces, dtype=int)

            md = gl.MeshData(vertexes=verts, faces=fs)
            mesh = gl.GLMeshItem(
                meshdata=md,
                smooth=False,
                color=(0.72, 0.75, 0.82, 1.0),
                shader="shaded",
                drawEdges=False
            )

            # Normalize model size.
            center = verts.mean(axis=0)
            verts_centered = verts - center
            max_extent = max(abs(verts_centered).max(), 0.001)
            scale = 6.0 / max_extent

            # Rebuild normalized mesh.
            verts_centered *= scale
            md = gl.MeshData(vertexes=verts_centered, faces=fs)
            mesh = gl.GLMeshItem(
                meshdata=md,
                smooth=False,
                color=(0.72, 0.75, 0.82, 1.0),
                shader="shaded",
                drawEdges=False
            )

            self.mannequin.view.addItem(mesh)
            self.layers.addItem(QListWidgetItem(Path(path).stem + " [3D Model]"))
            self.viewport_tabs.setCurrentIndex(1)

            QMessageBox.information(
                self,
                "Imported",
                f"Imported: {Path(path).name}\n\n"
                "The model was added as a separate 3D layer."
            )

        except Exception as exc:
            QMessageBox.critical(
                self, "Import failed",
                f"Could not import this OBJ model.\n\n{exc}"
            )

    def sculpt_placeholder(self):
        QMessageBox.information(
            self,
            "Sculpt Editor — Beta",
            "The sculpt workspace is planned for the next beta.\n\n"
            "The architecture already treats 3D models as their own layer, "
            "so the sculpt system can be added without replacing the 2D timeline."
        )

    def new_project(self):
        self.timeline = self.timeline  # keep current UI object
        self.canvas.clear_canvas()
        self.layers.clear()
        for name in ["3D Model (Mannequin)", "2D Character", "Drawing", "Background"]:
            self.layers.addItem(QListWidgetItem(name))
        self.timeline.slider.setValue(1)

    def project_data(self):
        return {
            "app": APP_NAME,
            "ui": {
                "accent": self.accent,
                "canvas_background": self.canvas_bg
            },
            "animation": {
                "current_frame": self.timeline.current_frame,
                "total_frames": self.timeline.total_frames
            },
            "layers": [
                self.layers.item(i).text()
                for i in range(self.layers.count())
            ],
            "notes": "AnimForge beta project file"
        }

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save AnimForge Project", "",
            "AnimForge Project (*.animforge.json)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.project_data(), f, indent=2)
            self.project_path = path
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open AnimForge Project", "",
            "AnimForge Project (*.animforge.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            ui = data.get("ui", {})
            self.accent = ui.get("accent", self.accent)
            self.canvas_bg = ui.get("canvas_background", self.canvas_bg)
            self.canvas.set_background(self.canvas_bg)

            self.layers.clear()
            for name in data.get("layers", []):
                self.layers.addItem(QListWidgetItem(name))

            animation = data.get("animation", {})
            total = int(animation.get("total_frames", 24))
            while self.timeline.total_frames < total:
                self.timeline.add_frame()
            while self.timeline.total_frames > total:
                self.timeline.delete_frame()

            self.timeline.slider.setValue(
                max(1, min(int(animation.get("current_frame", 1)), total))
            )

            self.apply_theme()
            self.project_path = path

        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def export_frame(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Canvas Frame", "",
            "PNG Image (*.png)"
        )
        if not path:
            return

        pixmap = self.canvas.grab()
        if pixmap.save(path):
            QMessageBox.information(self, "Exported", f"Saved:\n{path}")
        else:
            QMessageBox.warning(self, "Export failed", "Could not save the PNG.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AnimForge")
    window = AnimForge()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
