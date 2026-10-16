"""节点卡片的 `QGraphicsItem`。

扁平卡片 + 类型色带 + 类型图标 + 接口圆点 + focus 角标 + 书签 / 注释 /
停用对角线，以及命中测试（`shape()` 必须自己写，别跟着悬停会膨胀的
`boundingRect()` 走）。
"""

import math


import Gaffer

from Qt import QtCore, QtGui, QtWidgets

from .backdrop_item import *

# Qt：节点卡片


## 把「展开的复合数值插口」（Color3f 右键 Expand RGB 那种）的子接口并成**一簇**，
# 其余插口各自一簇 —— 返回 [ [plug, ...], ... ]，顺序照原样。
#
# 原生是把 r/g/b 塞在父接口那一格里、整组缩到 0.75 挤在一起，不是当兄弟接口摊开
# （`CompoundNumericNodule.cpp`）。侧边分栏是我们自己排的行，得自己把它们并回一簇。
def _noduleClusters(node, plugs):

    clusters = []
    byParent = {}

    for plug in plugs:
        parent = plug.parent()
        key = None
        if (
            isinstance(parent, Gaffer.Plug)
            and not node.isSame(parent)
            and isExpandedCompoundNumeric(parent)
        ):
            key = plugKey(node, parent)

        if key is not None and key in byParent:
            clusters[byParent[key]].append(plug)
            continue

        if key is not None:
            byParent[key] = len(clusters)
        clusters.append([plug])

    return clusters


## 悬停放大标签的字号（画 + 算包围盒余量两处共用）。
_HOVER_LABEL_FONT_SIZE = 8.5

_penCache = {}


## 复用一支 QPen（`painter.setPen` 按值拷贝，共享一支是安全的）。一帧几百个圆点
# 各自 `QPen( QColor( ... ) )` 是 paint 里最贵的一项 Python 开销。**别对返回值
# 调 setStyle / setWidth** —— 要改就自己 `QPen( pen )` 拷一份。
def _cachedPen(color, width):

    pen = _penCache.get((color, width))
    if pen is None:
        pen = QtGui.QPen(QtGui.QColor(color), width)
        _penCache[(color, width)] = pen
    return pen


_sectionHeaderQColor = None


def _sectionHeaderColor():

    global _sectionHeaderQColor
    if _sectionHeaderQColor is None:
        _sectionHeaderQColor = QtGui.QColor(
            mixColors(_textColor, _backgroundColor, 0.30)
        )
    return _sectionHeaderQColor


class _NodeItem(QtWidgets.QGraphicsItem):

    ## `graphGadget` 是原生 GraphGadget（可能为 None）—— 大小和接口位置都从它身上取，
    # 保证和原生节点编辑器里一模一样；拿不到就用公式回退。
    def __init__(self, node, owner, graphGadget=None):

        QtWidgets.QGraphicsItem.__init__(self)

        self.node = node
        self.nodeName = node.getName()
        self._owner = owner

        # 几何缓存。Qt 每帧每个 item 要问 `boundingRect()` 好几次，命中测试
        # （`items()`）对每个候选都要 `shape()` —— 这些只在 `__geometryChanged()`
        # 时才作废。分栏行 / 可见圆点 / 标签颜色在 item 的生命期内不变
        # （折叠状态改了走元数据信号重建整个 item），所以也只算一次。
        self.__boundsCache = None
        self.__shapeCache = None
        self.__cardPathCache = None
        self.__hoverMargin = 0.0  # 悬停放大标签要往卡外伸多远（`setHoveredNodule` 算）
        self.__endLabelOverhang = 0.0  # 顶 / 底接口标签横向超出卡片多少
        self.__nameWidth = 0.0
        self.__sectionRowsCache = {}
        self.__visibleSideCache = {}
        self.__sectionCollapsedCache = {}
        self.__sideLabelColorCache = {}
        self.__elidedLabelCache = {}
        self.__noduleDraw = {}  # { 边 : [ ( plug, key, 位置, 半径, 颜色 ), ... ] }
        self.__endLabelPlugs = {}

        self._nodules = noduleLayout(node)
        self._shape = nodeShape(node)
        self._glyph = (
            None if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY) else nodeGlyph(node)
        )

        # 大小：**以原生尺寸为下限**，但名字放不下就往宽了撑。
        #
        # 原生那个宽度是按它自己的字体算的，我们的字体和图标都不一样 —— 死守原生
        # 就会出现 `Create...tSetup` 这种截字，那还不如不一致。高度仍旧照原生
        # （侧边接口多的材质节点原生本来就更高，圆点位置也是照它来的）。
        widthUnits, heightUnits = nodeSizeUnits(node, graphGadget)
        self.__nativeWidth = widthUnits * PX_PER_UNIT
        self._height = heightUnits * PX_PER_UNIT
        self._width = max(self.__nativeWidth, self.__contentsWidth())
        # 卡片撑宽之后，原生给的接口 x 坐标要跟着按比例拉开，否则边上的圆点会跑到卡片里
        self.__noduleScaleX = (
            self._width / self.__nativeWidth if self.__nativeWidth > 1e-6 else 1.0
        )

        # 侧边（左 / 右）接口的行数。原生把材质节点的参数挂在这两条边上，
        # 节点本身也跟着长高 —— 高度已经由 `nodeSizeUnits` 拿到了。
        self._sideRows = max(len(self._nodules["left"]), len(self._nodules["right"]))

        # 接口位置 / 切线：优先照抄原生 nodule gadget 的坐标
        self.__nodulePositions = {}
        self.__noduleTangents = {}
        self.__noduleColors = {}
        self.__noduleRadii = {}  # 展开的 Color3f 子接口是 0.75 档，比常规圆点小
        self.__hoveredNodule = None
        self.__buildNodules(
            graphGadget
        )  # rebucket → 侧边分栏数据 →（有分栏就重排高度 / 圆点）
        self.__buildSideLabels()
        # 顶 / 底那两排接口的标签（场景节点的 `in` / `out` / `filter`…）。
        # 原生这些标签平时不画，只在**悬停节点**、**拖连线过来**、或者节点右键
        # 勾了 `/Connections/Show Input·Output Labels` 时才出来 —— 照做。
        self.__inputLabelsVisible = noduleLabelsVisible(node, Gaffer.Plug.Direction.In)
        self.__outputLabelsVisible = noduleLabelsVisible(
            node, Gaffer.Plug.Direction.Out
        )
        self.__dragLabelKeys = set()  # 拖连线过来时，能接的那几个
        self.__buildEndLabels()

        # 「加插口」的小 `+`（原生 PlugAdder）
        self.__adderPositions = {}
        self.__hoveredAdder = None
        self.__hoveredSection = (None, None)  # 鼠标停着的分栏折叠三角
        self.__buildAdders(graphGadget)

        self._accent = QtGui.QColor(nodeAccentColor(node))
        self._cardColor = QtGui.QColor(cardColor(node))
        # focus 之后不参与计算的节点也变暗（原生 `StandardNodeGadget` 同款：
        # 卡片走 DisabledState、名字 `setDimmed( True )`）
        self._active = True
        self.__dimAccent = _disabledColor(self._accent)
        self.__dimCard = _disabledColor(self._cardColor)
        self._focused = False
        self._focusFlagEnabled = focusGadgetVisible(node)
        self._dropTarget = False
        self.__nodeHovered = False  # 鼠标在这个节点上（focus flag 靠它决定显不显）
        self.__focusFlagHovered = False
        self._canEnter = canEnter(node)
        self._enabled = nodeEnabled(node)
        # `enabled` 要算的时候（`dependsOnCompute`），原生是问 ContextTracker 要答案的
        # （`m_nodeEnabledInContextTracker`）。None = 还不知道。
        self._dynamicEnabled = None
        self._bookmark = Gaffer.MetadataAlgo.numericBookmark(node)
        self._bookmarked = Gaffer.MetadataAlgo.getBookmarked(node)
        self._readOnly = Gaffer.MetadataAlgo.readOnly(node)
        # 注释：按编辑器当前的「显示哪些注释」过滤（工具条那个 Annotations 菜单）。
        # `_annotation` 留着给 tooltip 和老接口用 = 第一条可见的。
        self._annotations = nodeAnnotations(node, self.__visibleAnnotations())
        self._annotation = self._annotations[0][1:] if self._annotations else None
        self.__annotationWidth = self.__measureAnnotations()
        self._error = False
        self._errorMessage = None  # 原生 ErrorGadget 把出错信息挂在 tooltip 上

        # 位置 / 半径 / 颜色都定了，把 paint 和命中测试要的那份表一次算好
        self.__buildNoduleDraw()

        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, not self._readOnly)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)  # focus flag 要跟着鼠标进出显隐
        self.setZValue(10)

        self.setToolTip(self.__toolTip())

    ## 图标 + 名字至少要多宽才不被截。
    def __contentsWidth(self):

        if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY):
            return 0.0

        width = QtGui.QFontMetrics(_font(NODE_FONT_SIZE)).horizontalAdvance(
            self.nodeName
        )
        self.__nameWidth = float(width)  # `__paintTitle` 每帧要用，别再量一遍
        width += NODE_TEXT_MARGIN * 2.0
        if self._glyph is not None:
            width += GLYPH_SIZE + GLYPH_GAP

        return width

    ## 每个 nodule 在 item 局部坐标里的位置（像素，y 向下）。
    #
    # 有原生 gadget 就问它：`nodeGadget.nodule( plug ).transformedBound( nodeGadget )`
    # 的中心就是原生画圆点的地方，`connectionTangent()` 就是原生连线的出射方向。
    # 这样接口的位置 / 间距 / 挂哪条边全部和原生对齐，不用自己猜。
    def __buildNodules(self, graphGadget):

        gadget = graphGadget.nodeGadget(self.node) if graphGadget is not None else None

        for section, plugs in self._nodules.items():
            for index, plug in enumerate(plugs):

                position = None
                tangent = None

                nodule = gadget.nodule(plug) if gadget is not None else None
                if nodule is not None:
                    bound = nodule.transformedBound(gadget)
                    centre = bound.center()
                    position = QtCore.QPointF(
                        centre.x * PX_PER_UNIT * self.__noduleScaleX,
                        -centre.y * PX_PER_UNIT,
                    )
                    t = gadget.connectionTangent(nodule)
                    tangent = QtCore.QPointF(t.x, -t.y)
                    # **半径也问原生要**：常规圆点是 1 单位见方（= 6px），
                    # 而展开的 Color3f 子接口整组缩到 0.75（4.5px）——
                    # 照常规半径画的话三个圆点会糊成一坨。
                    size = bound.size()
                    radius = min(size.x, size.y) * 0.5 * PX_PER_UNIT
                    if 1.0 < radius < NODULE_RADIUS:
                        self.__noduleRadii[plugKey(self.node, plug)] = radius

                if position is None:
                    position = self.__sectionPoint(section, index, len(plugs))
                if tangent is None:
                    tangent = _sectionTangent(section)

                key = plugKey(self.node, plug)
                self.__nodulePositions[key] = position
                self.__noduleTangents[key] = tangent
                # 圆点颜色按**插口类型**来（`nodule:color`），这是原生「看圆点认类型」的依据
                self.__noduleColors[key] = QtGui.QColor(noduleColor(plug))

        if gadget is not None:
            self.__rebucketNodules()

        # 侧边参数分栏（Houdini 式可收放）：有分栏就①高度按可见行数重算
        # （收起来的只算 header 一行）；②侧边圆点不照原生位置，改按行往下排。
        # 没分栏的（含灯光节点）`buildSectionData` 返回空，一切照旧。
        self.__sectionData = buildSectionData(self.node, self._nodules)
        self.__sectionHeaders = {"left": [], "right": []}
        # 卡**内**最长标签宽（只有分栏节点才算得出来，但一律先建好这个属性 ——
        # 不然非分栏节点上问它就是 AttributeError）。和卡**外**留白 `__sideLabelWidth` 分开。
        self.__sectionedLabelWidth = 0.0
        if self.__sectionData:
            self.__addMissingSectionParams()
            self.__applySectionedLayout()

    ## 隐藏参数（`noduleLayout:visible=False`，`hasNodule` 过滤掉）不在 `_nodules` 里，
    # 原生 GraphEditor 上没圆点。材质节点要把**所有属性**都显示在侧边栏 ——
    # `buildSectionData` 已经把它们并进分栏了，这里补进 `_nodules` 那条边、给齐切线 /
    # 颜色（位置由 `__applySectionedLayout` 按行给）。标签在 `__buildSideLabels` 里
    # 会照 `_nodules` 一起画出来。
    def __addMissingSectionParams(self):

        seen = set()
        for plugs in self._nodules.values():
            for plug in plugs:
                seen.add(plugKey(self.node, plug))

        for side, groups in self.__sectionData.items():
            for name, plugs in groups:
                if name is None:
                    continue
                for plug in plugs:
                    key = plugKey(self.node, plug)
                    if key in seen:
                        continue
                    self._nodules[side].append(plug)
                    self.__noduleTangents[key] = _sectionTangent(side)
                    self.__noduleColors[key] = QtGui.QColor(noduleColor(plug))
                    seen.add(key)

    ## 一个插口上有没有连线（父插口没直接连的话钻进子插口看）。
    @staticmethod
    def __plugConnected(plug):

        if plug.getInput() is not None or len(plug.outputs()):
            return True
        for child in Gaffer.Plug.RecursiveRange(plug):
            if child.getInput() is not None or len(child.outputs()):
                return True

        return False

    ## 侧边圆点旁边要写的字：{ plugKey : ( 文字, 宽度, 有没有连线 ) }。
    def __buildSideLabels(self):

        self.__sideLabels = {}
        self.__sideLabelPlugs = {}  # 每条标签的「连没连线」看哪几个插口
        self.__sideLabelWidth = 0.0

        if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY):
            return

        # **一律按粗体量**：接上线的那几个画成粗体，按常规字量的话矩形比字窄，
        # 左边那排右对齐、被裁掉的是名字的**头**。按最宽那档量，常规字画在同一个
        # 矩形里位置一点不动，还省掉"连上线要重算几何"。
        metrics = QtGui.QFontMetricsF(_font(SIDE_LABEL_SIZE, bold=True))
        for section in ("left", "right"):
            for cluster in _noduleClusters(self.node, self._nodules.get(section, [])):
                # 一簇（展开的 Color3f）只写**一条**标签：三个字挨着 9px 间距会叠在
                # 一起，而原生那一格本来就是一个插口 —— 写父接口的名字，摆在正中那
                # 个圆点旁边，`r`/`g`/`b` 各自的名字留给悬停那个放大标签。
                if len(cluster) == 1:
                    plug, text = cluster[0], noduleLabel(cluster[0])
                else:
                    plug = cluster[len(cluster) // 2]
                    text = noduleLabel(cluster[0].parent())
                self.__sideLabelPlugs[plugKey(self.node, plug)] = cluster
                self.__sideLabels[plugKey(self.node, plug)] = (
                    text,
                    metrics.horizontalAdvance(text),
                    any(self.__plugConnected(p) for p in cluster),
                )

        # 分栏材质节点：参数名 / 分栏名都写在**卡片里面**，
        # 卡片宽度已经在 `__applySectionedLayout` 里照最宽那条撑开了 —— 包围盒不再
        # 需要外侧余量，外侧只剩折叠三角（`boundingRect` 有专门的兜底）。普通节点照旧：
        # 文字画在卡片外面，`boundingRect` 按最宽那条往外撑。
        if self.__sectionData:
            return

        for section in ("left", "right"):
            for plug in self._nodules.get(section, []):
                entry = self.__sideLabels.get(plugKey(self.node, plug))
                if entry is not None:
                    self.__sideLabelWidth = max(self.__sideLabelWidth, entry[1])

    ## 顶 / 底两排接口的标签。左右两侧那批走 `__buildSideLabels`（那是常驻的
    # Houdini 式参数名），这里是原生那套「平时不画」的接口名。
    def __buildEndLabels(self):

        self.__endLabels = {}
        self.__endLabelClusters = {}

        if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY):
            return

        metrics = QtGui.QFontMetricsF(_font(SIDE_LABEL_SIZE, bold=True))
        rect = self.cardRect()
        for section in ("top", "bottom"):
            for cluster in _noduleClusters(self.node, self._nodules.get(section, [])):
                if len(cluster) == 1:
                    plug, text = cluster[0], noduleLabel(cluster[0])
                else:
                    plug = cluster[len(cluster) // 2]
                    text = noduleLabel(cluster[0].parent())
                key = plugKey(self.node, plug)
                width = metrics.horizontalAdvance(text)
                self.__endLabels[key] = (
                    section,
                    plug,
                    text,
                    width,
                    any(self.__plugConnected(p) for p in cluster),
                )
                # `refreshSideLabels` 重算「接没接上」时要看整簇，不能只看代表那个
                self.__endLabelPlugs[key] = list(cluster)
                # 标签以圆点为中心横着画（`__paintEndLabels`），靶在卡片角上的圆点
                # 会让它伸出卡片边 —— 记下最多伸出多少，`boundingRect` 要留这份余量
                point = self.nodulePosition(plug)
                half = width / 2.0 + 4.0
                self.__endLabelOverhang = max(
                    self.__endLabelOverhang,
                    half - (point.x() - rect.left()),
                    half - (rect.right() - point.x()),
                )
                # 一簇（展开的 Color3f）三个子圆点共用这一条标签 —— 悬停的可能是
                # 其中任意一个，记下整簇的 key，画的时候好让位
                self.__endLabelClusters[key] = set(
                    plugKey(self.node, p) for p in cluster
                )

    ## 顶 / 底的接口标签现在要不要画。
    def endLabelsVisible(self):

        return bool(
            self.__endLabels
            and (
                self.__nodeHovered
                or self.__dragLabelKeys
                or self.__inputLabelsVisible
                or self.__outputLabelsVisible
            )
        )

    ## 这一刻真会画出来的那些端标签的 key。
    #
    # **鼠标正压着的那个圆点要让位** —— 那时候 `__paintHoveredNodule` 已经在圆点
    # 外侧画了一个放大标签，两个叠在一起糊成一团。左右两侧的常驻
    # 参数名也是同样的让位逻辑。一簇（展开的 Color3f）三个子圆点共用一条标签，
    # 悬停其中任意一个都算。
    def endLabelPaintKeys(self):

        result = []
        for key, entry in self.__endLabels.items():
            if not self.__endLabelVisible(entry[1], key):
                continue
            if self.__hoveredNodule in self.__endLabelClusters.get(key, ()):
                continue
            result.append(key)

        return result

    ## 某一条要不要画（metadata 只管自己那个方向）。
    def __endLabelVisible(self, plug, key):

        if self.__nodeHovered:
            return True
        if key in self.__dragLabelKeys:
            return True
        if plug.direction() == Gaffer.Plug.Direction.In:
            return self.__inputLabelsVisible
        return self.__outputLabelsVisible

    ## 拖连线过来时，把「能接上的那几个接口」的名字显示出来
    # （原生 `StandardNodeGadget::dragEnter` 就是这么干的）。
    def setDragLabelPlugs(self, plugs):

        keys = set(plugKey(self.node, plug) for plug in plugs or [])
        if keys == self.__dragLabelKeys:
            return

        self.__geometryChanged()
        self.__dragLabelKeys = keys
        self.update()

    ## 只把「有没有连线」这一项重新算一遍（连线一改就得刷，但**不重建 item** ——
    # 重建的代价是几十倍，而且会把手上的拖动打断）。
    def refreshSideLabels(self):

        changed = False
        for key, entry in self.__sideLabels.items():
            plugs = self.__sideLabelPlugs.get(key, [])
            connected = any(self.__plugConnected(p) for p in plugs)
            if connected != entry[2]:
                self.__sideLabels[key] = (entry[0], entry[1], connected)
                changed = True

        for key, entry in self.__endLabels.items():
            connected = any(
                self.__plugConnected(p)
                for p in self.__endLabelPlugs.get(key, (entry[1],))
            )
            if connected != entry[4]:
                self.__endLabels[key] = entry[:4] + (connected,)
                changed = True

        if changed:
            self.update()

    ## 按**原生给的切线**重新分边，并按边上的先后排好序。
    #
    # 元数据推出来的边偶尔和原生对不上（NameSwitch 就会上下串位），而切线是原生
    # `connectionTangent()` 给的，就是圆点真正长在哪条边上。
    def __rebucketNodules(self):

        rebuilt = {"top": [], "bottom": [], "left": [], "right": []}

        for plugs in self._nodules.values():
            for plug in plugs:

                tangent = self.__noduleTangents.get(plugKey(self.node, plug))
                if tangent is None:
                    rebuilt["bottom"].append(plug)
                    continue

                if abs(tangent.x()) > abs(tangent.y()):
                    section = "right" if tangent.x() > 0 else "left"
                else:
                    section = "bottom" if tangent.y() > 0 else "top"

                rebuilt[section].append(plug)

        for section, plugs in rebuilt.items():
            horizontal = section in ("top", "bottom")
            plugs.sort(
                key=lambda p: (
                    self.nodulePosition(p).x()
                    if horizontal
                    else self.nodulePosition(p).y()
                )
            )

        self._nodules = rebuilt

    ## 这个侧边当前展开时占几行（header 也算一行）。
    #
    # `( "param", [ plug, ... ] )` 一行里可以有**多个**插口 —— 展开的 Color3f
    # 子接口是一簇挤在同一行上的（照原生）。
    def __sectionRows(self, side):

        rows = self.__sectionRowsCache.get(side)
        if rows is not None:
            return rows

        # 这里是整个 item 里唯一读 `sectionCollapsed` 元数据的地方；折叠状态一变
        # 元数据信号会重建整个 item（`rebuildOnNodeMetadata`），所以算一次就够 ——
        # 不缓存的话每帧 paint、每次鼠标移动都在问 Metadata（66 个参数 11 栏的
        # standard_surface 一帧几百次）。
        rows = []
        for name, plugs in self.__sectionData.get(side, []):
            if name is None:
                rows.extend(
                    ("param", cluster) for cluster in _noduleClusters(self.node, plugs)
                )
            else:
                rows.append(("header", name))
                collapsed = sectionCollapsed(self.node, side, name)
                self.__sectionCollapsedCache[(side, name)] = collapsed
                if not collapsed:
                    rows.extend(
                        ("param", cluster)
                        for cluster in _noduleClusters(self.node, plugs)
                    )

        self.__sectionRowsCache[side] = rows
        return rows

    ## 这个侧边**现在画得出来**的参数（收起来的栏不画）。非分栏侧边原样返回。
    def __visibleSidePlugs(self, side):

        if side not in self.__sectionData:
            return self._nodules.get(side, [])

        visible = self.__visibleSideCache.get(side)
        if visible is None:
            visible = [
                plug
                for row in self.__sectionRows(side)
                if row[0] == "param"
                for plug in row[1]
            ]
            self.__visibleSideCache[side] = visible
        return visible

    ## 分栏模式：重算高度 + 按行重排侧边圆点，并记下每个 header 的 y。
    #
    # 高度公式和原生同一条（`rows * SIDE_ROW_UNITS + SIDE_ROWS_BASE_UNITS`），只是
    # 行数从「接口数」换成「header + 展开的参数」。没分栏的那条边照
    # `__sectionPoint` 重算（高度变了，原生给的 y 会离开垂直中线）。
    def __applySectionedLayout(self):

        self.__applySectionedSize()

        rect = self.cardRect()
        for side in ("left", "right"):
            if side in self.__sectionData:
                self.__placeSectionRows(side, rect)
            else:
                # 非分栏侧边：高度变了，按新卡片重排（居中分布）。**一簇算一行** ——
                # 展开的 Color3f 子接口挤在同一格里（照原生），不各占一行。
                clusters = _noduleClusters(self.node, self._nodules.get(side, []))
                for i, cluster in enumerate(clusters):
                    pos = self.__sectionPoint(side, i, len(clusters))
                    self.__placeCluster(cluster, pos.x(), pos.y())

    ## 把一簇接口摆在 `(x, y)` 这一格上：一个的居中，一簇的沿边排开、间距照原生
    # （相邻圆点刚好相切，= 两倍小半径）。
    def __placeCluster(self, cluster, x, y):

        if len(cluster) == 1:
            self.__nodulePositions[plugKey(self.node, cluster[0])] = QtCore.QPointF(
                x, y
            )
            return

        pitch = self.noduleRadius(cluster[0]) * 2.0
        first = -pitch * (len(cluster) - 1) / 2.0
        for i, plug in enumerate(cluster):
            self.__nodulePositions[plugKey(self.node, plug)] = QtCore.QPointF(
                x, y + first + pitch * i
            )

    ## 分栏节点的卡片尺寸：高度按行数、宽度按卡内最长那条标签（外加标题条的下限）。
    def __applySectionedSize(self):

        rows = 0
        for side in ("left", "right"):
            if side in self.__sectionData:
                rows = max(rows, len(self.__sectionRows(side)))
            else:
                rows = max(
                    rows,
                    len(_noduleClusters(self.node, self._nodules.get(side, []))),
                )
        self._height = (
            max(NODE_HEIGHT_UNITS, rows * SIDE_ROW_UNITS + SIDE_ROWS_BASE_UNITS)
            * PX_PER_UNIT
        )
        self._sideRows = rows

        # **卡片要宽到放得下参数名**：名字画在卡片**里面**，最宽那条标签 + 左右各一个圆点 + 间隙，不够就撑宽。没分栏的那条边
        # （材质右边那个 `out`）也照算。
        maxLeft = self.__sectionedLabelWidthFor("left")
        maxRight = self.__sectionedLabelWidthFor("right")
        self.__sectionedLabelWidth = max(maxLeft, maxRight)
        minWidth = (
            (NODULE_RADIUS + SIDE_LABEL_GAP) * 2.0
            + maxLeft
            + maxRight
            + SECTION_CARD_PAD
        )
        # 标题条也得放得下：图标 + 间隙 + 节点名 + 左右边距（名字画在色带里、左对齐）
        titleMetrics = QtGui.QFontMetricsF(_font(NODE_FONT_SIZE))
        minWidth = max(
            minWidth,
            (
                NODE_TEXT_MARGIN * 2.0
                + (GLYPH_SIZE + GLYPH_GAP if self._glyph is not None else 0.0)
                + titleMetrics.horizontalAdvance(self.nodeName)
                + 2.0
            ),
        )
        if minWidth > self._width:
            self._width = minWidth
            if self.__nativeWidth > 1e-6:
                self.__noduleScaleX = self._width / self.__nativeWidth

    ## 这一侧卡内最宽的一条标签。**按全部参数算、不只按可见行**（否则收起 / 展开
    # 宽度会跳），但每条都夹在 `SECTION_LABEL_MAX` 以内（超长的画省略号）。
    def __sectionedLabelWidthFor(self, side):

        metrics = QtGui.QFontMetricsF(_font(SIDE_LABEL_SIZE, bold=True))

        widths = []
        if side in self.__sectionData:
            for name, plugs in self.__sectionData[side]:
                if name is not None:
                    widths.append(metrics.horizontalAdvance(name))
                widths.extend(
                    metrics.horizontalAdvance(noduleLabel(plug)) for plug in plugs
                )
        else:
            widths = [
                metrics.horizontalAdvance(noduleLabel(plug))
                for plug in self._nodules.get(side, [])
            ]

        widths = [min(w, SECTION_LABEL_MAX) for w in widths]
        return max(widths) if widths else 0.0

    ## 一栏一行地摆这一侧：栏名一行、栏里的参数各一行，收起来的栏把圆点锚到栏名那行。
    def __placeSectionRows(self, side, rect):

        # 固定行距，行区从**名字条下面**往下排（名字钉在顶栏）：卡片高 = 行数 × 行距
        # + 底座（`SIDE_ROWS_BASE_UNITS` 那一段），所以行区顶 = rect.top() + 底座。
        # 顶栏给名字，行区只排参数（整列居中的话名字会浮在材质卡正中间）。
        pitch = SIDE_ROW_UNITS * PX_PER_UNIT
        rowTop = rect.top() + SIDE_ROWS_BASE_UNITS * PX_PER_UNIT
        x = rect.left() if side == "left" else rect.right()

        for i, row in enumerate(self.__sectionRows(side)):
            y = rowTop + pitch * (i + 0.5)
            if row[0] != "header":
                self.__placeCluster(row[1], x, y)
                continue

            self.__sectionHeaders[side].append((row[1], y))
            # 收起来的栏：参数圆点**锚到 header 这一行** —— 隐藏的插口还连着线的话，
            # 连线终点停在 header 那儿（表示"这一栏里有接线"），不会甩出卡片。
            for name, plugs in self.__sectionData[side]:
                if name == row[1] and sectionCollapsed(self.node, side, name):
                    for plug in plugs:
                        self.__nodulePositions[plugKey(self.node, plug)] = (
                            QtCore.QPointF(x, y)
                        )

    ## 折叠三角的命中矩形（item 局部坐标）。三角画在**卡片边线上**
    # （左 = 卡片左缘、右 = 卡片右缘，和 paint 里同一个位置）。整条栏名行的命中
    # 见 `__sectionRowRect`，`sectionAt` 两个都认。
    def __sectionTriangleRect(self, side, y):

        rect = self.cardRect()
        cx = rect.left() if side == "left" else rect.right()
        return QtCore.QRectF(
            cx - SECTION_TRIANGLE_HIT,
            y - SECTION_TRIANGLE_HIT,
            SECTION_TRIANGLE_HIT * 2,
            SECTION_TRIANGLE_HIT * 2,
        )

    ## 分栏 header 这一**整行**的命中矩形（item 局部坐标）——
    # Houdini 式：三角和栏名一起点（卡边线上那个 8px 三角单独用太难瞄）。
    # 只覆盖自己这一侧的半张卡，另一侧的行归另一侧。
    def __sectionRowRect(self, side, y):

        rect = self.cardRect()
        half = SIDE_ROW_UNITS * PX_PER_UNIT / 2.0
        if side == "left":
            left, right = rect.left() - SECTION_TRIANGLE_HIT, rect.center().x()
        else:
            left, right = rect.center().x(), rect.right() + SECTION_TRIANGLE_HIT
        return QtCore.QRectF(left, y - half, right - left, half * 2.0)

    ## 这个局部坐标点落在哪个分栏 header 上（三角**或**整条栏名行），
    # 返回 ( side, 分栏名 )。
    def sectionAt(self, point):

        for side in ("left", "right"):
            for name, y in self.__sectionHeaders.get(side, []):
                if self.__sectionTriangleRect(side, y).contains(
                    point
                ) or self.__sectionRowRect(side, y).contains(point):
                    return (side, name)
        return None

    ## `+` 画在哪。
    #
    # 原生把「一排 nodule + 末尾的 adder」整体居中，所以 adder 的坐标可以直接从 nodule
    # 的坐标反推出来：**它们的和为 0**（实测 Box 提升一个插口时 nodule 在 -1.5、
    # adder 就在 +1.5；两个插口时 -1.5/0，adder 还是 +1.5）。
    def __buildAdders(self, graphGadget):

        if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY):
            return

        rect = self.cardRect()
        inset = ADDER_SIZE * 0.6

        # 谁有 `+` 以原生 gadget 为准（`plugAdders` 里做的），
        # 一条边上就画一个，不自己发明。
        for section in plugAdders(self.node, graphGadget):

            # 分栏材质节点：所有属性都显示在卡片里了（收放由分栏三角管），
            # `parameters` 上那个「显示隐藏参数」的 `+` 是多余的 —— 不画。
            if self.__sectionData and section in self.__sectionData:
                continue

            horizontal = section in ("top", "bottom")
            coordinates = [
                (
                    self.nodulePosition(plug).x()
                    if horizontal
                    else self.nodulePosition(plug).y()
                )
                for plug in self._nodules.get(section, [])
            ]

            # 原生把「一排 nodule + 末尾的 adder」整体居中：
            #   一个 nodule  → 两者关于中线对称（坐标和为 0）
            #   多个 nodule  → 沿用它们之间的间距，接在最后一个后面
            #   没有 nodule  → 就在这条边的正中
            if not coordinates:
                coordinate = 0.0
            elif len(coordinates) == 1:
                coordinate = -coordinates[0]
            else:
                coordinate = coordinates[-1] + (coordinates[-1] - coordinates[-2])

            if horizontal:
                x = max(rect.left() + inset, min(rect.right() - inset, coordinate))
                y = rect.top() if section == "top" else rect.bottom()
            else:
                y = max(rect.top() + inset, min(rect.bottom() - inset, coordinate))
                x = rect.left() if section == "left" else rect.right()

            self.__adderPositions[section] = QtCore.QPointF(x, y)

    def adderSections(self):

        return dict(self.__adderPositions)

    ## 命中测试：局部坐标 `point` 附近有没有 `+`，有就返回它所在的边。
    def adderAt(self, point):

        best, bestDistance = None, ADDER_HIT_RADIUS

        for section, position in self.__adderPositions.items():
            d = math.hypot(position.x() - point.x(), position.y() - point.y())
            if d < bestDistance:
                best, bestDistance = section, d

        return best

    ## 鼠标停在某个分栏的折叠三角上（`name` 为 None = 没有）。只换悬停小框，不重画。
    def setHoveredSection(self, side, name):

        if (side, name) == self.__hoveredSection:
            return

        self.__hoveredSection = (side, name)
        if name is None:
            self.setToolTip(self.__toolTip())
            return

        self.setToolTip(
            "参数栏「%s」—— 点一下%s这一栏"
            % (name, "展开" if sectionCollapsed(self.node, side, name) else "收起")
        )

    def setHoveredAdder(self, section):

        if section == self.__hoveredAdder:
            return

        self.__hoveredAdder = section
        # `+` 上的悬停小框（中文）
        self.setToolTip(
            "＋ 加接口：把连线拖到这里 —— Box 会提升出插口、Switch / NameSwitch 加一路、"
            "材质会让你挑一个藏起来的参数"
            if section is not None
            else self.__toolTip()
        )
        self.update()

    def __toolTip(self):

        tip = "<b>%s</b><br>%s" % (
            self.node.getName(),
            type(self.node).__module__ + "." + type(self.node).__name__,
        )
        if self._readOnly:
            tip += "<br><i>只读，改不了</i>"
        if self._enabled is False:
            tip += "<br><i>已停用</i>"
        for unusedName, text, unusedColor in self._annotations:
            tip += "<br><br>%s" % text.replace("\n", "<br>")
        if self._errorMessage:
            tip += "<br><br><i>出错了：</i><br>%s" % self._errorMessage.replace(
                "\n", "<br>"
            )
        return tip

    ## 注释里最长那条有多宽（包围盒要按它往右让位）。
    def __measureAnnotations(self):

        if not self._annotations:
            return 0.0

        metrics = QtGui.QFontMetricsF(_font(ANNOTATION_SIZE))
        return max(
            metrics.horizontalAdvance(text.split("\n")[0])
            for unusedName, text, unusedColor in self._annotations
        )

    ## 编辑器现在让画哪些注释（拿不到 owner 就用默认那套）。
    def __visibleAnnotations(self):

        owner = self._owner
        return owner.getVisibleAnnotations() if owner is not None else None

    ## 「显示哪些注释」改了 —— 只重算这一项，不重建 item。
    def refreshAnnotations(self):

        annotations = nodeAnnotations(self.node, self.__visibleAnnotations())
        if annotations == self._annotations:
            return

        self.__geometryChanged()
        self._annotations = annotations
        self._annotation = annotations[0][1:] if annotations else None
        self.__annotationWidth = self.__measureAnnotations()
        self.setToolTip(self.__toolTip())
        self.update()

    ## 几何要变（`boundingRect` / `shape` 会给出不同答案）之前必须调这个：
    # 先告诉 Qt（它拿**旧**包围盒把 item 从索引里摘下来），再作废缓存。
    ## 包围盒要变了（悬停 / focus / 注释 / 拖连线标签）。`shape()` 不在这里作废：
    # 它只取决于卡片、分栏三角和 focus 开关，item 生命期内都不变。
    def __geometryChanged(self):

        self.prepareGeometryChange()
        self.__boundsCache = None

    def boundingRect(self):

        if self.__boundsCache is None:
            self.__boundsCache = self.__computeBoundingRect()
        return QtCore.QRectF(self.__boundsCache)

    def __computeBoundingRect(self):

        # focus 环 + nodule + 注释 + 卡外的侧边参数名都要包进来，否则移动留残影。
        # ⚠️ 悬停余量不能**盖掉**侧边标签的余量：`__sideLabelWidth` 可能比 150 还宽，
        # 悬停时硬换成 150 会把侧边标签裁掉（那半截就变成残影）。
        # 悬停放大标签用的是**完整**参数名，长名字（`transmission_scatter_anisotropy`）
        # 能伸出 150px 之外 —— `__hoverMargin` 是按它真实宽度算的。
        margin = max(
            self.__sideLabelWidth + SIDE_LABEL_GAP + NODULE_RADIUS + 6.0,
            (
                max(150.0, self.__hoverMargin)
                if self.__hoveredNodule is not None
                else 10.0
            ),
        )

        # focus 角标画在卡片外面（所有节点），包围盒要放得下（不然拖动留残影）。
        # **判据是「会不会画」而不是「有没有 focus」** —— 鼠标停在节点上时没 focus
        # 也画角标（`focusFlagVisible`），框选一堆节点拖着走时光标就压在其中一个
        # 上面，缩放过的画面里那个角标会拖出一串残影。
        if self.focusFlagVisible():
            margin = max(margin, self.focusTabMaxSize() + 6.0)
        else:
            # 不画的时候也要放得下**命中区**（`shape()` 一直把它划进去）
            margin = max(margin, self.focusTabHitSize() + 6.0)

        # 分栏材质节点：外侧只剩折叠三角（`__sideLabelWidth` 是 0），三角画在卡片
        # 边上、命中半径 `SECTION_TRIANGLE_HIT` —— 兜底别裁到它（不然拖动留残影）。
        margin = max(margin, SECTION_TRIANGLE_HIT + 4.0)

        # 书签旗 / 编号画在卡片左上角外面，编号那串字最远到左边 28 个（缩放前的）像素，
        # 拉远时按 `BOOKMARK_MAX_SCALE` 放大（`__paintBookmark`）
        if self._bookmarked or self._bookmark:
            margin = max(margin, 28.0 * BOOKMARK_MAX_SCALE + 4.0)

        # 顶 / 底的接口标签画在卡片外面（只在显示的时候占地方，别让平时的包围盒变大）
        if self.endLabelsVisible():
            margin = max(
                margin, NODULE_RADIUS + SIDE_LABEL_GAP + 20.0, self.__endLabelOverhang
            )

        # 注释画在卡片**右边**、一条条往下排（`__paintAnnotations`）—— 不算进
        # 包围盒的话，加了注释的节点一拖就留一串文字残影。
        if self._annotations:
            margin = max(margin, ANNOTATION_GAP + self.__annotationWidth + 6.0)
            # 多条注释是竖着排的，末尾可能垂到卡片下面去
            overflow = (
                ANNOTATION_LINE_HEIGHT * len(self._annotations)
                + 16.0
                - self._height / 2.0
            )
            margin = max(margin, overflow)

        return QtCore.QRectF(
            -self._width / 2.0 - margin,
            -self._height / 2.0 - margin,
            self._width + margin * 2,
            self._height + margin * 2 + 6,
        )

    def cardRect(self):

        return QtCore.QRectF(
            -self._width / 2.0, -self._height / 2.0, self._width, self._height
        )

    ## 框选判定用的矩形（scene 坐标）—— 用卡片本身，不含阴影/悬停标签那些余量。
    # 原生要求**完全框住**才算选中。
    def selectionRect(self):

        return self.sceneCardRect()

    ## 卡片本身的 scene 矩形（连线绕开节点也用它）。
    def sceneCardRect(self):

        return self.mapToScene(self.cardRect()).boundingRect()

    ## 命中形状。**必须重写** —— 默认实现拿 `boundingRect()` 当命中区，而我们的
    # boundingRect 在有接口被悬停时会撑到 ±150px（要放得下放大的圆点和标签）。
    # 不重写的话，刚悬停过的那个节点会把周围一大片的点击/拖放都吃掉（z 值还被抬高了），
    # 表现就是「从这个节点的小圆点拖到隔壁节点上连不上」—— 上下挨得近的两个节点必现。
    def shape(self):

        if self.__shapeCache is None:
            self.__shapeCache = self.__computeShape()
        return self.__shapeCache

    def __computeShape(self):

        path = QtGui.QPainterPath()
        # **必须显式设 WindingFill**：`QPainterPath` 默认是 `OddEvenFill`，往同一条 path
        # 里 `addRect` 两个**互相重叠**的矩形，重叠那块会被异或成**洞** —— 折叠三角的
        # 命中框贴在卡片边线上、和卡片那块重叠，结果三角正下方那一小片反而不算命中区，
        # `items()` / `contains()` 全部返回空（表现就是「点展开三角一点反应都没有」，
        # 而 item 自己的 `sectionAt()` 却是对的 —— 差别就在这条 path 的填充规则上）。
        path.setFillRule(QtCore.Qt.WindingFill)
        path.addRect(
            self.cardRect().adjusted(
                -NODULE_HIT_RADIUS,
                -NODULE_HIT_RADIUS,
                NODULE_HIT_RADIUS,
                NODULE_HIT_RADIUS,
            )
        )

        # 分栏折叠三角画在卡片边线上、一半伸到卡片外面，`items()` 按 shape() 命中 ——
        # 不把三角划进命中形状，鼠标点在外面那半个三角上 `sectionHeaderAt` 的探针就
        # 找不到这个节点。只加三角那一小块（栏名行在卡片里面，本来就在命中形状内）。
        for side in ("left", "right"):
            for _, y in self.__sectionHeaders.get(side, []):
                path.addRect(self.__sectionTriangleRect(side, y))

        # focus 角标同理：画在卡片右上角**外面**，不划进命中形状的话 `items()`
        # 只在卡片 + `NODULE_HIT_RADIUS` 那一圈里认得它 —— 角标外面那半截既
        # 悬停不出来（`focusFlagVisible` 要 `__nodeHovered`）也点不动。**用固定尺寸**（`shape` 是几何，
        # 不能跟着画的时候才知道的 lod 变），拉远之后那一圈交给 view 的
        # `focusTabAt` 用探针兜。
        if self._focusFlagEnabled:
            path.addRect(self.focusFlagHitRect())

        return path

    ## 卡片轮廓（尺寸在构造之后不变，算一次）。
    def cardPath(self):

        if self.__cardPathCache is None:
            self.__cardPathCache = self.__computeCardPath()
        return self.__cardPathCache

    def __computeCardPath(self):

        rect = self.cardRect()
        path = QtGui.QPainterPath()

        if self._shape == SHAPE_DOT:
            path.addEllipse(rect)

        elif self._shape == SHAPE_OVAL:
            radius = rect.height() / 2.0
            path.addRoundedRect(rect, radius, radius)

        elif self._shape == SHAPE_AUXILIARY:
            path.addRoundedRect(rect, NODE_RADIUS, NODE_RADIUS)

        else:
            path.addRoundedRect(rect, NODE_RADIUS, NODE_RADIUS)

        return path

    ## nodule 在**item 局部坐标**里的位置。
    def nodulePosition(self, plug):

        result = self.__nodulePositions.get(plugKey(self.node, plug))
        if result is not None:
            return result

        # 没有 nodule（aux 连接）→ 退回边中点
        return self.__sectionCentre(plugSection(plug))

    ## nodule 的出射方向（连线从这儿伸出去的切线，y 向下）。
    def noduleTangent(self, plug):

        result = self.__noduleTangents.get(plugKey(self.node, plug))
        if result is not None:
            return result

        return _sectionTangent(plugSection(plug))

    ## 这个 nodule 该画多大（半径，px）。常规是 `NODULE_RADIUS`，展开的复合数值
    # 子接口照原生缩到 0.75 档。
    def noduleRadius(self, plug):

        return self.__noduleRadii.get(plugKey(self.node, plug), NODULE_RADIUS)

    def __sectionCentre(self, section):

        rect = self.cardRect()
        return {
            "top": QtCore.QPointF(0, rect.top()),
            "bottom": QtCore.QPointF(0, rect.bottom()),
            "left": QtCore.QPointF(rect.left(), 0),
            "right": QtCore.QPointF(rect.right(), 0),
        }.get(section, QtCore.QPointF(0, rect.bottom()))

    def __sectionPoint(self, section, index, count):

        rect = self.cardRect()

        if section in ("top", "bottom"):
            margin = min(NODULE_MARGIN, rect.width() / 2.0)
            left = rect.left() + margin
            span = max(0.0, rect.width() - margin * 2)
            x = left + (span * (index + 0.5) / count if count else span * 0.5)
            return QtCore.QPointF(x, rect.top() if section == "top" else rect.bottom())

        x = rect.left() if section == "left" else rect.right()
        span = rect.height() - 8
        y = rect.top() + 4 + (span * (index + 0.5) / count if count else span * 0.5)
        return QtCore.QPointF(x, y)

    ## paint 和命中测试共用的那份表：每条边上**现在画得出来**的圆点，连同 key /
    # 位置 / 半径 / 颜色一次算好。`plugKey` 是一次 C++ `relativeName`，原来每帧每个
    # 圆点要算三遍（找 key、查位置、查半径），一帧几千次。
    def __buildNoduleDraw(self):

        self.__noduleDraw = {}
        raised = QtGui.QColor(_raisedColor)

        for section, plugs in self._nodules.items():
            visible = (
                self.__visibleSidePlugs(section)
                if section in ("left", "right")
                else plugs
            )
            entries = []
            for plug in visible:
                key = plugKey(self.node, plug)
                entries.append(
                    (
                        plug,
                        key,
                        self.nodulePosition(plug),
                        self.__noduleRadii.get(key, NODULE_RADIUS),
                        self.__noduleColors.get(key, raised),
                    )
                )
            self.__noduleDraw[section] = entries

    ## 命中测试：局部坐标 `point` 附近有没有 nodule，有就返回 plug。
    def noduleAt(self, point):

        best, bestDistance = None, NODULE_HIT_RADIUS
        px, py = point.x(), point.y()

        for entries in self.__noduleDraw.values():
            for plug, _, p, _, _ in entries:
                d = math.hypot(p.x() - px, p.y() - py)
                if d < bestDistance:
                    best, bestDistance = plug, d

        return best

    ## 鼠标移到哪个接口上了（`plug` 为 None = 没有）。原生的表现是圆点半径翻倍 +
    # 变成 HighlightColor，我们再把插口名一并显示出来，并把悬停小框换成这个参数的中文说明。
    def setHoveredNodule(self, plug):

        name = plugKey(self.node, plug) if plug is not None else None
        if name == self.__hoveredNodule:
            return

        self.__geometryChanged()
        self.__hoveredNodule = name
        if plug is not None:
            hoverRadius = NODULE_HOVER_RADIUS * self.noduleRadius(plug) / NODULE_RADIUS
            labelWidth = (
                QtGui.QFontMetrics(_font(_HOVER_LABEL_FONT_SIZE)).horizontalAdvance(
                    noduleLabel(plug)
                )
                + 10.0
            )
            self.__hoverMargin = labelWidth + hoverRadius + 4.0 + 6.0
        else:
            self.__hoverMargin = 0.0
        self.setZValue(20 if name is not None else 10)
        self.setToolTip(
            self.__noduleToolTip(plug) if plug is not None else self.__toolTip()
        )
        self.update()

    ## 悬停在参数圆点上弹的那个小框（中文）：参数名 + 输入 / 输出 + 接没接上 +
    # 节点自己注册的 `description` 元数据（原生文档，英文，照抄不翻）。
    def __noduleToolTip(self, plug):

        label = plug.relativeName(self.node)
        isInput = plug.direction() == Gaffer.Plug.Direction.In
        tip = "<b>%s</b><br>%s参数 · %s" % (
            label,
            "输入" if isInput else "输出",
            type(plug).__name__,
        )

        if isInput:
            source = plug.getInput()
            if source is not None:
                node = source.node()
                tip += "<br>已连接：%s.%s" % (
                    node.getName() if node is not None else "?",
                    source.relativeName(node) if node is not None else source.getName(),
                )
            else:
                tip += "<br>未连接（从圆点拖出去就能接线）"
        else:
            count = len(plug.outputs())
            tip += "<br>%s" % ("接出去 %d 处" % count if count else "还没接出去")

        description = self.__plugDescription(plug)
        if description:
            tip += "<br><br>%s" % description

        return tip

    ## 插口自己注册的 `description` 元数据（原生文档）。太长的截一段。
    @staticmethod
    def __plugDescription(plug):

        description = Gaffer.Metadata.value(plug, "description")
        if not description:
            return None

        description = " ".join(str(description).split())
        return description if len(description) <= 200 else description[:197] + "..."

    def hoveredNodule(self):

        return self.__hoveredNodule

    ## 这个节点参不参与 focus 节点的计算（不参与的整块变暗，和原生一样）。
    def setNodeActive(self, active):

        if active == self._active:
            return

        self._active = active
        self.update()

    def isNodeActive(self):

        return self._active

    ## `enabled` 得靠 compute 才知道时，ContextTracker 算出来的那个答案。
    # None = 它没跟踪这个节点（原生这时候什么都不画）。
    def setDynamicEnabled(self, enabled):

        if enabled == self._dynamicEnabled:
            return

        self._dynamicEnabled = enabled
        self.update()

    def dynamicEnabled(self):

        return self._dynamicEnabled

    ## 现在该画哪种停用线："static" / "dynamic" / "unknown" / None。
    def strikeThroughState(self):

        if self._enabled is False:
            return "static"

        if self._enabled is None:
            if self._dynamicEnabled is False:
                return "dynamic"
            if self._dynamicEnabled is None:
                return "unknown"

        return None

    ## 拖连线时鼠标落在这个节点上（原生 `StandardNodeGadget` 在 dragEnter 里
    # `setHighlighted( true )`，整块卡片描边变高亮色）。
    def setDropTarget(self, dropTarget):

        if dropTarget == self._dropTarget:
            return

        self._dropTarget = dropTarget
        self.update()

    ## 折角 tab 的边长。
    #
    # 角标一律画在卡片右上角**外面**，所以不按卡片比例缩 —— 所有节点一个尺寸，
    # 小到 Dot 也是这么大，一眼就认得出，也不占卡片上任何可点区域（画在里面的话
    # 30x30 的 Dot 上 21% 面积会被当成"点 focus"，而且 Dot 走 `paint()` 早退分支画不到）。
    #
    # 传了 `lod`（镜头缩放）就**反向补偿**：拉远时按 1/lod 放大，屏幕上至少
    # `FOCUS_TAB_MIN_PIXELS` 那么大。
    def focusTabSize(self, lod=None):

        size = FOCUS_TAB_SIZE

        # ⚠️ **补偿必须夹住**（`FOCUS_LOD_FLOOR`）：`boundingRect()` 是"几何"，
        # 只能在 `prepareGeometryChange()` 之后变，而 lod 是**画的时候**才知道的 ——
        # 不夹的话角标会跑到包围盒外面去，缩过的画面里拖节点就留一串金色拖影。
        if lod is not None and 1e-6 < lod < 1.0:
            size = max(size, FOCUS_TAB_MIN_PIXELS / max(lod, FOCUS_LOD_FLOOR))

        return size

    ## 命中用的边长：画出来那么大，再往卡片外放宽 `FOCUS_TAB_HIT_PAD`。
    def focusTabHitSize(self, lod=None):

        return self.focusTabSize(lod) + FOCUS_TAB_HIT_PAD

    ## 角标 / 小旗在 item 坐标里最大能画到多大（`boundingRect` 拿它留余量）。
    def focusTabMaxSize(self):

        return max(
            FOCUS_TAB_SIZE,
            FOCUS_TAB_MIN_PIXELS / FOCUS_LOD_FLOOR,
            FOCUS_FLAG_PIXELS / FOCUS_LOD_FLOOR,
        )

    ## 折角 tab 的三角形（item 局部坐标），贴在卡片右上角外侧。
    def focusTabPolygon(self, lod=None):

        rect = self.cardRect()
        size = self.focusTabSize(lod)

        return QtGui.QPolygonF(
            [
                QtCore.QPointF(rect.right(), rect.top() - size),
                QtCore.QPointF(rect.right() + size, rect.top()),
                QtCore.QPointF(rect.right(), rect.top()),
            ]
        )

    ## 折角 tab 画出来那块的包围盒（**视觉**用，比命中区小）。
    def focusFlagRect(self):

        return self.focusTabPolygon().boundingRect()

    ## 点击判定区：卡片右上角**外侧**那个方角（item 局部坐标）。
    #
    # 角标一律画在卡片外面，所以方角空着的那半边白送 —— 卡片上的可点区域一点不占，
    # 而按斜边判的话面积只有一半、三角那两个尖还最难瞄。
    def focusFlagHitRect(self, lod=None):

        rect = self.cardRect()
        size = self.focusTabHitSize(lod)

        return QtCore.QRectF(rect.right(), rect.top() - size, size, size)

    ## 这个局部坐标点算不算点在折角上。**按方角判、不按三角形斜边** ——
    # 角标画在卡片外面，方角那半边不占卡片上任何可点区域，拿它当按钮面积正好；
    # 容差 1.5px 往卡片里让一点，方便贴着边线点。
    def focusFlagAt(self, point, lod=None):

        if not self.focusFlagVisible():
            return False

        rect = self.cardRect()

        # 往**右上**量，卡片里面一点都不算
        size = self.focusTabHitSize(lod)
        dx = point.x() - rect.right()
        dy = rect.top() - point.y()
        return -1.5 <= dx <= size and -1.5 <= dy <= size

    ## 现在画不画 flag：focus 中的常显，其余只在鼠标停在这个节点上时显。
    # 节点上把 `nodeGadget:focusGadgetVisible` 关掉的话一律不画（原生
    # `StandardNodeGadget::updateFocusGadgetVisibility`）。
    def focusFlagVisible(self):

        if not self._focusFlagEnabled:
            return False

        return self._focused or self.__nodeHovered

    def hoverEnterEvent(self, event):

        self.__geometryChanged()
        self.__nodeHovered = True
        self.update()
        QtWidgets.QGraphicsItem.hoverEnterEvent(self, event)

    def hoverLeaveEvent(self, event):

        self.__geometryChanged()
        self.__nodeHovered = False
        if self.__focusFlagHovered:
            self.__focusFlagHovered = False
            self.setToolTip(self.__toolTip())
        self.update()
        QtWidgets.QGraphicsItem.hoverLeaveEvent(self, event)

    def hoverMoveEvent(self, event):

        overFlag = self.focusFlagAt(event.pos())
        if overFlag != self.__focusFlagHovered:
            self.__focusFlagHovered = overFlag
            self.setToolTip(
                ("点一下取消 Focus" if self._focused else "点一下把 Focus 设到这个节点")
                if overFlag
                else self.__toolTip()
            )
            self.update()

        QtWidgets.QGraphicsItem.hoverMoveEvent(self, event)

    def setFocused(self, focused):

        if focused != self._focused:
            # focus 角标会画（`focusFlagVisible`），包围盒要放宽到 `focusTabMaxSize`
            # —— 不报几何变化的话 Qt 索引里还是小的那份，拉远之后拖动留金色拖影
            self.__geometryChanged()
            self._focused = focused
            self.update()

    def setError(self, error, message=None):

        message = str(message) if message else None
        if error == self._error and message == self._errorMessage:
            return

        self._error = error
        self._errorMessage = message
        self.setToolTip(self.__toolTip())
        self.update()

    def itemChange(self, change, value):

        # 拖动时自动对齐：把「即将去到的位置」交给编辑器修一下
        if (
            change == QtWidgets.QGraphicsItem.ItemPositionChange
            and self._owner is not None
        ):
            return self._owner._snapNodePosition(self, value)

        if (
            change == QtWidgets.QGraphicsItem.ItemPositionHasChanged
            and self._owner is not None
        ):
            self._owner._nodeItemMoved(self)

        return QtWidgets.QGraphicsItem.itemChange(self, change, value)

    ##########################################################################
    # 绘制（扁平：单色卡片 + 细描边 + 顶部类型色带，不做渐变 / 投影）
    ##########################################################################

    def paint(self, painter, option, widget=None):

        lod = _lod(option, painter)
        rect = self.cardRect()
        selected = self.isSelected()

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        path = self.cardPath()

        # --- 远景：一个纯色块就够了 ---
        if lod < LOD_MEDIUM:
            self.__paintFar(painter, path, selected, lod)
            return

        self.__paintCardBody(painter, path, selected)

        self.__paintAccentBand(painter, rect, path)

        self.__paintNodules(painter)

        self.__paintSideLabels(painter, lod)
        self.__paintEndLabels(painter, lod)

        self.__paintSectionHeaders(painter, lod)

        self.__paintAdders(painter)

        # **focus 角标 / 书签要画在这里**（Dot 早退之前）：放在函数末尾的话，Dot 走的
        # 是下面那条早退分支，压根走不到 —— Dot 上看不到角标、没法设 focus。
        # 角标和书签本来就是"一眼找到某个节点"用的，Dot 也要有。
        if self.focusFlagVisible():
            self.__paintFocusTab(painter, path, lod)

        if self._bookmarked or self._bookmark:
            self.__paintBookmark(painter, rect, lod)

        # Dot 到此为止：和原生一样只是个小圆点，不写名字
        if self._shape == SHAPE_DOT:
            return

        # --- 小方块（Expression / Spreadsheet …）：只写一个首字母，和原生一致 ---
        if self._shape == SHAPE_AUXILIARY:
            painter.setFont(_font(10.0, bold=True))
            painter.setPen(QtGui.QColor("#14161a"))
            painter.drawText(rect, QtCore.Qt.AlignCenter, auxiliaryLabel(self.node))
            return

        self.__paintTitle(painter, rect)

        self.__paintStrikeThrough(painter, rect)

        # （focus 角标 / 书签已经在上面画过了 —— 必须在 Dot 那条早退之前，
        # 而且要在 `lod < LOD_NEAR` 这道早退之前：这两样恰恰是拉远时最需要的）

        if lod < LOD_NEAR:
            return

        self.__paintDetails(painter, rect)

    def __paintFar(self, painter, path, selected, lod):

        painter.setPen(QtCore.Qt.NoPen)
        if selected:
            painter.setBrush(QtGui.QColor(_selectedBorder))
        else:
            # **别把 focus 的整块刷成金色**：本来就是黄色的节点（灯光那些）会被误认
            # 成 focus。focus 一律靠**右上角那个角标**认，形状说话、不靠颜色。
            painter.setBrush(self._accent if self._active else self.__dimAccent)
        painter.drawPath(path)

        if self._focused:
            self.__paintFocusTab(painter, path, lod)

    def __paintCardBody(self, painter, path, selected):

        # --- 卡片本体 ---
        # 主体色 = 节点自己的 `nodeGadget:color` 压暗（色相还在，字也读得清）。
        # Dot / 小方块没有名字也没有色带，整个块直接用类型色，不然只是个灰疙瘩。
        if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY):
            painter.setBrush(self._accent if self._active else self.__dimAccent)
        else:
            painter.setBrush(self._cardColor if self._active else self.__dimCard)

        if self._error:
            pen = QtGui.QPen(QtGui.QColor(_errorColor), 2.0)
        elif self._dropTarget:
            pen = QtGui.QPen(QtGui.QColor(_highlightColor), 2.4)
        elif selected:
            pen = QtGui.QPen(QtGui.QColor(_selectedBorder), 2.0)
        else:
            pen = QtGui.QPen(QtGui.QColor(_cardBorder), 1.0)
        if self._readOnly:
            pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)

    def __paintAccentBand(self, painter, rect, path):

        # --- 顶部类型色带（扁平的一条，不做渐变）---
        #
        # **focus 中不把整条色带刷成金色**（那条长条太抢眼）——
        # 「当前 focus 是谁」只由右上角那个折角说了算。
        if self._shape == SHAPE_RECTANGLE:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(self._accent if self._active else self.__dimAccent)
            if self.__sectionData:
                # **分栏材质节点：色带加宽成标题条**，名字 + 图标
                # 都画在它里面（见下面画名字那段）。**要按卡片轮廓裁剪** —— 直接画一个
                # 圆角矩形的话，圆角半径和卡片对不上，顶部两个角会露出细缝。
                painter.save()
                painter.setClipPath(path)
                painter.drawRect(
                    QtCore.QRectF(
                        rect.left(), rect.top(), rect.width(), SECTION_TITLE_HEIGHT
                    )
                )
                painter.restore()
            else:
                painter.drawRoundedRect(
                    QtCore.QRectF(
                        rect.left() + 1.0,
                        rect.top() + 1.0,
                        rect.width() - 2.0,
                        ACCENT_HEIGHT,
                    ),
                    1.5,
                    1.5,
                )

    def __paintNodules(self, painter):

        # --- nodule（大小、颜色、悬停放大都照原生）---
        # 收起来的栏里的圆点不画（`__visibleSidePlugs` 已经过滤掉了）。
        hovered = None
        hoveredKey = self.__hoveredNodule
        painter.setPen(_cachedPen(_cardBorder, 1.0))
        for entries in self.__noduleDraw.values():
            for plug, key, position, radius, color in entries:
                if key == hoveredKey:
                    hovered = plug
                    continue
                painter.setBrush(color)
                painter.drawEllipse(position, radius, radius)

        if hovered is not None:
            self.__paintHoveredNodule(painter, hovered)

    ## 侧边圆点旁边的参数名（材质节点那种）。
    #
    # **三段式**：够大就写字；小到读不清了退化成一小截**色块**（颜色还是插口类型色，
    # 所以"这排接口分别是什么类型"仍然看得出来）；再小就彻底不画。
    def __paintSideLabels(self, painter, lod):

        if not self.__sideLabels or lod < SIDE_LABEL_BLOCK_LOD:
            return

        asText = lod >= SIDE_LABEL_MIN_LOD

        for section in ("left", "right"):
            for plug, key, position, _, _ in self.__noduleDraw.get(section, ()):
                label = self.__sideLabels.get(key)
                if label is None:
                    continue
                if key == self.__hoveredNodule and not self.__sectionData:
                    # 标签画在卡片**外面**时，悬停那个放大标签正好压在同一处 ——
                    # 只有这种情况才让位。分栏材质节点的标签在卡片**里面**，放大
                    # 标签弹到卡外，两者不打架，**必须照画**（鼠标移上去节点上的
                    # 文字不能消失）。
                    continue
                self.__paintSideLabel(
                    painter, section, plug, key, label, asText, position
                )

    ## 顶 / 底接口的名字（原生那套平时不画的 nodule label）。
    #
    # 原生把这些标签**斜着 45°** 画（`StandardNodule::renderLabel` 按连线切线转角度，
    # 太竖了就掰回 45°）。我们改成水平画在圆点外侧、以圆点为中心 —— 一样是"哪个圆点
    # 叫什么"，但不用歪着头读。
    def __paintEndLabels(self, painter, lod):

        if not self.endLabelsVisible() or lod < SIDE_LABEL_MIN_LOD:
            return

        painter.save()
        for key in self.endLabelPaintKeys():
            section, plug, text, width, connected = self.__endLabels[key]

            point = self.nodulePosition(plug)
            gap = NODULE_RADIUS + SIDE_LABEL_GAP
            top = point.y() - gap - 14.0 if section == "top" else point.y() + gap
            rect = QtCore.QRectF(point.x() - width / 2.0 - 4.0, top, width + 8.0, 14.0)

            # 垫一层半透明底，压在连线上也读得清
            painter.setPen(QtCore.Qt.NoPen)
            backing = QtGui.QColor(_backgroundColor)
            backing.setAlpha(200)
            painter.setBrush(backing)
            painter.drawRoundedRect(rect, 3, 3)

            painter.setFont(_font(SIDE_LABEL_SIZE, bold=connected))
            painter.setPen(QtGui.QColor(_textColor if connected else _dimTextColor))
            painter.drawText(rect, QtCore.Qt.AlignCenter, text)

        painter.restore()

    def __paintSideLabel(self, painter, section, plug, key, label, asText, point=None):

        text, width, connected = label

        # 分栏节点的标签画在卡片里，超过 `SECTION_LABEL_MAX` 就画省略号
        # （否则一条超长参数名把整卡撑到两倍宽）。
        # 完整名字仍在**悬停**那个放大标签里，信息没丢。
        if self.__sectionData and width > SECTION_LABEL_MAX:
            elided = self.__elidedLabelCache.get((key, connected))
            if elided is None:
                elided = QtGui.QFontMetricsF(
                    _font(SIDE_LABEL_SIZE, bold=connected)
                ).elidedText(text, QtCore.Qt.ElideRight, SECTION_LABEL_MAX)
                self.__elidedLabelCache[(key, connected)] = elided
            text = elided
            width = SECTION_LABEL_MAX

        if point is None:
            point = self.nodulePosition(plug)
        color = self.__sideLabelColor(key, connected)

        if not asText:
            # 色块：长短跟着名字走，一眼还能看出"这几个接口不一样"
            blockWidth = max(6.0, min(22.0, width * 0.35))
            x = self.__sideLabelX(section, point, blockWidth)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QtCore.QRectF(x, point.y() - 1.8, blockWidth, 3.6), 1.8, 1.8
            )
            return

        # 分栏材质节点：文字画在卡片**里面**、贴着圆点那一侧；不分栏的画在卡片外面。
        inside = bool(self.__sectionData)
        x = self.__sideLabelX(section, point, width)
        align = (
            (QtCore.Qt.AlignLeft if section == "left" else QtCore.Qt.AlignRight)
            if inside
            else (QtCore.Qt.AlignRight if section == "left" else QtCore.Qt.AlignLeft)
        )

        painter.setFont(_font(SIDE_LABEL_SIZE, bold=connected))
        painter.setPen(color)
        painter.drawText(
            QtCore.QRectF(x, point.y() - 7.0, width, 14.0),
            QtCore.Qt.AlignVCenter | align,
            text,
        )

    ## 一条侧标（文字或色块）的左边缘：分栏节点画在卡片里，其余画在卡片外。
    def __sideLabelX(self, section, point, width):

        gap = NODULE_RADIUS + SIDE_LABEL_GAP
        if self.__sectionData:
            return point.x() + gap if section == "left" else point.x() - gap - width
        return point.x() - gap - width if section == "left" else point.x() + gap

    ## **接了线的那几个保持高亮**，没接的压暗一档 —— 材质节点一排参数里
    # 「哪些真的接了东西」一眼就分得出来。
    def __sideLabelColor(self, key, connected):

        cacheKey = (key, connected, self._active)
        color = self.__sideLabelColorCache.get(cacheKey)
        if color is None:
            color = self.__computeSideLabelColor(key, connected)
            self.__sideLabelColorCache[cacheKey] = color
        return color

    def __computeSideLabelColor(self, key, connected):

        color = self.__noduleColors.get(key, QtGui.QColor(_textColor))
        if connected:
            color = _emphasisColor(color)
        elif self.__sectionData:
            # 卡内标签：文字画在卡片**里面**、底是节点自己的色 —— 再混向深背景
            # 就糊成一团看不清。所以混向白色，保留插口类型色相又提亮，
            # 和卡片色拉开。「接没接」仍靠粗体 + `_emphasisColor` 分。
            color = QtGui.QColor(mixColors(color.name(), _textColor, 0.30))
        else:
            # 卡外标签：画在深色背景上，未接线的低调一档照旧。
            color = QtGui.QColor(mixColors(color.name(), _backgroundColor, 0.45))

        if not self._active:
            color = _disabledColor(color)

        return color

    def __paintSectionHeaders(self, painter, lod):

        # --- 分栏 header（Houdini 式：按 `layout:section` 分组，可收放）---
        #
        # 和参数同一个对齐方向（左 = 右对齐贴卡边、右 = 左对齐贴卡边），
        # 最外面带个折叠箭头：收起 ► / 展开 ▼。颜色比普通参数稍亮一档，
        # 一眼分出"这是组名、那才是参数"。
        if self.__sectionHeaders and lod >= SIDE_LABEL_MIN_LOD:

            for side in ("left", "right"):
                for name, y in self.__sectionHeaders.get(side, []):

                    collapsed = self.__sectionCollapsedCache.get((side, name))
                    if collapsed is None:
                        collapsed = sectionCollapsed(self.node, side, name)
                    color = _sectionHeaderColor()
                    if not self._active:
                        color = _disabledColor(color)

                    rect = self.cardRect()
                    painter.setFont(_font(SIDE_LABEL_SIZE, bold=True))
                    painter.setPen(color)

                    # 折叠箭头（收起 = ►、展开 = ▼）画在**卡片边上** —— 名字都进卡里了，
                    # 箭头留在外侧当"这行可点"的记号。收起时箭头指向卡内（左栏 ►、右栏 ◄）。
                    s = 4.0
                    cx = rect.left() if side == "left" else rect.right()
                    cy = y
                    if collapsed:
                        pts = [
                            QtCore.QPointF(
                                cx + s * 0.7 if side == "left" else cx - s * 0.7, cy
                            ),
                            QtCore.QPointF(cx, cy - s),
                            QtCore.QPointF(cx, cy + s),
                        ]
                    else:
                        pts = [
                            QtCore.QPointF(cx, cy - s * 0.7),
                            QtCore.QPointF(cx - s, cy),
                            QtCore.QPointF(cx + s, cy),
                        ]
                    painter.setBrush(color)
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.drawPolygon(QtGui.QPolygonF(pts))

                    # 名字画在卡片**里面**（对着圆点那一侧起笔，贴卡边）
                    textRect = QtCore.QRectF(
                        rect.left() + NODULE_RADIUS + SIDE_LABEL_GAP,
                        y - 7.0,
                        rect.width() - (NODULE_RADIUS + SIDE_LABEL_GAP) * 2.0,
                        14.0,
                    )
                    painter.setPen(color)
                    painter.drawText(
                        textRect,
                        QtCore.Qt.AlignVCenter
                        | (
                            QtCore.Qt.AlignLeft
                            if side == "left"
                            else QtCore.Qt.AlignRight
                        ),
                        name,
                    )

    def __paintAdders(self, painter):

        # --- 「加插口」的 `+`（Box / Switch / Loop … 都有）---
        for section, position in self.__adderPositions.items():

            active = section == self.__hoveredAdder
            # 细了看不清 —— 加粗，并且平时也用亮一点的颜色
            pen = QtGui.QPen(
                QtGui.QColor(_highlightColor if active else _textColor),
                3.2 if active else 2.4,
            )
            pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)

            arm = ADDER_SIZE * (0.42 if not active else 0.5)
            painter.drawLine(
                QtCore.QPointF(position.x() - arm, position.y()),
                QtCore.QPointF(position.x() + arm, position.y()),
            )
            painter.drawLine(
                QtCore.QPointF(position.x(), position.y() - arm),
                QtCore.QPointF(position.x(), position.y() + arm),
            )

    def __paintTitle(self, painter, rect):

        # --- 类型图标 + 名字 ---
        #
        # 卡片宽度是照原生 NodeGadget 来的，而原生那点宽度是按**它自己的字体**、
        # 且没有图标算出来的。所以图标是「有地方才画」：名字放不下就先不画图标，
        # 名字优先 —— 宁可少个图标，也不要把节点名截掉。
        font = _font(NODE_FONT_SIZE)
        nameWidth = self.__nameWidth

        available = rect.adjusted(
            NODE_TEXT_MARGIN, ACCENT_HEIGHT, -NODE_TEXT_MARGIN, 0.0
        )
        gap = GLYPH_GAP

        # 卡片宽度已经按「图标 + 名字」撑开了（`__contentsWidth`），所以图标照画不误，
        # 名字**整条画出来，不做任何省略号处理** —— 节点名被截掉比节点大小和原生
        # 差几像素严重得多。
        drawGlyph = self._glyph is not None

        if self.__sectionData:
            # **分栏材质节点：名字和图标都画在加宽的色带里、左对齐，图标在名字左边**
            # —— 不做"图标+名字整组居中"，标题条就照标题条的样子来。
            #
            # 文字颜色按色带亮度挑（色带是类型色，灯光那种暖黄上白字看不清）。
            centreY = rect.top() + SECTION_TITLE_HEIGHT / 2.0
            left = rect.left() + NODE_TEXT_MARGIN
            titleColor = _contrastTextColor(
                self._accent if self._active else self.__dimAccent
            )
            if self._enabled is False or not self._active:
                titleColor = QtGui.QColor(
                    mixColors(titleColor.name(), _dimTextColor, 0.45)
                )
            nameRect = QtCore.QRectF(
                left, rect.top(), rect.width() - NODE_TEXT_MARGIN, SECTION_TITLE_HEIGHT
            )
        else:
            # 图标和名字当成**一组**居中 —— 图标钉左边、名字在剩下的空间里再居中，
            # 两者之间会空出一大块，看着散。
            groupWidth = nameWidth + (GLYPH_SIZE + gap if drawGlyph else 0.0)
            left = rect.center().x() - groupWidth / 2.0
            centreY = rect.center().y() + ACCENT_HEIGHT / 2.0
            titleColor = QtGui.QColor(
                _textColor
                if (self._enabled is not False and self._active)
                else _dimTextColor
            )
            nameRect = None

        if drawGlyph:
            _drawGlyph(
                painter,
                self._glyph,
                QtCore.QPointF(left + GLYPH_SIZE / 2.0, centreY),
                GLYPH_SIZE,
                titleColor,
            )
            left += GLYPH_SIZE + gap

        painter.setFont(font)
        painter.setPen(titleColor)
        if nameRect is None:
            nameRect = QtCore.QRectF(
                left, available.top(), nameWidth + 2.0, available.height()
            )
        else:
            # 图标占掉的那一截要让出来（图标在名字左边）
            nameRect = QtCore.QRectF(
                left,
                nameRect.top(),
                max(1.0, rect.right() - NODE_TEXT_MARGIN - left),
                nameRect.height(),
            )
        painter.drawText(
            nameRect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.nodeName
        )

    def __paintStrikeThrough(self, painter, rect):

        # 停用 = 对角线划掉，照原生 `StandardNodeGadget::renderLayer` 的 Highlighting
        # 层（Gaffer 的 y 朝上，`min→max` 就是左下角拉到右上角那条 `/`）。颜色也照抄：
        # 静态停用 0.1 灰（不参与计算 0.2 灰），动态关着画黄色。
        # 比原生多一态：`enabled` 要算但 ContextTracker 没跟踪它 —— 原生什么都不画
        # （不敢跑 compute），我们画**虚**线提示"说不准"。
        strike = self.strikeThroughState()
        if strike is not None:

            if strike == "dynamic":
                color = QtGui.QColor(STRIKE_DYNAMIC)
            else:
                color = QtGui.QColor(
                    STRIKE_STATIC if self._active else STRIKE_STATIC_DIM
                )

            pen = QtGui.QPen(color, STRIKE_WIDTH)
            pen.setCapStyle(QtCore.Qt.FlatCap)
            if strike == "unknown":
                pen.setWidthF(STRIKE_WIDTH * 0.5)
                pen.setStyle(QtCore.Qt.DotLine)
            painter.setPen(pen)
            painter.drawLine(
                QtCore.QPointF(rect.left(), rect.bottom()),
                QtCore.QPointF(rect.right(), rect.top()),
            )

    def __paintDetails(self, painter, rect):

        # --- 角标 ---
        # 角标一律靠左排 —— 右上角让给 focus 折角
        badgeX = rect.left() + 3
        if self._error:
            self.__badge(
                painter, badgeX, rect.top() + ACCENT_HEIGHT + 3, "!", _errorColor
            )
            badgeX += 15

        # --- 可进入的容器：右下角小三角 ---
        if self._canEnter:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(255, 255, 255, 70))
            x, y = rect.right() - 5, rect.bottom() - 5
            painter.drawPolygon(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(x - 6, y),
                        QtCore.QPointF(x, y),
                        QtCore.QPointF(x, y - 6),
                    ]
                )
            )

        # --- 注释 ---
        #
        # **画在节点右边、顶端对齐**，和原生一致：`AnnotationsGadget.cpp` 里
        # `annotationOrigin = V2f( b.max.x + 0.5, b.max.y )`（右上角往外挪半个单位）。
        # 画在卡片正下方的话会和下游连线打架。
        if self._annotations:
            annotationFont = _font(ANNOTATION_SIZE)
            metrics = QtGui.QFontMetrics(annotationFont)
            painter.setFont(annotationFont)
            y = rect.top() - 1.0
            # 一个节点可以挂好几条注释（`user` + 项目自己注册的模板），原生是一条条
            # 竖着排下来的 —— 照做，每条只写第一行（多行的完整内容在悬停小框里）。
            for unusedName, text, color in self._annotations:
                line = text.split("\n")[0]
                painter.setPen(QtGui.QColor(color))
                painter.drawText(
                    QtCore.QRectF(
                        rect.right() + ANNOTATION_GAP,
                        y,
                        metrics.horizontalAdvance(line) + 2.0,
                        14,
                    ),
                    QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                    line,
                )
                y += ANNOTATION_LINE_HEIGHT

    ## 折角 tab：focus 中画实心亮金，没 focus 时只在悬停节点/悬停折角时画折痕提示。
    def __paintFocusTab(self, painter, cardPath, lod=None):

        # **镜头拉远时改画"卡片外面的小旗"**：角标缩小之后只剩几个像素，
        # 拉远了就画一面固定屏幕尺寸的小旗，形状说话、不靠颜色区分。
        if self._focused and lod is not None and 1e-6 < lod < FOCUS_FLAG_LOD:
            self.__paintFocusFlag(painter, lod)
            return

        polygon = self.focusTabPolygon(lod)

        painter.save()
        # **画在卡片外面，一律不裁剪**

        if self._focused:

            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(_focusRing))
            painter.drawPolygon(polygon)

            # 外面是深背景，描一圈深色边，边界才干净
            painter.setPen(QtGui.QPen(QtGui.QColor(_cardBorder), 1.0))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPolygon(polygon)

        else:

            # **鼠标滑过时的提示要看得见**：角标画在卡片外面、底下是深背景
            # （`#242424`），alpha 22/110 那种几乎看不见。实心度 0.3 / 描边 0.85，
            # 光标真的压在角标上再加重到 0.55 / 1.0。
            hovered = self.__focusFlagHovered

            fill = QtGui.QColor(_focusRing)
            fill.setAlpha(140 if hovered else 78)

            hint = QtGui.QColor(_focusRing)
            hint.setAlpha(255 if hovered else 215)

            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPolygon(polygon)

            painter.setPen(QtGui.QPen(hint, 1.4))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPolygon(polygon)

        painter.restore()

    ## 拉远之后的 focus 标记：卡片右上角**外侧**一面小旗，尺寸按 1/lod 补偿，
    # 所以屏幕上永远是那么大一块，怎么缩都看得见。
    def __paintFocusFlag(self, painter, lod):

        rect = self.cardRect()
        # 和 `focusTabSize` 一样夹住补偿 —— 包围盒盖不住就会留拖影
        size = FOCUS_FLAG_PIXELS / max(lod, FOCUS_LOD_FLOOR)

        x = rect.right()
        y = rect.top()

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(_cardBorder), max(1.0, size * 0.12)))
        painter.setBrush(QtGui.QColor(_focusRing))
        painter.drawPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y),
                    QtCore.QPointF(x + size, y - size * 0.55),
                    QtCore.QPointF(x + size, y + size * 0.55),
                ]
            )
        )
        painter.restore()

    ## 被悬停的接口：半径翻倍 + 换成 HighlightColor（原生 `renderNodule( 1.0,
    # HighlightedState )`），再把插口名写在圆点外侧 —— 原生是靠 `setLabelVisible`
    # 在拖连线时才显示标签，这里直接跟着悬停走，省得材质节点上一堆圆点认不出来。
    def __paintHoveredNodule(self, painter, plug):

        point = self.nodulePosition(plug)
        tangent = self.noduleTangent(plug)

        # 原生是「半径翻倍 + HighlightColor」（`renderNodule( 1.0, HighlightedState )`），
        # 小一号的圆点（展开的 Color3f 子接口）也照它自己那档翻倍。
        hoverRadius = NODULE_HOVER_RADIUS * self.noduleRadius(plug) / NODULE_RADIUS

        painter.setPen(_cachedPen(_cardBorder, 1.0))
        painter.setBrush(QtGui.QColor(_highlightColor))
        painter.drawEllipse(point, hoverRadius, hoverRadius)

        font = _font(_HOVER_LABEL_FONT_SIZE)
        metrics = QtGui.QFontMetrics(font)
        text = noduleLabel(plug)
        width = metrics.horizontalAdvance(text) + 10.0
        height = metrics.height() + 4.0

        # 沿着接口的出射方向把标签推到节点外面
        anchorX = point.x() + tangent.x() * (hoverRadius + 4.0)
        anchorY = point.y() + tangent.y() * (hoverRadius + 4.0)

        if abs(tangent.x()) > abs(tangent.y()):
            box = QtCore.QRectF(
                anchorX if tangent.x() > 0 else anchorX - width,
                anchorY - height / 2.0,
                width,
                height,
            )
        else:
            box = QtCore.QRectF(
                anchorX - width / 2.0,
                anchorY if tangent.y() > 0 else anchorY - height,
                width,
                height,
            )

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(20, 22, 26, 232))
        painter.drawRoundedRect(box, 3, 3)

        painter.setFont(font)
        painter.setPen(QtGui.QColor(_textColor))
        painter.drawText(box, QtCore.Qt.AlignCenter, text)

    ## 名字在卡片里放得下吗（测试用：确认没被省略号截掉）。
    def nameFits(self):

        if self._shape in (SHAPE_DOT, SHAPE_AUXILIARY):
            return True

        metrics = QtGui.QFontMetrics(_font(NODE_FONT_SIZE))
        needed = metrics.horizontalAdvance(self.nodeName) + NODE_TEXT_MARGIN * 2.0
        if self._glyph is not None:
            needed += GLYPH_SIZE + GLYPH_GAP

        return needed <= self._width + 1e-6

    ## 左上角的书签标记（形状照原生：收藏 = 书签旗，只有数字 = 星星；数字写在左边）。
    def __paintBookmark(self, painter, rect, lod=None):

        scale = 1.0
        if lod is not None and 1e-6 < lod < 1.0:
            # 拉远了也得看得见（和折角一个道理）；上限要和 `boundingRect` 的余量对得上
            scale = min(BOOKMARK_MAX_SCALE, 1.0 / lod)

        x = rect.left() - 2.0 * scale
        y = rect.top() - 1.0 * scale
        color = QtGui.QColor(_bookmarkColor)
        if not self._active:
            color = _disabledColor(color)

        painter.setPen(QtGui.QPen(QtGui.QColor(_cardBorder), 1.0))
        painter.setBrush(color)

        if self._bookmarked:
            # 书签旗：一个下缘开口的小旗子
            painter.drawPolygon(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(x - 5 * scale, y - 6 * scale),
                        QtCore.QPointF(x + 5 * scale, y - 6 * scale),
                        QtCore.QPointF(x + 5 * scale, y + 7 * scale),
                        QtCore.QPointF(x, y + 2.5 * scale),
                        QtCore.QPointF(x - 5 * scale, y + 7 * scale),
                    ]
                )
            )
        else:
            # 只有数字书签：五角星
            star = QtGui.QPolygonF()
            for i in range(10):
                angle = math.pi / 2.0 + i * math.pi / 5.0
                radius = (6.5 if i % 2 == 0 else 2.9) * scale
                star.append(
                    QtCore.QPointF(
                        x + radius * math.cos(angle), y - radius * math.sin(angle)
                    )
                )
            painter.drawPolygon(star)

        if self._bookmark:
            painter.setFont(_font(8.0 * scale, bold=True))
            painter.setPen(color)
            painter.drawText(
                QtCore.QRectF(x - 26 * scale, y - 8 * scale, 18 * scale, 16 * scale),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                str(self._bookmark),
            )

    def __badge(self, painter, x, y, text, color):

        box = QtCore.QRectF(x, y, 12, 12)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(color))
        painter.drawEllipse(box)
        painter.setPen(QtGui.QColor("#14161a"))
        painter.setFont(_font(7.0, bold=True))
        painter.drawText(box, QtCore.Qt.AlignCenter, text)


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
