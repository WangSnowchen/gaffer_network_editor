---
name: gaffer-qt-network-editor
description: 用 Qt（QGraphicsView）在 Gaffer 里另起一个节点图编辑器的标准做法：为什么原生 GraphEditor 改不动、和原生共用哪些数据、连线/nodule/形状怎么对齐原生、以及一整套必踩的坑。参考实现是 gaffer_network_editor 仓库（目标 Gaffer 1.7，1.7.1.0 实测；1.6 只作为版本差异记录）。
---

# Gaffer Qt 节点图编辑器（另起 QGraphicsView 视图）

想让 Gaffer 的节点图有现代观感（渐变 / 阴影 / 任意字号 / 矢量图标 / 连线渐隐）时的标准做法。
**先读这份，别从零摸索。**

## 参考实现

就是本仓库（路径都相对仓库根目录）：

| 路径 | 内容 |
| --- | --- |
| `python/networkEditor/` | 实现，分层的包：`constants` → `graph`（只碰 Gaffer）→ `layout` → `qt` → `backdrop_item` → `node_item` → `edge_item` → `view` → `panel` → `editor` → `register`，`__init__.py` 是门面 |
| `python/networkEditor/editor.py` | Editor 本体：信号、增量更新、菜单、接管 `GafferUI.GraphEditor` |
| `python/networkEditor/node_item.py` / `edge_item.py` / `backdrop_item.py` | 卡片、连线、Backdrop 的 `QGraphicsItem` |
| `python/networkEditor/view.py` | `QGraphicsView`：鼠标、键盘、命中、平移缩放 |
| `python/networkEditor/panel.py` | Tab 建节点面板 / 菜单转面板 |
| `python/networkEditor/layout.py` | 自动排列（分层布局） |
| `startup/gui/networkEditor.py` | 注册 |
| `tests/test_network_editor.py`、`test_optimizations.py`、`test_review_v070.py` | 无头测试 |
| `tests/e2e_network_editor.py`、`e2e_show_contents.py`、`e2e_panel_input.py` | 真机（screengrab / xdotool 真输入） |
| `tests/bench_layout.py` | 自动排列对照台 |

长篇版本在 `docs/`：`docs/pitfalls.md`（坑位全集）、`docs/gaffer-knowledge.md`（Gaffer 内部机制）、
`docs/architecture.md`、`docs/design-and-comparison.md`、`docs/testing.md`。

**验证跑的是哪一份代码**：环境里可能还有另一份同名 `networkEditor` 模块在 `PYTHONPATH` 上，
`import networkEditor` 谁先谁赢。screengrab 里打 `sys.modules["networkEditor"].__file__`
或 `NE.packageRoot()` 确认；夹具（`.gfr`）找不到通常就是跑到了别的副本。
**改了模块代码要重启 Gaffer**：`startup/gui` 里的 import 只跑一次，关掉再打开编辑器面板不会重新加载。

---

## 一、先搞清楚：原生 GraphEditor 改不动

GraphEditor 是 **OpenGL + 一个写死的 GLSL shader**（`src/GafferUI/StandardStyle.cpp` 里的字符串），
只支持纯色填充、一档圆角、一种深色描边、纹理贴图。**没有渐变、阴影、多层描边、任意字号、SVG。**

而且关键几个类**不能 Python 子类化**（binding 用 `RunTimeTypedClass` / `GadgetClass`，没给 wrapper）：

| 类 | binding | 能否子类化 |
| --- | --- | --- |
| `GafferUI.Style` | `StyleBinding.cpp:77` `RunTimeTypedClass` | ❌ |
| `GafferUI.GraphGadget` | `GraphGadgetBinding.cpp:283` `GadgetClass` | ❌ |
| `GafferUI.GraphLayout` | `GraphGadgetBinding.cpp:330` `RunTimeTypedClass` | ❌ |
| `GafferUI.NodeGadget` / `StandardNodeGadget` | 有 `NodeGadgetWrapper` | ✅ |
| `GafferUI.ConnectionCreator` / `PlugAdder` | 有 `ConnectionCreatorWrapper` | ✅ |
| `Gadget.renderLayer` | `GadgetBinding.h:156` `methodOverride` | ✅ 可 override |

**在原生视图里能改的全部**：

- metadata 5 个旋钮：`nodeGadget:color` / `shape`(仅 rectangle\|oval) / `minWidth`(默认 **10**，
  就是它让短名字节点看起来一样宽) / `padding` / `icon`+`iconScale`
- `StandardStyle` 8 个全局颜色 + `setFont`
- 圆角半径 = `renderNodeFrame` 的 borderWidth 参数（`renderFrameInternal` 里 `cornerSizes = padding / boxSize`），
  `StandardNodeGadget` 写死 `g_borderWidth = 0.5`，metadata 够不着；想改只能 override `renderLayer`

**结论**：要现代观感 → 另起 Qt 视图。QGraphicsScene 是矢量的，缩放不糊、无贴图，自带 BSP + culling。
**不要**走「Qt 画卡片 → 贴成纹理 → `Style::renderImage`」：每节点一张贴图，节点一多就崩。

---

## 二、和原生共用同一套数据（两个视图可同开互通）

| 东西 | 存在哪 | 备注 |
| --- | --- | --- |
| 节点位置 | `node["__uiPosition"]`（V2fPlug/Dynamic） | **中心点**，Gaffer y 向上 |
| 连线折叠 | `node["__uiInputConnectionsMinimised"]` / `__uiOutputConnectionsMinimised`（BoolPlug/Dynamic） | |
| Backdrop 框 | `node["__uiBound"]`（Box2fPlug） | |
| 选择 | `script.selection()`（StandardSet） | |
| focus | `script.getFocus()` / `focusChangedSignal()` | |
| 书签 / 注释 / 只读 | `Gaffer.MetadataAlgo` | |
| 形状 / 颜色 / 图标（含右键 **Show Name**） | 节点元数据 | Show Name 改的是 `nodeGadget:type`（`UIEditor.__setNameVisible`）；**必须连 `Gaffer.Metadata.nodeValueChangedSignal( node )`（3 参 `node, key, reason`）才会跟着变**，否则点了没反应 |
| focus 上下游链高亮 | 自己算 | 有的 overlay 扩展往 `connectionGadget:color` 上注册元数据做高亮，但它只挂在原生 GraphEditor 上 —— 只开自建编辑器时没人注册 |

四个 plug 名在装机版二进制里 grep 得到，可放心用。

### 增量更新，别全量重建

全量重建 63% 的时间花在逐个建节点 item（每个都要问原生 gadget 要尺寸 / nodule / `+` 号），
800 节点 240ms —— 每连一根线卡这么久没法用。按名字 diff 之后 **18ms**。信号怎么分：

- root 的 `childAdded/Removed` = 节点集合变了（diff + 边整体对 key）
- `nameChanged` = 那一个 item 重建（item 按名字存）
- `plugInputChanged` **报的是目的地节点**，只重收以它为终点的边
- 节点自己的 `childAdded/Removed` = 插口结构变了（提升 / `setup()`）→ 那个 item 重建
- 元数据 / `enabled` = 那个 item 重建；`__uiPosition` = 只挪位置

三个坑：①**动 item 期间要 `scene.blockSignals`**，否则删掉一个选中的 item 会发
`selectionChanged`，被当成"用户改了选择"写回 script，选择被吃掉；②**`ArrayPlug` 长一路
只有 `plugInputChangedSignal`**（NameSwitch/Collect 那种），信号不说"多了个接口"——
拿 `noduleLayout()` 和 item 上的接口对指纹；③增量不清 scene，临时 item（划线虚线）反而
更安全，只有全量重建才要先丢掉它们。

**光做 diff 还不够，第二刀砍"每次编辑都无脑做的 O(全图)"**：diff 之后 2000 节点改一根线
还要 44ms，profile 说 43ms 都是这三样 —— ①`collectNodes( root )` 扫全图拿节点集合
（9.3ms，只改线时**一次都不该扫**，用现成的 item 索引当节点集合）；②`updateFocus` +
`updateActiveState` 扫全图（9ms，只在**有新 item** 时做，focus / tracker 自己变化有各自的
信号，新建的单个 item 就地上色）；③`setSceneRect()` **会让整个视口失效**（包围盒没变就
别设）。砍完 **4.6–5.3ms 且和图的大小无关**（原生的数据层是 0.08ms，剩下的是 Python 常数）。

**`FullViewportUpdate` 是"改一根线重绘整屏"的元凶**（300 个节点就是 300 张卡片全重画）。
换 `SmartViewportUpdate` + `CacheBackground` 之后 300 → 18。前提是自绘的东西都能正确报脏区：
橡皮筋用独立的 `QRubberBand` **控件**（天然安全）、划线/临时连线用真的 `QGraphicsItem`
（`setPath` 内部会 `prepareGeometryChange`）、`drawForeground` 画的东西**自己在变化时
`viewport().update()`**。**验收只能在真屏幕上做**：`grab()` 永远重新渲染一遍、看不到残迹，
要用 `screen.grabWindow()` 抓屏幕内容再和强制 `repaint()` 后的逐像素比。

**接一根 ScenePlug 的线，`plugInputChangedSignal` 会沿下游链响 87 次**（`in.transform` /
`out.transform` 这些子插口的 pass-through 被重接了一遍）—— 整条下游链的节点都会进"脏"集合，
但它们的边一条没变。所以重收边时**先比 key、没变就一个 item 都不动**。

**给 item 开 `DeviceCoordinateCache` 不值**：平移一帧 300 节点 5.3→4.8ms、
800 节点 11→7.3ms、2000 节点 26.7→25.2ms，代价是每节点一张 pixmap（2000 节点约 50MB）+
每次缩放全部失效。平移的开销本质是 **item 数量**，真要解决只能做视口虚拟化。

**这类优化一律用"次数"做回归断言，别用时间**：改一根线时 `paint` 被调了几次、
`collectNodes` 被调了几次、item 被建了几个 —— 换台机器时间就变，次数不会。

### 原生的右键菜单有三套，全借

节点（`nodeContextMenuSignal`，含多选那一路 `nodeContextMenuSignal( True )`）、**插口**
（`plugContextMenuSignal`，官方注册了 8 处：提升 / 取消提升 / 改名 / 挪到哪条边 / Dot / Loop /
Collect / Shader）、**连线**（`connectionContextMenuSignal`，DotUI 的「插入 Dot」）。四个必踩：

①**这三个信号各有「类级 + 实例级」两份，弹菜单时两份都要发**（`GraphEditor.py:470-490`）。
原生访问器是 `classOrSelf` 混合式；自建编辑器不是它的子类，**必须自己建四个
`Gaffer.Signals.Signal3()` 当实例那份**（plug / connection / node / multiNode）并给出同签名的
访问器 —— 1.7 的 `_PlugVisibilityGadget.connectToEditor` 会往 Editor **实例**上连
`plugContextMenuSignal()`，而接管装着时 `isinstance( 我们, GraphEditor )` 为真、这个
connectToEditor 会落到我们身上，**缺方法就直接把编辑器构造炸掉**（`Editor._postConstructor` 里抛）。

②**整套节点菜单挂在多选那一路上，而且要无条件发**：`/Edit...` `/Enabled` `/Connections`
`/Focus` `/Show Contents...` `/Bookmarked` 注释全注册在 `nodeContextMenuSignal( True )`
（`startup/gui/graphEditor.py:116`），参数是**节点列表**；原生 `__buttonPress` 发它时
**没有「选了几个」的守卫**。只在多选时发 = **单选右键菜单整个空掉**（这是 1.6 → 1.7 的变化）。

③**菜单宿主要是 GraphEditor**（`DotUI.__insertDot` 要 `menu.ancestor( GraphEditor )`），
而且它拿 `menu.popupPosition()` 反算新节点位置 → 宿主是自己时要给出图坐标的真实屏幕位置。

④某个 handler 炸了会打断整轮发信号，但**之前已经填进去的条目仍然有效**，别一律 return False。

### 往外拖是中键

`GraphGadget::dragBegin` 里 `event.buttons == Middle` → `Sending`，拖 `script.selection()`；
左键才是移动节点 —— 照这个分法，自己的"中键平移"只要判「按在空白处」就完全不冲突。接线两点：
①GafferUI 的拖放靠**全局唯一**的事件过滤器，而它只装在 Editor 顶层 QWidget 上，事件被
`QGraphicsView` 吃了 → 自己往视图 + viewport 上再装一遍；②起拖**不能走 `buttonPressSignal`**
（返回 True 会吃掉 Qt 事件，自己那套点选/拖动全废），只补它需要的
`__lastButtonPressWidget` / `__lastButtonPressEvent`。

### 接管 `GafferUI.GraphEditor`（让写死它的地方也认得你）

官方 `EditMenu.scope()`（菜单栏剪切/复制/粘贴**作用在哪一层**）、`GraphBookmarksUI`、
`NodeFinderDialogue`、`BoxUI` 的 "Show Contents…" 全靠 `isinstance( x, GafferUI.GraphEditor )` 或
`layout.editor( GafferUI.GraphEditor )` 找编辑器。做法：把它换成一个**元类壳** ——
`__instancecheck__` 对你**和原生都为真**（原生不受影响、退路还在）、`__getattr__` 把类属性
转给原生类（startup 里的 `connect()` 挂的是原生类的信号，必须同一个对象）、
`__call__` **仍然构造原生的**（旧 layout 里写死的就是 `GafferUI.GraphEditor( script )`）、
`acquire()` 优先落到 layout 里的自家编辑器。配套必须在自己身上补
`graphGadget()` / `graphGadgetWidget()` / `frame( nodes, extend )`（`EditMenu` 直接调，
不补整条 Edit 菜单报错）。**最容易漏的**：自己找原生类时必须显式找**原生类**
（参考实现 `_nativeGraphEditorClass()`），否则接管后会把自己借给自己。

借来的原生右键菜单里那条 `Show Contents...` 的原生命令是 `GraphEditor.acquire`（1.7 是
`functools.partial( GraphEditor.__acquireNodes, nodeList )`），layout 里没有原生 GraphEditor
时它会现建一个 → 按**菜单路径**就地换成自己的"进层级"命令（`insertBefore` 保位，`append`
同名会挪到末尾）。

### 不建任何原生 GraphEditor 实例

"原生"要拆三层看：

| 层 | 是什么 | 成本 |
| --- | --- | --- |
| L1 | 隐藏的 GraphEditor | 真窗口，建一个 7.7ms、真建 QOpenGLWidget |
| L2 | 裸 `GafferUI.GraphGadget( script )` | 不是窗口，~0ms、不要 GL；给尺寸 / 接口位置 / `+` / 原生自动摆位 |
| L3 | 菜单内容与元数据 | 不是窗口 |

L1 只被三件事需要：①原生右键菜单命令的 `menu.ancestor( GafferUI.GraphEditor )`；②原生 NodeMenu
里「创建函数自己要 menu」的节点（Box/Backdrop/Reference/图像滤波）；③pipeline 通过
`GraphEditor.instanceCreatedSignal` 注册的快捷键。三步全部摆脱：

1. **菜单宿主改成自己**：接管装着时 `isinstance( 我们, GafferUI.GraphEditor )` 为真，
   `_Menu__popupParent` 设成 **`weakref.ref( self )`**（`Menu.parent()` 解弱引用，Menu.py:131-138）。
   借原生菜单时信号第一个参数传宿主；宿主是自己时压根没有实例级 `nodeContextMenuSignal` 之外的
   原生方法 → 用一个 `__hostSignal()` 判 None 只发类级那份（直接调会 AttributeError 被吞、
   表现成"三套原生菜单全空"）。加一个 `__getattr__` 诊断钩子记录"原生要过但我们没有"的属性。
2. **`graphGadgetWidget()` 返回一个壳**：只实现 `getViewportGadget()` / `bound()` / `size()` /
   `_qtWidget()`，**故意不做成 `GafferUI.Widget`**（`Widget.__init__` 会登记全局 owner 表 + 设
   `WA_StyledBackground`）。`getViewportGadget()` 返回一个只算不画的独立
   `ViewportGadget( graphGadget )`，每次调用同步 `setViewport( 视口像素 )` + `frame( 可见 scene
   矩形 → Gaffer 单位, y 翻转 )` —— 往返误差 0.013~0.022 单位（≈0.25px，raster 取整）。
   壳的 `bound()` 和取景按**整个编辑器**（含工具条）：原生 `EditMenu.paste` 拿
   `graphEditor.bound()` 算 raster。
3. **快捷键**：接管装着时主动 `GafferUI.GraphEditor.instanceCreatedSignal()( self )`
   （`Editor.__init__`（Editor.py:240）本来自己沿类层级发，per-class `Signal1`），pipeline 的
   handler 直接连**我们的** `keyPressSignal`。没接住的键**先发给自己**，没人要且有引擎才退回引擎。

`NodeMenu.nodeCreatorWrapper`（NodeMenu.py:98-150）要的 API 面只有：`graphGadgetWidget()` /
`graphGadget()`（`getRoot` / `getLayout().connectNode` / `positionNode`）/ `scriptNode()` /
`frame( [node], extend = True )` + `menu.popupPosition( relativeTo = gadgetWidget )` +
`getViewportGadget().rasterToGadgetSpace()`；`DotUI.__insertDot`(:136) 同前四样；
`BoxUI`(:115) 只要 scriptNode + graphGadget；`BackdropUI`(:50) 多 graphGadgetWidget；
`ReferenceUI`(:79) 多 `ancestor( Window )`。`StandardGraphLayout.connectNode/positionNode` **只要
gadget 不要 editor**，所以 L2 留着，零成本还换来和原生一致的数值。

两个开关当尺子（常驻在参考实现里）：`GAFFER_NETWORK_EDITOR_ENGINE=0/1` 强制不建 / 建引擎，
`GAFFER_NETWORK_EDITOR_GADGET=0` 不用裸 GraphGadget。接管装着时默认不建引擎；引擎那条路
留着当接管关掉时的退路。

**`graphGadget()` 一律给自己的裸 gadget 并连 `rootChangedSignal`**：pipeline 的跳层快捷键
用 `graphGadget().setRoot()` 换层，给引擎或借来的原生 gadget 视图就不动。

**ViewportGadget 的四条性质**（`Gadget`≈`QGraphicsItem`、`GraphGadget` = 节点图内容、
`ViewportGadget` = gadget 树的根 + 相机、`GadgetWidget` = 装它的真 QWidget，GL 在这一层；
原生 `GraphEditor.py:107-116` 就是 `ViewportGadget()` + `setMaxPlanarZoom(25)` + `GadgetWidget` +
`setPrimaryChild(GraphGadget)`）：

1. 默认就是 2D 相机（`getPlanarMovement()==True`），**默认视口 `V2i(640,480)`**（不 setViewport 就
   按它算，没显示过的引擎算出 nan 就是这条的极端情况）；
2. `frame( box )` = 把整个框装进视口，宽高比不同往长边扩 → 喂 `mapToScene( viewport.rect() )`
   得来的框天生同宽高比、精确；
3. **改视口尺寸不会自动重新取景**（`setViewport` 只改画布、每单位像素不变）→ 缩放/平移/resize 都要
   重新 `setViewport + frame`，或者"用之前同步一次"；
4. **y 轴相反**（raster y 向下、gadget y 向上），`rasterToGadgetSpace` 返回 `LineSegment3f` 取 `.p0`。

裸建不需要窗口/GL。两条约束：①**一个 gadget 只有一个父**，挂给第二个 ViewportGadget 会**抢走**
（原来那个 `getPrimaryChild()` 变 None）→ 绝不挂借来的真 GraphEditor 的 gadget；
②`rasterToGadgetSpace( gadget = X )` 对不在树里的 X 给同样答案（顶层变换是单位矩阵）。

### 其他共用数据层的要点

**`ContextTracker` 是异步的，别在它算完之前刷状态**：焦点刚变的那一下 `isTracked()`
全是 False，照着刷会把整张图先刷暗一帧再亮回来（"点 focus 闪一下"，图里只有一个节点时最明显）。
`updatePending()` 为真时直接 return，等它的 `changedSignal`。计算线程的 `errorSignal` 先
`executeOnUIThread` 再碰 UI。

**"一眼找到这个节点"的标记（focus 角标 / 书签）要放在 LOD 早退之前，还要按 `1/lod` 反向
补偿**：它们恰恰是镜头拉远时最需要的东西，画在 `lod < LOD_NEAR : return` 后面就等于
"一拉远就没了"。补偿要夹 lod 下限，见「五、坑位清单」。

**材质节点的类型分不出来别怪自己**：`ArnoldShader.loadShader()` 之后**所有** Arnold 材质的
`type` 都是 `ai:surface`（image / noise / color_correct 全一样）。靠得住的是 `name` 关键字 +
**`out` 的插口类型**（`ClosurePlug` = 真材质，`Color3f/4f` = 纹理或工具）。

**"这个复合插口展开了没有"只认 `compoundNumericNodule:childrenVisible`**：Arnold 材质的 `out`
根本没注册 `nodule:type`（CompoundNumericNodule 是 Gaffer 按插口类型给的默认 nodule），
卡着 `nodule:type == "GafferUI::CompoundNumericNodule"` 判的话，原生菜单点了
"Expand RGB Components"、卡片上却不长子圆点。

**`+` 上丢连线要弹隐藏参数**（材质节点的 `+` 就是干这个的）：背后是一堆
`noduleLayout:visible = False` 的插口，照原生 `PlugAdder::plugMenuSignal` 的路子 ——
一个候选直接接、多个弹菜单让人挑，挑中的**显示出来 + 接上**放进同一个 UndoScope。

**注释和书签照抄 `AnnotationsGadget`**：注释从 `V2f( b.max.x + 0.5, b.max.y )` 起画
（节点**右上角外侧**，不是下方）；书签图标画在 `V2f( b.min.x, b.max.y )`（**左上角**），
收藏是书签图、只有数字书签是星星图，**数字另外写在图标左边** —— 两者同时存在时是
"图标 + 数字"，不是互相顶掉。

**连线的二次编辑照抄 `StandardConnectionGadget`**：`endAt()` 只有**靠近两端**才算抓住
（灵敏区 = `clamp( 线长/4, 2.5, 25 )` 个单位，中段故意不响应，不然长线上随手一点就把线
拽走）；抓目的地那头 = 手里攥着**源插口**去找新输入，抓源那头 = 攥着**目的地插口**去找
新输出；**落在没人接的地方就断开**（原生 `dragEnd` 原话：noone wanted the drop so we'll
disconnect）。改接和拆旧连接进**同一个 UndoScope**。另：**`plug.settable()` 不是「能不能
改接线」** —— 已经被驱动的输入插口它是 False，判据要用 `MetadataAlgo.readOnly()`。
**按在已连接的输入圆点上 = 断连/改接手势**：先查以这个插口为终点的边，走"改接"那条路；
只走"新建连线"会让"断开"静默无效 —— 测试要断言画出来的边/手势，光断言 `getInput()` 抓不到。

**插口元数据要单独连信号**：`Metadata.nodeValueChangedSignal( node )` 只报节点自己的；
插口上的（`noduleLayout:*` / `nodule:*` / `compoundNumericNodule:childrenVisible`）得连
`Metadata.plugValueChangedSignal( node )`（3 参 plug/key/reason）。圆点右键
「Expand RGB Components」改的就是**父插口**上的 `compoundNumericNodule:childrenVisible`。

**缩放要设上限**：原生是 `viewportGadget.setMaxPlanarZoom( imath.V2f( 25 ) )`
（每个 Gaffer 单位最多 25 像素），`fitInView` 之后也要夹一次，否则框一个小节点会一路
放大到几十倍。

**每一层的视野要各记一份**：换 root 之后无脑 `frameAll()` 的话，「放大盯着某个 Box 看 →
进去 → 出来」出来就是全景。原生 GraphEditor 把 frame 存在历史条目里
（`GraphEditor._HistoryWidget.__createHistoryEntry` / `__frame`），照抄：换层前按
**节点**记下当前可见的那块区域，到了新的一层先查有没有记过，有就 `fitInView` 回去，
第一次来才取全景。键不能用节点名（会改名），拿节点对象 + `isSame()` 比；条数封顶（20）
免得攥着已删节点不放。当前层改名要刷标题，被移出图要退回脚本根。

**节点创建 / 自动连接 / 粘贴摆位直接复用原生**（`NodeMenu` + `StandardGraphLayout`）：
`graphGadget().getLayout()` 正好给 `connectNode` / `connectNodes` / `positionNodes` / `layoutNodes`。

---

## 三、几何直接问原生要，别自己算

节点大小 / 接口位置 / 出射切线全部从原生 gadget 上取，这是「看着不一样但用起来没区别」
最省事也最准的一条：

```python
gadget = graphGadget.nodeGadget( node )
bound  = gadget.bound()                              # 节点大小（Gaffer 单位）
nodule = gadget.nodule( plug )                       # 复合插口直接传子插口也行
centre = nodule.transformedBound( gadget ).center()  # 接口位置（相对节点中心）
tangent = gadget.connectionTangent( nodule )         # 连线出射方向
```

- **裸 `GafferUI.GraphGadget( script )` 就能用**：不需要 GraphEditor、不需要 GL 上下文，
  无头能跑，而且**不会**去建 `__uiPosition`（那是 GraphEditor `preRender` 才做的）。
- **原生尺寸实测值**（1.7.1.0，Gaffer 单位；和 1.6 一致）：StandardNodeGadget `11.000 x 4.164`、
  DotNodeGadget `2.5`、AuxiliaryNodeGadget（Expression / Spreadsheet / Random）`2 x 2`。
- **⚠ 宽度只能拿原生当下限，不能死守**：原生那个宽度是按**它自己的字体**、而且不含
  类型图标算的。Qt 字体和图标都不一样，死守就会截字（出现过 `Create...tSetup`）。
  做法：`宽 = max( 原生宽, 图标 + 名字 + 边距 )`，高度照原生；卡片撑宽后**原生给的接口 x 坐标
  要按同一比例拉开**，否则边上的圆点会落进卡片里。名字别用 `elidedText`，图标也别写成
  「放得下才画」—— **截字和丢图标比尺寸差几像素严重得多**。
  公式：`宽 = max( nodeGadget:minWidth(默认10), 名字宽 + 2 ) + padding(默认1)*2 - 0.5*2`，
  高 = `max( 4.164, 侧边接口数 * 1.2 + 2.4 )`。
- **名字宽度**用原生字体度量：`GafferUI.Style.getDefaultStyle().textBound(
  GafferUI.Style.TextType.LabelText, name )`。
- **Expression / Spreadsheet / Random 不是胶囊，是 2x2 的小方块 + 一个首字母**
  （`nodeGadget:type == "GafferUI::AuxiliaryNodeGadget"`、`auxiliaryNodeGadget:label`）。
  它们同时也标了 `nodeGadget:shape=oval`，判断顺序要先看 `nodeGadget:type`。
- ⚠️ **拿原生 gadget 量子圆点，先 `nodeGadget.bound()` 一下**：里面那些 `LinearContainer`
  是**懒排**的，没问过尺寸就 `nodule( plug ).transformedBound( ng )` 拿回来的是**父容器
  局部坐标**（看着像"原生位置是 (0,0)"）。写对拍测试时最容易中。

### 配色也全在元数据里，别自己发明

| 画什么 | 读哪个键 | 谁注册的 |
| --- | --- | --- |
| 节点颜色 | 节点上的 `nodeGadget:color` | 原生 `startup/gui/graphEditor.py`（SceneProcessor 紫 / SceneElementProcessor 蓝 / GlobalsProcessor 绿 / Transform·Constraint 棕 / TaskNode 红 / EditScope 蓝 / Expression 绿 / Spreadsheet 橙 / SubGraph·BoxIO 灰）+ 各站点 startup（可能给 `Gaffer.Node` 注册一个万能默认灰、给灯光注册黄） |
| **接口圆点颜色** | 插口上的 `nodule:color` | 同一个文件按**插口类型**注册：ScenePlug `#3d577c`、FilterPlug `#b0893a`、FloatPlug 蓝、Color3fPlug 橙、V3fPlug 红、TaskPlug 红 |
| 连线颜色覆盖 | dst 插口上的 `connectionGadget:color` | TaskPlug 有；插件也拿它做高亮 |
| 都没有 | StandardStyle `RaisedColor` = `#666666` | |

**「看圆点认类型」靠的就是 `nodule:color`**。这些注册都在 **`startup/gui/`** 里，
`gaffer env python` **不跑 gui 启动脚本** —— 无头探测到的全是 None，要在 screengrab（GUI 上下文）里量。

判断「这个节点其实没有类型色」：拿 `Gaffer.Metadata.value( Gaffer.Node(), "nodeGadget:color" )`
取那个万能默认色比一比（`Metadata.value` 不收 Python 类，只能拿实例）。

### 两件原生"在渲染时才做"的事，自己必须补

1. **没摆过位置的节点要自己跑自动布局**。Box 内部的节点常常没有 `__uiPosition`，
   原生是在 `GraphEditor.__preRender` 里现算的：
   ```python
   nodes = Gaffer.StandardSet( [ g.node() for g in graphGadget.unpositionedNodeGadgets() ] )
   graphGadget.getLayout().positionNodes( graphGadget, nodes, fallbackPosition )  # 摆到视野中心
   graphGadget.getLayout().layoutNodes( graphGadget, nodes )                      # 再排整齐
   ```
   算完顺手写进 plug，**不进撤销栈**（原生就是在渲染回调里直接写的）。不补这一步，进 Box
   看到的就是一堆挤在一起 / 斜着排的节点。
2. **一个节点里插口名会重复**：NameSwitch 上 `in.in0.value` / `in.in1.value` / `out.value`
   全叫 `value`。位置 / 颜色 / 切线 / 连线 key / 接口指纹的字典拿 `getName()` 当键会互相覆盖 ——
   表现是「多个输入接口只剩一个，而且上下串位」或「原生画着的连线我们这边少一根」。一律用
   **节点内相对名** `plug.relativeName( node )`。接口挂哪条边按原生 `connectionTangent()` 分，
   元数据推的边偶尔对不上。
3. **`+`（PlugAdder）只能自己画**。它在 C++ 匿名命名空间里，没绑到 Python ——
   `nodeGadget.children()` 拿回来的是个光秃秃的 `Gaffer::GraphComponent`，连 `bound()`
   都没有。详见「五、对齐原生的语义 → `+`」。
4. **注释里的 `{xxx}` 要替换**。`AnnotationsGadget::substitutePlugValues`：
   `{插口路径}` → 该插口的值（照 `formatPlugValue`），找不到就换成空。照抄 `annotation.text()`
   会在节点旁边画出一个字面的 `{name}`。

---

## 四、建节点面板 / 菜单转面板

### 让 pipeline 快捷键的菜单也走自己的面板

pipeline 通过 `GraphEditor.instanceCreatedSignal` 注册的快捷键（例如 S / Q 菜单）的处理器都是
「造一个 `GafferUI.Menu` 然后 `popup( editor )`」。想让它们长成自己的样子：**转发按键期间
临时把 `GafferUI.Menu.popup` 换掉**，把 Menu 截下来、拿它的定义用自己的面板画，完事再换回去。

```python
originalPopup = GafferUI.Menu.popup
captured = []
GafferUI.Menu.popup = lambda menu, *a, **kw : captured.append( ( menu, a, kw ) )
try : handled = target.keyPressSignal()( target, event )
finally : GafferUI.Menu.popup = originalPopup
```

- **定义挂在 Qt 对象上**：`menu._qtWidget()._Menu__definition`（`Menu.__init__` 里写的是
  `self._qtWidget().__definition`），标题是 `menu._Menu__title`。定义可能是 callable。
- **必须递归钻 `subMenu`**：这些菜单顶层常常清一色是子菜单，不钻一条都拿不到。子菜单本身也可能是 callable。
- **Gaffer 信号是「第一个返回 True 的就截住」**，测试探针要用没人要的键（F5）验证链路。
  转发完再看一眼 root 有没有被切走（跳层那类），跟着切过去。

### 条目求值一律照抄原生 `Menu`

- **`Menu.__argNames` / `__evaluateItemValue`**：看穿 `Gaffer.WeakMethod`、函数式 `active`
  带 menu 求值、灰掉的子菜单整个点不动、点下去再问一次 active。
- ⚠️ **勾选型条目（`checkBox`）必须把勾选状态传给命令**：原生 `Menu.__actionTriggered`
  （`Menu.py:194-209`）对 checkable 条目会把「点完之后」的勾选状态塞进命令的**第一个位置参数**
  （命令自己声明了 `checkBox` 参数的话走关键字 `checkBox=`）。很多命令签名就是
  `command( state, script, … )`，`state` 是留给它的。裸调 `command()` → `TypeError`。
  `checkBox` 可以是函数（照 `Menu.__evaluateItemValue` 求值，要 `menu` 就传），传 `not 当前值`。
  面板上把勾画出来（名字**左边留白**里点一个 `✓`，别挤名字）。
- **别写「命令一抛就退回原生菜单」的兜底**：那类菜单常是 `searchable=True` 的，退回去弹出来
  长得和原生 Tab 栏一模一样 —— 「参数没传对」会被伪装成「点一下又弹出原生菜单」。
  "点一下就回到原生"类的现象，先查有没有吞掉的异常。

### 级联面板的结构

- **一列一个窗口，别用一个大框装所有列**：一个窗口只有一个高度 —— 跟着最长那列变就是
  「展开一级长高一次」，定死就是「第一列条目少时下面一片留白」。**原生 QMenu 之所以两头都对，
  就是因为每级菜单各自一个窗口、各自按自己的内容定高** —— 照抄：根窗口 = 标题 + 搜索框 + 第一列
  （高度只看第一列条目数），第二列往后各自一个窗口，顶端对着**展开它的那一行**的行顶（记住 anchorRow），
  一列接一列往右排，右边放不下就翻到左边。列数设上限（4），再深就把最左边那列顶掉。
- **子列窗口必须是嵌套 `Qt.Popup`**：`Qt.Tool` / `Qt.ToolTip` 会被 Qt 当成「点在 popup 外面」，
  第一下点击就把整个面板关了；嵌套 popup 被认成「点在另一个 popup 上」，不会关。代价是
  **鼠标事件只发给最上面那个 popup** —— 鼠标退回左边那些列时，事件以「窗口外的坐标」落在
  最上面那个窗口上，得自己按全局坐标派发（QMenu 内部也是这么转发的）。三个连着的坑：
  ①窗口上**不 `setMouseTracking( True )` 就收不到"没按键的移动"**，这条路直接哑掉（只有
  **真鼠标**测得出来，无头直接调派发函数是绿的）；②「点在外面就关掉」要把**自己窗口的边距 /
  标题 / 搜索框**排除掉；③**已经摆好的子列窗口别重复 `move()`** —— 窗口 map 之前 `move()`
  给的是外框位置、map 之后是内容位置，来回 move 每次漂 2px。
- **列里的滚动条也要自己转发**：嵌套 popup 下第一列自己的滚动条收不到原生 press/move →
  按滚动条本地坐标现造 `QMouseEvent`、`QApplication.sendEvent` 直发，加一个滚动拖拽状态机。
- **滚轮也一样**：Qt 只发给光标底下那个控件，光标在搜索框 / 标题 / 边距上时滚轮到不了列表。
  面板和每个子列窗口各挂一个 `wheelEvent`，统一按全局坐标派发（压着哪列滚哪列 → 没压着列表就
  滚光标所在那个窗口的列 → 再不行滚第一列）。**只有真滚轮测得出来**（xdotool `click 4` / `click 5`）。
- **一列一个窗口之后出图要自己拼**：`grab()` 只拿得到根窗口，按全局坐标把几个窗口画到一张图上。
- **「进下一级，上一级不能动」**：①`QHBoxLayout` 默认把每个控件拉到行高 → 右边开出一列长的会把
  左边已经摊开的列**一起拉高**。每列自己 `setFixedSize( 列宽, 自己的行数 × 行高 )` +
  `addWidget( w, 0, AlignTop )`。②别把「当前层级」写进标题：标题从无到有，整块面板连第一列一起
  往下挪一行。验收**逐像素比几何**（`column.geometry()` 前后必须完全相同），而且面板得**真的
  `popupAt()` 弹出来**再量 —— 没 `show()` 的面板布局压根不生效。
- **`widget.isVisible()` 在面板还没 `show()` 时恒为 False**，拿它算高度或判断「要不要收起某一列」
  都会错。用和显示无关的判据（有没有文字 / 有没有内容）。
- **`QtGui.QGuiApplication` 在 Qt.py 这层壳里不存在**（`hasattr` 实测 False）。「别让弹窗跑出屏幕」
  常见写法 `QtGui.QGuiApplication.screenAt( pos )` 在 Gaffer 里**每次都 AttributeError**，被
  `except` 一吞就退回主屏夹坐标 —— 多显示器下鼠标在副屏按 Tab，弹窗被硬夹回主屏。用
  `QtWidgets.QApplication.screenAt()`，再兜一层遍历 `screens()` 找 `geometry().contains()`；
  **问不出是哪块屏就别夹**。Qt 跨屏移动 popup 本身没问题，别怀疑窗口管理器。
  顺带：`QRect.right()` 是**含端点**的 `left+width-1`。
- **`Qt.Popup` 的原生窗口在「创建那一刻」就认下 transient parent**：面板缓存在编辑器上，
  Gaffer 换布局是把编辑器控件整个 reparent 到另一个窗口 —— 控件对象没变，光比 `parentWidget()`
  看不出来。每次弹之前比 `view.window()`，变了就 `setParent( window, Qt.Popup )` 重挂。

### 悬停高亮与预选

- **悬停高亮只能自己用"当前行"做，别碰 Qt 的 `State_MouseOver`**：`QListWidget` 要
  `setMouseTracking( True )` 才发 `itemEntered`，`itemEntered` 里把那行设成**该列的当前行**
  （QMenu 手感，更左边那些列的高亮留在原地正好显示"现在展开的是哪一条"）。**delegate 里一旦画上
  `State_MouseOver` 就会留残留**：不是最上面那个 popup 的列收不到真鼠标事件，Qt 内部的 hover 状态
  停在最后划过的行上清不掉。
- **新开的列 `setCurrentRow( -1 )`，别预选第一行**（原生 QMenu 打开子菜单也不预选）。
  **只有搜过的时候**预选第一条，好让回车直接建出最匹配的那个。
- **用 xdotool 做真鼠标测试时，光标已经在目标点上就不会发 motion 事件**（`itemEntered` 不来，
  表现为"偶发某一列没开出来"）—— `mouseTo()` 里先挪到旁边几像素再挪过去。
- 这类"亮几行"的毛病**只能数像素验**：抓每一列的图，逐行取底色，断言亮着的行恰好等于
  `[ currentRow ]`（灰底 r=g=b，高亮偏蓝，一句 `blue > red + 8` 就分得开）。

### 分层与平铺

- **面板要分层，别摊平**：NodeMenu 能有 600+ 条。没输搜索词时只列当前层的大类（右边写「229 items ›」）+
  落在这一层的条目，点进去看下一层，`←`/`Backspace` 返回；一输搜索词就**全局扁平搜**。
- 条目少于 50 条就直接平铺 —— **但还要「只有一个顶层分类」**：分组子菜单（三个、六个分组的那种）
  照条数平铺会把分组摊成一坨，原生这里就是几个子菜单，照分组分列才对。
- **分节标题当一种行画**（另一个 data role + `NoItemFlags`）：上下键要**跳过去**、鼠标划过
  **不高亮不展开**、点它什么也不发生。

### 一行的排版：名字绝对优先 + 列宽跟内容走

一行里「左边名字 + 右边层级/路径」两块文字，**宽度必须先分配再各自截** —— 两块都 `drawText`
到同一个矩形（一个 AlignLeft、一个 AlignRight）迟早叠在一起（B 找书签那列右边就是节点在图里的整条路径）。
**所有面板共用同一个 delegate**，改一处就是 Tab 建节点 / 找书签 / 菜单转面板 / 选隐藏参数全好。

- **浏览态不写右边的层级**（层级本来就摆在眼前，一列就是一级），只有**搜索结果**才写。
- **名字绝对优先**：名字要多少给多少，右侧拿剩下的、给个上限（200px），剩不下 30px 就整块不画；
  路径用 `ElideLeft` 截头留尾（`… / Primitives`）。别给名字设"最小宽度"然后两边各截。
- **列宽按「列里最长那行一个字都不截要多宽」算**，下限是原来那个固定宽度（300/250）、上限 720px，
  行数到滚动条门槛再加一根滚动条的宽度。
- ⚠️ **宽度算得「刚刚好」等于没算**：`QFontMetrics.horizontalAdvance()` 和实际排版差一两像素，
  宽度正好等于文字宽度时 Qt 照样 elide。留 2-3px 余量，**而且分宽度时要把这几像素算进名字那一份**，
  否则右边那块立刻把余量吃回去。
- 验收数像素：渲染一行、扫每一列有没有字，断言「一行里最宽的那段空白」够宽；
  **扫的时候跳过最上面几行 y**，分节标题那条 1px 分隔线通到头，算进来永远找不到空白列。

### 建节点条目必须自己接手

- 这些菜单里的条目大多是 `NodeMenu.nodeCreatorWrapper` 包出来的，里面写死了
  `assert menu.ancestor( GafferUI.GraphEditor ) is not None` —— 面板不是菜单，直接调必然
  `AssertionError`。认法：`command.__code__.co_freevars` 里有 `nodeCreator`。拆闭包取原生创建函数 ——
  `command.__code__.co_freevars` + `command.__closure__` → `nodeCreator` / `plugValues` /
  `postCreator`，自己 `UndoScope` 里跑，再走原生 `connectNode` / `positionNode`。
- **拆不出创建函数的，也别退回原生菜单**（在自己面板里打完 "box" 回车又冒出原生搜索框要重打一遍）。
  `Box` / `Backdrop` / `Reference` / 图像滤波那几个都是 `nodeMenuCreateCommand( menu )`，只要
  `menu.ancestor( GafferUI.GraphEditor )`（`Reference` 还要 `ancestor( Window )` 当文件浏览器的父窗口，
  给不了就是 None，照样能弹）。做法：**现造一个没弹出来的 `GafferUI.Menu( IECore.MenuDefinition() )`**，
  补上 `Menu.popup()` 本来会写的两个私有属性 `_Menu__popupParent`（weakref 到宿主）和
  `_Menu__popupPosition`，调完还原。截得到真菜单就用真的。
- **`Backdrop` 那条是 `nodeMenu.definition().append( path, { "command" : ... } )` 直接挂的裸函数**，
  没有 `nodeCreatorWrapper` 闭包。统一按**「命令要不要 `menu` 参数」**
  （`inspect.getfullargspec( fn ).args`）兜底就都覆盖了。
- **借宿主跑原生创建命令的尾巴**：①原生摆位拿弹出菜单的 raster 坐标反算图坐标
  （`popupPosition( relativeTo = gadgetWidget )` → `rasterToGadgetSpace`），宿主视口退化时算出 `nan`。
  建完统一检一遍位置（`math.isfinite`），坏的、以及没连上任何东西的，摆到鼠标那儿。
  **有选中节点时建的 `Backdrop` 例外** —— 它已经框住那些节点了。②原生 `nodeCreatorWrapper` 最后一句是
  `graphEditor.frame( [ node ], extend = True )` —— 宿主是借来的真 GraphEditor 时用户那边的视野会被
  拽走，跑之前把 `frame` 临时换成空函数（实例属性，用完 `__dict__.pop`）。③摆位**别包 `UndoScope`**
  （原生也在 scope 外），包了的话建一个节点得按两次 Ctrl+Z。
- **NodeMenu 是非模态的**，弹出后立刻查「新建了什么」查不到 → 连 `visibilityChangedSignal`，菜单关掉再 idle 一拍才收尾。
- **`NodeMenu` 挂在 `applicationRoot._nodeMenu` 这个 Python 属性上**，Boost 包装对象只有 **Python 子类**
  才保得住身份。真实 Gaffer 的 root 是 Python 子类（`Gaffer.Application` 里的
  `_NonSlicingApplicationRoot`）；**无头测试里直接 `Gaffer.ApplicationRoot()` 拿到的菜单永远是空的**，
  测试要自己派生一个子类。另：裸 `gaffer env python` 不跑 gui 启动脚本 → NodeMenu 是空的，别当回归。

### 搜索要分档

**别只写「连续命中 + 子序列」两档**。用户常打**首字母缩写**（`ass` → aiStandardSurface）。两档模型下
`ass` 先给一堆名字里含 "ass" 的（Glass / ShaderAssignment），要的那个掉进子序列档。按**证据强度**分档：

| 档 | 命中什么 |
| --- | --- |
| 0 | 名字前缀（`sph` → **Sph**ere） |
| 10 / 20 | **首字母缩写**（`ass` → **a**i**S**tandard**S**urface）/ 缩写的前缀 |
| 50 + 位置 | 词中命中（`ass` → Shader**Ass**ignment） |
| 200+ | 首字母串里命中 / 首字母子序列 |
| 400+ | 按词头分段吃掉（`aistand`、`stdsurf` —— 每段压在词头，段内可以省字母） |
| 1000+ | 随便什么子序列（兜底） |

- 切词：`[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z][a-z0-9]*|[0-9]+`（驼峰 + 连续大写算一个词，
  `_ - . /` 和空格天然是边界），`lru_cache` 一下，每次敲键都要跑几百条。
- **缩写档必须排在「词中命中」前面**；单个字母不走缩写档；空格当**与**。
- **搜索认的是条目自己的 `searchText`**：NodeMenu 叶子标签是**带空格的显示名**（`Standard Surface`），
  `searchText` 才是 `aiStandardSurface`。测试里按显示名断言一定挂。
- 两条都命中缩写时按名字长度分先后就够了 —— 别发明更聪明的规则，「常用」的加权自己会把常用那个顶上来。

### 「常用 / 喜爱」

根层最上面两节 —— 喜爱是自己钉的（顺序 = 加入顺序），常用按用过多少次自动排（最多 8 条）。

- **钉住的动作要"顺手"**：右键**按下就钉**、不建节点、不关面板（`Ctrl+D` 同义）。面板的鼠标事件是
  自己按全局坐标派发的，所以 **button 得自己从派发函数一路带进来**，Qt 的 `contextMenuEvent` 到不了各列。
- 钉住 / 用得多的在**搜索结果里各减一点分**（喜爱 -8、次数 -min(n,6)）—— 只在同一档里冒头。
- 收藏一变行数就变，**重填之后按 key 找回选中行**，别按下标。
- 记录**跟人走不跟文件走**：`~/.gaffer_network_editor/nodeCreator.json`（`$GAFFER_NETWORK_EDITOR_STATE_DIR`
  可搬，测试一律指到临时目录），先写 `.tmp` 再 `os.replace`；**读不出来 / 坏了一律当空的**。
  榜单里有、菜单里已经没有的条目（卸了的插件）要**当场滤掉**。
- 榜单只给**建节点**那个面板；快捷键借来的菜单不带。

画图 / 测试上的坑：

- **1px 分隔线要关掉抗锯齿**（开着 AA 时半个像素落在矩形外，肉眼和像素断言都看不见）。
- **面板 `popupAt()` 之后别 `EventLoop.waitForIdle()`** —— offscreen 下那一趟事件循环会把 `Qt.Popup`
  关掉，用 `QApplication.processEvents()`。星星 / 标题这类画法要验，就把 delegate 单独渲染进一张
  `QImage` 数像素（真窗口 `grab()` 有**亚像素抗锯齿**，橙色边缘会把"金色像素"计数打乱）。
- **Tab 面板一个 tooltip 都不要**：它是"扫着找、找到就回车"的用法，划过一行冒一个提示、Qt 提示消失
  又慢，会糊住下面几行。测试里留一条反向断言（每行 `toolTip()` 必须空）。

---

## 五、对齐原生的语义（不照抄就"看着像但不对"）

### 选择（点选 / 框选）

逐条抄 `GraphGadget::buttonPress`（1035 一带）与 `GraphGadget.cpp:1565`：

- **点已选中的节点**：Ctrl 才取消选中；否则**什么都不动**（好让你拖整组）。
- **点没选中的节点**：没按 Shift/Ctrl 先清空，再加进去。
- **Alt+Shift / Alt+Ctrl 点**：连上游 / 下游一起选。
- **点 Backdrop**：连它框住的节点一起（Ctrl 时只动它自己，`GraphGadget.cpp:1056`）。
- **空白处按下**：清空选择，除非按着 Shift/Ctrl。
- **框选**：原生**完全框住才算**（`boxContains`），Ctrl 是减选。参考实现对节点故意改成
  "相交即选"（Nuke/Houdini/Maya 手感，代码和文档里写明是故意的），**Backdrop 仍要求整个框住** ——
  它盖一大片，相交就算的话在它上面框几个节点必然把它一起选上、一拖整组搬走。

Qt 那套对不上：自带橡皮筋只有「相交即选中」+ Ctrl 加选。只能 `setDragMode( NoDrag )`
自己用 `QRubberBand` 画、自己判。按下节点时**要把修饰键抹掉再交给基类**（合成一个
`NoModifier` 的 `QMouseEvent`），否则 Qt 会用自己那套把选择改回去，同时又不能不交给它 —— 拖动是它做的。
选择同步按 `isSame()` 比，只认 `parent().isSame( root )` 的（每个 Box 里都有 `in`/`out`，裸名字会撞）。

### 拖连线的落点（吸附 + 放大）

原生 `StandardNodeGadget::closestDragDestination`：拖着连线经过一个节点时，在它身上
**所有可见、接得上的 `ConnectionCreator` 里挑离鼠标最近的那个**（`transformedBound` 求距离），
`setHighlighted( true )` 让它放大（`renderNodule( 1.0 )`），整块卡片也 `setHighlighted`；
连线末端直接**吸**到那个接口的位置和切线上，松手不用精确点中圆点。

- **它会替你挑插口**：只要落在节点身上，它就给你一个最近的接得上的插口（哪怕光标离得老远）。
  所以 `+`（PlugAdder）这种"落点优先级更高"的东西，判据**不能**是"没挑到插口"，必须是
  "光标没正压在某个圆点上" —— 否则 `+` 永远抢不过它。
- **原生吸附很黏**：ArrayPlug 上"最近的接得上的"是第一个**空槽**（排在一排圆点的最后），看着像
  "总是吸到最后一个"。改手感只在**视觉**上加一道吸附距离（26px），**别动"松手接哪个"的判据**。
- **圆点画在卡片边界上**（顶边那排还在卡片外 2px），而 `shape()` 只比卡片大一圈 —— 瞄着圆点丢连线时
  光标常常整个落在节点外面。松手时在光标周围（28px）再捞一遍最近的节点；`noduleAt` 也补同样的兜底。
- **拖端点改接时，原来那根线要立刻藏掉**（原生拖的时候就不画它了）：接上了下一拍重建自然收掉，
  **接不上要原样放回去** —— 只有"丢在空白处"才算断开。
- 拖连线过来时把这个节点上接得上的那几个接口标签亮出来（原生 `dragEnter`）。

### "把节点塞进一根连线"

原生 `GraphGadget::updateDragReconnectCandidate`：拿**节点中心** ±2 单位那一小块去找线（不是鼠标位置），
**只在拖单个节点时**做；插口配对五条判据：只认有 `correspondingInput` 的输出、两头都 `acceptsInput`、
那个输入必须还空着、输出在这张图里不能已经接了别人、两个插口都得画着圆点。
松手 `in ← 上游` + `下游 ← out`，一步撤销。

### nodule（接口圆点）

- **有没有 nodule**：`nodule:type == ""` 明确隐藏、`noduleLayout:visible == False` 隐藏，
  **`__` 开头的插口一律没有**（`NoduleLayout::layoutOrder()` 一进循环就 `starts_with( "__" ) → continue`，
  子插口同理）。第三条不判，Expression 的 `__in`/`__out` 会被当成有 nodule，连线一半实线一半虚线。
- **ArrayPlug 要摊开**：`nodule:type == "GafferUI::CompoundNodule"` 标记的插口，nodule 画在**子插口**上
  （`GafferSceneUI/SceneProcessorUI.py:58` 的 lambda）。写个 `nodulePlug( node, plug )` 把任意深度插口
  解析到「画着 nodule 的那一层」。
- **挂哪条边**：`noduleLayout:section`，缺省 **输入 top / 输出 bottom**（`NoduleLayout.cpp` 的 `section()`）
  —— **Gaffer 的图和 Houdini 一样是上→下流的**。材质节点是例外：参数 left、`out` right
  （`GafferSceneUI/ShaderUI.py:154/207`）。
- **标签**：`noduleLayout:label` 优先，否则插口名（`StandardNodule.cpp:236`）。
- **尺寸与悬停**：平时 `renderNodule( 0.5 )`，鼠标移上去 `renderNodule( 1.0, HighlightedState )`
  —— **半径直接翻倍 + 换成 HighlightColor**。
- **接口标签有三个显示条件，一个都不能少**（原生 `StandardNodeGadget`）：①**悬停整个节点**就把该节点
  所有接口名字显示出来（`labelsVisibleOnHover` 默认开）；②节点右键 `/Connections/Show Input·Output Labels`
  写的是 `nodeGadget:input/outputNoduleLabelsVisible` 元数据 → 那个方向的标签**常驻**；③**拖连线过来**时
  亮出接得上的那几个。少了②借来的那条菜单点了没反应。原生标签是**斜 45°** 画的（`StandardNodule::renderLabel`
  按连线切线转角度），水平画也行，但要知道自己在偏离什么。鼠标压着某个圆点时，放大标签和节点上那条
  接口名会叠在一起 → 压着的那条让位。
- **父插口连上时不要再钻子插口**：父连接会同时给每个子插口设 input，不挡住会画一堆重复线。
- **`compoundNumericNodule:childrenVisible` 不能单看这一条元数据**：`.gfr` 里它可能被写在**没有子插口的
  FloatPlug** 上（一张真实图里 38 处），原生对这种插口画的还是普通 `StandardNodule`。判据必须再加
  「真的有子插口」，否则圆点凭空消失、线画到空处。
- **「展开 RGB」的子圆点是「一格里一簇」，不是兄弟接口**：原生 `CompoundNumericNodule`
  （`src/GafferUI/CompoundNumericNodule.cpp` 的 `updateChildNoduleVisibility`）给自己加一个
  `NoduleLayout( plug() )` 并 `setTransform( M44f().scale( V3f( 0.75 ) ) )` —— 子圆点 **0.75 单位**、
  **间距 0.75 单位**（相邻刚好相切）、整簇待在**父接口原来那一格**里。和 `GafferUI::CompoundNodule`
  （ArrayPlug、材质的 `parameters`，子接口当兄弟摊开）**必须分开判**：判据 =
  「`nodule:type != "GafferUI::CompoundNodule"` 且 `isCompoundNodule` 为真」。混用的后果：拿
  `isCompoundNodule` 当"挤成一簇"的判据会把材质 66 个参数叠进一格。三处要跟着改：**半径**（问
  `nodule.transformedBound( gadget )` 的 `size`，别写死常量）、**位置**（自己排行的侧边要把一簇并成
  **一行**）、**标签**（一簇只写一条父接口名）。

### `+`（PlugAdder）

**位置能数出来**：它在 gadget 里的名字是 `ConnectionCreator`（nodule 叫 `Nodule`）；原生把「一排 nodule +
末尾 adder」整体居中，所以**它们的坐标和为 0**（Box 提升 1 个插口：nodule -1.5、adder +1.5）；有 ≥2 个
nodule 时直接「最后一个 + 它们之间的间距」。`PlugAdder::bound()` 是 1x1 图单位。
**别拿「数 gadget 里的 ConnectionCreator」当可见性判据**：里面混着 BoxIO 那种隐藏的边 gadget，没绑 Python，
连 `getVisible()` 都问不到。

**判据有两层，只看一层会漏**：

1. **节点级**注册（`noduleLayout:customGadget:<名字>:gadgetType`，空 / None = 关掉；`:section` 挂哪条边；
   `:visible` 可以藏起来）：Switch / NameSwitch / Loop / ContextProcessor / EditScope / BoxIO 这一族都是
   「setup 过就 `setVisible(False)`」（BoxIO `setVisible( !plug() )`、Switch `in ArrayPlug == nullptr`、
   Loop / ContextProcessor / EditScope `!inPlug()`），**`Gaffer.Box` 没有这条规则**（所以 Box 四个 `+` 常在）；
   `AttributeQuery` 那种 `setupButton` 是 `setVisible( !isSetup() )`。**`inPlug()` 到 1.7.1.0 都没绑 Python**，
   判 setup 统一用 `getChild( "in" )`。BoxIO 的 `+` 是 C++ `setEdgeGadget` 挂的、没有元数据，还没 setup 时
   要自己补四条边。
2. **插口级**注册（画在那个插口那条边、接在最后一个 nodule 后面）：**`NameSwitch.in` 上那个一直可见**
   （`NameSwitchUI.cpp` 压根没有 `updateVisibility`）—— setup 过的 NameSwitch 顶上仍然有一个 `+`；
   `Gaffer.Collect.in` 同样一直可见；材质 `parameters`（1.7 是 `PlugVisibilityGadget`，1.6 是
   `ShaderUI.PlugAdder`）和 `ShaderTweaks.tweaks` 是「底下有能显示但藏着的插口才出现」（照 `showablePlugs`）。

**没绑 Python 的 gadget 怎么问出可见性**（通用招）：装它的 `__noduleContainer`（LinearContainer）的
`bound()` **只算可见子项**，所以「容器长度 − 可见 nodule 占的长度（含 `noduleLayout:spacing`）」就能反推
末尾那个 `+` 在不在。实测：set-up Switch 顶部容器 = 1.0（正好一个 nodule）→ `+` 藏着；set-up NameSwitch
的 `in` 嵌套容器 = 7.0（两个 nodule + 间距 2 只占 4）→ `+` 可见；aiStandardSurface 的 `parameters` 容器
13.0 vs 10 个 nodule 的 11.8 → `+` 可见。

**三种语义，只做一种就会有"拖上去没反应"**：
①**`setup( endpoint )`** —— 还没 setup 的 Switch / NameSwitch / Loop / ContextProcessor / EditScope /
BoxIn / BoxOut（`SwitchUI.cpp:79`、`LoopUI.cpp:83`、`ContextProcessorUI.cpp:71`、`EditScopeUI.cpp:91`、
`BoxIONodeGadget.cpp:95`）；Box 那份很短（`BoxUI.cpp`）：建 `BoxIn`/`BoxOut` → `setup( endpoint )` → 接上 →
给提升的插口写 `noduleLayout:section`、内部那半写对边；
②**加一路** —— setup 过的 ArrayPlug：照 `NameSwitchPlugAdder::createConnection`
（`src/GafferUI/NameSwitchUI.cpp`：`s = children().size(); resize( s+1 ); connect in[s].value;`）**一律
`resize(s+1)` 接新那路，不复用空槽、不判断 default 空不空**；NameSwitch 一路是 `NameValuePlug`（接 `value`）。
**ArrayPlug 取元素用 `plug[i]`，`getChild()` 只收名字**，传 int 直接 Boost `ArgumentError`。
"第二个圆点接不上"靠**拖到圆点本身直连**（圆点优先 + 光标周围兜底）解决，不改 `+` 语义；
③**显示一个藏起来的插口** —— 材质 / ShaderTweaks（见上文"`+` 上丢连线要弹隐藏参数"）。
接完还要照 `PlugAdder::applyEdgeMetadata` 写 `noduleLayout:section`（丢下去那条边给输入、对边给输出）。
Python 绑定**到 1.7.1.0 都没有 `BoxIO.direction()` / `Loop.inPlug()` / `Switch.inPlug()`**，按类型 + `getChild("in")` 走。

画在卡片外面的 `+` 命中测试要单独兜：光标正压在它上面时 `itemAt` 反而返回 None，要在光标周围取
一小块（28×28）再捞一遍。ArrayPlug 缩身（删一路）要连 ArrayPlug 的 `childAddedSignal` / `childRemovedSignal`
让卡片跟着变窄。

### 连线

- **折叠判据**：dst 输入折叠 **或** src 输出折叠（`GraphGadget.cpp:1852`）。
- **折叠渲染**：从 dst nodule 伸出 **1.5 个 Gaffer 单位**的短尾巴，悬停才画完整
  （`StandardConnectionGadget::minimisedPositionAndTangent`）。
- **原生连线颜色**（StandardStyle 默认值，`getColor()` 复核）：普通 `Color3f(0.6)` = `#999999`、
  辅助 `Color3f(0.3,0.45,0.3)` = `#4d734d`、悬停高亮 `Color3f(0.466,0.612,0.741)` = `#779cbd`。
- **颜色覆盖**：原生 `connectionGadget:color` 从 **dst nodule 的 plug** 上读（`StandardConnectionGadget.cpp:710`）。
  参考实现按接口类型色（`nodule:color`，源插口优先、没有再看目标插口）上色，亮度低于 0.42 的按比例提亮，
  没有类型色 / 灰色类型色用原生 `#999999`，辅助连线保持原生绿；**不读 `connectionGadget:color`**
  （装了某些扩展的环境里会读到扩展的配色）。无头环境里 ScenePlug 的 `nodule:color` 也注册着，测「没有类型色」
  要拿 int 连线。
- **两端没 nodule 的**（Expression 驱动）→ 原生的 AuxiliaryConnection，画虚线。规则照
  `AuxiliaryConnectionsGadget.cpp:83` 的 `visitAuxiliaryConnections`：遍历 dst 节点的**递归**输入插口，
  有 input、源节点在本层、且该插口（或其祖先）**没有 nodule** 就画一条；
  **`ignorePrivatePlugs = !runTimeCast<Expression>( dstNode )`** —— Expression 的输入挂在私有 `__in` 里，
  一律跳过 `__` 就会把「表达式读了哪些节点」的线全丢掉。**一对端点只画一条**。
- **连线不穿过两端节点**：Houdini rounded 形状只看两个端点，接口在卡片侧边、上游在另一边时（filter
  接右侧而 PathFilter 在左、BoxIn 右上接左侧参数、节点自连的辅助回环）会横穿卡片。只在折线穿过两端卡片时
  换成横平竖直的绕行折线（`edge_item._routeAround`：出口/进口各留 `WIRE_STUB` 直段，中间 0~2 拐点候选，
  避外扩 `WIRE_CLEARANCE`（9px）的卡片、不掉头、长度 + 拐点数最小），没穿的形状不变。
  **「穿没穿」按卡片本身判、绕行按外扩判**（否则几乎平齐的横线被误判）；端点在卡片里面的（Dot）不绕；
  拖线预览同一套。验证：沿路径采样数落进卡片的点。

#### 曲线连线的形状：照 Houdini 的 rounded 来，它**不是贝塞尔**

Gaffer 原生连线是贝塞尔，但「像 Houdini」指的是 Houdini 的 **rounded** 样式（Houdini 只有两种：默认直线 /
`'rounded'`，见 `$HFS/houdini/python3.11libs/nodegraphhotkeys.py` 的 `change_wire_style`）。量出来的形状是
**「直段 + 正圆弧」**：

| | |
|---|---|
| 出口直段 = 出口圆角半径 | `min( 0.30 网格单位, 流向距离/2 )` |
| 中间 | **横平**的一段（不是斜线，也不是贝塞尔那种连续弯） |
| 主圆角 | 正圆弧，半径 `min( 侧向余量, 流向余量, 0.42 * 流向余量 + 常数 )` |
| 末段 | 沿入口方向直着扎进去 |
| 几乎平齐 | 近乎直的横线，**不绕回环** |
| 目标在上游 | 出去 → 侧移一半 → 绕回去 → 侧移 → 扎进入口（5 个拐角） |

实现：在「流向 / 侧向」局部坐标里排折线，再把拐角换成圆弧 —— 圆弧用 `4/3*tan(φ/4)` 的标准贝塞尔近似
（90° 就是 0.5523 kappa），切线长 `r*tan(φ/2)`，半径按相邻两段长度自动收。1 Houdini 网格单位按节点高换算
≈ 101px ≈ 8.4 Gaffer 单位（常量 `WIRE_STUB` / `WIRE_TURN_SLOPE` / `WIRE_TURN_BASE`）。

**怎么把别的软件的曲线量出来（可复用）**：

1. 起那个软件，用它的 Python API 拿到「图坐标 ↔ 屏幕像素」的映射
   （Houdini 是 `hou.NetworkEditor.visibleBounds()` / `screenBounds()`）。
2. `import -window root` 抓图，按颜色 + 连通分量抠出连线像素，换算回图坐标。
3. **先判形状再拟参数**：拐角处做圆拟合，残差小到 ~1px 才敢说"是正圆弧"；拟不动就别硬套。
4. **把点云存进仓库当基准**（`tests/houdini_rounded_wire.json`，5 用例 × 45 点 + 采集方法 + 换算比例），
   测试直接量「我们的路径离它多远」（平均 1.7px / 最大 7.1px）—— 公式里的常数就是拿这个指标调出来的。

四个坑：

- **`setVisibleBounds()` 对「大小不变、只挪位置」的请求会被静默忽略**，而且视口不是立刻到位 →
  扫描脚本必须「先缩到全图 → 再框到目标 → **回读确认到位**」再抓图，不然抓到的是上一个用例的画面。
- **不参与显示的支线，Houdini 画成虚线** → 逐像素追踪时连通半径要放宽到 ~6px。
- **别想当然认为「离得近就该绕回环」** —— Houdini 在几乎平齐时画的是直线。
- **软件渲染（Xvnc + llvmpipe）下 Houdini 起不来（段错误）** → 这类探针只能跑在真实显示器上；
  `pkill -f "<模式>"` 会匹配到自己那条 shell 命令行。

### focus

原生在 `StandardNodeGadget.cpp` 里有个内部 `FocusGadget`：

- 画在**节点右上角外侧**，图标是 `focusOff.png` / `focusOn.png`（+ hover 变体）。
- **平时不画**：只有 focus 中的节点、鼠标压在图标上、或者鼠标在**节点**上停了 **500ms**
  （静态 `QTimer` + `g_pendingHoveredFocus`）才画。
- 点一下 `toggleFocus()`：不是 focus 就设成 focus，已经是 focus 就 `setFocus( nullptr )`。双击也走同一条。
- 不是框选的目标（`RenderReason::DragSelect` 直接 return）。

参考实现的形态：**所有节点**的 focus 角标都画在卡片右上角**外侧**（统一 `FOCUS_TAB_SIZE`、不按卡片比例缩、
不裁剪），拉远按 `1/lod` 补偿保持屏幕上恒定像素（夹 `FOCUS_LOD_FLOOR`）。

- **别做成"把整张卡片刷成金色"** —— 灯光那类节点本来就是黄卡片，一屏下来分不出谁是 focus。
- **画在卡片里面会吃掉可点区域**：30×30 的 Dot 上按比例缩的折角占两成面积，命中再按包围盒判 → 点节点
  变成点 focus。画在外面 + 命中按三角形斜边 `dx + dy <= size`（1.5px 容差）。
- **小节点（Dot）那条 `paint()` 早退分支压根走不到画角标那一步** → 角标 / 书签这类必须画在**所有早退之前**。
- 画到深背景上后悬停提示的 alpha 要加重（22/110 → 78/215），否则等于没画。
- 书签 / 报错角标挪到靠左排。

**focus 之后的连线怎么画：原生是「变暗不参与的」，不是「加亮参与的」**：

- 机制在 `ConnectionGadget::updateFromContextTracker`（`ConnectionGadget.cpp:205`）：
  `active = contextTracker->targetNode() ? contextTracker->isTracked( m_dstNodule->plug() ) : true`，
  然后 `StandardConnectionGadget::renderLayer` 用
  `highlighted() ? HighlightedState : ( m_active ? NormalState : DisabledState )`。
  节点侧 `StandardNodeGadget::updateFromContextTracker` 一样，外加名字 `setDimmed( True )`。
  **参与的东西一点不动**（参考实现在明暗对比上故意比原生拉得更开：不参与的压到 0.20）。
- 暗色照 `StandardStyle::colorForState( c, DisabledState )`（`StandardStyle.cpp:1331`）算：
  连线是「往 0.26 灰去饱和 50% → 再把亮度钉到 0.31」（`#999999` → **`#4f4f4f`**）；
  其它颜色（卡片 / 色带 / 辅助线）是「往 0.26 灰 lerp 75%」。
- **那个集合只有 `ContextTracker` 算得对，别自己爬图**：只算**上游**，而且是**当前 context 真正走到的那条路**
  （Switch / NameSwitch 没选中的支不算，改 index 会变）。自己 BFS 上下游的结果和它差很远。
  Python：`GafferUI.ContextTracker.acquireForFocus( scriptNode )` → `targetNode()` /
  `isTracked( 节点或插口 )` / `isEnabled( node )` / `changedSignal()` / `updatePending()`。**异步算**：
  必须连 `changedSignal()` 再刷一遍，测试里用 `updatePending()` 等。
- `QGraphicsItem` 自己有 `setActive()` / `isActive()`（面板激活用），自定义 item 上**别用这两个名字**，
  取名 `setWireActive` / `setNodeActive`。
- 验证**不能只断言 pen**：截图里**数像素**（`QImage.pixel` + 容差）。
- **删 / 剪切前，要删的就是 focus 那个 → 先 `setFocus( None )`**：否则 ShaderView 的输入没材质了 →
  `shaderPrefix()` 空串 → 报 `ShaderView : SceneCreator "Default" not registered`（`ShaderView.cpp:395`，
  裸 `script.removeChild()` 也照样报，是原生行为）。

### 拖放（从 Viewer / HierarchyView / SetEditor / 文件浏览器拖进来）

**GafferUI 的拖放不走 Qt 的 QDrag**，是它自己在 `Widget.py` 的 `_EventFilter` 里做的一套：拖拽过程中用
`Widget.widgetAt( 全局坐标 )` 找目标控件（再往上走 GafferUI 父链），给它发 `dragEnterSignal` /
`dragMoveSignal` / `dragLeaveSignal` / `dropSignal`。**自建编辑器不接这四个信号，从视口 / 层级视图拖路径
过来就一点反应都没有**。四种数据、原生分别在哪：

| 数据 | 落点 | 谁处理 |
| --- | --- | --- |
| 场景路径 `StringVectorData`（"/" 开头） | 节点 | `GafferSceneUI/PathFilterUI.py` 的 `addObjectDropTarget`（挂在每个 NodeGadget 上） |
| 场景路径（单条） | 空白 | `startup/gui/graphEditor.py` 的 `__locationDrop` —— **是跳到生成它的节点，不是建 PathFilter** |
| 集合名 | 节点 | `SetFilterUI.addSetDropTarget` |
| 节点 / 节点集合 | 任意 | `GraphEditor.__drop` → 换 root + 取景 |
| 文件路径 | 空白 | `startup/gui/graphEditor.py` 的 `__fileDrop`（扩展名→节点类型那张表是私有 dict，抄不到；转发原生，单 UndoScope） |

**落在节点上的直接转发给原生 NodeGadget 的信号**：`graphGadget.nodeGadget( node ).dropSignal()( nodeGadget, event )`
—— 那些 gadget 早被 `NodeGadget.instanceCreatedSignal` 挂上了 PathFilterUI / SetFilterUI（连站点自己注册的
drop 目标都一起有）。五个坑：

1. **`GafferUI.Pointer.getCurrent()` 平时就是 `None`**（标准指针）——**别拿它非空当「拖拽进行中」的标志**，
   另开一个布尔标志。
2. **dragEnter 要收得宽**：GafferUI 只在**目标控件变化时**发一次 dragEnter，之后就只有 dragMove。落在哪个节点
   上是在 dragMove 里自己算 + 自己给原生 gadget 补发 dragEnter/dragLeave。
3. **`event.line` 是相对目标控件的像素**（`__widgetSpaceLine`），不是场景坐标；工具条也占高度 →
   直接 `viewport().mapFromGlobal( QCursor.pos() )`。位置做成**可注入参数**（无头没有真鼠标，`QCursor.pos()` 恒为 0,0）。
4. 指针名照原生：`replaceObjects` / `addObjects` / `removeObjects`，**`notEditable` 没有 `Objects` 后缀**；
   `Pointer.getCurrent()` 返回 Pointer 对象，测试里比 `.fileName()`。
5. 测试可以**自己造事件**：`GafferUI.DragDropEvent()` 无参可构造，`data` / `modifiers` / `sourceWidget` 都可写。
   `Widget.ancestor()` **不含自身** —— 要让它认出「来自 HierarchyView」，sourceWidget 得是 HierarchyView
   **里面**的子控件。Python 假对象当 `DragDropEvent` 过不了 Boost 参数检查。

`GafferScene.SceneAlgo.source( scene, path )` 会为不存在的路径**抛异常**（原生 `__locationDrop` 没兜）。

### 书签（`B` 键）

- ⚠️ **数据源别用 `Gaffer.MetadataAlgo.bookmarks( script )`** —— 它**只遍历直接子节点**
  （`src/Gaffer/MetadataAlgo.cpp:420` 就是个 `Node::Iterator`）。书签基本都在 Box 里，用它的话一条都列不出来；
  代码还写着「空就 return」的话就是「B 键没反应」。原生 `GraphBookmarksUI.__findableBookmarks` 用的是
  `Gaffer.Metadata.nodesWithMetadata( script, "bookmarked", instanceOnly = True )`（递归、快），并**排掉
  `ancestor( Gaffer.Reference )` 非空的**。
- **一条都没有时也要给反馈**：原生挂一条灰的 `No bookmarks available`。
- **自己是书签、底下还有书签** → 挂成 `<路径>/This Node`（`haveDescendantBookmarks`：路径排过序，和**下一条**比前缀）。
- **跳过去 = 换层 + 取景**：`graphGadget().setRoot( node.parent() )` + `frame([node])`。
- 菜单标题原生是 `Find Bookmark`、`searchable = True`。

### 节点状态

- **`enabled` 千万不要盲目 `getValue()`** —— 被上游驱动时那是一次真正的 compute，大图上慢，**图里有依赖环时会刷一屏
  "Cycle detected"**。照 `hasStaticValue()`（`StandardNodeGadget.cpp:520`）：`Gaffer.PlugAlgo.dependsOnCompute( plug )`
  为真就别读，返回第三态。
- **停用画的是对角线**（`StandardNodeGadget::renderLayer` 的 Highlighting 层：`b.min → b.max`，Gaffer y 朝上 =
  左下到右上那条 `/`，线宽 0.5 单位）。颜色三档：`enabled` 是死值 → 0.1 灰（不参与计算 0.2 灰）；`enabled` 要算且
  ContextTracker 说它关着 → **黄色 `#f0dc28`**；要算又没被跟踪 → 原生什么都不画。`enabled` 接上/拔掉驱动**只有
  `plugInputChangedSignal` 报**，只标脏边的话画面停在旧样子。
- **`D` 键语义**：`GraphEditor.__enabledPlugForEditing`（enabled 被驱动时改源头；源头是 compute 就看能不能改上游节点
  的 enabled）+ 「**只要有一个开着就全关**」+ 单个 UndoScope。
- **`errorSignal` 是瞬时的**（compute 时抛，3 参），不是持久状态 → 自己累积，和原生 `ErrorGadget` 一样；`plugDirtied` 时清。
- `nodeDoubleClickSignal` 要发出来（接管装着时第一个参数是自己）；**双击节点是开浮动 NodeEditor，不是钻进去**
  （`startup/gui/graphEditor.py`）。

### 注释

原生过滤（`AnnotationsGadget::update`）：名字自己匹配 pattern 就画；匹配不上时只有**没注册过模板的**那些才靠
`__untemplated__` 放行；默认 pattern 是 `"*"`。⚠️ **Arnold 材质上那条 `shader_type = {name}` 不是注册过的模板**
（1.7.1.0 的模板仍只有 `performanceMonitor:*` 和 `contextMonitor`）→ 原生默认会在每个材质节点旁写一行
`standard_surface`。默认 pattern 里放 `__untemplated__` 就等于把这行放出来。**默认只放 `user`**（右键 Annotate…
加的那条），其余交给工具条菜单（照原生 `__annotationsMenu`）。多条注释竖排。
**这条只有真机能验**：无头没跑 gui 启动脚本，模板注册情况和真机不一样。

### Backdrop

- **命中形状必须留个洞**（`shape()` 只包四条边 + 顶上那条标题条）。原生 selection render 就这么画的
  （`BackdropNodeGadget.cpp:350`："leaving the main body of the backdrop as a hole is necessary to allow the
  GraphGadget to continue to perform drag selection on the nodes on top"）—— 整块能点的话在 Backdrop 上按下拖
  就是整组搬走、没法框选。四条边在角上重叠，`QPainterPath` 必须 `setFillRule( WindingFill )`。
- **`ItemIsMovable` 别漏**（`MetadataAlgo.readOnly( node )` 的不给拖）。漏了的话 Qt 一样 accept 按下、一样进
  move 模式、松手一样调写回，**只是不挪 item** —— "自己 `setPos()` 再 commit"的合成断言照样全绿，只有 xdotool
  真按住拖测得出来。
- **位置写回**：item 位置是「框的中心」（`__uiPosition` + `__uiBound` 的中心），能写回的只有 `__uiPosition`，差一个
  偏移（`centerOffset()` 实时从 `__uiBound` 算，与位置无关所以幂等）。不减它，框有偏心的 Backdrop 一拖就跳一段。
- **拉边缘改大小**：四边四角、最小 12 单位（原生 `g_margin*4`）、光标按方向换；**上边缘抓手比别的窄**
  （`min( hoverWidth*2, g_titleBarMargin )`），顶上留给搬动；拉框时**只改 item 上的预览 bound、松手才写 `__uiBound`**
  → 一步撤销；坐标换算用「scene 坐标 − `__uiPosition`」（原生 `dragMove` 的 `event.line.p0` 语义），**别经过 item 局部坐标**
  （item 摆在框中心、拉框时中心一直动，每帧累加偏移 → "往左拖框反而越来越长"）。
- **`boundingRect()` 外扩描边余量**：拆 `frameRect()`（框本身：绘制、`shape()`、命中、框选、标题/描述矩形）+
  `boundingRect()` = 外扩 3px（选中时 2px 描边居中画在路径上往外溢 1px，不留就每帧留一条擦不掉的竖线）。
- 插口：`scale`（放大标题和描述、**不改框**）、`depth`（[-1,1]，一档一档挪层叠）、`description`（自动折行）；
  层叠顺序 = `depth` 分档 + **同档里面积大的垫在后面**（原生用 GL 深度缓冲，换成 `zValue`）。
  标题居中、鼠标在框身上时标题条高亮、tooltip。标题矩形高要 `ceil( fontMetrics.height() ) + 3`（浮点高度直接用会
  切掉 `g`/`y` 下伸笔画和中文下半格）。

### 拖到视口边缘让画面自己滚

原生 `ViewportGadget::trackDrag`（GraphEditor 两个轴都开）：不滚区 = 视口往里缩 `min( min(w,h)/8, 60 )` 一圈，速度从 0
线性升到边上最大、**出了视口不再更快**，门槛取历史最小值（在边缘区里起拖、往中间拖时不会一上手就滚）；定时器里滚一步
之后要**补一次鼠标移动事件**。⚠️ **方向向量用真实长度归一、夹住的那个只拿来算速度系数** —— 拿夹过的长度归一，拖到
视口外老远时方向被放大好几倍（实测 460，上限本该 60）。断言写「拖到视口外速度封顶」，别只写「能滚」。

### 相机操作（平移 / 缩放）照 `ViewportGadget` 抄

`src/GafferUI/ViewportGadget.cpp` 的 `cameraMotionType()`：

| 手势 | 原生动作 |
|---|---|
| 中键拖（无修饰） | Track（平移） |
| **Alt + 左键** | Tumble（2D 视图里就是把相机转歪 —— 自建编辑器建议改成平移） |
| **Alt + 中键** | Track |
| **Alt + 右键** | **Dolly = 缩放** |
| 滚轮 | 缩放 |

planar（2D）模式下 `dolly()` 的式子：

```
dv = ( p - motionStart ) / 视口分辨率        # 按视口归一化，不是按像素
d  = dv.x - dv.y                            # 往右 / 往上都是放大
planarScale = 起始 planarScale * exp( -1.9 * d )
再夹 maxPlanarZoom（GraphEditor 设 25 像素/单位）
最后把"缩放原点"钉在 motionStart 上
```

`planarScale` 是「一个像素几个单位」，`QGraphicsView` 的 scale 是反过来的 → **指数换符号**：
`zoom = 起始 zoom * exp( 1.9 * d )`。锚点是**按下那一刻**光标底下那个点。

- **右键菜单要让开**：X11 上右键一按下 Qt 就发 `ContextMenuEvent`，在 `contextMenuEvent` 里按「当前是缩放手势 /
  按着 Alt」挡掉，否则手势变成"点一下弹菜单"。
- ⚠️ **`Alt + 右键`只有真键盘真鼠标测得出来**：窗口管理器（KWin 之类）常把它绑成「拖着改窗口大小」，合成
  `QMouseEvent` 永远测不到被抢。真输入：`xdotool keydown alt` → `mousedown 3` → `mousemove`×N → `mouseup 3` →
  `keyup alt`，再断言模式和 zoom 都变了。真输入脚本里右键点在节点上会弹原生 QMenu 阻塞事件循环 → 点空白处。
- **别指望 Qt 的 `AnchorUnderMouse`**：它锚的是 `lastMouseMoveScenePoint`，只有 `QGraphicsView.mouseMoveEvent`
  走到基类才更新 —— 自己接管鼠标移动之后它就是**过期**的，任何 `scale()` 都会拿这个过期点当锚把画面甩出去
  （中键拖动 + 滚轮横着甩）。缩放一律自己锚：记下光标底下的场景点 → 缩放 → 挪回去；`fitInView` 之后夹缩放上限
  那一下围着**画面中心**缩。横向滚轮（`angleDelta().y() == 0`）别当成"往下滚"。

### 原生键位清单

`GraphEditor.__keyPress` + `EditMenu` + `GraphBookmarksUI`：
`F` 取景 / `` ` `` 框 focus / ``Ctrl+` `` 设 focus / **`↓` 进、`↑` 出**（`↓` 只有能进入时才免修饰键，否则要
`Shift+Ctrl+↓`）/ `[` `]` 根历史 / `Tab` 建节点 / `D` 停用 / `B` 书签菜单 / `1-9` 跳编号书签、`Ctrl+1-9` 设、
`Ctrl+0` 清 / `Delete`·`Backspace` 删 / `Ctrl+C·X·V` / `Ctrl+D` = **Duplicate with Inputs** /
`Ctrl+A`·`Shift+Ctrl+A` / `Ctrl+L` 布局 / `F2` 改名 / `Ctrl+F` 查找。

**「能不能进这个节点」有三个键**，顺序照 `GraphEditor.__childrenViewable`（`GraphEditor.py:895-908`）：
`ui:childNodesAreViewable`（1.7 正式）→ `graphEditor:childrenViewable` → `nodeGraph:childrenViewable`（都是 legacy）。
Gaffer 自带 Box 两个键都写，**只查老键时自带节点看不出问题，只写新键的第三方节点才会「按 ↓ 进不去」**。

**菜单栏 QAction 在 `ShortcutOverride` 阶段就把键抢走了**，widget 的 `keyPressEvent` 收不到 `Ctrl+C` / `Delete` /
`F2`。覆盖 `event()`，在 `ShortcutOverride` 时对自己认领的组合 `accept()` 并返回 True（`Ctrl+Z` 别抢）。
为什么非抢不可：菜单栏那套走 `EditMenu.scope()`，钻进 Box 时它会拿错 parent。

`P` 键（原生只在 `NodeSetEditor` 上认 P = pin，节点图这里是空的）在参考实现里弹一个停靠在视口右上角的参数面板，
依赖一个可选的独立 `parameterEditor` 扩展；没装时 `P` 什么都不做。import 只能写在按键处理里（扩展加载顺序不定）。

### 交互取舍

- **"点一下删东西"和"划一笔删一片"可以共存**（按住 X）：按下和松开位置差在几个像素内算"点"（点线删线、点节点删节点，
  上下游自动接起来），否则划线切多根。
- **按住式交互做得成，前提是两边都挡自动重复**：X11 按住约 0.5 秒后会一直发 press/release 对 ——
  `keyPressEvent` **和** `keyReleaseEvent` 开头都写 `if event.isAutoRepeat() : return`（Gaffer 自己的
  `Widget.__keyRelease` 也是这么写的）。**只有真键盘长按验得了**（xdotool `keydown` → 停 1.5 秒 → `keyup`）。
  只挡 press 那边会被打断（划线一直闪）。
- **连线可选中 Delete 删除**（点中段选中、点两端改接）。
- **拖动自动对齐**（原生没有，默认关、工具条给开关）：`_NodeItem.itemChange( ItemPositionChange )` 把即将去到的位置
  交给编辑器修正。规则：`SNAP_RANGE`（360px）以内的节点才是候选；候选里筛「能横平竖直对上」
  （`min(|dx|,|dy|) <= SNAP_DISTANCE`）再取**最近**那个；**只吸一个轴**（`|dx|<=|dy|` 吸 x 成竖列、否则吸 y 成横行）；
  参考线只画两节点之间。三个注意：①只在单个节点拖动时生效（多选时每个 item 各吸各的会搅乱相对位置）；②只在真的拖动时
  生效（程序 `setPos` 时不吸）；③吸附发生在写回 Gaffer 之前。参考线是 1px 虚线 + 抗锯齿，像素验收要按"偏黄（红−蓝>40）"
  判且只在参考线那几列取样。
- **中键拖节点给别的编辑器**（`Sending`，见「二」）。

---

## 六、自动排列：原生那套不够好，自己写分层布局

原生 `StandardGraphLayout::layoutNodes` 是"贪心找空位"，节点一多就横着摊开、上下层错开、连线来回穿。换成**分层布局**
（Sugiyama），按 Gaffer 的上→下流：

1. **分层**：`rank = max( rank(上游) + 1 )`（最长路径）。环上的边忽略，**迭代版 DFS**（2000 个节点串一条链，递归会爆栈）。
2. **长边打桩**（最值钱）：跨了好几层的边如果不管，定序那步"看不见"它，它横穿好几行 —— 不打桩比原生还差（130 vs 98 处交叉），
   打桩之后 65。中间每层塞一个宽 1.5 单位的"桩"，最后扔掉。
3. **定序**：重心法来回扫，每遍之后做一轮**相邻交换**（交叉少了就留），全程记住交叉最少的那一遍。交叉数用**树状数组**数逆序对，
   别写两重循环：相邻交换每换一次就要重数一遍，O(边²) 在 300 节点稠密图上光这一项 4.9 秒（树状数组 1.2 秒；换之前拿两重循环版
   当 oracle 200 组随机图逐组比对）。
4. **定位**：**Brandes–Köpf**（"Fast and Simple Horizontal Coordinate Assignment", GD 2001）。先决定"谁和谁必须对齐"（连成 block），
   再整块一起摆 —— 长边的桩链天生落进同一个 block，于是**长边是一条笔直的线**。四遍（上/下 × 左/右）取中间两个的平均。
5. **整块平移回原来那堆节点的中心**。

**每一步都做成可换实现 + 一台对照台**（参考实现：`layout.py` 的 `LAYOUT_STRATEGY` / `layoutStrategy()`（`rank` / `order` /
`position` / `spine` 四个键）和 `tests/bench_layout.py`）。12 张图约 200 个节点：

| 组合 | 交叉 | 总长 | 长边直 | 主干直 | 乱序 | 毫秒 |
| --- | --- | --- | --- | --- | --- | --- |
| **Brandes–Köpf + 主干优先对齐 + 补钉** | **174** | 6888 | **32/80** | **80/80** | 7 | 85.9 |
| 中位数来回扫 + 事后钉主干 | 191 | 6891 | 17/80 | 80/80 | 4 | 83.9 |
| 网络单纯形分层 + 同上 | 174 | 6799 | 32/80 | 80/80 | 7 | 86.6 |
| ALAP + 按插口顺序 DFS + 树式定位（**Houdini 那味**） | 195 | 7021 | 19/82 | 80/80 | **3** | **65.1** |

- **Brandes–Köpf 值得换**：交叉 −8.9%、长边直的条数 +88%，耗时不变。收益几乎全落在**稠密材质图**上（36 个 OSLCode：
  交叉 63 → 44），场景流水线基本持平 —— **别拿一张简单图下结论**，12 张里有 8 张所有组合完全打平。
- **网络单纯形（`dot` 那套）不值得**：连线总长只少 1.3%、交叉一个不差，600 节点稠密图多花 5 秒（O(V·E) 一轮）。留着当对照，
  默认不开、超过 `LAYOUT_SIMPLEX_NODE_LIMIT`（250）自动退回。
- **中位数定序（dot 的 `medianvalue`）和重心法一模一样**（12 张图逐项相同）。
- **Houdini 那套**（ALAP + 按插口顺序深度优先 + 树式定位、**完全不做交叉优化**）：交叉最多、连线最长，但**输入口顺序保持得最好**、
  **最快**。它的长处「`in0` 一定在 `in1` 左边」单独留成一个初始次序选项（`order="dfs*"`）就够了。

代价与验收：400 节点 0.6s、800 节点 0.1s（超过 400 个跳过"相邻交换"）。**"优雅"要能量**：拿一张真实材质图数**连线交叉**
（线段两两求交），我们 87 / 原生 119；再断言"没有一条连线往上走"和"同层不重叠"。

### 必须**认流向**（这条比算法本身重要）

Gaffer 的图**同时存在两种流向**，按插口挂在哪条边定（`noduleLayout:section`）：

| 节点 | 插口 | 流向 |
| --- | --- | --- |
| 场景 / 图像 | `in` 上、`out` 下 | 竖着流（上游在上） |
| 材质 / OSL | 参数在左、`out` 在右 | **横着流（上游在左）** |
| `ShaderAssignment` | `in`/`out` 上下 + `shader` 在左 | 竖着流，材质从左边喂进来 |

一律从上往下排的话，材质那一坨的连线全得从右边绕到下一个的左边。材质应以最终 ShaderAssignment 为核心做左右排布：

1. `nodeFlowAxis( node )`：**判据是"输出圆点挂在哪条边"** —— 场景 / 图像节点的 `out` 挂**下边**、材质 `out` 挂**右边**。
   一个输出圆点都没有（还没 `setup()` 的 Switch）才退回看输入。⚠️ **别写成"有没有输入挂上边"** —— `OSLCode` 的 `code`、
   `ArnoldDisplacement` 的 `map` / `height` 都是挂**上边**的输入圆点，照那条判据整类材质节点会被当成场景节点 → 材质参数挂左边
   → 一张图的边**全被算成"侧面喂进来的"** → **每个节点各自一组**（36 个 OSLCode 排出 35 组、161 处交叉；判据改对之后 63 处）。
   `OSLCode` 在生产图里很常见，这是真 bug。
2. **纯过路的节点（`BoxIn` / `BoxOut` / `Dot`）自己不定方向**：默认竖着流，**邻居都朝一个方向就跟着改**。提升出来的 `filter`
   BoxIn（FilterPlug 圆点挂**左边**）要特判，不然被当成"材质"。
3. 按流向切**连通分量**，每组各自跑分层布局（只是"沿流向 / 垂直流向"换个轴）。
4. 跨流向的边当"挂钩"：**主组挑最下游那个**（组间连线只进不出的 sink，**不是节点最多的** —— 材质 40 个、场景 4 个，按大小挑正好挑反），
   其余组按目的插口所在的边贴过去（左边喂进来 → 整坨摆在它左边、和那个插口同高）。
5. **摆完还要推开**：挂钩只对齐到一个节点，下游组里别的节点可能正好横在旁边。

横着流的组要用**更大的列间距**（11 个单位）—— 不分栏材质节点的参数名画在卡片**外面**（最长 10 个单位）。

还有两步：

6. **侧面喂进来的边不算主流**：`filter`（挂右边）、`shader`（挂左边）这类边如果参与分层，喂它的那条链就被排进主干的某一层。
   判据看**目的插口挂在哪条边**（`isFlowEdge()`）：竖着流只认上下、横着流只认左右；`BoxOut.passThrough` 是脚手架也不算。
   **过路节点（BoxIO / Dot）例外** —— 它们的插口都算主流。**兜底**：节点在流向那两条边上压根没有输入圆点时，它挂哪儿哪儿就是
   主流（`ArnoldDisplacement`：`out` 在右算材质，参数全挂上边，不兜就一条主流边都没有）。
7. **主干拉直**：分层 + 定位之后主干仍会被同层旁支挤得左右错开。**两步做**：①把主干那条边喂给 Brandes–Köpf 当"优先对齐"的
   候选；②剩下那几段再钉到一条中线上、同层其它节点往两边推（`_layoutRowPinned`）。**只做②不做①会把定位结果整个搅乱**
   （交叉 165 → 187）。⚠️ 两步都必须限权，见下一节。

### ⚠️ 拉直主干**无权**动扇入 / 扇出那个节点

图：6 个 Sphere 喂一个 Group 再接 Transform（标准答案 `tests/test_layout_group.gfr`，手摆的）。应该 Group 停在那一排的**正中间**；
越权的实现把它贴到了**最左边**那个 Sphere 底下。两处越权：

1. 定位里主干优先对齐把主干那条边插到**中位数候选之前** → Group 不去中位数、跑去和某个 Sphere 对齐；
2. 拉直把**整条主干**钉到一条中线上，连 Sphere 一起钉 → 那一排上游被整排推走。

**它客观更差**：中位数是"到所有邻居的总横向偏移最小"那个位置（L1 中心）。Group 在正中间总偏移 **126**，贴到最左那个 Sphere 上
是 **210**。所以修法不是调参数，而是收回越权：

| | 规矩 |
| --- | --- |
| 定位（BK） | 主干**只在中位数之间取舍，不许越过中位数**。偶数个邻居本来就有两个中位数，正好留给主干当 tie-break；奇数个就没它的事 |
| 拉直 | ① 主干**在扇入那儿断开**（一个节点有 ≥2 路同流向输入 → 它属于那几路的正中间），每段各自钉自己的中线；② 钉完**总横向偏移不许上升**，升了整段否掉 |

② 是兜底闸：一个源扇出到十几路时它直接否掉硬推（所以①只按入度断开就够）。**只留②**和 ①+② 结果一个数都不差；①的价值在**粒度**
—— 长主干中间夹一个 Group 时两头各自拉直、Group 居中。

14 张图（默认组合）：交叉 **−20%**、连线总长 **−16%**、总横向偏移 **−27%**、长边偏移 **−29%**，耗时不变；代价是"完全笔直"的长边少 5 条、
主干 89/89→78/89 —— 少掉的恰恰是穿过扇入/扇出的那几段。

两个连带的坑：

- ⚠️ **交叉数指标会把"扇形居中"算成假交叉**：叉积符号判定在两条边**共用端点**时 `d1 == 0`，另外两个端点分列两侧就判成交叉 ——
  "源摆正中间"（对）比"贴到最边上"（错）凭空多一堆交叉，照这个指标优化会被引向错的排布。共用端点的两条边直接跳过。改了口径之后
  历史交叉数字不能和新的混着比。
- **试过 dot 的边权做加权中位数**（桩—桩 8 / 桩—真 2 / 真—真 1）：长边偏移 −7%，但"主干头一个节点同时喂着一条长边"时长边会把它从
  主干那列拽走（主干直 78→69）。**留普通中位数**，长边靠 BK 的"一型冲突让桩链赢"拉直就够。

**方法论**：这类"heuristic 覆盖了最优解"的 bug，判据就是**拿目标函数算一遍两种摆法的分数**（Σ|x_u − x_v|）。分数更差还被选中 =
越权，收回它；分数更好但看着不喜欢 = 才是审美问题。**要知道目标排布**，让人把图**摆好存一份 `.gfr`**，然后逐容器打印「手摆的位置」
和「排出来的位置」（按 y 分行、行内按 x 排）对比。

### 侧面喂进来的 / 互不相连的那几坨摆在哪

**PathFilter 这类"从侧面喂进来的一坨"**：

1. **挡路判定按逐个节点的矩形来，绝不能按整组的包围盒**。主干那组的包围盒是从头到尾一整条 —— 一个挂在旁边的 filter 撞上就得整个越过去，
   几个 filter 接连让下去甩出几十个单位（平均"侧跳" 99.8 个单位，原生 14.6；改成逐节点矩形 25.5）。
2. **判"撞上了没有"的余量和推开的间距是两回事**。拿组间距（6）去判的话，主干上下相邻两个节点之间只有 5 的空隙，挂在旁边的两个 filter
   会被判成互撞、一个接一个往外让（17 / 34 / 17 / 34 / 51）。判用小余量（`LAYOUT_CLEAR_GAP=1`）、推用 `LAYOUT_GROUP_GAP=6`。
   测试断言写成「五个 filter 的跳距不许一个比一个远」，比「不重叠」严得多。
3. **一个 filter 常常喂好几个节点**：挂钩方向取**最外面**那个、垂直方向取**平均**。

逐节点判定推一次可能又撞上第三个 → 顺着挂钩方向**推到底**，推不干净再退回"四个方向挑位移最小"。

**⚠️ 一条边都没有的散节点：`Ctrl+L` 必须把它们排成一排**（否则零位移、"按了没反应"）。没有边 → 每个节点各自一个连通分量，没有挂钩的
分量只做「落回原中心 + 撞上才推开」。修法：把**在所有边里都没出现过**的散节点并成一组（侧面喂进来的 PathFilter 是"单节点组但有挂钩"，
不能并进去）。并完全在同一层（rank 0），分层布局天然把一层排成「对齐 + 等距 + 保持原来的先后」（夹具 `tests/loose_nodes.gfr`）：

```
之前  x=-27.2/-14.5/-1.5/13.4/30.9/47.6   y=13.1~18.9（抖动）  间距 12.7~17.5（不均）
之后  x=-26.9/-12.9/1.1/15.1/29.1/43.1    y 全 14.2            间距全 14.0（宽 11 + 间距 3）
```

排横还是竖：先看**现在摆成什么样**（长边就是那条线）；堆在一起 / 方方正正时回退到**这类节点的流向惯例**（场景节点并排成横排；材质节点
叠成竖列）。实现上「横排」= 把这一组的轴设成 `vertical`（展开轴是 x）。少于两个别动。顺带收益：一批刚粘贴进来、位置几乎重合的节点
直接排成整齐一排。

**摆开互不相连的那几坨（component packing）**：分层布局只管一个连通分量。挂不上钩的那几坨很容易写成「落回原中心就完事」—— 各坨排完
**尺寸变了**，原来紧挨着的就**叠在一起**（4 坨 x 3 节点：原间距 8 → 3 对重叠；间距 3 → 6 对全叠；刚粘贴的几乎重合 → 叠成一摊）。
做法：挂上钩的那几坨（含 anchor）**当障碍物不动**，其余逐坨落回原位再推开。**推开要比"推到底"的终局代价，不能逐步贪心**：「四个方向各推
一次、取推得最少的、外面循环 8 次」会让最右那坨往左让（24 < 27）、又撞上 anchor 再往左推，从最右挤到最左（位移 41）；改成「四个方向
**各推到底**再比总位移」就对了（27）。

**Hilbert Sort 在这里值不值（量过）**：同一套摆放规则只换排序，4 张随机图、8~20 坨：

| 摆放顺序 | 总位移 | 最大位移 | 重叠 | 邻居保持率 |
| --- | --- | --- | --- | --- |
| 按到中心的距离（径向） | **586.7** | **41.8** | 0 | **71.0%** |
| 组号（= 建节点顺序） | 609.3 | 53.4 | 0 | 69.6% |
| Z-order / Morton | 676.3 | 48.1 | 0 | 64.5% |
| **Hilbert** | 740.8 | 57.0 | 0 | 58.0% |
| 按 x | 763.5 | 50.4 | 0 | 58.7% |

这一步每坨**已经有目标位置**，撞了才往外让 —— 正确顺序是「先摆中心拥挤的，外面的有空地可退」（= 径向），Hilbert 在象限间跳，常先摆外圈
再把内圈挤出去。**重叠归零靠的是"摆开"这一步本身，跟顺序无关。** 「压成一块」的紧凑摆放里 Hilbert 邻居保持率 42.1% / 面积 9285，也没赢过
按 x（47.0% / 8953）。结论：引入这类算法前**先把"换掉排序函数跑对照"的开关做出来**（`hilbertSorted` 可整体替换）。空间排序真正的用处在
**视口虚拟化 / 空间索引**。参考实现默认走 Hilbert 是看过上表之后的取舍，不是量化最优。

`hilbertIndex` 实现上：流传的 `rot()` 有传全边长 `n` 和传当层 `s` 两个版本，两个都是合法 Hilbert 曲线（互为反射）；**穷举验**：
`2^order x 2^order` 个格子下标要**不重不漏**、相邻下标在格子上曼哈顿距离恰好 1（1~4 阶几毫秒）；图坐标是浮点且可能为负 → 按所有点的
**包围盒**量化（`2^16`），退化那一维取 0；同格要有**稳定的次级 key**。

---

## 七、观感设计

- **形状按大类分，身份靠图标** —— 和 Houdini 一个分工。轮廓三档：Dot 小圆点 / `nodeGadget:shape=="oval"` 胶囊 / 圆角矩形。
  图标用 `QPainter` 矢量手绘（按 16×16 设计再缩放）。加图标 = `qt.py` 加一个 `_glyphXxx` 函数 + `_GLYPH_PAINTERS` 表里加一行。
- **类型判断用 MRO 里的类名，不用 isinstance** —— ArnoldLight / CyclesLight / USDLight 全派生自 `GafferScene::Light`，一次覆盖；而且不用
  import 可选模块（`GafferArnold` 无头 import 就 SIGABRT）。
- **侧边接口徽章阈值设 2** —— 几乎每个场景节点都有个 `filter` 挂右边，为它一个把所有节点撑高一行不值当。
- **方向箭头画中点不画终点**（Houdini 就是这样），中点方向用相邻两点（0.46/0.54）数值求，**别用 `angleAtPercent()`** —— 它的角度约定
  按 y 轴向上算，和场景坐标反着。
- **长连线中段渐隐**：`QPen` 挂 `QLinearGradient`（p0→p1，中间 stop 降 alpha）。
- **画粗体的文字要按粗体量宽度**：侧标"接上线就加粗"，宽度按常规字量 → 名字被裁。同一段文字有两种字重，一律按最宽那档量。
- 侧边参数名三段式 LOD（字 → 色块 → 无）；连线**两头**的侧标都要在边变化时刷新（增量更新不重建节点 item，靠"连没连"变样子的东西
  要有自己的轻量刷新，参考实现 `refreshSideLabels()`）。

### 材质节点：分栏的写卡里、不分栏的写卡外

Houdini 式"卡外圆点旁写参数名"是**不分栏节点**的做法。节点一旦有分栏（`parameters` 底下的插口带 `layout:section`，standard_surface 那种
66 参数 11 栏），卡外那套撑不住。定下来的形态：

- **只给材质，不给灯光**：`buildSectionData` 开头 `if isLightNode( node ) : return {}`。判据复用 `isLightNode`：`GafferScene::Light` 子类走 MRO
  类名、LightFilter、以及**网格光**（`any( n.endswith( "MeshLight" ) ... )` —— 1.6 的 `ArnoldMeshLight` 派生自 `FilteredSceneProcessor`、
  没有独立 MeshLight 基类；1.7 才有 `GafferScene::MeshLight`）。灯光参数在 NodeEditor 里调，图上基本不接线。
- **分栏规则**：只对「有 `parameters` 子插口且侧边有 `layout:section` 元数据插口」的分栏，按首现顺序；`hasNodule==False`（被
  `noduleLayout:visible=False` 藏掉）但带 `layout:section` 的也收进来；**输出口不参与分栏**（材质 `out` 带 `layout:section="Settings"`，
  照直分栏会长出只装 `out` 的栏）；子接口跟父插口进同一栏。
- **默认收起**：折叠态存**非持久**节点元数据 `nodeGadget:sectionCollapsed:<side>:<栏名>`，无元数据 = 收起；展开态必须存
  `BoolData(False)`（**绝不 deregister**，否则读回默认收起）。⚠️ `Metadata.value` 把 `IECore.BoolData` 解包成 Python bool，
  `isinstance( data, IECore.BoolData )` 永远 False。
- **名字（含类型图标）独占顶部标题条**（`SECTION_TITLE_HEIGHT=22`，非分栏仍是 3px 色带），**左对齐、图标在名字左边**；参数行从标题条
  **下面**开始、固定行距（`columnTop` 固定行距居中列，别均匀铺满整卡 —— 那样最后一行贴底、`+` 被 clamp 回参数圆点上）。
  画标题条要 `painter.setClipPath( 卡片 path )`（直接画圆角矩形圆角半径对不上，顶上两角露缝）；文字色按色带亮度挑
  （`0.2126R + 0.7152G + 0.0722B > 0.55` → 深色字）。
- **参数名 / 栏名写进卡片**（左排贴圆点右侧左对齐、右排反过来）；卡片**自己撑宽**：
  `minWidth = (NODULE_RADIUS + SIDE_LABEL_GAP)*2 + maxLeft + maxRight + SECTION_CARD_PAD`，撑宽**必须同步 `__noduleScaleX`**
  （`_width / __nativeWidth`）；宽度按**全部参数**算（只按可见行 → 收起时缩窄、展开跳宽）；卡内标签夹 `SECTION_LABEL_MAX`（140px），
  否则 `Transmission Scatter Anisotropy`（粗体 182.8px）一条就把卡撑到 274px，完整名字留在悬停放大标签里。
- **卡外只留两样**：接口圆点 + 收放小三角（`__sectionHeaders` 存 `(name, y)`，x 由边线定）。`__sideLabelWidth` 对分栏节点归零（它还管
  `boundingRect` 悬停余量）—— 第一遍循环只填 `__sideLabels`，宽度累加挪到"分栏就早退"之后。收起来的参数圆点锚到栏 header 行。
- **收放点击范围 = 三角 + 整条栏名行**（`__sectionRowRect(side,y)` = 这侧半张卡 × 一行高），参数行照旧不算 header、圆点命中优先级不动。
  三角命中框要加进 `shape()`（只加小框，别把整条名字加进去，否则悬停 margin 吃邻居点击），而且 `shape()` 要 `WindingFill`（见下）。
- **分栏节点不画 `+`**：只在画的那一层跳过（`__buildAdders` 里 `if self.__sectionData and section in self.__sectionData : continue`），
  **`plugAdders()` 纯函数别动**（语义照原生、测试直接断言它），`__hiddenConnectablePlugs` / `__showAndConnect` 留着。
- **卡内文本和节点色区分开**：卡内未接线 `mixColors( noduleColor, _textColor, 0.30 )`（混向白、保留类型色相），接上线 `_emphasisColor` + 粗体；
  卡外照旧 `mixColors( noduleColor, 深背景, 0.45 )`。
- **悬停放大标签只在「标签画在卡外」时让位**：判据 `key == hovered and not sectionData`。
- 参数圆点、`+`、折叠三角各有中文 tooltip 是参考实现的界面约定（界面标签英文 + 悬停小框中文）；悬停通道判定顺序 nodule → adder → section。

### 灯光图标：按类型分，照官方 PNG 逐像素量

- **灯光类型读 `__shader.name`**：`GafferScene::Light` 把 shader 存在 `__shader` 子节点，ArnoldLight 顶层 `name` 只是 `"light"`，真正类型在
  `__shader.name`（point_light / quad_light / spot_light / distant_light / disk_light / cylinder_light / skydome_light / photometric_light /
  mesh_light）。读不到再退回顶层 `name`；`lightGlyph( node )` 映射到 9 种图标，认不出兜底回灯泡。
- `$GAFFER_ROOT/graphics/{point,spot,quad,distant,disk,cylinder,environment,photometric,mesh,portal}Light.png`（16×16）就是 LightEditor 那套。
  **别按印象画**，三步：
  1. **量**：dump 成 ASCII（`ramp = " .:-=+*#%@"`，值取 `alpha * max(r,g,b)`），算 **alpha 加权重心 / 阈值包围盒 / 二阶矩主轴角与长短轴 /
     覆盖面积**，以及沿四个对角方向的极值点（旋转矩形角点）。
  2. **画**：在 16×16 坐标系（中心 0,0 = png 坐标 −8）里用矢量画同形状。point = 小实心圆 r≈2.2；quad = 45° 斜**实心矩形**；
     disk = 同朝向**实心椭圆**（7.4×4.4）；portal = quad 那块矩形**只描边**；distant = 两支朝左下的 45° 箭头（倒刺横竖）；spot = **描边**
     锥形（两条边到锥尖距离不等 → 二次贝塞尔）；cylinder = 实心圆柱 + 顶盖缝；environment = 带经纬线实心球；photometric = 灯泡 + 半圆配光 + 缝；
     mesh = 斜实心网格面。
  3. **对拍**：渲染回 16×16 和原生逐像素比重心 / 包围盒 / 墨量，写进无头测试（重心 < 1px、包围盒 ≤ 1.5px、墨量 ±30%；描边和弯折豁免墨量）。
     看不了图也能看懂 ASCII 和数字，这是能自己迭代的关键。
- **"缝"怎么画**：原生内部分隔线在 PNG 里是把填充**掏掉**露底色。别用 `CompositionMode_Clear`（打穿卡片）—— 按亮度往黑或往白混一档
  （`lightnessF() > 0.5 ? 混黑 : 混白`，0.6 左右）；灯泡那种浮在填充外的缝要 `setClipPath` 裁进填充，否则空气里拖出深色圆环。

---

## 八、坑位清单（全部实测）

### 架构级

1. **重建必须 defer 到 idle**。原生 GraphEditor 的 `__preRender` 会写 `__uiPosition` → 发 `childAdded` → 若在信号里同步重建 → 又触发渲染，
   **永不 idle（100% CPU）**。信号只标脏，`EventLoop.addIdleCallback` 一次性回调（`return False`）里才干活。位置变化只移动已有 item。
2. **只读路径绝不 `createIfMissing`**。`__uiPosition` 是原生在 `preRender` 里按自动布局算完才建的，抢先建会把自动布局搞坏。
3. **选择同步必须 diff + 延到松手**。拖框时 `selectionChanged` 每帧都发；每次 `clear()` + 全量 `add()` 会让 NodeEditor / Viewer /
   HierarchyView 全跟着抖。按住鼠标时不写回（`QApplication.mouseButtons()`）、只删该删的只加该加的。
4. **编辑操作以 `script.selection()` 为准**，不看 scene 选中状态 —— 同步是 defer 的，可能差一拍。
5. **全量重建之后必须把「选中 / focus / 参与计算」重新盖上去**：换层（进出 Box）走的就是全量重建 —— 忘了刷的表现是「进 Box 变暗没生效、
   出 Box focus 角标丢了」。判断一律 `isSame()`。结构变化时 item 按 `isSame` 换绑（Revert 后同名不同节点）。
6. **拖动期间绝不重建**：重建把 item 删掉重做，Qt 的**隐式鼠标抓取**跟着没了，这一下拖动**静默失效**。判据要**同时**看自己的模式标记和
   `QApplication.mouseButtons()`（只看模式标记的话，哪条路松手没走到重建就永久冻住）。手势之间要互斥（记住发起手势的按键）。
7. **编辑器被拆掉之后 idle 回调还会再响一次** → `RuntimeError: Internal C++ object (_GraphView) already deleted` 刷屏。Python 属性还指着壳，
   `is not None` 判不出来，得真去碰一下（`view.viewport()` 包 `try/except RuntimeError`），死了就 `return False` 注销回调。
8. **增量更新的代价：靠"连没连"变样子的东西不会自己刷新**（侧边参数名高亮），给这类状态写只重算这一项的轻量刷新，并在边变化时对线的两头都调。

### 版本差

9. **版本敏感的 API 一律拿装机版复核**（`<GAFFER_ROOT>/python/` 里的 Python 源码、`lib/libGaffer*.so` 用 `strings` grep），源码检出不一定和你跑的
   版本同步。
10. **升级 Gaffer 大版本时，先原样跑一遍测试拿真实失败清单，别先猜**。1.6 → 1.7 只有两处真破（右键菜单扩展点，见「二」①②），几何常量 /
    `ViewportGadget` 默认值 / 注释模板 / 包装对象身份 / `BoxIO.direction` 之类一条都没变。⚠️ **「一条 FAIL 都没有」要先确认它跑到了结尾** ——
    1.7 上 `OSLShader` 出厂多了一个空的 `out` 容器 `Plug`，测试夹具 `if "out" not in children : addChild( Color3fPlug( "out" ) )` 被跳过，
    `Plug` 接不上 `Color3fPlug`，**硬中断在半路**，`grep -c FAIL` 得 0。
11. 1.7 新增 `ui:childNodesAreViewable` 键（见「原生键位清单」）；`Show Contents...` 的原生命令换成 `functools.partial( GraphEditor.__acquireNodes, … )`；
    `PlugAlgo.dependsOnCompute` 那段从 `GraphEditor.py:843` 挪到 `:932`；1.6.5.1 的访问器是只吃 cls 的 classmethod，传 True 要多选那路直接 TypeError。

### Qt

12. **`sceneRect` 必须留大余量**（每边 20000px）。QGraphicsView 把可视区夹在 sceneRect 里，不放大就「中键拖到内容边缘拖不出去」。
    相应地 **BSP 深度要自己设**（`setBspTreeDepth( 16 )`），见「九」。
13. **平移必须临时切 `NoAnchor`**：`AnchorUnderMouse` 会在任何变换改变时重新锚定，把 `translate()` 抵消。**切了 `NoAnchor` 就必须自己记视野中心**：
    Qt 内部的 `lastCenterPoint` 只在 `centerOn()` / `scrollContentsBy()` 里更新，于是尺寸一变（拖布局分隔条、换 tab、面板 reparent）`resizeEvent`
    就 `centerOn( 陈旧的点 )` —— 「一拖布局，图就弹回中心」。平移 / 缩放 / 取景 / `scrollContentsBy` 之后各记一次
    `mapToScene( viewport().rect().center() )`，在 `resizeEvent`（基类那次复位用标志挡掉别记）与 `showEvent` 里 `centerOn` 回去。**不要**每次平移
    顺手 `centerOn`：它取整滚动条值，连续小步平移每步漂 1px（200 步漂 200px）。
14. **视口更新模式别用 `FullViewportUpdate`**，用 `SmartViewportUpdate` + `CacheBackground`（见「二」）。
15. **`boundingRect()` 必须把 pen 宽的一半算进去**，「包围盒恰好等于自己画的那个矩形」的 item 最容易漏（Backdrop 选中 2px 描边每帧留一条竖线）。
    同类三条：①拖动 / 拉框途中**别动 `sceneRect`**（`setSceneRect` 改滚动条范围让视图漂一下，漂移只有那个 item 报了脏 → 大面积不重画），松手再更新；
    ②**改几何前记旧 scene 区域、改完 `scene.update( 旧区域 )`** —— `prepareGeometryChange()` 记的是当前包围盒，紧接着 `setPos()` 用**新**包围盒标旧位置，
    尺寸和位置一起变时错位；③坐标换算别混两个基准。验残迹**只能在真屏幕上**（`screen.grabWindow` vs 强制 `repaint()`），**测量本身会重绘** ——
    脚本每帧只看到一条线（几十个采样点），连续拖动不重绘才攒成一大片，别当噪声。
16. **任何按 `1/lod` 放大的绘制都必须夹 lod 下限，`boundingRect()` 按那个下限留余量**。`boundingRect()` 是几何，改它必须先
    `prepareGeometryChange()`，而 lod 是 `paint()` 时才知道的 —— 不夹的话缩到 `MIN_ZOOM` 时就画到包围盒外，拖动留拖影（focus 角标 lod=0.02 时
    item 坐标里 **550px**，包围盒 222px；参考实现 `FOCUS_LOD_FLOOR = LOD_MEDIUM/2 = 0.09`）。①判据用「会不会画」（focus 角标悬停时也画），
    不是「是不是 focus」；②**画在卡片外面的一切都要进包围盒**：卡外参数名、`+`、focus 角标、**节点右边的注释**（竖排溢出底部的部分也算）。
17. **`shape()` 必须自己写，别跟着 `boundingRect()` 走**。boundingRect 为了阴影/悬停标签放大了一圈，放大 + 抬高 z 值的 item 会把周围点击/拖放全吃掉
    （「从这个节点的小圆点拖到隔壁节点上连不上」）。
18. **`QPainterPath` 默认 `OddEvenFill`，`shape()` 里重叠的 `addRect` 会被异或成洞**：那一片 `view.items()` / `item.contains()` / `nodeItemAt` 全返回空，
    而 item 自己的 `xxxAt( 局部坐标 )` 判据却是对的。修：`path.setFillRule( QtCore.Qt.WindingFill )`。确诊：沿水平线扫 `shape().contains()` 打表
    （dx=-120 True / -130 **False** / -147 True）。
19. **命中测试别只问"光标底下是哪个 item"**：画在卡片外面的东西（`+`、角标、侧标）不在 `shape()` 里，在光标周围取一小块区域再捞一遍。
20. **无头（offscreen）QPA 下 `QGraphicsScene` 偶尔不给按下建立隐式抓取**（`mouseGrabberItem()` 是 None）：合成事件测"拖动把节点挪走了"会随机失败 ——
    交给真鼠标 e2e，无头那边验"进没进拖动模式 + 松手写没写回 Gaffer"。
21. **弹出的菜单必须留引用**（存 `self.__contextMenu`），局部变量出作用域就被 GC，菜单一闪而过（原生 `GraphEditor.__buttonPress` 也是存 `self.__m`）。
22. **Qt 默认拿 `Tab` 做焦点切换** → 覆盖 `focusNextPrevChild()` 返回 False。
23. **方向键 / PageUp·Down / Home·End 是 `QAbstractScrollArea` 的滚动键**：上下键进不去 / 出不来层级时被基类拿去滚画面（原生是 GL 视图一动不动）。
    转发之后把这几个键吞掉，别调基类。
24. **`scene.clear()` 销毁 C++ item**，Python 包装立刻 `Internal C++ object already deleted` —— **包括自己加的临时 item**（划线虚线、拖拽连线）。
    重建前置 None，调用处再包 `try/except RuntimeError`。
25. **裸 `QWidget` 会被 Gaffer 的 stylesheet 设上 `WA_StyledBackground`** → `GafferUI.Widget( qtRoot )` 包一层再传给 `Editor.__init__`。
26. **`QMouseEvent.pos()` PySide6 已废弃** → `event.position().toPoint()`（写个 `_eventPos()` 兼容）。
27. **自己管选择时 Qt 会在按下和松手各插一手**：「没有 item 接受这次按下」时 `clearSelection()`；`QGraphicsItem::mouseReleaseEvent` 里「没移动又没按 Ctrl
    就只留这一个」。抹掉修饰键再转发**不够**，要**按下前后、松手前后各记一次 scene 选择，对不上就对回去**。
28. **兜回选择这一来一回必须挂起「写回 script」**，否则 node set 顺序被悄悄换掉：写回是 diff 式的，松手时 `mouseButtons()` 已是 `NoButton`、按键守卫
    拦不住，先 `remove(A)` 再兜回 `add(A)` —— `[A, B]` 变成 `[B, A]`。跟 node set 的面板只显示 `_lastAddedNode()`，表现是「Shift 加选后面板先跳到
    新节点又弹回旧的」。基类事件 + 兜回来整段用 `_setSelectionSyncSuspended` 挡住写回，结束后统一 flush。**回归测试断言顺序**，`sorted()` / `len()` 抓不到。
29. **中键平移期间 `setInteractive( False )` + 主动清悬停**，否则画面从鼠标底下滑过、扫到的连线都 hover 亮一下、节点弹 tooltip。关掉后 Qt 不再发
    hoverLeave，要自己清已高亮的。
30. **`paint()` 里抛的异常被 Qt 吞掉**（只在日志刷一行 traceback），画面上就是那一块没有。几何断言（量矩形）全绿证明不了"画出来了" ——
    **真渲染一遍数亮像素**（`QImage` + `QPainter` + `item.paint()`），顺带量文字矩形下缘那两三行有没有墨（截断从下缘开始少）。

### 信号形参个数（多一个会被 `CatchingCombiner` 吞掉、**静默失效**）

| 信号 | 参数 |
| --- | --- |
| `nameChanged` / `childAdded` / `childRemoved` / `focusChanged` / Set 成员变化 | **2** |
| `plugSet` / `plugInputChanged` / `plugDirtied` | **1** |
| `errorSignal` / `Metadata.nodeValueChangedSignal( node )` / `plugValueChangedSignal( node )` | **3** |
| 勾选类菜单项的命令 | 多收一个 toggled → 签名要 `*unused` 兜底 |

信号连接也算钱：`connect( scoped = True )` ≈ 2 us；节点自己的 `childAdded` 只给会长子插口的直系插口连（`ArrayPlug` / `CompoundDataPlug` /
`TweaksPlug` / 裸 `Gaffer.Plug` 容器）。节点的 `childAdded` 也为插口发 —— 只关心节点时判 `isinstance( child, Gaffer.Node )`。

### 环境

31. **无头测试不能碰 `GafferArnold`** —— `ArnoldLight` / `ArnoldShader` 在 `gaffer env python` 里可能 SIGABRT（`free(): invalid size`）。规则用桩类验
    （桩类名要真以判据要求的后缀结尾，如 `...MeshLight`），真节点只在真机 e2e（screengrab）里验。
32. **`connectionGadget:color` 可能被站点扩展占用**（例如给 focus 节点整条上游链注册暖色高亮，`persistent=False`）。量类型配色前先
    `script.setFocus( None )`，否则量到的全是高亮色。
33. **改大段缩进之后，`py_compile` 过了不代表结构对**：最容易出的是缩多了一级、整块缩到上一个分支的 `continue` 后面 —— 语法合法、**静默不执行**。
    脚本化改缩进时，锚点若是**方法体里的行**（2+ 层缩进），按"`def` 在 1 层"算的缩进量一定过深；改完**逐行打缩进层数**核嵌套，特别看
    `continue` / `return` 之后那几行；别信 `cat -A | cut` 的列数（中文注释的字节展开会顶掉）。

---

## 九、热路径：哪几刀真值钱，怎么量

**先 profile 再动手**（`cProfile` 包 `view.render()` / 合成 `MouseMove` / `__rebuild`，600 个节点的图）：

| 热点 | 之前 | 之后 | 改法 |
| --- | --- | --- | --- |
| 空着手移动一次鼠标 | 3.3 ms | 0.13 ms | 一次 `items()` + 缓存 `boundingRect` + BSP 深度 |
| 600 个节点全在视口里画一帧 | 74 ms | 51 ms | 圆点绘制表 + 缓存字体 / 画笔 / 名字宽度 |
| 拉远到色块档画一帧 | 18 ms | 11 ms | `boundingRect` 缓存（Qt 一帧每个 item 问 4 次） |
| 首次建 600 个 item | 445 ms | 382 ms | 直系插口的 `childAdded` 只连会长子插口的那几个 |

- **`boundingRect()` / `shape()` / `cardPath()` 要缓存**。作废顺序：**先 `prepareGeometryChange()` 再清缓存** —— Qt 在里面拿**旧**包围盒把 item 从 BSP 摘下来
  （`removeItem` → `sceneEffectiveBoundingRect()`），缓存先清了就按新框去找、留一份脏索引。凡是影响包围盒的状态（hover / focus / 端标签 / 注释）都走同一个
  `__geometryChanged()`。
- **`items()` 一次鼠标移动只查一次**：`noduleAt` / `adderAt` / `sectionHeaderAt` / `backdropEdgeAt` / `backdropItemAt` 各问一遍就是 7~9 次。合并成一个探针
  （取最大半径），候选里各自判。`items( QPoint )` 的判据是「这一个像素映射到 scene 的小矩形和 `shape()` 求交」，照抄（别用 `contains()`，亚像素上会差）——
  再写一条**等价性测试**：几百个随机点 + 专门凑到圆点 / `+` / 分栏三角 / Backdrop 边上的点，逐个比新旧答案。
- **BSP 深度自己设**（`setBspTreeDepth( 16 )`）：Qt 自动定的深度切的是**整个 sceneRect**，而 sceneRect 留了两万像素平移余量 → 整张图挤在一两个叶子里。
  `items( QPoint )` 123 → 23 us。
- **paint 里别调 `relativeName`**：一次 C++ 调用 ~3 us，以前每帧每个圆点三遍。位置 / 半径 / 颜色 / key 在构造时一次算进一张表，paint 和 `noduleAt` 共用。
  `QPen( QColor( … ) )` / `QFont()` / `QFontMetrics` 按参数缓存（`functools.lru_cache`，`painter.setFont` 按值拷贝，共享安全 —— **别改返回值**）。
- **分栏节点 paint 里读元数据 = 每帧几百次 C++ 调用**：`sectionCollapsed` 只在 item 生命期内读一次（折叠状态一变元数据信号会重建 item）。判据是"这个状态变了
  会不会重建 item"。
- `__uiPosition` 变化按节点名记脏，连线由 `itemChange → _nodeItemMoved` 跟。

---

## 十、代码组织

### 单文件长到几千行之后怎么拆（拆完测试一行不用改）

两个硬要求：**功能不许丢**、**测试不许改**（测试里到处是 `NE._NodeItem` / `NE._matchScore` / `editor._NetworkEditor__nodeItems` 这类私有访问）。

1. **严格一层套一层**，下层不许回头引用上层，永远没有循环 import：

   ```mermaid
   flowchart LR
     constants --> graph["graph（只碰 Gaffer）"] --> layout --> qt --> backdrop_item --> node_item --> edge_item --> view --> panel --> editor --> register --> init["__init__（门面）"]
   ```

   每个模块开头 `from .上一层 import *`，天然看得见所有下层的名字 —— 和单文件时代同一个命名空间。

2. **每个模块结尾补一句**（关键）：

   ```python
   __all__ = [ name for name in dir() if not name.startswith( "__" ) ]
   ```

   `import *` 默认跳过下划线开头的名字，而私有名字恰恰是上层和测试在用的；显式列进 `__all__` 就能带上去。

3. **门面用 `__init__.py`** —— 包属性访问（`NE._NodeItem`）和名称重整（`_NetworkEditor__nodeItems`，只看**类名**不看模块）都照旧。唯一要改的是
   「用 `__file__` 数 dirname 找包内资源」的代码：给一个 `packageRoot()`，谁要资源问它（screengrab commandFile 里没有 `__file__`，也走它）。

4. **模块级可变全局必须和它的读写者同文件**（`global _x` 那种）：门面里的 `NE._creatorUsage` 这类**值**是拆分那一刻的快照，之后模块内 `global` 改的是
   模块自己那份 —— 外部一律**走函数**读写。

5. **分层有没有被破坏用 `symtable` 扫**（比 `ast.Name` 准，后者会把局部变量全报出来）：

   ```python
   table = symtable.symtable( source, path, "exec" )
   # 递归每个 scope，symbol.is_global() 为真的就是"引用了全局"
   ```

   自下而上累加"这一层可见的名字"，发现有名字不在里面就是跨层引用。

6. 顺手扫一遍**没人用的模块级名字**（正则数出现次数 ≤ 1）。

拆函数时按行号机械切，边界那两行要回头看（跨阶段的注释会被切成两半，`ast.parse` / black 都不报）。扁平的快捷键判定链别为拆而拆
（查表反而看不出修饰键条件）；`self.__xxx` 私有方法互调的大类别拆成 mixin（换类就要改名称重整）。

### 按 PEP 8 整理

Gaffer 自家风格（tab 缩进、`foo( a, b )`、`def f( x ) :`）不是 PEP 8。要转的话：

- **格式交给 `black`**（`--line-length 88`），别手改缩进。
- **命名保持 camelCase —— PEP 8 允许**（"mixedCase is allowed only in contexts where that's already the prevailing style"）。三重不可动：
  **Qt 虚函数覆写**（`paint` / `shape` / `boundingRect` / `mousePressEvent` / `itemChange` / `eventFilter`…）、GafferUI / Gaffer API 契约、测试和 startup
  引用的公开名。
- ⚠️ **删未用 import 之前先查 star-import 借用**：`from .x import *` + `__all__ = dir()` 的包，**上游的 `import os` 会漏到下游**，下游可能一直白用着它。用 AST
  比「每个模块用到的模块名 − 它自己 import 的」，借的地方补显式 import 再删。看着像死代码但不能动的：`scoped=True` 信号的 keep-alive 变量、带 `global` 的赋值
  （AST 扫描不处理 global 会假报警）。
- **只在函数里建的属性会变成"有时才存在"**：一律在 `__init__` 里先建好。
- **重构时让「没改格式的测试」当独立 oracle**：只动被测代码、`tests/` 一个字不改，每做一步跑一遍。测试和实现同一轮一起重构，出了问题分不清是谁的锅。

### 注释删什么、留什么

- **删历史叙事**（「以前是…后来改成…」「上一版就是这么干的」）—— 属于开发日志，不属于代码。
- **删重复解释**（同一条脚注抄 10 遍）、**删纯装饰**（`####` 横幅：模块头改 docstring，分节横幅直接删）。
- **留不变量和源码引用**：`StandardStyle.cpp:534`、`GraphGadget.cpp:1273`、「`plugInputChangedSignal` 沿下游链响 87 次」、「`QPainterPath` 默认 OddEvenFill
  会异或出洞」、「侧标一律按粗体量宽度」。判据：**删了会不会有人再踩一遍**。

---

## 十一、和原生对拍

"看起来对"不够时做一个**对拍脚本**（真机 screengrab，Arnold 才加载得到）：同一个 root 各建一个自己的编辑器和一个**真正的原生 GraphEditor**
（`_nativeGraphEditorClass()`，别拿被接管的壳），比三样：

1. **每个圆点**：`nodeGadget.nodule( plug )` 非空的插口落在哪条边（拿 `nodule.transformedBound( gadget ).center()` 和 gadget bound 比）、在那条边上排第几。
   ⚠️ **父插口拿到的是 `CompoundNodule` 容器不是圆点**（`parameters`、展开后的 `out`），要把「有子 nodule 的」排掉。
2. **每条连线**：`graphGadget.connectionGadget( plug )` 的 `srcNodule().plug()` / `dstNodule().plug()` —— 两边都用 **nodule 那一层**的相对名。
3. **节点尺寸**：`nodeGadget.bound()`。

一张真实材质图（`tests/shader_test.gfr`，34 个 ArnoldShader + 5 个 OSLShader）第一次跑就抓到 14 个缺失的圆点（`childrenVisible` 写在无子插口
FloatPlug 上那条），连线 62:62 全中。原生视图是 OpenGL 的，`grab()` 抓出来是黑图 —— **只能当数据上的参照**。e2e 里材质断言**别写死节点名**。

凡是"原生有、我们没有"的问题，第一步先和原生**对拍数量**（例如画出来的边数），只断言插口层面 `getInput()` 会一路全绿、什么都发现不了。

---

## 十二、注册与测试

```python
GafferUI.MyEditor = MyEditor
GafferUI.Editor.registerType( "MyEditor", MyEditor )
GafferUI.Layouts.acquire( application ).registerEditor( "MyEditor" )   # startup/gui/ 里调
```

Editor 类必须实现 `__repr__`（layout 序列化用），形如 `"GafferUI.MyEditor( scriptNode )"`。

在仓库根目录下（`gaffer` 指 Gaffer 1.7 安装目录下的 `bin/gaffer`）：

```bash
# 无头（数据层 + UI + 编辑）
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_network_editor.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_optimizations.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_review_v070.py
# 没有 GPU 加 LIBGL_ALWAYS_SOFTWARE=1；图标对拍那节要 GAFFERUI_IMAGE_PATHS 指向安装目录的 graphics/

# 真机端到端 + 出图（需要 GL 上下文 / Arnold 的都放这儿）
GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:$PWD" \
    gaffer screengrab -commandFile tests/e2e_network_editor.py -image out.png

# 真键盘真鼠标（xdotool）
DISPLAY=:0 gaffer env python tests/e2e_panel_input.py

# 自动排列对照台
QT_QPA_PLATFORM=offscreen gaffer env python tests/bench_layout.py
```

详细说明见 `docs/testing.md`。要点：

- **无头命令里的 `QT_QPA_PLATFORM=offscreen` 不能省**。不带它、机器上又有 `DISPLAY` 时 Qt 走真 X11：视口尺寸 / 可见性 / 曝光时机全不确定，`frame()`、
  「hide→show 之后画面留在原处」这类靠几何断言的用例**稳定挂**，拖动和重绘计数**随机**挂（`Qt.Popup` 的 `isVisible()` 在真 X11 不稳）。
- **计数式性能测试要先泵到"一帧都不画"再开测**：视图第一次显示必然全量画一遍，`ContextTracker` 异步那一拍也会刷整屏。settle 循环 = 连着两轮零重绘
  **且** `tracker.updatePending()` 为假。
- 无头测试里要 `GafferUI.EventLoop.waitForIdle()` 才能等到 defer 的重建；**建完编辑器之后才改的图，取 `__nodeItems` / `__edgeItems` 前先 `waitForIdle()`**。
- screengrab commandFile 里 `__name__ == 'builtins'`、没有 `__file__`，**不能加 `if __name__ == "__main__"` 守卫**。
- offscreen QPA 不支持窗口遮罩（`setMask` 值 Qt 侧记着、断言有效，但"角真被切"只能真机数像素）；offscreen 虚拟屏只有 800x800，大测试窗口一半在屏幕外，
  位置断言用纯函数算期望值比，别写死。
- **报告"条数一点没变"= 脚本中途抛异常了**：screengrab e2e、对照台这类**跑到最后才一次性写报告**的脚本，中途抛异常 → 文件压根不重写 → `grep -c PASS`
  读到的是**上一轮旧报告**，看着像"新断言没生效"。高频原因：新断言引用了文件里**后面**才定义的变量（e2e commandFile 是一整个模块作用域，循环变量还会覆盖上面
  建的同名节点）；插入点劈开一个 `if` 块（插完先 `ast.parse`）。规矩：**跑之前 `rm -f <报告文件>`、别把 stderr 丢进 /dev/null、读数字前先 `grep -c Traceback`**。
- **拿整包副本当 oracle**（只还原这一处改动、跑同一份新测试）来证明新断言抓得住；**改过的测试文件也要拷进副本** —— 先拷副本后改测试，oracle 报旧条数，看着像
  "新断言没生效"。判据：oracle 总条数应和主干一样多（没装可选 `parameterEditor` 扩展时 `P` 键那节的差额是正常的）。
- **flaky 的真机断言**：比"真屏幕抓图 vs 强制 repaint"的残迹类断言会被别的窗口盖住、或窗口挪到副屏却用 `primaryScreen().grabWindow()` 抓 → 首跑失败原地重跑，
  重跑全绿就不是回归。多个会话同时改同一个包时，先看 `ls -l` 的 mtime 再断定谁弄坏的。
