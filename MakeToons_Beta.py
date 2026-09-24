
import sys, json, base64, os, shutil, copy, traceback
from pathlib import Path
from collections import deque

from PySide6.QtCore import Qt, QPoint, QRect, QBuffer, QIODevice, QTimer, Signal, QSize, QByteArray
from PySide6.QtGui import (
    QColor, QImage, QPainter, QPen, QPixmap, QIcon, QKeySequence,
    QShortcut, QPolygon, QPainterPath, QCursor, QFont, QBrush, QPalette
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QSpinBox, QColorDialog,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QInputDialog, QSplitter,
    QScrollArea, QToolButton, QDialog, QDialogButtonBox, QLineEdit,
    QDoubleSpinBox, QFormLayout, QStackedWidget, QComboBox, QSlider,
    QTabWidget, QPlainTextEdit
)
from PySide6.QtSvg import QSvgRenderer

APP = "MakeToons"
VERSION = "0.8 Beta"
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
        # Per-frame exposure source. -1 means the frame is its own drawing.
        self.exposure = list(range(frames))

    def ensure(self, frames):
        while len(self.frames) < frames:
            self.frames.append(blank(self.frames[0].width(), self.frames[0].height()))
            self.exposure.append(len(self.frames)-1)
        self.frames = self.frames[:frames]
        self.exposure = self.exposure[:frames]

    def source_index(self, frame):
        if not (0 <= frame < len(self.frames)):
            return frame
        src = self.exposure[frame] if frame < len(self.exposure) else frame
        return max(0, min(src, len(self.frames)-1))

    def image_at(self, frame):
        return self.frames[self.source_index(frame)]


class ColorDialog(QDialog):
    def __init__(self, app, initial):
        super().__init__(app)
        self.setWindowTitle("MakeToons Color Picker")
        self.resize(520, 560)
        self.result_color = QColor(initial)
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(100, 100)
        top.addWidget(self.preview)
        title = QLabel("COLOR\nRGB + HSL")
        title.setStyleSheet("font-size:20px;font-weight:bold;")
        top.addWidget(title)
        top.addStretch()
        root.addLayout(top)

        self.r = QSpinBox(); self.r.setRange(0, 255)
        self.g = QSpinBox(); self.g.setRange(0, 255)
        self.b = QSpinBox(); self.b.setRange(0, 255)
        self.h = QSpinBox(); self.h.setRange(0, 359)
        self.s = QSpinBox(); self.s.setRange(0, 255)
        self.l = QSpinBox(); self.l.setRange(0, 255)

        form = QFormLayout()
        for label, box in [
            ("Red (R)", self.r), ("Green (G)", self.g), ("Blue (B)", self.b),
            ("Hue (H)", self.h), ("Saturation (S)", self.s), ("Lightness (L)", self.l)
        ]:
            form.addRow(label, box)
        root.addLayout(form)

        native = QPushButton("Open Advanced Color Picker")
        native.clicked.connect(self.native_picker)
        root.addWidget(native)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for box in (self.r, self.g, self.b): box.valueChanged.connect(self.rgb_changed)
        for box in (self.h, self.s, self.l): box.valueChanged.connect(self.hsl_changed)
        self.set_rgb(initial.red(), initial.green(), initial.blue())

    def update_preview(self):
        self.preview.setStyleSheet(
            f"background:{self.result_color.name(QColor.HexArgb)};"
            "border-radius:50px;border:2px solid #68758c;"
        )

    def set_rgb(self, r, g, b):
        for box, value in ((self.r,r),(self.g,g),(self.b,b)):
            box.blockSignals(True); box.setValue(value); box.blockSignals(False)
        c = QColor(r,g,b)
        h,s,l,_ = c.getHsl()
        for box,value in ((self.h,max(0,h)),(self.s,s),(self.l,l)):
            box.blockSignals(True); box.setValue(value); box.blockSignals(False)
        self.result_color = c
        self.update_preview()

    def rgb_changed(self):
        self.set_rgb(self.r.value(), self.g.value(), self.b.value())

    def hsl_changed(self):
        self.set_rgb(*QColor.fromHsl(self.h.value(), self.s.value(), self.l.value()).getRgb()[:3])

    def native_picker(self):
        c = QColorDialog.getColor(self.result_color, self, "Advanced Color Picker")
        if c.isValid(): self.set_rgb(c.red(), c.green(), c.blue())


class NewProjectDialog(QDialog):
    PRESETS = {
        "YouTube 16:9 — 1920 × 1080": (1920,1080),
        "TikTok 9:16 — 1080 × 1920": (1080,1920),
        "Instagram Post 1:1 — 1080 × 1080": (1080,1080),
        "3:4 — 1080 × 1440": (1080,1440),
        "HD 16:9 — 1280 × 720": (1280,720),
        "Custom": None,
    }
    def __init__(self,parent=None):
        super().__init__(parent); self.setWindowTitle("New MakeToons Project")
        root=QVBoxLayout(self); form=QFormLayout()
        self.name=QLineEdit("My Animation")
        self.preset=QComboBox(); self.preset.addItems(self.PRESETS.keys())
        self.width=QSpinBox(); self.width.setRange(64,8000); self.width.setValue(DEFAULT_W)
        self.height=QSpinBox(); self.height.setRange(64,8000); self.height.setValue(DEFAULT_H)
        self.frames=QSpinBox(); self.frames.setRange(1,1000); self.frames.setValue(DEFAULT_FRAMES)
        self.duration=QDoubleSpinBox(); self.duration.setRange(.01,10); self.duration.setDecimals(2); self.duration.setSingleStep(.01); self.duration.setValue(.10); self.duration.setSuffix(" s")
        form.addRow("Project name:",self.name); form.addRow("Canvas preset:",self.preset); form.addRow("Width:",self.width); form.addRow("Height:",self.height); form.addRow("Starting frames:",self.frames); form.addRow("Frame duration:",self.duration)
        root.addLayout(form)
        self.preset.currentTextChanged.connect(self.apply_preset); self.apply_preset(self.preset.currentText())
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
    def apply_preset(self,text):
        size=self.PRESETS[text]; custom=size is None; self.width.setEnabled(custom); self.height.setEnabled(custom)
        if size: self.width.setValue(size[0]); self.height.setValue(size[1])
    def values(self):
        return {"name":self.name.text().strip() or "My Animation","w":self.width.value(),"h":self.height.value(),"frames":self.frames.value(),"duration":self.duration.value()}


class ExportDialog(QDialog):
    def __init__(self,parent,title="Export PNG"):
        super().__init__(parent); self.setWindowTitle(title); root=QVBoxLayout(self); root.addWidget(QLabel("Transparent PNG?"))
        self.toggle=QPushButton("ON — Transparent"); self.toggle.setCheckable(True); self.toggle.setChecked(True); self.toggle.clicked.connect(self.update_button); root.addWidget(self.toggle)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons); self.update_button()
    def update_button(self):
        self.toggle.setText("ON — Transparent" if self.toggle.isChecked() else "OFF — Opaque")
        self.toggle.setStyleSheet(("background:#20a85a;color:white;" if self.toggle.isChecked() else "background:#c52d35;color:white;")+"border-radius:7px;padding:9px;")
    @property
    def transparent(self): return self.toggle.isChecked()


class Canvas(QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; self.zoom=1.; self.tool="pencil"; self.size=8; self.opacity=1.; self.color=QColor("white")
        self.last=None; self.drawing=False; self.panning=False; self.pan_start=QPoint(); self.view_offset=QPoint(0,0); self.lasso_points=[]; self.move_start=None; self.setMouseTracking(True); self.setFocusPolicy(Qt.StrongFocus); self.setMinimumSize(400,250)

    def image_rect(self):
        w=int(self.app.canvas_w*self.zoom); h=int(self.app.canvas_h*self.zoom)
        return QRect((self.width()-w)//2+self.view_offset.x(),(self.height()-h)//2+self.view_offset.y(),w,h)

    def image_pos(self,p):
        r=self.image_rect()
        if not r.contains(p): return None
        return QPoint(max(0,min(self.app.canvas_w-1,int((p.x()-r.x())/self.zoom))),max(0,min(self.app.canvas_h-1,int((p.y()-r.y())/self.zoom))))

    def wheelEvent(self,e):
        if e.modifiers() & Qt.ControlModifier:
            old=self.zoom; new=max(.10,min(8.,old*(1.15 if e.angleDelta().y()>0 else 1/1.15))); cursor=e.position().toPoint(); before=self.image_pos(cursor); self.zoom=new
            if before:
                r=self.image_rect(); target=QPoint(int(r.left()+before.x()*self.zoom),int(r.top()+before.y()*self.zoom)); self.view_offset += cursor-target
            self.app.update_zoom_label(); self.update()
        else:
            self.app.timeline.scroll_horizontal(e.angleDelta().y())
            super().wheelEvent(e)

    def mousePressEvent(self,e):
        if e.button()==Qt.MiddleButton:
            self.panning=True; self.pan_start=e.position().toPoint(); self.setCursor(Qt.ClosedHandCursor); return
        if e.button()==Qt.LeftButton and QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self.panning=True; self.pan_start=e.position().toPoint(); self.setCursor(Qt.ClosedHandCursor); return
        p=self.image_pos(e.position().toPoint())
        if p is None: return
        if self.tool=="picker":
            self.color=self.app.composite().pixelColor(p); self.app.color_preview(); self.app.set_tool("pencil"); return
        if self.tool=="lasso":
            self.lasso_points=[p]; self.drawing=True; return
        if self.tool=="magic":
            self.app.magic_wand(p); return
        if self.tool=="bucket":
            self.app.bucket_fill(p); return
        if self.tool=="text":
            self.app.add_text_at(p); return
        if self.tool=="select_move":
            if self.app.selection_path and self.app.selection_path.contains(p):
                self.move_start = p
                self.setCursor(Qt.ClosedHandCursor)
            return
        layer=self.app.layer()
        if not layer or layer.locked: return
        if self.tool in ("pencil","eraser"):
            self.app.begin_undo()
            self.drawing=True; self.last=p; self.stroke_to(p)
            self.set_tool_cursor()

    def mouseMoveEvent(self,e):
        p2=e.position().toPoint()
        if self.panning:
            delta=p2-self.pan_start; self.view_offset+=delta; self.pan_start=p2; self.update(); return
        if not self.drawing: self.update_cursor(p2); return
        p=self.image_pos(p2)
        if p is None: return
        if self.tool=="select_move":
            if self.move_start is not None:
                dx=p.x()-self.move_start.x(); dy=p.y()-self.move_start.y()
                if dx or dy:
                    self.app.move_selection_pixels(dx,dy, record_undo=False)
                    self.move_start=p
            return
        if self.tool=="lasso":
            if not self.lasso_points or (p-self.lasso_points[-1]).manhattanLength()>3: self.lasso_points.append(p); self.update()
            return
        if self.tool in ("pencil","eraser"):
            self.stroke_to(p); self.last=p

    def mouseReleaseEvent(self,e):
        if e.button() in (Qt.LeftButton,Qt.RightButton):
            if self.tool=="lasso" and self.drawing and len(self.lasso_points)>=3: self.app.make_selection(self.lasso_points)
            self.drawing=False; self.last=None
            self.move_start=None
            if hasattr(self.app,"timeline"): self.app.timeline.update_cells()
        if e.button() in (Qt.LeftButton,Qt.MiddleButton):
            self.panning=False; self.unsetCursor()

    def update_cursor(self,p):
        if self.tool in ("pencil","eraser"):
            self.set_tool_cursor()
        elif self.tool=="lasso": self.setCursor(Qt.CrossCursor)
        elif self.tool=="picker": self.setCursor(Qt.CrossCursor)
        elif self.tool=="magic": self.setCursor(Qt.CrossCursor)
        elif self.tool=="bucket": self.setCursor(Qt.CrossCursor)
        elif self.tool=="text": self.setCursor(Qt.IBeamCursor)
        else: self.unsetCursor()

    def set_tool_cursor(self):
        if self.app.cursor_style=="Cross":
            self.setCursor(Qt.CrossCursor); return
        d=max(4,int(self.size*self.zoom)); d=min(d,128)
        pm=QPixmap(d+4,d+4); pm.fill(Qt.transparent); q=QPainter(pm); q.setPen(QPen(Qt.white,1)); q.drawEllipse(2,2,d,d); q.end()
        self.setCursor(QCursor(pm, d//2+2, d//2+2))

    def stroke_to(self,p):
        layer=self.app.layer()
        if not layer: return
        img=layer.frames[self.app.frame]; painter=QPainter(img); painter.setRenderHint(QPainter.Antialiasing,True)
        if self.tool=="eraser":
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            pen=QPen(Qt.transparent,max(1,int(self.size)),Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin)
        else:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            c=QColor(self.color); c.setAlphaF(max(0.,min(1.,self.opacity)))
            pen=QPen(c,max(1,int(self.size)),Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin)
        painter.setPen(pen)
        if self.last is None: painter.drawPoint(p)
        else: painter.drawLine(self.last,p)
        painter.end()
        layer.exposure[self.app.frame]=self.app.frame
        self.app.dirty=True; self.update()

    def paintEvent(self,e):
        p=QPainter(self); p.fillRect(self.rect(),self.app.program_background())
        r=self.image_rect(); self.app.paint_background(p,r)
        if self.app.onion and not self.app.playing:
            for d in range(self.app.prev_onion,0,-1):
                i=self.app.frame-d
                if i>=0:
                    p.save(); p.setOpacity(max(.08,.30/d)); p.drawImage(r,self.app.tinted_composite(self.app.drawing_composite(i),self.app.onion_prev_color)); p.restore()
            for d in range(1,self.app.next_onion+1):
                i=self.app.frame+d
                if i<self.app.frames:
                    p.save(); p.setOpacity(max(.08,.30/d)); p.drawImage(r,self.app.tinted_composite(self.app.drawing_composite(i),self.app.onion_next_color)); p.restore()
        p.drawImage(r,self.app.composite())
        if self.app.selection_points:
            pts=[QPoint(r.left()+int(pt.x()*self.zoom),r.top()+int(pt.y()*self.zoom)) for pt in self.app.selection_points]
            p.save(); p.setPen(QPen(self.app.selection_color,2,Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawPolygon(QPolygon(pts)); p.restore()
        if self.lasso_points:
            pts=[QPoint(r.left()+int(pt.x()*self.zoom),r.top()+int(pt.y()*self.zoom)) for pt in self.lasso_points]
            p.setPen(QPen(self.app.selection_color,2,Qt.DashLine)); p.drawPolyline(QPolygon(pts))
        # Selection overlay: blue, configurable, non-editable.
        if self.app.selection_mask is not None:
            overlay=blank(self.app.canvas_w,self.app.canvas_h); op=QPainter(overlay); op.setClipPath(self.app.selection_path); c=QColor(self.app.selection_color); c.setAlphaF(self.app.selection_opacity); op.fillRect(overlay.rect(),c); op.end(); p.drawImage(r,overlay)
        p.setPen(QPen(QColor("#65738b"),2)); p.drawRect(r); p.end()



class LayerHandle(QToolButton):
    moved = Signal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("☰")
        self.setToolTip("Drag to reorder layer")
        self.setFixedWidth(30)
        self._start = None
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.position().toPoint()
        super().mousePressEvent(e)
    def mouseMoveEvent(self, e):
        if self._start is not None and (e.position().toPoint() - self._start).manhattanLength() > 12:
            dy = e.position().toPoint().y() - self._start.y()
            self.moved.emit(-1 if dy < 0 else 1)
            self._start = e.position().toPoint()
        super().mouseMoveEvent(e)
    def mouseReleaseEvent(self, e):
        self._start = None
        super().mouseReleaseEvent(e)


class LayerRow(QWidget):
    clicked = Signal()
    moved = Signal(int)
    def __init__(self, layer, app):
        super().__init__()
        self.layer = layer
        self.app = app
        row = QHBoxLayout(self)
        row.setContentsMargins(0,0,0,0)
        self.name = QToolButton()
        self.name.setText(("👁 " if layer.visible else "○ ") + ("🔒 " if layer.locked else "") + layer.name)
        self.name.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.name.setToolTip("Click to select layer")
        self.name.clicked.connect(self.clicked.emit)
        self.handle = LayerHandle()
        self.handle.moved.connect(self.moved.emit)
        row.addWidget(self.name, 1)
        row.addWidget(self.handle)

class Timeline(QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; root=QVBoxLayout(self); root.setContentsMargins(4,4,4,4)
        top=QHBoxLayout(); top.addWidget(QLabel("Timeline")); top.addStretch()
        self.prev_btn=QToolButton(); self.prev_btn.setText("◀"); self.prev_btn.clicked.connect(lambda:app.set_frame(app.frame-1))
        self.play_btn=QToolButton(); self.play_btn.setText("▶"); self.play_btn.clicked.connect(app.toggle_play)
        self.next_btn=QToolButton(); self.next_btn.setText("▶"); self.next_btn.clicked.connect(lambda:app.set_frame(app.frame+1))
        top.addWidget(self.prev_btn); top.addWidget(self.play_btn); top.addWidget(self.next_btn)
        self.frame_label=QLabel(); top.addWidget(self.frame_label)
        top.addWidget(QLabel("Frame:")); self.duration=QDoubleSpinBox(); self.duration.setRange(.01,10); self.duration.setDecimals(2); self.duration.setSingleStep(.01); self.duration.setValue(.10); self.duration.setSuffix(" s"); self.duration.setFixedWidth(86); self.duration.valueChanged.connect(app.set_frame_duration); top.addWidget(self.duration)
        self.fps_label=QLabel("10 FPS"); top.addWidget(self.fps_label); root.addLayout(top)

        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn); self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.body=QWidget(); self.grid=QGridLayout(self.body); self.grid.setSpacing(2); self.scroll.setWidget(self.body); root.addWidget(self.scroll,1)

        bottom=QHBoxLayout(); self.addb=QPushButton("+ Add Frame"); self.dupb=QPushButton("Duplicate"); self.delb=QPushButton("Delete"); self.extendb=QPushButton("Extend to Next"); self.addb.clicked.connect(app.add_frame); self.dupb.clicked.connect(app.duplicate_frame); self.delb.clicked.connect(app.delete_frame); self.extendb.clicked.connect(app.extend_frame); [bottom.addWidget(x) for x in (self.addb,self.dupb,self.delb,self.extendb)]; bottom.addStretch(); root.addLayout(bottom)

    def scroll_horizontal(self,delta):
        bar=self.scroll.horizontalScrollBar(); bar.setValue(bar.value()-delta)

    def cell_button(self,layer,f):
        b=QToolButton(); b.setFixedSize(48,30)
        img = layer.image_at(f)
        occupied=layer.background or self.app.has_pixels_fast(img)
        src=layer.source_index(f)
        b.setText("◆" if f==src and occupied else ("=" if src!=f else "·"))
        thumb = img.scaled(42,24,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        if not thumb.isNull():
            b.setIcon(QIcon(QPixmap.fromImage(thumb)))
            b.setIconSize(QSize(42,24))
        active=f==self.app.frame and layer is self.app.layer()
        b.setStyleSheet(f"QToolButton{{background:{self.app.accent.name() if active else '#152238'};color:{'#fff' if occupied else '#65738b'};border:1px solid #31405a;border-radius:3px;}}")
        b.clicked.connect(lambda _,i=f,l=layer:self.app.select_timeline_cell(l,i))
        return b

    def rebuild(self):
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.grid.addWidget(QLabel("Layers"),0,0)
        for f in range(self.app.frames):
            q=QToolButton(); q.setText(str(f+1)); q.setFixedSize(48,26); q.clicked.connect(lambda _,i=f:self.app.set_frame(i)); self.grid.addWidget(q,0,f+1)
        for row,layer in enumerate(self.app.layers,1):
            lr = LayerRow(layer, self.app)
            lr.clicked.connect(lambda l=layer:self.app.select_layer_obj(l))
            lr.moved.connect(lambda delta,l=layer:self.app.move_layer_obj(l, delta))
            self.grid.addWidget(lr,row,0)
            for f in range(self.app.frames): self.grid.addWidget(self.cell_button(layer,f),row,f+1)
        # fixed selection row
        sb=QToolButton(); sb.setText("▣ Selection"); sb.setFixedWidth(150); sb.setEnabled(False); self.grid.addWidget(sb,len(self.app.layers)+1,0)
        for f in range(self.app.frames):
            x=QToolButton(); x.setText("S" if self.app.selection_points else "·"); x.setEnabled(False); x.setFixedSize(48,30); self.grid.addWidget(x,len(self.app.layers)+1,f+1)
        self.update_label()

    def update_cells(self):
        # Rebuilding is intentionally avoided while drawing for responsiveness.
        self.frame_label.setText(f"Frame {self.app.frame+1} / {self.app.frames}")
        self.update()

    def update_label(self):
        self.frame_label.setText(f"Frame {self.app.frame+1} / {self.app.frames}")


class SettingsDialog(QDialog):
    def __init__(self,app):
        super().__init__(app); self.app=app; self.setWindowTitle("MakeToons Settings"); self.resize(700,700)
        root=QVBoxLayout(self); tabs=QTabWidget(); root.addWidget(tabs,1)

        appearance=QWidget(); ar=QVBoxLayout(appearance)
        ar.addWidget(QLabel("CANVAS"))
        self.bg_mode=QComboBox(); self.bg_mode.addItems(["Light Transparent Checker","Dark Transparent Checker","Solid Color"]); self.bg_mode.setCurrentText(app.bg_mode); self.bg_mode.currentTextChanged.connect(self.bg_changed)
        ar.addWidget(QLabel("Canvas background mode")); ar.addWidget(self.bg_mode)
        self.bg_color=QPushButton("Choose Background Color"); self.bg_color.clicked.connect(self.choose_bg); ar.addWidget(self.bg_color)
        ar.addWidget(self.line())

        ar.addWidget(QLabel("ONION SKIN"))
        self.onion_enable=QCheckBox("Enable onion skin"); self.onion_enable.setChecked(app.onion); self.onion_enable.toggled.connect(lambda v:setattr(app,"onion",v) or app.canvas.update()); ar.addWidget(self.onion_enable)
        self.prev_count=QSpinBox(); self.prev_count.setRange(0,8); self.prev_count.setValue(app.prev_onion); self.prev_count.valueChanged.connect(lambda v:setattr(app,"prev_onion",v) or app.canvas.update())
        self.next_count=QSpinBox(); self.next_count.setRange(0,8); self.next_count.setValue(app.next_onion); self.next_count.valueChanged.connect(lambda v:setattr(app,"next_onion",v) or app.canvas.update())
        ar.addWidget(QLabel("Previous frames")); ar.addWidget(self.prev_count); ar.addWidget(QLabel("Next frames")); ar.addWidget(self.next_count)
        self.prev_color=QPushButton("Previous onion color"); self.prev_color.clicked.connect(lambda:self.choose_onion("prev")); ar.addWidget(self.prev_color)
        self.next_color=QPushButton("Next onion color"); self.next_color.clicked.connect(lambda:self.choose_onion("next")); ar.addWidget(self.next_color)
        ar.addWidget(self.line())

        ar.addWidget(QLabel("CURSOR"))
        self.cursor_combo=QComboBox(); self.cursor_combo.addItems(["Circle","Cross"]); self.cursor_combo.setCurrentText(app.cursor_style); self.cursor_combo.currentTextChanged.connect(lambda t:setattr(app,"cursor_style",t)); ar.addWidget(self.cursor_combo)
        ar.addWidget(self.line())

        ar.addWidget(QLabel("SELECTION"))
        self.sel_color=QPushButton("Selection color"); self.sel_color.clicked.connect(self.choose_sel); ar.addWidget(self.sel_color)
        self.sel_opacity=QSlider(Qt.Horizontal); self.sel_opacity.setRange(5,100); self.sel_opacity.setValue(int(app.selection_opacity*100)); self.sel_opacity.valueChanged.connect(lambda v:setattr(app,"selection_opacity",v/100) or app.canvas.update()); ar.addWidget(QLabel("Selection transparency")); ar.addWidget(self.sel_opacity)
        ar.addWidget(self.line())

        ar.addWidget(QLabel("UI THEME"))
        self.accent=QPushButton("Choose UI Theme Color"); self.accent.clicked.connect(self.choose_accent); ar.addWidget(self.accent)
        ar.addWidget(QLabel("Program background"))
        self.program_bg_mode=QComboBox(); self.program_bg_mode.addItems(["Solid Color","Picture","Desktop Background"]); self.program_bg_mode.setCurrentText(app.program_bg_mode); self.program_bg_mode.currentTextChanged.connect(lambda t:setattr(app,"program_bg_mode",t) or app.apply_theme()); ar.addWidget(self.program_bg_mode)
        self.program_bg_color=QPushButton("Choose Program Background Color"); self.program_bg_color.clicked.connect(self.choose_program_bg); ar.addWidget(self.program_bg_color)
        self.program_bg_path=QPushButton("Choose Program Background Picture"); self.program_bg_path.clicked.connect(self.choose_program_picture); ar.addWidget(self.program_bg_path)
        ar.addWidget(self.line())

        ar.addWidget(QLabel("TOOLS"))
        self.outline_color=QPushButton("Choose Text/Outline Color"); self.outline_color.clicked.connect(self.choose_outline_color); ar.addWidget(self.outline_color)
        self.outline_size=QSpinBox(); self.outline_size.setRange(1,50); self.outline_size.setValue(app.outline_size); self.outline_size.valueChanged.connect(lambda v:setattr(app,"outline_size",v)); ar.addWidget(QLabel("Outline size")); ar.addWidget(self.outline_size)
        self.pencil_opacity=QSlider(Qt.Horizontal); self.pencil_opacity.setRange(1,100); self.pencil_opacity.setValue(int(app.canvas.opacity*100)); self.pencil_opacity.valueChanged.connect(lambda v:setattr(app.canvas,"opacity",v/100)); ar.addWidget(QLabel("Current tool opacity")); ar.addWidget(self.pencil_opacity)
        ar.addStretch()
        appearance_scroll=QScrollArea(); appearance_scroll.setWidgetResizable(True); appearance_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); appearance_scroll.setWidget(appearance)
        tabs.addTab(appearance_scroll,"Appearance")

        shortcuts=QWidget(); sr=QFormLayout(shortcuts); self.edits={}
        for key,label in [("pencil","Pencil"),("eraser","Eraser"),("picker","Picker"),("bucket","Bucket"),("lasso","Lasso"),("magic","Magic Wand"),("text","Text"),("play","Play/Pause"),("save","Save"),("undo","Undo"),("redo","Redo"),("copy","Copy"),("cut","Cut"),("paste","Paste")]:
            e=QLineEdit(app.shortcuts.get(key,"")); self.edits[key]=e; sr.addRow(label,e)
        tabs.addTab(shortcuts,"Shortcuts")

        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self.apply); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def line(self):
        from PySide6.QtWidgets import QFrame
        x=QFrame(); x.setFrameShape(QFrame.HLine); x.setFrameShadow(QFrame.Sunken); return x
    def bg_changed(self,t): self.app.bg_mode=t; self.app.canvas.update()
    def choose_bg(self):
        c=QColorDialog.getColor(self.app.bg_color,self,"Canvas Background"); 
        if c.isValid(): self.app.bg_color=c; self.app.canvas.update()
    def choose_onion(self,w):
        c=QColorDialog.getColor(self.app.onion_prev_color if w=="prev" else self.app.onion_next_color,self,"Onion Color")
        if c.isValid():
            if w=="prev": self.app.onion_prev_color=c
            else: self.app.onion_next_color=c
            self.app.canvas.update()
    def choose_sel(self):
        c=QColorDialog.getColor(self.app.selection_color,self,"Selection Color")
        if c.isValid(): self.app.selection_color=c; self.app.canvas.update()
    def choose_accent(self):
        c=QColorDialog.getColor(self.app.accent,self,"UI Theme Color")
        if c.isValid(): self.app.accent=c; self.app.apply_theme()
    def choose_program_bg(self):
        c=QColorDialog.getColor(self.app.program_bg_color,self,"Program Background Color")
        if c.isValid(): self.app.program_bg_color=c; self.app.apply_theme()
    def choose_program_picture(self):
        path,_=QFileDialog.getOpenFileName(self,"Program Background Picture","","Images (*.png *.jpg *.jpeg *.bmp)")
        if path: self.app.program_bg_path=path; self.app.program_bg_mode="Picture"; self.program_bg_mode.setCurrentText("Picture"); self.app.apply_theme()
    def choose_outline_color(self):
        c=QColorDialog.getColor(self.app.outline_color,self,"Outline Color")
        if c.isValid(): self.app.outline_color=c
    def apply(self):
        for k,e in self.edits.items():
            if e.text().strip(): self.app.shortcuts[k]=e.text().strip()
        self.app.save_settings(); self.app.setup_shortcuts(); self.app.apply_theme(); self.accept()


class HomePage(QWidget):
    newProject=Signal(); openProject=Signal(str)
    def __init__(self,app):
        super().__init__(); self.app=app; root=QVBoxLayout(self); root.setContentsMargins(50,35,50,35)
        top=QHBoxLayout(); logo=QLabel(); path=Path(__file__).with_name("MakeToons_logo_full.png")
        if path.exists(): logo.setPixmap(QPixmap(str(path)).scaled(620,120,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else: logo.setText("MAKETOONS")
        top.addWidget(logo); top.addStretch(); s=QPushButton("⚙ Settings"); s.clicked.connect(app.open_settings); top.addWidget(s); root.addLayout(top)
        title=QLabel("My Projects"); title.setStyleSheet("font-size:25px;font-weight:bold;margin-top:18px;"); root.addWidget(title)
        self.projects=QListWidget(); self.projects.setViewMode(QListWidget.IconMode); self.projects.setResizeMode(QListWidget.Adjust); self.projects.setSpacing(16); self.projects.itemDoubleClicked.connect(lambda item:self.openProject.emit(item.data(Qt.UserRole))); root.addWidget(self.projects,1)
        buttons=QHBoxLayout(); n=QPushButton("+ New Project"); n.setMinimumHeight(45); n.clicked.connect(self.newProject.emit); o=QPushButton("Open Project"); o.clicked.connect(self.open_file); buttons.addWidget(n); buttons.addWidget(o); root.addLayout(buttons); self.refresh()
    def open_file(self):
        p,_=QFileDialog.getOpenFileName(self,"Open MakeToons Project","","MakeToons Project (*.maketoon)")
        if p:self.openProject.emit(p)
    def refresh(self):
        self.projects.clear(); PROJECT_DIR.mkdir(exist_ok=True)
        for p in sorted(PROJECT_DIR.glob("*.maketoon"),key=lambda x:x.stat().st_mtime,reverse=True):
            i=QListWidgetItem(p.stem); i.setData(Qt.UserRole,str(p)); self.projects.addItem(i)


class MakeToons(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(f"{APP} {VERSION}"); self.resize(1550,950)
        self.canvas_w=DEFAULT_W; self.canvas_h=DEFAULT_H; self.frames=DEFAULT_FRAMES; self.frame=0; self.frame_duration=.10; self.playing=False; self.dirty=False; self.project_path=None
        self.onion=True; self.prev_onion=2; self.next_onion=2; self.onion_prev_color=QColor("#ff5b7f"); self.onion_next_color=QColor("#4dc9ff")
        self.bg_mode="Dark Transparent Checker"; self.bg_color=QColor("#ffffff"); self.accent=QColor("#713cff")
        self.program_bg_mode="Solid Color"; self.program_bg_color=QColor("#0b1018"); self.program_bg_path=""
        self.cursor_style="Circle"; self.selection_color=QColor("#2589ff"); self.selection_opacity=.25; self.outline_color=QColor("#ffffff"); self.outline_size=2; self.text_bg_color=QColor("#000000"); self.text_bg_opacity=1.0
        self.shortcuts={"pencil":"B","eraser":"E","picker":"I","bucket":"G","lasso":"L","magic":"W","text":"T","play":"Space","save":"Ctrl+S","undo":"Ctrl+Z","redo":"Ctrl+Y","copy":"Ctrl+C","cut":"Ctrl+X","paste":"Ctrl+V"}
        self.undo_stack=[]; self.redo_stack=[]; self.clipboard_image=None
        self.selection_path=None; self.selection_points=[]; self.selection_mask=None
        self.load_settings()
        self.layers=[Layer("Character",self.canvas_w,self.canvas_h,self.frames),Layer("Sketch",self.canvas_w,self.canvas_h,self.frames),Layer("Background",self.canvas_w,self.canvas_h,self.frames,True)]
        self.stack=QStackedWidget(); self.setCentralWidget(self.stack)
        self.home=HomePage(self); self.home.newProject.connect(self.new_project); self.home.openProject.connect(self.load_project_path); self.stack.addWidget(self.home)
        self.tool_settings={"pencil":{"size":12,"opacity":100},"eraser":{"size":20,"opacity":100}}
        self.build_editor()
        self.timer=QTimer(self); self.timer.timeout.connect(self.play_step); self.update_timer_interval(); self.setup_shortcuts(); self.apply_theme()

    def toggle_fullscreen(self):
        if self.isFullScreen(): self.showNormal()
        else: self.showFullScreen()

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def build_editor(self):
        root = QWidget()
        main = QVBoxLayout(root)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(7)

        # Header
        header = QHBoxLayout()
        header.setSpacing(5)

        home = QToolButton()
        home.setText("←")
        home.setToolTip("Projects")
        home.setFixedSize(38, 34)
        home.clicked.connect(self.go_home)
        header.addWidget(home)

        logo = QLabel("MAKETOONS")
        logo.setStyleSheet("font-size:20px;font-weight:800;letter-spacing:3px;padding-left:5px;")
        header.addWidget(logo)
        header.addStretch()

        for symbol, tip, fn in [
            ("↶", "Undo", self.undo),
            ("↷", "Redo", self.redo),
            ("▣", "Copy", self.copy_selection),
            ("✂", "Cut", self.cut_selection),
            ("▤", "Paste", self.paste_selection),
        ]:
            b = QToolButton()
            b.setText(symbol)
            b.setToolTip(tip)
            b.setFixedSize(36, 32)
            b.clicked.connect(fn)
            header.addWidget(b)

        header.addSpacing(10)

        settings = QToolButton()
        settings.setText("⚙")
        settings.setToolTip("Settings")
        settings.setFixedSize(38, 34)
        settings.clicked.connect(self.open_settings)
        fullscreen_btn=QToolButton(); fullscreen_btn.setText("⛶"); fullscreen_btn.setToolTip("Toggle Fullscreen"); fullscreen_btn.setFixedSize(38,34); fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        header.addWidget(fullscreen_btn)
        header.addWidget(settings)

        save = QToolButton()
        save.setText("▣")
        save.setToolTip("Save Project")
        save.setFixedSize(38, 34)
        save.clicked.connect(self.save_project)
        header.addWidget(save)

        main.addLayout(header)

        # Main three-column editor.
        outer = QSplitter(Qt.Horizontal)
        outer.setChildrenCollapsible(False)

        # LEFT: compact icon-only tool rail.
        left = QWidget()
        left.setMinimumWidth(66)
        left.setMaximumWidth(76)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(3, 3, 3, 3)
        ll.setSpacing(6)

        self.tool_buttons = {}
        tool_defs = [
            ("pencil", "Pencil"),
            ("eraser", "Eraser"),
            ("picker", "Color Picker"),
            ("bucket", "Bucket"),
            ("lasso", "Lasso"),
            ("magic", "Magic Wand"),
            ("text", "Text"),
        ]

        for key, name in tool_defs:
            b = QToolButton()
            b.setToolTip(name)
            b.setAccessibleName(name)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setFixedSize(52, 46)
            b.setIconSize(QSize(28, 28))
            b.clicked.connect(lambda checked, k=key: self.set_tool(k))
            self.tool_buttons[key] = b
            ll.addWidget(b, 0, Qt.AlignHCenter)

        ll.addStretch()

        label = QLabel("TOOLS")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size:9px;color:#7f8da3;font-weight:700;")
        ll.addWidget(label)

        self.update_tool_icons()
        outer.addWidget(left)

        # CENTER: canvas on top, timeline below.
        center = QSplitter(Qt.Vertical)
        center.setChildrenCollapsible(False)

        canvas_panel = QWidget()
        cp = QVBoxLayout(canvas_panel)
        cp.setContentsMargins(0, 0, 0, 0)
        cp.setSpacing(5)

        canvas_top = QHBoxLayout()
        canvas_top.addWidget(QLabel("Canvas"))
        canvas_top.addStretch()

        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(48)

        minus = QToolButton()
        minus.setText("−")
        minus.setToolTip("Zoom Out")
        plus = QToolButton()
        plus.setText("+")
        plus.setToolTip("Zoom In")
        fit = QToolButton()
        fit.setText("Fit")
        fit.setToolTip("Fit Canvas")

        minus.clicked.connect(lambda: self.set_zoom(self.canvas.zoom / 1.15))
        plus.clicked.connect(lambda: self.set_zoom(self.canvas.zoom * 1.15))
        fit.clicked.connect(self.fit_canvas)

        canvas_top.addWidget(minus)
        canvas_top.addWidget(self.zoom_label)
        canvas_top.addWidget(plus)
        canvas_top.addWidget(fit)
        cp.addLayout(canvas_top)

        # Canvas must exist before rebuilding tool options.
        self.canvas = Canvas(self)
        cp.addWidget(self.canvas, 1)

        center.addWidget(canvas_panel)

        self.timeline = Timeline(self)
        center.addWidget(self.timeline)
        center.setSizes([560, 300])

        outer.addWidget(center)

        # RIGHT: dynamic tool options + layer/frame properties.
        right = QWidget()
        right.setMinimumWidth(235)
        right.setMaximumWidth(300)
        rr = QVBoxLayout(right)
        rr.setContentsMargins(3, 0, 3, 0)
        rr.setSpacing(7)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        tool_page = QWidget()
        tr = QVBoxLayout(tool_page)
        tr.setContentsMargins(8, 8, 8, 8)

        self.tool_options = QGroupBox("Tool")
        self.options_layout = QVBoxLayout(self.tool_options)
        self.options_layout.setSpacing(7)
        tr.addWidget(self.tool_options)

        selection = QGroupBox("Selection")
        sg = QGridLayout(selection)
        selection_defs = [
            ("Clear Inside", self.clear_selected),
            ("Clear Outside", self.clear_outside),
            ("Move", self.start_move_selection),
            ("Invert", self.invert_selection),
            ("Copy", self.copy_selection),
            ("Cut", self.cut_selection),
            ("Paste", self.paste_selection),
        ]
        for i, (label_text, fn) in enumerate(selection_defs):
            b = QPushButton(label_text)
            b.clicked.connect(fn)
            sg.addWidget(b, i // 2, i % 2)

        tr.addWidget(selection)
        tr.addStretch()
        tabs.addTab(tool_page, "Tool")

        layer_page = QWidget()
        lr = QVBoxLayout(layer_page)
        lr.setContentsMargins(8, 8, 8, 8)

        layer_box = QGroupBox("Layer")
        lg = QVBoxLayout(layer_box)

        self.layer_name = QLabel()
        self.layer_name.setStyleSheet("font-size:14px;font-weight:700;padding:4px;")
        lg.addWidget(self.layer_name)

        self.visible = QCheckBox("Visible")
        self.lock = QCheckBox("Locked")
        self.visible.toggled.connect(self.toggle_visible)
        self.lock.toggled.connect(self.toggle_lock)
        lg.addWidget(self.visible)
        lg.addWidget(self.lock)

        rename = QPushButton("Rename Layer")
        rename.clicked.connect(self.rename_layer)
        delete = QPushButton("Delete Layer")
        delete.clicked.connect(self.delete_layer)
        lg.addWidget(rename)
        lg.addWidget(delete)

        lr.addWidget(layer_box)

        frame_box = QGroupBox("Frame")
        fg = QVBoxLayout(frame_box)
        self.frame_info = QLabel()
        self.frame_info.setWordWrap(True)
        fg.addWidget(self.frame_info)

        clear = QPushButton("Clear Frame")
        clear.clicked.connect(self.clear_frame)
        save_frame = QPushButton("Save Frame PNG")
        save_frame.clicked.connect(self.save_frame_png)
        save_layer = QPushButton("Save Layer PNG")
        save_layer.clicked.connect(self.save_layer_png)

        fg.addWidget(clear)
        fg.addWidget(save_frame)
        fg.addWidget(save_layer)

        lr.addWidget(frame_box)
        lr.addStretch()
        tabs.addTab(layer_page, "Layer")

        rr.addWidget(tabs, 1)
        outer.addWidget(right)

        outer.setSizes([72, 1050, 270])
        main.addWidget(outer, 1)

        self.editor = root
        self.stack.addWidget(root)

        self.refresh_layers()
        self.color_preview()
        self.set_tool("pencil")
    def _tool_svg(self, kind, color):
        c=color
        common=f'fill="none" stroke="{c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"'
        svgs={
            "pencil":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="M6 24.5 21.8 8.7l3.5 3.5L9.5 28H6z"/><path {common} d="m20.3 10.2 2.2-2.2a2.1 2.1 0 0 1 3 0l1.5 1.5a2.1 2.1 0 0 1 0 3L24.8 14"/><path {common} d="M6 24.5 4.5 29.5 9.5 28"/></svg>',
            "eraser":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="m6 21 11.8-12a3 3 0 0 1 4.3 0l3 3a3 3 0 0 1 0 4.3L15.5 26H9z"/><path {common} d="M14 13 22 21"/><path {common} d="M19 26h7"/></svg>',
            "picker":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="m8 24 12.7-12.7"/><path {common} d="m18 7 7 7"/><path {common} d="m20.5 4.5 7 7-2.2 2.2-7-7z"/><path {common} d="m7 25 3.2-1.2L8.2 22z"/></svg>',
            "bucket":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="m9 7 11 11a3.5 3.5 0 0 1 0 5l-1 1a3.5 3.5 0 0 1-5 0L7 17a3.5 3.5 0 0 1 0-5z"/><path {common} d="m9 7 4-4 7 7-4 4"/><path {common} d="M21 24c3.5 0 5.5-1.5 6.5-4"/></svg>',
            "lasso":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="M24.5 8.5c4 3.5 2.5 9.5-2.5 13.5-5.5 4.5-13.5 5.5-17 1.5-3-3.5-.5-8.5 4-11.5 5-3.2 11.5-3.5 15.5-.5"/><path {common} d="M6 23c-1.8 1.5-2 3.7-.5 4.8 1.4 1 3.8.5 5.2-1"/></svg>',
            "magic":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="m8 24 11.5-11.5 4 4L12 28H8z"/><path {common} d="M21 5v5M18.5 7.5h5M26 13v4M24 15h4M12 6v3M10.5 7.5h3"/></svg>',
            "text":f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path {common} d="M7 7h18M16 7v19M11 26h10"/></svg>'
        }
        return svgs[kind]

    def _icon_from_svg(self, svg):
        renderer=QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pix=QPixmap(32,32); pix.fill(Qt.transparent)
        painter=QPainter(pix); renderer.render(painter); painter.end()
        return QIcon(pix)

    def update_tool_icons(self):
        if not hasattr(self, "tool_buttons"): return
        emojis={"pencil":"✏️","eraser":"🧽","picker":"🎨","bucket":"🪣","lasso":"⭕","magic":"🪄","text":"🔤"}
        for key,button in self.tool_buttons.items():
            button.setIcon(QIcon()); button.setText(emojis.get(key,"•")); button.setStyleSheet("font-size:22px;")

    def clear_tool_options(self):
        while self.options_layout.count():
            it=self.options_layout.takeAt(0)
            if it.widget(): it.widget().deleteLater()

    def add_number_with_nudge(self,parent,label,initial,minimum,maximum,step=1):
        row=QHBoxLayout(); row.addWidget(QLabel(label)); minus=QToolButton(); minus.setText("−"); box=QSpinBox(); box.setRange(minimum,maximum); box.setValue(initial); box.setFixedWidth(68); plus=QToolButton(); plus.setText("+")
        minus.clicked.connect(lambda: box.setValue(max(minimum,box.value()-step))); plus.clicked.connect(lambda: box.setValue(min(maximum,box.value()+step)))
        row.addWidget(minus); row.addWidget(box); row.addWidget(plus); parent.addLayout(row); return box

    def rebuild_tool_options(self):
        if not hasattr(self,"options_layout"): return
        self.clear_tool_options(); t=self.canvas.tool
        if t in ("pencil","eraser"):
            title="Pencil" if t=="pencil" else "Eraser"; self.options_layout.parentWidget().setTitle(title)
            state=self.tool_settings[t]
            self.tool_size_box=self.add_number_with_nudge(self.options_layout,"Size",state["size"],1,200)
            self.tool_size_box.valueChanged.connect(lambda v:self._tool_value("size",v))
            self.tool_opacity_box=self.add_number_with_nudge(self.options_layout,"Opacity %",state["opacity"],1,100)
            self.tool_opacity_box.valueChanged.connect(lambda v:self._tool_value("opacity",v))
            if t=="pencil":
                b=QToolButton(); b.setText("◉ Color"); b.clicked.connect(self.choose_color); self.options_layout.addWidget(b)
            self.options_layout.addWidget(QLabel("Settings are saved separately for Pencil and Eraser."))
        elif t=="picker":
            self.options_layout.parentWidget().setTitle("Color Picker"); self.options_layout.addWidget(QLabel("Click a pixel to pick its color."))
        elif t=="bucket":
            self.options_layout.parentWidget().setTitle("Bucket"); box=self.add_number_with_nudge(self.options_layout,"Opacity %",int(self.canvas.opacity*100),1,100); box.valueChanged.connect(lambda v:setattr(self.canvas,"opacity",v/100)); self.options_layout.addWidget(QLabel("Respects visible outlines above the active layer."))
        elif t in ("lasso","magic"):
            self.options_layout.parentWidget().setTitle("Selection Tool")
            for text,fn in [("Clear Inside",self.clear_selected),("Clear Outside",self.clear_outside),("Move",self.start_move_selection),("Invert",self.invert_selection),("Copy",self.copy_selection),("Cut",self.cut_selection),("Paste",self.paste_selection)]:
                b=QToolButton(); b.setText(text); b.clicked.connect(fn); self.options_layout.addWidget(b)
        elif t=="text":
            self.options_layout.parentWidget().setTitle("Text"); self.text_edit=QLineEdit("Text"); self.options_layout.addWidget(self.text_edit)
            self.text_size_box=self.add_number_with_nudge(self.options_layout,"Size",32,6,200)
            self.text_color=QToolButton(); self.text_color.setText("Text Color"); self.text_color.clicked.connect(self.choose_text_color); self.options_layout.addWidget(self.text_color)
            self.text_bg=QCheckBox("Background"); self.options_layout.addWidget(self.text_bg)
            self.text_bg_color=QToolButton(); self.text_bg_color.setText("Background Color"); self.text_bg_color.clicked.connect(self.choose_text_bg_color); self.options_layout.addWidget(self.text_bg_color)
            self.text_bg_opacity_box=self.add_number_with_nudge(self.options_layout,"Background %",100,1,100); self.text_bg_opacity_box.valueChanged.connect(lambda v:setattr(self,"text_bg_opacity",v/100))
        self.color_preview()

    def _tool_value(self,key,value):
        self.tool_settings[self.canvas.tool][key]=value
        if key=="size": self.canvas.size=value; self.canvas.set_tool_cursor()
        elif key=="opacity": self.canvas.opacity=value/100

    def set_tool(self,tool):
        if not hasattr(self,"tool_settings"): self.tool_settings={"pencil":{"size":12,"opacity":100},"eraser":{"size":20,"opacity":100}}
        if hasattr(self,"canvas") and self.canvas.tool in self.tool_settings:
            self.tool_settings[self.canvas.tool]["size"]=self.canvas.size; self.tool_settings[self.canvas.tool]["opacity"]=int(self.canvas.opacity*100)
        self.canvas.tool=tool
        if tool in self.tool_settings:
            self.canvas.size=self.tool_settings[tool]["size"]; self.canvas.opacity=self.tool_settings[tool]["opacity"]/100
        self.rebuild_tool_options(); self.canvas.set_tool_cursor(); self.statusBar().showMessage("Tool: "+tool.title(),1500)

    def choose_color(self):
        d=ColorDialog(self,self.canvas.color)
        if d.exec()==QDialog.Accepted: self.canvas.color=d.result_color; self.color_preview()
    def choose_text_color(self): self.choose_color()
    def choose_text_bg_color(self):
        c=QColorDialog.getColor(self.text_bg_color,self,"Text Background Color")
        if c.isValid(): self.text_bg_color=c
    def color_preview(self):
        if hasattr(self,"color_btn"):
            self.color_btn.setStyleSheet(f"background:{self.canvas.color.name()};color:{'#000' if self.canvas.color.lightness()>160 else '#fff'};border-radius:12px;padding:6px;")
        if hasattr(self,"preview"): self.preview.setStyleSheet(f"background:{self.canvas.color.name()};")
    def layer(self):
        i=getattr(self,"_selected_layer_index",self.list.currentRow() if hasattr(self,"list") else 0)
        return self.layers[i] if 0<=i<len(self.layers) else None
    def select_layer_obj(self,layer):
        if layer in self.layers:
            self._selected_layer_index=self.layers.index(layer); self.update_layer_info(); self.timeline.rebuild(); self.canvas.update()
    def select_timeline_cell(self,layer,frame):
        self.select_layer_obj(layer); self.set_frame(frame)
    def refresh_layers(self):
        self._selected_layer_index=max(0,min(getattr(self,"_selected_layer_index",0),len(self.layers)-1)) if self.layers else 0
        self.update_layer_info(); self.timeline.rebuild(); self.canvas.update()
    def update_layer_info(self):
        if not hasattr(self,"layer_name"): return
        x=self.layer(); self.layer_name.setText(x.name if x else ""); self.visible.blockSignals(True); self.lock.blockSignals(True); self.visible.setChecked(bool(x and x.visible)); self.lock.setChecked(bool(x and x.locked)); self.visible.blockSignals(False); self.lock.blockSignals(False); self.frame_info.setText(f"Frame {self.frame+1} / {self.frames}\nLayer: {x.name if x else 'None'}")
    def add_layer(self):
        name,ok=QInputDialog.getText(self,"New Layer","Layer name:",text="New Layer")
        if ok and name.strip(): self.layers.insert(0,Layer(name.strip(),self.canvas_w,self.canvas_h,self.frames)); self._selected_layer_index=0; self.refresh_layers(); self.dirty=True
    def delete_layer(self):
        x=self.layer()
        if not x or x.background: QMessageBox.information(self,APP,"The Background layer cannot be deleted."); return
        if len(self.layers)<=1:return
        if QMessageBox.question(self,"Delete Layer",f'Delete "{x.name}"?',QMessageBox.Yes|QMessageBox.No)==QMessageBox.Yes:
            self.layers.pop(self._selected_layer_index); self._selected_layer_index=max(0,self._selected_layer_index-1); self.refresh_layers(); self.dirty=True
    def rename_layer(self):
        x=self.layer()
        if not x:return
        name,ok=QInputDialog.getText(self,"Rename Layer","New name:",text=x.name)
        if ok and name.strip():x.name=name.strip();self.refresh_layers();self.dirty=True
    def toggle_visible(self,v):
        x=self.layer()
        if x:x.visible=v;self.canvas.update()
    def toggle_lock(self,v):
        x=self.layer()
        if x:x.locked=v;self.timeline.rebuild()
    def move_layer(self,delta):
        i=self._selected_layer_index;j=i+delta
        if not(0<=i<len(self.layers) and 0<=j<len(self.layers)):return
        if self.layers[i].background or self.layers[j].background:return
        self.layers[i],self.layers[j]=self.layers[j],self.layers[i];self._selected_layer_index=j;self.refresh_layers();self.dirty=True
    def move_layer_obj(self, layer, delta):
        if layer not in self.layers:
            return
        i=self.layers.index(layer); j=i+delta
        if not (0 <= j < len(self.layers)):
            return
        if self.layers[i].background or self.layers[j].background:
            return
        self.layers[i],self.layers[j]=self.layers[j],self.layers[i]
        self._selected_layer_index=j
        self.refresh_layers()
        self.dirty=True

    def set_frame(self,index):
        self.frame=max(0,min(index,self.frames-1)); self.update_layer_info(); self.timeline.update_label(); self.canvas.update()
    def has_pixels_fast(self,img):
        # Small sample; actual drawing remains on the full image.
        step_y=max(32,self.canvas_h//16); step_x=max(32,self.canvas_w//16)
        for y in range(0,self.canvas_h,step_y):
            for x in range(0,self.canvas_w,step_x):
                if img.pixelColor(x,y).alpha()>10:return True
        return False
    def add_frame(self):
        at=self.frame+1
        for l in self.layers:
            l.frames.insert(at,blank(self.canvas_w,self.canvas_h) if not l.background else l.image_at(self.frame).copy()); l.exposure.insert(at,at)
        self.frames+=1; self.frame=at; self.timeline.rebuild(); self.canvas.update(); self.dirty=True
    def duplicate_frame(self):
        at=self.frame+1
        for l in self.layers:l.frames.insert(at,l.image_at(self.frame).copy()); l.exposure.insert(at,at)
        self.frames+=1;self.frame=at;self.timeline.rebuild();self.canvas.update();self.dirty=True
    def delete_frame(self):
        if self.frames<=1:return
        for l in self.layers: del l.frames[self.frame]; del l.exposure[self.frame]
        self.frames-=1;self.frame=min(self.frame,self.frames-1);self.timeline.rebuild();self.canvas.update();self.dirty=True
    def extend_frame(self):
        l=self.layer()
        if not l:return
        src=self.frame
        if src>=self.frames-1:return
        # Make following frames display this drawing until the next existing keyframe.
        for f in range(src+1,self.frames):
            if l.exposure[f]==f and self.has_pixels_fast(l.frames[f]): break
            l.exposure[f]=src
        self.timeline.rebuild();self.canvas.update();self.dirty=True
    def clear_frame(self):
        l=self.layer()
        if l and not l.locked:self.begin_undo();l.frames[self.frame].fill(Qt.transparent);l.exposure[self.frame]=self.frame;self.timeline.rebuild();self.canvas.update();self.dirty=True
    def drawing_composite(self,frame=None):
        f=self.frame if frame is None else frame; out=blank(self.canvas_w,self.canvas_h); p=QPainter(out)
        for l in reversed(self.layers):
            if l.visible and not l.background:p.drawImage(0,0,l.image_at(f))
        p.end(); return out
    def composite(self,frame=None):
        f=self.frame if frame is None else frame; out=blank(self.canvas_w,self.canvas_h); p=QPainter(out)
        for l in reversed(self.layers):
            if l.visible:p.drawImage(0,0,l.image_at(f))
        p.end(); return out
    def tinted_composite(self,img,color):
        out=blank(self.canvas_w,self.canvas_h); p=QPainter(out); p.drawImage(0,0,img); p.setCompositionMode(QPainter.CompositionMode_SourceIn); p.fillRect(out.rect(),color); p.end(); return out
    def paint_background(self,p,r):
        if self.bg_mode=="Solid Color":p.fillRect(r,self.bg_color);return
        c1,c2=(QColor("#eeeeee"),QColor("#ffffff")) if self.bg_mode=="Light Transparent Checker" else (QColor("#252525"),QColor("#111111")); cell=max(8,int(18*min(1.5,self.canvas.zoom)))
        for y in range(r.top(),r.bottom(),cell):
            for x in range(r.left(),r.right(),cell):p.fillRect(QRect(x,y,cell,cell),c1 if ((x//cell+y//cell)%2==0) else c2)
    def bucket_fill(self,start):
        l=self.layer()
        if not l or l.locked:return
        w,h=self.canvas_w,self.canvas_h; img=l.frames[self.frame]; idx=self.layers.index(l)
        barrier=QImage(w,h,QImage.Format_Alpha8);barrier.fill(0);bp=QPainter(barrier)
        for upper in reversed(self.layers[:idx]):
            if upper.visible:bp.drawImage(0,0,upper.image_at(self.frame))
        bp.end()
        target_alpha=img.pixelColor(start).alpha()
        target_color=img.pixelColor(start)
        tol=10
        def passable(x,y):
            if x<0 or y<0 or x>=w or y>=h:return False
            if barrier.pixelColor(x,y).value()>25:return False
            c=img.pixelColor(x,y)
            return c.alpha()<=20 if target_alpha<=20 else (abs(c.red()-target_color.red())<tol and abs(c.green()-target_color.green())<tol and abs(c.blue()-target_color.blue())<tol)
        q=deque([(start.x(),start.y())]);seen=set(q)
        while q:
            x,y=q.popleft()
            for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if (nx,ny) not in seen and passable(nx,ny):seen.add((nx,ny));q.append((nx,ny))
        if not seen:return
        self.begin_undo(); painter=QPainter(img); c=QColor(self.canvas.color); c.setAlphaF(self.canvas.opacity);painter.setPen(Qt.NoPen);painter.setBrush(c)
        rows={}
        for x,y in seen:rows.setdefault(y,[]).append(x)
        for y,xs in rows.items():
            xs.sort(); sx=px=xs[0]
            for x in xs[1:]:
                if x!=px+1:painter.drawRect(sx,y,px-sx+1,1);sx=x
                px=x
            painter.drawRect(sx,y,px-sx+1,1)
        painter.end();l.exposure[self.frame]=self.frame;self.dirty=True;self.canvas.update();self.timeline.update_cells()
    def magic_wand(self,start):
        # Selection version of bucket: select the connected region instead of filling it.
        l=self.layer()
        if not l:return
        img=l.image_at(self.frame); w,h=self.canvas_w,self.canvas_h; target=img.pixelColor(start); target_alpha=target.alpha(); tol=10
        def same(x,y):
            c=img.pixelColor(x,y)
            if target_alpha<=20:return c.alpha()<=20
            return c.alpha()>20 and abs(c.red()-target.red())<tol and abs(c.green()-target.green())<tol and abs(c.blue()-target.blue())<tol
        q=deque([(start.x(),start.y())]);seen=set(q)
        while q:
            x,y=q.popleft()
            for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if 0<=nx<w and 0<=ny<h and (nx,ny) not in seen and same(nx,ny):seen.add((nx,ny));q.append((nx,ny))
        mask=QImage(w,h,QImage.Format_Alpha8);mask.fill(0);mp=QPainter(mask);mp.setPen(Qt.white)
        for x,y in seen:mp.drawPoint(x,y)
        mp.end();self.selection_mask=mask
        path=QPainterPath()
        # bounding outline for visual selection
        xs=[x for x,y in seen]; ys=[y for x,y in seen]
        if xs:path.addRect(min(xs),min(ys),max(xs)-min(xs)+1,max(ys)-min(ys)+1)
        self.selection_path=path;self.selection_points=[];self.selection_label_update();self.canvas.update()
    def make_selection(self,points):
        if len(points)<3:return
        path=QPainterPath();path.moveTo(points[0])
        for pt in points[1:]:path.lineTo(pt)
        path.closeSubpath();self.selection_path=path;self.selection_points=list(points);self.selection_mask=QImage(self.canvas_w,self.canvas_h,QImage.Format_Alpha8);self.selection_mask.fill(0);mp=QPainter(self.selection_mask);mp.setClipPath(path);mp.fillRect(self.selection_mask.rect(),Qt.white);mp.end();self.selection_label_update();self.canvas.update()
    def selection_label_update(self):
        if hasattr(self,"selection_label"):self.selection_label.setText("Selection active")
    def clear_selection(self):
        self.selection_path=None;self.selection_points=[];self.selection_mask=None;self.canvas.lasso_points=[];self.canvas.update()
    def selected_rect(self):
        if self.selection_path and not self.selection_path.isEmpty():return self.selection_path.boundingRect().toRect()
        return None
    def clear_selected(self):
        l=self.layer()
        if not l or l.locked or not self.selection_path:return
        self.begin_undo();img=l.frames[self.frame];p=QPainter(img);p.setCompositionMode(QPainter.CompositionMode_Clear);p.setClipPath(self.selection_path);p.fillRect(img.rect(),Qt.transparent);p.end();l.exposure[self.frame]=self.frame;self.dirty=True;self.canvas.update()
    def clear_outside(self):
        l=self.layer()
        if not l or l.locked or not self.selection_path:return
        self.begin_undo();img=l.frames[self.frame];kept=blank(self.canvas_w,self.canvas_h);kp=QPainter(kept)
        if self.selection_mask is not None:
            kp.setCompositionMode(QPainter.CompositionMode_Source)
            kp.drawImage(0,0,img)
            kp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            kp.drawImage(0,0,self.selection_mask)
        else:
            kp.setClipPath(self.selection_path);kp.drawImage(0,0,img)
        kp.end();l.frames[self.frame]=kept;l.exposure[self.frame]=self.frame;self.dirty=True;self.canvas.update()
    def invert_selection(self):
        if not self.selection_path:
            return
        # Keep an explicit inverted mask; drawing operations use the mask.
        mask = QImage(self.canvas_w, self.canvas_h, QImage.Format_Alpha8)
        mask.fill(255)
        p = QPainter(mask)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setClipPath(self.selection_path)
        p.fillRect(mask.rect(), Qt.transparent)
        p.end()
        self.selection_mask = mask
        self.canvas.update()
    def start_move_selection(self):
        if not self.selection_path:return
        self.canvas.statusTip="Drag selection with the Move tool is planned; use arrow keys for 1px movement."
        self.canvas.tool="select_move";self.statusBar().showMessage("Selection move mode: arrow keys move selected pixels.")
    def move_selection_pixels(self,dx,dy,record_undo=True):
        l=self.layer()
        if not l or not self.selection_path:return
        rect=self.selected_rect()
        if not rect:return
        if record_undo:
            self.begin_undo()
        img=l.frames[self.frame];patch=blank(rect.width(),rect.height());pp=QPainter(patch);pp.setClipPath(self.selection_path.translated(-rect.x(),-rect.y()));pp.drawImage(-rect.x(),-rect.y(),img);pp.end()
        cp=QPainter(img);cp.setCompositionMode(QPainter.CompositionMode_Clear);cp.setClipPath(self.selection_path);cp.fillRect(img.rect(),Qt.transparent);cp.end()
        np=self.selection_path.translated(dx,dy);cp=QPainter(img);cp.drawImage(rect.x()+dx,rect.y()+dy,patch);cp.end();self.selection_path=np;self.selection_points=[pt+QPoint(dx,dy) for pt in self.selection_points];self.dirty=True;self.canvas.update()
    def copy_selection(self):
        l=self.layer()
        if not l:return
        img=l.image_at(self.frame);rect=self.selected_rect()
        if rect:
            self.clipboard_image=img.copy(rect)
            QApplication.clipboard().setImage(self.clipboard_image)
            self.statusBar().showMessage("Selection copied.",1200)
    def cut_selection(self):
        self.copy_selection();self.clear_selected()
    def paste_selection(self):
        if self.clipboard_image is None:
            clip = QApplication.clipboard().image()
            if not clip.isNull():
                self.clipboard_image = clip
        if self.clipboard_image is None:return
        l=self.layer()
        if not l or l.locked:return
        self.begin_undo();p=QPainter(l.frames[self.frame]);pos=QPoint((self.canvas_w-self.clipboard_image.width())//2,(self.canvas_h-self.clipboard_image.height())//2);p.drawImage(pos,self.clipboard_image);p.end();l.exposure[self.frame]=self.frame;self.dirty=True;self.canvas.update()
    def add_text_at(self,pos):
        if not hasattr(self,"text_edit"):return
        l=self.layer()
        if not l or l.locked:return
        text=self.text_edit.text()
        if not text:return
        self.begin_undo();img=l.frames[self.frame];p=QPainter(img);font=QFont("Segoe UI",self.text_size_box.value());p.setFont(font)
        fm=p.fontMetrics(); rect=fm.boundingRect(text); rect.moveTopLeft(pos+QPoint(0,-fm.ascent()))
        if getattr(self,"text_bg",None) and self.text_bg.isChecked():
            bc=QColor(self.text_bg_color); bc.setAlphaF(self.text_bg_opacity); p.fillRect(rect.adjusted(-6,-4,6,4),bc)
        c=QColor(self.canvas.color);c.setAlphaF(self.canvas.opacity)
        p.setPen(QPen(self.outline_color,self.outline_size));p.drawText(pos.x(),pos.y(),text)
        p.setPen(c);p.drawText(pos.x(),pos.y(),text)
        p.end();l.exposure[self.frame]=self.frame;self.dirty=True;self.canvas.update()
    def begin_undo(self):
        # Snapshot only once per event; drawing is grouped by short timer.
        self.undo_stack.append(self.snapshot()); self.undo_stack=self.undo_stack[-30:]; self.redo_stack.clear()
    def snapshot(self):
        return {"layers":[{"name":l.name,"visible":l.visible,"locked":l.locked,"background":l.background,"frames":[x.copy() for x in l.frames],"exposure":list(l.exposure)} for l in self.layers],"frame":self.frame}
    def restore_snapshot(self,s):
        self.layers=[]
        for z in s["layers"]:
            l=Layer(z["name"],self.canvas_w,self.canvas_h,self.frames,z["background"]);l.visible=z["visible"];l.locked=z["locked"];l.frames=[x.copy() for x in z["frames"]];l.exposure=list(z.get("exposure",range(self.frames)));self.layers.append(l)
        self.frame=s["frame"];self.refresh_layers();self.canvas.update();self.dirty=True
    def undo(self):
        if not self.undo_stack:return
        self.redo_stack.append(self.snapshot());self.restore_snapshot(self.undo_stack.pop())
    def redo(self):
        if not self.redo_stack:return
        self.undo_stack.append(self.snapshot());self.restore_snapshot(self.redo_stack.pop())
    def save_frame_png(self):
        d=ExportDialog(self,"Save Frame as PNG")
        if d.exec()!=QDialog.Accepted:return
        path,_=QFileDialog.getSaveFileName(self,"Save Frame PNG",f"frame_{self.frame+1:04d}.png","PNG Image (*.png)")
        if not path:return
        img=self.composite()
        if not d.transparent:
            bg=QImage(self.canvas_w,self.canvas_h,QImage.Format_RGB32);bg.fill(self.bg_color);p=QPainter(bg);p.drawImage(0,0,img);p.end();img=bg
        img.save(path,"PNG")
    def save_layer_png(self):
        l=self.layer()
        if l:
            path,_=QFileDialog.getSaveFileName(self,"Save Selected Layer as Transparent PNG",f"{l.name}_frame_{self.frame+1:04d}.png","PNG Image (*.png)")
            if path:l.image_at(self.frame).save(path,"PNG")
    def set_zoom(self,z):self.canvas.zoom=max(.1,min(8.,z));self.update_zoom_label();self.canvas.update()
    def update_zoom_label(self):
        if hasattr(self,"zoom_label"):self.zoom_label.setText(f"{int(self.canvas.zoom*100)}%")
    def fit_canvas(self):
        aw=max(100,self.canvas.width()-30);ah=max(100,self.canvas.height()-30);self.set_zoom(min(aw/self.canvas_w,ah/self.canvas_h));self.canvas.view_offset=QPoint(0,0)
    def set_frame_duration(self,v):
        self.frame_duration=float(v);self.timeline.fps_label.setText(f"{1/self.frame_duration:.2f} FPS");self.update_timer_interval()
    def update_timer_interval(self):
        if hasattr(self,"timer"):self.timer.setInterval(max(10,int(self.frame_duration*1000)))
    def play_step(self):
        self.set_frame((self.frame+1)%self.frames); self.canvas.update()
    def toggle_play(self):
        self.playing=not self.playing
        if self.playing:self.timer.start()
        else:self.timer.stop()
        self.timeline.play_btn.setText("⏸" if self.playing else "▶");self.canvas.update()
    def load_settings(self):
        if not SETTINGS_FILE.exists():return
        try:
            d=json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.shortcuts.update(d.get("shortcuts",{}));self.bg_mode=d.get("bg_mode",self.bg_mode);self.bg_color=QColor(d.get("bg_color",self.bg_color.name()));self.onion_prev_color=QColor(d.get("onion_prev_color",self.onion_prev_color.name()));self.onion_next_color=QColor(d.get("onion_next_color",self.onion_next_color.name()));self.accent=QColor(d.get("accent",self.accent.name()));self.program_bg_mode=d.get("program_bg_mode",self.program_bg_mode);self.program_bg_color=QColor(d.get("program_bg_color",self.program_bg_color.name()));self.program_bg_path=d.get("program_bg_path","");self.cursor_style=d.get("cursor_style",self.cursor_style);self.selection_color=QColor(d.get("selection_color",self.selection_color.name()));self.selection_opacity=float(d.get("selection_opacity",self.selection_opacity));self.outline_color=QColor(d.get("outline_color",self.outline_color.name()));self.outline_size=int(d.get("outline_size",self.outline_size));self.text_bg_color=QColor(d.get("text_bg_color",self.text_bg_color.name()));self.text_bg_opacity=float(d.get("text_bg_opacity",self.text_bg_opacity))
        except Exception:pass
    def save_settings(self):
        SETTINGS_FILE.write_text(json.dumps({"shortcuts":self.shortcuts,"bg_mode":self.bg_mode,"bg_color":self.bg_color.name(),"onion_prev_color":self.onion_prev_color.name(),"onion_next_color":self.onion_next_color.name(),"accent":self.accent.name(),"program_bg_mode":self.program_bg_mode,"program_bg_color":self.program_bg_color.name(),"program_bg_path":self.program_bg_path,"cursor_style":self.cursor_style,"selection_color":self.selection_color.name(),"selection_opacity":self.selection_opacity,"outline_color":self.outline_color.name(),"outline_size":self.outline_size,"text_bg_color":self.text_bg_color.name(),"text_bg_opacity":self.text_bg_opacity},indent=2),encoding="utf-8")
    def program_background(self):
        return self.program_bg_color
    def apply_theme(self):
        a=self.accent.name(); bg=self.program_bg_color.name()
        self.setStyleSheet(f"""
        QWidget{{background:{bg};color:#e8ecf5;font-family:Segoe UI;font-size:13px;}}
        QGroupBox{{border:1px solid #28344a;border-radius:8px;margin-top:10px;padding:8px;font-weight:bold;}}
        QPushButton,QToolButton{{background:#15223a;border:1px solid #2c3b55;border-radius:6px;padding:7px;}}
        QPushButton:hover,QToolButton:hover{{background:#243453;}}
        QToolButton:checked{{background:{a};}}
        QListWidget,QScrollArea{{background:#0f1623;border:1px solid #28344a;border-radius:6px;}}
        QListWidget::item{{padding:9px;}} QListWidget::item:selected{{background:{a};}}
        QSpinBox,QDoubleSpinBox{{background:#121b2b;border:1px solid #30405a;padding:2px;min-width:72px;max-width:90px;}}
        QLineEdit,QComboBox{{background:#121b2b;border:1px solid #30405a;padding:3px;}}
        QSplitter::handle{{background:#33415a;}}
        """)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, self.program_bg_color)
        if self.program_bg_mode == "Picture" and self.program_bg_path:
            pm = QPixmap(self.program_bg_path)
            if not pm.isNull():
                pal.setBrush(QPalette.ColorRole.Window, QBrush(pm))
        elif self.program_bg_mode == "Desktop Background":
            try:
                pm = QApplication.primaryScreen().grabWindow(0)
                if not pm.isNull():
                    pal.setBrush(QPalette.ColorRole.Window, QBrush(pm))
            except Exception:
                pass
        self.setPalette(pal)
        self.update_tool_icons()
        self.canvas.update()
    def setup_shortcuts(self):
        for s in getattr(self,"_shortcuts",[]):s.deleteLater()
        self._shortcuts=[]; actions={"pencil":lambda:self.set_tool("pencil"),"eraser":lambda:self.set_tool("eraser"),"picker":lambda:self.set_tool("picker"),"bucket":lambda:self.set_tool("bucket"),"lasso":lambda:self.set_tool("lasso"),"magic":lambda:self.set_tool("magic"),"text":lambda:self.set_tool("text"),"play":self.toggle_play,"save":self.save_project,"undo":self.undo,"redo":self.redo,"copy":self.copy_selection,"cut":self.cut_selection,"paste":self.paste_selection}
        for k,fn in actions.items():
            seq=self.shortcuts.get(k,"")
            if seq:
                try:s=QShortcut(QKeySequence(seq),self);s.activated.connect(fn);self._shortcuts.append(s)
                except Exception:pass
    def save_project(self):
        PROJECT_DIR.mkdir(exist_ok=True)
        if self.project_path is None:
            path,_=QFileDialog.getSaveFileName(self,"Save MakeToons Project",str(PROJECT_DIR/"My Animation.maketoon"),"MakeToons Project (*.maketoon)")
            if not path:return
            self.project_path=Path(path)
        data={"app":APP,"version":VERSION,"canvas_w":self.canvas_w,"canvas_h":self.canvas_h,"frames":self.frames,"current":self.frame,"frame_duration":self.frame_duration,"layers":[]}
        for l in self.layers:data["layers"].append({"name":l.name,"visible":l.visible,"locked":l.locked,"background":l.background,"frames":[encode(x) for x in l.frames],"exposure":l.exposure})
        self.project_path.write_text(json.dumps(data),encoding="utf-8");self.dirty=False;self.home.refresh();self.statusBar().showMessage(f"Saved: {self.project_path.name}",2500)
    def load_project_path(self,path):
        try:
            d=json.loads(Path(path).read_text(encoding="utf-8"));self.canvas_w=int(d.get("canvas_w",DEFAULT_W));self.canvas_h=int(d.get("canvas_h",DEFAULT_H));self.frames=int(d["frames"]);self.frame=max(0,min(int(d.get("current",0)),self.frames-1));self.frame_duration=float(d.get("frame_duration",.10));self.layers=[]
            for z in d["layers"]:
                l=Layer(z["name"],self.canvas_w,self.canvas_h,self.frames,bool(z.get("background",False)));l.visible=bool(z.get("visible",True));l.locked=bool(z.get("locked",l.background));l.frames=[decode(x) for x in z["frames"]];l.exposure=list(z.get("exposure",range(self.frames)));l.ensure(self.frames);self.layers.append(l)
            self.project_path=Path(path);self.dirty=False;self.timeline.duration.blockSignals(True);self.timeline.duration.setValue(self.frame_duration);self.timeline.duration.blockSignals(False);self.update_timer_interval();self.show_editor()
        except Exception as e:QMessageBox.critical(self,APP,f"Could not open project:\n{e}")
    def show_editor(self):self.stack.setCurrentWidget(self.editor);self.refresh_layers();self.fit_canvas()
    def go_home(self):
        if self.dirty and QMessageBox.question(self,APP,"This project has unsaved changes. Go back anyway?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
        self.playing=False;self.timer.stop();self.home.refresh();self.stack.setCurrentWidget(self.home)
    def new_project(self):
        d=NewProjectDialog(self)
        if d.exec()!=QDialog.Accepted:return
        v=d.values();self.canvas_w=v["w"];self.canvas_h=v["h"];self.frames=v["frames"];self.frame=0;self.frame_duration=v["duration"];self.layers=[Layer("Character",self.canvas_w,self.canvas_h,self.frames),Layer("Sketch",self.canvas_w,self.canvas_h,self.frames),Layer("Background",self.canvas_w,self.canvas_h,self.frames,True)];self.project_path=PROJECT_DIR/(v["name"]+".maketoon");self.dirty=True;self.selection_path=None;self.selection_points=[];self.selection_mask=None;self.timeline.duration.setValue(self.frame_duration);self.show_editor()
    def keyPressEvent(self,e):
        if self.canvas.tool=="select_move" and e.key() in (Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down):
            dx=(1 if e.key()==Qt.Key_Right else -1 if e.key()==Qt.Key_Left else 0);dy=(1 if e.key()==Qt.Key_Down else -1 if e.key()==Qt.Key_Up else 0);self.move_selection_pixels(dx,dy);return
        if e.key()==Qt.Key_Left:self.set_frame(self.frame-1)
        elif e.key()==Qt.Key_Right:self.set_frame(self.frame+1)
        elif e.key() in (Qt.Key_Plus,Qt.Key_Equal):self.set_zoom(self.canvas.zoom*1.15)
        elif e.key()==Qt.Key_Minus:self.set_zoom(self.canvas.zoom/1.15)
        else:super().keyPressEvent(e)


if __name__=="__main__":
    log_path=Path(__file__).with_name("MakeToons_startup_error.txt")
    try:
        app=QApplication(sys.argv)
        logo=Path(__file__).with_name("MakeToons_logo_full.png")
        if logo.exists():
            app.setWindowIcon(QIcon(str(logo)))
        w=MakeToons()
        w.show()
        sys.exit(app.exec())
    except Exception:
        err=traceback.format_exc()
        try:
            log_path.write_text(err,encoding="utf-8")
        except Exception:
            pass
        try:
            QMessageBox.critical(None,APP,"MakeToons failed to start.\\n\\n"+err)
        except Exception:
            pass
        raise
