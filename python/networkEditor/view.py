"""`QGraphicsView`：平移 / 缩放 / 框选 / 拖节点 / 拉连线 / 划线删除 / 快捷键。"""

import math


import Gaffer

from Qt import QtCore, QtGui, QtWidgets

from .edge_item import *

# Qt：视图

_MODE_NONE = 0
_MODE_PAN = 1
_MODE_CONNECT = 2
_MODE_CUT = 3
_MODE_MOVE = 4
_MODE_BAND = 5
_MODE_ZOOM = 6  # Alt + 右键拖 = 缩放（原生 ViewportGadget 的 dolly）
_MODE_RESIZE = 7  # 拖 Backdrop 的边缘改大小（原生 BackdropNodeGadget 的 dragMove）


class _GraphView(QtWidgets.QGraphicsView):

    def __init__(self, owner):

        QtWidgets.QGraphicsView.__init__(self)

        self.__owner = owner

        self.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.setBackgroundBrush(QtGui.QColor(_backgroundColor))
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        # 橡皮筋自己画：Qt 自带的只认 Ctrl=加选、且是「相交即选中」，
        # 原生是 **完全框住才算** + Shift 加选 + Ctrl 减选（`GraphGadget.cpp:1565`）。
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        # 视口更新：不用 `FullViewportUpdate`（它防得住 `drawBackground` 的网格留残迹，
        # 代价是**任何一点变化都重绘整个视口** —— 300 个节点改一根线要重绘 300 张卡片）。
        # 用 `SmartViewportUpdate` + 背景走缓存：网格由 Qt 按脏矩形自己补；
        # 橡皮筋是独立的 `QRubberBand` **控件**（不在 scene 里，本来就不会留痕）；
        # 划线是真的 `QGraphicsItem`；只有 `drawForeground` 画的对齐参考线要自己
        # 在变化时 `viewport().update()`（`_clearSnapGuides` / `_snapNodePosition` 里已经做了）。
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setCacheMode(QtWidgets.QGraphicsView.CacheBackground)
        self.setOptimizationFlags(
            QtWidgets.QGraphicsView.DontSavePainterState
            | QtWidgets.QGraphicsView.DontAdjustForAntialiasing
        )
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)

        self.__mode = _MODE_NONE
        self.__zoomStart = QtCore.QPoint()
        self.__zoomAnchor = QtCore.QPointF()
        self.__zoomStartScale = 1.0
        self.__panStart = QtCore.QPoint()
        self.__connectFrom = None  # ( _NodeItem, plug )
        self.__connectDetach = None  # 改接时要拆掉的那条旧边
        self.__connectDetachItem = None  # 改接期间被藏起来的那条线（没接成要还回来）
        self.__connectWire = None  # 临时 QGraphicsPathItem
        self.__cutPoints = []
        self.__cutStroke = False  # 左键按着才算在划
        self.__cutPressPosition = None  # 这一下是"点"还是"划"，靠它判
        self.__cutItem = None
        # 按着 X 时中键平移：平移期间划线模式挂起，松开中键回来（期间松了 X 就不回来）
        self.__cutSuspended = False
        self.__gestureButton = None  # 正在进行的手势是哪个键按出来的
        self.__resizeItem = None  # 正在拉框的那个 Backdrop
        self.__resizeEdges = (0, 0)  # 拉的是哪条边（horizontal, vertical）

        # 拖到视口边缘时画面自己跟着滚（原生 `ViewportGadget::trackDrag`，
        # GraphEditor 两个轴都开着：`setDragTracking( X | Y )`）
        self.__dragTrackVelocity = QtCore.QPointF()
        self.__dragTrackThreshold = 0.0
        self.__dragTrackPosition = QtCore.QPoint()
        self.__dragTrackTimer = QtCore.QTimer(self)
        self.__dragTrackTimer.setInterval(DRAG_TRACK_INTERVAL)
        self.__dragTrackTimer.timeout.connect(self.__trackDragIdle)
        self.__band = None  # 自绘橡皮筋
        self.__bandOrigin = QtCore.QPoint()
        self.__bandModifiers = QtCore.Qt.NoModifier
        self.__connectDestination = (None, None)  # 连线拖拽时吸附到的目标

    ##########################################################################
    # 背景
    ##########################################################################

    def drawBackground(self, painter, rect):

        QtWidgets.QGraphicsView.drawBackground(self, painter, rect)

        scale = math.sqrt(abs(self.transform().determinant())) or 1.0
        if scale < 0.35:
            return

        step = PX_PER_UNIT * 4.0
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setPen(QtGui.QPen(QtGui.QColor(_gridColor), 0))

        x = math.floor(rect.left() / step) * step
        while x < rect.right():
            painter.drawLine(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
            x += step

        y = math.floor(rect.top() / step) * step
        while y < rect.bottom():
            painter.drawLine(QtCore.QLineF(rect.left(), y, rect.right(), y))
            y += step

    ##########################################################################
    # 平移 / 缩放
    ##########################################################################

    # 必须临时切 NoAnchor —— AnchorUnderMouse 会在任何变换改变时重新锚定，
    # 把 translate() 原样抵消掉（表现就是「中键拖了没反应」）。
    # 另外 sceneRect 必须留足余量，否则拖到内容边缘就被夹住、拖不出去。
    def __pan(self, delta):

        scale = math.sqrt(abs(self.transform().determinant())) or 1.0

        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
        self.translate(delta.x() / scale, delta.y() / scale)
        self.setTransformationAnchor(anchor)
        self._rememberCentre()

    ## 平移期间把 item 交互整个关掉。
    #
    # 不关的话，画面在鼠标底下滑过去，鼠标扫到的每条连线都会收到 hover 而亮一下、
    # 节点还会弹 tooltip —— 看着就是「一拖就到处闪」。原生 GraphEditor 平移时也不
    # 做任何 hover 高亮。
    def __beginPan(self, position):

        self.__mode = _MODE_PAN
        self.__panStart = position
        self.__owner._clearWireHover()
        self.__owner._setHoveredNodule(None, None)
        self.__owner._setHoveredAdder(None, None)
        self.__owner._setHoveredSection(None, None, None)
        QtWidgets.QToolTip.hideText()
        self.setInteractive(False)
        self.viewport().setCursor(QtCore.Qt.ClosedHandCursor)

    def __endPan(self):

        self.__mode = _MODE_NONE
        self.setInteractive(True)
        self.viewport().unsetCursor()

        if self.__cutSuspended:
            self.__cutSuspended = False
            self.__mode = _MODE_CUT
            self.viewport().setCursor(QtCore.Qt.CrossCursor)

    ## **Alt + 右键拖 = 缩放**（原生 `ViewportGadget` 的 dolly，`cameraMotionType` 里
    # 「Alt 修饰 + 右键 → Dolly」那一路）。
    #
    # 公式照抄 `ViewportGadget.cpp` 的 `dolly()`：把位移按视口尺寸归一化，
    # `d = dx - dy`（往右 / 往上都是放大），`planarScale *= exp( -1.9 * d )`。
    # `planarScale` 是「一个像素几个单位」，我们的 `zoom()` 是反过来的
    # 「一个单位几个像素」→ 指数换个符号：`zoom = 起始 zoom * exp( 1.9 * d )`。
    #
    # 锚点是**按下那一刻**光标底下那个点（原生 `m_motionStart`），不是当前光标 ——
    # 所以整个手势里画面是"围着按下的地方"缩放。
    def __beginZoom(self, position):

        self.__mode = _MODE_ZOOM
        self.__zoomStart = QtCore.QPoint(position)
        self.__zoomAnchor = self.mapToScene(position)
        self.__zoomStartScale = self.zoom()
        self.__owner._clearWireHover()
        self.__owner._setHoveredNodule(None, None)
        self.__owner._setHoveredAdder(None, None)
        self.__owner._setHoveredSection(None, None, None)
        QtWidgets.QToolTip.hideText()
        self.setInteractive(False)

    def __updateZoom(self, position):

        size = self.viewport().size()
        dx = (position.x() - self.__zoomStart.x()) / max(1.0, float(size.width()))
        dy = (position.y() - self.__zoomStart.y()) / max(1.0, float(size.height()))
        target = self.__zoomStartScale * math.exp(1.9 * (dx - dy))

        current = self.zoom()
        if current < 1e-9:
            return

        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
        try:
            self.scaleBy(target / current)
            after = self.mapToScene(self.__zoomStart)
            self.translate(
                after.x() - self.__zoomAnchor.x(), after.y() - self.__zoomAnchor.y()
            )
        finally:
            self.setTransformationAnchor(anchor)

        self._rememberCentre()

    def __endZoom(self):

        self.__mode = _MODE_NONE
        self.setInteractive(True)

    ## 滚轮缩放。
    #
    # **锚点自己算，别用 `AnchorUnderMouse`** —— 它锚的是 Qt 自己记的
    # `lastMouseMoveScenePoint`，那个只在 `QGraphicsView.mouseMoveEvent` 被调用时才更新，
    # 而我们平移那条路自己处理完就 return 了 → 它一直停在"开始拖之前"那个点，
    # 拖得越远滚一下画面甩得越狠。自己锚：记下光标底下的场景点 → 缩放 → 挪回去。
    def wheelEvent(self, event):

        delta = event.angleDelta().y()
        if not delta:
            # 横向滚轮（鼠标左右拨）：原来会被当成"往下滚"一路缩小，别理它
            event.accept()
            return

        position = _eventPos(event)
        before = self.mapToScene(position)

        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
        try:
            self.scaleBy(1.15 if delta > 0 else 1.0 / 1.15)
            after = self.mapToScene(position)
            self.translate(after.x() - before.x(), after.y() - before.y())
        finally:
            self.setTransformationAnchor(anchor)

        self._rememberCentre()
        event.accept()

    ## 当前缩放倍数（1.0 = `PX_PER_UNIT` 像素一个 Gaffer 单位）。
    def zoom(self):

        return self.transform().m11()

    ## 缩放，**夹在 `MIN_ZOOM` / `MAX_ZOOM` 之间**（上限照原生的 25 像素/单位）。
    # 返回真正用上的倍率。
    def scaleBy(self, factor):

        current = self.zoom()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        factor = target / current if current > 1e-9 else 1.0

        if abs(factor - 1.0) < 1e-9:
            return 1.0

        self.scale(factor, factor)
        return factor

    ## `fitInView` 之后把缩放夹回上限（框一个小节点会一路放大到几十倍）。
    #
    # **围着画面中心缩**：默认的 `AnchorUnderMouse` 会拿 Qt 自己记的那个鼠标场景点
    # 当锚，取景完还要按它挪一下 —— 框住的东西就偏出去了（鼠标离得越远偏得越狠）。
    def _clampZoom(self):

        current = self.zoom()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current))
        if abs(target - current) > 1e-9 and current > 1e-9:
            centre = self.mapToScene(self.viewport().rect().center())
            anchor = self.transformationAnchor()
            self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
            try:
                self.scale(target / current, target / current)
                self.centerOn(centre)
            finally:
                self.setTransformationAnchor(anchor)

    ##########################################################################
    # 视野中心
    ##########################################################################

    # 平移是直接改 transform（NoAnchor，见 __pan），Qt 内部那个 lastCenterPoint
    # **不会**跟着更新。而只要尺寸一变（拖布局分隔条、换 tab、面板重新 parent），
    # QGraphicsView 就按 resizeAnchor 去 `centerOn( lastCenterPoint )` —— 画面直接
    # 跳回平移之前的位置，看着就是「一拖布局，图就弹回中心」。
    # 所以自己记住视野中心，尺寸变了 / 重新显示时对回去。
    __viewCentre = None  # scene 坐标；None = 还没动过，交给 Qt 自己处理
    __restoringCentre = False  # 复位过程里别把复位本身当成用户操作记下来

    def _rememberCentre(self):

        if self.__restoringCentre:
            return
        rect = self.viewport().rect()
        if rect.isEmpty():
            return
        # mapToScene 只吃 QPoint（QPointF 会 TypeError）
        self.__viewCentre = self.mapToScene(rect.center())

    def __restoreCentre(self):

        if self.__viewCentre is None or self.viewport().rect().isEmpty():
            return
        self.__restoringCentre = True
        try:
            # centerOn 顺带把 Qt 的 lastCenterPoint 也校准了
            self.centerOn(self.__viewCentre)
        finally:
            self.__restoringCentre = False

    ## 别的路径（Qt 自己的滚动、ensureVisible…）挪了画面也得记下来，
    # 否则下一次 resize 会把画面拽回上一次记住的位置。
    def scrollContentsBy(self, dx, dy):

        QtWidgets.QGraphicsView.scrollContentsBy(self, dx, dy)
        self._rememberCentre()

    def resizeEvent(self, event):

        # 基类会用（陈旧的）lastCenterPoint 复位一次，那次滚动不能被记成用户操作
        self.__restoringCentre = True
        try:
            QtWidgets.QGraphicsView.resizeEvent(self, event)
        finally:
            self.__restoringCentre = False
        self.__restoreCentre()

    ## 拖布局时面板会被 hide → 换 parent → show，中途尺寸可能是 0，
    # 滚动位置就丢了；显示回来的时候再对一次中心。
    def showEvent(self, event):

        QtWidgets.QGraphicsView.showEvent(self, event)
        self.__restoreCentre()

    ## 图要重建了：把加在 scene 上的临时 item 忘掉。
    #
    # `scene.clear()` 会**销毁**它们的 C++ 对象，Python 包装还留着的话下一次
    # `setPath()` / `removeItem()` 就是 `Internal C++ object already deleted`
    # （按住 X 划线的时候图一重建就崩）。
    def _discardTransientItems(self):

        self.__connectWire = None
        self.__connectDetachItem = None
        self.__cutItem = None
        self.__connectFrom = None
        self.__connectDetach = None
        self.__connectDestination = (None, None)
        self.__cutPoints = []
        self.__cutStroke = False
        self.__cutPressPosition = None
        # 正在拉框的 Backdrop 也是 scene 里的 item，一并放手
        self.__resizeItem = None
        self.__resizeEdges = (0, 0)

        # 划线模式不退：X 还按着，只是没划完的那一笔作废（虚线下一笔会重建）
        if self.__mode in (_MODE_CONNECT, _MODE_RESIZE):
            self.__mode = _MODE_NONE
            self.setInteractive(True)
            self.viewport().unsetCursor()

    ## 现在是不是正在拖节点（自动对齐只在拖动时生效，程序改位置时不能乱吸）。
    def isDraggingNodes(self):

        return self.__mode == _MODE_MOVE

    ## 对齐参考线画在最上层。
    def drawForeground(self, painter, rect):

        QtWidgets.QGraphicsView.drawForeground(self, painter, rect)

        guides = self.__owner.snapGuides()
        if not guides:
            return

        pen = QtGui.QPen(QtGui.QColor(_snapGuideColor), 0, QtCore.Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)

        for guide in guides:

            orientation, coordinate = guide[0], guide[1]

            # 有起终点就只画两个节点之间那一段（Houdini 那种"对上了谁"的感觉）；
            # 没给就退回拉满视口（老格式）。
            if len(guide) > 3:
                start, end = guide[2], guide[3]
            elif orientation == "v":
                start, end = rect.top(), rect.bottom()
            else:
                start, end = rect.left(), rect.right()

            if orientation == "v":
                painter.drawLine(QtCore.QLineF(coordinate, start, coordinate, end))
            else:
                painter.drawLine(QtCore.QLineF(start, coordinate, end, coordinate))

    ##########################################################################
    # 命中测试
    ##########################################################################

    def nodeItemAt(self, position):

        for item in self.items(position):
            if isinstance(item, _NodeItem):
                return item
        return None

    ## 能被选中的 item（节点或 Backdrop）。
    def selectableItemAt(self, position):

        for item in self.items(position):
            if isinstance(item, (_NodeItem, _BackdropItem)):
                return item
        return None

    ## 光标压在哪个 Backdrop 的哪条边上。返回 ( item, horizontal, vertical )。
    #
    # Backdrop 的 `shape()` 只有四条边和标题条（框身是洞），所以直接问 `items()`
    # 就够 —— 但抓手只有 10px 宽，光标可能刚好落在框外一点点，所以照 `adderAt`
    # 那手法在光标周围取一小块再问一遍。
    def backdropEdgeAt(self, position):

        scenePoint = self.mapToScene(position)
        probe = QtCore.QRect(
            position.x() - BACKDROP_EDGE_HIT,
            position.y() - BACKDROP_EDGE_HIT,
            BACKDROP_EDGE_HIT * 2,
            BACKDROP_EDGE_HIT * 2,
        )

        for candidate in self.items(probe):
            if not isinstance(candidate, _BackdropItem):
                continue
            horizontal, vertical = candidate.edgeAt(candidate.mapFromScene(scenePoint))
            if horizontal or vertical:
                return candidate, horizontal, vertical

        return None, 0, 0

    ## 光标压在哪个 Backdrop 上（含标题条，用来决定标题条要不要高亮）。
    def backdropItemAt(self, position):

        for item in self.items(position):
            if isinstance(item, _BackdropItem):
                return item
        return None

    def edgeItemAt(self, position):

        for item in self.items(position):
            if isinstance(item, _EdgeItem):
                return item
        return None

    ## 鼠标底下是哪个接口圆点。返回 ( item, plug )。
    #
    # **圆点是画在卡片边界上的**（顶边那排在卡片外 2px），`shape()` 只比卡片多
    # `NODULE_HIT_RADIUS` 一圈 —— 光标从外面凑近某个圆点时很容易整个落在节点外面，
    # 于是"照着圆点丢过去却接不上"（NameSwitch 的第二个圆点就是这样）。
    # 找不到节点时在光标周围再捞一遍（和 `adderAt` 同一手法）。
    def noduleAt(self, position):

        item = self.nodeItemAt(position)

        if item is None:
            scenePoint = self.mapToScene(position)
            probe = QtCore.QRect(
                position.x() - NODULE_HIT_RADIUS,
                position.y() - NODULE_HIT_RADIUS,
                NODULE_HIT_RADIUS * 2,
                NODULE_HIT_RADIUS * 2,
            )
            best, bestDistance = None, None
            for candidate in self.items(probe):
                if not isinstance(candidate, _NodeItem):
                    continue
                local = candidate.mapFromScene(scenePoint)
                plug = candidate.noduleAt(local)
                if plug is None:
                    continue
                point = candidate.nodulePosition(plug)
                distance = math.hypot(point.x() - local.x(), point.y() - local.y())
                if bestDistance is None or distance < bestDistance:
                    best, bestDistance = (candidate, plug), distance
            if best is not None:
                return best
            return None, None

        plug = item.noduleAt(item.mapFromScene(self.mapToScene(position)))
        return (item, plug) if plug is not None else (item, None)

    ## 鼠标底下有没有「加插口」的 `+`。返回 ( item, 边 )。
    #
    # **不能只问 `nodeItemAt`**：`+` 常常画在卡片**外面**（材质节点那个就在左下角外侧），
    # 而 `shape()` 只包到卡片 + 一点点余量 —— 光标正落在 `+` 上时 `nodeItemAt` 反而
    # 是 None，于是"拖到 + 上没反应"（真机上就是这么发现的）。这里在光标周围取一小块
    # 区域找节点，再问它这块有没有 `+`。
    def adderAt(self, position):

        item = self.nodeItemAt(position)

        if item is None:
            scenePoint = self.mapToScene(position)
            probe = QtCore.QRect(position.x() - 14, position.y() - 14, 28, 28)
            for candidate in self.items(probe):
                if not isinstance(candidate, _NodeItem):
                    continue
                if candidate.adderAt(candidate.mapFromScene(scenePoint)) is not None:
                    item = candidate
                    break

        if item is None:
            return None, None

        section = item.adderAt(item.mapFromScene(self.mapToScene(position)))
        return (item, section) if section is not None else (item, None)

    ## 局部坐标点附近有没有**分栏 header**（画在卡片外面，`nodeItemAt` 找不到）。
    # 返回 ( item, side, 分栏名 )，没有就 ( None, None, None )。
    def sectionHeaderAt(self, position):

        scenePoint = self.mapToScene(position)
        probe = QtCore.QRect(position.x() - 6, position.y() - 6, 12, 12)
        for candidate in self.items(probe):
            if not isinstance(candidate, _NodeItem):
                continue
            found = candidate.sectionAt(candidate.mapFromScene(scenePoint))
            if found is not None:
                return (candidate, found[0], found[1])

        return None, None, None

    ## 光标压在哪个节点的 focus 角标上（没有就 None）。
    #
    # 角标画在卡片右上角**外面**：`shape()` 划进去的是固定尺寸那一块（几何不能跟着
    # lod 变），镜头拉远时角标按 1/lod 长大、会长到 shape 外面去 —— 所以先问
    # `nodeItemAt`，不成再在光标周围取一小块捞一遍（和 `adderAt` /
    # `sectionHeaderAt` 同一手法）。判据仍是节点自己的 `focusFlagAt`，
    # 不会去抢别人的点击。
    def focusTabAt(self, position):

        scenePoint = self.mapToScene(position)
        lod = abs(self.transform().m11()) or None

        item = self.nodeItemAt(position)
        if item is not None:
            if item.focusFlagAt(item.mapFromScene(scenePoint), lod):
                return item
            # 光标正压在**最上面**那个节点的卡片上 → 这一下归卡片（选中 / 拖动），
            # 别让下面那个节点的角标把它抢走。谁在上面谁说话，和画出来的一致。
            if item.cardRect().contains(item.mapFromScene(scenePoint)):
                return None

        probe = QtCore.QRect(
            position.x() - FOCUS_TAB_HIT_PROBE,
            position.y() - FOCUS_TAB_HIT_PROBE,
            FOCUS_TAB_HIT_PROBE * 2,
            FOCUS_TAB_HIT_PROBE * 2,
        )
        for candidate in self.items(probe):
            if not isinstance(candidate, _NodeItem):
                continue
            if candidate.focusFlagAt(candidate.mapFromScene(scenePoint), lod):
                return candidate

        return None

    ##########################################################################
    # 鼠标
    ##########################################################################

    def mousePressEvent(self, event):

        position = _eventPos(event)

        # **一个手势没做完时按下第二个键一律不理**：中键平移中按左键会把模式改成
        # 框选 / 拖动，`__endPan` 永远跑不到，`setInteractive( False )` 和抓手光标
        # 就一直卡着；拖连线时按中键会把临时那根线留在 scene 里。
        if self.__mode not in (_MODE_NONE, _MODE_CUT):
            event.accept()
            return

        # 划线模式（按着 X）：**左键按下才开始划**，右键取消，中键照旧平移
        # （平移期间挂起划线模式，别让平移手势把它的状态冲掉；别的键一律不理）
        if self.__mode == _MODE_CUT:
            self.__gestureButton = event.button()
            if not self.__cutModePress(event, position):
                if event.button() == QtCore.Qt.MiddleButton:
                    self.__cutSuspended = True
                    self.__beginPan(position)
            event.accept()
            return

        self.__gestureButton = event.button()

        # **中键按在节点上 = 把节点拖出去给别的编辑器**（原生 `GraphGadget::dragBegin`
        # 里 `event.buttons == Middle` 那一路：`m_dragMode = Sending`，拖的是选中的那些
        # 节点）。中键按在空白处才是平移 —— 和原生分得一模一样，两者不打架。
        if event.button() == QtCore.Qt.MiddleButton:
            item = self.nodeItemAt(position)
            if item is not None and self.__owner._beginNodeDragOut(item, event):
                event.accept()
                return

        if event.button() == QtCore.Qt.MiddleButton or (
            event.button() == QtCore.Qt.LeftButton
            and (event.modifiers() & QtCore.Qt.AltModifier)
        ):
            self.__beginPan(position)
            event.accept()
            return

        # **Alt + 右键 = 缩放**（原生就是这么按的）。右键菜单要让开 ——
        # `contextMenuEvent` 那边按 Alt / 当前模式挡掉。
        if event.button() == QtCore.Qt.RightButton and (
            event.modifiers() & QtCore.Qt.AltModifier
        ):
            self.__beginZoom(position)
            event.accept()
            return

        if event.button() == QtCore.Qt.LeftButton:
            self.__leftPress(event, position)
            event.accept()
            return

        QtWidgets.QGraphicsView.mousePressEvent(self, event)

    ## 划线模式下的按下：左键开始划、右键取消。处理掉了返回 True（中键留给平移）。
    def __cutModePress(self, event, position):

        if event.button() == QtCore.Qt.LeftButton:
            self.__cutStroke = True
            self.__cutPressPosition = QtCore.QPoint(position)
            self.__cutPoints = [self.mapToScene(position)]
            self.__updateCutLine()
            return True

        if event.button() == QtCore.Qt.RightButton:
            self.__endCutMode()
            return True

        return False

    ## 左键按下的一整条判定链：圆点 → 分栏 header → focus 折角 → 连线 → 节点 → 框选。
    def __leftPress(self, event, position):

        modifiers = QtCore.Qt.KeyboardModifiers(event.modifiers())

        item, plug = self.noduleAt(position)
        if plug is not None and not self.__owner.readOnly():
            self.__pressNodule(item, plug, position)
            return

        # 点在分栏 header 上：收起 / 展开这一栏（Houdini 式）。header 画在
        # 卡片外面，`item` 从上面 `noduleAt` 拿不到 —— 用 `sectionHeaderAt`
        # 在光标附近自己捞，命中就切换，不选中不拖动。
        headerItem, side, section = self.sectionHeaderAt(position)
        if headerItem is not None:
            self.__owner._toggleSection(headerItem.node, side, section)
            return

        # 点在 focus flag 上：切换 focus，不选中也不拖动（和原生 FocusGadget 一样）
        flagItem = self.focusTabAt(position)
        if flagItem is not None:
            self.__owner._toggleNodeFocus(flagItem.node)
            return

        # 连线的命中区比较宽，放在节点判定之后，别抢了节点的点击。
        if item is None and self.__pressEdge(position, modifiers):
            return

        # 压在 Backdrop 的边上 = 拉框改大小（原生 `BackdropNodeGadget::buttonPress`：
        # 命中边缘就自己吃掉这次按下，不交给 GraphGadget 去做选择）
        if item is None and not self.__owner.readOnly():
            backdropItem, horizontal, vertical = self.backdropEdgeAt(position)
            if backdropItem is not None:
                self.__beginResize(backdropItem, horizontal, vertical, position)
                return

        item = item or self.selectableItemAt(position)

        if item is not None:
            self.__pressItem(item, event, modifiers)
            return

        # 空白处：开始框选
        self.__beginBand(position, modifiers)

    ## 按在接口圆点上：已连接的输入圆点是"把这一头拽下来改接/断开"，否则起一根新线。
    #
    # 不这么办的话，按在圆点上拖到空白处是静默无操作 —— 用户以为断开了，原线还挂着，
    # 回头连 `+` 时 NameSwitch 两个槽都占着，`__growArrayPlug` 找不到空槽就多长出一路
    # （"断开 default 再连 + 不行"）。
    def __pressNodule(self, item, plug, position):

        edgeItem, end = self.__owner._edgeItemForPlug(plug)
        if edgeItem is not None and self.__beginReconnect(edgeItem, end, position):
            return

        self.__beginConnect(item, plug, position)

    ## 点在连线上：**靠近两端 = 把这一头拽下来改接**（原生同款），
    # 中间那段 = 选中这条线（Shift 加选，Delete 删）。处理掉了返回 True。
    def __pressEdge(self, position, modifiers):

        edgeItem = self.edgeItemAt(position)
        if edgeItem is None:
            return False

        end = edgeItem.endAt(self.mapToScene(position))
        if end is not None and not self.__owner.readOnly():
            if self.__beginReconnect(edgeItem, end, position):
                return True

        self.__owner._selectEdgeClicked(edgeItem, modifiers)
        self.__mode = _MODE_NONE
        return True

    ## 点在节点 / Backdrop 上：选择规则逐条抄原生 `GraphGadget::buttonPress`：
    #   已选中 + Ctrl  -> 取消选中（不进入拖动）
    #   已选中        -> 保持不动（好让你拖整组）
    #   没选中        -> 没按 Shift/Ctrl 先清空，再加进去
    #   Alt+Shift / Alt+Ctrl -> 连上游 / 下游一起选
    def __pressItem(self, item, event, modifiers):

        if self.__owner._selectClicked(item, modifiers):
            self.__mode = _MODE_NONE
            return

        self.__resetDragTracking()
        self.__mode = _MODE_MOVE

        # 选择已经由我们摆平了，Qt 只负责拖动 —— 所以把修饰键抹掉再交给它，
        # 否则 Qt 会用自己那套（Ctrl 切换、Shift 当普通点击）把选择改回去。
        #
        # 光抹修饰键还不够：`QGraphicsScene` 在「没有 item 接受这次按下」时会
        # 直接 `clearSelection()`（Shift 多选会被这样清空）。所以按下
        # 前后各记一次、对不上就对回去 —— 松手那边同理。
        selectionBefore = self.__owner._selectedSceneItems()
        self.__owner._setSelectionSyncSuspended(True)
        try:
            QtWidgets.QGraphicsView.mousePressEvent(
                self, self.__withoutModifiers(event)
            )
            self.__owner._restoreSceneSelection(selectionBefore)
        finally:
            self.__owner._setSelectionSyncSuspended(False)
        self.__owner._flushSelectionToScript()

    def __withoutModifiers(self, event):

        return QtGui.QMouseEvent(
            event.type(),
            QtCore.QPointF(_eventPos(event)),
            QtCore.QPointF(_globalPos(event)),
            event.button(),
            event.buttons(),
            QtCore.Qt.NoModifier,
        )

    ##########################################################################
    # 拖到边缘画面自己跟着滚（原生 ViewportGadget::trackDrag）
    ##########################################################################

    ## 每次拖动的鼠标移动都过一遍：算出「画面该以多快往哪滚」。
    #
    # 语义逐条照 `ViewportGadget.cpp:1825`：视口往里缩一圈 `borderWidth =
    # min( min(w,h)/8, 60 )` 当"不滚区"，光标出了这圈才滚；速度从 0 线性升到
    # 边上最大、出了视口不再更快；**门槛取历史最小值**，这样在边缘区里起拖、
    # 往中间拖的时候不会一上手就滚。
    def __updateDragTracking(self, position):

        if not self.interacting():
            self.__stopDragTracking()
            return

        size = self.viewport().size()
        border = min(min(size.width(), size.height()) / 8.0, DRAG_TRACK_BORDER)
        if border <= 0.0:
            self.__stopDragTracking()
            return

        inset = QtCore.QRectF(
            border,
            border,
            max(0.0, size.width() - border * 2.0),
            max(0.0, size.height() - border * 2.0),
        )

        offset = QtCore.QPointF(0.0, 0.0)
        if not inset.contains(QtCore.QPointF(position)):
            offset = QtCore.QPointF(
                min(max(position.x(), inset.left()), inset.right()) - position.x(),
                min(max(position.y(), inset.top()), inset.bottom()) - position.y(),
            )
            offset = QtCore.QPointF(-offset.x(), -offset.y())

        # **归一化要用真实长度，夹住的那个只用来算速度系数** —— 拿夹过的长度去
        # 归一，光标拖到视口外老远时方向向量会被放大好几倍（实测 460 vs 上限 60）。
        rawLength = math.hypot(offset.x(), offset.y())
        length = min(rawLength, border)
        self.__dragTrackThreshold = min(length, self.__dragTrackThreshold)

        if rawLength <= 1e-4:
            self.__stopDragTracking()
            return

        # lerpfactor( length, threshold, border )：门槛以内是 0，到边上是 1
        span = border - self.__dragTrackThreshold
        factor = 0.0 if span <= 1e-6 else (length - self.__dragTrackThreshold) / span
        factor = min(max(factor, 0.0), 1.0)

        self.__dragTrackVelocity = QtCore.QPointF(
            -offset.x() / rawLength * border * factor,
            -offset.y() / rawLength * border * factor,
        )
        self.__dragTrackPosition = QtCore.QPoint(position)

        if factor <= 1e-4:
            self.__stopDragTracking()
        elif not self.__dragTrackTimer.isActive():
            self.__dragTrackTimer.start()

    ## 定时器：滚一小步，然后**补一次鼠标移动**（画面动了，手上拖的那个东西
    # 相对图的位置也跟着变 —— 原生同样在这儿 fake 一个 dragMove）。
    def __trackDragIdle(self):

        if not self.interacting():
            self.__stopDragTracking()
            return

        step = DRAG_TRACK_INTERVAL / 1000.0 * DRAG_TRACK_SPEED
        self.__pan(
            QtCore.QPointF(
                self.__dragTrackVelocity.x() * step,
                self.__dragTrackVelocity.y() * step,
            )
        )

        position = self.__dragTrackPosition
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(position),
            QtCore.QPointF(self.viewport().mapToGlobal(position)),
            QtCore.Qt.NoButton,
            QtWidgets.QApplication.mouseButtons(),
            QtWidgets.QApplication.keyboardModifiers(),
        )
        self.mouseMoveEvent(event)

    def __stopDragTracking(self):

        if self.__dragTrackTimer.isActive():
            self.__dragTrackTimer.stop()
        self.__dragTrackVelocity = QtCore.QPointF()

    ## 拖动一开始把门槛复位成"整圈"，这样起拖点就在边缘区里时不会立刻滚。
    def __resetDragTracking(self):

        self.__stopDragTracking()
        self.__dragTrackThreshold = DRAG_TRACK_BORDER

    ##########################################################################
    # 拉 Backdrop 的框（原生 BackdropNodeGadget 的 dragMove）
    ##########################################################################

    def __beginResize(self, item, horizontal, vertical, position):

        self.__resetDragTracking()
        self.__mode = _MODE_RESIZE
        self.__resizeItem = item
        self.__resizeEdges = (horizontal, vertical)
        self.__applyResizeCursor(horizontal, vertical)

    def __updateResize(self, position):

        item = self.__resizeItem
        if item is None or item.scene() is None:
            return

        horizontal, vertical = self.__resizeEdges
        self.__owner._resizeBackdrop(
            item, horizontal, vertical, self.mapToScene(position)
        )

    def __endResize(self):

        item = self.__resizeItem
        self.__mode = _MODE_NONE
        self.__resizeItem = None
        self.__resizeEdges = (0, 0)
        self.viewport().unsetCursor()

        if item is not None and item.scene() is not None:
            self.__owner._commitBackdropResize(item)

    ## 光标形状照原生（`moveHorizontally` / `moveVertically` / 两种对角）。
    def __applyResizeCursor(self, horizontal, vertical):

        if horizontal and vertical:
            # y 向上算：( 左, 下 ) / ( 右, 上 ) 是 "/" 那条对角
            self.viewport().setCursor(
                QtCore.Qt.SizeBDiagCursor
                if horizontal * vertical > 0
                else QtCore.Qt.SizeFDiagCursor
            )
        elif horizontal:
            self.viewport().setCursor(QtCore.Qt.SizeHorCursor)
        elif vertical:
            self.viewport().setCursor(QtCore.Qt.SizeVerCursor)
        else:
            self.viewport().unsetCursor()

    ## 空着手移动一次要回答的全部问题（圆点 / `+` / 分栏三角 / Backdrop 边与框身）
    # 只查 **一次** scene。语义和 `noduleAt` / `adderAt` / `sectionHeaderAt` /
    # `backdropEdgeAt` / `backdropItemAt` 逐个问完全一致（那几个留给别的调用方）——
    # 逐个问要 `items()` 七八次，每次都对探针附近每个 item 过一遍 `boundingRect`
    # 和 `shape`，600 个节点的图上一次鼠标移动要 3ms 以上。
    def __updateHover(self, position):

        scenePoint = self.mapToScene(position)
        # Qt 的 `items( QPoint )` 拿的是这一个像素映射到 scene 的那个小矩形和
        # `shape()` 求交 —— 照抄这个判据，别用 `contains()`（亚像素上会差）
        pixelRect = self.mapToScene(QtCore.QRect(position, QtCore.QSize(1, 1)))
        pixelRect = pixelRect.boundingRect()

        reach = int(max(14, NODULE_HIT_RADIUS, BACKDROP_EDGE_HIT))
        probe = QtCore.QRect(
            position.x() - reach, position.y() - reach, reach * 2, reach * 2
        )
        nodes = []
        backdrops = []
        for candidate in self.items(probe):  # 已按叠放顺序（上层在前）
            if isinstance(candidate, _NodeItem):
                nodes.append(candidate)
            elif isinstance(candidate, _BackdropItem):
                backdrops.append(candidate)

        def hitsPoint(item):
            return item.shape().intersects(item.mapFromScene(pixelRect).boundingRect())

        under = None
        for candidate in nodes:
            if hitsPoint(candidate):
                under = candidate
                break

        # --- 圆点（同 `noduleAt`）---
        item, plug = None, None
        if under is not None:
            item = under
            plug = under.noduleAt(under.mapFromScene(scenePoint))
        else:
            bestDistance = None
            for candidate in nodes:
                local = candidate.mapFromScene(scenePoint)
                found = candidate.noduleAt(local)
                if found is None:
                    continue
                point = candidate.nodulePosition(found)
                distance = math.hypot(point.x() - local.x(), point.y() - local.y())
                if bestDistance is None or distance < bestDistance:
                    item, plug, bestDistance = candidate, found, distance
        self.__owner._setHoveredNodule(item, plug)

        # --- `+`（同 `adderAt`，只在没压着圆点时找）---
        adderItem, section = None, None
        if plug is None:
            adderItem = under
            if adderItem is None:
                for candidate in nodes:
                    if (
                        candidate.adderAt(candidate.mapFromScene(scenePoint))
                        is not None
                    ):
                        adderItem = candidate
                        break
            if adderItem is not None:
                section = adderItem.adderAt(adderItem.mapFromScene(scenePoint))
                if section is None:
                    adderItem = None
        self.__owner._setHoveredAdder(adderItem, section)

        # --- 分栏三角 / 栏名行（同 `sectionHeaderAt`）---
        headerItem, side, headerName = None, None, None
        if plug is None and section is None:
            for candidate in nodes:
                found = candidate.sectionAt(candidate.mapFromScene(scenePoint))
                if found is not None:
                    headerItem, side, headerName = candidate, found[0], found[1]
                    break
        self.__owner._setHoveredSection(headerItem, side, headerName)

        if plug is not None or section is not None or headerItem is not None:
            self.__owner._setHoveredBackdrop(None)
            return

        # --- Backdrop：先看边（换光标），再看框身 / 标题条（高亮）---
        backdrop, horizontal, vertical = None, 0, 0
        for candidate in backdrops:
            h, v = candidate.edgeAt(candidate.mapFromScene(scenePoint))
            if h or v:
                backdrop, horizontal, vertical = candidate, h, v
                break
        if backdrop is None:
            for candidate in backdrops:
                if hitsPoint(candidate):
                    backdrop = candidate
                    break

        self.__applyResizeCursor(horizontal, vertical)
        self.__owner._setHoveredBackdrop(
            backdrop
            if (backdrop is not None and not (horizontal or vertical))
            else None
        )

    ##########################################################################
    # 框选（自绘，为了支持 Shift 加选 / Ctrl 减选 + 完全框住才算）
    ##########################################################################

    def __beginBand(self, position, modifiers):

        self.__resetDragTracking()
        self.__mode = _MODE_BAND
        self.__bandOrigin = position
        self.__bandModifiers = modifiers

        # 原生：空白处按下就清空选择，除非按着 Shift/Ctrl（那是要改选择）
        if not (modifiers & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier)):
            self.__owner._clearSelection()
            self.__owner._clearEdgeSelection()

        if self.__band is None:
            self.__band = QtWidgets.QRubberBand(
                QtWidgets.QRubberBand.Rectangle, self.viewport()
            )
        self.__band.setGeometry(QtCore.QRect(position, QtCore.QSize()))
        self.__band.show()

    def __updateBand(self, position):

        if self.__band is not None:
            self.__band.setGeometry(
                QtCore.QRect(self.__bandOrigin, position).normalized()
            )

    def __endBand(self, position):

        rect = QtCore.QRect(self.__bandOrigin, position).normalized()
        modifiers = self.__bandModifiers

        self.__mode = _MODE_NONE
        self.__bandModifiers = QtCore.Qt.NoModifier
        if self.__band is not None:
            self.__band.hide()

        if rect.width() < 2 and rect.height() < 2:
            return

        self.__owner._applyBandSelection(
            self.mapToScene(rect).boundingRect(),
            remove=bool(modifiers & QtCore.Qt.ControlModifier),
        )

    # Qt 默认拿 Tab 做焦点切换，不挡掉的话 keyPressEvent 永远收不到 Tab。
    def focusNextPrevChild(self, nextChild):

        return False

    def mouseMoveEvent(self, event):

        position = _eventPos(event)

        if self.__mode == _MODE_PAN:
            self.__pan(position - self.__panStart)
            self.__panStart = position
            event.accept()
            return

        if self.__mode == _MODE_ZOOM:
            self.__updateZoom(position)
            event.accept()
            return

        if self.__mode == _MODE_CONNECT:
            self.__updateConnectWire(position)
            self.__updateDragTracking(position)
            event.accept()
            return

        if self.__mode == _MODE_RESIZE:
            self.__updateResize(position)
            self.__updateDragTracking(position)
            event.accept()
            return

        if self.__mode == _MODE_CUT:
            # **只有按着左键才画**（手感：按住 X → 左键划 → 松开 X）
            if self.__cutStroke:
                self.__cutPoints.append(self.mapToScene(position))
                self.__updateCutLine()
            event.accept()
            return

        if self.__mode == _MODE_BAND:
            self.__updateBand(position)
            self.__updateDragTracking(position)
            event.accept()
            return

        # 空着手移动时跟踪鼠标底下的接口圆点（悬停放大 + 显示插口名）与 `+`
        if self.__mode == _MODE_NONE:
            self.__updateHover(position)

        QtWidgets.QGraphicsView.mouseMoveEvent(self, event)

        # 拖着单个节点压过一根线 → 把那根线点亮（松手就塞进去）。**必须放在基类之后**：
        # item 是在基类里被挪动的，先算候选的话拿的还是上一帧的位置。
        if self.__mode == _MODE_MOVE:
            self.__owner._updateInsertCandidate()
            self.__updateDragTracking(position)

    def leaveEvent(self, event):

        self.__owner._setHoveredNodule(None, None)
        self.__owner._setHoveredAdder(None, None)
        self.__owner._setHoveredSection(None, None, None)
        self.__owner._setHoveredBackdrop(None)
        QtWidgets.QGraphicsView.leaveEvent(self, event)

    ## 手上是不是正在做一件"按着不放"的事（拖节点 / 拉线 / 框选 / 划线）。
    # 重建期间 item 会被删掉重做，Qt 的鼠标抓取跟着没，手上这一下就静默失效了 ——
    # 所以这期间一律不重建，松手再补。
    def interacting(self):

        return self.__mode in (
            _MODE_MOVE,
            _MODE_CONNECT,
            _MODE_BAND,
            _MODE_CUT,
            _MODE_RESIZE,
        )

    def mouseReleaseEvent(self, event):

        self.__stopDragTracking()
        try:
            self.__mouseReleaseEvent(event)
        finally:
            # 手松开了，把拖动期间推迟下来的重建补上（`interacting()` 这时已经是 False）
            self.__owner._flushPostponedUpdate()

    def __mouseReleaseEvent(self, event):

        position = _eventPos(event)

        # 松开的不是按出这个手势的那个键（左键拖着节点时按了下右键那种）→ 不算结束
        if (
            self.__mode not in (_MODE_NONE, _MODE_CUT)
            and self.__gestureButton is not None
            and event.button() != self.__gestureButton
        ):
            event.accept()
            return

        if self.__mode == _MODE_PAN:
            self.__endPan()
            event.accept()
            return

        if self.__mode == _MODE_ZOOM:
            self.__endZoom()
            event.accept()
            return

        if self.__mode == _MODE_CONNECT:
            self.__endConnect(position)
            event.accept()
            return

        if self.__mode == _MODE_RESIZE:
            self.__endResize()
            event.accept()
            return

        if self.__mode == _MODE_BAND:
            self.__endBand(position)
            event.accept()
            return

        if self.__mode == _MODE_CUT:
            # 松开左键 = 这一笔切下去；X 还按着的话可以接着划下一笔
            if event.button() == QtCore.Qt.LeftButton and self.__cutStroke:
                self.__cutStroke = False
                # **只是"点"了一下**（没划）→ 删光标底下那一样东西：先看连线，
                # 没有连线就删那个节点（X + 左键点线删线、点节点删节点）
                if self.__cutWasClick(position):
                    self.__cutPoints = []
                    self.__updateCutLine()
                    self.__cutClick(position)
                    return
                self.__applyCut(keepMode=True)
            return

        wasMoving = self.__mode == _MODE_MOVE
        self.__mode = _MODE_NONE

        # Qt 的 `QGraphicsItem::mouseReleaseEvent` 里有一段：鼠标没移动、又没按 Ctrl 的话，
        # **把别的 item 全取消选中、只留这一个**。所以 Shift 多选点完一松手就塌回单选。
        # 我们自己那套选择规则（`_selectClicked`）在按下时就已经算好了，这里把它护住：
        # 记下松手前的选择，基类跑完再对回去。
        selectionBefore = None
        if wasMoving:
            selectionBefore = [item for item in self.__owner._selectedSceneItems()]

        # 基类会先按它自己那套改一遍选择，兜回来之前不要写回 script ——
        # 一来一回的 remove + add 会把「最后加进来的节点」换成先选的那个，
        # 跟着 node set 走的面板就会在 Shift 加选后弹回去（见
        # `_setSelectionSyncSuspended`）。
        self.__owner._setSelectionSyncSuspended(True)
        try:
            QtWidgets.QGraphicsView.mouseReleaseEvent(self, event)

            if selectionBefore is not None:
                self.__owner._restoreSceneSelection(selectionBefore)
        finally:
            self.__owner._setSelectionSyncSuspended(False)

        if wasMoving:
            self.__owner._clearSnapGuides()
            # 写位置；压在某根线上松手 = 把这个节点**塞进那根线**（原生 `dragEnd` 里的
            # `m_dragReconnectCandidate`）。两件事一步撤销。
            self.__owner._commitDrag()

        # 选择在**松手时**才写回 script。拖框过程中每帧写会让 NodeEditor
        # 把所有节点跳一遍，很卡。
        self.__owner._flushSelectionToScript()

    ## 双击 = 打开浮动 NodeEditor，和原生一样
    # （`startup/gui/graphEditor.py` 的 `__nodeDoubleClick`）。
    # 进 Box 走上下键 / 右键菜单，不走双击。
    def mouseDoubleClickEvent(self, event):

        # 快速点两下时第二下是 DoubleClick 事件：划线模式里它得照样算一次「点」，
        # 手势进行中照样不理 —— 都交给按下那条判定链
        if self.__mode != _MODE_NONE:
            self.mousePressEvent(event)
            return

        item = self.nodeItemAt(_eventPos(event))
        if item is not None:
            self.__owner._editNode(item.node)
            event.accept()
            return

        QtWidgets.QGraphicsView.mouseDoubleClickEvent(self, event)

    def contextMenuEvent(self, event):

        # 划线模式下右键只是取消，不弹菜单
        if self.__mode == _MODE_CUT:
            self.__endCutMode()
            event.accept()
            return

        # **Alt + 右键是缩放手势**（X11 上右键一按下 Qt 就发 ContextMenu 事件），
        # 不能顺手把菜单弹出来 —— 一弹就把手势打断，缩放变成"点一下出菜单"。
        if self.__mode == _MODE_ZOOM or (event.modifiers() & QtCore.Qt.AltModifier):
            event.accept()
            return

        position = _eventPos(event)
        item = self.nodeItemAt(position)
        # 点在接口圆点上 → 走**插口**菜单（原生 `plugContextMenuSignal`：提升到 Box /
        # 取消提升 / Dot 的方向 / 插口可见性…… 官方注册了 6 处）
        nodule = self.noduleAt(position) if item is not None else None
        edge = self.edgeItemAt(position) if item is None else None

        self.__owner._showContextMenu(
            item,
            edge,
            _globalPos(event),
            self.mapToScene(position),
            plug=nodule[1] if nodule is not None else None,
        )
        event.accept()

    ##########################################################################
    # 连线拖拽
    ##########################################################################

    ## 抓住连线的一头往外拖 = 改接。
    #
    # 规矩照原生 `StandardConnectionGadget::dragBegin`：
    # * 抓**目的地**那头（"dst"）→ 手里攥着的是**源插口**，找一个新的输入落下去；
    # * 抓**源**那头（"src"）→ 攥着的是**目的地插口**，找一个新的输出。
    # 松手时不管落在哪儿，原来那根线都断掉（落在别的接口上就顺手接新的）。
    def __beginReconnect(self, edgeItem, end, position):

        edge = edgeItem.edge
        srcItem = self.__owner._nodeItem(edge.srcNode.getName())
        dstItem = self.__owner._nodeItem(edge.dstNode.getName())
        if srcItem is None or dstItem is None:
            return False

        # **把原来那条线藏起来**：不藏的话拖的时候屏幕上是两条 —— 一条跟着鼠标走的新线，
        # 一条还赖在原地的旧线。松手要是没接成，再让它显示回来。
        if end == "dst":
            self.__beginConnect(srcItem, edge.srcPlug, position, detach=edge)
        else:
            self.__beginConnect(dstItem, edge.dstPlug, position, detach=edge)

        edgeItem.setVisible(False)
        self.__connectDetachItem = edgeItem

        return True

    def __beginConnect(self, item, plug, position, detach=None):

        self.__resetDragTracking()
        self.__mode = _MODE_CONNECT
        self.__connectFrom = (item, plug)
        self.__connectDetach = detach
        self.__connectDetachItem = None

        self.__connectWire = QtWidgets.QGraphicsPathItem()
        self.__connectWire.setZValue(50)
        self.__connectWire.setPen(
            QtGui.QPen(
                QtGui.QColor(_dragWireColor),
                2.0,
                QtCore.Qt.SolidLine,
                QtCore.Qt.RoundCap,
            )
        )
        self.scene().addItem(self.__connectWire)
        self.__updateConnectWire(position)

    ## 拖连线时的目标：**照原生 `StandardNodeGadget::closestDragDestination`** ——
    # 鼠标落在某个节点上，就在它身上挑一个**最近的、接得上的**接口，不用精确点到圆点。
    def __dragDestination(self, position):

        if self.__connectFrom is None:
            return (None, None)

        fromItem, fromPlug = self.__connectFrom

        item = self.nodeItemAt(position)
        if item is None:
            # 光标在卡片外面一点（圆点就画在卡片边界上，照着圆点丢很容易整个落在卡外）
            # —— 在光标周围再捞一遍最近的节点，不然"照着圆点丢过去却接不上"
            # （NameSwitch 的第二个圆点就是这样）。
            item = self.__nearestNodeItem(position, CONNECT_REACH)
        if item is None or item.nodeName == fromItem.nodeName:
            return (None, None)

        localPosition = item.mapFromScene(self.mapToScene(position))

        # 正好压在某个圆点上就用它
        plug = item.noduleAt(localPosition)
        if plug is not None:
            outward = fromPlug.direction() == Gaffer.Plug.Direction.Out
            pair = (fromPlug, plug) if outward else (plug, fromPlug)
            if canConnect(*pair):
                return (item, plug)

        # 否则挑这个节点上最近的兼容接口
        best, bestDistance = None, None
        for candidate in candidatePlugs(item.node, fromPlug):
            point = item.nodulePosition(candidate)
            distance = math.hypot(
                point.x() - localPosition.x(), point.y() - localPosition.y()
            )
            if bestDistance is None or distance < bestDistance:
                best, bestDistance = candidate, distance

        return (item, best) if best is not None else (item, None)

    ## 光标离这个接口够不够近（够近才吸线）。
    def __withinSnapDistance(self, item, plug, position):

        if item is None or plug is None:
            return False

        point = item.nodulePosition(plug)
        if point is None:
            return False

        local = item.mapFromScene(self.mapToScene(position))
        return (
            math.hypot(point.x() - local.x(), point.y() - local.y())
            <= CONNECT_SNAP_DISTANCE
        )

    ## 光标周围 `reach` 像素内最近的那个节点 item（找不到 None）。
    def __nearestNodeItem(self, position, reach):

        scenePoint = self.mapToScene(position)
        probe = QtCore.QRect(
            int(position.x() - reach),
            int(position.y() - reach),
            int(reach * 2),
            int(reach * 2),
        )

        best, bestDistance = None, None
        for candidate in self.items(probe):

            if not isinstance(candidate, _NodeItem):
                continue

            local = candidate.mapFromScene(scenePoint)
            card = candidate.cardRect()
            dx = max(card.left() - local.x(), 0.0, local.x() - card.right())
            dy = max(card.top() - local.y(), 0.0, local.y() - card.bottom())
            distance = math.hypot(dx, dy)
            if bestDistance is None or distance < bestDistance:
                best, bestDistance = candidate, distance

        return best

    def __updateConnectWire(self, position):

        if self.__connectFrom is None:
            return

        item, plug = self.__connectFrom
        p0 = item.mapToScene(item.nodulePosition(plug))
        t0 = item.noduleTangent(plug)

        targetItem, targetPlug = self.__dragDestination(position)
        self.__connectDestination = (targetItem, targetPlug)

        # **够近才吸**（见 `CONNECT_SNAP_DISTANCE`）：不够近的话线继续跟着鼠标走，
        # 但 `__connectDestination` 照旧记着"松手会接哪一个"（原生那套落在节点身上
        # 就接最近的行为不变）。
        snapPlug = (
            targetPlug
            if self.__withinSnapDistance(targetItem, targetPlug, position)
            else None
        )

        # **落在 `+` 上也要给反馈**：材质节点的参数默认全是藏起来的，`+` 就是"还有一堆
        # 参数在这儿"的入口 —— 拖过去的时候把它点亮，松手才知道会弹菜单。
        # `+` 常常画在卡片外面，`__dragDestination`（按节点命中）根本找不到它。
        # 判据不是 `targetPlug is None`：`__dragDestination` 落在节点身上会**自动挑一个
        # 最近的接得上的接口**（哪怕光标离它老远），所以拖到 `+` 上时它给的是某个参数 ——
        # 只有光标**正压在某个圆点上**才让圆点赢，否则 `+` 优先。
        adderItem, adderSection = self.adderAt(position)
        if adderSection is not None and self.noduleAt(position)[1] is None:
            self.__owner._setHoveredAdder(adderItem, adderSection)
            self.__owner._setHoveredNodule(None, None)
            self.__owner._setDropTarget(adderItem, plug)
            p1 = adderItem.mapToScene(adderItem.adderSections()[adderSection])
            self.__setConnectWirePath(
                p0,
                t0,
                p1,
                _sectionTangent(adderSection),
                (item.sceneCardRect(), adderItem.sceneCardRect()),
            )
            return

        self.__owner._setHoveredAdder(None, None)

        avoid = [item.sceneCardRect()]
        if snapPlug is not None:
            # **吸附**到目标接口上，并让那个圆点放大高亮（原生就是这个反馈）
            p1 = targetItem.mapToScene(targetItem.nodulePosition(snapPlug))
            t1 = targetItem.noduleTangent(snapPlug)
            avoid.append(targetItem.sceneCardRect())
            self.__owner._setHoveredNodule(targetItem, snapPlug)
            self.__owner._setDropTarget(targetItem, plug)
        else:
            p1 = self.mapToScene(position)
            t1 = QtCore.QPointF(-t0.x(), -t0.y())
            self.__owner._setHoveredNodule(None, None)
            self.__owner._setDropTarget(targetItem, plug)

        self.__setConnectWirePath(p0, t0, p1, t1, avoid)

    def __setConnectWirePath(self, p0, t0, p1, t1, avoid):

        if self.__connectWire is None:
            return

        try:
            self.__connectWire.setPath(
                _wirePath(p0, t0, p1, t1, self.__owner.getWireStyle(), avoid)
            )
        except RuntimeError:
            self.__connectWire = None  # 被重建销毁了

    def __endConnect(self, position):

        if self.__connectWire is not None:
            try:
                self.scene().removeItem(self.__connectWire)
            except RuntimeError:
                pass
            self.__connectWire = None

        if self.__connectFrom is None:
            self.__mode = _MODE_NONE
            return

        fromItem, fromPlug = self.__connectFrom
        detach = self.__connectDetach
        detachItem = self.__connectDetachItem
        self.__connectFrom = None
        self.__connectDetach = None
        self.__connectDetachItem = None
        self.__mode = _MODE_NONE

        ## 藏起来的那条旧线：接成了的话它下一拍会被重建掉；要是这一下什么都没发生
        # （接不上），得让它显示回来，否则线就"凭空消失"了。
        def restoreDetached():

            if detachItem is None:
                return
            try:
                if detachItem.scene() is not None:
                    detachItem.setVisible(True)
            except RuntimeError:
                pass

        # 吸附时已经算好目标了，直接用它（和松手位置差一点也照连，原生就是这个手感）
        targetItem, targetPlug = self.__connectDestination
        self.__connectDestination = (None, None)
        self.__owner._setHoveredNodule(None, None)
        self.__owner._setHoveredAdder(None, None)
        self.__owner._setDropTarget(None)

        # **先看是不是丢在 `+` 上**。这一步必须在"找不到目标就断开"之前 ——
        # `+` 画在卡片外面，按节点命中根本找不着它（真机上就是这么"拖上去没反应"的）。
        adderItem, adderSection = self.adderAt(position)
        if adderSection is not None and self.noduleAt(position)[1] is None:
            if self.__owner._createPromotedConnection(
                adderItem.node, adderSection, fromPlug
            ):
                restoreDetached()
                return

        if targetItem is None:
            targetItem, targetPlug = self.noduleAt(position)

        if targetItem is None or targetItem.node.getName() == fromItem.node.getName():
            # 改接时落在空白处 / 落回自己身上 = 把这根线断掉（原生也是这个手感）
            if detach is not None:
                self.__owner._disconnect([detach])
            else:
                restoreDetached()
            return

        # （落在 `+` 上的那条路已经在上面处理过了）

        self.__owner._createConnection(
            fromPlug,
            targetItem.node,
            targetPlug,
            self.viewport().mapToGlobal(position),
            detach=detach,
        )
        restoreDetached()

    ##########################################################################
    # 键盘
    ##########################################################################

    ## 我们自己实现的快捷键要盖过菜单栏上的同名 QAction。
    #
    # Qt 里 QAction 的快捷键在 ShortcutOverride 阶段就把键抢走了，widget 的
    # keyPressEvent 根本收不到。菜单栏的 Edit 菜单（Ctrl+C/V/X/D、Delete、Ctrl+A…）
    # 走的是 `EditMenu.scope()`，那玩意儿只认 GraphEditor —— 我们在 Box 里的时候
    # 它会拿错 parent。所以这些键在这儿被我们截下来自己处理。
    __overrideKeys = {
        (QtCore.Qt.Key_C, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_X, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_V, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_D, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_A, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_A, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier),
        (QtCore.Qt.Key_L, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_F, QtCore.Qt.ControlModifier),
        (QtCore.Qt.Key_F2, QtCore.Qt.NoModifier),
        (QtCore.Qt.Key_Delete, QtCore.Qt.NoModifier),
        (QtCore.Qt.Key_Backspace, QtCore.Qt.NoModifier),
        (QtCore.Qt.Key_QuoteLeft, QtCore.Qt.ControlModifier),
    }

    ## `QGraphicsView` 继承 `QAbstractScrollArea`，这几个键**默认是用来滚画面的**。
    # 原生 GraphEditor 是 GL 视图、压根没有滚动条：没进 Box 的时候按上下键，原生一动不动，
    # 我们这儿画面却会上下挪。谁都没要的话就吞掉，别交给基类。
    __scrollKeys = {
        QtCore.Qt.Key_Up,
        QtCore.Qt.Key_Down,
        QtCore.Qt.Key_Left,
        QtCore.Qt.Key_Right,
        QtCore.Qt.Key_PageUp,
        QtCore.Qt.Key_PageDown,
        QtCore.Qt.Key_Home,
        QtCore.Qt.Key_End,
    }

    def event(self, event):

        if event.type() == QtCore.QEvent.ShortcutOverride:
            key = (event.key(), QtCore.Qt.KeyboardModifiers(event.modifiers()))
            if key in self.__overrideKeys:
                event.accept()
                return True

        return QtWidgets.QGraphicsView.event(self, event)

    def keyPressEvent(self, event):

        # 自动重复的按键一律不管 —— 它是「划线一直闪」的根因，别的快捷键也没必要连发
        if event.isAutoRepeat():
            event.accept()
            return

        if self.__handleKey(event):
            event.accept()
            return

        # 我们没接的键，交给 pipeline 注册在 `GraphEditor.instanceCreatedSignal` 上的
        # 那些快捷键 —— 一次性全接上，以后加新的也自动跟着有。
        if self.__owner._forwardShortcutKey(event):
            event.accept()
            return

        # 方向键 / PageUp·Down / Home·End 到这儿就到头了 —— 再往下基类会拿它们滚画面
        # （见 `__scrollKeys`）。转发那步在前面，pipeline 要是把方向键注册成快捷键，
        # 照样接得到。
        if event.key() in self.__scrollKeys:
            event.accept()
            return

        # 再没人要就往上传（Gaffer 的 Editor 会拿到，菜单栏快捷键也还在）
        QtWidgets.QGraphicsView.keyPressEvent(self, event)

    ## 快捷键逐条对齐原生 `GraphEditor.__keyPress` + `EditMenu` + `GraphBookmarksUI`。
    def __handleKey(self, event):

        key = event.key()
        modifiers = QtCore.Qt.KeyboardModifiers(event.modifiers())
        owner = self.__owner

        control = bool(modifiers & QtCore.Qt.ControlModifier)
        shift = bool(modifiers & QtCore.Qt.ShiftModifier)
        alt = bool(modifiers & QtCore.Qt.AltModifier)
        plain = not (control or shift or alt)

        # --- 取景 / focus ---
        if key == QtCore.Qt.Key_F and plain:
            self.frameSelection()
            return True
        if key == QtCore.Qt.Key_QuoteLeft and plain:
            owner._frameFocus()
            return True
        if key == QtCore.Qt.Key_QuoteLeft and modifiers == QtCore.Qt.ControlModifier:
            owner._focusSelection()
            return True

        # --- 层级导航（和原生一样是上下键）---
        if key == QtCore.Qt.Key_Down and (
            plain or modifiers == (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier)
        ):
            return owner._enterSelectedNode(withModifiers=not plain)
        if key == QtCore.Qt.Key_Up and plain:
            return owner._leaveNode()
        if key == QtCore.Qt.Key_BracketLeft and plain:
            return owner._previousRoot()
        if key == QtCore.Qt.Key_BracketRight and plain:
            return owner._nextRoot()

        # --- 建节点 ---
        if key == QtCore.Qt.Key_Tab and plain:
            owner._popupNodeMenu(QtGui.QCursor.pos())
            return True

        # --- 停用 / 启用 ---
        if key == QtCore.Qt.Key_D and plain:
            owner._toggleEnabled()
            return True

        # --- 参数面板（照 Houdini 的 P 键：光标边上弹一块纯参数面）---
        # 原生只在 `NodeSetEditor` 上认 P（那是 pin，`CompoundEditor.py:1523`），
        # 我们这个编辑器不是 NodeSetEditor，P 是空着的。
        if key == QtCore.Qt.Key_P and plain:
            return owner._popupParameters()

        # --- 划线断连：**按住 X 划、松手生效** ---
        #
        # X11 的按键自动重复会一直发 press/release 对（按住约 0.5 秒后开始），
        # 不管的话 release 把划线收了、下一个 press 又重开 —— 表现是「划到一定距离
        # 就一直闪、画不出来」。所以 `keyPressEvent` / `keyReleaseEvent` **两边**
        # 都要 `if event.isAutoRepeat() : return`（真机 xdotool 长按验过）。
        if key == QtCore.Qt.Key_X and plain:
            if self.__mode == _MODE_NONE:
                self.__beginCut()
            return True

        if key == QtCore.Qt.Key_Escape and self.__mode == _MODE_CUT:
            self.__endCutMode()
            return True

        # --- 书签 ---
        if key == QtCore.Qt.Key_B and plain:
            owner._popupBookmarkMenu(QtGui.QCursor.pos())
            return True
        if QtCore.Qt.Key_0 <= key <= QtCore.Qt.Key_9 and (
            plain or modifiers == QtCore.Qt.ControlModifier
        ):
            number = key - QtCore.Qt.Key_0
            if control:
                owner._assignNumericBookmark(number)
            else:
                owner._findNumericBookmark(number)
            return True

        # --- 编辑（对齐菜单栏 Edit 菜单）---
        if key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace) and plain:
            owner._deleteSelected()
            return True
        if key == QtCore.Qt.Key_F2 and plain:
            owner._renameSelected()
            return True

        if modifiers == QtCore.Qt.ControlModifier:
            if key == QtCore.Qt.Key_C:
                owner._copySelected()
                return True
            if key == QtCore.Qt.Key_X:
                owner._cutSelected()
                return True
            if key == QtCore.Qt.Key_V:
                owner._paste()
                return True
            if key == QtCore.Qt.Key_D:
                owner._duplicateWithInputs()
                return True
            if key == QtCore.Qt.Key_A:
                owner._selectAll()
                return True
            if key == QtCore.Qt.Key_L:
                owner._arrange()
                return True
            if key == QtCore.Qt.Key_F:
                owner._find()
                return True

        if (
            modifiers == (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
            and key == QtCore.Qt.Key_A
        ):
            owner._selectNone()
            return True

        return False

    def keyReleaseEvent(self, event):

        # **自动重复的 release 一律不算数** —— 按住 X 的时候 X11 会不停发
        # press/release 对，认了的话线划到一半就自己断了
        if event.isAutoRepeat():
            event.accept()
            return

        # 松开 X = 收尾（还有没提交的一笔就顺手切掉），退出划线模式
        if event.key() == QtCore.Qt.Key_X and self.__mode == _MODE_CUT:
            self.__applyCut()
            event.accept()
            return

        # 平移到一半松了 X：平移结束后不再回到划线模式，提示 / 光标现在就收掉
        if event.key() == QtCore.Qt.Key_X and self.__cutSuspended:
            self.__cutSuspended = False
            self.__clearCutState()
            event.accept()
            return

        QtWidgets.QGraphicsView.keyReleaseEvent(self, event)

    ##########################################################################
    # 划线断连（按住 X）
    ##########################################################################

    ## 进入划线模式：**按住 X，按着左键划过连线，松开左键（或松开 X）就切**。
    def __beginCut(self):

        self.__mode = _MODE_CUT
        self.__cutPoints = []
        self.__cutStroke = False

        self.viewport().setCursor(QtCore.Qt.CrossCursor)
        # 提示原文：删除模式（按住 X）—— 点连线删线、点节点删节点；
        # 按住左键划线可一次切多根。松开 X 或按 Esc 退出
        self.__owner._setStatusHint(
            "Delete mode (hold X): click a connection to cut it, click a node to "
            "delete it; drag with the left button to slice several. "
            "Release X or press Esc to exit"
        )

    def __endCutMode(self):

        self.__clearCutState()
        self.__mode = _MODE_NONE
        self.viewport().unsetCursor()

    ## 划线留下的东西（没提交的点、虚线、状态栏提示）收干净，模式和光标不动。
    def __clearCutState(self):

        self.__cutPoints = []
        self.__cutStroke = False
        self.__owner._setStatusHint(None)

        if self.__cutItem is not None:
            try:
                self.scene().removeItem(self.__cutItem)
            except RuntimeError:
                pass  # 已经被重建销毁了
            self.__cutItem = None

    def isCutting(self):

        return self.__mode == _MODE_CUT

    def __updateCutLine(self):

        path = QtGui.QPainterPath()
        if self.__cutPoints:
            path.moveTo(self.__cutPoints[0])
            for p in self.__cutPoints[1:]:
                path.lineTo(p)

        # item 可能已经被一次重建（`scene.clear()`）销毁了 —— 那就重新建一个
        for _ in range(2):
            try:
                if self.__cutItem is None:
                    self.__cutItem = QtWidgets.QGraphicsPathItem()
                    self.__cutItem.setZValue(60)
                    self.__cutItem.setPen(
                        QtGui.QPen(QtGui.QColor(_cutColor), 2.0, QtCore.Qt.DashLine)
                    )
                    self.scene().addItem(self.__cutItem)
                self.__cutItem.setPath(path)
                return
            except RuntimeError:
                self.__cutItem = None

    ## 这一下到底是"点"还是"划"（按下和松开离得够近就是点）。
    def __cutWasClick(self, position):

        if self.__cutPressPosition is None:
            return False

        return (position - self.__cutPressPosition).manhattanLength() <= CUT_CLICK_SLOP

    ## X 模式下点一下：删光标底下的连线，没连线就删节点。
    def __cutClick(self, position):

        edgeItem = self.edgeItemAt(position)
        if edgeItem is not None:
            self.__owner._disconnect([edgeItem.edge])
            return

        item = self.nodeItemAt(position)
        if item is not None:
            self.__owner._deleteNodes([item.node])

    ## 把当前这一笔切下去。`keepMode = True` 表示还按着 X，切完继续待命（可以再划一笔）。
    def __applyCut(self, keepMode=False):

        points = list(self.__cutPoints)

        if keepMode:
            self.__cutPoints = []
            self.__cutStroke = False
            self.__updateCutLine()
        else:
            self.__endCutMode()

        if len(points) < 2:
            return

        cut = QtGui.QPainterPath()
        cut.moveTo(points[0])
        for p in points[1:]:
            cut.lineTo(p)

        # 让 scene 的空间索引来找（`IntersectsItemShape` = 和 `shape()` 求交，
        # 判据等同于逐个 `shape().intersects( cut )`），别把全图 item 扫一遍
        hits = [
            item.edge
            for item in self.scene().items(cut, QtCore.Qt.IntersectsItemShape)
            if isinstance(item, _EdgeItem)
        ]

        if hits:
            self.__owner._disconnect(hits)

    ##########################################################################
    # 取景
    ##########################################################################

    ## 取景只看卡片 / 框本身（`selectionRect()`），不看包围盒 —— 包围盒在悬停 / focus
    # 时带着一两百像素的标签、角标余量，框多松就成了「鼠标在哪」决定的。
    def __frameNodeItems(self, items, padding):

        rect = QtCore.QRectF()
        for item in items:
            if isinstance(item, (_NodeItem, _BackdropItem)):
                bounds = item.selectionRect()
                rect = bounds if rect.isNull() else rect.united(bounds)

        if rect.isNull():
            return False

        self.fitInView(
            rect.adjusted(-padding, -padding, padding, padding),
            QtCore.Qt.KeepAspectRatio,
        )
        self._clampZoom()
        self._rememberCentre()
        return True

    def frameAll(self):

        self.__frameNodeItems(self.scene().items(), 60)

    def frameSelection(self):

        if not self.__frameNodeItems(self.scene().selectedItems(), 90):
            self.frameAll()

    ## 现在看得见的那块 scene 区域（进 Box / 出 Box 时拿它记住视野）。
    def viewedSceneRect(self):

        rect = self.viewport().rect()
        if rect.isEmpty():
            return None

        return self.mapToScene(rect).boundingRect()

    ## 把视野对回之前记下的那块区域。成功返回 True。
    def setViewedSceneRect(self, rect):

        if rect is None or rect.isNull() or self.viewport().rect().isEmpty():
            return False

        self.fitInView(rect, QtCore.Qt.KeepAspectRatio)
        self._clampZoom()
        self._rememberCentre()
        return True

    ## 把指定的 item 框进画面（书签跳转 / focus 取景用）。
    def frameItems(self, items):

        self.__frameNodeItems(items, 90)


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
