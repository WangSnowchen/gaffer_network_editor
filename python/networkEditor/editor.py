"""`NetworkEditor` 本体：GafferUI Editor 外壳 + 和原生共用数据 + 增量更新 +
借原生右键菜单 / 快捷键转发 / 拖放 / 建节点 / 编辑操作。
"""

import os
import math
import weakref
import collections
import functools
import importlib.util

import imath

import IECore
import Gaffer
import GafferUI
import GafferScene

from Qt import QtCore, QtGui, QtWidgets

from .panel import *

# GafferUI Editor


## 一个上下文菜单信号要发给谁：类级那份 + 宿主实例上那份。
#
# `GraphEditor` 的这三个访问器是 `classOrSelf` 混合式，类上取类那份、实例上取实例那份，
# 弹菜单时**两份都发**（`GraphEditor.py:470-490`）。按对象身份去重是防御性的：
# 拿不到实例那份（`None`）或两者恰好是同一个对象时只发一次。
def _contextMenuSignals(classSignal, instanceSignal):

    signals = [classSignal]
    if instanceSignal is not None and instanceSignal is not classSignal:
        signals.append(instanceSignal)
    return signals


## 冒充原生 `GadgetWidget` 的那层壳（`graphGadgetWidget()` 返回它）。
#
# 原生命令只摸它三样（照 Gaffer 1.7.1.0 源码数的）：
#
# * `getViewportGadget()` —— 问「这个像素是图里哪个点」（`NodeMenu.py:134`、
#   `DotUI.py:150`、`BackdropUI.py:69`）；
# * `bound()` —— `menu.popupPosition( relativeTo = gadgetWidget )` 里那句
#   `result - relativeTo.bound().min()`（`Menu.py:149`）；
# * `size()` —— `GraphEditor.py:737` 那种"没连线就摆视口正中"的算法。
#
# **故意不做成 `GafferUI.Widget`**：`Widget.__init__` 会把被包的 QWidget 登记进全局
# owner 表（还 assert 不能重复包）、并给直接 `QWidget` 实例设 `WA_StyledBackground` ——
# 拿我们真正的 `QGraphicsView` viewport 去冒这个风险没必要，鸭子类型就够。
class _GadgetWidgetShim(object):

    def __init__(self, editor):

        self.__editor = weakref.ref(editor)

    ## 取景已经同步成"我们视图现在看到的那块"的 ViewportGadget（见 `_syncedViewport`）。
    def getViewportGadget(self):

        editor = self.__editor()
        return editor._syncedViewport() if editor is not None else None

    ## 屏幕上的矩形（全局坐标）= **整个编辑器**那块，和 `graphEditor.bound()` 一样。
    # 原生 GraphEditor 没有工具条，编辑器和 GadgetWidget 是同一块；`EditMenu` 粘贴 /
    # `FileMenu` 导入拿 `graphEditor.bound()` 算 raster、再用这里的 ViewportGadget
    # 换算，两者必须是同一块，否则粘贴的节点差一个工具条的高度（`_syncedViewport`
    # 取景也按这一块来）。
    def bound(self):

        editor = self.__editor()
        return editor.bound() if editor is not None else imath.Box2i()

    def size(self):

        editor = self.__editor()
        return editor.size() if editor is not None else imath.V2i(0)

    ## 底层 QWidget：和 `bound()` 同一块（编辑器自己）。
    def _qtWidget(self):

        editor = self.__editor()
        return editor._qtWidget() if editor is not None else None


## 接管装上了没有（装上之后 `isinstance( ourEditor, GafferUI.GraphEditor )` 就是 True）。
def graphEditorTakeoverInstalled():

    return _nativeGraphEditor is not None


## 要不要建那个隐藏的原生 GraphEditor 当"引擎"。
#
# **默认不建** —— 接管装上之后我们自己就算一个 GraphEditor：
#
# * 原生菜单命令要的 `menu.ancestor( GafferUI.GraphEditor )` → `__menuHost()` 给的是我们；
# * 它们要的 `graphGadgetWidget()` → `_GadgetWidgetShim` + 取景同步的 ViewportGadget；
# * 项目注册在 `GraphEditor.instanceCreatedSignal` 上的快捷键 → `__announceInstance()`
#   把自己宣布出去，handler 直接连我们的 `keyPressSignal`。
#
# 所以引擎只在**接管没装**（`GAFFER_NETWORK_EDITOR_TAKEOVER=native`）时才需要 ——
# 那时 `isinstance` 不成立，只能借一个真的 GraphEditor 当宿主。
#
# 两个显式开关：`GAFFER_NETWORK_EDITOR_ENGINE=1` 强制建（想对比行为时用）、`=0` 强制不建
# （哪怕接管没装，代价是三套原生菜单和 pipeline 快捷键都没了）。
def engineEnabled():

    value = os.environ.get("GAFFER_NETWORK_EDITOR_ENGINE", "")
    if value == "0":
        return False
    if value == "1":
        return True

    return not graphEditorTakeoverInstalled()


## 要不要用原生 GraphGadget 问几何（默认要）。
#
# `GAFFER_NETWORK_EDITOR_GADGET=0` 关掉之后节点尺寸 / 接口位置 / `+` 全部走公式回退，
# 和原生视图会有像素级差异 —— 只在"完全不想碰原生 UI"时才关。
def gadgetEnabled():

    return os.environ.get("GAFFER_NETWORK_EDITOR_GADGET", "1") != "0"


class NetworkEditor(GafferUI.Editor):

    def __init__(self, scriptNode, **kw):

        # 裸 QWidget 会被 Gaffer 的 stylesheet 设上 WA_StyledBackground，必须自己包一层。
        root = QtWidgets.QWidget()
        root.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        root.setStyleSheet("background-color: %s;" % _backgroundColor)

        GafferUI.Editor.__init__(self, GafferUI.Widget(root), scriptNode, **kw)

        self.__initState(scriptNode)
        self.__buildWidgets(root)
        self.__connectScript(scriptNode)

        # 接管装着的话，现在就把自己当成一个 GraphEditor 宣布出去 —— 项目那些注册在
        # `GraphEditor.instanceCreatedSignal` 上的快捷键于是直接连到我们身上。
        # （接管晚装的情形：第一次转发键时 `__announceInstance()` 会补上。）
        self.__announceInstance()

        self.__rebuild()

    ## 全部实例状态在这里一次列清楚（哪个是增量更新的脏标记、哪个是懒建的原生组件）。
    def __initState(self, scriptNode):

        self.__root = scriptNode
        self.__rootHistory = collections.deque([], 20)
        self.__navigatingRootHistory = False
        # 每一层看到哪儿（缩放 + 位置）各记一份：( 节点, scene 矩形 )
        self.__viewStates = collections.deque([], 20)
        self.__wireStyle = WIRE_CURVED
        self.__statusHint = None  # 状态栏上进行中的模式提示（`_setStatusHint`）
        self.__nodeItems = {}  # 节点名 -> _NodeItem
        self.__backdropItems = {}
        self.__edgeItems = []
        self.__edgesByNode = {}  # 节点名 -> [ _EdgeItem ]
        self.__errorNodes = set()

        # 下面几个是**增量**的（见 `__applyGraphChanges`）：全量重建在 800 个节点的图上
        # 要 245ms，每连一根线卡这么久没法用。真正贵的是逐个建 `_NodeItem`（占 63%），
        # 没变的节点根本不用重建。
        self.__structureDirty = False  # 节点增删改名 → 节点集合要 diff
        self.__dirtyItems = set()  # 这些节点的 item 要重建（元数据 / enabled 变了）
        self.__dirtyEdges = set()  # 这些节点**作为目的地**的边要重收（输入变了）
        self.__dirtyPositions = (
            set()
        )  # `__uiPosition` 变了的节点名（只挪它们和它们的边）
        self.__selectionDirty = False
        self.__idleScheduled = False
        self.__updatePostponed = False  # 拖动期间推迟下来的重建
        self.__updatingSelection = False
        self.__selectionSyncSuspended = False

        self.__hoveredNoduleItem = None  # 鼠标停着的那个接口所在的节点名
        self.__hoveredAdderItem = None  # 鼠标停着的那个 `+` 所在的节点名
        self.__hoveredSectionItem = None  # 鼠标停着的那个分栏三角所在的节点名
        self.__hoveredBackdrop = None  # 鼠标停着的那个 Backdrop 的节点名
        self.__dropTargetItem = None  # 拖连线时鼠标落在的那个节点名
        # 注意别拿 `__dragPointer is not None` 当「拖拽进行中」的标志 ——
        # `Pointer.getCurrent()` 平时就是 None（标准指针），那样整套拖放会直接哑掉
        self.__dragActive = False  # 正在接一次从别的编辑器来的拖拽
        self.__dragPointer = None  # 拖进来之前的鼠标指针（结束时还原）
        self.__dragTargetNode = None  # 拖进来的东西现在落在哪个节点上
        self.__dragOutNodes = None  # 中键从本编辑器往外拖的那些节点
        self.__snapEnabled = True  # 拖动时自动对齐（默认开，工具条 Snap 开关）
        # 画哪些注释（工具条 Annotations 菜单，原生是 GraphEditor 右上角那个图标菜单）
        self.__visibleAnnotations = DEFAULT_VISIBLE_ANNOTATIONS
        self.__snapGuides = []  # 现在亮着的对齐参考线
        self.__nodeConnections = {}  # 节点名 -> [ 该节点的信号连接 ]
        self.__rootConnections = []  # root 的 childAdded / childRemoved
        self.__tracker = None  # 原生 ContextTracker（focus 之后谁参与计算）
        # 拖着一个节点压在某根线上时记的「松手就塞进去」候选：( edgeItem, in, out )
        self.__insertCandidate = None
        self.__trackerConnection = None
        # 懒建的裸 GraphGadget（几何 / 布局 / 对外的 `graphGadget()`）
        self.__gadgetForGeometry = None
        self.__gadgetRootChangedConnection = None
        # layout 里有没有原生 GraphEditor 可借，每层只查一次（`__graphGadget` 在
        # 拖放 / 插入候选那些每帧都走的路上，每次都去 layout 树里翻一遍太贵）
        self.__existingEditorChecked = False
        self.__engineEditor = None  # 懒建的隐藏 GraphEditor（原生菜单要它当 ancestor）
        self.__borrowedEngine = False  # engine 是从 layout 里借来的（不能改它的 root）
        self.__creatorPopup = None  # 我们自己那个面板（Tab / B / 内部快捷键都用它）
        self.__pendingCreate = None
        # 弹出的菜单必须留个引用，否则局部变量出作用域就被 GC 掉、菜单一闪而过
        self.__contextMenu = None
        # Houdini 那种「P 键弹出来的纯参数面板」（懒建，见 `_popupParameters`）
        self.__parameterPopup = None
        # 「只算不画」的取景器 + 冒充 GadgetWidget 的壳（懒建，见 `_syncedViewport`）
        self.__viewportGadget = None
        self.__gadgetWidgetShim = None
        # 有没有把自己当成一个 GraphEditor "宣布"出去过（见 `__announceInstance`）
        self.__announced = False

        # 实例级的右键菜单信号（照 `GraphEditor.__init__` 建的那四个）。原生扩展点
        # 往**实例**上连（`_PlugVisibilityGadget.connectToEditor` 就是），而接管装着时
        # `isinstance( 我们, GraphEditor )` 为真、这些 connectToEditor 会落到我们身上。
        self.__plugContextMenuSignal = Gaffer.Signals.Signal3()
        self.__connectionContextMenuSignal = Gaffer.Signals.Signal3()
        self.__nodeContextMenuSignal = Gaffer.Signals.Signal3()
        self.__multiNodeContextMenuSignal = Gaffer.Signals.Signal3()

    ## 工具条 + QGraphicsScene + 我们自己的 QGraphicsView。
    def __buildWidgets(self, root):

        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.__buildToolBar())

        self.__scene = QtWidgets.QGraphicsScene(root)
        self.__scene.setItemIndexMethod(QtWidgets.QGraphicsScene.BspTreeIndex)
        self.__scene.setBspTreeDepth(BSP_TREE_DEPTH)  # 见 constants.py 那段
        self.__scene.selectionChanged.connect(self.__sceneSelectionChanged)

        self.__view = _GraphView(self)
        self.__view.setScene(self.__scene)
        layout.addWidget(self.__view, 1)

    ## script 上的信号 + GafferUI 那四条拖放信号（不接就一点反应都没有）。
    def __connectScript(self, scriptNode):

        self.__scriptConnections = [
            scriptNode.selection()
            .memberAddedSignal()
            .connect(Gaffer.WeakMethod(self.__selectionMemberChanged), scoped=True),
            scriptNode.selection()
            .memberRemovedSignal()
            .connect(Gaffer.WeakMethod(self.__selectionMemberChanged), scoped=True),
            scriptNode.focusChangedSignal().connect(
                Gaffer.WeakMethod(self.__focusChanged), scoped=True
            ),
            # 从别的编辑器（Viewer / HierarchyView / SetEditor / 文件浏览器）拖东西进来
            self.dragEnterSignal().connect(
                Gaffer.WeakMethod(self.__dragEnter), scoped=True
            ),
            self.dragMoveSignal().connect(
                Gaffer.WeakMethod(self.__dragMove), scoped=True
            ),
            self.dragLeaveSignal().connect(
                Gaffer.WeakMethod(self.__dragLeave), scoped=True
            ),
            self.dropSignal().connect(Gaffer.WeakMethod(self.__drop), scoped=True),
            # 往外拖（中键按住节点拖到别的编辑器里去）
            self.dragBeginSignal().connect(
                Gaffer.WeakMethod(self.__dragBegin), scoped=True
            ),
            self.dragEndSignal().connect(
                Gaffer.WeakMethod(self.__dragEnd), scoped=True
            ),
        ]

        # 上面那句 `dragBeginSignal()` 会让 GafferUI 把全局事件过滤器装到我们的**顶层**
        # QWidget 上，但鼠标事件都进了 `QGraphicsView` 这个子控件 —— 得自己再装一遍
        self.__installDragSourceFilter()

    ##########################################################################
    # 公开接口
    ##########################################################################

    ## 标签页 / 浮动窗口标题。照原生 `GraphEditor.getTitle`：进了 Box 就把层级
    # 接在后面（`Network Editor : lightRig / shaders`）。
    def getTitle(self):

        title = GafferUI.Editor.getTitle(self)
        if title:
            return title

        result = IECore.CamelCase.toSpaced(self.__class__.__name__)

        # 当前层刚被删掉、还没退回脚本根的那一下，它已经不在脚本里了
        root = self.__root
        script = self.scriptNode()
        if root is not None and script.isAncestorOf(root):
            result += " : " + root.relativeName(script).replace(".", " / ")

        return result

    def getRootNode(self):

        return self.__root

    def setRootNode(self, node):

        if node is None:
            node = self.scriptNode()
        if self.__root is not None and node.isSame(self.__root):
            return

        previousRoot = self.__root
        # 离开这一层之前先把视野记下来，回来时对回去（原生 GraphEditor 的历史条目
        # 里也存了 frame，一个道理）—— 否则进一趟 Box 再出来就成了「全部节点」。
        self.__rememberViewState(previousRoot)

        self.__root = node
        # 右键菜单还没收尾的「建了什么节点」检查是按上一层记的，换层就作废 ——
        # 不作废的话「Show Contents...」进 Box 之后会把 Box 里没连线的节点全搬到菜单
        # 弹出的位置去（而且不进撤销栈）
        self.__pendingCreate = None
        self.__existingEditorChecked = False
        # 自己建的 engine / 裸 gadget 跟着走；layout 里借来的那个是用户的，不能动它的 root
        if self.__engineEditor is not None and not self.__borrowedEngine:
            self.__engineEditor.graphGadget().setRoot(node)
        if self.__gadgetForGeometry is not None:
            self.__gadgetForGeometry.setRoot(node)

        # 根历史（`[` / `]` 用），和原生 `GraphEditor.__rootChanged` 一个规矩
        if self.__navigatingRootHistory:
            self.__navigatingRootHistory = False
        elif previousRoot is not None:
            if not (self.__rootHistory and self.__rootHistory[-1].isSame(previousRoot)):
                self.__rootHistory.append(previousRoot)

        self.__rebuild()
        # 这一层以前来过就回到当时看的地方，第一次来才取全景。
        if not self.__restoreViewState(node):
            self.__view.frameAll()

        # 标签页 / 浮动窗口的标题跟着层级走（原生 `__rootChanged` 里也发这个信号）
        self.titleChangedSignal()(self)

    # --- 和原生 GraphEditor 的兼容接口 ---
    #
    # 接管之后官方那些「拿到一个 GraphEditor 使唤它」的地方会落到我们身上，最典型的是
    # `EditMenu.scope()`（剪切 / 复制 / 粘贴 / 删除全靠 `graphGadget().getRoot()` 决定
    # 作用在哪一层），还有项目快捷键 J / `/` 那种 `graphGadget().setRoot( x )` 换层。
    # 一律给**我们自己那个**裸 GraphGadget —— 别人对它 `setRoot()` 我们的视图跟着换
    # （`__gadgetRootChanged`）。隐藏引擎只当菜单宿主，它的 gadget 不驱动我们的视图；
    # 借来的原生 GraphEditor 的更不能给：那会把用户另一个面板换走。

    def graphGadget(self):

        return self.__ownGraphGadget()

    ## 原生那边 `graphEditor.graphGadgetWidget()` 拿到的东西。
    #
    # **返回我们自己的壳**（`_GadgetWidgetShim`）——背后是**我们真正的视口**和一个
    # 取景同步过的 ViewportGadget，所以原生代码算出来的位置和用户看到的一致。
    # 壳建不出来（没有视图）才退回隐藏引擎那个真 GadgetWidget。
    def graphGadgetWidget(self):

        if self.__view is not None:
            if self.__gadgetWidgetShim is None:
                self.__gadgetWidgetShim = _GadgetWidgetShim(self)
            return self.__gadgetWidgetShim

        engine = self.__engine()
        return engine.graphGadgetWidget() if engine is not None else None

    ## 把这些节点框进画面。`extend = True` 时保留当前视野再并进去（原生同义）。
    def frame(self, nodes, extend=False):

        items = []
        for node in nodes:
            item = self.__nodeItems.get(node.getName()) or self.__backdropItems.get(
                node.getName()
            )
            # 只认这一层的那个节点（别层同名的不算）
            if item is not None and item.node.isSame(node):
                items.append(item)

        if not items:
            return

        # 卡片 / 框本身，不含悬停标签、角标那些余量（否则框多松取决于鼠标在哪）
        rect = QtCore.QRectF()
        for item in items:
            bounds = item.selectionRect()
            rect = bounds if rect.isNull() else rect.united(bounds)

        if extend:
            current = self.__view.viewedSceneRect()
            if current is not None and not current.isNull():
                rect = rect.united(current)

        self.__view.setViewedSceneRect(rect.adjusted(-60, -60, 60, 60))

    ## 实例级的右键菜单信号，签名照 `GraphEditor`（`GraphEditor.py:205/216/264`）。
    #
    # 原生那三个访问器是 `classOrSelf` 混合式（类上取类那份、实例上取实例那份）；
    # 我们不是它的子类，直接给实例那份就行 —— 类级那份原生自己有，弹菜单时两份都发
    # （见 `__nativeNodeMenu` 一带）。

    def plugContextMenuSignal(self):

        return self.__plugContextMenuSignal

    def connectionContextMenuSignal(self):

        return self.__connectionContextMenuSignal

    def nodeContextMenuSignal(self, multiNode=False):

        if multiNode:
            return self.__multiNodeContextMenuSignal
        return self.__nodeContextMenuSignal

    def getWireStyle(self):

        return self.__wireStyle

    def setWireStyle(self, style):

        if style == self.__wireStyle:
            return

        self.__wireStyle = style
        for item in self.__edgeItems:
            item.updateGeometry(style)

    def readOnly(self):

        return Gaffer.MetadataAlgo.getChildNodesAreReadOnly(
            self.__root
        ) or Gaffer.MetadataAlgo.readOnly(self.__root)

    ## 诊断钩子：原生命令 / 插件在我们身上问了一个**不存在**的属性时记一条日志，
    # 再照常抛 `AttributeError`。靠它发现"还缺哪个 GraphEditor API" ——
    # 日志级别调到 Debug 把常用菜单都点一遍，缺什么一目了然。
    def __getattr__(self, name):

        if not name.startswith("_"):
            IECore.msg(
                IECore.Msg.Level.Debug,
                "NetworkEditor",
                "Something asked for '%s', which this editor does not implement "
                "(GraphEditor API surface)." % name,
            )

        raise AttributeError(name)

    ## 这块面板现在是不是被**空格**「最大化」了。
    #
    # Gaffer 的空格**不是真全屏** —— `CompoundEditor.__keyPress`（`CompoundEditor.py:381`）
    # 做的是把光标所在面板的**所有祖先 SplitContainer 的手柄推到两端**
    # （`setSizes( [ 1 - childIndex, childIndex ] )`）。判据照抄它：每一层的手柄位置
    # 都恰好等于 `1 - 自己在父级里的序号`。
    #
    # 和原生那段有一处故意不同：**一个 split 祖先都没有时返回 False**（原生的
    # `all( [] )` 是 True）—— 浮动窗口 / 单面板布局里压根没有"最大化"这回事。
    # 真正的窗口全屏是另一回事，问 `isWindowFullScreen()`。
    def isPanelMaximised(self):

        positions = []

        widget = self
        while widget is not None:
            parent = widget.parent()
            if isinstance(parent, GafferUI.SplitContainer) and len(parent) == 2:
                sizes = parent.getSizes()
                total = float(sum(sizes)) or 1.0
                positions.append((parent.index(widget), sizes[0] / total))
            widget = parent

        if not positions:
            return False

        return all(abs(position - (1 - index)) < 1e-6 for index, position in positions)

    ## 装着这块面板的那个窗口是不是真全屏（F11 那种）。
    def isWindowFullScreen(self):

        window = self.ancestor(GafferUI.Window)
        return bool(window is not None and window.getFullScreen())

    def graphView(self):

        return self.__view

    def __repr__(self):

        return "GafferUI.NetworkEditor( scriptNode )"

    ##########################################################################
    # 隐藏的 GraphEditor —— 借原生的 GraphGadget / NodeMenu 实现
    ##########################################################################

    ## `NodeMenu.nodeCreatorWrapper` 里有 `assert graphEditor is not None`，
    # 而 `StandardGraphLayout.connectNode/positionNode` 需要真的 GraphGadget。
    # 优先复用 layout 里现成的 GraphEditor（零额外开销），否则懒建一个不显示的。
    ## layout 里有没有一个正看着同一层的原生 GraphEditor。有就借它的，零额外开销。
    def __existingGraphEditor(self):

        scriptWindow = GafferUI.ScriptWindow.acquire(
            self.scriptNode(), createIfNecessary=False
        )
        if scriptWindow is None:
            return None

        # **一定要找原生那个类**：接管之后 `GafferUI.GraphEditor` 的 isinstance
        # 把我们自己也算作 GraphEditor，借回来当引擎就没有 `graphGadget()` 了
        for editor in scriptWindow.getLayout().editors(type=_nativeGraphEditorClass()):
            if self.__root.isSame(editor.graphGadget().getRoot()):
                return editor

        return None

    ## 隐藏引擎（原生 GraphEditor）—— 只有需要「一个 GraphEditor 当宿主」的活才用它：
    # 原生右键菜单命令里的 `menu.ancestor( GafferUI.GraphEditor )`、原生 NodeMenu 的
    # 创建函数、以及项目把快捷键注册在 `GraphEditor.instanceCreatedSignal` 上的那些。
    #
    # `GAFFER_NETWORK_EDITOR_ENGINE=0` 可以整个关掉 —— **这既是"想彻底不碰原生窗口"
    # 时的开关，也是量"到底有多依赖它"的尺子**：关掉跑一遍测试，挂掉的就是靠它的那些。
    def __engine(self):

        if not engineEnabled():
            return None

        if self.__engineEditor is not None:
            if self.__root.isSame(self.__engineEditor.graphGadget().getRoot()):
                return self.__engineEditor
            if self.__borrowedEngine:
                # 借来的那个已经不在这一层了，别动它，自己另建
                self.__engineEditor = None
                self.__borrowedEngine = False
            else:
                self.__engineEditor.graphGadget().setRoot(self.__root)
                return self.__engineEditor

        editor = self.__existingGraphEditor()
        if editor is not None:
            self.__engineEditor = editor
            self.__borrowedEngine = True
            return editor

        editor = _nativeGraphEditorClass()(self.scriptNode())
        editor.graphGadget().setRoot(self.__root)
        # 这个引擎从不显示，视口是退化的 → 原生那些 `rasterToGadgetSpace()` 会
        # 算出 nan（新节点直接飞到画面外）。**把它的取景同步成我们视图看到的那块**，
        # 引擎那条路算出来的数就和用户看到的一致。
        self.__syncViewportGadget(editor.graphGadgetWidget().getViewportGadget())
        self.__engineEditor = editor
        self.__borrowedEngine = False
        return editor

    ## 原生菜单命令要的那个「GraphEditor 宿主」。
    #
    # **接管装上之后就是我们自己**：`Widget.ancestor( type )` 用的是 `isinstance`
    # （`Widget.py:415-423`），而接管那个元类的 `__instancecheck__` 让我们通过 —— 所以
    # `menu.ancestor( GafferUI.GraphEditor )` 认我们，隐藏引擎的主用途就没了。
    # 接管被关掉（`GAFFER_NETWORK_EDITOR_TAKEOVER=native`）时 isinstance 不成立，
    # 那就还得退回隐藏引擎。
    def __menuHost(self):

        if isinstance(self, GafferUI.GraphEditor):
            return self

        return self.__engine()

    ## 宿主身上那份**实例级**的菜单信号。
    #
    # 宿主是我们自己时给我们自己那四个（`plugContextMenuSignal` 一带），是隐藏引擎时
    # 给那个真 GraphEditor 实例上的 —— 原生扩展点连的就是实例这一份。
    @staticmethod
    def __hostSignal(host, name, *args):

        return getattr(host, name)(*args)

    ## 借来的那个菜单该「假装」在屏幕上的哪个位置。
    #
    # 宿主是**我们自己**时：就是那个图坐标在屏幕上的真实位置 —— 我们的壳报的 `bound()`
    # 是真视口、取景也同步过，原生那一路 `popupPosition( relativeTo = gadgetWidget )` →
    # `rasterToGadgetSpace()` 算回来正好落在它上面。
    # 宿主是隐藏引擎时：走反向算法（`__enginePopupPosition`）。
    def __hostPopupPosition(self, host, scenePosition):

        if host is not self:
            return self.__enginePopupPosition(host, scenePosition)

        viewPosition = self.__view.mapFromScene(scenePosition)
        globalPosition = self.__view.viewport().mapToGlobal(viewPosition)
        result = imath.V2f(globalPosition.x(), globalPosition.y())
        if positionUsable(result):
            return result

        position = QtGui.QCursor.pos()
        return imath.V2f(position.x(), position.y())

    ## 「只算不画」的取景器：一个独立 `ViewportGadget`，视口和取景**同步成我们这个
    # 视图现在看到的那块**，专门给原生代码回答「这个像素是图里哪个点」。
    #
    # 四条实测出来的性质（1.7.1.0 复核过，和 1.6 一致）：
    #
    # 1. `ViewportGadget` 默认就是 2D 相机（`getPlanarMovement() == True`），**默认视口
    #    `V2i(640,480)`** —— 不 `setViewport` 就按它算（隐藏引擎算出 `nan` 就是这条的
    #    极端情况）；
    # 2. `frame( box )` 是"把整个框装进视口"，宽高比不同就往长边扩 —— 我们喂的框来自
    #    `mapToScene( viewport.rect() )`，天生就是视口的宽高比，所以是精确的；
    # 3. **改视口尺寸不会自动重新取景**，所以每次用之前都同步一遍；
    # 4. raster 是 y 向下、gadget 是 y 向上，`rasterToGadgetSpace` 返回 `LineSegment3f`
    #    （取 `.p0`）。
    #
    # ⚠️ **它 host 的必须是我们自己那个裸 GraphGadget**：一个 gadget 只有一个父，挂给
    # 第二个 `ViewportGadget` 会把它从原来那个上**抢走**（实测原来那个的
    # `getPrimaryChild()` 变成 `None`）—— 要是抢了"借来的真 GraphEditor"的 gadget，
    # 用户那个原生视图就坏了。好消息：`rasterToGadgetSpace( gadget = X )` 对**不在这棵树里**
    # 的 X 也给同样的答案（顶层 gadget 的变换是单位矩阵，实测一致），所以不必和原生
    # 共用同一个 gadget 对象。
    def _syncedViewport(self):

        if self.__viewportGadget is None:
            self.__viewportGadget = GafferUI.ViewportGadget(self.__ownGraphGadget())

        self.__syncViewportGadget(self.__viewportGadget)
        return self.__viewportGadget

    ## 把一个 `ViewportGadget` 的视口 + 取景调成「我们视图现在看到的那块」。
    def __syncViewportGadget(self, viewportGadget):

        if viewportGadget is None or not self.__viewAlive():
            return

        # raster 是**整个编辑器**那块（含工具条，见 `_GadgetWidgetShim.bound`）：
        # 把编辑器左上角换算到视口坐标里，那块矩形映射到 scene 就是这次的取景
        root = self._qtWidget()
        width, height = root.width(), root.height()
        if width < 2 or height < 2:
            return

        qtViewport = self.__view.viewport()
        rasterRect = QtCore.QRect(
            qtViewport.mapFrom(root, QtCore.QPoint(0, 0)), root.size()
        )

        viewportGadget.setViewport(imath.V2i(width, height))

        visible = self.__view.mapToScene(rasterRect).boundingRect()
        if visible.width() < 1e-6 or visible.height() < 1e-6:
            return

        # scene 像素 → Gaffer 单位（y 翻转）
        viewportGadget.frame(
            imath.Box3f(
                imath.V3f(
                    visible.left() / PX_PER_UNIT, -visible.bottom() / PX_PER_UNIT, 0
                ),
                imath.V3f(
                    visible.right() / PX_PER_UNIT, -visible.top() / PX_PER_UNIT, 0
                ),
            )
        )

    ## 我们自己那个裸 GraphGadget（不含"借来的编辑器"那种）——取景器只能挂它。
    def __ownGraphGadget(self):

        if self.__gadgetForGeometry is None:
            self.__gadgetForGeometry = GafferUI.GraphGadget(self.scriptNode())
            self.__gadgetRootChangedConnection = (
                self.__gadgetForGeometry.rootChangedSignal().connect(
                    Gaffer.WeakMethod(self.__gadgetRootChanged), scoped=True
                )
            )

        if not self.__gadgetForGeometry.getRoot().isSame(self.__root):
            self.__gadgetForGeometry.setRoot(self.__root)

        return self.__gadgetForGeometry

    ## 有人对我们交出去的 gadget `setRoot()`（项目 J / `/` 快捷键）→ 视图跟着换层。
    # 我们自己 `setRootNode` 时先改 `__root` 再 `setRoot`，到这里已经相等，什么都不做。
    def __gadgetRootChanged(self, gadget, previousRoot):

        root = gadget.getRoot()
        if not root.isSame(self.__root):
            self.setRootNode(root)

    ## 几何 / 自动布局用的原生 GraphGadget。
    #
    # 节点大小、接口位置一律从它身上取（`nodeSizeUnits` / `_NodeItem.__buildNodules`），
    # 这样和原生节点编辑器里的节点分毫不差；`connectNode` / `positionNode` /
    # `layoutNodes` 也是它提供的。裸 GraphGadget 比整个 GraphEditor 轻得多，而且实测
    # **不会**偷偷去建 `__uiPosition`（那是 GraphEditor 渲染时才做的事）。
    def __graphGadget(self):

        if not gadgetEnabled():
            return None  # 几何全部退回公式（见 `nodeSizeUnits` / `__buildNodules`）

        if self.__engineEditor is not None:
            if self.__root.isSame(self.__engineEditor.graphGadget().getRoot()):
                return self.__engineEditor.graphGadget()

        if not self.__existingEditorChecked:
            self.__existingEditorChecked = True
            editor = self.__existingGraphEditor()
            if editor is not None:
                self.__engineEditor = editor
                self.__borrowedEngine = True
                return editor.graphGadget()

        return self.__ownGraphGadget()

    ##########################################################################
    # 工具条
    ##########################################################################

    def __buildToolBar(self):

        bar = QtWidgets.QWidget()
        bar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        bar.setStyleSheet("background-color: %s;" % _toolBarColor)
        bar.setFixedHeight(28)

        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(6)

        # **界面文字一律英文**（和原生 Gaffer 拼在一起不串语言），
        # **悬停小框（tooltip）一律中文**做辅助。
        self.__upButton = QtWidgets.QToolButton()
        self.__upButton.setText("↑")
        self.__upButton.setToolTip("回到上一层（快捷键 ↑）")
        self.__upButton.clicked.connect(lambda *unused: self._leaveNode())
        row.addWidget(self.__upButton)

        self.__crumbLabel = QtWidgets.QLabel()
        self.__crumbLabel.setStyleSheet("color: #b9c0c6;")
        row.addWidget(self.__crumbLabel)

        row.addStretch(1)

        self.__wireButton = QtWidgets.QToolButton()
        self.__wireButton.setText("Curved")
        self.__wireButton.setToolTip(
            "连线样式：Curved 曲线 / Straight 直线，点一下切换"
        )
        self.__wireButton.clicked.connect(lambda *unused: self.__toggleWireStyle())
        row.addWidget(self.__wireButton)

        self.__annotationsButton = QtWidgets.QToolButton()
        self.__annotationsButton.setToolTip(
            "显示哪些注释：全部 / 一条都不显示 / 按类型挑（默认只显示人写的那些）"
        )
        icon = _graphicIcon("annotations.png")
        if icon is not None:
            self.__annotationsButton.setIcon(icon)
        else:
            self.__annotationsButton.setText("Notes")
        self.__annotationsButton.clicked.connect(
            lambda *unused: self.__popupAnnotationsMenu()
        )
        row.addWidget(self.__annotationsButton)

        self.__snapButton = QtWidgets.QToolButton()
        self.__snapButton.setText("Snap")
        self.__snapButton.setToolTip(
            "自动对齐：拖动节点时吸附到其它节点的中线并亮出参考线（默认开）"
        )
        self.__snapButton.setCheckable(True)
        self.__snapButton.setChecked(self.__snapEnabled)
        self.__snapButton.toggled.connect(lambda enabled: self.setSnapEnabled(enabled))
        row.addWidget(self.__snapButton)

        frameButton = QtWidgets.QToolButton()
        frameButton.setText("Frame")
        frameButton.setToolTip("适应视图（快捷键 F）；有选中的节点时只框住选中的")
        frameButton.setAutoRaise(True)
        frameButton.clicked.connect(lambda *unused: self.__view.frameSelection())
        row.addWidget(frameButton)

        self.__statusLabel = QtWidgets.QLabel()
        self.__statusLabel.setStyleSheet("color: #6f7981;")
        self.__statusLabel.setToolTip(
            "当前这一层有多少个节点、多少条连线；进入删除模式时这里显示操作提示"
        )
        row.addWidget(self.__statusLabel)

        return bar

    ##########################################################################
    # 注释的可见性（原生 GraphEditor 右上角那个 annotations 菜单）
    ##########################################################################

    ## 现在画哪些注释（`IECore.StringAlgo` 的匹配模式，空格分隔）。
    def getVisibleAnnotations(self):

        return self.__visibleAnnotations

    def setVisibleAnnotations(self, pattern):

        pattern = str(pattern)
        if pattern == self.__visibleAnnotations:
            return

        self.__visibleAnnotations = pattern
        for item in self.__nodeItems.values():
            item.refreshAnnotations()

    ## 菜单内容照原生 `GraphEditor.__annotationsMenu`：All / None / 每个模板一条。
    def __annotationsMenuDefinition(self):

        names = annotationTemplateNames() + ["user", UNTEMPLATED_ANNOTATIONS]
        visible = set(
            name
            for name in names
            if IECore.StringAlgo.matchMultiple(name, self.__visibleAnnotations)
        )

        definition = IECore.MenuDefinition()
        definition.append(
            "/All",
            {
                "checkBox": len(visible) == len(names),
                "command": functools.partial(
                    Gaffer.WeakMethod(self.__setVisibleAnnotations), {"*"}
                ),
            },
        )
        definition.append(
            "/None",
            {
                "checkBox": len(visible) == 0,
                "command": functools.partial(
                    Gaffer.WeakMethod(self.__setVisibleAnnotations), set()
                ),
            },
        )
        definition.append("/__allDivider__", {"divider": True})

        def append(name, label=None):

            definition.append(
                "/" + (label if label is not None else annotationLabel(name)),
                {
                    "checkBox": name in visible,
                    "command": functools.partial(
                        Gaffer.WeakMethod(self.__setVisibleAnnotations),
                        (visible - {name}) if name in visible else (visible | {name}),
                    ),
                },
            )

        userTemplates = annotationTemplateNames(userOnly=True)
        for name in userTemplates:
            append(name)
        if userTemplates:
            definition.append("/__userDivider__", {"divider": True})
        append("user")

        others = [n for n in annotationTemplateNames() if n not in userTemplates]
        if others:
            definition.append("/__templateDivider__", {"divider": True})
            for name in others:
                append(name)

        definition.append("/__otherDivider__", {"divider": True})
        append(UNTEMPLATED_ANNOTATIONS, label="Other")

        return definition

    def __setVisibleAnnotations(self, annotations, *unused):

        # 原生 `__setVisibleAnnotations`：集合 → 用空格连起来的匹配模式
        self.setVisibleAnnotations(
            " ".join(a.replace(" ", r"\ ") for a in sorted(annotations))
        )

    def __popupAnnotationsMenu(self):

        # 走我们自己的面板（和 Tab / S / Q 那些菜单同一个通道），贴着按钮下沿弹
        self.__annotationsMenu = GafferUI.Menu(
            self.__annotationsMenuDefinition(), title="Annotations"
        )
        button = self.__annotationsButton
        self._showMenuAsPanel(
            self.__annotationsMenu,
            globalPosition=button.mapToGlobal(QtCore.QPoint(0, button.height())),
        )

    def __toggleWireStyle(self):

        if self.__wireStyle == WIRE_CURVED:
            self.setWireStyle(WIRE_STRAIGHT)
            self.__wireButton.setText("Straight")
        else:
            self.setWireStyle(WIRE_CURVED)
            self.__wireButton.setText("Curved")

    ##########################################################################
    # 层级导航
    ##########################################################################

    def _enterNode(self, node):

        self.setRootNode(node)

    ## 原生 `GraphEditor.__childrenViewable`：Box 之类标了 `ui:childNodesAreViewable`
    # 的直接按 ↓ 进去（右键也才有 Show Contents...），别的（比如内部实现不该乱翻的
    # 节点）要 Shift+Ctrl+↓。
    @staticmethod
    def _childrenViewable(node):

        # 三层键，顺序照原生 `GraphEditor.__childrenViewable`（`GraphEditor.py:895-908`）：
        # `ui:childNodesAreViewable` 是现在的正式键（Box / Reference / EditScope /
        # ScriptNode 都注册它），另外两个是逐代淘汰中的老键 —— 原生还认，我们也认，
        # 否则只写了老键的第三方节点按 ↓ 进不去。
        for key in (
            "ui:childNodesAreViewable",
            "graphEditor:childrenViewable",
            "nodeGraph:childrenViewable",
        ):
            viewable = Gaffer.Metadata.value(node, key)
            if viewable is not None:
                return bool(viewable)

        return False

    ## ↓ 键：进入选中的那个节点。逐条抄原生 `GraphEditor.__keyPress` 的 "Down" 分支。
    def _enterSelectedNode(self, withModifiers=False):

        selection = self.scriptNode().selection()
        if selection.size() != 1:
            return False

        node = selection[0]
        if not isinstance(node, Gaffer.Node):
            return False

        parent = node.parent()
        if parent is None or not self.__root.isSame(parent):
            return False

        needsModifiers = not self._childrenViewable(node)
        if needsModifiers != withModifiers:
            return False

        self.setRootNode(node)
        return True

    ## ↑ 键：回到上一层。
    def _leaveNode(self):

        if self.__root is None or self.__root.isSame(self.scriptNode()):
            return False

        parent = self.__root.parent()
        while parent is not None and not isinstance(parent, Gaffer.Node):
            parent = parent.parent()

        self.setRootNode(parent if parent is not None else self.scriptNode())
        return True

    ## `[` / `]`：在去过的层之间来回跳（原生同款根历史）。
    def _previousRoot(self):

        return self.__navigateRootHistory(1)

    def _nextRoot(self):

        return self.__navigateRootHistory(-1)

    def __navigateRootHistory(self, direction):

        if len(self.__rootHistory) < 1:
            return False

        script = self.scriptNode()
        root = self.__root

        self.__navigatingRootHistory = True

        if direction > 0 and not self.__rootHistory[-1].isSame(root):
            self.__rootHistory.append(root)
            self.__rootHistory.rotate(1)

        guard = len(self.__rootHistory)
        while guard and self.__rootHistory[-1].isSame(root):
            self.__rootHistory.rotate(direction)
            guard -= 1

        alternateRoot = self.__rootHistory[-1]
        if alternateRoot.isSame(script) or script.isAncestorOf(alternateRoot):
            self.setRootNode(alternateRoot)
        else:
            # 那一层已经被删掉了
            self.__rootHistory.pop()
            self.__navigatingRootHistory = False

        return True

    ## 双击 = 打开浮动 NodeEditor（原生 `startup/gui/graphEditor.py` 的行为）。
    def _editNode(self, node):

        # 先发原生的 `nodeDoubleClickSignal`（和另外三套右键菜单同一个路子）——
        # 装机版 `startup/gui/graphEditor.py` 连的就是「开一个浮动 NodeEditor」，
        # 而项目自己也可能往这个信号上挂东西。有人处理了就到此为止。
        host = self.__menuHost()
        # （`WidgetEventSignal` 的 combiner 自己会接住并打印 handler 抛的异常）
        if host is not None:
            if GafferUI.GraphEditor.nodeDoubleClickSignal()(host, node):
                return

        GafferUI.NodeEditor.acquire(node, floating=True)

    ## 点节点上的 focus flag：设为 focus；已经是 focus 就取消。
    # 逐条抄原生 `StandardNodeGadget.cpp` 里 `FocusGadget::toggleFocus`。
    def _toggleNodeFocus(self, node):

        script = self.scriptNode()
        focus = script.getFocus()

        if focus is not None and focus.isSame(node):
            script.setFocus(None)
        else:
            script.setFocus(node)

    ## 收起 / 展开某个侧边分栏（Houdini 式）。收放状态存**节点非持久元数据**，
    # 重排 item 不会丢、也不存进 .grf；`nodeValueChangedSignal` 那边
    # `rebuildOnNodeMetadata` 认 `nodeGadget:sectionCollapsed:` 前缀，一变就重建。
    ##########################################################################
    # Backdrop：悬停高亮标题条 / 拉框改大小
    ##########################################################################

    ## 光标压在哪个 Backdrop 的框身上（原生：不在边缘上时标题条高亮）。
    def _setHoveredBackdrop(self, item):

        name = item.nodeName if item is not None else None
        if name == self.__hoveredBackdrop:
            return

        previous = self.__backdropItems.get(self.__hoveredBackdrop)
        if previous is not None:
            previous.setHovered(False)

        self.__hoveredBackdrop = name
        if item is not None:
            item.setHovered(True)

    ## 拉框：只改 item 上的预览，松手才写回插口（一次拖动一步撤销）。
    def _resizeBackdrop(self, item, horizontal, vertical, scenePoint):

        if self.readOnly():
            return

        item.setPreviewBound(item.boundForEdgeDrag(horizontal, vertical, scenePoint))
        # **拉框途中绝不动 `sceneRect`**：`setSceneRect` 会改滚动条范围、视图跟着漂
        # 一下，而漂移只有 item 那一块报了脏 → 屏幕上留一大片没重画的东西
        # （实测每帧差两三千个采样点，而且框会一路自己变长）。sceneRect 有
        # `SCENE_MARGIN` 那么大的余量，画到它外面也不会被裁 —— 松手
        # `_commitBackdropResize` 时再更新一次就够。

    def _commitBackdropResize(self, item):

        if item.commitPreviewBound():
            self.__updateSceneRect()

    def _toggleSection(self, node, side, section):

        if sectionCollapsed(node, side, section):
            setSectionCollapsed(node, side, section, False)
        else:
            setSectionCollapsed(node, side, section, True)

    ## ` 键：把 focus 节点框进画面。
    def _frameFocus(self):

        focus = self.scriptNode().getFocus()
        if focus is None:
            return

        item = self.__nodeItems.get(focus.getName())
        if item is not None:
            self.__view.frameItems([item])

    ## Ctrl+` ：把选中的第一个节点设成 focus。
    def _focusSelection(self):

        selection = self.scriptNode().selection()
        if len(selection):
            self.scriptNode().setFocus(selection[0])

    ## 记下某一层现在看到哪儿。同一层只留最后一次。
    def __rememberViewState(self, node):

        if node is None:
            return

        rect = self.__view.viewedSceneRect()
        if rect is None or rect.isNull():
            return

        for index, (other, _) in enumerate(self.__viewStates):
            if other.isSame(node):
                del self.__viewStates[index]
                break

        self.__viewStates.append((node, rect))

    ## 把视野对回这一层上次看的地方。没记过（或那层已经被删了）返回 False。
    def __restoreViewState(self, node):

        if node is None:
            return False

        for other, rect in self.__viewStates:
            if not other.isSame(node):
                continue
            if other.scriptNode() is None:
                return False
            return self.__view.setViewedSceneRect(rect)

        return False

    def __updateCrumbs(self):

        names = []
        node = self.__root
        script = self.scriptNode()
        while node is not None and not node.isSame(script):
            names.append(node.getName())
            node = node.parent()

        names.reverse()
        self.__crumbLabel.setText(" / ".join(["root"] + names))
        self.__upButton.setEnabled(bool(names))

    ##########################################################################
    # 信号 -> 标脏（绝不在这里同步重建，会和原生 GraphEditor 的 preRender 打成死循环）
    ##########################################################################

    def __scheduleUpdate(self):

        if self.__idleScheduled:
            return

        self.__idleScheduled = True
        GafferUI.EventLoop.addIdleCallback(
            Gaffer.WeakMethod(self.__idleUpdate, fallbackResult=False)
        )

    ## 底下那个 QGraphicsView 的 C++ 对象还在不在。
    #
    # 面板被关掉 / 布局重排把编辑器拆掉时，Qt 先销毁 `_GraphView`，而已经挂在事件循环上
    # 的 idle 回调还会再响一次 —— 那一下碰 `self.__view` 就是
    # `RuntimeError: Internal C++ object (_GraphView) already deleted` 刷一屏。
    # Python 这边的属性还指着那个壳，`is not None` 判不出来，只能真去碰一下。
    def __viewAlive(self):

        if self.__view is None:
            return False

        try:
            self.__view.viewport()
        except RuntimeError:
            return False

        return True

    def __idleUpdate(self):

        self.__idleScheduled = False

        # 编辑器已经被拆掉了：什么都别做，也别再挂下一次（返回 False = 注销回调）。
        if not self.__viewAlive():
            return False

        # **正在拖东西的时候不重建**（脏标记原样留着，松手那一下 `_flushPostponedUpdate`
        # 会补上）。这里不能顺手再 `__scheduleUpdate()` —— idle 回调里再挂 idle 回调
        # 就是那个 100% CPU 的死循环。
        # 还要真的**有键按着**才算：模式标记是我们自己维护的，万一哪条路松手没走到
        # （测试里合成事件、或者焦点被抢走），光看模式就会把重建永久冻住。
        if (
            self.__view is not None
            and self.__view.interacting()
            and QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton
        ):
            self.__updatePostponed = True
            return False

        self.__updatePostponed = False

        if self.__structureDirty or self.__dirtyItems or self.__dirtyEdges:
            self.__applyGraphChanges()
        if self.__dirtyPositions:
            self.__updatePositions()
        if self.__selectionDirty:
            self.__updateSelection()

        self.__structureDirty = False
        self.__dirtyItems = set()
        self.__dirtyEdges = set()
        self.__dirtyPositions = set()
        self.__selectionDirty = False

        return False

    ## 拖动期间推迟掉的重建，松手之后补上。
    def _flushPostponedUpdate(self):

        if not self.__updatePostponed:
            return

        self.__updatePostponed = False
        self.__scheduleUpdate()

    def __childrenChanged(self, parent, child):

        if not isinstance(child, Gaffer.Node):
            return

        self.__structureDirty = True
        self.__scheduleUpdate()

    ## 当前这一层（或它的某个祖先）改名了 —— 标题和面包屑跟着刷。
    def __rootNameChanged(self, node, oldName):

        self.__updateCrumbs()
        self.titleChangedSignal()(self)

    ## 当前这一层（或它的某个祖先）被移出图了 —— 退回脚本根（原生同款）。
    def __rootParentChanged(self, node, oldParent):

        if node.parent() is None:
            self.setRootNode(self.scriptNode())

    def __nodeNameChanged(self, node, oldName):

        # item 是按名字存的（`__nodeItems`），而且宽度跟名字走 —— 改名当成"结构变了"，
        # 那一个节点的 item 重建一次就够（全图不用动）。
        self.__structureDirty = True
        self.__dirtyItems.add(oldName)
        self.__scheduleUpdate()

    def __plugInputChanged(self, plug):

        # 信号报的是**目的地**那个节点：只有以它为终点的那些边会变
        node = plug.node()
        if node is None:
            self.__structureDirty = True
        else:
            self.__dirtyEdges.add(node.getName())

            # **`enabled` 接上 / 拔掉驱动**：从"读得出的死值"变成"要算的"（或反过来），
            # 停用那条对角线跟着换一种画法 —— 这个只有 `plugInputChangedSignal` 报，
            # `plugSetSignal` 不报，光标脏边的话画面会一直停在旧样子。
            if isinstance(node, Gaffer.DependencyNode):
                enabledPlug = node.enabledPlug()
                if enabledPlug is not None and (
                    enabledPlug.isSame(plug) or enabledPlug.isAncestorOf(plug)
                ):
                    self.__markItemDirty(node)

        self.__scheduleUpdate()

    def __plugSet(self, plug):

        name = plug.getName()

        node = plug.node()

        if name == "__uiPosition":
            if node is not None:
                self.__dirtyPositions.add(node.getName())
            self.__scheduleUpdate()
        elif name in (
            "__uiInputConnectionsMinimised",
            "__uiOutputConnectionsMinimised",
            "__uiBound",
        ):
            self.__markItemDirty(node)
            self.__scheduleUpdate()
        elif isinstance(node, Gaffer.Backdrop) and name in (
            "title",
            "description",
            "scale",
            "depth",
        ):
            self.__markItemDirty(node)
            self.__scheduleUpdate()
        elif isinstance(node, Gaffer.DependencyNode):
            # 只认节点自己那个 `enabled`（Spreadsheet 行、Tweaks 成员里也有叫 enabled 的）
            enabledPlug = node.enabledPlug()
            if enabledPlug is not None and enabledPlug.isSame(plug):
                self.__markItemDirty(node)
                self.__scheduleUpdate()

    ## 节点元数据变了（3 参：node, key, reason）。
    def __nodeMetadataChanged(self, node, key, reason):

        if not rebuildOnNodeMetadata(key):
            return

        self.__markItemDirty(node)
        self.__scheduleUpdate()

    ## 节点身上多了 / 少了插口（2 参：parent, child）。
    def __nodePlugsChanged(self, parent, child):

        if not isinstance(child, Gaffer.Plug):
            return

        # 定位这次增删属于哪个节点。`parent` 可能是节点自己（childAdded 直达），
        # 也可能是插口自己（`in` ArrayPlug 的 childRemoved）—— 后者要拿
        # `parent.node()`，**不能**拿 `child.node()`：`child` 是刚被摘掉的插口，
        # 已经 detached、node() 是 None（节点被删时连着的插口一并拆掉也会走到这），
        # 拿它定位会误判成全图 dirty、触发整图重建、把 X 模式的划线状态冲掉。
        node = parent if isinstance(parent, Gaffer.Node) else parent.node()
        if node is None:
            return

        self.__markItemDirty(node)
        self.__scheduleUpdate()

    ## 插口元数据变了（3 参：plug, key, reason）。
    def __plugMetadataChanged(self, plug, key, reason):

        if not rebuildOnPlugMetadata(key):
            return

        node = plug.node() if plug is not None else None
        if node is None:
            # 插口正在被销毁（节点删除时元数据跟着拆），节点删除本身会走
            # childRemoved 那路处理，这里定位不到节点就不掺和 —— 否则又是全图 dirty。
            return

        self.__markItemDirty(node)
        self.__scheduleUpdate()

    ## 某个节点的 item 要重建（形状 / 颜色 / 图标 / 尺寸可能都变了）。
    def __markItemDirty(self, node):

        self.__dirtyItems.add(node.getName())

    def __nodePlugDirtied(self, plug):

        if not self.__errorNodes:
            return

        node = plug.node()
        if node is None:
            return

        name = node.getName()
        if name in self.__errorNodes:
            self.__errorNodes.discard(name)
            item = self.__nodeItems.get(name)
            if item is not None:
                item.setError(False)

    ## `errorSignal` 在**做计算的那个线程**上发（Viewer、后台任务），碰 Qt 之前先回 UI
    # 线程 —— 原生 `StandardNodeGadget::error` 也是 `callOnUIThread`。
    def __nodeError(self, plug, source, message):

        node = plug.node()
        if node is None:
            return

        GafferUI.EventLoop.executeOnUIThread(
            functools.partial(
                Gaffer.WeakMethod(self.__showNodeError), node, str(message)
            )
        )

    def __showNodeError(self, node, message):

        item = self.__nodeItems.get(node.getName())
        if item is None or not item.node.isSame(node):
            return

        self.__errorNodes.add(node.getName())
        # 原生的 ErrorGadget 把出错信息挂在 tooltip 上（`StandardNodeGadget`
        # 的 `addError`）—— 照做，光有个红角标看不出出了什么事。
        item.setError(True, message)

    def __selectionMemberChanged(self, memberSet, member):

        if self.__updatingSelection:
            return

        self.__selectionDirty = True
        self.__scheduleUpdate()

    def __focusChanged(self, script, node):

        self.__updateFocus()

    ##########################################################################
    # 重建
    ##########################################################################

    def __rebuild(self):

        script = self.scriptNode()

        if self.__root is None or (
            not self.__root.isSame(script) and self.__root.parent() is None
        ):
            self.__root = script

        # scene.clear() 会销毁临时 item（划线、拖拽中的连线），先让视图忘掉它们
        self.__view._discardTransientItems()

        self.__scene.blockSignals(True)
        try:
            self.__scene.clear()
        finally:
            self.__scene.blockSignals(False)

        self.__nodeItems = {}
        self.__backdropItems = {}
        self.__edgeItems = []
        self.__edgesByNode = {}
        self.__nodeConnections = {}
        self.__rootConnections = []
        self.__hoveredNoduleItem = None
        self.__hoveredAdderItem = None
        self.__hoveredBackdrop = None
        self.__hoveredSectionItem = None
        self.__dropTargetItem = None
        self.__insertCandidate = None  # item 都被销毁了，候选跟着作废
        self.__snapGuides = []
        # 错误角标按名字记，换层后另一层的同名节点不该亮
        self.__errorNodes = set()

        # 节点大小 / 接口位置全部照抄原生 NodeGadget（拿不到就走公式回退）
        graphGadget = self.__graphGadget()

        # 进 Box 之前先把「从没摆过位置」的节点按原生自动布局排好
        self.__layoutUnpositionedNodes(graphGadget)

        nodes = collectNodes(self.__root)

        unpositioned = 0
        for node in nodes:
            unpositioned = self.__createNodeItem(node, graphGadget, unpositioned)

        self.__syncEdges(nodes)

        self.__rootConnections = [
            self.__root.childAddedSignal().connect(
                Gaffer.WeakMethod(self.__childrenChanged), scoped=True
            ),
            self.__root.childRemovedSignal().connect(
                Gaffer.WeakMethod(self.__childrenChanged), scoped=True
            ),
        ]

        # **root 和它所有祖先都要跟着**（原生 `__rootChanged` 同款）：改名了标题和
        # 面包屑要跟着变；被删掉 / 从图里移走了就退回脚本根 —— 不然编辑器会停在
        # 一个已经不在图里的 Box 上（面包屑还画着它）。
        node = self.__root
        while node is not None and not isinstance(node, Gaffer.ScriptNode):
            self.__rootConnections.append(
                node.nameChangedSignal().connect(
                    Gaffer.WeakMethod(self.__rootNameChanged), scoped=True
                )
            )
            self.__rootConnections.append(
                node.parentChangedSignal().connect(
                    Gaffer.WeakMethod(self.__rootParentChanged), scoped=True
                )
            )
            node = node.parent()

        # **`created = True`**：全量重建的 item 个个都是新的，`选中 / focus / 参与计算`
        # 这三样状态都还是默认值，必须重新盖上去。少了这一下，**进 / 出 Box 之后
        # focus 角标丢了、focus 的变暗也不生效** —— 换层走的就是这条路。
        self.__finishUpdate(created=True)

    ## **增量更新**：只动真变了的那几个 item / 那几条边。
    #
    # 全量重建在 800 节点的图上要 245ms（63% 花在逐个建 `_NodeItem`：每个都要问原生
    # gadget 要尺寸 / nodule / `+`）。按名字 diff：节点集合变了只建删差集那几个；
    # 只是某根线接上 / 拔了（`plugInputChangedSignal` 报的是**目的地**节点）就连
    # 节点集合都不扫，只重收以它为终点的那几条边。
    def __applyGraphChanges(self):

        script = self.scriptNode()

        if self.__root is None or (
            not self.__root.isSame(script) and self.__root.parent() is None
        ):
            self.__rebuild()
            return

        # **只是几根线变了**（拖线 / 拔线，日常最常见的一件事）：节点集合根本没动 ——
        # 这条路上一次全图都不许扫（`collectNodes` 在 2000 个节点上要 9ms），
        # 直接用现成的 item 索引当「当前有哪些节点」。
        if not self.__structureDirty and not self.__dirtyItems and self.__dirtyEdges:
            if self.__applyEdgeChangesOnly():
                return

        graphGadget = self.__graphGadget()
        self.__layoutUnpositionedNodes(graphGadget)

        nodes = collectNodes(self.__root)
        wanted = collections.OrderedDict((node.getName(), node) for node in nodes)

        # 只报了"某根线变了"的那些节点，顺手核一下**接口是不是也变了**：
        # `NameSwitch` / `Collect` 那种 ArrayPlug 是「丢条线上去自动长一路」的，
        # 信号只有 `plugInputChangedSignal`，不核对的话卡片上就少一个圆点。
        for name in list(self.__dirtyEdges):
            item = self.__nodeItems.get(name)
            node = wanted.get(name)
            if item is None or node is None:
                continue
            if _noduleSignature(noduleLayout(node)) != _noduleSignature(item._nodules):
                self.__dirtyItems.add(name)

        have = set(self.__nodeItems) | set(self.__backdropItems)
        stale = (have - set(wanted)) | (self.__dirtyItems & have)

        # 名字还在、节点已经换了一个（File > Revert、Reference 重载、删掉再建同名）：
        # 旧 item 连着的是已经删掉的节点，必须重建。只在节点集合动过时才查。
        gone = have - set(wanted)
        if self.__structureDirty:
            for name in have & set(wanted):
                item = self.__nodeItems.get(name) or self.__backdropItems.get(name)
                if not item.node.isSame(wanted[name]):
                    stale.add(name)
                    gone.add(name)

        # 节点没了 / 换成了同名的另一个：错误角标不能留给新来的那个
        self.__errorNodes -= gone

        # **动 item 期间一律屏蔽 scene 的信号**：删掉一个选中的 item，
        # `QGraphicsScene` 会发 `selectionChanged` → 我们把"少了一个"当成用户改选择
        # 又写回 script，选择就被吃掉了（全量重建那边早就这么防着了）。
        self.__scene.blockSignals(True)
        try:

            for name in stale:
                self.__removeNodeItem(name)

            missing = [
                node
                for name, node in wanted.items()
                if name not in self.__nodeItems and name not in self.__backdropItems
            ]

            unpositioned = 0
            for node in missing:
                unpositioned = self.__createNodeItem(node, graphGadget, unpositioned)

            if stale or missing:
                # 节点集合动过（新建 / 删除 / 改名 / item 重建）→ 边整体对一遍。
                # 收边比建 item 便宜一个数量级，够用。
                self.__syncEdges(nodes)
            else:
                names = set(wanted)
                for name in self.__dirtyEdges:
                    self.__refreshEdgesForDestination(wanted.get(name), names)

        finally:
            self.__scene.blockSignals(False)

        self.__finishUpdate(structural=True, created=bool(stale or missing))

    ## 只重收几个节点的**入边**，别的什么都不动。
    #
    # 接口对不上（`NameSwitch` 那种「丢条线上去自动长一路」）就返回 False，
    # 退回上面那条完整的路。
    def __applyEdgeChangesOnly(self):

        names = set(self.__nodeItems) | set(self.__backdropItems)

        targets = []
        for name in self.__dirtyEdges:

            item = self.__nodeItems.get(name)
            if item is None:
                if name in self.__backdropItems:
                    continue  # Backdrop 上没有连线
                return False  # 名字对不上（刚被删了？）→ 走完整那条路

            node = item.node
            if _noduleSignature(noduleLayout(node)) != _noduleSignature(item._nodules):
                self.__dirtyItems.add(name)  # 接口变了 → 那个 item 得重建
                return False

            targets.append(node)

        self.__scene.blockSignals(True)
        try:
            for node in targets:
                self.__refreshEdgesForDestination(node, names)
        finally:
            self.__scene.blockSignals(False)

        self.__finishUpdate(structural=False, created=False)
        return True

    ## 一次更新的收尾。
    #
    # 每一项都是 **O(全图)**（2000 节点上光 focus + active + sceneRect 就 14ms），
    # 所以各自只在真需要时做：`structural` = 节点集合 / 位置变了才重算包围盒和面包屑；
    # `created` = 有新 item 才补选择和 focus 状态。
    def __finishUpdate(self, structural=True, created=False):

        if structural:
            self.__updateSceneRect()
            self.__updateCrumbs()

        if created:
            self.__updateSelection()
            self.__updateFocus()

        self.__refreshStatus()

    ##########################################################################
    # item 的增删（全量和增量走同一套）
    ##########################################################################

    ## 建一个节点的 item 并接上它的信号。返回新的「没位置的节点」计数。
    def __createNodeItem(self, node, graphGadget, unpositioned=0):

        name = node.getName()

        if isinstance(node, Gaffer.Backdrop):
            item = _BackdropItem(node, self)
            self.__scene.addItem(item)
            self.__backdropItems[name] = item
        else:
            item = _NodeItem(node, self, graphGadget)
            position = nodePosition(node)
            if position is None:
                # 刚建出来、原生 GraphEditor 还没跑 preRender → 先错开排一列，
                # 等它写了 __uiPosition 我们再跟上。
                item.setPos(unpositioned * 30.0, unpositioned * 22.0)
                unpositioned += 1
            else:
                item.setPos(position.x * PX_PER_UNIT, -position.y * PX_PER_UNIT)

            if name in self.__errorNodes:
                item.setError(True)

            self.__scene.addItem(item)
            self.__nodeItems[name] = item

        self.__nodeConnections[name] = [
            node.nameChangedSignal().connect(
                Gaffer.WeakMethod(self.__nodeNameChanged), scoped=True
            ),
            # 插口结构变了（Box 提升出一个插口、BoxIO/Switch `setup()`…）→ 接口圆点
            # 会变，这个 item 得重建。`plugInputChangedSignal` 只报"谁接上了"，报不了
            # "多了个插口"。
            node.childAddedSignal().connect(
                Gaffer.WeakMethod(self.__nodePlugsChanged), scoped=True
            ),
            node.childRemovedSignal().connect(
                Gaffer.WeakMethod(self.__nodePlugsChanged), scoped=True
            ),
            node.plugInputChangedSignal().connect(
                Gaffer.WeakMethod(self.__plugInputChanged), scoped=True
            ),
            node.plugSetSignal().connect(
                Gaffer.WeakMethod(self.__plugSet), scoped=True
            ),
            node.errorSignal().connect(
                Gaffer.WeakMethod(self.__nodeError), scoped=True
            ),
            # 出过错的节点，下一次任何插口变脏就把红角标摘掉（原生 `StandardNodeGadget`
            # 就是 `plugDirtiedSignal → removeError`）；没出过错时这个回调一句判断就返回
            node.plugDirtiedSignal().connect(
                Gaffer.WeakMethod(self.__nodePlugDirtied), scoped=True
            ),
            # 形状 / 颜色 / 图标 / 书签这些都写在节点元数据上（右键 Show Name 就是改
            # `nodeGadget:type`），不听这个信号画面不会跟着变
            Gaffer.Metadata.nodeValueChangedSignal(node).connect(
                Gaffer.WeakMethod(self.__nodeMetadataChanged), scoped=True
            ),
            # **插口**元数据（3 参：plug, key, reason）。圆点右键那条
            # 「Expand RGB Components」改的就是子插口上的 `noduleLayout:visible` ——
            # 不听这个信号，菜单点了卡片上不长子圆点。
            Gaffer.Metadata.plugValueChangedSignal(node).connect(
                Gaffer.WeakMethod(self.__plugMetadataChanged), scoped=True
            ),
        ]

        # **直系插口自己也会增删子插口**：`NameSwitch.in` / `Collect.in` / `Group.in`
        # 这些 ArrayPlug 的 `resize()` 会往 `in` 里塞 / 拔 `NameValuePlug`。
        # `plugInputChangedSignal` 只在「接上 / 拔掉一根线」时响 —— 一个**空着**的
        # 槽位被 `resize()` 删掉它根本不响，节点卡片就永远停在旧大小（加满输入的
        # NameSwitch 一个个删输入口，大小不跟着变）。必须连每个直系
        # 插口自己的 `childAddedSignal` / `childRemovedSignal`，`in` 一缩就重建。
        # 只连**会长子插口的**那几个（`plugMayGrowChildren`）：ScenePlug / Float /
        # V3f 这些叶子的子插口结构是死的，全连的话建一个 item 一半时间花在连信号上。
        for plug in node.children(Gaffer.Plug):
            if not plugMayGrowChildren(plug):
                continue
            self.__nodeConnections[name].append(
                plug.childAddedSignal().connect(
                    Gaffer.WeakMethod(self.__nodePlugsChanged), scoped=True
                )
            )
            self.__nodeConnections[name].append(
                plug.childRemovedSignal().connect(
                    Gaffer.WeakMethod(self.__nodePlugsChanged), scoped=True
                )
            )

        return unpositioned

    ## 拆掉一个节点的 item：连它的边、信号连接、以及所有指着它的悬停 / 拖拽状态。
    def __removeNodeItem(self, name):

        for edgeItem in list(self.__edgesByNode.get(name, [])):
            self.__removeEdgeItem(edgeItem)
        self.__edgesByNode.pop(name, None)

        item = self.__nodeItems.pop(name, None)
        if item is None:
            item = self.__backdropItems.pop(name, None)

        if item is not None and item.scene() is not None:
            self.__scene.removeItem(item)

        self.__nodeConnections.pop(name, None)

        # 这些都是**按名字**记的状态，item 没了就得跟着清，否则下一次悬停 / 拖放
        # 会去访问一个已经不在 scene 里的 item
        if self.__hoveredNoduleItem == name:
            self.__hoveredNoduleItem = None
        if self.__hoveredAdderItem == name:
            self.__hoveredAdderItem = None
        if self.__hoveredBackdrop == name:
            self.__hoveredBackdrop = None
        if self.__hoveredSectionItem == name:
            self.__hoveredSectionItem = None
        if self.__dropTargetItem == name:
            self.__dropTargetItem = None

    def __createEdgeItem(self, edge):

        srcItem = self.__nodeItems.get(edge.srcNode.getName())
        dstItem = self.__nodeItems.get(edge.dstNode.getName())
        if srcItem is None or dstItem is None:
            return None

        item = _EdgeItem(edge, srcItem, dstItem, self.__wireStyle)
        self.__scene.addItem(item)
        self.__edgeItems.append(item)
        self.__edgesByNode.setdefault(edge.srcNode.getName(), []).append(item)
        self.__edgesByNode.setdefault(edge.dstNode.getName(), []).append(item)

        return item

    def __removeEdgeItem(self, item):

        if item in self.__edgeItems:
            self.__edgeItems.remove(item)

        for name in (item.edge.srcNode.getName(), item.edge.dstNode.getName()):
            bucket = self.__edgesByNode.get(name)
            if bucket is not None and item in bucket:
                bucket.remove(item)

        if item.scene() is not None:
            self.__scene.removeItem(item)

    ## 全图的边对一遍：多出来的删掉、缺的补上（按 `Edge.key()` 比）。
    def __syncEdges(self, nodes):

        wanted = {}
        for edge in collectEdges(self.__root, nodes):
            wanted[edge.key()] = edge

        for item in list(self.__edgeItems):
            if item.edge.key() not in wanted:
                self.__removeEdgeItem(item)

        existing = set(item.edge.key() for item in self.__edgeItems)
        for key, edge in wanted.items():
            if key not in existing:
                self.__createEdgeItem(edge)

    ## 只重收「以这个节点为目的地」的边（拔线 / 接线走这条路）。
    #
    # **没变就一个 item 都不动**：接一根 ScenePlug 的线，`plugInputChangedSignal` 会沿
    # 下游链**响 87 次**（子插口 pass-through 被重接），整条链都进了 `__dirtyEdges`，
    # 但画出来的边一条没变。收一遍便宜、拆了重建很贵，所以先比 key 再决定动不动。
    def __refreshEdgesForDestination(self, node, names):

        if node is None:
            return

        name = node.getName()

        existing = [
            item
            for item in self.__edgesByNode.get(name, [])
            if item.edge.dstNode.getName() == name
        ]
        wanted = edgesForDestination(self.__root, node, names)

        if set(item.edge.key() for item in existing) == set(
            edge.key() for edge in wanted
        ):
            return

        # 侧边参数名"连了就高亮"，所以线一变，**两头**的那两个 item 都要把这一项
        # 重算一遍（只刷这一项，不重建 item）。
        affected = {name}
        for item in existing:
            affected.add(item.edge.srcNode.getName())
        for edge in wanted:
            affected.add(edge.srcNode.getName())

        for item in existing:
            self.__removeEdgeItem(item)

        for edge in wanted:
            self.__createEdgeItem(edge)

        for affectedName in affected:
            affectedItem = self.__nodeItems.get(affectedName)
            if affectedItem is not None:
                affectedItem.refreshSideLabels()

    ## 给「从没摆过位置」的节点跑一遍原生自动布局。
    #
    # Box 内部的节点常常没有 `__uiPosition`，原生是在 `GraphEditor.__preRender` 里现算
    # （`unpositionedNodeGadgets()` → `positionNodes()` → `layoutNodes()`）。我们没有
    # preRender，不补这一步进 Box 就是一堆挤在一起的节点。和原生一样**不进撤销栈**。
    def __layoutUnpositionedNodes(self, graphGadget):

        if graphGadget is None:
            return

        nodes = [gadget.node() for gadget in graphGadget.unpositionedNodeGadgets()]
        if not nodes:
            return

        # mapToScene 只吃 QPoint（QPointF 会 TypeError）
        centre = self.__view.mapToScene(self.__view.viewport().rect().center())
        fallbackPosition = imath.V2f(
            centre.x() / PX_PER_UNIT, -centre.y() / PX_PER_UNIT
        )

        nodeSet = Gaffer.StandardSet(nodes)
        layout = graphGadget.getLayout()
        layout.positionNodes(graphGadget, nodeSet, fallbackPosition)
        layout.layoutNodes(graphGadget, nodeSet)

    ## QGraphicsView 会把可视区夹在 sceneRect 里。不留足余量，中键平移到内容边缘
    # 就被夹住，表现为「拖不动 / 移不自由」。
    def __updateSceneRect(self):

        rect = self.__scene.itemsBoundingRect()
        if rect.isNull():
            rect = QtCore.QRectF(-1, -1, 2, 2)

        rect = rect.adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN)

        # **`setSceneRect` 会让整个视口失效** —— 没变就别设（改一根线时它根本不会变）
        if rect == self.__scene.sceneRect():
            return

        self.__scene.setSceneRect(rect)

    ## 只挪 `__uiPosition` 变了的那几个节点，和**它们**的边。信号本来就报的是哪个
    # 节点 —— 一个标记管全图的话，拖完一个节点松手要把所有节点的位置插口读一遍、
    # 所有连线的路径重算一遍（2000 个节点的图上每次松手都这样）。
    def __updatePositions(self):

        names = self.__dirtyPositions
        self.__dirtyPositions = set()

        # 连线不用在这儿管：`item.setPos()` 会走 `itemChange( ItemPositionHasChanged )`
        # → `_nodeItemMoved`，只重算挂在那个节点上的边
        for name in names:

            item = self.__nodeItems.get(name)
            if item is not None:
                position = nodePosition(item.node)
                if position is not None:
                    target = QtCore.QPointF(
                        position.x * PX_PER_UNIT, -position.y * PX_PER_UNIT
                    )
                    if (target - item.pos()).manhattanLength() > 1e-4:
                        item.setPos(target)

            backdrop = self.__backdropItems.get(name)
            if backdrop is not None:
                center = backdropBound(backdrop.node)[0]
                backdrop.setPos(center.x * PX_PER_UNIT, -center.y * PX_PER_UNIT)

        self.__updateSceneRect()

    def __updateFocus(self):

        focus = self.scriptNode().getFocus()

        # **按节点身份比，不按名字**：Box 里外重名太常见（`in` / `out` / `Sphere`…），
        # 按名字比会在别的层上点出一个假的 focus 角标。
        for item in self.__nodeItems.values():
            item.setFocused(focus is not None and item.node.isSame(focus))

        self.__updateActiveState()

    ## focus 之后哪些东西「参与计算」—— 完全走原生那套 `ContextTracker`。
    #
    # 原生是**变暗不参与的**、不是给参与的加亮（`*::updateFromContextTracker`：
    # `isTracked()` 为假就画 `Style::DisabledState`）。
    #
    # 自己 BFS 上下游是**错的**：原生只算 focus 的**上游**，而且只算**当前 context
    # 真正走到的那条路**（Switch 没选中的支不算），只有 ContextTracker 算得对。
    # 它**异步**更新，要连 `changedSignal` 等它算完再刷一遍。
    def __contextTracker(self):

        if self.__tracker is None:
            self.__tracker = GafferUI.ContextTracker.acquireForFocus(self.scriptNode())
            self.__trackerConnection = self.__tracker.changedSignal().connect(
                Gaffer.WeakMethod(self.__contextTrackerChanged), scoped=True
            )

        return self.__tracker

    def __contextTrackerChanged(self, *unused):

        self.__updateActiveState()

    def __updateActiveState(self):

        tracker = self.__contextTracker()

        # **还在算的时候什么都别动**。`ContextTracker` 是异步的：刚点上 focus 那一下
        # 它还没算完，这时候问 `isTracked()` 全是 False —— 于是整张图先刷暗一帧、
        # 等它算完再亮回来，看着就是"点 focus 会闪一下"（只有一个节点时最明显）。
        # 算完它会发 `changedSignal`，那时候再刷。
        if tracker.updatePending():
            return

        target = tracker.targetNode()

        def tracked(thing):

            return target is None or tracker.isTracked(thing)

        emphasis = target is not None

        for item in self.__edgeItems:
            # 原生看的是**目标插口**（`m_dstNodule->plug()`），不是节点
            item.setWireActive(tracked(item.edge.dstPlug))
            item.setFocusEmphasis(emphasis)

        ## `enabled` 得靠 compute 才知道的那些节点，答案在 ContextTracker 手里
        ## （原生 `StandardNodeGadget::updateStrikeThroughState` 就是这么拿的）。
        ## 它没跟踪的返回 None —— 原生这时候什么都不画。
        def dynamicEnabled(node):

            if target is None or not tracker.isTracked(node):
                return None
            return tracker.isEnabled(node)

        for item in self.__nodeItems.values():
            item.setNodeActive(tracked(item.node))
            if item._enabled is None:
                item.setDynamicEnabled(dynamicEnabled(item.node))

    ## 走一遍完整的拖放（进入 → 移动到 position → 放下），返回有没有被处理。
    #
    # GUI 里这三步是 GafferUI 的 `_EventFilter` 按鼠标位置驱动的；这个方法是给**测试**
    # 和「外部想直接投一把」用的 —— position 是视口像素。
    def _performDrop(self, event, position):

        if not self._NetworkEditor__dragEnter(self, event):
            return False

        self._updateDragTarget(event, position)
        return bool(self._NetworkEditor__drop(self, event, position))

    # --- 从别的编辑器拖东西进来 ---
    #
    # GafferUI 的拖放**不走 Qt 的 QDrag**，是它自己按鼠标位置找目标控件、发
    # `dragEnter/dragMove/dragLeave/dropSignal`（`Widget.py` 的 `_EventFilter`）——
    # **不接这四个信号就一点反应都没有**。原生收四种：
    #
    #  - 场景路径（以 "/" 开头的 `StringVectorData`）落在节点上 → PathFilterUI 建 / 改
    #    PathFilter；落在空白上 → 跳到生成这个位置的那个节点。
    #  - 集合名 → SetFilterUI。节点 / 节点集合 → 换 root 并取景。
    #  - 文件路径 → **转发给原生 graphGadget** 建（扩展名→节点类型那张表是 startup
    #    里的私有变量），我们只负责把新节点摆到落点上。
    #
    # 落在节点上的两种也**优先转发给原生 NodeGadget 的信号** —— 那些 gadget 早被
    # `NodeGadget.instanceCreatedSignal` 挂上了 PathFilterUI / SetFilterUI，连第三方扩展
    # 注册的 drop 目标都一起有了。没人接才退回自己那份实现。

    ##########################################################################
    # 往外拖：中键按住节点拖到别的编辑器里去（原生同款手感）
    ##########################################################################

    ## 把 GafferUI 的全局事件过滤器补装到视图和它的 viewport 上。
    def __installDragSourceFilter(self):

        eventFilter = _gafferUIEventFilter()
        if eventFilter is None:
            return False

        self.__view.installEventFilter(eventFilter)
        self.__view.viewport().installEventFilter(eventFilter)
        return True

    ## 中键按在节点上：记一笔「按下」给 GafferUI 的拖放机器，接下来鼠标一动它就会来问
    # 我们要拖拽数据（`__dragBegin`）。返回 True 表示这一下我们接了（不再平移）。
    #
    # 为什么要自己记：`_EventFilter.__buttonPress` 靠 `buttonPressSignal` 的返回值决定
    # 「这次按下算不算数」，而**返回 True 会把 Qt 事件吃掉**，我们自己那套点选 / 拖动就
    # 全废了。所以只补它需要的那两个私有属性，别的一律不碰。
    def _beginNodeDragOut(self, item, qEvent):

        if item is None:
            return False

        eventFilter = _gafferUIEventFilter()
        if eventFilter is None:
            return False

        script = self.scriptNode()
        selection = [n for n in script.selection() if isinstance(n, Gaffer.Node)]
        selected = any(n.isSame(item.node) for n in selection)
        self.__dragOutNodes = selection if selected else [item.node]

        globalPosition = _globalPos(qEvent)
        origin = self.bound().min()
        x = globalPosition.x() - origin.x + 0.5
        y = globalPosition.y() - origin.y + 0.5

        buttonEvent = GafferUI.ButtonEvent(
            GafferUI.ButtonEvent.Buttons.Middle,
            GafferUI.ButtonEvent.Buttons.Middle,
            IECore.LineSegment3f(imath.V3f(x, y, 1), imath.V3f(x, y, 0)),
            0.0,
            GafferUI.ModifiableEvent.Modifiers.None_,
        )
        eventFilter._EventFilter__lastButtonPressWidget = weakref.ref(self)
        eventFilter._EventFilter__lastButtonPressEvent = buttonEvent

        return True

    ## GafferUI 来要拖拽数据了。
    #
    # 数据形状照抄原生 `GraphGadget::dragBegin` 的 `Sending` 那一路：拖的节点在选择里
    # 就给整个 `script.selection()`（别的编辑器认这个 Set），否则给那一个节点。
    def __dragBegin(self, widget, event):

        nodes = self.__dragOutNodes
        if not nodes:
            return None

        script = self.scriptNode()
        selection = script.selection()

        GafferUI.Pointer.setCurrent("nodes")

        if len(nodes) > 1 or (
            nodes
            and any(n.isSame(nodes[0]) for n in selection if isinstance(n, Gaffer.Node))
        ):
            return selection

        return nodes[0]

    def __dragEnd(self, widget, event):

        self.__dragOutNodes = None
        GafferUI.Pointer.setCurrent(None)
        return False

    ## 拖进来的东西看着能不能收。
    #
    # 收得宽一点是故意的：GafferUI 只在**目标控件变化时**发一次 dragEnter，之后就只有
    # dragMove 了 —— 这里要是按「当前落点」判，鼠标一进来落在空白上就被判死，之后移到
    # 节点上也没人管了。
    def __canAcceptDrag(self, event):

        # 自己中键拖出去的那一份别自己收（不然拖到一半划过自己的视图就开始"跳转层级"）
        if getattr(event, "sourceWidget", None) is self:
            return False

        data = event.data

        if isinstance(data, IECore.StringVectorData):
            return len(data) > 0

        if isinstance(data, Gaffer.Node):
            return bool(self.scriptNode().isAncestorOf(data))

        if isinstance(data, Gaffer.Set):
            nodes = [x for x in data if isinstance(x, Gaffer.Node)]
            return bool(nodes) and bool(self.scriptNode().isAncestorOf(nodes[0]))

        return False

    ## 拖拽当前位置（视口像素）。
    #
    # 不用 `event.line` —— 那个是相对**编辑器**的（含工具条那一条），我们要的是视图里的。
    def _dragViewPosition(self):

        return self.__view.viewport().mapFromGlobal(QtGui.QCursor.pos())

    def __dragEnter(self, widget, event):

        if event.sourceWidget is self:
            return False

        if not self.__canAcceptDrag(event):
            return False

        self.__dragActive = True
        self.__dragPointer = GafferUI.Pointer.getCurrent()
        self.__dragTargetNode = None
        self._updateDragTarget(event)
        return True

    def __dragMove(self, widget, event):

        if not self.__dragActive:
            return False

        self._updateDragTarget(event)
        return True

    ## 拖放这一套的位置一律可以显式传（视口像素），不传就问鼠标要 —— 无头测试里
    # 没有真鼠标，`QCursor.pos()` 永远是 (0,0)。
    def _dragPosition(self, position=None):

        return self._dragViewPosition() if position is None else position

    def __dragLeave(self, widget, event):

        if not self.__dragActive:
            return False

        self.__endDrag(event, leaving=True)
        return True

    def __drop(self, widget, event, position=None):

        if not self.__dragActive:
            return False

        target = self.__dragTargetNode
        try:
            if target is not None:
                handled = self.__forwardDragToNode(target, "drop", event)
                if not handled:
                    handled = self._dropPathsOnNode(target, event)
            else:
                handled = self._dropOnBackground(event, position)
        finally:
            # 拖放状态（指针、落点高亮）无论如何都要收干净
            self.__endDrag(event, leaving=False)

        return handled

    def __endDrag(self, event, leaving):

        if leaving and self.__dragTargetNode is not None:
            self.__forwardDragToNode(self.__dragTargetNode, "dragLeave", event)

        self.__dragTargetNode = None
        self.__dragActive = False
        self._setDropTarget(None)

        self.__setPointer(self.__dragPointer)
        self.__dragPointer = None

    ## 算出鼠标现在落在哪个节点上，该进该出通知到原生 gadget，并给出指针反馈。
    def _updateDragTarget(self, event, position=None):

        item = self.__view.nodeItemAt(self._dragPosition(position))
        name = item.nodeName if item is not None else None

        if name != self.__dragTargetNode:

            if self.__dragTargetNode is not None:
                self.__forwardDragToNode(self.__dragTargetNode, "dragLeave", event)
            self.__dragTargetNode = None

            if name is not None:
                # 原生处理器只有 dragEnter 返回过 True 才认这次拖拽，顺序不能省
                if (
                    self.__forwardDragToNode(name, "dragEnter", event)
                    or self._pathDropMode(name, event) is not None
                ):
                    self.__dragTargetNode = name

            self._setDropTarget(
                self.__nodeItems.get(self.__dragTargetNode)
                if self.__dragTargetNode is not None
                else None
            )

        if self.__dragTargetNode is not None:
            if not self.__forwardDragToNode(self.__dragTargetNode, "dragMove", event):
                mode = self._pathDropMode(self.__dragTargetNode, event) or "replace"
                # 指针名和原生 `PathFilterUI.__dragMove` 一样：notEditable 没有 Objects 后缀
                self.__setPointer(
                    "notEditable" if mode == "notEditable" else mode + "Objects"
                )
        elif self._locationDropData(event) is not None:
            self.__setPointer("targetObjects")
        elif self.__dropNodes(event.data):
            self.__setPointer("target")

    ## 换鼠标指针。拿不到图（自定义指针图找不着）就算了，别为这个把拖放整个搞崩。
    def __setPointer(self, name):

        GafferUI.Pointer.setCurrent(name)

    ## 把一个拖拽信号转发给原生的 NodeGadget（它身上挂着 PathFilterUI / SetFilterUI）。
    def __forwardDragToNode(self, name, which, event):

        item = self.__nodeItems.get(name)
        if item is None:
            return False

        graphGadget = self.__graphGadget()
        if graphGadget is None:
            return False

        nodeGadget = graphGadget.nodeGadget(item.node)
        if nodeGadget is None:
            return False

        # Gadget 的拖放信号用 `EventSignalCombiner`，handler 抛的异常它自己打印
        return bool(getattr(nodeGadget, which + "Signal")()(nodeGadget, event))

    ##########################################################################
    # 自己实现的那份退路（原生 NodeGadget 没接住时用）
    ##########################################################################

    ## 这些路径落在这个节点上会怎么处理："replace" / "add" / "remove" / "notEditable"，
    # 不该处理就 None。规则逐条照 `GafferSceneUI/PathFilterUI.py` 的 `__dropMode`。
    def _pathDropMode(self, name, event):

        if not isinstance(event.data, IECore.StringVectorData) or not len(event.data):
            return None
        if not all(p.startswith("/") for p in event.data):
            return None

        item = self.__nodeItems.get(name)
        if item is None:
            return None

        node = item.node
        pathsPlug = _pathsPlug(node)
        if pathsPlug is None:

            filterPlug = _filterPlug(node)
            if filterPlug is None:
                return None

            filter = (
                filterPlug.source().node()
                if filterPlug.getInput() is not None
                else None
            )
            if filter is None:
                return "replace" if _plugEditable(filterPlug) else "notEditable"
            elif not isinstance(filter, GafferScene.PathFilter):
                return None
            pathsPlug = _pathsPlug(filter)

        if pathsPlug is None or not _plugEditable(pathsPlug):
            return "notEditable"

        if event.modifiers & event.Modifiers.Shift:
            return "add"
        elif event.modifiers & event.Modifiers.Control:
            return "remove"
        return "replace"

    ## 路径落在节点上：没有 PathFilter 就建一个接上去，有就改它的 paths。
    def _dropPathsOnNode(self, name, event):

        mode = self._pathDropMode(name, event)
        if mode is None:
            return False
        if mode == "notEditable":
            return True

        node = self.__nodeItems[name].node
        pathsPlug = _pathsPlug(node)
        if pathsPlug is None:
            pathsPlug = _pathsPlug(_filterPlug(node).source().node())

        dropPaths = list(event.data)
        if mode == "replace" or pathsPlug is None:
            paths = sorted(set(dropPaths))
        else:
            paths = set(pathsPlug.getValue())
            if mode == "add":
                paths.update(dropPaths)
            else:
                paths.difference_update(dropPaths)
            paths = sorted(paths)

        with Gaffer.UndoScope(self.scriptNode()):

            if pathsPlug is None:
                pathFilter = GafferScene.PathFilter()
                node.parent().addChild(pathFilter)
                _filterPlug(node).setInput(pathFilter["out"])
                pathsPlug = pathFilter["paths"]

            pathsPlug.setValue(IECore.StringVectorData(paths))

        return True

    ##########################################################################
    # 落在空白处
    ##########################################################################

    ## 「一个场景位置」这种拖拽的来龙去脉（照 `startup/gui/graphEditor.py`
    # 的 `__dropLocationData`）。
    def _locationDropData(self, event):

        if (
            not isinstance(event.data, IECore.StringVectorData)
            or len(event.data) != 1
            or not event.data[0].startswith("/")
            or event.sourceWidget is None
        ):
            return None

        # 写在这儿：GafferSceneUI 只有 GUI 里才需要，别拖慢无头 import
        import GafferSceneUI

        scene = None
        sourceEditor = event.sourceWidget.ancestor(GafferUI.Editor)
        if isinstance(sourceEditor, GafferUI.Viewer):
            if isinstance(event.sourceGadget, GafferSceneUI.SceneGadget):
                scene = sourceEditor.view()["in"].getInput()
        elif isinstance(sourceEditor, GafferSceneUI.HierarchyView):
            scene = sourceEditor.scene()

        if scene is None:
            return None

        return {
            "path": event.data[0],
            "scene": scene,
            "context": sourceEditor.getContext(),
        }

    def _dropOnBackground(self, event, position=None):

        # 1) 单个场景位置 → 跳到生成它的那个节点（原生就是这个行为，不是建 PathFilter）
        locationData = self._locationDropData(event)
        if locationData is not None:

            # 照原生 `SceneHistoryUI.__editSourceNode` 直接算
            with locationData["context"]:
                source = GafferScene.SceneAlgo.source(
                    locationData["scene"], locationData["path"]
                )

            if source is not None:
                self._revealNodes([source.node()])
            return True

        # 2) 节点 / 节点集合 → 换 root 并取景
        nodes = self.__dropNodes(event.data)
        if nodes:
            self._revealNodes(nodes)
            return True

        # 3) 文件 → 让原生 graphGadget 去建节点，我们把它们摆到落点上
        return self.__dropFiles(event, position)

    ## 原生 `GraphEditor.__dropNodes`：只有同一个父级下的节点才收。
    def __dropNodes(self, dragData):

        if isinstance(dragData, Gaffer.Node) and self.scriptNode().isAncestorOf(
            dragData
        ):
            return [dragData]
        elif isinstance(dragData, Gaffer.Set):
            nodes = [x for x in dragData if isinstance(x, Gaffer.Node)]
            if nodes and self.scriptNode().isAncestorOf(nodes[0]):
                if len(set(n.parent() for n in nodes)) == 1:
                    return nodes

        return []

    ## 换到这些节点所在的那一层、把它们框进画面、并选中。
    def _revealNodes(self, nodes):

        nodes = [n for n in nodes if n is not None and n.parent() is not None]
        if not nodes:
            return False

        self.setRootNode(nodes[0].parent())

        items = [self.__nodeItems.get(n.getName()) for n in nodes]
        items = [i for i in items if i is not None]
        if items:
            self.__view.frameItems(items)

        selection = self.scriptNode().selection()
        selection.clear()
        for node in nodes:
            selection.add(node)

        return True

    def __dropFiles(self, event, position=None):

        graphGadget = self.__graphGadget()
        if graphGadget is None:
            return False

        before = set(n.getName() for n in self.__root.children(Gaffer.Node))

        # 建节点和重新摆位放进**同一个** UndoScope（Gaffer 只记最外层那个）——
        # 拆成两步的话第一次 Ctrl+Z 是把节点挪回原生按像素算出来的那个错位置
        with Gaffer.UndoScope(self.scriptNode()):

            if not bool(graphGadget.dragEnterSignal()(graphGadget, event)):
                return False
            if not bool(graphGadget.dropSignal()(graphGadget, event)):
                return False

            # 原生是拿 `event.line` 当图坐标用的，而我们转过去的 line 是像素 ——
            # 位置肯定不对，所以新建出来的节点自己重新摆一遍
            new = [
                n
                for n in self.__root.children(Gaffer.Node)
                if n.getName() not in before
            ]
            if new:
                scenePos = self.__view.mapToScene(self._dragPosition(position))
                position = imath.V2f(
                    scenePos.x() / PX_PER_UNIT, -scenePos.y() / PX_PER_UNIT
                )
                for node in new:
                    setNodePosition(node, imath.V2f(position))
                    position.x += nodeSizeUnits(node, graphGadget)[0] + 2.0

        return True

    ##########################################################################
    # 拖动时自动对齐
    ##########################################################################

    def getSnapEnabled(self):

        return self.__snapEnabled

    def setSnapEnabled(self, enabled):

        self.__snapEnabled = bool(enabled)
        # 程序里改开关也要让按钮跟上（按钮自己 toggled 回调进来时这里是空操作）
        self.__snapButton.setChecked(self.__snapEnabled)
        if not self.__snapEnabled:
            self._clearSnapGuides()

    ## 现在亮着的对齐参考线，[ ( "v" | "h", 坐标, 起点, 终点 ), … ]（scene 坐标）。
    def snapGuides(self):

        return self.__snapGuides

    def _clearSnapGuides(self):

        if not self.__snapGuides:
            return

        self.__snapGuides = []
        self.__view.viewport().update()

    ## 拖动中的节点「即将去到的位置」，需要的话吸到和最近那个节点对齐的位置上。
    #
    # **照 Houdini 那套**：只在 `SNAP_RANGE` 这个半径里挑**一个**参照 —— 范围内
    # 「能横平竖直对上」（某个轴的差在 `SNAP_DISTANCE` 之内）的节点里取**最近**那个，
    # 然后只吸**一个轴**：差得少的那个轴归零，两个节点于是要么站成一条竖列、
    # 要么排成一条横行。「x 吸最近的、y 吸最近的」的话，两个轴可能来自**两个不同**
    # 节点、而且完全不管有多远 —— 大图上经常被视野外的节点拽着走。
    #
    # 只在**单个节点**拖动时生效 —— 多选拖动时每个 item 都会各自收到一次
    # `ItemPositionChange`，各吸各的会把这一组的相对位置搅乱。
    def _snapNodePosition(self, item, position):

        if not self.__snapEnabled or not self.__view.isDraggingNodes():
            return position

        selected = [
            i
            for i in self.__scene.selectedItems()
            if isinstance(i, (_NodeItem, _BackdropItem))
        ]
        if len(selected) > 1:
            return position

        reference = self.__snapReference(item, position)

        guides = []
        result = QtCore.QPointF(position)

        if reference is not None:

            other, dx, dy = reference

            # 差得少的那个轴归零：上下摆着的吸 x（站成竖列），左右摆着的吸 y（排成横行）
            if abs(dx) <= abs(dy):
                result.setX(other.pos().x())
                guides.append(self.__snapGuide("v", item, other, result))
            else:
                result.setY(other.pos().y())
                guides.append(self.__snapGuide("h", item, other, result))

        if guides != self.__snapGuides:
            self.__snapGuides = guides
            self.__view.viewport().update()

        return result

    ## 范围内「能横平竖直对上」的节点里最近的那个，返回 ( item, dx, dy )（没有则 None）。
    def __snapReference(self, item, position):

        best = None

        # 只问 `SNAP_RANGE` 那一圈里的 item（走 scene 的空间索引），别每帧扫全图
        probe = QtCore.QRectF(
            position.x() - SNAP_RANGE,
            position.y() - SNAP_RANGE,
            SNAP_RANGE * 2.0,
            SNAP_RANGE * 2.0,
        )
        for other in self.__scene.items(probe):
            if not isinstance(other, _NodeItem) or other.nodeName == item.nodeName:
                continue

            dx = other.pos().x() - position.x()
            dy = other.pos().y() - position.y()

            distance = math.hypot(dx, dy)
            if distance > SNAP_RANGE:
                continue  # 手边以外的节点一概不参与

            if min(abs(dx), abs(dy)) > SNAP_DISTANCE:
                continue  # 两个轴都差得远，跟它对不成横平竖直

            if best is None or distance < best[0]:
                best = (distance, other, dx, dy)

        return None if best is None else (best[1], best[2], best[3])

    ## 一条参考线：`( "v" | "h", 坐标, 起点, 终点 )`。**只画在两个节点之间**
    # （两头各伸出一点），一眼看出是"和谁对齐了"，不像拉满整个视口那样没有指向。
    @staticmethod
    def __snapGuide(orientation, item, other, position):

        if orientation == "v":
            coordinate = other.pos().x()
            half, otherHalf = item._height / 2.0, other._height / 2.0
            centre, otherCentre = position.y(), other.pos().y()
        else:
            coordinate = other.pos().y()
            half, otherHalf = item._width / 2.0, other._width / 2.0
            centre, otherCentre = position.x(), other.pos().x()

        start = min(centre - half, otherCentre - otherHalf) - SNAP_GUIDE_OVERSHOOT
        end = max(centre + half, otherCentre + otherHalf) + SNAP_GUIDE_OVERSHOOT

        return (orientation, coordinate, start, end)

    ## Houdini 的 P 键：在光标边上弹一块**纯参数面板**（没有头部 / 面包屑 / 工具条 /
    # 齿轮，只有参数本身）。再按一次 P、或者面板里按 Esc 关掉。
    #
    # 参数面板是**可选的另一个扩展**（Python 模块 `parameterEditor`，提供
    # `popupParameters( node, anchor )`）。没装就不接这个键。
    def _popupParameters(self):

        if self.__closeParameterPopup():
            return True  # 已经开着 → 这一下 P 是关掉它

        # 按键时才找：扩展是一个一个加路径、跑 startup 的，networkEditor 的 startup
        # 跑的时候 parameterEditor 的 python/ 可能还没上 sys.path。
        if importlib.util.find_spec("parameterEditor") is None:
            return False

        node = self.__parameterPopupNode()
        if node is None:
            return False

        import parameterEditor

        # **停靠在节点图视口的右上角**（Houdini 的 P 面板就在网络视图右上角），
        # 不是跟着鼠标弹 —— 位置固定才能"按 P 看一眼、再按 P 收起"，不用满屏找它。
        viewport = self.__view.viewport()
        anchor = QtCore.QRect(
            viewport.mapToGlobal(QtCore.QPoint(0, 0)), viewport.size()
        )

        # 面板**跟着选择走**，所以按 P 的时候先把这个节点变成"当前选中" ——
        # 不然光标底下是 A、选中的是 B，弹出来给的是 B 的参数。**已经选上了就不动**
        # （别把用户的多选压成单选）。
        selection = self.scriptNode().selection()
        if not selection.contains(node):
            selection.clear()
            selection.add(node)

        self.__parameterPopup = parameterEditor.popupParameters(node, anchor=anchor)
        return self.__parameterPopup is not None

    ## P 键弹出来的那块参数面板（没开着返回 None）。
    def parameterPopup(self):

        return self.__parameterPopup

    ## 开着就关掉并返回 True。
    def __closeParameterPopup(self):

        popup = self.__parameterPopup
        self.__parameterPopup = None

        if popup is None:
            return False

        try:
            if not popup.getVisible():
                return False
            popup.setVisible(False)
        except RuntimeError:
            return False  # Qt 那边已经销毁了

        return True

    ## P 键该看哪个节点：光标底下那个 → focus → 最后选中的那个。
    def __parameterPopupNode(self):

        viewPosition = self.__view.viewport().mapFromGlobal(QtGui.QCursor.pos())
        if self.__view.viewport().rect().contains(viewPosition):
            item = self.__view.nodeItemAt(viewPosition)
            if item is not None:
                return item.node

        focus = self.scriptNode().getFocus()
        if (
            focus is not None
            and self.__root is not None
            and (focus.isSame(self.__root) or self.__root.isAncestorOf(focus))
        ):
            return focus

        nodes = self.__selectedNodes()
        return nodes[-1] if nodes else None

    ## 工具条右边那行小字提示（None = 恢复成「几个节点 · 几条连线」）。
    ## 状态栏临时提示（划线模式那种）。None = 回到「几个节点 · 几根线」。
    # 提示记下来，图更新时刷计数不会把还在进行的模式提示冲掉。
    def _setStatusHint(self, text):

        self.__statusHint = text or None
        self.__refreshStatus()

    def __refreshStatus(self):

        self.__statusLabel.setText(
            self.__statusHint
            or "%d nodes · %d connections"
            % (len(self.__nodeItems), len(self.__edgeItems))
        )

    ## 取消所有连线的悬停高亮（中键平移开始时调 —— 那会儿 Qt 不再派发 hover 事件）。
    def _clearWireHover(self):

        for item in self.__edgeItems:
            item.clearHover()

    ## 节点被拖动时只更新它自己那几条线，不动别的。
    def _nodeItemMoved(self, item):

        for edge in self.__edgesByNode.get(item.nodeName, []):
            edge.updateGeometry(self.__wireStyle)

    ##########################################################################
    # 选择同步（双向，diff 式）
    ##########################################################################

    ## 面板已经被销毁之后（换布局 / 关掉这一格），Qt 的信号还会再送进来一两次，
    ## 而底层 C++ 的 QGraphicsScene 早没了 —— 碰它就是
    ## `RuntimeError: Internal C++ object (QGraphicsScene) already deleted`
    # 那一类。
    ## 选择同步这几个入口统一挡一下。
    def __sceneItems(self):

        try:
            return [i for i in self.__scene.selectedItems()]
        except RuntimeError:
            return None

    ## 选中集合里**这一层**的节点（名字在一层里唯一，别的层同名的不算 —— 每个 Box
    # 里都有叫 `in` / `out` 的 BoxIn / BoxOut，按裸名字比会把别层选中的当成这层的）。
    def __selectedInRoot(self, selection):

        root = self.__root
        names = set()
        foreign = []
        for node in selection:
            if not isinstance(node, Gaffer.Node):
                continue
            parent = node.parent()
            if parent is not None and root.isSame(parent):
                names.add(node.getName())
            else:
                foreign.append(node)
        return names, foreign

    def __updateSelection(self):

        selected, _ = self.__selectedInRoot(self.scriptNode().selection())

        if self.__sceneItems() is None:
            return

        self.__updatingSelection = True
        self.__scene.blockSignals(True)
        try:
            # 只改真正变了的，避免 N 次无谓重绘
            for name, item in list(self.__nodeItems.items()) + list(
                self.__backdropItems.items()
            ):
                want = name in selected
                if item.isSelected() != want:
                    item.setSelected(want)
        finally:
            self.__scene.blockSignals(False)
            self.__updatingSelection = False

    def __sceneSelectionChanged(self):

        # Qt 自己在按下 / 松手时改的那几下不算数（见 `_setSelectionSyncSuspended`）
        if self.__selectionSyncSuspended:
            return

        # 拖框过程中不写回 script —— 每帧 clear + add 会让 NodeEditor / Viewer
        # 把所有节点跳一遍，非常卡。松手时由 `_flushSelectionToScript` 统一写。
        #
        # 这里就在 Qt 的 selectionChanged 回调里，直接问 Qt。
        # （`GafferUI.Widget.currentButtons()` 是同一件事的包装，还要多转一次枚举。）
        if self.__updatingSelection:
            return
        if QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton:
            return

        self._flushSelectionToScript()

    def _flushSelectionToScript(self):

        if self.__updatingSelection or self.__selectionSyncSuspended:
            return

        items = self.__sceneItems()
        if items is None:
            return  # 面板已经销毁，这一下信号不用管了

        wanted = []
        for item in items:
            if isinstance(item, (_NodeItem, _BackdropItem)):
                wanted.append(item.node)

        wantedNames = set(n.getName() for n in wanted)  # 都在这一层，名字唯一

        selection = self.scriptNode().selection()
        # 别的层里选中的节点一律算"要清掉的"（原生点一下就是 `selection()->clear()`），
        # 但判"没变化就别写"时得把它们算进去，不然选着别层同名节点时这里会漏写
        currentNames, foreign = self.__selectedInRoot(selection)

        if wantedNames == currentNames and not foreign:
            return

        # **diff 式**：只删该删的、只加该加的。整体 clear + add 会为每个节点各发一次
        # memberRemoved/memberAdded，观察者（NodeEditor / Viewer / HierarchyView）
        # 全都要跟着抖一遍。
        self.__updatingSelection = True
        try:
            for node in foreign:
                selection.remove(node)
            for node in list(selection):
                if isinstance(node, Gaffer.Node) and node.getName() not in wantedNames:
                    selection.remove(node)
            for node in wanted:
                if node.getName() not in currentNames:
                    selection.add(node)
        finally:
            self.__updatingSelection = False

    ##########################################################################
    # 点选 / 框选（语义逐条抄原生 GraphGadget）
    ##########################################################################

    ## 左键点在 `item` 上时怎么改选择。返回 True 表示「已经处理完，别再拖动了」。
    def _selectClicked(self, item, modifiers):

        self._clearEdgeSelection()  # 选节点就不再选着线

        shift = bool(modifiers & QtCore.Qt.ShiftModifier)
        control = bool(modifiers & QtCore.Qt.ControlModifier)
        alt = bool(modifiers & QtCore.Qt.AltModifier)

        affected = [item]

        # Backdrop：连它框住的节点一起（Ctrl 时只动它自己），和原生一样
        if isinstance(item, _BackdropItem) and not control:
            affected.extend(self.__itemsFramedBy(item))

        # Alt+Shift 连上游、Alt+Ctrl 连下游
        if alt and (shift or control) and isinstance(item, _NodeItem):
            affected.extend(
                self.__connectedItems(
                    item,
                    Gaffer.Plug.Direction.In if shift else Gaffer.Plug.Direction.Out,
                )
            )

        consumed = False
        self.__scene.blockSignals(True)
        try:
            if item.isSelected():
                if control:
                    for other in affected:
                        other.setSelected(False)
                    consumed = True
                # 已选中又没按 Ctrl：什么都不动，好让你拖着整组走
            else:
                if not control and not shift:
                    for other in self.__scene.selectedItems():
                        other.setSelected(False)
                for other in affected:
                    other.setSelected(True)
        finally:
            self.__scene.blockSignals(False)

        self._flushSelectionToScript()
        return consumed

    ##########################################################################
    # 连线的选中（Gaffer 的 `script.selection()` 只装节点，所以自己管一份）
    ##########################################################################

    ## 点在一条连线上。Shift = 加选，别的情况先清空。
    def _selectEdgeClicked(self, edgeItem, modifiers=QtCore.Qt.NoModifier):

        shift = bool(modifiers & QtCore.Qt.ShiftModifier)
        control = bool(modifiers & QtCore.Qt.ControlModifier)

        if control and edgeItem.isWireSelected():
            edgeItem.setWireSelected(False)
            return

        if not shift and not control:
            # 选线就清掉节点选择（反过来点节点也会清掉线选择）—— 免得 Delete 的时候
            # 分不清到底要删哪个
            self._clearEdgeSelection()
            self._clearSelection()

        edgeItem.setWireSelected(True)

    ## 按名字取一个节点 item（视图那边改接时要用）。
    def _nodeItem(self, name):

        return self.__nodeItems.get(name)

    def selectedEdges(self):

        return [item for item in self.__edgeItems if item.isWireSelected()]

    def _clearEdgeSelection(self):

        for item in self.__edgeItems:
            item.setWireSelected(False)

    ## 现在 scene 里选中的那些 item（节点 / Backdrop）。
    def _selectedSceneItems(self):

        items = self.__sceneItems()
        if items is None:
            return []

        return [item for item in items if isinstance(item, (_NodeItem, _BackdropItem))]

    ## 「Qt 正在自作主张改选择」期间挂起写回 script。
    #
    # 基类会在按下 / 松手两处自作主张改选择（空白按下 `clearSelection()`、松手时
    # 「没移动就只留一个」），我们随后 `_restoreSceneSelection` 兜回来。中间这一来一回
    # **不能写进 script**：写回是 diff 式的，`remove(A)` 再 `add(A)` 会让 A 变成 node set
    # 里**最后加进来**的那个 —— 跟着 node set 的面板只显示 `_lastAddedNode()`，
    # 于是 Shift 加选后「先跳到新节点又弹回旧的」。挂起期间只动 scene，兜完统一 flush。
    def _setSelectionSyncSuspended(self, suspended):

        self.__selectionSyncSuspended = bool(suspended)

    ## 把 scene 的选择对回给定的 item 列表（Qt 在松手时会自己改选择，用它兜回来）。
    def _restoreSceneSelection(self, items):

        if self.__sceneItems() is None:
            return

        wanted = set(id(item) for item in items)
        current = self._selectedSceneItems()
        if set(id(item) for item in current) == wanted:
            return

        self.__scene.blockSignals(True)
        try:
            for item in current:
                if id(item) not in wanted:
                    item.setSelected(False)
            for item in items:
                try:
                    item.setSelected(True)
                except RuntimeError:
                    pass  # item 可能已经被重建掉了
        finally:
            self.__scene.blockSignals(False)

        self._flushSelectionToScript()

    ## 空白处按下（没按修饰键）时清空选择。
    def _clearSelection(self):

        items = self.__sceneItems()
        if items is None:
            return

        self.__scene.blockSignals(True)
        try:
            for item in items:
                item.setSelected(False)
        finally:
            self.__scene.blockSignals(False)

        self._flushSelectionToScript()

    ## 框选收尾。`sceneRect` 是框出来的区域，`remove=True` = 按着 Ctrl（减选）。
    #
    # ⚠️ **擦到一部分就算选中，故意不跟原生**：原生要求整个节点都在框里
    # （`GraphGadget::updateDragSelection` 的 `boxContains`），一大张图上得把框拉得很大、
    # 还常常"扫过去了却没选上"。相交即选是 Nuke / Houdini / Maya 的手感。
    def _applyBandSelection(self, sceneRect, remove=False):

        if self.__sceneItems() is None:
            return

        self.__scene.blockSignals(True)
        try:
            # **节点：相交就算**（原生要求完全框住，这条故意不跟原生）。
            for item in self.__nodeItems.values():
                if sceneRect.intersects(item.selectionRect()):
                    item.setSelected(not remove)

            # **Backdrop：照原生要求整个框住**。它盖着一大片，相交就算的话
            # 「在 Backdrop 上框选几个节点」会顺手把 Backdrop 一起选上 ——
            # 接着一拖就把整组都搬走了。
            for item in self.__backdropItems.values():
                if sceneRect.contains(item.selectionRect()):
                    item.setSelected(not remove)
        finally:
            self.__scene.blockSignals(False)

        self._flushSelectionToScript()

    ## Backdrop 框住了哪些节点。
    def __itemsFramedBy(self, backdropItem):

        rect = backdropItem.selectionRect()
        return [
            item
            for item in self.__nodeItems.values()
            if rect.contains(item.selectionRect())
        ]

    ## 顺着连线走，收集上游（In）或下游（Out）的所有节点。
    def __connectedItems(self, item, direction):

        result = []
        seen = set([item.nodeName])
        queue = [item.nodeName]

        while queue:
            name = queue.pop()
            for edge in self.__edgesByNode.get(name, []):
                if direction == Gaffer.Plug.Direction.In:
                    other = (
                        edge.edge.srcNode.getName()
                        if edge.edge.dstNode.getName() == name
                        else None
                    )
                else:
                    other = (
                        edge.edge.dstNode.getName()
                        if edge.edge.srcNode.getName() == name
                        else None
                    )
                if other is None or other in seen:
                    continue
                seen.add(other)
                queue.append(other)
                if other in self.__nodeItems:
                    result.append(self.__nodeItems[other])

        return result

    ##########################################################################
    # 接口悬停
    ##########################################################################

    ## 鼠标现在停在哪个接口圆点上（原生：圆点半径翻倍 + HighlightColor）。
    def _setHoveredNodule(self, item, plug):

        name = item.nodeName if (item is not None and plug is not None) else None

        if self.__hoveredNoduleItem is not None and self.__hoveredNoduleItem != name:
            previous = self.__nodeItems.get(self.__hoveredNoduleItem)
            if previous is not None:
                previous.setHoveredNodule(None)

        self.__hoveredNoduleItem = name
        if name is not None:
            item.setHoveredNodule(plug)

    ## 鼠标停在哪个分栏的折叠三角上（只影响悬停小框）。
    def _setHoveredSection(self, item, side, section):

        name = item.nodeName if (item is not None and section is not None) else None

        if self.__hoveredSectionItem is not None and self.__hoveredSectionItem != name:
            previous = self.__nodeItems.get(self.__hoveredSectionItem)
            if previous is not None:
                previous.setHoveredSection(None, None)

        self.__hoveredSectionItem = name
        if name is not None:
            item.setHoveredSection(side, section)

    ## 拖连线时鼠标落在哪个节点上（整块卡片描边高亮）。
    #
    # `fromPlug` 给了的话，顺手把这个节点上**接得上的那几个接口的名字**显示出来
    # （原生 `StandardNodeGadget::dragEnter` 里就是这么干的："Display the labels for
    # all the compatible nodules"）。
    def _setDropTarget(self, item, fromPlug=None):

        name = item.nodeName if item is not None else None
        if name == self.__dropTargetItem:
            return

        if self.__dropTargetItem is not None:
            previous = self.__nodeItems.get(self.__dropTargetItem)
            if previous is not None:
                try:
                    previous.setDropTarget(False)
                    previous.setDragLabelPlugs(None)
                except RuntimeError:
                    pass

        self.__dropTargetItem = name
        if item is not None:
            item.setDropTarget(True)
            item.setDragLabelPlugs(
                candidatePlugs(item.node, fromPlug) if fromPlug is not None else None
            )

    ## 鼠标现在停在哪个 `+` 上。
    def _setHoveredAdder(self, item, section):

        name = item.nodeName if (item is not None and section is not None) else None

        if self.__hoveredAdderItem is not None and self.__hoveredAdderItem != name:
            previous = self.__nodeItems.get(self.__hoveredAdderItem)
            if previous is not None:
                previous.setHoveredAdder(None)

        self.__hoveredAdderItem = name
        if name is not None:
            item.setHoveredAdder(section)

    ## 连线丢到 `+` 上：新建 / 提升出一个插口再接上（原生 PlugAdder 的活）。
    #
    # 原生那些 PlugAdder 在 C++ 匿名命名空间里没绑 Python，只能照着重写：
    # `Gaffer.Box` → 提升出 BoxIn / BoxOut（`BoxUI.cpp`）；**插口级注册在 ArrayPlug 上的**
    # （NameSwitch / Collect 的 `in`）→ `resize( n + 1 )` 出一路新的再接
    # （`NameSwitchUI.cpp` 的 `createConnection`）。其余返回 False，调用方退回
    # 「拖到节点身上自动挑插口」那条老路。
    def _createPromotedConnection(self, node, section, fromPlug):

        if self.readOnly() or Gaffer.MetadataAlgo.readOnly(node):
            return False
        if fromPlug is None or fromPlug.node() is None or fromPlug.node().isSame(node):
            return False

        # **还没 setup 的节点**（刚从 Tab 建出来的 Switch / NameSwitch / Loop /
        # ContextProcessor / EditScope / BoxIn / BoxOut）：那个 `+` 背后是
        # `setup( endpoint )`，不是"加一路"也不是"显示某个藏起来的插口"。
        # 这条要排在最前面 —— EditScope 是 Box 的子类，走 Box 那条就错了。
        if self.__setupFromAdder(node, section, fromPlug):
            return True

        if not isinstance(node, Gaffer.Box):
            # 材质 / ShaderTweaks 那种：`+` 背后是**一堆藏起来的插口**，
            # 原生的做法是弹一个菜单让你挑一个（`PlugAdder::plugMenuSignal`，
            # 处理函数在 `GafferUI/_PlugAdder.py`），挑中的那个显示出来再接上。
            if self.__connectToHiddenPlug(node, section, fromPlug):
                return True
            return self.__growArrayPlug(node, section, fromPlug)

        with Gaffer.UndoScope(self.scriptNode()):

            inward = fromPlug.direction() == Gaffer.Plug.Direction.In
            boxIO = Gaffer.BoxOut() if inward else Gaffer.BoxIn()

            node.addChild(boxIO)
            boxIO.setup(fromPlug)

            if inward:
                fromPlug.setInput(boxIO.promotedPlug())
            else:
                boxIO.promotedPlug().setInput(fromPlug)

            # 提升出来的那半挂在丢下去的那条边上，内部那半挂对边
            Gaffer.Metadata.registerValue(
                boxIO.promotedPlug(), "noduleLayout:section", section
            )
            Gaffer.Metadata.registerValue(
                boxIO.plug(), "noduleLayout:section", oppositeSection(section)
            )

        return True

    ## 把连线丢到材质节点的 `+` 上：列出**藏起来又接得上**的插口让你挑，
    # 挑中的显示出来（`noduleLayout:visible = True`）再接上。
    #
    # 照原生 `PlugAdder` 的路子：一个候选就直接用，多个就弹菜单
    # （原生 `_PlugAdder.__plugMenu` 弹的是模态 QMenu，我们用自己的面板，一样的意思）。
    def __connectToHiddenPlug(self, node, section, fromPlug):

        candidates = self.__hiddenConnectablePlugs(node, section, fromPlug)
        if not candidates:
            return False

        if len(candidates) == 1:
            self.__showAndConnect(candidates[0], fromPlug)
            return True

        entries = [
            (
                noduleLabel(plug),
                plug.relativeName(node).rpartition(".")[0],
                plug.relativeName(node),
                _PanelCommand(functools.partial(self.__showAndConnect, plug, fromPlug)),
            )
            for plug in candidates
        ]
        self._showPanel(
            entries,
            lambda item: item.command() if item.command is not None else None,
            title="Connect To Parameter",
        )
        return True

    ## 这个节点上**藏起来的、能接 `fromPlug` 的**插口有哪些。
    def __hiddenConnectablePlugs(self, node, section, fromPlug):

        outward = fromPlug.direction() == Gaffer.Plug.Direction.Out

        result = []
        stack = list(node.children(Gaffer.Plug))
        while stack:

            plug = stack.pop(0)

            if plug.getName().startswith(_internalPlugPrefix):
                continue

            visible = Gaffer.Metadata.value(plug, "noduleLayout:visible")
            hidden = visible is not None and not visible
            noduleType = Gaffer.Metadata.value(plug, "nodule:type")

            if (
                hidden
                and not Gaffer.MetadataAlgo.readOnly(plug)
                and (noduleType is None or noduleType != "")
                and canConnect(
                    fromPlug if outward else plug, plug if outward else fromPlug
                )
            ):
                result.append(plug)
                continue  # 命中就不往下钻了（原生 RecursiveIterator 也是 prune）

            stack.extend(plug.children(Gaffer.Plug))

        return result

    ## 让一个藏起来的插口显示出来，然后接上。两件事一步撤销。
    def __showAndConnect(self, plug, fromPlug):

        outward = fromPlug.direction() == Gaffer.Plug.Direction.Out
        pair = (fromPlug, plug) if outward else (plug, fromPlug)
        if not canConnect(*pair):
            return False

        with Gaffer.UndoScope(self.scriptNode()):
            Gaffer.Metadata.registerValue(plug, "noduleLayout:visible", True)
            self.__connect(*pair)

        return True

    ## 这条边上的 `+` 是注册在哪个 ArrayPlug 上的（NameSwitch / Collect 的 `in`）。
    ## 丢到「还没 setup 的节点」那个 `+` 上：先 `setup( endpoint )` 把插口造出来再接。
    #
    # 逐条照原生那几个 PlugAdder 的 `createConnection`：Switch / NameSwitch
    # `SwitchUI.cpp:79`（NameSwitch 接 `in[0].value`）、Loop `LoopUI.cpp:83`（还要写
    # next / previous）、ContextProcessor `ContextProcessorUI.cpp:71`、EditScope
    # `EditScopeUI.cpp:91`、BoxIn / BoxOut `BoxIONodeGadget.cpp:95`（名字取自对面插口）。
    def __setupFromAdder(self, node, section, fromPlug):

        if adderSetupComplete(node):
            return False

        setup = getattr(node, "setup", None)
        if setup is None:
            return False

        # `PlugAdder::canCreateConnection`：CompoundNodule 那种插口不收
        if Gaffer.Metadata.value(fromPlug, "nodule:type") == "GafferUI::CompoundNodule":
            return False

        outward = fromPlug.direction() == Gaffer.Plug.Direction.Out

        with Gaffer.UndoScope(self.scriptNode()):
            if isinstance(node, Gaffer.BoxIO):
                return self.__setupBoxIO(node, section, fromPlug, setup)
            return self.__setupProcessor(node, section, fromPlug, setup, outward)

    ## `PlugAdder::applyEdgeMetadata`：造出来的插口挂在丢下去的那条边上，对家挂对边。
    def __applyEdgeSection(self, plug, section, opposite=False):

        if plug is not None:
            Gaffer.Metadata.registerValue(
                plug,
                "noduleLayout:section",
                oppositeSection(section) if opposite else section,
            )

    ## BoxIn / BoxOut：`setup()` 之后自己那面和提升出来的那面各挂一边，再接上线。
    def __setupBoxIO(self, node, section, fromPlug, setup):

        # 原生拿对面插口的相对名当 BoxIO 的名字（`.` 换成 `_`）
        node["name"].setValue(fromPlug.relativeName(fromPlug.node()).replace(".", "_"))

        setup(fromPlug)

        self.__applyEdgeSection(node.plug(), section)
        if isinstance(node, Gaffer.BoxOut):
            self.__applyEdgeSection(node.getChild("passThrough"), section)
        if node.promotedPlug() is not None:
            self.__applyEdgeSection(node.promotedPlug(), section, opposite=True)

        # ⚠️ **`BoxIO.direction()` 到 1.7.1.0 仍然没绑 Python**（C++ 有，实测 hasattr
        # 为假）—— 按类型分：BoxIn 提升出来的是输入、BoxOut 是输出。
        if isinstance(node, Gaffer.BoxIn):
            fromPlug.setInput(node.plug())
        else:
            node.plug().setInput(fromPlug)

        return True

    ## Switch / NameSwitch / Loop / ContextProcessor / EditScope：`setup()` 之后
    # 按拖过来的方向接 in 或 out，两边的插口各挂一条边。
    def __setupProcessor(self, node, section, fromPlug, setup, outward):

        setup(fromPlug)

        # `inPlug()` / `outPlug()` 到 1.7.1.0 也没绑 Python，一律按名字取
        inPlug = node.getChild("in")
        outPlug = node.getChild("out")

        if isinstance(node, Gaffer.NameSwitch):
            # 一路输入是 NameValuePlug，接的是它的 `value`
            target = (
                inPlug[0].getChild("value")
                if inPlug is not None and len(inPlug)
                else None
            )
            source = outPlug.getChild("value") if outPlug is not None else None
        else:
            target = (
                inPlug[0]
                if isinstance(inPlug, Gaffer.ArrayPlug) and len(inPlug)
                else inPlug
            )
            source = outPlug

        if outward:
            if target is None:
                return False
            target.setInput(fromPlug)
        else:
            if source is None:
                return False
            fromPlug.setInput(source)

        self.__applyEdgeSection(inPlug, section, opposite=not outward)
        self.__applyEdgeSection(outPlug, section, opposite=outward)

        # Loop 还有 next / previous 两个，跟 in / out 各站一边
        if isinstance(node, Gaffer.Loop):
            self.__applyEdgeSection(
                node.getChild("next"), section, opposite=not outward
            )
            self.__applyEdgeSection(
                node.getChild("previous"), section, opposite=outward
            )

        return True

    def __adderArrayPlug(self, node, section):

        for plug in node.children(Gaffer.Plug):
            if not isinstance(plug, Gaffer.ArrayPlug) or not hasNodule(plug):
                continue
            if plugSection(plug) != section:
                continue
            if _metadataAdderSections(plug, section):
                return plug

        return None

    ## 丢到 ArrayPlug 上那个 `+`：接一路。
    #
    # 照原生（`ArrayPlugUI.cpp:93` / `NameSwitchUI.cpp:92`）一律 `resize( n + 1 )`
    # 然后接**新**那路，不复用空槽（细节见函数体里那段注释）。
    def __growArrayPlug(self, node, section, fromPlug):

        arrayPlug = self.__adderArrayPlug(node, section)
        if arrayPlug is None:
            return False

        ## 一路输入真正要接的那个插口（NameSwitch 的一路是 NameValuePlug，接的是 `value`）
        def slotPlug(slot):

            value = slot.getChild("value")
            return value if value is not None else slot

        size = len(arrayPlug.children())
        if not size:
            return False

        # **照原生 `NameSwitchPlugAdder::createConnection`**
        # （`src/GafferUI/NameSwitchUI.cpp`）：
        # 一律 `resize( s + 1 )` 接**新那路** `in[s]` —— 绝不复用任何空槽、也不判断
        # default 空不空：default / 第二路空着时丢 `+` 也是长新路。
        maxSize = arrayPlug.maxSize()
        if maxSize and size >= maxSize:
            return False

        with Gaffer.UndoScope(self.scriptNode()):

            arrayPlug.resize(size + 1)
            newPlug = arrayPlug[size]  # ArrayPlug 按下标取，`getChild()` 只收名字

            # NameSwitch 一路输入是 NameValuePlug，要接的是它的 `value`
            target = slotPlug(newPlug)

            if fromPlug.direction() == Gaffer.Plug.Direction.In:
                fromPlug.setInput(target)
            else:
                target.setInput(fromPlug)

            # 原生：不是 `NameSwitch.in` 本体（而是提升出来的副本）时，元数据继承不到，
            # 得把上一路的显式拷过来
            if not isinstance(node, Gaffer.NameSwitch) or not arrayPlug.isSame(
                node.getChild("in")
            ):
                Gaffer.MetadataAlgo.copy(arrayPlug[size - 1], newPlug)

        return True

    ##########################################################################
    # 快捷键转发
    ##########################################################################

    ## 把我们没接住的按键原样交给隐藏的原生 GraphEditor。
    #
    ## 把自己当成一个 GraphEditor **宣布**出去（幂等）。
    #
    # 工作室的 pipeline 启动脚本常把一批快捷键（切换上下文、快捷收藏、跳层级……）
    # 注册在 `GraphEditor.instanceCreatedSignal` 上 ——
    # `Editor.__init__`（`Editor.py:240`）自己就是沿类层级
    # `cls.instanceCreatedSignal()( self )` 发的。接管装上之后我们**也算** GraphEditor，
    # 所以主动发一次，那些 handler 就直接连到**我们的** `keyPressSignal` 上，
    # 不用再把键转发给隐藏引擎。
    #
    # 接管没装（`GAFFER_NETWORK_EDITOR_TAKEOVER=native`）时不发 —— 那时 handler 里的
    # `isinstance` 判断会不成立，发过去也白发。
    def __announceInstance(self):

        if self.__announced:
            return

        if not isinstance(self, GafferUI.GraphEditor):
            return

        self.__announced = True
        # 原生 `Editor.__init__` 也是这样直接发（`Editor.py:240`）
        GafferUI.GraphEditor.instanceCreatedSignal()(self)

    ## 我们没接住的键：交给「pipeline 注册在 GraphEditor 上的那些快捷键」。
    #
    # **先发给自己**（接管装上 + `__announceInstance()` 之后那些 handler 就在我们身上），
    # 自己这条没人要、又确实有隐藏引擎时才退回转发给引擎（接管被关掉的情形）。
    def _forwardShortcutKey(self, qEvent):

        self.__announceInstance()

        try:
            key = GafferUI.Widget._key(qEvent.key())
        except KeyError:
            return False  # Qt 没给名字的键（输入法 / 死键），不是快捷键

        event = GafferUI.KeyEvent(key, GafferUI.Widget._modifiers(qEvent.modifiers()))

        handled = self.__emitKeyPress(self, event)
        if handled:
            return True

        engine = self.__engine()
        if engine is None or engine is self:
            return False

        handled = self.__emitKeyPress(engine, event)

        if handled:
            # 内部脚本可能顺手把引擎切到别的层了（比如跳工作区），跟上去
            engineRoot = engine.graphGadget().getRoot()
            if not engineRoot.isSame(self.__root):
                self.setRootNode(engineRoot)

        return handled

    ## 往 `target` 的 `keyPressSignal` 发一个键，并把它想弹的菜单**截下来用我们的面板画**。
    #
    # 内部那些快捷键的做法都是「造一个 `GafferUI.Menu` 然后 `popup()`」。发信号期间把
    # `Menu.popup` 临时换掉就能截住，原生那个搜索式 QMenu 就不出现了。
    # （某个 handler 抛异常由 Gaffer 的 `EventSignalCombiner` 自己打印，不打断其它 handler。）
    def __emitKeyPress(self, target, event):

        captured = []
        originalPopup = GafferUI.Menu.popup

        def capturingPopup(menu, *args, **kw):
            captured.append(menu)

        GafferUI.Menu.popup = capturingPopup
        try:
            handled = bool(target.keyPressSignal()(target, event))
        finally:
            GafferUI.Menu.popup = originalPopup

        for menu in captured:
            self._showMenuAsPanel(menu)

        return handled

    def _selectAll(self):

        self.__scene.blockSignals(True)
        try:
            for item in list(self.__nodeItems.values()) + list(
                self.__backdropItems.values()
            ):
                item.setSelected(True)
        finally:
            self.__scene.blockSignals(False)
        self._flushSelectionToScript()

    ## 编辑操作一律以 `script.selection()` 为准（和原生 EditMenu 同一个口径），
    # 不看 scene 的选中状态 —— 两者虽然同步，但同步是 defer 的，可能差一拍。
    def __selectedNodes(self):

        result = []
        for node in self.scriptNode().selection():
            if not isinstance(node, Gaffer.Node):
                continue
            parent = node.parent()
            if parent is not None and self.__root.isSame(parent):
                result.append(node)

        return result

    ##########################################################################
    # 摆位写回
    ##########################################################################

    # 拖动过程中只动 Qt item，松手才一次性写回 Gaffer —— 一次拖动 = 一步撤销，
    # 而且避免每帧发一堆 plugSet 信号（`_commitDrag`）。

    ## 拖着一个节点从一根连线上经过 → 记下「松手就把它塞进这根线」。
    #
    # 照原生 `GraphGadget::updateDragReconnectCandidate`：**只在拖单个节点时**生效，
    # 候选是**节点中心 ±2 个 Gaffer 单位**内那根，两头都不能是自己，
    # 插口配对规则见 `insertionPlugs()`。
    def _updateInsertCandidate(self):

        candidate = None

        items = [
            item for item in self.__scene.selectedItems() if isinstance(item, _NodeItem)
        ]
        if len(items) == 1 and not self.readOnly():

            item = items[0]
            centre = item.mapToScene(QtCore.QPointF(0, 0))
            probe = QtCore.QRectF(
                centre.x() - 2.0 * PX_PER_UNIT,
                centre.y() - 2.0 * PX_PER_UNIT,
                4.0 * PX_PER_UNIT,
                4.0 * PX_PER_UNIT,
            )

            for edgeItem in self.__scene.items(probe):

                if not isinstance(edgeItem, _EdgeItem) or edgeItem.edge.auxiliary:
                    continue
                if (
                    edgeItem.edge.srcNode.getName() == item.nodeName
                    or edgeItem.edge.dstNode.getName() == item.nodeName
                ):
                    continue

                plugs = insertionPlugs(
                    item.node, edgeItem.edge.srcPlug, edgeItem.edge.dstPlug, self.__root
                )
                if plugs is not None:
                    candidate = (edgeItem, plugs[0], plugs[1])
                    break

        if candidate is None and self.__insertCandidate is None:
            return

        if (
            candidate is not None
            and self.__insertCandidate is not None
            and candidate[0] is self.__insertCandidate[0]
        ):
            return

        self._clearInsertCandidate()

        self.__insertCandidate = candidate
        if candidate is not None:
            try:
                candidate[0].setInsertTarget(True)
            except RuntimeError:
                self.__insertCandidate = None

    def _clearInsertCandidate(self):

        candidate = self.__insertCandidate
        self.__insertCandidate = None
        if candidate is None:
            return

        try:
            candidate[0].setInsertTarget(False)
        except RuntimeError:
            pass  # item 已经被重建销毁了

    ## 松手：真的把节点塞进那根线里。成功返回 True。
    def _applyInsertCandidate(self):

        candidate = self.__insertCandidate
        self._clearInsertCandidate()

        if candidate is None or self.readOnly():
            return False

        edgeItem, inPlug, outPlug = candidate
        edge = edgeItem.edge

        # 候选在拖动过程中已经按 `insertionPlugs()` 验过能接
        with Gaffer.UndoScope(self.scriptNode()):
            inPlug.setInput(edge.srcPlug)
            edge.dstPlug.setInput(outPlug)

        return True

    ## 拖完松手：写位置 + 压在线上就塞进去，**同一步撤销**（原生 `dragEnd` 里摆位和
    # 重接线共用一个 `dragMergeGroup()`，`GraphGadget.cpp:1255/1393`）。
    def _commitDrag(self):

        with Gaffer.UndoScope(self.scriptNode()):
            self._commitNodePositions()
            self._applyInsertCandidate()

    ## 把挪过的 item 位置写回 `__uiPosition`。Qt 只挪选中的 item（拖 Backdrop 时它框住的
    # 节点也已经被选上），所以只看选中的那些。
    def _commitNodePositions(self):

        changed = []

        # Backdrop 的 item 位置是**框的中心**，写回 `__uiPosition` 要把
        # `__uiBound` 的中心偏移减掉（`centerOffset()`）。
        offsets = []
        for item in self.__scene.selectedItems():
            if isinstance(item, _BackdropItem):
                offsets.append((item, item.centerOffset()))
            elif isinstance(item, _NodeItem):
                offsets.append((item, imath.V2f(0)))

        for item, offset in offsets:
            want = imath.V2f(
                item.pos().x() / PX_PER_UNIT - offset.x,
                -item.pos().y() / PX_PER_UNIT - offset.y,
            )
            current = nodePosition(item.node)
            if (
                current is None
                or abs(current.x - want.x) > 1e-4
                or abs(current.y - want.y) > 1e-4
            ):
                changed.append((item.node, want))

        if not changed:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            for node, position in changed:
                setNodePosition(node, position)

        self.__updateSceneRect()

    ##########################################################################
    # 连接编辑
    ##########################################################################

    ## 从 `fromPlug` 拖到 `targetNode`（可能精确落在 `targetPlug` 上）。
    ## 接一根线。`detach` 是「改接」时要拆掉的那条旧边 —— 新的接上了就把它断掉，
    # 两件事进**同一步撤销**（原生改接也是一步）。
    def _createConnection(
        self, fromPlug, targetNode, targetPlug, globalPosition, detach=None
    ):

        if self.readOnly():
            return

        outward = fromPlug.direction() == Gaffer.Plug.Direction.Out

        def apply(pair):

            if not canConnect(*pair):
                # 接不上就别把旧的也拆了（改接失败 = 什么都没发生）
                return
            with Gaffer.UndoScope(self.scriptNode()):
                if detach is not None and not detach.dstPlug.isSame(pair[1]):
                    # 注意别用 `_plugEditable`：它里头的 `settable()` 对**已经被驱动的**
                    # 输入插口是 False（值被上游接管了），拆连接根本不看这个
                    if not Gaffer.MetadataAlgo.readOnly(detach.dstPlug):
                        self.__disconnectPlug(detach.dstPlug)
                self.__connect(*pair)

        if targetPlug is not None:
            apply((fromPlug, targetPlug) if outward else (targetPlug, fromPlug))
            return

        candidates = candidatePlugs(targetNode, fromPlug)
        if not candidates:
            return

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            chosen = self.__pickPlug(candidates, globalPosition)
            if chosen is None:
                return

        apply((fromPlug, chosen) if outward else (chosen, fromPlug))

    def __connect(self, srcPlug, dstPlug):

        target = resolveInputPlug(dstPlug)
        if target is None:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            target.setInput(srcPlug)

    def __pickPlug(self, plugs, globalPosition):

        chosen = []

        definition = IECore.MenuDefinition()
        for plug in plugs:
            label = Gaffer.Metadata.value(plug, "noduleLayout:label") or plug.getName()
            definition.append(
                "/" + label, {"command": functools.partial(chosen.append, plug)}
            )

        menu = GafferUI.Menu(definition, title="Connect To")
        menu.popup(
            position=imath.V2i(globalPosition.x(), globalPosition.y()), modal=True
        )

        return chosen[0] if chosen else None

    ## 找一条挂在 `plug` 上的边（只找输入边 —— 输出圆点按原生允许多连，按下是新增连接，
    # 不把已有的拔下来）。返回 ( _EdgeItem, "dst" )；找不到 ( None, None )。
    def _edgeItemForPlug(self, plug):

        if plug.direction() != Gaffer.Plug.Direction.In or plug.getInput() is None:
            return (None, None)

        for edgeItem in self.__edgesByNode.get(plug.node().getName(), []):
            if edgeItem.edge.dstPlug.isSame(plug):
                return (edgeItem, "dst")

        return (None, None)

    def _disconnect(self, edges):

        if self.readOnly() or not edges:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            for edge in edges:
                self.__disconnectPlug(edge.dstPlug)

    ## 断开一个目的地插口上的输入（父插口没直接连的话钻进子插口去断）。
    def __disconnectPlug(self, plug):

        if plug.getInput() is not None:
            plug.setInput(None)
            return

        for child in Gaffer.Plug.RecursiveRange(plug):
            if child.getInput() is not None:
                child.setInput(None)

    ##########################################################################
    # 节点创建 / 增删改
    ##########################################################################

    ## Tab / 空白处右键：弹自己的建节点面板。
    #
    # 面板是我们自己的 Qt UI（搜索框 + 结果列表），但**节点是怎么建出来的完全照原生**：
    # 条目就是 `GafferUI.NodeMenu` 的定义，创建函数从 `nodeCreatorWrapper` 的闭包里取出来
    # 直接跑（见 `_unwrapNodeCreator`），连自动连接、自动摆位都用原生
    # `StandardGraphLayout`。取不出来的（Box / Backdrop / Reference 那种自己要 menu 的）
    # 原样跑命令，借我们自己当菜单宿主（`__createWithCommand`）。
    def _popupNodeMenu(self, globalPosition):

        if self.readOnly():
            GafferUI.PopupWindow.showWarning("Node Graph Not Editable", parent=self)
            return

        scenePosition = self.__view.mapToScene(
            self.__view.viewport().mapFromGlobal(globalPosition)
        )

        self._showPanel(
            self.__nodeMenuEntries(),
            functools.partial(self.__createFromMenuItem, scenePosition=scenePosition),
            globalPosition=globalPosition,
            # 只有建节点这个面板带「常用 / 喜爱」—— 榜单认的是 NodeMenu 里的路径
            usage=creatorUsage(),
        )

    ## 用**我们自己画的那个面板**显示一组条目（搜索框 + 列表）。
    # Tab 建节点、`B` 书签、内部快捷键弹出来的那些菜单，统统走这里。
    def _showPanel(
        self, entries, onAccept, globalPosition=None, title=None, usage=None
    ):

        if not entries:
            return False

        # **面板挂在本编辑器当前所在的那个窗口上**。`Qt.Popup` 的原生窗口是**创建那一刻**
        # 认下 transient parent 的，而 Gaffer 换布局是把控件整个 reparent（控件对象不变，
        # 比 `parentWidget()` 看不出来）→ 多窗口下「Tab 栏总在其中一个窗口上」。
        # 窗口变了就 `setParent()` 重来一次（重建原生窗口，认新的 transient parent）。
        window = self.__view.window()

        if self.__creatorPopup is None:
            self.__creatorPopup = _NodeCreatorPopup(window)
        elif window is not None and self.__creatorPopup.parentWidget() is not window:
            self.__creatorPopup.setParent(window, QtCore.Qt.Popup)

        self.__creatorPopup.setTitle(title)
        self.__creatorPopup.setEntries(entries, usage=usage)
        self.__creatorPopup.popupAt(globalPosition or QtGui.QCursor.pos(), onAccept)
        return True

    ## 把一个原生 `GafferUI.Menu` 换成我们的面板显示。
    def _showMenuAsPanel(self, menu, globalPosition=None):

        entries = _entriesFromDefinition(_menuDefinition(menu), menu)
        if not entries:
            # 一条都没有（连灰的都没有）→ 面板画个空的也比弹原生菜单一致
            entries = [("(nothing available)", "", "", _PanelCommand(None))]

        self._showPanel(
            entries,
            functools.partial(self.__invokeMenuItem, menu=menu),
            globalPosition=globalPosition,
            title=menu._Menu__title,
        )

    ## 面板里选中一条原生菜单条目 → 执行它的命令。照 `Menu.__actionTriggered`
    # （`Menu.py:170-202`）：先再问一遍 `active`（建面板到点下去之间可能变了），
    # 再按命令收不收 `menu` / `checkBox` 传参。
    def __invokeMenuItem(self, item, menu=None):

        command = getattr(item, "command", None)
        if command is None:
            return

        if not _entryActiveNow(item, menu):
            return

        # 「建节点」类的条目走我们自己的通道 —— `NodeMenu` 的包装里有
        # `assert menu.ancestor( GafferUI.GraphEditor )`，面板不是菜单，直接调必炸。
        if _isNodeCreatorCommand(command):
            self.__createFromMenuItem(item, self.__mouseScenePosition())
            return

        args = []
        kw = {}

        if _commandWantsMenu(command):
            # 截下来的菜单没真弹过，`Menu.popup()` 本该记下的 popup parent 自己补上
            # （**默认就是我们自己**），命令里的 `menu.ancestor( GafferUI.GraphEditor )` /
            # `menu.popupPosition()` 才有东西可拿。⚠️ `Menu.parent()` 解的是**弱引用**
            # （`Menu.py:131-138`），存的必须是 `weakref.ref( host )`。
            position = QtGui.QCursor.pos()
            menu._Menu__popupParent = weakref.ref(self.__menuHost())
            menu._Menu__popupPosition = imath.V2i(position.x(), position.y())
            kw["menu"] = menu

        # **勾选型条目要把勾选状态传给命令**：原生对 checkable 条目把「点完之后」的
        # 状态塞进第一个位置参数（命令自己收 `checkBox` 就走关键字）。pipeline 里
        # 「切换上下文」那类勾选菜单的命令就是靠它吃第一个参数的。
        checked = _entryCheckState(item, menu)
        if checked is not None:
            if _commandWantsCheckBox(command):
                kw["checkBox"] = not checked
            else:
                args.append(not checked)

        command(*args, **kw)

    ## 鼠标现在指着的 scene 坐标（新建的节点摆这儿）。
    def __mouseScenePosition(self):

        return self.__view.mapToScene(
            self.__view.viewport().mapFromGlobal(QtGui.QCursor.pos())
        )

    ## 建节点面板的条目：( 叶子名, 所在分类, MenuItemDefinition )。
    def __nodeMenuEntries(self):

        application = self.scriptNode().applicationRoot()
        if application is None:
            return []

        return _entriesFromDefinition(
            GafferUI.NodeMenu.acquire(application).definition()
        )

    ## 面板里选中一条 → 把节点建出来。逐条对齐 `NodeMenu.nodeCreatorWrapper`。
    def __createFromMenuItem(self, item, scenePosition):

        command = item.command
        unwrapped = _unwrapNodeCreator(command)
        if unwrapped is None:
            # 拆不出创建函数（`Box` / `Backdrop` / `Reference` / 图像那几个滤波节点
            # 自己要 menu，或者干脆不是 NodeMenu 包装的命令）：原样跑命令
            self.__createWithCommand(command, scenePosition)
            return True

        creator, plugValues, postCreator = unwrapped

        script = self.scriptNode()
        graphGadget = self.__graphGadget()
        fallbackPosition = imath.V2f(
            scenePosition.x() / PX_PER_UNIT, -scenePosition.y() / PX_PER_UNIT
        )

        with Gaffer.UndoScope(script):

            node = creator()
            if node is None:
                return False

            with script.context():
                Gaffer.NodeAlgo.applyUserDefaults(node)

            for plugName, plugValue in (plugValues or {}).items():
                node.descendant(plugName).setValue(plugValue)

            if node.parent() is None:
                self.__root.addChild(node)

            if graphGadget is not None:
                graphGadget.getLayout().connectNode(
                    graphGadget, node, script.selection()
                )

        # 没连上任何东西的话自动布局不知道该摆哪儿 —— 摆到鼠标位置去。
        # 和原生一样，这一步不进撤销。
        if graphGadget is not None:
            graphGadget.getLayout().positionNode(graphGadget, node, fallbackPosition)
        elif nodePosition(node) is None:
            setNodePosition(node, fallbackPosition)

        script.selection().clear()
        script.selection().add(node)

        if postCreator is not None:
            postCreator(node, None)

        return True

    ## 跑一条拆不出创建函数的建节点命令。命令自己要 `menu` 参数（`Box` / `Backdrop` /
    # `Reference` 这些 `nodeMenuCreateCommand`）时造一个**没弹出来的** `GafferUI.Menu`、
    # 把 popup parent 指到宿主（接管装着时就是我们自己）上，命令里的
    # `menu.ancestor( GafferUI.GraphEditor )` 就有东西可拿。摆位一律走
    # `__finishNodeCreation`（新建的、没连线的节点摆到鼠标那儿）。
    def __createWithCommand(self, command, scenePosition):

        self.__beginPendingCreate(scenePosition)

        if not _commandWantsMenu(command):
            try:
                command()
            finally:
                self.__finishNodeCreation()
            return

        host = self.__menuHost()
        menu = GafferUI.Menu(IECore.MenuDefinition())
        menu._Menu__popupParent = weakref.ref(host)
        menu._Menu__popupPosition = self.__hostPopupPosition(host, scenePosition)

        # 原生包装最后会 `graphEditor.frame( [ node ], extend = True )` —— 宿主是我们
        # 自己时那就把**用户正在看的视野**拽走了；宿主是"借来的那个真 GraphEditor"时
        # 拽的是人家的视野。两种都不行，临时换成空函数。
        framedByInstance = "frame" in host.__dict__
        originalFrame = host.__dict__.get("frame")

        try:
            host.frame = lambda *args, **kw: None
            command(menu=menu)
        finally:
            if framedByInstance:
                host.frame = originalFrame
            else:
                host.__dict__.pop("frame", None)
            self.__finishNodeCreation()

    ## 借来的那个菜单该「假装」在屏幕上的哪个位置。
    #
    # 原生命令里是 `menu.popupPosition( relativeTo = gadgetWidget )` →
    # `rasterToGadgetSpace()`，我们把这一路反着算一遍，让它最后拿到的就是鼠标所在的
    # 图坐标。视口退化算出 nan 的话退回鼠标屏幕坐标（位置由 `__finishNodeCreation` 兜底）。
    def __enginePopupPosition(self, engine, scenePosition):

        target = imath.V2f(
            scenePosition.x() / PX_PER_UNIT, -scenePosition.y() / PX_PER_UNIT
        )

        gadgetWidget = engine.graphGadgetWidget()
        raster = gadgetWidget.getViewportGadget().gadgetToRasterSpace(
            imath.V3f(target.x, target.y, 0), gadget=engine.graphGadget()
        )
        origin = gadgetWidget.bound().min()
        result = imath.V2f(raster.x + origin.x, raster.y + origin.y)
        if positionUsable(result):
            return result

        position = QtGui.QCursor.pos()
        return imath.V2f(position.x(), position.y())

    def __nodeMenuVisibilityChanged(self, menu):

        # 菜单是非模态的，命令在关闭前后才跑完 —— 等 idle 再收尾。
        if menu.visible() or self.__pendingCreate is None:
            return

        GafferUI.EventLoop.addIdleCallback(
            Gaffer.WeakMethod(self.__finishNodeCreation, fallbackResult=False)
        )

    ## 跑一条「可能会建节点」的原生命令之前记一笔：这一层现在有哪些节点、要摆到哪、
    # 当时有没有选中节点（Backdrop 用）、在哪一层。`__finishNodeCreation` 拿它收尾。
    def __beginPendingCreate(self, scenePosition):

        self.__pendingCreate = (
            set(n.getName() for n in collectNodes(self.__root)),
            scenePosition,
            bool(len(self.scriptNode().selection())),
            self.__root,
        )

    def __finishNodeCreation(self):

        if self.__pendingCreate is None:
            return False

        before, scenePosition, hadSelection, root = self.__pendingCreate
        self.__pendingCreate = None

        # 菜单里点的是「进这一层」之类换了 root 的命令：`before` 记的是上一层的名字，
        # 拿它和这一层比会把这层所有没连线的节点都当成"刚建的"搬走
        if root is None or not root.isSame(self.__root):
            return False

        created = [n for n in collectNodes(self.__root) if n.getName() not in before]

        # 没连上任何东西的，摆到鼠标位置。原生走 raster→gadget 换算，我们直接就知道。
        # **建的时候有选中节点的 Backdrop 除外** —— 它已经把那些节点框住了
        # （`BackdropUI.nodeMenuCreateCommand` 里的 `nodeGadget.frame`），再挪就跑了。
        # 位置算坏了（nan / inf，见 `positionUsable`）的一律拉回鼠标那儿。
        orphans = []
        for node in created:
            position = nodePosition(node)
            if not positionUsable(position):
                orphans.append(node)
            elif hadSelection and isinstance(node, Gaffer.Backdrop):
                continue
            elif not self.__nodeHasConnections(node):
                orphans.append(node)

        # 和原生一样，摆位**不进撤销** —— 进了的话建一个节点得按两次 Ctrl+Z
        # （第一次只是把它挪回原处），原生 `nodeCreatorWrapper` 里的 `positionNode`
        # 也是写在 `UndoScope` 外面的。
        for node in orphans:
            setNodePosition(
                node,
                imath.V2f(
                    scenePosition.x() / PX_PER_UNIT, -scenePosition.y() / PX_PER_UNIT
                ),
            )

        return False

    def __nodeHasConnections(self, node):

        for plug in Gaffer.Plug.RecursiveRange(node):
            if plug.getInput() is not None:
                return True
            if len(plug.outputs()):
                return True
        return False

    ## `D` 键停用 / 启用选中节点。语义抄原生 GraphEditor：**只要有一个是开着的就
    # 全部关掉**，全关着才全打开；一次操作一步撤销。
    def _toggleEnabled(self):

        if self.readOnly():
            return

        plugs = []
        for node in self.__selectedNodes():
            if node.getName() not in self.__nodeItems:
                continue
            plug = enabledPlugForEditing(node)
            if (
                plug is None
                or not plug.settable()
                or Gaffer.MetadataAlgo.readOnly(plug)
            ):
                continue
            plugs.append(plug)

        if not plugs:
            return

        enabled = any(plug.getValue() for plug in plugs)
        with Gaffer.UndoScope(self.scriptNode()):
            for plug in plugs:
                plug.setValue(not enabled)

    def _deleteSelected(self):

        if self.readOnly():
            return

        # 选着线就删线（选线的时候节点选择已经被清掉了，不会两边一起删）
        edges = self.selectedEdges()
        if edges:
            self._disconnect([item.edge for item in edges])
            self._clearEdgeSelection()
            return

        nodes = self.__selectedNodes()
        if not nodes:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            self.__clearFocusIfDeleting(nodes)
            # reconnect = True：删中间节点时把上下游接起来，原生 Edit/Delete 的行为
            self.scriptNode().deleteNodes(self.__root, Gaffer.StandardSet(nodes), True)

    ## 要删的节点里有 focus 的那个？**先把 focus 取消掉再删**。
    #
    # 否则跟着 focus 走的 `ShaderView` 会在节点消失后再跑一次 `updateScene()`，这时输入
    # 上已经没材质、`shaderPrefix()` 是空串，于是刷一条
    # `ERROR : ShaderView : SceneCreator "Default" not registered`
    # （`ShaderView.cpp:395`）。
    # **这是原生自带的**（裸 `removeChild( 被 focus 的材质 )` 也照样报），但既然删的就是它，
    # 顺手取消 focus 正好躲开。
    def __clearFocusIfDeleting(self, nodes):

        script = self.scriptNode()
        focus = script.getFocus()
        if focus is None:
            return

        for node in nodes:
            if node.isSame(focus) or node.isAncestorOf(focus):
                script.setFocus(None)
                return

    ## 删掉指定的那些节点（X 模式点一下删、以及别处想删指定节点时用）。
    # 和 `_deleteSelected` 走同一条路：`reconnect = True` 让上下游接起来。
    def _deleteNodes(self, nodes):

        if self.readOnly() or not nodes:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            self.__clearFocusIfDeleting(nodes)
            self.scriptNode().deleteNodes(self.__root, Gaffer.StandardSet(nodes), True)

    def _copySelected(self):

        nodes = self.__selectedNodes()
        if not nodes:
            return
        self.scriptNode().copy(self.__root, Gaffer.StandardSet(nodes))

    def _cutSelected(self):

        if self.readOnly():
            return

        nodes = self.__selectedNodes()
        if not nodes:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            self.__clearFocusIfDeleting(nodes)
            self.scriptNode().cut(self.__root, Gaffer.StandardSet(nodes))

    def _paste(self):

        if self.readOnly():
            return

        script = self.scriptNode()
        originalSelection = Gaffer.StandardSet(iter(script.selection()))

        position = self.__view.mapToScene(
            self.__view.viewport().mapFromGlobal(QtGui.QCursor.pos())
        )
        fallback = imath.V2f(position.x() / PX_PER_UNIT, -position.y() / PX_PER_UNIT)

        graphGadget = self.__graphGadget()

        with Gaffer.UndoScope(script):

            script.paste(self.__root, continueOnError=True)

            if graphGadget is None:
                return

            layout = graphGadget.getLayout()
            layout.connectNodes(graphGadget, script.selection(), originalSelection)

            needLayout = [
                n for n in script.selection() if not graphGadget.hasNodePosition(n)
            ]
            layout.positionNodes(graphGadget, script.selection(), fallback)
            if needLayout:
                layout.layoutNodes(graphGadget, Gaffer.StandardSet(needLayout))

    ## Ctrl+D：连输入一起复制。逐条抄原生 `EditMenu.duplicateWithInputs`
    # （序列化选中节点 → 在空 script 里执行一遍拿到顺序 → 再执行到当前层 → 按顺序
    # 把输入接回去 → 整体偏移半个节点高）。
    def _duplicateWithInputs(self):

        if self.readOnly():
            return

        script = self.scriptNode()
        nodes = self.__selectedNodes()
        if not nodes:
            return

        nodeOffset = imath.V2f(2.25, -2.25)

        with Gaffer.UndoScope(script):

            source = script.serialise(self.__root, Gaffer.StandardSet(nodes))

            dummyNodes = []
            dummyScript = Gaffer.ScriptNode()
            dummyConnection = dummyScript.childAddedSignal().connect(
                lambda parent, child: dummyNodes.append(child), scoped=True
            )
            dummyScript.execute(source)

            newNodes = []
            scriptConnection = self.__root.childAddedSignal().connect(
                lambda parent, child: newNodes.append(child), scoped=True
            )
            script.execute(source, self.__root)
            del scriptConnection

            def duplicateInputs(sourceComponent, destComponent):

                if isinstance(destComponent, Gaffer.Plug):

                    if destComponent.direction() == Gaffer.Plug.Direction.Out:
                        return

                    if (
                        sourceComponent.getInput() is not None
                        and destComponent.getInput() is None
                    ):
                        if isinstance(
                            sourceComponent.getInput().node(), Gaffer.Expression
                        ):
                            # 表达式的插口是随表达式变的临时插口，直接接源插口更稳
                            destComponent.setInput(sourceComponent)
                        else:
                            destComponent.setInput(sourceComponent.getInput())
                        return

                for sourceChild in sourceComponent.children():
                    destChild = destComponent.getChild(sourceChild.getName())
                    if destChild is not None:
                        duplicateInputs(sourceChild, destChild)

            for i in range(0, min(len(newNodes), len(dummyNodes))):
                original = self.__root.getChild(dummyNodes[i].getName())
                if original is not None:
                    duplicateInputs(original, newNodes[i])

            script.selection().clear()
            for node in newNodes:
                script.selection().add(node)
                position = nodePosition(node)
                if position is not None:
                    setNodePosition(node, position + nodeOffset)

    def _selectNone(self):

        self.scriptNode().selection().clear()

    ## Ctrl+L：自动布局。入口语义照原生 `EditMenu.arrange`（没选中就排整层），
    # **算法是我们自己的分层布局**（见 `layoutNodes()`）—— 原生那套在多节点上
    # 横向拉得太宽、上下层错开、连线来回穿。
    #
    # 只选了一个节点时没什么可排的，那就整层一起排（选一个节点按 Ctrl+L 的人
    # 想要的是"把图理一理"，不是"把这一个挪一下"）。
    def _arrange(self):

        if self.readOnly():
            return

        script = self.scriptNode()
        nodes = [
            node for node in script.selection() if self.__root.isSame(node.parent())
        ]
        if len(nodes) < 2:
            nodes = list(self.__root.children(Gaffer.Node))

        graphGadget = self.__graphGadget()
        positions = layoutNodes(nodes, self.__root, graphGadget)
        if not positions:
            return

        with Gaffer.UndoScope(script):
            for node, position in positions.items():
                setNodePosition(node, position)

    ## F2：改名。和原生 `EditMenu.rename` 一样，连输入校验都借 NameWidget 的。
    def _renameSelected(self):

        if self.readOnly():
            return

        nodes = self.__selectedNodes()
        if not nodes:
            return

        dialogue = GafferUI.TextInputDialogue(
            initialText=nodes[-1].getName(), title="Enter name", confirmLabel="Rename"
        )

        # 照原生 `EditMenu.__renameSelection`（`EditMenu.py:297`）
        from GafferUI.NameWidget import _Validator

        textWidget = dialogue._getWidget()._qtWidget()
        textWidget.setValidator(_Validator(textWidget))

        newName = dialogue.waitForText(parentWindow=self.ancestor(GafferUI.Window))
        if not newName:
            return

        with Gaffer.UndoScope(self.scriptNode()):
            for node in nodes:
                node.setName(newName)

    ## Ctrl+F：查找节点。用的就是原生那个 NodeFinderDialogue，而且和原生共用
    # ScriptWindow 上的同一个实例。
    def _find(self):

        scriptWindow = GafferUI.ScriptWindow.acquire(
            self.scriptNode(), createIfNecessary=False
        )
        if scriptWindow is None:
            return

        dialogue = getattr(scriptWindow, "__findDialogue", None)
        if dialogue is None:
            dialogue = GafferUI.NodeFinderDialogue(self.__root)
            scriptWindow.addChildWindow(dialogue)
            setattr(scriptWindow, "__findDialogue", dialogue)

        dialogue.setScope(self.__root)
        dialogue.setVisible(True)

    ##########################################################################
    # 书签（B / 数字键 / Ctrl+数字键，语义抄 GraphBookmarksUI）
    ##########################################################################

    def _popupBookmarkMenu(self, globalPosition):

        script = self.scriptNode()

        # 路径按原生那样排（`GraphBookmarksUI.__findBookmark`）：`/rigBox` 紧挨在
        # `/rigBox/innerSphere` 前面，所以「这个书签底下还有书签吗」比一下**下一条**就知道。
        pathsAndNodes = [
            ("/" + node.relativeName(script).replace(".", "/"), node)
            for node in self._findableBookmarks()
        ]

        entries = []
        for i, (path, node) in enumerate(pathsAndNodes):

            command = _PanelCommand(functools.partial(self.__revealNode, node))

            # **自己是书签、底下还有书签** → 照原生挂成 `<路径>/This Node`：
            # 它在面板里就落在自己那一组里面，不会和「同名的那一组」在同一层打架。
            if i < len(pathsAndNodes) - 1 and pathsAndNodes[i + 1][0].startswith(
                path + "/"
            ):
                entries.append(
                    (
                        "This Node",
                        path.strip("/").replace("/", " / "),
                        node.getName(),
                        command,
                    )
                )
                continue

            entries.append(
                (
                    node.getName(),
                    path.strip("/").rpartition("/")[0].replace("/", " / "),
                    node.relativeName(script),
                    command,
                )
            )

        if not entries:
            # 一条书签都没有也得给个反馈（原生那条 "No bookmarks available" 是灰的）——
            # 直接 return 的话按 B 什么都不发生，看着就是「这个功能没了」。
            entries = [("No bookmarks available", "", "", _PanelCommand(None))]

        self._showPanel(
            entries,
            self.__invokeMenuItem,
            globalPosition=globalPosition,
            title="Find Bookmark",
        )

    ## 图里所有能跳过去的书签，**整棵树都算**（照原生 `GraphBookmarksUI.__findableBookmarks`）。
    #
    # ⚠️ **别用 `Gaffer.MetadataAlgo.bookmarks( script )`** —— 它只扫**直接子节点**
    # （`MetadataAlgo.cpp:420` 的 `Node::Iterator`），装在 Box 里的书签一个都找不到；
    # 实际工程里书签基本都在 Box 里，于是「按 B 什么都没有」。原生用的是
    # `Metadata.nodesWithMetadata( script, "bookmarked", instanceOnly = True )`（递归、而且快），
    # 并且**排掉 Reference 里面的**（那些跟着 .grf 走，跳进去也改不了）。
    def _findableBookmarks(self):

        script = self.scriptNode()

        bookmarks = Gaffer.Metadata.nodesWithMetadata(
            script, "bookmarked", instanceOnly=True
        )

        bookmarks = [
            node
            for node in bookmarks
            if node.ancestor(Gaffer.Reference) is None
            and Gaffer.MetadataAlgo.getBookmarked(node)
        ]

        return sorted(bookmarks, key=lambda n: n.relativeName(script))

    ## 数字键：跳到编号书签。原生的做法是**切到那个节点所在的层再框住它**。
    def _findNumericBookmark(self, number):

        if number == 0:
            return False

        node = Gaffer.MetadataAlgo.getNumericBookmark(self.scriptNode(), number)
        if not node:
            return False

        self.__revealNode(node)
        return True

    ## Ctrl+数字键：把选中的节点设成编号书签（0 = 清掉）。
    def _assignNumericBookmark(self, number):

        script = self.scriptNode()
        selection = script.selection()

        node = None
        if len(selection) == 1:
            node = selection[0]
        else:
            backdrops = [n for n in selection if isinstance(n, Gaffer.Backdrop)]
            if len(backdrops) == 1:
                node = backdrops[0]

        if node is None:
            return

        with Gaffer.UndoScope(script):
            if number == 0:
                current = Gaffer.MetadataAlgo.numericBookmark(node)
                if current:
                    Gaffer.MetadataAlgo.setNumericBookmark(script, current, None)
            else:
                Gaffer.MetadataAlgo.setNumericBookmark(script, number, node)

    def __revealNode(self, node, *unused):

        parent = node.parent()
        if isinstance(parent, Gaffer.Node):
            self.setRootNode(parent)

        script = self.scriptNode()
        script.selection().clear()
        script.selection().add(node)

        item = self.__nodeItems.get(node.getName())
        if item is not None:
            self.__view.frameItems([item])

    ##########################################################################
    # 右键菜单
    ##########################################################################

    def _showContextMenu(
        self, nodeItem, edgeItem, globalPosition, scenePosition, plug=None
    ):

        if nodeItem is None and edgeItem is None:
            self._popupNodeMenu(globalPosition)
            return

        if plug is not None and self.__popupPlugMenu(
            plug, globalPosition, scenePosition
        ):
            return

        if edgeItem is not None:
            self.__popupEdgeMenu(edgeItem, globalPosition, scenePosition)
            return

        self.__popupNodeMenuFor(nodeItem.node, globalPosition, scenePosition)

    ## 点在接口圆点上：整份菜单都由原生给（提升 / 取消提升 / Dot 方向 / 可见性…）。
    # 一条都没有就返回 False，让调用方退回节点菜单。
    def __popupPlugMenu(self, plug, globalPosition, scenePosition):

        definition = IECore.MenuDefinition()
        self.__appendNativePlugMenu(definition, plug)
        self.__appendComponentMenu(definition, plug)
        if not len(definition.items()):
            return False

        self.__popupContextMenu(
            definition,
            globalPosition,
            scenePosition,
            title=plug.relativeName(self.__root),
        )
        return True

    ## 点在连线上：断开（Disconnect）+ 原生挂在连线上的那些
    # （DotUI 的「在连线上插入 Dot」就是这条）。
    def __popupEdgeMenu(self, edgeItem, globalPosition, scenePosition):

        definition = IECore.MenuDefinition()
        definition.append(
            "/Disconnect",
            {"command": functools.partial(self._disconnect, [edgeItem.edge])},
        )

        native = IECore.MenuDefinition()
        if self.__appendNativeConnectionMenu(native, edgeItem.edge.dstPlug):
            definition.append("/ConnectionNativeDivider", {"divider": True})
            for path, item in native.items():
                definition.append(path, item)

        # 标题照原生：`-> 目的地插口`（`GraphEditor.py:476`）
        self.__popupContextMenu(
            definition,
            globalPosition,
            scenePosition,
            title="-> " + edgeItem.edge.dstPlug.relativeName(self.__root),
        )

    ## 点在节点上：先试原生那份，原生给不出来才用我们自己拼的。
    def __popupNodeMenuFor(self, node, globalPosition, scenePosition):

        definition = IECore.MenuDefinition()
        readOnly = self.readOnly() or Gaffer.MetadataAlgo.readOnly(node)

        # 先试原生的节点右键菜单 —— 它才是「和原生没区别」的那份（Edit… / Enabled /
        # Connections / Focus / 注释 / 书签 / 各家插件挂上去的条目全在里面）。
        # 需要一个 GraphEditor 当第一个参数，engine 就是干这个的。
        if self.__appendNativeNodeMenu(definition, node):

            # 原生那条 "Show Contents..." 走 `GraphEditor.acquire()` —— 会往当前
            # layout 里塞一个**原生 GraphEditor**（layout 里没有的话就现建一个）。
            # 就地把它改成我们自己的进层级，位置和标签都不动。原生没给这一条
            # （节点没标 `ui:childNodesAreViewable`）就是不该有。
            self.__redirectShowContents(definition, node)
        else:
            self.__appendOwnNodeMenu(definition, node, readOnly)

        # 标题照原生：右键点在多选里的一个上就是「N Nodes」（`GraphEditor.py:492`）
        nodeList = self.__contextNodeList(node)
        self.__popupContextMenu(
            definition,
            globalPosition,
            scenePosition,
            title=(
                "{} Nodes".format(len(nodeList))
                if len(nodeList) > 1
                else node.getName()
            ),
        )

    ## 右键点在 `node` 上时菜单作用于哪些节点：它在选中里就是这一层所有选中的，
    # 否则就它自己（原生 `GraphEditor.__buttonPress`）。
    def __contextNodeList(self, node):

        selected = self.__selectedNodes()
        return selected if any(n.isSame(node) for n in selected) else [node]

    ## 原生菜单一条都没给时自己拼一份。条目名一律用原生的英文措辞，对照：
    #   Focus = 设为 / 取消 focus；Enabled = 启用；Bookmarked = 书签；
    #   Connections/Show Input·Output Connections = 显示输入 / 输出连线（关掉即折叠）；
    #   Show Contents... = 进入这一层；Copy / Cut / Delete = 复制 / 剪切 / 删除。
    def __appendOwnNodeMenu(self, definition, node, readOnly):

        script = self.scriptNode()
        focus = script.getFocus()
        isFocus = focus is not None and focus.isSame(node)
        definition.append(
            "/Focus",
            {
                "command": functools.partial(self.__setFocus, node, not isFocus),
                "checkBox": isFocus,
            },
        )

        if isinstance(node, Gaffer.DependencyNode) and node.enabledPlug() is not None:
            enabled = nodeEnabled(node)
            definition.append(
                "/Enabled",
                {
                    "command": functools.partial(self.__setEnabled, node),
                    "checkBox": enabled is True,
                    "active": not readOnly and enabled is not None,
                },
            )

        definition.append("/BookmarkDivider", {"divider": True})
        definition.append(
            "/Bookmarked",
            {
                "command": functools.partial(self.__setBookmarked, node),
                "checkBox": Gaffer.MetadataAlgo.getBookmarked(node),
                "active": not readOnly,
            },
        )

        definition.append("/ConnectionsDivider", {"divider": True})
        for label, direction in (
            ("Show Input Connections", Gaffer.Plug.Direction.In),
            ("Show Output Connections", Gaffer.Plug.Direction.Out),
        ):
            definition.append(
                "/Connections/" + label,
                {
                    "command": functools.partial(
                        self.__setConnectionsMinimised, node, direction
                    ),
                    "checkBox": not nodeConnectionsMinimised(node, direction),
                    "active": not readOnly,
                },
            )

        if self._childrenViewable(node):
            definition.append("/EnterDivider", {"divider": True})
            definition.append(
                "/Show Contents...",
                {"command": functools.partial(self._enterNode, node)},
            )

        definition.append("/EditDivider", {"divider": True})
        definition.append("/Copy", {"command": self._copySelected})
        definition.append(
            "/Cut", {"command": self._cutSelected, "active": not readOnly}
        )
        definition.append(
            "/Delete", {"command": self._deleteSelected, "active": not readOnly}
        )

    ## 弹一份右键菜单。
    #
    # 三件事：①**挂在宿主上**（原生命令里有 `menu.ancestor( GafferUI.GraphEditor )`；
    # 接管装着时宿主就是我们自己，否则是隐藏引擎）；②**弹出去之后覆盖 `popupPosition`**
    # —— 那些命令拿它反算图坐标给新节点摆位，显示要用鼠标屏幕坐标、算位置要用换算回来
    # 正好是鼠标那点的值；③**盯着有没有新节点冒出来** —— 菜单关掉后走一遍
    # `__finishNodeCreation`，没连线的新节点摆到鼠标那儿、坏位置（nan）拉回来。
    #
    # 菜单对象必须留引用，否则局部变量出作用域就被 GC、菜单一闪而过。
    def __popupContextMenu(
        self, definition, globalPosition, scenePosition=None, title=None
    ):

        host = self.__menuHost()
        if host is not None and host is not self:
            self.__syncViewportGadget(host.graphGadgetWidget().getViewportGadget())

        self.__contextMenu = GafferUI.Menu(definition, title=title)

        if scenePosition is not None:
            self.__beginPendingCreate(scenePosition)
            self.__contextMenu.visibilityChangedSignal().connect(
                Gaffer.WeakMethod(self.__nodeMenuVisibilityChanged)
            )

        self.__contextMenu.popup(
            parent=host,
            position=imath.V2i(globalPosition.x(), globalPosition.y()),
        )

        if host is not None and scenePosition is not None:
            self.__contextMenu._Menu__popupPosition = self.__hostPopupPosition(
                host, scenePosition
            )

    ## 把原生 GraphEditor 的节点右键菜单填进 `definition`。成功返回 True。
    def __appendNativeNodeMenu(self, definition, node):

        # 发信号时第一个参数就是"那个 GraphEditor"——接管之后传**我们自己**，
        # 于是 handler 里的 `graphEditor.graphGadget()` / `scriptNode()` /
        # `graphGadgetWidget()` 全落到我们身上（前两个本来就有，第三个是那层壳）。
        host = self.__menuHost()
        if host is None:
            return False

        graphGadget = self.__graphGadget()
        if graphGadget is None:
            return False

        if graphGadget.nodeGadget(node) is None:
            return False

        # 原生是**先多选后单个**（`GraphEditor.__buttonPress:487-490`），而且多选那一路
        # **无条件发**（没有「选了几个」的守卫）—— 整套节点菜单（`/Edit...` / `/Enabled` /
        # `/Connections` / `/Bookmarked` / 注释 / `Show Contents...`）全注册在
        # `nodeContextMenuSignal( True )` 上，参数是**节点列表**
        # （`startup/gui/graphEditor.py:116`）。只在多选时发它 = 单选时菜单全空。
        # 和原生一样不兜 handler 的异常。
        nodeList = self.__contextNodeList(node)

        for signal in _contextMenuSignals(
            GafferUI.GraphEditor.nodeContextMenuSignal(True),
            self.__hostSignal(host, "nodeContextMenuSignal", True),
        ):
            signal(host, nodeList, definition)

        # 单个那一路核心已经没人注册了（1.7 全搬去了多选），但第三方仍可能连它。
        for signal in _contextMenuSignals(
            GafferUI.GraphEditor.nodeContextMenuSignal(),
            self.__hostSignal(host, "nodeContextMenuSignal"),
        ):
            signal(host, node, definition)

        return len(definition.items()) > 0

    ## 把原生 GraphEditor 的**插口**右键菜单填进 `definition`。成功返回 True。
    #
    # 官方注册了 6 处（`BoxUI` 提升 / 取消提升、`DotUI` 方向与标签、`LoopUI`、
    # `CollectUI`、`CompoundNumericNoduleUI` 展开收起、`_PlugVisibilityGadget` 可见性），
    # 第三方插件也可能挂 —— 不借这一条，圆点上右键就是空的。
    def __appendNativePlugMenu(self, definition, plug):

        host = self.__menuHost()
        if host is None or plug is None:
            return False

        for signal in _contextMenuSignals(
            GafferUI.GraphEditor.plugContextMenuSignal(),
            self.__hostSignal(host, "plugContextMenuSignal"),
        ):
            signal(host, plug, definition)

        return len(definition.items()) > 0

    ## 补一条「展开 / 收起 RGB 子插口」。
    #
    # 原生这条挂在 `CompoundNumericNoduleUI` 上，**但要求 nodule 已经是
    # `CompoundNumericNodule`** —— Arnold 材质的 `out` 压根没注册
    # `nodule:type`，所以原生那条根本不出现。这里自己补：把 `nodule:type` 和
    # `compoundNumericNodule:childrenVisible` 一起写上（实例元数据，原生视图也认）。
    def __appendComponentMenu(self, definition, plug):

        if plug is None:
            return False

        # 原生已经给了就别重复
        if any("Components" in path for path, _ in definition.items()):
            return False

        children = plug.children(Gaffer.Plug)
        if len(children) < 2 or len(children) > 4:
            return False
        if not all(isinstance(c, (Gaffer.FloatPlug, Gaffer.IntPlug)) for c in children):
            return False
        if not hasNodule(plug):
            return False

        names = "".join(c.getName() for c in children).upper()
        expanded = bool(
            Gaffer.Metadata.value(plug, "compoundNumericNodule:childrenVisible")
        )

        definition.append(
            (
                # Collapse / Expand … Components = 收起 / 展开子插口（照抄原生措辞）
                "/Collapse %s Components" % names
                if expanded
                else "/Expand %s Components" % names
            ),
            {
                "command": functools.partial(
                    self.__setComponentsVisible, plug, not expanded
                ),
                "active": not Gaffer.MetadataAlgo.readOnly(plug),
            },
        )
        return True

    ## 展开 / 收起一个 Color3f / V3f 之类插口的子圆点。
    def __setComponentsVisible(self, plug, visible):

        with Gaffer.UndoScope(self.scriptNode()):
            if visible:
                # 原生的 `CompoundNumericNodule` 才认 `childrenVisible`，
                # 所以顺手把 nodule 类型也写上（Arnold 的 out 默认没有）
                if (
                    Gaffer.Metadata.value(plug, "nodule:type")
                    != "GafferUI::CompoundNumericNodule"
                ):
                    Gaffer.Metadata.registerValue(
                        plug, "nodule:type", "GafferUI::CompoundNumericNodule"
                    )
                Gaffer.Metadata.registerValue(
                    plug, "compoundNumericNodule:childrenVisible", True
                )
            else:
                Gaffer.Metadata.deregisterValue(
                    plug, "compoundNumericNodule:childrenVisible"
                )

        return True

    ## 把原生 GraphEditor 的**连线**右键菜单填进 `definition`（`DotUI` 的插入 Dot）。
    #
    # 原生传的是**目的地那一端的插口**（`gadgets[0].dstNodule().plug()`）。
    def __appendNativeConnectionMenu(self, definition, dstPlug):

        host = self.__menuHost()
        if host is None or dstPlug is None:
            return False

        for signal in _contextMenuSignals(
            GafferUI.GraphEditor.connectionContextMenuSignal(),
            self.__hostSignal(host, "connectionContextMenuSignal"),
        ):
            signal(host, dstPlug, definition)

        return len(definition.items()) > 0

    ## 把原生菜单里的 "Show Contents..." 改成走我们自己的进层级。改了返回 True。
    #
    # 原生那条的命令是 `functools.partial( GraphEditor.__acquireNodes, nodeList )`，它在
    # layout 里找不到原生 GraphEditor 就会**新建一个 `addEditor()` 进去**
    # （实测 0 -> 1）—— 对「布局里只留 NetworkEditor」的用法就是原生面板自己冒出来。
    # 原生只在 `ui:childNodesAreViewable` 时才给这一条（和 ↓ 键同一个判据），
    # 换成 `_enterNode` 语义对得上。位置靠 `insertBefore` 保住（`append` 同名会把条目挪到末尾）。
    def __redirectShowContents(self, definition, node):

        paths = [path for path, item in definition.items()]

        target = None
        for path in paths:
            if path.rpartition("/")[2].startswith("Show Contents"):
                target = path
                break

        if target is None:
            return False

        index = paths.index(target)
        following = paths[index + 1] if index + 1 < len(paths) else None

        item = IECore.MenuItemDefinition(
            command=functools.partial(self._enterNode, node)
        )

        definition.remove(target)
        if following is not None:
            definition.insertBefore(target, item, following)
        else:
            definition.append(target, item)

        return True

    # 勾选项的命令会多收一个 toggled 参数（Menu.__actionTriggered 对 checkable
    # action 会把勾选状态 append 进 args），签名要用 *unused 兜底。
    def __setFocus(self, node, focus, *unused):

        self.scriptNode().setFocus(node if focus else None)

    def __setEnabled(self, node, *unused):

        plug = enabledPlugForEditing(node)
        if plug is None or not plug.settable() or Gaffer.MetadataAlgo.readOnly(plug):
            return
        with Gaffer.UndoScope(self.scriptNode()):
            plug.setValue(not plug.getValue())

    def __setBookmarked(self, node, *unused):

        with Gaffer.UndoScope(self.scriptNode()):
            Gaffer.MetadataAlgo.setBookmarked(
                node, not Gaffer.MetadataAlgo.getBookmarked(node)
            )

    def __setConnectionsMinimised(self, node, direction, *unused):

        with Gaffer.UndoScope(self.scriptNode()):
            setNodeConnectionsMinimised(
                node, direction, not nodeConnectionsMinimised(node, direction)
            )


# 让写死了 `GafferUI.GraphEditor` 的那些地方也认得我们

_nativeGraphEditor = None  # 接管之前那个真的 GraphEditor 类


## 真正的原生 GraphEditor 类（接管与否都拿得到）。
def _nativeGraphEditorClass():

    return (
        _nativeGraphEditor if _nativeGraphEditor is not None else GafferUI.GraphEditor
    )


## 接管之后 `GafferUI.GraphEditor` 就是这个壳，它**只改「找编辑器」这件事**：
#
# * `isinstance( x, GafferUI.GraphEditor )` 对我们和原生**都为真** —— `EditMenu.scope()`
#   / `GraphBookmarksUI` / `NodeFinderDialogue` / `CompoundEditor.editor()` 都能找到我们，
#   而原生编辑器一点没受影响（随时切回去的退路还在）。
# * 类属性一律转给原生类 —— startup 里那些 `connect()` 早挂在原生类上，必须是同一个
#   信号对象。
# * **构造仍然构造原生的** —— 存过的 layout 里写死的就是这一句，换成我们会让所有旧布局
#   悄悄变样。
# * `acquire()` 优先落到 layout 里现成的 NetworkEditor 上。
class _GraphEditorTakeoverMeta(type):

    def __instancecheck__(cls, instance):

        return isinstance(instance, (NetworkEditor, _nativeGraphEditorClass()))

    def __subclasscheck__(cls, subclass):

        return issubclass(subclass, (NetworkEditor, _nativeGraphEditorClass()))

    def __getattr__(cls, name):

        return getattr(_nativeGraphEditorClass(), name)

    def __call__(cls, *args, **kw):

        return _nativeGraphEditorClass()(*args, **kw)

    def __repr__(cls):

        return repr(_nativeGraphEditorClass())


class _GraphEditorProxy(metaclass=_GraphEditorTakeoverMeta):

    ## 优先用 layout 里现成的 NetworkEditor 进这一层；没有就退回原生那套。
    @staticmethod
    def acquire(rootNode):

        script = (
            rootNode
            if isinstance(rootNode, Gaffer.ScriptNode)
            else rootNode.scriptNode()
        )

        scriptWindow = GafferUI.ScriptWindow.acquire(script, createIfNecessary=False)
        if scriptWindow is not None:
            editors = scriptWindow.getLayout().editors(type=NetworkEditor)
            # 已经在这一层的优先
            for editor in editors:
                if editor.getRootNode().isSame(rootNode):
                    _revealEditorTab(editor)
                    return editor
            if editors:
                editors[0].setRootNode(rootNode)
                _revealEditorTab(editors[0])
                return editors[0]

        return _nativeGraphEditorClass().acquire(rootNode)


## 把编辑器所在的那个 tab 切到前面（原生 `GraphEditor.acquire` 也这么干）。
# 浮动窗口里的编辑器父级是 Window，没有 tab 可切。
def _revealEditorTab(editor):

    parent = editor.parent()
    if isinstance(parent, GafferUI.TabbedContainer):
        parent.setCurrent(editor)


## 装上接管。`GAFFER_NETWORK_EDITOR_TAKEOVER=native` 可以关掉。
def installGraphEditorTakeover(force=False):

    global _nativeGraphEditor

    if _nativeGraphEditor is not None:
        return True

    if not force and os.environ.get("GAFFER_NETWORK_EDITOR_TAKEOVER", "") == "native":
        return False

    native = getattr(GafferUI, "GraphEditor", None)
    if not isinstance(native, type):
        return False

    _nativeGraphEditor = native
    GafferUI.GraphEditor = _GraphEditorProxy
    return True


def uninstallGraphEditorTakeover():

    global _nativeGraphEditor

    if _nativeGraphEditor is None:
        return False

    GafferUI.GraphEditor = _nativeGraphEditor
    _nativeGraphEditor = None
    return True


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
