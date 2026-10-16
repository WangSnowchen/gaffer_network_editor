"""Backdrop 的 `QGraphicsItem`。

语义逐条照原生 `BackdropNodeGadget.cpp`：框身是**空的**（只有四条边和顶上那条
标题条能点），所以在 Backdrop 上照样能框选它上面的节点；四条边是拉框改大小的
抓手；`scale` 放大文字、`depth` 加面积决定谁垫在谁后面。
"""

import math

import imath

import Gaffer

from Qt import QtCore, QtGui, QtWidgets

from .qt import *

# Qt：Backdrop


class _BackdropItem(QtWidgets.QGraphicsItem):

    def __init__(self, node, owner=None):

        QtWidgets.QGraphicsItem.__init__(self)

        self.node = node
        self.nodeName = node.getName()
        self._owner = owner
        self._readOnly = Gaffer.MetadataAlgo.readOnly(node)
        self._hovered = False

        self._color = QtGui.QColor(
            nodeColor(node)
            if Gaffer.Metadata.value(node, "nodeGadget:color")
            else _backdropColor
        )

        # 拉框时先只改这份预览，松手才写回插口（一次拖动一步撤销）。
        self._previewBound = None

        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        # 和节点一样能拖着走（原生点 Backdrop 连它框住的节点一起选，于是整组一起移动）。
        self.setFlag(
            QtWidgets.QGraphicsItem.ItemIsMovable,
            not self._readOnly,
        )

        self.refresh()

    ##########################################################################
    # 几何（框相对 `__uiPosition`，item 摆在框的中心上）
    ##########################################################################

    ## 把插口上的一切重新读一遍（框 / 缩放 / 深度 / 标题 / 描述）。
    def refresh(self):

        # **旧那块要自己报一遍脏**。`prepareGeometryChange()` 记的是"当前"包围盒，
        # 而紧接着的 `setPos()` 会用**新**包围盒去标记旧位置那一块 —— 拉框时
        # 尺寸和位置是**一起**变的（框中心跟着走），两者一错位就有一条没被重画的
        # 带子留在屏幕上（快速拉长再缓慢缩短时，屏幕内容和强制重绘实测差
        # 5274 个采样点）。
        scene = self.scene()
        oldSceneRect = None
        if scene is not None and getattr(self, "_width", None) is not None:
            oldSceneRect = self.mapToScene(self.boundingRect()).boundingRect()

        self.prepareGeometryChange()

        box = self.relativeBound()
        position = nodePosition(self.node) or imath.V2f(0)

        self._width = max(1.0, (box.max().x - box.min().x) * PX_PER_UNIT)
        self._height = max(1.0, (box.max().y - box.min().y) * PX_PER_UNIT)
        self._scale = backdropScale(self.node)
        self._depth = backdropDepth(self.node)
        self._title, self._description = backdropTitleAndDescription(self.node)
        if not self._title:
            self._title = self.node.getName()

        center = imath.V2f(
            position.x + (box.min().x + box.max().x) * 0.5,
            position.y + (box.min().y + box.max().y) * 0.5,
        )
        self.setPos(center.x * PX_PER_UNIT, -center.y * PX_PER_UNIT)
        self.setZValue(self.__zValue())
        self.setToolTip(self.__toolTip())
        self.update()

        if oldSceneRect is not None:
            scene.update(oldSceneRect)

    ## 现在这一刻的框（拉框途中是预览的那份）。相对 `__uiPosition`，和原生
    # `BackdropNodeGadget::getBound()` 同语义。
    def relativeBound(self):

        if self._previewBound is not None:
            return self._previewBound

        return backdropRelativeBound(self.node)

    ## 拉框途中的预览。`box` 相对 `__uiPosition`（Gaffer 单位）。
    def setPreviewBound(self, box):

        self._previewBound = box
        self.refresh()

    ## 把预览写回插口（一步撤销），返回有没有真的改动。
    def commitPreviewBound(self):

        box = self._previewBound
        self._previewBound = None
        if box is None or self._readOnly:
            self.refresh()
            return False

        current = backdropRelativeBound(self.node)
        if (
            abs(current.min().x - box.min().x) < 1e-4
            and abs(current.min().y - box.min().y) < 1e-4
            and abs(current.max().x - box.max().x) < 1e-4
            and abs(current.max().y - box.max().y) < 1e-4
        ):
            self.refresh()
            return False

        script = self.node.ancestor(Gaffer.ScriptNode)
        if script is not None:
            with Gaffer.UndoScope(script):
                setBackdropRelativeBound(self.node, box)
        else:
            setBackdropRelativeBound(self.node, box)

        self.refresh()
        return True

    ## item 的位置是**框的中心**（`__uiPosition` + `__uiBound` 的中心），而写回 script
    # 只能写 `__uiPosition` —— 两者差的就是这个偏移。拖动松手时拿它换算回去。
    def centerOffset(self):

        box = self.relativeBound()
        return imath.V2f(
            (box.min().x + box.max().x) * 0.5, (box.min().y + box.max().y) * 0.5
        )

    ## 层叠顺序。原生把 `depth`（[-1,1]）划成几段深度区间，段内按**面积**排
    # （大的更靠后），所以大框自动垫在小框后面。这里换成 `zValue` 同样的排法。
    def __zValue(self):

        area = self._width * self._height
        areaFraction = area / (area + BACKDROP_Z_AREA_REFERENCE)
        return BACKDROP_Z_BASE + self._depth * BACKDROP_Z_DEPTH_STEP - areaFraction

    ## 框本身（绘制、命中、框选判定都用它）。
    def frameRect(self):

        return QtCore.QRectF(
            -self._width / 2.0, -self._height / 2.0, self._width, self._height
        )

    ## ⚠️ **包围盒要比框本身大出描边的一半**（Qt 的老规矩：`boundingRect()` 必须
    # 把 pen 宽算进去）。选中时描边是 **2px**、居中画在路径上 → 往外溢 1px，
    # 再加抗锯齿一圈 —— 包围盒不放大的话那一圈永远不会被重画：**拉框时每一帧都
    # 留一条 1px 的竖线，屏幕上就是一排均匀的细条纹**（只在「Backdrop 选中着」
    # 的时候出现，因为不选中描边只有 1px）。
    def boundingRect(self):

        margin = BACKDROP_STROKE_MARGIN
        return self.frameRect().adjusted(-margin, -margin, margin, margin)

    ## **命中形状：只有四条边和顶上那条标题条，框身是空的。**
    #
    # 原生在 selection render 里就是这么画的（`BackdropNodeGadget.cpp:350`：
    # "leaving the main body of the backdrop as a hole is necessary to allow the
    # GraphGadget to continue to perform drag selection on the nodes on top"）——
    # 不留这个洞，在 Backdrop 上就没法框选它框住的节点，只能把整个 Backdrop 拖走。
    def shape(self):

        rect = self.frameRect()
        width = BACKDROP_EDGE_HIT

        path = QtGui.QPainterPath()
        # 四条边在角上互相重叠 —— 必须 WindingFill，OddEvenFill 会把重叠处异或成洞
        path.setFillRule(QtCore.Qt.WindingFill)
        path.addRect(QtCore.QRectF(rect.left(), rect.top(), width, rect.height()))
        path.addRect(
            QtCore.QRectF(rect.right() - width, rect.top(), width, rect.height())
        )
        path.addRect(
            QtCore.QRectF(rect.left(), rect.bottom() - width, rect.width(), width)
        )
        path.addRect(QtCore.QRectF(rect.left(), rect.top(), rect.width(), width))
        path.addRect(self.titleBarRect())
        return path

    ## 顶上那条标题条（抓着它搬动整个 Backdrop）。
    def titleBarRect(self):

        rect = self.frameRect()
        margin = BACKDROP_TITLE_BAR_MARGIN / self._scale
        height = BACKDROP_TITLE_BAR_HEIGHT / self._scale
        return QtCore.QRectF(
            rect.left() + margin,
            rect.top() + margin,
            max(1.0, rect.width() - margin * 2.0),
            height,
        )

    ## 框选判定用的矩形（scene 坐标）。原生要求**完全框住**才算选中。
    def selectionRect(self):

        return self.mapToScene(self.frameRect()).boundingRect()

    ##########################################################################
    # 拉框改大小
    ##########################################################################

    ## 局部坐标点压在哪条边上，返回 ( horizontal, vertical )，取值 -1 / 0 / 1。
    #
    # 照原生 `hoveredEdges`：左右下三边的抓手是 `BACKDROP_EDGE_HIT`，
    # **上边窄得多**（`min( width, g_titleBarMargin )`）—— 顶上那条要留给搬动。
    # 注意 y 在 Qt 里向下，所以 `vertical = 1`（原生的"上"）对应 `rect.top()`。
    def edgeAt(self, position):

        if self._readOnly:
            return 0, 0

        rect = self.frameRect()
        width = BACKDROP_EDGE_HIT
        horizontal = vertical = 0

        if not rect.adjusted(-width, -width, width, width).contains(position):
            return 0, 0

        if abs(position.x() - rect.left()) < width:
            horizontal = -1
        elif abs(position.x() - rect.right()) < width:
            horizontal = 1

        if abs(position.y() - rect.bottom()) < width:
            vertical = -1
        elif abs(position.y() - rect.top()) < min(
            width, BACKDROP_TOP_EDGE_HIT / self._scale
        ):
            vertical = 1

        return horizontal, vertical

    ## 拖着某条边到 `scenePoint`（scene 坐标）时框应该长什么样。
    # 最小尺寸照原生 `g_margin * 4`。
    #
    # ⚠️ **换算一定要走「scene 坐标 → 节点位置」这条路，别经过 item 的局部坐标**：
    # item 摆在**框的中心**上，拉框时中心一直在动，而基准 `box` 取的是插口里那份
    # （拖动期间不写回）—— 两个基准混用的话每一帧都在累加偏移，表现是「往左拖框
    # 反而越来越长」（实测光标一路左移，`max.x` 从 44.6 涨到 57.0）。
    # 节点位置（`__uiPosition`）在拉框时是不动的，拿它当基准才稳（原生 `dragMove`
    # 用的 `event.line.p0` 就是"相对节点位置"的 gadget 局部坐标）。
    def boundForEdgeDrag(self, horizontal, vertical, scenePoint):

        box = backdropRelativeBound(self.node)
        minimum = BACKDROP_MIN_SIZE / PX_PER_UNIT

        position = nodePosition(self.node) or imath.V2f(0)
        x = scenePoint.x() / PX_PER_UNIT - position.x
        y = -scenePoint.y() / PX_PER_UNIT - position.y

        left, bottom = box.min().x, box.min().y
        right, top = box.max().x, box.max().y

        if horizontal == -1:
            left = min(x, right - minimum)
        elif horizontal == 1:
            right = max(x, left + minimum)

        if vertical == -1:
            bottom = min(y, top - minimum)
        elif vertical == 1:
            top = max(y, bottom + minimum)

        return imath.Box2f(imath.V2f(left, bottom), imath.V2f(right, top))

    ##########################################################################
    # 悬停（原生：鼠标在框身上、又不在边缘上时，标题条高亮）
    ##########################################################################

    def setHovered(self, hovered):

        hovered = bool(hovered)
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()

    def __toolTip(self):

        # 标题和描述都是用户自己写在节点上的内容，原样显示（不是我们的界面文字）。
        parts = []
        if self._title:
            parts.append("<b>%s</b>" % _escape(self._title))
        if self._description:
            parts.append(_escape(self._description).replace("\n", "<br>"))
        return "<br><br>".join(parts)

    ##########################################################################
    # 绘制
    ##########################################################################

    def paint(self, painter, option, widget=None):

        rect = self.frameRect()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        fill = QtGui.QColor(self._color)
        fill.setAlpha(70)
        painter.setBrush(fill)
        painter.setPen(
            QtGui.QPen(QtGui.QColor(_selectedBorder), 2.0)
            if self.isSelected()
            else QtGui.QPen(self._color.lighter(130), 1.0)
        )
        painter.drawRoundedRect(rect, 6, 6)

        if _lod(option, painter) < LOD_MEDIUM:
            return

        self.__paintTitleBar(painter)
        self.__paintText(painter, rect)

    ## 顶上那条标题条：悬停在框身上时高亮，平时 15% 白（照原生两档颜色）。
    def __paintTitleBar(self, painter):

        bar = self.titleBarRect()
        painter.setPen(QtCore.Qt.NoPen)
        if self._hovered:
            painter.setBrush(QtGui.QColor(BACKDROP_TITLE_BAR_HOVER))
        else:
            color = QtGui.QColor(255, 255, 255)
            color.setAlpha(BACKDROP_TITLE_BAR_IDLE_ALPHA)
            painter.setBrush(color)
        painter.drawRect(bar)

    ## 标题字号。`scale` 只放大文字，不改框（原生就是这个语义）。
    def titleFont(self):

        return _font(BACKDROP_TITLE_SIZE * self._scale, bold=True)

    ## 标题占的那块矩形。
    #
    # ⚠️ **高度要往上取整再留一点** —— 直接拿 `QFontMetricsF.height()`（浮点）
    # 当矩形高度，`drawText` 会把字的下缘（`g` / `y` 那一撇、中文的下半格）截掉
    # 几个像素。
    def titleTextRect(self):

        rect = self.frameRect()
        metrics = QtGui.QFontMetricsF(self.titleFont())
        return QtCore.QRectF(
            rect.left() + BACKDROP_MARGIN,
            rect.top()
            + BACKDROP_TITLE_BAR_MARGIN
            + BACKDROP_TITLE_BAR_HEIGHT / self._scale,
            max(1.0, rect.width() - BACKDROP_MARGIN * 2.0),
            math.ceil(metrics.height()) + BACKDROP_TITLE_SLACK,
        )

    ## 描述的字号（同样跟着 `scale`）。
    def descriptionFont(self):

        return _font(BACKDROP_DESCRIPTION_SIZE * self._scale)

    ## 描述占的那块矩形（标题下面、四周留 `BACKDROP_MARGIN`）。
    def descriptionTextRect(self):

        rect = self.frameRect()
        titleRect = self.titleTextRect()
        return QtCore.QRectF(
            rect.left() + BACKDROP_MARGIN,
            titleRect.bottom() + BACKDROP_MARGIN * 0.5,
            max(1.0, rect.width() - BACKDROP_MARGIN * 2.0),
            max(
                0.0,
                rect.bottom()
                - BACKDROP_MARGIN
                - titleRect.bottom()
                - BACKDROP_MARGIN * 0.5,
            ),
        )

    def __paintText(self, painter, rect):

        margin = BACKDROP_MARGIN
        titleFont = self.titleFont()
        painter.setFont(titleFont)
        metrics = QtGui.QFontMetricsF(titleFont)
        titleRect = self.titleTextRect()

        painter.setPen(QtGui.QColor(_textColor))
        painter.drawText(
            titleRect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
            metrics.elidedText(self._title, QtCore.Qt.ElideRight, titleRect.width()),
        )

        if not self._description:
            return

        bodyRect = self.descriptionTextRect()
        if bodyRect.height() < 4.0:
            return

        painter.setFont(self.descriptionFont())
        painter.setPen(QtGui.QColor(_dimTextColor))
        painter.drawText(
            bodyRect,
            int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap),
            self._description,
        )


def _escape(text):

    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
