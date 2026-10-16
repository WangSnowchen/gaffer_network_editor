"""连线的 `QGraphicsItem` 和连线路径。"""

import math


from Qt import QtCore, QtGui, QtWidgets

from .node_item import *

# Qt：连线


## 连线路径。曲线模式照 Houdini 的 `rounded` 连线来 —— 它不是贝塞尔，而是
# **直段 + 圆弧**：出口先顺着流向走一小段、用一个小圆角拐向侧面，横平地走过去，
# 再用一个大圆弧拐成流向，直着扎进入口。
#
# 形状是在真机 Houdini 21.0.596（`View > Change network wiring style` 的 rounded）
# 上量出来的：`hou.NetworkEditor` 给出图坐标↔屏幕像素的映射，逐像素抠出连线再拟合，
# 拐角处圆拟合残差 ~0.005 单位（≈1px）—— 确实是正圆弧，不是贝塞尔。
# 参数（Houdini 单位，1 单位 ≈ 一个节点宽）：出口直段 s = min(0.30, 流向距离/2)；
# 出口圆角半径 = s；主圆角半径 = min(侧向余量, 0.42 * (流向距离 - s) + 0.67)。
#
# `avoid` 是两端节点卡片的 scene 矩形。Houdini 那套形状只看两个端点，接口在卡片
# 侧边、上游又在另一边时（filter 接在右侧、源节点在左边；BoxIn 在右上、参数接口在
# 左边；节点自己连自己的回环），折线会从卡片中间横穿过去。这种时候换成
# `_routeAround()` 绕开卡片走的折线，其余情况形状不变。
def _wirePath(p0, t0, p1, t1, style, avoid=()):

    if style != WIRE_CURVED:
        path = QtGui.QPainterPath(p0)
        path.lineTo(p1)
        return path

    f = _unit(t0)  # 出口方向（流向）
    g = _unit(QtCore.QPointF(-t1.x(), -t1.y()))  # 进入目标时的行进方向
    points, radii = _houdiniWirePoints(p0, f, p1, g)

    cards = _cardsToAvoid(avoid, p0, p1)
    if cards and _polylineCrossesCards(points, cards):
        routed = _routeAround(p0, f, p1, g, cards)
        if routed is not None:
            return _roundedPath(routed, *([WIRE_STUB] * (len(routed) - 2)))

    return _roundedPath(points, *radii)


## Houdini `rounded` 连线的折线（拐点 + 每个拐角的圆角半径）。
def _houdiniWirePoints(p0, f, p1, g):

    d = QtCore.QPointF(p1.x() - p0.x(), p1.y() - p0.y())

    along = d.x() * f.x() + d.y() * f.y()  # 沿流向走了多远
    lateralVec = QtCore.QPointF(d.x() - along * f.x(), d.y() - along * f.y())
    lateral = math.hypot(lateralVec.x(), lateralVec.y())
    if lateral > 1e-6:
        l = QtCore.QPointF(lateralVec.x() / lateral, lateralVec.y() / lateral)
    else:
        l = QtCore.QPointF(-f.y(), f.x())  # 正对着的时候侧向随便取一边

    aligned = f.x() * g.x() + f.y() * g.y() > 0.7  # 出入方向同向（最常见）

    if not aligned:
        # 进出方向垂直/斜交（比如场景节点的 filter 接口在侧边）：走一个拐点的折线
        return [p0, _elbow(p0, f, p1, g), p1], (WIRE_STUB,)

    if along >= -1.0 and lateral < 0.5:
        return [p0, p1], ()  # 正上正下：Houdini 也是一条直线

    if along < -1.0:
        # 目标在上游侧：先出去、侧移一半、绕回去、再侧移进入口（Houdini 也是这么绕的）
        s = WIRE_STUB
        bulge = max(lateral * 0.5, WIRE_STUB * 1.2)
        a = _offset(p0, f, s)
        b = _offset(a, l, bulge)
        c = _offset(b, f, along - 2.0 * s)
        e = _offset(c, l, lateral - bulge)
        r = min(s, bulge * 0.5, abs(along - 2.0 * s) * 0.5)
        return [p0, a, b, c, e, p1], (r, r, r, r)

    # 常规：出口直段 -> 小圆角 -> 横段 -> 大圆角 -> 直着进入口
    s = max(0.0, min(WIRE_STUB, along * 0.5))
    a = _offset(p0, f, s)
    c = _offset(a, l, lateral)
    rA = min(s, lateral * 0.5)
    rC = min(lateral - rA, along - s, WIRE_TURN_SLOPE * (along - s) + WIRE_TURN_BASE)
    return [p0, a, c, p1], (rA, max(0.0, rC))


## 要绕开的卡片。端点落在卡片**里面**的不算（Dot 的接口在圆心上，绕不开也不该绕）；
# 节点自己连自己时两张卡片是同一张，去掉重复的。
def _cardsToAvoid(avoid, p0, p1):

    cards = []
    for rect in avoid:
        inner = rect.adjusted(2.0, 2.0, -2.0, -2.0)
        if inner.contains(p0) or inner.contains(p1):
            continue
        if any(rect == other for other in cards):
            continue
        cards.append(rect)

    return cards


## 折线有没有从卡片中间穿过去。判的是卡片本身往里收 2px（端点就在卡片边上，
# 贴着边走不算），两头各让开一点 —— 接口圆点压在卡片边线上。
def _polylineCrossesCards(points, cards):

    insides = [rect.adjusted(2.0, 2.0, -2.0, -2.0) for rect in cards]
    trim = 3.0
    last = len(points) - 2
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        if i == 0:
            a = _towards(a, b, trim)
        if i == last:
            b = _towards(b, a, trim)
        if any(_segmentHitsRect(a, b, rect) for rect in insides):
            return True

    return False


## 从 a 往 b 挪 distance（不越过 b）。
def _towards(a, b, distance):

    length = math.hypot(b.x() - a.x(), b.y() - a.y())
    if length <= distance:
        return QtCore.QPointF(b)
    t = distance / length
    return QtCore.QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)


## 线段和矩形内部有没有交集（Liang–Barsky 裁剪）。
def _segmentHitsRect(a, b, rect):

    if rect.width() <= 0.0 or rect.height() <= 0.0:
        return False

    dx, dy = b.x() - a.x(), b.y() - a.y()
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, a.x() - rect.left()),
        (dx, rect.right() - a.x()),
        (-dy, a.y() - rect.top()),
        (dy, rect.bottom() - a.y()),
    ):
        if abs(p) < 1e-9:
            if q <= 0.0:
                return False
            continue
        t = q / p
        if p < 0.0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1:
            return False

    return True


## 绕开卡片的横平竖直折线：出口顺流向走一个 `WIRE_STUB`，进口前同样留一段直的，
# 中间用「0~2 个拐点」的候选里挑一条 —— 不碰任何一张卡片（外扩 `WIRE_CLEARANCE`）、
# 不走回头路，按「长度 + 拐点数」取最短。接口方向不是横平竖直的（自定义 nodule）
# 或者一条能走的都没有，返回 None，调用方照旧画 Houdini 那条。
def _routeAround(p0, f, p1, g, cards):

    if not (_axisAligned(f) and _axisAligned(g)):
        return None

    a = _offset(p0, f, WIRE_STUB)
    b = _offset(p1, g, -WIRE_STUB)
    blocked = [
        rect.adjusted(-WIRE_CLEARANCE, -WIRE_CLEARANCE, WIRE_CLEARANCE, WIRE_CLEARANCE)
        for rect in cards
    ]

    xs = {a.x(), b.x(), (a.x() + b.x()) * 0.5}
    ys = {a.y(), b.y(), (a.y() + b.y()) * 0.5}
    for rect in blocked:
        xs.update((rect.left(), rect.right()))
        ys.update((rect.top(), rect.bottom()))
    xs.update(_gaps([(r.left(), r.right()) for r in blocked]))
    ys.update(_gaps([(r.top(), r.bottom()) for r in blocked]))

    middles = [
        [],
        [QtCore.QPointF(a.x(), b.y())],
        [QtCore.QPointF(b.x(), a.y())],
    ]
    middles += [[QtCore.QPointF(x, a.y()), QtCore.QPointF(x, b.y())] for x in xs]
    middles += [[QtCore.QPointF(a.x(), y), QtCore.QPointF(b.x(), y)] for y in ys]

    best, bestScore = None, None
    for middle in middles:
        points = _simplifyPolyline([p0, a] + middle + [b, p1])
        if points is None or _polylineBlocked(points, blocked):
            continue
        length = sum(
            math.hypot(q.x() - p.x(), q.y() - p.y()) for p, q in zip(points, points[1:])
        )
        score = length + (len(points) - 2) * WIRE_STUB * 2.0
        if bestScore is None or score < bestScore:
            best, bestScore = points, score

    return best


def _axisAligned(v):

    return abs(v.x()) < 1e-3 or abs(v.y()) < 1e-3


## 区间两两之间的空隙中点（卡片在这个轴上分开时，从中间穿过去）。
def _gaps(intervals):

    result = []
    for lo0, hi0 in intervals:
        for lo1, hi1 in intervals:
            if hi0 < lo1:
                result.append((hi0 + lo1) * 0.5)
    return result


## 去掉重合点和共线的中间点；有斜段或者 180° 掉头的返回 None。
def _simplifyPolyline(points):

    pts = [points[0]]
    for p in points[1:]:
        if math.hypot(p.x() - pts[-1].x(), p.y() - pts[-1].y()) > 1e-6:
            pts.append(p)

    result = [pts[0]]
    for i in range(1, len(pts)):
        p = pts[i]
        if abs(p.x() - result[-1].x()) > 1e-6 and abs(p.y() - result[-1].y()) > 1e-6:
            return None
        if len(result) >= 2:
            d0 = _unit(
                QtCore.QPointF(
                    result[-1].x() - result[-2].x(), result[-1].y() - result[-2].y()
                )
            )
            d1 = _unit(QtCore.QPointF(p.x() - result[-1].x(), p.y() - result[-1].y()))
            dot = d0.x() * d1.x() + d0.y() * d1.y()
            if dot < -0.5:
                return None  # 掉头
            if dot > 0.5:
                result[-1] = p  # 共线，并进上一段
                continue
        result.append(p)

    return result


## 折线碰没碰外扩后的卡片。头尾两段是从接口伸出来的，起点 / 终点本来就在外扩
# 范围里，让开外扩那一圈再判。
def _polylineBlocked(points, blocked):

    trim = WIRE_CLEARANCE + 2.0
    last = len(points) - 2
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        if i == 0:
            a = _towards(a, b, trim)
        if i == last:
            b = _towards(b, a, trim)
        if any(_segmentHitsRect(a, b, rect) for rect in blocked):
            return True

    return False


def _unit(v):

    length = math.hypot(v.x(), v.y())
    if length < 1e-9:
        return QtCore.QPointF(0.0, 1.0)
    return QtCore.QPointF(v.x() / length, v.y() / length)


def _offset(p, direction, distance):

    return QtCore.QPointF(
        p.x() + direction.x() * distance, p.y() + direction.y() * distance
    )


## 两条射线（p0 沿 f 出、p1 沿 -g 回）的交点，取不到就退回中点。
def _elbow(p0, f, p1, g):

    det = f.x() * g.y() - f.y() * g.x()
    if abs(det) < 1e-6:
        return QtCore.QPointF((p0.x() + p1.x()) * 0.5, (p0.y() + p1.y()) * 0.5)

    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
    t = (dx * g.y() - dy * g.x()) / det
    return _offset(p0, f, t)


## 把折线拐角换成正圆弧。每个拐角一个半径，半径按相邻两段长度自动收，
# 圆弧用「4/3*tan(φ/4)」那条标准的贝塞尔近似画（90° 就是熟悉的 0.5523 kappa）。
def _roundedPath(points, *radii):

    pts = [points[0]]
    for p in points[1:]:
        if math.hypot(p.x() - pts[-1].x(), p.y() - pts[-1].y()) > 1e-6:
            pts.append(p)

    path = QtGui.QPainterPath(pts[0])
    if len(pts) < 3:
        for p in pts[1:]:
            path.lineTo(p)
        return path

    radii = list(radii) + [0.0] * (len(pts) - 2 - len(radii))
    cursor = pts[0]
    for i in range(1, len(pts) - 1):
        prev, corner, nxt = pts[i - 1], pts[i], pts[i + 1]
        dIn = _unit(QtCore.QPointF(corner.x() - prev.x(), corner.y() - prev.y()))
        dOut = _unit(QtCore.QPointF(nxt.x() - corner.x(), nxt.y() - corner.y()))
        cross = dIn.x() * dOut.y() - dIn.y() * dOut.x()
        dot = max(-1.0, min(1.0, dIn.x() * dOut.x() + dIn.y() * dOut.y()))
        turn = math.atan2(abs(cross), dot)
        if turn < 1e-3 or turn > math.pi - 1e-3:
            path.lineTo(corner)
            cursor = corner
            continue

        # 切线长 = r * tan(φ/2)，两头都不能吃掉超过半段
        lenIn = math.hypot(corner.x() - cursor.x(), corner.y() - cursor.y())
        lenOut = math.hypot(nxt.x() - corner.x(), nxt.y() - corner.y())
        if i < len(pts) - 2:
            lenOut *= 0.5
        tan = math.tan(turn * 0.5)
        r = min(radii[i - 1], lenIn / tan, lenOut / tan)
        if r <= 1e-6:
            path.lineTo(corner)
            cursor = corner
            continue

        t = r * tan
        k = r * 4.0 / 3.0 * math.tan(turn * 0.25)
        start = _offset(corner, dIn, -t)
        end = _offset(corner, dOut, t)
        path.lineTo(start)
        path.cubicTo(_offset(start, dIn, k), _offset(end, dOut, -k), end)
        cursor = end

    path.lineTo(pts[-1])
    return path


## 路径中点处的位置与单位方向向量。
# 用相邻两点数值求方向，绕开 `angleAtPercent()` 的 y 轴翻转约定。
def _pathMidpoint(path):

    a = path.pointAtPercent(0.46)
    b = path.pointAtPercent(0.54)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return path.pointAtPercent(0.5), QtCore.QPointF(0, 1)

    return path.pointAtPercent(0.5), QtCore.QPointF(dx / length, dy / length)


class _EdgeItem(QtWidgets.QGraphicsPathItem):

    def __init__(self, edge, srcItem, dstItem, wireStyle):

        QtWidgets.QGraphicsPathItem.__init__(self)

        self.__midpoint = None  # 箭头中点缓存，见 setPath()
        self.__shape = None  # 命中形状（描边加宽）缓存，见 setPath()
        self.__pathMetrics = None  # ( 长度, 起点, 终点 ) 缓存，见 setPath()
        self.edge = edge
        self._baseZ = 2 if not edge.auxiliary else 1
        self.setZValue(self._baseZ)
        self.setAcceptHoverEvents(True)

        self._minimised = connectionMinimised(edge)
        self._hovered = False
        self._srcItem = srcItem
        self._dstItem = dstItem
        self._stub = False
        self._emphasis = False  # 图里有 focus 时，参与计算的线提亮一档
        self._selected = False  # 被选中（点一下选、Delete 删）

        self._color = QtGui.QColor(wireColor(edge))
        # 悬停 = 原生 StandardStyle 的 HighlightColor（`colorForState`）
        self._highlightColor = QtGui.QColor(_highlightColor)
        self._insertTarget = False
        # focus 之后不参与 focus 节点计算的线画成 DisabledState（原生就是变暗，不是高亮）
        self._active = True
        self._disabledColor = _disabledColor(self._color, connection=True)
        self._midAlpha = 255
        self.setBrush(QtCore.Qt.NoBrush)

        self.updateGeometry(wireStyle)  # 顺带 `__applyPen()`

        # 悬停小框：连线两头 + 中文说明（界面文字英文、提示中文）
        self.setToolTip(
            "%s.%s &rarr; %s.%s%s<br><i>点中段选中（Delete 删除），拖两端可改接</i>"
            % (
                edge.srcNode.getName(),
                # 相对名，不是 getName()：NameSwitch 的每一路输入都叫 `value`
                edge.srcPlug.relativeName(edge.srcNode),
                edge.dstNode.getName(),
                edge.dstPlug.relativeName(edge.dstNode),
                "<br><i>这条连线已折叠</i>" if self._minimised else "",
            )
        )

    ## 画笔。长连线中段渐隐是 Houdini 的做法 —— 长线不淡化的话，大图上连线会
    # 糊成一片、盖住节点。悬停时不淡化，方便顺着看一条线走到哪。
    def __applyPen(self):

        if self._insertTarget:
            base = QtGui.QColor(_snapGuideColor)  # 「松手就把节点塞进这根线」
        elif self._selected:
            base = QtGui.QColor(_selectedBorder)
        elif self._hovered:
            base = QtGui.QColor(self._highlightColor)
        elif not self._active:
            base = QtGui.QColor(self._disabledColor)
        elif self._emphasis:
            base = _emphasisColor(self._color)  # 有 focus 时，参与计算的更亮
        else:
            base = QtGui.QColor(self._color)

        # 中点箭头和线同一个颜色（选中 / 塞入候选 / 提亮那几种状态也跟着变）
        self.__penBase = base

        # 粗细不跟着变 —— 原生 `renderConnection` 的线宽和 state 无关
        # （选中和悬停是我们自己加的两种状态，那时候才加粗）
        width = (
            2.8
            if self._insertTarget
            else (
                2.4
                if self._selected
                else (
                    2.0 if self._hovered else (1.5 if not self.edge.auxiliary else 1.1)
                )
            )
        )
        style = QtCore.Qt.SolidLine if not self.edge.auxiliary else QtCore.Qt.DashLine

        length, p0, p1 = self.__pathEndpoints()

        fade = (
            not self._hovered
            and not self._stub
            and length > WIRE_FADE_START
            and (abs(p1.x() - p0.x()) > 1e-3 or abs(p1.y() - p0.y()) > 1e-3)
        )

        if not fade:
            self._midAlpha = 255
            brush = QtGui.QBrush(base)
        else:
            t = min(
                1.0,
                (length - WIRE_FADE_START) / max(1.0, WIRE_FADE_FULL - WIRE_FADE_START),
            )
            self._midAlpha = int(255 - (255 - WIRE_FADE_MIN_ALPHA) * t)

            mid = QtGui.QColor(base)
            mid.setAlpha(self._midAlpha)

            gradient = QtGui.QLinearGradient(p0, p1)
            gradient.setColorAt(0.0, base)
            gradient.setColorAt(0.16, base)
            gradient.setColorAt(0.5, mid)
            gradient.setColorAt(0.84, base)
            gradient.setColorAt(1.0, base)
            brush = QtGui.QBrush(gradient)

        self.setPen(
            QtGui.QPen(brush, width, style, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        )

    # 加宽命中区，细线也好点中。描边一次算好缓存起来 —— 每次 `items()` 命中测试
    # 都要对探针附近每条线问一遍 `shape()`，`createStroke` 不便宜。
    def shape(self):

        if self.__shape is None:
            stroker = QtGui.QPainterPathStroker()
            stroker.setWidth(10.0)
            self.__shape = stroker.createStroke(self.path())
        return self.__shape

    def hoverEnterEvent(self, event):

        # 按着任何一个键在拖（中键平移、拖节点、框选）的时候不要高亮 —— 平移经过的
        # 每条线都亮一下，看着像图在闪。原生也只在「什么都没按」时才高亮连线。
        if QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton:
            return

        self._hovered = True
        self.__applyPen()
        if self._minimised:
            self.updateGeometry(self._wireStyle)
        self.update()
        QtWidgets.QGraphicsPathItem.hoverEnterEvent(self, event)

    def hoverLeaveEvent(self, event):

        self.clearHover()
        QtWidgets.QGraphicsPathItem.hoverLeaveEvent(self, event)

    ## 这条线参不参与 focus 节点的计算。
    #
    # 原生（`ConnectionGadget::updateFromContextTracker` + `StandardConnectionGadget`）：
    # focus 着谁的时候，`ContextTracker::isTracked( 目标插口 )` 为假的线画成
    # `Style::DisabledState`（变暗），**参与的线保持原样，不做任何加亮**。
    def setWireActive(self, active):

        if active == self._active:
            return

        self._active = active
        self.__applyPen()
        self.update()

    ## 鼠标点在这条线的哪一头上（scene 坐标）。返回 "src" / "dst" / None。
    #
    # 逐条抄原生 `StandardConnectionGadget::endAt`：**只有靠近两端才算抓住连线**
    # （中间一大段不响应，不然长线上随手一点就把线拽走了）。灵敏区跟线长成正比，
    # 夹在一个上下限之间 —— 原生是 `clamp( length / 4, 2.5, 25 )` 个 Gaffer 单位。
    def endAt(self, scenePosition):

        if self.edge.auxiliary:
            return None  # 辅助连线原生也不给拖

        p0, _, p1, _ = self.endPoints()
        length = math.hypot(p1.x() - p0.x(), p1.y() - p0.y())
        threshold = max(2.5 * PX_PER_UNIT, min(25.0 * PX_PER_UNIT, length / 4.0))

        dSrc = math.hypot(scenePosition.x() - p0.x(), scenePosition.y() - p0.y())
        dDst = math.hypot(scenePosition.x() - p1.x(), scenePosition.y() - p1.y())

        if min(dSrc, dDst) >= threshold:
            return None

        return "src" if dSrc < dDst else "dst"

    ## 选中 / 取消选中这条线。选中的线按选中色画粗一点，Delete 就断开它。
    def setWireSelected(self, selected):

        if selected == self._selected:
            return

        self._selected = selected
        self.setZValue(self._baseZ + (3 if selected else 0))
        self.__applyPen()
        self.update()

    def isWireSelected(self):

        return self._selected

    ## 「现在拖着的那个节点松手就塞进这根线里」的高亮（原生是把这根线藏起来、
    # 另画两根高亮的预览线；我们就地把它画成金色加粗，一样一眼看得出）。
    def setInsertTarget(self, insertTarget):

        if insertTarget == self._insertTarget:
            return

        self._insertTarget = insertTarget
        self.setZValue(
            self._baseZ + (4 if insertTarget else (3 if self._selected else 0))
        )
        self.__applyPen()
        self.update()

    def isInsertTarget(self):

        return self._insertTarget

    ## 现在图里有没有 focus。有的话「参与计算」的线提亮一档（`_emphasisColor`），
    # 和变暗的那些拉开差距；没有 focus 时一切照原生原色。
    def setFocusEmphasis(self, emphasis):

        if emphasis == self._emphasis:
            return

        self._emphasis = emphasis
        self.__applyPen()
        self.update()

    def isWireActive(self):

        return self._active

    ## 强制取消悬停高亮。中键平移时用 —— 那会儿 Qt 不再往 item 派发 hover 事件，
    # 不主动清的话高亮会僵在那条线上。
    def clearHover(self):

        if not self._hovered:
            return

        self._hovered = False
        self.__applyPen()
        if self._minimised:
            self.updateGeometry(self._wireStyle)
        self.update()

    def endPoints(self):

        p0 = self._srcItem.mapToScene(self._srcItem.nodulePosition(self.edge.srcPlug))
        p1 = self._dstItem.mapToScene(self._dstItem.nodulePosition(self.edge.dstPlug))
        t0 = self._srcItem.noduleTangent(self.edge.srcPlug)
        t1 = self._dstItem.noduleTangent(self.edge.dstPlug)
        return p0, t0, p1, t1

    def updateGeometry(self, wireStyle):

        self._wireStyle = wireStyle
        p0, t0, p1, t1 = self.endPoints()

        # 折叠：抄 `StandardConnectionGadget::minimisedPositionAndTangent` —— 从 dst
        # nodule 伸出 1.5 个单位的小尾巴，鼠标悬停时才画完整。
        avoid = (self._srcItem.sceneCardRect(), self._dstItem.sceneCardRect())
        if self._minimised and not self._hovered:
            p0 = QtCore.QPointF(
                p1.x() + t1.x() * MINIMISED_STUB, p1.y() + t1.y() * MINIMISED_STUB
            )
            t0 = QtCore.QPointF(-t1.x(), -t1.y())
            avoid = ()

        self.setPath(_wirePath(p0, t0, p1, t1, wireStyle, avoid))
        self._stub = self._minimised and not self._hovered
        # 渐隐画笔依赖路径长度与端点，必须在 setPath 之后重算
        self.__applyPen()

    ## 路径一变，中点缓存就作废。`_EdgeItem` 的路径只在 `updateGeometry()` 里设，
    # 但覆写在这里，任何路径改动都覆盖得到。
    def setPath(self, path):

        self.__midpoint = None
        self.__shape = None
        self.__pathMetrics = None
        QtWidgets.QGraphicsPathItem.setPath(self, path)

    ## 路径的 ( 长度, 起点, 终点 )。`__applyPen` 每次改状态（悬停 / 选中 / 变暗）都要
    # 用，而 `length()` 要把整条曲线做一遍弧长参数化 —— 路径没变就别重算。
    def __pathEndpoints(self):

        if self.__pathMetrics is None:
            path = self.path()
            if path.isEmpty():
                origin = QtCore.QPointF()
                self.__pathMetrics = (0.0, origin, QtCore.QPointF(origin))
            else:
                self.__pathMetrics = (
                    path.length(),
                    path.pointAtPercent(0.0),
                    path.pointAtPercent(1.0),
                )

        return self.__pathMetrics

    ## 中点箭头的位置与方向，按当前路径缓存。
    # `pointAtPercent()` 每次都要把整条贝塞尔做一遍弧长参数化，而 paint 里一条边要问三次
    # —— 平移 / 缩放**根本不改路径**，却每帧重算一遍：实测 300 节点全景平移时它是单项
    # 开销第一名（9900 次调用 59ms，占一帧的 18%）。
    def midpoint(self):

        if self.__midpoint is None:
            self.__midpoint = _pathMidpoint(self.path())

        return self.__midpoint

    def paint(self, painter, option, widget=None):

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        QtWidgets.QGraphicsPathItem.paint(self, painter, option, widget)

        if _lod(option, painter) < LOD_MEDIUM or self.edge.auxiliary or self._stub:
            return

        # 方向箭头画在**线的中点**（Houdini 就是这么做的）。画在终点会和 nodule
        # 叠在一起，糊成一坨。
        point, direction = self.midpoint()
        size = 5.5
        tx, ty = direction.x(), direction.y()
        px, py = -ty, tx

        arrowColor = QtGui.QColor(self.__penBase)
        arrowColor.setAlpha(self._midAlpha)  # 跟着中段一起淡

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(arrowColor)
        painter.drawPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(point.x() + tx * size, point.y() + ty * size),
                    QtCore.QPointF(
                        point.x() - tx * size * 0.6 + px * size * 0.62,
                        point.y() - ty * size * 0.6 + py * size * 0.62,
                    ),
                    QtCore.QPointF(
                        point.x() - tx * size * 0.6 - px * size * 0.62,
                        point.y() - ty * size * 0.6 - py * size * 0.62,
                    ),
                ]
            )
        )


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
