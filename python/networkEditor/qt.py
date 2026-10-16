"""Qt 小工具 + 矢量类型图标。

字体、LOD 取值、事件坐标、GafferUI 全局事件过滤器的入口，以及节点上那些
手绘的类型图标（不用贴图，缩放不糊）。
"""

import os
import sys
import math
import functools

import IECore


from Qt import QtCore, QtGui, QtWidgets

from .layout import *

# Qt 小工具


## 从 `GAFFERUI_IMAGE_PATHS` 里找一张官方图标做成 `QIcon`（找不到返回 None）。
def _graphicIcon(name):

    path = IECore.SearchPath(os.environ.get("GAFFERUI_IMAGE_PATHS", "")).find(name)
    if not path:
        return None

    icon = QtGui.QIcon(path)
    return None if icon.isNull() else icon


## 字体按 ( 字号, 粗细 ) 复用一份 —— 一帧里 paint 要问几十次，`QFont()` 每次新建
# 不便宜；`painter.setFont` / `QFontMetrics` 都按值拷贝，共享一份是安全的。
# **别改返回值**（要改就 `QFont( font )` 拷一份）。
@functools.lru_cache(maxsize=None)
def _font(pointSize, bold=False):

    font = QtGui.QFont()
    font.setPointSizeF(pointSize)
    font.setBold(bold)
    return font


def _lod(option, painter):

    return QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(
        painter.worldTransform()
    )


## 鼠标 / 滚轮事件用 `position()`（`pos()` 在 PySide6 已废弃）；`QContextMenuEvent`
# 只有 `pos()` / `globalPos()`（右键菜单那一路就是它）。
def _eventPos(event):

    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


def _globalPos(event):

    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


## GafferUI 那个**全局唯一**的事件过滤器（`GafferUI/Widget.py` 模块级的 `_eventFilter`）。
#
# 整套拖放都是它驱动的：它按鼠标位置找目标控件、发 `dragEnter/dragMove/dragLeave/drop`。
# 想让别的编辑器收得到我们拖出去的东西，就得让它**看得见我们视图里的鼠标事件** ——
# 而 `Widget.__ensureEventFilter` 只把它装在 Editor 的顶层 QWidget 上，事件全被
# `QGraphicsView` 这个子控件吃掉了，所以要自己往视图上再装一遍。
def _gafferUIEventFilter():

    module = sys.modules.get("GafferUI.Widget")
    return getattr(module, "_eventFilter", None) if module is not None else None


def _sectionTangent(section):

    return {
        "top": QtCore.QPointF(0, -1),
        "bottom": QtCore.QPointF(0, 1),
        "left": QtCore.QPointF(-1, 0),
        "right": QtCore.QPointF(1, 0),
    }.get(section, QtCore.QPointF(0, 1))


# 类型图标（矢量手绘，不用贴图）


# 每个类型图标一个画法（都在 16x16 的坐标系里画，`_drawGlyph` 已经把
# 缩放 / 画笔 / 颜色都摆好了）。加一种图标 = 加一个函数 + 往下面那张表里加一行。


def _glyphLight(painter, pen, color):

    # 灯泡：玻璃球 + 灯颈 + 灯座两道 + 三条光线
    painter.drawEllipse(QtCore.QPointF(0, -3.2), 4.6, 4.6)
    painter.drawLine(QtCore.QPointF(-2.2, 1.4), QtCore.QPointF(-2.2, 3.6))
    painter.drawLine(QtCore.QPointF(2.2, 1.4), QtCore.QPointF(2.2, 3.6))
    painter.drawLine(QtCore.QPointF(-2.2, 4.6), QtCore.QPointF(2.2, 4.6))
    painter.drawLine(QtCore.QPointF(-1.4, 6.2), QtCore.QPointF(1.4, 6.2))
    for a in (-140.0, -90.0, -40.0):
        r = math.radians(a)
        painter.drawLine(
            QtCore.QPointF(math.cos(r) * 6.2, -3.2 + math.sin(r) * 6.2),
            QtCore.QPointF(math.cos(r) * 7.8, -3.2 + math.sin(r) * 7.8),
        )


## 图标内部那些「缝」（圆柱的接缝、球的经纬线、mesh 的网格线）。
#
# 原生 PNG 是把填充**掏掉**、露出底色；我们手上只有一个前景色，就压暗（浅色图标）
# 或提亮（深色图标）一档 —— 画在实心填充上看着和原生那条缝一样。
def _glyphSeamColor(color):

    target = 0 if color.lightnessF() > 0.5 else 255
    mix = 0.62
    return QtGui.QColor(
        int(color.red() * (1.0 - mix) + target * mix),
        int(color.green() * (1.0 - mix) + target * mix),
        int(color.blue() * (1.0 - mix) + target * mix),
    )


def _lerp(a, b, t):

    return QtCore.QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)


## 下面九个灯光图标都是照 LightEditor 那套 16x16 官方图标复刻的
# （`$GAFFER_ROOT/graphics/{point,spot,quad,distant,disk,cylinder,environment,
# photometric,mesh}Light.png`）—— 形状 / 尺寸 / 朝向都按图上量出来的坐标画，
# 只是改成矢量，缩放不糊。


def _glyphPointLight(painter, pen, color):

    # 点光：正中一个小实心圆
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    painter.drawEllipse(QtCore.QPointF(0, 0), 2.3, 2.3)


def _glyphDistantLight(painter, pen, color):

    # 平行光：两支朝左下的平行箭头（箭头的两根倒刺是横竖的，和原生一样）
    painter.setBrush(QtCore.Qt.NoBrush)
    for dx, dy in ((0.0, 0.0), (5.0, 5.0)):
        tip = QtCore.QPointF(-7.0 + dx, 1.0 + dy)
        painter.drawLine(tip, QtCore.QPointF(1.5 + dx, -6.5 + dy))
        painter.drawLine(tip, QtCore.QPointF(tip.x(), tip.y() - 3.0))
        painter.drawLine(tip, QtCore.QPointF(tip.x() + 3.0, tip.y()))


def _glyphQuadLight(painter, pen, color):

    # 面光：一块斜着的实心矩形（长边朝右下）
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    painter.drawPolygon(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(-1.5, -6.0),
                QtCore.QPointF(-6.0, -1.5),
                QtCore.QPointF(1.5, 6.0),
                QtCore.QPointF(6.0, 1.5),
            ]
        )
    )


def _glyphSpotLight(painter, pen, color):

    # 聚光：右上是灯头（锥尖），朝左下张开的一段扇形光锥 —— 两条边 + 一段弧，
    # 只画轮廓（原生图上量出来就是这么个扇形，不是填实的）
    painter.setBrush(QtCore.Qt.NoBrush)
    path = QtGui.QPainterPath()
    path.moveTo(6.0, -5.8)  # 锥尖（右上）
    path.lineTo(-7.6, -0.3)  # 锥口的一头
    # 锥口那段弧：原生两条边到锥尖的距离并不相等（不是正圆扇形），用一段二次
    # 贝塞尔照着图上的鼓包走。
    path.quadTo(-6.45, 8.45, 0.5, 6.2)
    path.closeSubpath()
    painter.drawPath(path)


def _glyphDiskLight(painter, pen, color):

    # 圆盘光：一块斜着的实心椭圆（和面光同朝向，只是圆的）
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    painter.save()
    painter.rotate(45.0)
    painter.drawEllipse(QtCore.QPointF(0, 0), 7.4, 4.4)
    painter.restore()


def _glyphCylinderLight(painter, pen, color):

    # 圆柱光：实心的立着的圆柱（上下是椭圆盖），顶盖下面一道接缝
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(-4.3, -6.6, 8.0, 13.4), 4.0, 2.1)
    painter.drawPath(path)

    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(QtGui.QPen(_glyphSeamColor(color), 1.2))
    painter.drawEllipse(QtCore.QPointF(-0.3, -4.5), 4.0, 2.1)


def _glyphSkydomeLight(painter, pen, color):

    # 环境光（skydome）：一个带经纬线的实心球
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    radius = 6.4
    painter.drawEllipse(QtCore.QPointF(0, 0), radius, radius)

    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(QtGui.QPen(_glyphSeamColor(color), 1.1))
    painter.drawEllipse(QtCore.QPointF(0, 0), 3.6, radius)  # 经线
    for y in (-1.9, 1.9):  # 纬线（按球面弦长收边）
        half = math.sqrt(max(0.0, radius * radius - y * y)) - 0.5
        painter.drawLine(QtCore.QPointF(-half, y), QtCore.QPointF(half, y))


def _glyphPhotometricLight(painter, pen, color):

    # 光度学（IES）：小灯泡 + 底下那片实心配光，中间留一道缝
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    dome = QtGui.QPainterPath()
    dome.moveTo(-7.0, -0.9)
    dome.arcTo(QtCore.QRectF(-7.0, -7.9, 14.0, 14.0), 180.0, 180.0)
    dome.closeSubpath()
    painter.drawPath(dome)
    painter.drawEllipse(QtCore.QPointF(-0.2, -3.0), 2.1, 2.1)

    # 灯泡和配光之间那道缝**只画在配光上** —— 不裁的话灯泡上半圈会在空气里
    # 拖出一个深色圆环（原生那儿是纯填充）。
    painter.save()
    painter.setClipPath(dome)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(QtGui.QPen(_glyphSeamColor(color), 1.2))
    painter.drawEllipse(QtCore.QPointF(-0.2, -3.0), 3.1, 3.1)
    painter.restore()


def _glyphMeshLight(painter, pen, color):

    # 网格光：一块斜着的实心网格面（面光那块矩形 + 网格线）
    top = QtCore.QPointF(-2.0, -6.2)
    left = QtCore.QPointF(-6.2, -2.0)
    bottom = QtCore.QPointF(2.0, 6.2)
    right = QtCore.QPointF(6.2, 2.0)

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    painter.drawPolygon(QtGui.QPolygonF([top, left, bottom, right]))

    # 网格线：长边上分三格、短边上分两格（再密就只剩线看不见面了）
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(QtGui.QPen(_glyphSeamColor(color), 0.9))
    for t in (1.0 / 3.0, 2.0 / 3.0):
        painter.drawLine(_lerp(top, right, t), _lerp(left, bottom, t))
    painter.drawLine(_lerp(top, left, 0.5), _lerp(right, bottom, 0.5))


def _glyphCamera(painter, pen, color):

    # 相机：机身 + 顶部取景凸起 + 镜头
    painter.drawRoundedRect(QtCore.QRectF(-7.0, -3.4, 14.0, 9.6), 1.6, 1.6)
    painter.drawLine(QtCore.QPointF(-3.4, -3.4), QtCore.QPointF(-2.2, -5.8))
    painter.drawLine(QtCore.QPointF(-2.2, -5.8), QtCore.QPointF(1.4, -5.8))
    painter.drawLine(QtCore.QPointF(1.4, -5.8), QtCore.QPointF(2.6, -3.4))
    painter.drawEllipse(QtCore.QPointF(-0.4, 1.4), 3.0, 3.0)
    painter.drawEllipse(QtCore.QPointF(-0.4, 1.4), 1.1, 1.1)


def _glyphFilter(painter, pen, color):

    # 漏斗
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(-6.4, -5.2),
                QtCore.QPointF(6.4, -5.2),
                QtCore.QPointF(1.6, 0.6),
                QtCore.QPointF(1.6, 6.0),
                QtCore.QPointF(-1.6, 4.2),
                QtCore.QPointF(-1.6, 0.6),
                QtCore.QPointF(-6.4, -5.2),
            ]
        )
    )


def _glyphShader(painter, pen, color):

    # 材质球：球 + 高光
    painter.drawEllipse(QtCore.QPointF(0, 0), 6.2, 6.2)
    painter.setBrush(QtGui.QBrush(color))
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawEllipse(QtCore.QPointF(-2.2, -2.4), 1.5, 1.1)


def _glyphDisplacement(painter, pen, color):

    # 置换：一条起伏的面 + 上下箭头
    path = QtGui.QPainterPath()
    path.moveTo(-7.0, 2.6)
    path.cubicTo(-3.5, -3.0, 0.5, 6.0, 7.0, 0.4)
    painter.drawPath(path)
    painter.drawLine(QtCore.QPointF(0, -6.6), QtCore.QPointF(0, -1.6))
    painter.drawLine(QtCore.QPointF(-1.8, -4.8), QtCore.QPointF(0, -6.6))
    painter.drawLine(QtCore.QPointF(1.8, -4.8), QtCore.QPointF(0, -6.6))


def _glyphVolume(painter, pen, color):

    # 体积：一团云
    painter.drawEllipse(QtCore.QPointF(-3.0, 1.0), 3.6, 3.2)
    painter.drawEllipse(QtCore.QPointF(1.4, -0.6), 4.4, 4.0)
    painter.drawEllipse(QtCore.QPointF(4.4, 2.0), 2.8, 2.4)


def _glyphTexture(painter, pen, color):

    # 贴图：画片 + 里头一座小山和太阳
    painter.drawRoundedRect(QtCore.QRectF(-7.0, -5.4, 14.0, 11.0), 1.4, 1.4)
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(-5.4, 4.0),
                QtCore.QPointF(-1.4, -1.4),
                QtCore.QPointF(1.6, 2.2),
                QtCore.QPointF(3.2, 0.4),
                QtCore.QPointF(5.4, 4.0),
            ]
        )
    )
    painter.drawEllipse(QtCore.QPointF(3.4, -3.0), 1.3, 1.3)


def _glyphPattern(painter, pen, color):

    # 程序纹理：2x2 棋盘
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    painter.drawRect(QtCore.QRectF(-6.0, -6.0, 6.0, 6.0))
    painter.drawRect(QtCore.QRectF(0.0, 0.0, 6.0, 6.0))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(pen)
    painter.drawRect(QtCore.QRectF(-6.0, -6.0, 12.0, 12.0))


def _glyphUtility(painter, pen, color):

    # 工具 / 数学：三条推子
    for index, y in enumerate((-4.2, 0.0, 4.2)):
        painter.drawLine(QtCore.QPointF(-6.4, y), QtCore.QPointF(6.4, y))
        x = (-2.6, 2.4, -0.6)[index]
        painter.setBrush(QtGui.QBrush(color))
        painter.drawEllipse(QtCore.QPointF(x, y), 1.7, 1.7)
        painter.setBrush(QtCore.Qt.NoBrush)


def _glyphRender(painter, pen, color):

    # 画面输出：画框 + 底座
    painter.drawRoundedRect(QtCore.QRectF(-7.0, -5.4, 14.0, 9.4), 1.4, 1.4)
    painter.drawLine(QtCore.QPointF(-2.4, 4.0), QtCore.QPointF(-2.4, 6.2))
    painter.drawLine(QtCore.QPointF(2.4, 4.0), QtCore.QPointF(2.4, 6.2))
    painter.drawLine(QtCore.QPointF(-4.6, 6.2), QtCore.QPointF(4.6, 6.2))


def _glyphGeometry(painter, pen, color):

    # 图元：一个立方体的等轴测线框
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(0, -6.4),
                QtCore.QPointF(6.0, -3.0),
                QtCore.QPointF(6.0, 3.4),
                QtCore.QPointF(0, 6.6),
                QtCore.QPointF(-6.0, 3.4),
                QtCore.QPointF(-6.0, -3.0),
                QtCore.QPointF(0, -6.4),
            ]
        )
    )
    painter.drawLine(QtCore.QPointF(0, -6.4), QtCore.QPointF(0, 0.2))
    painter.drawLine(QtCore.QPointF(0, 0.2), QtCore.QPointF(6.0, 3.4))
    painter.drawLine(QtCore.QPointF(0, 0.2), QtCore.QPointF(-6.0, 3.4))


def _glyphExpression(painter, pen, color):

    # 表达式：一个 Σ
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(5.0, -6.0),
                QtCore.QPointF(-5.0, -6.0),
                QtCore.QPointF(0.4, 0.0),
                QtCore.QPointF(-5.0, 6.0),
                QtCore.QPointF(5.0, 6.0),
            ]
        )
    )


def _glyphSpreadsheet(painter, pen, color):

    # 表格：外框 + 一条表头 + 一横一竖分隔
    painter.drawRoundedRect(QtCore.QRectF(-6.4, -6.0, 12.8, 12.0), 1.2, 1.2)
    painter.drawLine(QtCore.QPointF(-6.4, -2.4), QtCore.QPointF(6.4, -2.4))
    painter.drawLine(QtCore.QPointF(-6.4, 1.8), QtCore.QPointF(6.4, 1.8))
    painter.drawLine(QtCore.QPointF(-1.6, -2.4), QtCore.QPointF(-1.6, 6.0))
    # 表头填实一点，一眼看出是表
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    painter.drawRect(QtCore.QRectF(-6.4, -6.0, 12.8, 3.6))


def _glyphTransform(painter, pen, color):

    # 变换：两个方向的箭头
    painter.drawLine(QtCore.QPointF(-6.2, 4.4), QtCore.QPointF(5.0, 4.4))
    painter.drawLine(QtCore.QPointF(-6.2, 4.4), QtCore.QPointF(-6.2, -4.6))
    painter.setBrush(QtGui.QBrush(color))
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawPolygon(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(6.6, 4.4),
                QtCore.QPointF(4.2, 2.9),
                QtCore.QPointF(4.2, 5.9),
            ]
        )
    )
    painter.drawPolygon(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(-6.2, -6.4),
                QtCore.QPointF(-7.7, -4.0),
                QtCore.QPointF(-4.7, -4.0),
            ]
        )
    )


_GLYPH_PAINTERS = {
    GLYPH_LIGHT: _glyphLight,
    GLYPH_POINT_LIGHT: _glyphPointLight,
    GLYPH_DISTANT_LIGHT: _glyphDistantLight,
    GLYPH_QUAD_LIGHT: _glyphQuadLight,
    GLYPH_SPOT_LIGHT: _glyphSpotLight,
    GLYPH_DISK_LIGHT: _glyphDiskLight,
    GLYPH_CYLINDER_LIGHT: _glyphCylinderLight,
    GLYPH_SKYDOME_LIGHT: _glyphSkydomeLight,
    GLYPH_PHOTOMETRIC_LIGHT: _glyphPhotometricLight,
    GLYPH_MESH_LIGHT: _glyphMeshLight,
    GLYPH_CAMERA: _glyphCamera,
    GLYPH_FILTER: _glyphFilter,
    GLYPH_SHADER: _glyphShader,
    GLYPH_DISPLACEMENT: _glyphDisplacement,
    GLYPH_VOLUME: _glyphVolume,
    GLYPH_TEXTURE: _glyphTexture,
    GLYPH_PATTERN: _glyphPattern,
    GLYPH_UTILITY: _glyphUtility,
    GLYPH_RENDER: _glyphRender,
    GLYPH_GEOMETRY: _glyphGeometry,
    GLYPH_EXPRESSION: _glyphExpression,
    GLYPH_SPREADSHEET: _glyphSpreadsheet,
    GLYPH_TRANSFORM: _glyphTransform,
}


## 在 `centre` 处画一个 `size` 见方的类型图标。
def _drawGlyph(painter, kind, centre, size, color):

    paint = _GLYPH_PAINTERS.get(kind)
    if paint is None:
        return

    painter.save()
    painter.translate(centre)
    painter.scale(size / 16.0, size / 16.0)  # 图标按 16x16 设计
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    pen = QtGui.QPen(color, 1.4)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    paint(painter, pen, color)

    painter.restore()


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
