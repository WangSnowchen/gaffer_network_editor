# 开发中遇到的问题与解决方案

本文收录 NetworkEditor 开发过程中实测碰到的问题。每条按 **现象 → 原因 → 解决 → 验证 / 教训** 写；
源码出处的行号以 Gaffer 1.7 为准，1.6 时期的条目会单独注明。代码目标版本是 Gaffer 1.7（在 1.7.1.0 上测过）。

文中的「原生」指 Gaffer 自带的 `GafferUI.GraphEditor` 及其背后的 C++ gadget。

## 目录

1. [原生编辑器与依赖边界](#1-原生编辑器与依赖边界)
2. [和原生数据同步与重建](#2-和原生数据同步与重建)
3. [Gaffer 绑定与 API 陷阱](#3-gaffer-绑定与-api-陷阱)
4. [几何与命中测试](#4-几何与命中测试)
5. [绘制与重绘残影](#5-绘制与重绘残影)
6. [连线与接口](#6-连线与接口)
7. [选择与拖动](#7-选择与拖动)
8. [平移与缩放](#8-平移与缩放)
9. [快捷键与右键菜单](#9-快捷键与右键菜单)
10. [接管 GraphEditor 与隐藏引擎](#10-接管-grapheditor-与隐藏引擎)
11. [建节点面板 Tab](#11-建节点面板-tab)
12. [自动排列](#12-自动排列)
13. [Backdrop](#13-backdrop)
14. [材质节点分栏与类型图标](#14-材质节点分栏与类型图标)
15. [性能](#15-性能)
16. [代码组织与重构](#16-代码组织与重构)
17. [Gaffer 1.6 到 1.7 迁移](#17-gaffer-16-到-17-迁移)
18. [测试方法论](#18-测试方法论)
19. [故意不跟原生的取舍](#19-故意不跟原生的取舍)

---

## 1 原生编辑器与依赖边界

### 1.1 原生 GraphEditor 无法换观感

- **现象**：想要渐变、阴影、多层描边、任意字号、矢量图标，原生节点图一样都做不出来。
- **原因**：原生 GraphEditor 是 OpenGL 视图，节点由 `src/GafferUI/StandardStyle.cpp` 里一段写死的 GLSL 画，只支持纯色填充、一档圆角、一种深色描边和纹理贴图。`Style`、`GraphGadget`、`GraphLayout` 在 binding 里用的是 `RunTimeTypedClass` / `GadgetClass`，没有 wrapper，**不能从 Python 子类化**。能改的只有元数据里 5 个旋钮（`nodeGadget:color` / `shape` / `minWidth` / `padding` / `icon`）加 StandardStyle 的 8 个全局颜色。
- **解决**：另起一个 `QGraphicsView`。QGraphicsScene 是矢量的，缩放不糊，自带 BSP 索引和视口裁剪。
- **教训**：别走「用 Qt 把卡片画成纹理再贴进原生视图」这条路，每个节点一张贴图，节点一多就撑不住。

### 1.2 两个视图同时开着要互通

- **现象**：自己画的视图和原生 GraphEditor 同开时，位置、选择、focus 要两边一致。
- **解决**：所有状态都读写原生用的那份数据，不另存：

  | 东西 | 存在哪 |
  | --- | --- |
  | 节点位置 | `node["__uiPosition"]`（V2fPlug，节点**中心**，Gaffer y 向上） |
  | 连线折叠 | `__uiInputConnectionsMinimised` / `__uiOutputConnectionsMinimised` |
  | Backdrop 框 | `node["__uiBound"]` |
  | 选择 / focus | `script.selection()` / `script.getFocus()` |
  | 书签 / 注释 / 只读 | `Gaffer.MetadataAlgo` |

- **坐标约定**：`PX_PER_UNIT = 12`，Qt y 向下，换算 `y_px = -y * 12`。

### 1.3 依赖原生的哪些部分要量出来

- **现象**：一开始说不清「到底借了原生什么」，砍依赖时心里没底。
- **解决**：把原生拆成三层：
  - **L1 隐藏 GraphEditor**：一个不显示的原生 GraphEditor（建一个约 7.7ms，会真建 QOpenGLWidget）。借原生右键菜单、跑要 `menu` 的创建命令、转发 pipeline 注册在 `GraphEditor.instanceCreatedSignal` 上的快捷键都靠它。
  - **L2 裸 `GafferUI.GraphGadget( script )`**：纯 C++ 对象，不建 widget、不要 GL，建它几乎零成本。节点尺寸、接口位置、`+`、`StandardGraphLayout` 摆位从它来。
  - **L3 原生菜单定义与元数据**：不是窗口。
- 再用两个开关量依赖面：`GAFFER_NETWORK_EDITOR_ENGINE=0`（不建 L1）、`GAFFER_NETWORK_EDITOR_GADGET=0`（不问 L2）。关掉 L2 时挂的断言全是「新节点没位置」和「接口位置差几像素」（实测 ours `[-21.33, 0, 21.33]` vs native `[-21.6, -7.2, 7.2]`），说明 L2 留着值得。
- **结论**：要摆脱的只有 L1（见第 10 节），目标是「一个原生 GraphEditor 实例都不建」。L2 留着既零成本又换来和原生数值一致。

---

## 2 和原生数据同步与重建

### 2.1 在信号里同步重建，CPU 100% 永不空闲

- **现象**：开着原生 GraphEditor 时，本编辑器一重建就卡死，CPU 打满。
- **原因**：原生 `GraphEditor.__preRender` 会给没摆位置的节点写 `__uiPosition` → 发 `childAdded` → 我们在信号里同步重建 → 又触发原生渲染 → 再写 → 永不空闲。
- **解决**：所有信号只标脏，干活一律放进 `GafferUI.EventLoop.addIdleCallback` 的一次性回调（返回 `False`）。位置变化只移动已有 item，不重建。

### 2.2 只读路径上不能顺手建 `__uiPosition`

- **原因**：`__uiPosition` 是原生 GraphGadget 在 preRender 里按自动布局算完才建的。读位置时 `createIfMissing` 会抢先建出插口，把原生的自动布局搞坏。
- **解决**：读位置只读不建；没摆过位置的节点自己算临时位置，不写回。

### 2.3 进 Box 后节点挤在一起

- **现象**：进入 Box，内部节点叠成一团或斜着排，原生那边却整整齐齐。
- **原因**：Box 内部的节点常常没有 `__uiPosition`，原生是在 `GraphEditor.__preRender` 里现算的。我们没有 preRender。
- **解决**：进层时自己补一遍：
  ```python
  nodes = Gaffer.StandardSet( [ g.node() for g in graphGadget.unpositionedNodeGadgets() ] )
  graphGadget.getLayout().positionNodes( graphGadget, nodes, fallbackPosition )
  graphGadget.getLayout().layoutNodes( graphGadget, nodes )
  ```
  和原生一样**不进撤销栈**。

### 2.4 全量重建后选中 / focus / 变暗全丢了

- **现象**：focus 之后进 Box，「不参与计算的变暗」不生效；出 Box 后 focus 角标没了。
- **原因**：换层走全量重建，调的是 `__finishUpdate()` 的默认参数 `created = False`，新 item 全是默认状态，选中、focus、参与计算这三样是事后刷上去的，没有刷。
- **解决**：全量重建一律 `__finishUpdate( created = True )`。判断「是哪个节点」一律 `node.isSame()`，Box 里外重名太常见，按名字比会在别的层冒出假角标。

### 2.5 增量更新时选择被吃掉

- **现象**：删一个选中节点、或者增量更新动了 item 之后，script 的选择莫名其妙少了。
- **原因**：删掉一个选中的 item，`QGraphicsScene` 会发 `selectionChanged`，我们把它当成人为改选择写回 script。
- **解决**：动 item 的整段 `scene.blockSignals( True )`，并且放在 `try/finally` 里恢复（漏写 `finally` 时一旦中途抛异常，scene 信号就永久屏蔽）。

### 2.6 ArrayPlug 长出一路时接口不更新

- **现象**：往 NameSwitch / Collect 上丢线自动加了一路输入，卡片上没长出新圆点。
- **原因**：ArrayPlug 长一路时只有 `plugInputChangedSignal`，没有任何信号说「多了个接口」。
- **解决**：对这类节点额外拿 `noduleLayout()` 和 item 上的接口对一次指纹，不一样就重建这个 item。另外 ArrayPlug 的 `childAddedSignal` / `childRemovedSignal` 也连上，删输入口时卡片跟着缩窄。

### 2.7 接一根场景线，下游整条链都被标脏

- **现象**：接一根 ScenePlug 的线，`plugInputChangedSignal` 沿下游响了 87 次。
- **原因**：`in.transform` / `out.transform` 这类子插口的 pass-through 被重接了一遍，整条下游链都进了脏边集合，可它们画出来的边一条没变。
- **解决**：重收某个节点的入边时**先比 key**，没变就一个 item 都不动。收一遍便宜，拆了重建（带重绘）很贵。

### 2.8 节点元数据变了画面不动

- **现象**：右键 Show Name 之后节点外形没变。
- **原因**：Show Name 改的是 `nodeGadget:type`（`UIEditor.__setNameVisible`），形状、颜色、图标、书签、注释、接口布局都写在节点元数据里，没有监听就不会刷新。
- **解决**：连 `Gaffer.Metadata.nodeValueChangedSignal( node )`（3 参 `node, key, reason`），按 key 判要不要重建（`rebuildOnNodeMetadata()`）。

### 2.9 插口元数据要单独连信号

- **现象**：圆点右键「Expand RGB Components」点了，卡片不长出 r/g/b 子圆点。
- **原因**：`compoundNumericNodule:childrenVisible`、`noduleLayout:*`、`nodule:*` 是**插口**元数据，`nodeValueChangedSignal` 不报。
- **解决**：再连 `Gaffer.Metadata.plugValueChangedSignal( node )`（3 参 plug / key / reason）。

### 2.10 `enabled` 接上或拔掉驱动，停用画法不变

- **原因**：`enabled` 接线 / 断线只有 `plugInputChangedSignal` 报，而增量更新对它只标脏边、不重建节点 item。
- **解决**：入边变化时检查目标插口是不是节点自己的 `enabledPlug()`，是就重建这个 item。反过来，只认 `enabledPlug()`：Spreadsheet 行、Tweaks 成员里也有叫 `enabled` 的插口，按名字判会让它们一改就重建整张卡片。

### 2.11 靠「连没连」变样的东西不跟着刷新

- **现象**：材质参数接上线后，旁边的参数名应该加粗高亮，却一直停在建 item 那一刻的样子。
- **原因**：增量更新只标脏边，不重建节点 item。
- **解决**：给这类状态写只重算这一项的轻量刷新（`refreshSideLabels()`），在入边变化时**对线的两头**都调一次（源那头的 `out` 也要亮）。展开成一簇的子圆点按整簇判「接没接」。

### 2.12 拖动期间重建，这一下拖动静默失效

- **现象**：偶尔「拖了但节点没动」。
- **原因**：重建会删掉 item 重做，Qt 的隐式鼠标抓取跟着没了。
- **解决**：idle 回调里遇到「正在拖」就把脏标记留着，松手在 `mouseReleaseEvent` 里 `_flushPostponedUpdate()` 补上。判据要**同时**看自己的模式标记和 `QApplication.mouseButtons()`，只看模式标记的话，万一某条路松手没走到（合成事件、焦点被抢），重建会永久冻住。

### 2.13 编辑器拆掉后 idle 回调还在响

- **现象**：关掉面板后终端刷 `RuntimeError: Internal C++ object (_GraphView) already deleted`。
- **原因**：Python 那边的属性还指着已销毁的壳，`is not None` 判不出来。
- **解决**：`__viewAlive()` 真去碰一下 `viewport()`，抛 `RuntimeError` 就当死了，回调返回 `False` 注销自己。

### 2.14 File > Revert 之后 item 连着已删除的节点

- **现象**：Revert、Reference 重载、删掉再建同名节点之后，卡片还连着旧节点，编辑无效。
- **原因**：item 按名字索引，新节点同名，增量 diff 认为没变。
- **解决**：结构变化时按 `isSame` 核对 item 背后的节点，换了就重建。

### 2.15 改名

- `nameChangedSignal` 要标结构脏并重建那个 item：item 按名字存，改名等于换一个。
- 当前所在的那一层被改名时，标题和面包屑跟着刷；被移出图时退回脚本根（照原生 `__rootNameChanged` / `__rootParentChanged`）。

### 2.16 `scene.clear()` 销毁临时 item

- **现象**：按住 `X` 划线时，另一个视图写了 `__uiPosition` 触发重建，接着崩在 `cutItem.setPath()`。
- **原因**：`scene.clear()` 会销毁加在 scene 上的所有 C++ item，包括自己加的划线虚线、拖拽中的临时连线，Python 包装对象还在。
- **解决**：全量重建前 `_discardTransientItems()` 把它们置空，相关调用包 `try/except RuntimeError`。增量更新不清 scene，天然更安全。`_discardTransientItems` 也要清 Backdrop 拉框状态。

### 2.17 读 `enabled` 触发计算，图里有环时刷屏

- **现象**：大图上画停用状态很慢；图里有依赖环时终端刷一屏 `Cycle detected`。
- **原因**：`enabled` 被上游驱动时 `getValue()` 是一次真正的计算。
- **解决**：照原生 `StandardNodeGadget` 的 `hasStaticValue()`（`StandardNodeGadget.cpp:520`），用 `Gaffer.PlugAlgo.dependsOnCompute` 判：不依赖计算才读值，依赖计算时交给 ContextTracker（见 6.15），拿不准就画第三态。

### 2.18 错误角标

- `node.errorSignal()` 是瞬时的（计算时抛），不是持久状态，要自己累积，和原生 `ErrorGadget` 一样。
- 错误角标要能消：原生在 `plugDirtied` 里 `removeError`，照做。
- `errorSignal` 可能在**计算线程**上发，直接碰 Qt 会出问题：先 `executeOnUIThread` 回 UI 线程（原生是 `callOnUIThread`）。
- 角标按名字记的话，换层或同名新节点会继承旧角标：换层清空，节点没了或换了才清。
- 出错信息挂进节点的悬停提示（原生 ErrorGadget 也是 tooltip）。

### 2.19 位置更新每次都全图重算

- **解决**：`__uiPosition` 的信号按节点名记进 `__dirtyPositions`，只挪那几个节点；连线由 `itemChange → _nodeItemMoved` 跟着算。

### 2.20 每一层的视野要各记一份

- **现象**：放大盯着某个 Box 看 → 进去 → 出来，出来就成了全景。
- **原因**：换 root 后无脑 `frameAll()`。
- **解决**：照原生 `GraphEditor._HistoryWidget` 把 frame 存进历史：换层前按**节点对象**（`isSame`）记下可见矩形，到新层先查记过没有，有就 `fitInView` 回去，第一次来才取全景。

### 2.21 右键 Show Contents 进 Box，Box 里的节点被搬走

- **现象**：右键菜单点 `Show Contents...` 进 Box，Box 里没连线的节点全被搬到菜单弹出的位置，而且不进撤销栈。
- **原因**：「刚建的节点要摆到鼠标处」的记录（`__pendingCreate`）记的是上一层的节点名，换层后和这一层比对，全算成刚建的。
- **解决**：记录里带上 root，`setRootNode` 时一并作废。

### 2.22 选择同步按裸名字比对

- **现象**：别层选中一个叫 `in` 的节点，这一层的 BoxIn 也显示成选中；点这层那个又选不上。
- **原因**：每个 Box 里都有叫 `in` / `out` 的 BoxIn / BoxOut。
- **解决**：只认 `parent().isSame( root )` 的那批，别层的一律清掉（原生点一下就是 `selection()->clear()`）。

### 2.23 选择写回要 diff，并且延到松手

- **现象**：拖框选时 NodeEditor / Viewer / HierarchyView 疯狂跳。
- **原因**：`QGraphicsScene.selectionChanged` 每帧都发，每次 `clear()` + 全量 `add()` 让每个节点各发一次 memberRemoved / memberAdded。
- **解决**：按住鼠标时不写回（直接问 `QApplication.mouseButtons()`），松手统一写；只删该删的、只加该加的。编辑操作一律以 `script.selection()` 为准，不看 scene 选中状态（同步是延后的，可能差一拍）。

---

## 3 Gaffer 绑定与 API 陷阱

### 3.1 Python 包装对象身份不稳定

- 同一个 C++ 对象每次访问都可能得到新的 Python 包装，`a is a` 都可能为假。比较节点 / 插口一律 `isSame()`（`None` 没有 `isSame`，要特判）。1.7.1.0 仍然如此。

### 3.2 插口身份不能用 `plug.getName()`

- NameSwitch 上 `in.in0.value` / `in.in1.value` / `out.value` **全叫 `value`**。拿 `getName()` 当键的字典（位置 / 颜色 / 切线 / 连线 key / 接口指纹）会互相覆盖。一律用节点内相对名 `plug.relativeName( node )`（`plugKey()`）。这个坑的完整经过见 6.4。

### 3.3 没绑 Python 的 C++ 方法

- `BoxIO.direction()`、`Switch.inPlug()`、`Loop.inPlug()` 到 1.7.1.0 都没有 Python 绑定。BoxIO 按类型分（`Gaffer.BoxIn` 是输入、`Gaffer.BoxOut` 是输出），其余一律 `getChild( "in" )`；AttributeQuery 这类用 `isSetup()`。
- PlugAdder（节点上的 `+`）在 C++ 匿名命名空间里，从 `nodeGadget.children()` 拿回来是光秃秃的 `Gaffer::GraphComponent`，`bound()`、`getVisible()` 都问不到。详见 6.6。

### 3.4 ArrayPlug 取元素只能用下标

- `plug[ i ]` 可以；`getChild()` 只收名字，传 int 直接 `Boost.Python.ArgumentError`。

### 3.5 `Metadata.value` 会解包

- 读 `IECore.BoolData` 拿回来的是 Python `bool`，所以 `isinstance( data, IECore.BoolData )` 永远为假。写成 `return bool( data )`。
- `Gaffer.Metadata.value()` 不接受 Python 类作 target，类级元数据只能拿实例回读。

### 3.6 信号形参个数必须严格匹配

- 多声明一个形参，Python handler 抛 `TypeError`，被 `CatchingCombiner` / `EventSignalCombiner` 吞掉，回调**静默失效**。
  | 信号 | 参数个数 |
  | --- | --- |
  | `nameChanged` / `childAdded` / `childRemoved` / `focusChanged` / Set 成员变化 | 2 |
  | `plugSet` / `plugInputChanged` / `plugDirtied` | 1 |
  | `errorSignal` | 3 |
- 勾选型菜单项的命令会多收一个 toggled 参数，签名用 `*unused` 兜住。
- 排查「没反应」先查信号签名，别加 try/except 把错误吞得更深。

### 3.7 Gaffer 信号「第一个返回 True 的就截住」

- `EventSignalCombiner` 遇到第一个返回 True 的 handler 就停。转发按键时 pipeline 的处理器排在前面接住了，测试探针就收不到。验证链路要用没人要的键（例如 F5）。

### 3.8 `NodeMenu` 在无头测试里是空的

- `NodeMenu` 挂在 `applicationRoot._nodeMenu` 这个 Python 属性上，而 Boost 包装对象只有 **Python 子类**才保得住属性。真实 Gaffer 的 root 是 Python 子类（`Gaffer.Application` 内部的 `_NonSlicingApplicationRoot`），所以没事；无头测试里直接 `Gaffer.ApplicationRoot()` 每次拿到新包装，菜单永远空。测试里要自己派生一个子类。
- 裸 `gaffer env python` 也不跑 gui 启动脚本，NodeMenu、节点右键菜单里的 `/Focus`、`/Bookmarked` 都没人注册；`DotUI` 的「插入 Dot」要 `GafferUI.DotUI.connect( appRoot )` 才打开。这些在无头下缺失都不是回归。

### 3.9 `MetadataAlgo.bookmarks()` 只扫直接子节点

- **现象**：按 `B` 找书签什么都不发生。
- **原因**：`Gaffer.MetadataAlgo.bookmarks( script )` 只遍历直接子节点（`MetadataAlgo.cpp:420` 就是个 `Node::Iterator`），生产里书签基本都在 Box 里，返回空列表；老代码 `if not bookmarks : return` 静默退出。
- **解决**：照原生 `GraphBookmarksUI` 用 `Metadata.nodesWithMetadata( script, "bookmarked", instanceOnly = True )`（递归，而且快），排掉 `ancestor( Gaffer.Reference )` 非空的（Reference 里的跳进去也改不了）。一条都没有时也弹面板，给一条灰的 `No bookmarks available`。

### 3.10 `nodeGadget.nodule( 父插口 )` 返回的是容器

- 对 `parameters`、展开后的 `out` 这类父插口返回的是 `CompoundNodule` 容器，不是圆点。数圆点时要把「有子 nodule 的」排掉。

### 3.11 原生 gadget 里的容器是懒排的

- **现象**：对拍测试量原生子圆点，位置全是 `V3f(0,0,0)`。
- **原因**：`StandardNodeGadget` 里的 `LinearContainer` 懒排，没问过尺寸就直接 `nodule( plug ).transformedBound()`，拿到的是父容器局部坐标。
- **解决**：先调一次 `nodeGadget.bound()`。

### 3.12 `type` 插口分不出材质类型

- `ArnoldShader.loadShader()` 之后，所有 Arnold 材质的 `type` 都是 `ai:surface`（image / noise / color_correct 全一样）。要分类只能看 shader 名字和 `out` 的插口类型（`ClosurePlug` = 真材质，Color / Float = 纹理或工具）。

### 3.13 「展开没展开」的判据

- 真机上 Arnold 材质的 `out` 没注册 `nodule:type`（那是 Gaffer 按插口类型给的默认 nodule），卡着 `nodule:type == CompoundNumericNodule` 判，原生菜单点了卡片永远不长子圆点。判据只能是 `compoundNumericNodule:childrenVisible`。
- 反过来，这条元数据在真实 `.gfr` 里会出现在**没有子插口的 FloatPlug** 上（一张生产材质图里有 38 处，多半是右键菜单落到父插口之外时写上去的）。原生对这种插口画的还是普通 `StandardNodule`。照着递归，圆点凭空消失、线画到空处。判据要再加一句「真的有子插口」：`len( plug.children( Gaffer.Plug ) )`。

### 3.14 `settable()` 不能用来判「能不能改接线」

- 已经被驱动的输入插口 `settable()` 为 False（值被上游接管了），而拆连接根本不看这个。用 `MetadataAlgo.readOnly()` 判。

### 3.15 `__` 开头的插口与辅助连线

- `__` 开头的插口一定没有 nodule：`NoduleLayout::layoutOrder()` 一进循环就 `starts_with( name, "__" ) → continue`。`hasNodule()` 不判这条，Expression 的 `__in` / `__out` 会被当成有 nodule，表达式的连线虚实混杂。
- 辅助连线反过来**不能**一律跳过私有插口：原生 `AuxiliaryConnectionsGadget.cpp:89` 是 `ignorePrivatePlugs = !runTimeCast<Expression>( dstNode )`，Expression 的输入就挂在私有的 `__in` 里，跳过的话「表达式读了谁」那些线全丢。辅助连线按端点去重（一对端点一条线）。

### 3.16 `ContextTracker` 是异步的

- `GafferUI.ContextTracker.acquireForFocus( script )` 在后台算，焦点刚变时 `isTracked()` 全是 False。照着刷新会先暗一帧（「点 focus 闪一下」）。`updatePending()` 为真时什么都别动，等 `changedSignal()` 再刷。测试里也靠 `updatePending()` 等它算完。

### 3.17 删掉被 focus 的材质时报 `SceneCreator "Default" not registered`

- 这条是原生自带的：焦点在材质上、那个节点被删 → `ShaderView` 的输入没材质 → `shaderPrefix()` 是空串 → 空前缀下没注册过 scene（`ShaderView.cpp:395`）。裸 `script.removeChild()` 一样报。
- **解决**：删除 / 剪切前如果要删的就是 focus 节点，先 `setFocus( None )`（`__clearFocusIfDeleting`）。

### 3.18 注释

- 注释里的 `{插口路径}` 要替换成插口值（`AnnotationsGadget::substitutePlugValues`，找不到换成空）。照抄文本会在节点旁画出字面的 `{name}`。
- 值的格式照原生 `formatPlugValue`：Bool 写 On / Off，复合 / 向量用逗号连。
- 求值要在 focus 的 context 里：`ContextTracker.context( node )`。
- `shader_type` **不是**注册过的注释模板（1.7.1.0 只有 `performanceMonitor:*` 和 `contextMonitor`）。默认 pattern 里放 `__untemplated__` 等于在每个 Arnold 材质下面写一行 `standard_surface`。默认只画 `user`。无头没注册模板，两边行为不同，这条只有真机 e2e 抓得到。

### 3.19 `QtGui.QGuiApplication` 在 Qt.py 壳里不存在

- `hasattr( QtGui, "QGuiApplication" )` 实测 False。写成 `QtGui.QGuiApplication.screenAt( pos )` 会每次 AttributeError。要用 `QtWidgets.QApplication.screenAt()`。后果见 11.7。

### 3.20 无头不能碰 `GafferArnold`

- `ArnoldLight` / `ArnoldShader` 在 `gaffer env python` 里直接 SIGABRT（`free(): invalid size`）。灯光形状、图标规则用桩类验（判据按 MRO 类名），真节点只能在 screengrab e2e 里验。桩类名要真以 `MeshLight` 结尾，`ArnoldMeshLightStub` 这种不匹配 `endswith` 判据。

### 3.21 screengrab 的 commandFile

- 里面没有 `__file__`，`__name__` 是 `'builtins'`。带 `if __name__ == "__main__":` 守卫的脚本静默不执行。找包里的资源从模块反推，所以包里提供 `packageRoot()`。

### 3.22 插口上的 `connectionGadget:color`

- 原生 `StandardConnectionGadget` 会读插口上的 `connectionGadget:color` 覆盖连线颜色（`StandardConnectionGadget.cpp:710`）。环境里装了往这个键注册颜色的扩展时，连线就变成扩展的配色。本编辑器不读它，连线颜色只跟接口类型走。

### 3.23 `QGraphicsItem` 自带 `setActive()` / `isActive()`

- 那是面板激活用的，自定义 item 别占这两个名字（我们叫 `setWireActive` / `setNodeActive`）。

### 3.24 `QMouseEvent.pos()` 在 PySide6 已废弃

- 用 `event.position().toPoint()`，包一个 `_eventPos()`。6 参 `QMouseEvent` 构造在 Qt 6.4 起标了 deprecated，6.5 上照常工作。

---

## 4 几何与命中测试

### 4.1 节点大小别自己发明

- **解决**：问原生要：节点尺寸 `nodeGadget.bound()`（标准节点 11 x 4.164 单位，Dot 2.5，AuxiliaryNodeGadget 2 x 2）、接口位置 `nodule.transformedBound()`、出射方向 `connectionTangent()`。接口挂哪条边按 `connectionTangent()` 分，元数据推出来的边偶尔和原生对不上（NameSwitch 会串位）。
- 无头算名字宽度用 `GafferUI.Style.getDefaultStyle().textBound( LabelText, name )`，回退公式 `宽 = max( minWidth, 名字宽 + 2 ) + padding*2 - 1`。
- 裸 `GafferUI.GraphGadget` 可以当尺子，实测它不会去建 `__uiPosition`，也不要 GL。

### 4.2 死守原生宽度会截字

- **现象**：节点名被截成 `Create...tSetup`，类型图标被挤掉。
- **原因**：原生宽度是按它自己的字体、而且没有类型图标算的。
- **解决**：高度照原生，**宽度取 `max( 原生, 图标 + 名字所需 )`**，名字整条画、不做省略。卡片撑宽后，原生给的接口 x 坐标按同一比例拉开（`__noduleScaleX = _width / __nativeWidth`），圆点仍旧贴边。测试逐个节点断言 `nameFits()` 和「有图标的节点都留够位置」。

### 4.3 `shape()` 跟着 `boundingRect()` 走，吃掉邻居的点击

- **现象**：两个挨得近的节点（只隔 6 个单位），从一个的小圆点拖到另一个上连不上。
- **原因**：`boundingRect` 在有接口被悬停时会撑大一圈（放得下放大的圆点和标签），而 Qt 命中测试用 `shape()`，默认实现就是 boundingRect。刚悬停过的那个节点（z 还被抬高了）把周围一大片点击和拖放全吃了。
- **解决**：`shape()` 自己写，只包卡片和一小圈余量，不随悬停变化。悬停进出也别作废 `shape()` 缓存。

### 4.4 `QPainterPath` 默认 OddEvenFill，重叠部分被异或成洞

- **现象一**：材质节点分栏的折叠三角点了没反应，item 自己的 `sectionAt()` 却判对了。
- **原因**：`shape()` 往同一条 path 上 `addRect( 卡片 )` + `addRect( 三角命中框 )`，三角贴在卡片边线上，两块重叠的部分在 OddEvenFill 下被异或成洞，`view.items()`、`item.contains()`、`nodeItemAt` 在那一小片全返回空。
- **现象二**：Backdrop 的 `shape()` 由四条边组成，四个角点不中，同一个原因。
- **解决**：`path.setFillRule( QtCore.Qt.WindingFill )`。
- **确诊手法**：沿一条水平线逐点打 `shape().contains()`，洞一眼可见（实测 dx=-120 True / -130 False / -147 True）。`boundingRect()` 是对的，别盯它。

### 4.5 画在卡片外面的东西点不中

- **现象**：从别的材质 `out` 拖连线到 `+` 上一点反应都没有。
- **原因**：`+`、focus 角标、卡外侧标都不在 `shape()` 里（`shape()` 只包卡片），光标正压在 `+` 上时 `nodeItemAt` 反而是 None。
- **解决**：`adderAt()` 找不到时在光标周围（28×28）取一小块区域再捞一遍。只把**真需要点的小命中框**（例如每栏的三角）加进 `shape()`，别把整条名字都加进去，否则悬停余量又会吃邻居的点击。

### 4.6 `__dragDestination` 会替你挑插口

- **现象**：`+` 的优先级永远抢不过「接到节点身上」。
- **原因**：照原生 `closestDragDestination`，落在节点身上它就给最近的一个接得上的插口，哪怕离得老远。
- **解决**：「让 `+` 赢」的判据取「光标没正压在任何圆点上」。拿「有没有目标插口」判，`+` 永远输。

### 4.7 圆点画在卡片边界上，瞄着圆点丢却接不上

- **原因**：顶边那排圆点在卡片外 2px，命中只比卡片大一圈，光标常整个落在节点外面。
- **解决**：松手时在光标周围 `CONNECT_REACH`（28px）里再捞一遍最近的节点，`noduleAt` 也补同样的兜底；拖到圆点本身时圆点命中优先。

### 4.8 卡片上的「按钮」误触

- **现象**：点 Dot 会让 focus 乱跳。
- **原因**：focus 折角画在卡片右上角内侧，在 132×50 的标准节点上只占 3%，按比例缩到 30×30 的 Dot 上占两成面积；命中又按三角形的包围盒判（面积再翻倍）。Dot 卡片 121 个采样点里 25 个会误触。
- **解决**：所有节点的折角一律画在卡片右上角**外侧**、同一个尺寸（原生 FocusGadget 本来也在节点外面），命中按三角形斜边 `dx + dy <= size` 判，留 1.5px 容差。误触 25/121 → 1/121。

### 4.9 Dot 上看不到 focus 角标

- **原因**：Dot 走 `paint()` 的早退分支（`if shape == SHAPE_DOT : return`），压根画不到角标那一步。
- **解决**：focus 角标、书签这类「一眼找到某个节点」的东西画在**所有早退之前**。画到卡片外面之后底下是深背景，悬停提示的透明度要加重（22/110 → 78/215），不然等于没画。

### 4.10 `QGraphicsScene.items( rect )` 用的是 `shape()`

- **现象**：分栏标题行点名字中间没反应，只在卡片边 10px 内有效。
- **原因**：`items()` 默认 `IntersectsItemShape`，标题画在 `shape()` 之外。
- **解决**：见 4.5，把需要点的命中框加进 `shape()`。

### 4.11 同一段文字两种字重，要按宽的那档量

- **现象**：材质参数接上线后，参数名被裁掉头。
- **原因**：接上线画粗体，宽度却按常规字量。
- **解决**：一律按粗体量（`filter` 实测 23.2 → 27.3px），位置靠对齐方式固定住。

### 4.12 BSP 索引等于没有

- **原因**：Qt 按 item 数自动定的 BSP 深度切的是**整个** sceneRect，而 sceneRect 每边留了两万像素平移余量，整张图挤在一两个叶子里。
- **解决**：`setBspTreeDepth( 16 )`。`items( QPoint )` 123 → 23 us。

### 4.13 一次鼠标移动查了 7~9 次 scene

- **原因**：`noduleAt` / `adderAt` / `sectionHeaderAt` / `backdropEdgeAt` / `backdropItemAt` 各自 `items()` 一遍，一次移动 12.9 万次 `boundingRect`。
- **解决**：合并成一次探针（取最大半径），在候选里各自判；判据照 Qt `items( QPoint )`：一个像素映射到 scene 的小矩形和 `shape()` 求交（用 `contains()` 在亚像素上会差）。写一条等价性测试：几百个随机点 + 专门凑到圆点 / `+` / 分栏三角 / Backdrop 边上的点，逐个比新旧答案。3.3ms → 0.13ms。

### 4.14 `QRect` 的宽度与端点

- `QRect.right()` 含端点（`left + width - 1`），`QRect.width() == right() - left() + 1`。夹最小尺寸时的 `±1` 不能省（实测 301 vs 300）。

---

## 5 绘制与重绘残影

### 5.1 `FullViewportUpdate` 让改一根线重绘整屏

- **现象**：300 个节点的图，改一根线 300 张卡片全重画。
- **解决**：`SmartViewportUpdate` + `CacheBackground`。前提是所有自绘的东西都能正确报脏区：橡皮筋是独立的 `QRubberBand` 控件（天然安全）、划线和临时连线是真的 `QGraphicsItem`（`setPath` 内部会 `prepareGeometryChange`）、`drawForeground` 画的吸附参考线在变化时自己 `viewport().update()`。改一根线：节点重绘 300 → 18、连线 275 → 30。

### 5.2 `boundingRect()` 漏了描边的一半，留下一排竖线

- **现象**：选中 Backdrop 后拉右边框，右边留下一排等间距的 1px 竖线，垂直跨度正好等于框高。
- **原因**：Backdrop 的 `boundingRect()` 恰好等于框本身，而选中时描边 2px 居中画在路径上，往外溢 1px（加抗锯齿又一圈）。Qt 只重画包围盒里的东西，那一圈永远擦不掉，每帧留一条，连续拖攒成一排。不选中时描边 1px，看不出来，所以复现条件是「全程保持选中」。
- **解决**：拆成 `frameRect()`（框本身，绘制、`shape()`、边缘命中、框选判定、标题描述矩形都用它）和 `boundingRect()`（外扩 `BACKDROP_STROKE_MARGIN = 3`）。
- **教训**：`boundingRect()` 必须把 pen 宽的一半算进去。「包围盒恰好等于自己画的那个矩形」的 item 最容易漏，节点卡片因为有十几像素悬停余量一直把这个问题盖住了。

### 5.3 拖动途中别动 `sceneRect`

- **现象**：拉 Backdrop 时大面积不重画，而且往左拖框反而越来越长（`max.x` 44.6 → 57.0）。
- **原因**：`_resizeBackdrop` 里每帧顺手 `setSceneRect`，改滚动条范围让视图漂一下，漂移只有那个 item 报了脏；另外拉框的坐标换算经过了 item 局部坐标，而 item 摆在框中心、中心一直在动，两个基准混用每帧累加偏移。
- **解决**：松手时再更新 sceneRect（`SCENE_MARGIN` 余量足够画到外面）；拉框坐标用「scene 坐标 − `__uiPosition`」（原生 `dragMove` 的 `event.line.p0` 就是这个语义）。

### 5.4 尺寸和位置一起变时旧区域没擦掉

- **原因**：`prepareGeometryChange()` 记的是「当前」包围盒，紧接着的 `setPos()` 会用**新**包围盒去标记旧位置那一块。
- **解决**：改几何前记下旧的 scene 区域，改完显式 `scene.update( 旧区域 )`。

### 5.5 按 `1/lod` 放大的东西画到包围盒外

- **现象**：框选一组节点拖着走，光标压着的那个节点留一串金色拖影。
- **原因**：两处叠加。①focus 角标在「focus **或**悬停」时都画，包围盒的大余量却只在 `_focused` 时才留；②角标为了屏幕上大小恒定按 `FOCUS_TAB_MIN_PIXELS / lod` 补偿，**没有下限**，缩到 `MIN_ZOOM = 0.02` 时角标在 item 坐标里有 550px，包围盒只有 222px。
- **解决**：补偿夹在 `FOCUS_LOD_FLOOR = 0.09`（更远时角标跟着画面一起变小，那时节点本身也只剩十几像素）；包围盒判据改成「会不会画」（`focusFlagVisible()`），按 `focusTabMaxSize()` 留余量。书签编号同理（`BOOKMARK_MAX_SCALE`）。
- **教训**：`boundingRect()` 是几何，只能在 `prepareGeometryChange()` 之后变，而 lod 要到 `paint()` 时才知道。任何按 `1/lod` 放大的绘制都必须夹上限。

### 5.6 画在卡片外面的一切都要进包围盒

- 卡外的参数名、`+`、focus 角标、**节点右边的注释**（多条竖排，溢出卡片底部的也要算）。注释按最长那条字宽往右让（建 item 时量一次）。漏了就是拖动留文字拖影。
- 悬停放大的标签用完整参数名，长名字会伸出写死的 150px 余量：按实际字宽算余量，不写死。

### 5.7 改了影响包围盒的状态却不报几何变化

- **现象**：设 focus 后拉远拖动，留金色拖影。
- **原因**：`setFocused` 没有 `prepareGeometryChange()`，角标那一片在 BSP 索引里还是旧的。
- **解决**：hover / focus / 端标签 / 注释凡是影响包围盒的，统一走一个 `__geometryChanged()`。

### 5.8 缓存包围盒时作废顺序

- **先 `prepareGeometryChange()` 再清缓存**：Qt 在里面拿**旧**包围盒把 item 从 BSP 里摘下来（`removeItem` → `sceneEffectiveBoundingRect()`），缓存先清了它就按新框去找，留下一份脏索引。

### 5.9 `paint()` 里抛的异常被 Qt 吞掉

- **现象**：Backdrop 的描述文字没画出来，几何断言全绿。
- **原因**：拆函数时漏掉 `scale = self._scale`，描述那段 `NameError`，`paint()` 里的异常被 Qt 吞掉，只在日志刷一行。
- **教训**：几何断言证明不了「画出来了」。关键元素要真渲染一遍数亮像素。

### 5.10 文字下缘被截

- **现象**：Backdrop 标题 `g` / `y` 的下伸笔画、中文的下半格被切掉。
- **原因**：拿 `QFontMetricsF.height()`（浮点）直接当矩形高度。
- **解决**：`ceil( height ) + BACKDROP_TITLE_SLACK`。测试数「标题下面那两行像素有没有墨」，截断就是从下缘开始少的。

### 5.11 1px 分隔线淡到看不见

- `drawLine( ..., rect.top(), ... )` 开着 Antialiasing 时半个像素落在矩形外。画 1px 分隔线关掉抗锯齿。

### 5.12 标题条顶角露缝

- **现象**：分栏材质节点加宽的标题色带，顶上两个角露出细缝。
- **原因**：直接画圆角矩形，圆角半径和卡片轮廓对不上。
- **解决**：`painter.setClipPath( 卡片 path )` 后填矩形。

### 5.13 亮色色带上的白字看不清

- **解决**：标题文字色按色带亮度挑：亮度 > 0.55 用深色 `#15171a`，否则用常规文字色（`_contrastTextColor()`）。

### 5.14 卡内文字和节点底色糊成一团

- **现象**：分栏材质节点卡内的未接线参数名和卡片底色几乎同色。
- **原因**：未接线文字沿用卡外的画法 `mixColors( noduleColor, 深背景, 0.45 )`，卡片底本身就是节点色混出来的。
- **解决**：卡内未接线 `mixColors( noduleColor, 文字色, 0.30 )`（向白提亮、保留类型色相）；接上线照旧强调色 + 粗体；卡外照旧。

### 5.15 图标里的「缝」

- 复刻原生灯光图标时，原生 PNG 里的接缝 / 经纬线是把填充掏掉露出底色。用 `CompositionMode_Clear` 会把卡片也打穿；改为按亮度把前景色混黑或混白一档（`_glyphSeamColor()`）。浮在填充外的缝（灯泡）要 `setClipPath` 裁进填充，否则空气里拖出深色圆环。

### 5.16 远景整卡刷金色，认不出 focus

- **现象**：拉远之后 focus 节点被整张刷成金色，而灯光节点本来就是黄卡片。
- **原因**：远景（`lod < LOD_MEDIUM`）走另一条早退分支，那里把整卡刷成 focus 色。
- **解决**：远景照常按节点颜色画，只在卡片外面支一个屏幕大小恒定的三角角标。LOD 档位放宽（`LOD_MEDIUM` 0.30 → 0.18）。

### 5.17 残迹只能在真屏幕上验

- `widget.grab()` 永远重新渲染一遍，看不到残迹。要用 `screen.grabWindow()` 抓屏幕上真实显示的内容，再和强制 `repaint()` 之后的内容逐像素比。
- 测量本身会 `repaint()`，所以脚本里每帧只看到一条线（例如 59 个采样点）；实际连续拖动不重绘才攒成一排。别因为数字小就当噪声。
- 窗口挪到副屏却用 `primaryScreen().grabWindow()` 抓，多显示器下这条测量天生不稳，失败时重跑通常就绿。

---

## 6 连线与接口

### 6.1 连线不能照着 `getInput()` 全画

- 大量插口带 `nodule:type = ""`，全画会冒出原生看不见的线。两端没有 nodule 的（表达式驱动）画成虚线，对应原生 AuxiliaryConnection，颜色固定 `AuxiliaryConnectionColor`，不吃类型色。
- 父插口连上时 Gaffer 会同时给每个子插口设 input，不挡住会画一堆重复线：遇到有 input 的插口就停止下钻。

### 6.2 ArrayPlug 要摊成一排圆点

- 原生靠 `nodule:type = "GafferUI::CompoundNodule"` 标记（`GafferSceneUI/SceneProcessorUI.py:58`），圆点画在 `in0` / `in1` / … 上。不照抄的话 Group / Merge 只有一个接口，连线全挤在一点。`nodulePlug()` 负责把任意深度的插口解析到「画着 nodule 的那一层」。

### 6.3 接口颜色

- 「看圆点认类型」靠的是插口上的 `nodule:color`（原生 `startup/gui/graphEditor.py` 按插口类型注册），别按插口类名自己发明配色；没注册用 StandardStyle 的 RaisedColor `#666666`。
- 连线按接口类型色上色（源插口优先），类型色画成 1.5px 细线压在深底上太暗，亮度低于 0.42 的按比例提到 0.42、色相不变；没有类型色用原生 `ConnectionColor` `#999999`。
- 长连线中段渐隐时 pen 里装的是 `QLinearGradient`，`pen().color()` 是黑色；量颜色要看 `pen().brush().gradient().stops()[0]`。

### 6.4 「NameSwitch 第二个圆点连不上」

这个问题前后反复了好几轮，最后查出是几个原因叠在一起：

- **现象**：同一个源接到 NameSwitch 的第二路，原生窗口里看是连着的，本编辑器里看不到这根线。
- **根因一：连线 key 用了 `plug.getName()`**。key 写成 `( srcNode.getName(), srcPlug.getName(), dstNode.getName(), dstPlug.getName() )`，NameSwitch 每一路是 `NameValuePlug`，圆点画在 `in.in0.value` / `in.in1.value` 上，两个插口 `getName()` 都是 `"value"`，两条边算成同一条，第二条在 `collectEdges` 里被当重复扔掉（增量更新按 key diff，同样漏）。接口指纹 `_noduleSignature()`、辅助连线去重 key 是同一个坑。全部改用 `plugKey( node, plug )`。
- **根因二：圆点命中范围不够**，见 4.7。
- **根因三：按在已连接的输入圆点上应该是「改接 / 断开」手势**（原生 Reconnect 的手感）。只走「从圆点开始新连线」的话，想把 `in0` 断开再接到别处，「断开」静默无效。`mousePressEvent` 里先查 `_edgeItemForPlug( plug )`，有边就走 `__beginReconnect( edgeItem, "dst" )`：拖到空白真断开，拖到别处改接。
- **教训**：前几轮断言的都是 `getInput() is not None`，一直全绿。该断言的是**本编辑器画出来的边**（`collectEdges` / edge item 条数）。凡是「原生有、我们没有」，第一步就和原生对拍数量。回归夹具 `tests/shader_nameswitch_test.gfr`、`tests/shader_nameswitch_test2.gfr`。

### 6.5 `+`（PlugAdder）有三种语义

- **现象**：拖线到刚建、还没 setup 的 Switch / NameSwitch 的 `+` 上，什么都不发生。
- **原因**：`+` 背后有三种行为，只做了两种：
  1. **`setup( endpoint )`**：还没 setup 的 Switch / NameSwitch / Loop / ContextProcessor / EditScope / BoxIn / BoxOut，用丢过来的插口 setup 这个节点再接上（`SwitchUI.cpp:79`、`LoopUI.cpp:83`、`ContextProcessorUI.cpp:71`、`EditScopeUI.cpp:91`、`BoxIONodeGadget.cpp:95`），接完照 `PlugAdder::applyEdgeMetadata` 写 `noduleLayout:section`（丢下去那条边给输入、对边给输出）。
  2. **加一路**：setup 过的 ArrayPlug。
  3. **显示一个藏起来的插口**：材质 / ShaderTweaks（见 6.7）。
- **解决**：三种都实现。Box 照 `BoxUI.cpp` 的 `BoxPlugAdder::createConnection`：建 `BoxIn` 或 `BoxOut` → `setup()` → 接上 → 给提升出来的插口写 `noduleLayout:section`（内部那半写对边）。

### 6.6 `+` 显不显示：两层判据

- **节点级**：原生那些 PlugAdder「setup 过就把自己藏掉」，判据一致：BoxIO `setVisible( !m_boxIO->plug() )`（`BoxIONodeGadget.cpp:135`）、Switch / NameSwitch `in ArrayPlug == nullptr`、Loop / ContextProcessor / EditScope `!inPlug()`。**只有 `Gaffer.Box` 没有这条**，四个 `+` 一直都在。不照这条判就会出现「Switch 出口上还挂着 `+`」。其余看节点级元数据 `noduleLayout:customGadget:<名字>:gadgetType` / `:section` / `:visible`（「有些 Box 上没有 `+`」就是 `:visible = False`）。BoxIn / BoxOut 的 `+` 是 C++ `setEdgeGadget` 挂的，没有元数据，未 setup 时自己补四条边。
- **插口级**：`NameSwitch.in` 上的那个**一直可见**（`NameSwitchUI.cpp` 里没有 `updateVisibility`），所以 setup 过的 NameSwitch 顶上仍有一个 `+`；`Collect.in` 同理。漏掉这层就是「NameSwitch 上的 `+` 不见了」。
- **想问原生某个 `+` 现在可不可见**：PlugAdder 没绑 Python，但装它的 `__noduleContainer`（LinearContainer）的 `bound()` 只算可见子项，「容器长度 − 可见 nodule 占的长度（含 `noduleLayout:spacing`）」就反推出来了。别数 gadget 里的 `ConnectionCreator`，里面混着 BoxIO 那种 setup 后隐藏的边 gadget，数出来偏多。
- **位置**从 nodule 坐标反推：原生把「一排 nodule + 末尾的 adder」整体居中，坐标和为 0（Box 提升一个插口时 nodule 在 -1.5、adder 在 +1.5）。

### 6.7 材质与 ShaderTweaks 的 `+`

- 材质 `parameters` 上的 `+`（1.7 是 `GafferUI.PlugVisibilityGadget`）只在底下**有「能显示成 nodule 但现在藏着」的插口**时出现。实测 aiStandardSurface（66 个参数、56 个显式 `noduleLayout:visible = False`）容器 13.0、10 个 nodule 占 11.8 → 有 `+`；一个 16 参数、零隐藏的 OSLShader 容器 19.0 正好 → 没有。
- ShaderTweaks 的 `+` 照 `ShaderTweaksUI.cpp` 的 `showablePlugs`：看 **value 子插口**是否只读，`mode` 是死值时只有 Replace / Create 算。
- 往 `+` 上丢连线：照原生 `PlugAdder::plugMenuSignal`，一个候选直接接，多个弹面板挑，挑中的「显示出来 + 接上」算一步撤销。

### 6.8 ArrayPlug 的 `+` 要照原生 `resize( s + 1 )`

- **规则**：照 `NameSwitchPlugAdder::createConnection`（`src/GafferUI/NameSwitchUI.cpp`）：`s = children().size(); resize( s + 1 ); connect in[s]`。一律长新的一路，不复用空槽，也不判断 default 空不空。
- **教训**：「NameSwitch 的 `in` 天生 `minSize = 2`，第二路空着，丢 `+` 会把它跳过去」看着像要「有空槽先用空槽」，那会改掉原生语义；真正的问题在 6.4，第二个圆点靠「拖到圆点本身直连」解决。回归夹具 `tests/shader_nameswitch_test2.gfr`：default 和第二路都空着时丢 `+` 该长新路。
- 全新 NameSwitch 第一次丢 `+` 走的是 setup 路径（6.5 第 1 种），和这条规则无关。
- NameSwitch 一路是 `NameValuePlug`，接的是它的 `value`；不是 `NameSwitch.in` 本体时还要把上一路的元数据 `MetadataAlgo.copy` 过来。

### 6.9 拖连线吸附太黏

- **现象**：拖连线在节点范围里一动就「啪」地吸到最后一个接口上。
- **原因**：原生 `StandardNodeGadget::dragMove` → `closestDragDestination` → `updateDragEndPoint`，光标一进节点范围线头就吸到最近那个接得上的接口；ArrayPlug 上「最近的接得上的」是第一个空槽，排在一排圆点最后。
- **解决**：只在**视觉**上加一道吸附距离（`CONNECT_SNAP_DISTANCE = 26px`，靠近才吸、才放大圆点），松手接哪个的判据照原生不动。

### 6.10 拖端点改接

- 照原生 `StandardConnectionGadget`：`endAt` 只有靠近两端才抓得住（灵敏区 `clamp( 线长 / 4, 2.5, 25 )` 单位）；抓目的地那头 = 攥着源插口找新输入，抓源那头反之；落在没人接的地方就断开（原生 `dragEnd`：noone wanted the drop so we'll disconnect）。改接 + 拆旧是一步撤销。
- **现象**：拖起一头时画面上是「手上一根 + 原来那根」两根线。
- **解决**：开始拖时 `edgeItem.setVisible( False )` 并记在手上；接上了下一拍重建自然收掉；接不上（落到接不上的插口 / 节点）`restoreDetached()` 原样放回；只有丢在空白处才是真断开。

### 6.11 把节点塞进连线

- 照原生 `GraphGadget::updateDragReconnectCandidate`：拿**节点中心** ±2 单位那一小块找线（不是鼠标位置），只在拖单个节点时做（原生 `selection().size() != 1` 就返回）。
- 插口配对五条判据：只认有 `correspondingInput` 的输出、两头都 `acceptsInput`、那个输入必须还空着、输出在这张图里不能已接了别人、两个插口都得画着圆点。
- 松手 `in ← 上游` + `下游 ← out`；拖动摆位和塞进线里放进同一个 UndoScope（原生共用 `dragMergeGroup()`），否则是两步撤销。

### 6.12 展开的 RGB 子圆点和原生长得不一样

- **原因**：原生 `CompoundNumericNodule`（`src/GafferUI/CompoundNumericNodule.cpp`）把子接口放进**父接口那一格**的 `NoduleLayout`，整组 `scale( V3f( 0.75 ) )`：子圆点 0.75 单位、间距 0.75 单位（相邻相切）。`GafferUI::CompoundNodule`（Group 的 ArrayPlug、材质 `parameters`）才是摊开成兄弟。
- **解决**：`isExpandedCompoundNumeric()` = 「`nodule:type` 不是 CompoundNodule 且是复合圆点」。半径问原生 `transformedBound()` 要（悬停放大按自己那档翻倍）；分栏侧边是自己排行，用 `_noduleClusters()` 把一簇并成一行。子接口自己没有 `layout:section`，跟父插口进同一栏。
- **坑**：拿「是不是复合圆点」直接当「挤成一簇」的判据，会把材质 66 个参数叠进一格。
- 一簇只写一条标签（父接口名，摆在正中那个圆点旁边），三个名字挤在 9px 里会叠成一团。

### 6.13 圆点标签互相打架

- **现象一**：鼠标停在材质节点侧边的圆点上，卡内那条参数名消失。原因：侧标绘制一律跳过被悬停的那个（怕和放大标签重叠），而分栏节点的标签在卡片**里面**、放大标签弹到卡外，两者不打架。判据改为 `key == hovered and not self.__sectionData`。
- **现象二**：鼠标移到圆点上，放大标签和节点上那条接口名叠成一团。原因：「悬停整个节点 → 显示所有接口名」和「悬停某个圆点 → 放大标签」撞了。抽出 `endLabelPaintKeys()`，鼠标压着的那条让位（一簇子圆点共用一条标签，悬停任一个都算）。

### 6.14 接口标签的三个显示条件

- 以前顶 / 底两排接口压根没标签，借来的 `/Connections/Show Input·Output Labels` 点了没反应。三个条件照原生 `StandardNodeGadget` 一个不少：悬停整个节点（`labelsVisibleOnHover`）、元数据 `nodeGadget:input/outputNoduleLabelsVisible` 常驻、拖连线过来时把接得上的那几个亮出来（原生 `dragEnter`）。

### 6.15 focus 之后谁变暗

- **现象**：自己 BFS 上下游算「focus 链」，高亮位置不对。
- **原因**：原生的行为是**把不参与计算的东西变暗**，参与的一点不变（`ConnectionGadget::updateFromContextTracker` + `StandardNodeGadget::updateFromContextTracker`）；集合只有 `ContextTracker` 算得对：只算上游、而且只算当前 context 真正走到的那条路（Switch / NameSwitch 没选中的那一支不算，改 index 会跟着变）。
- **解决**：用 `ContextTracker.acquireForFocus( script )`，连线看目标插口 `isTracked( dstPlug )`。暗色照 `StandardStyle::colorForState`（`StandardStyle.cpp:1331`）：普通连线 `#999999` → `#4f4f4f`；辅助连线 / 卡片往 0.26 灰 lerp 75%。验证在截图里数暗色像素，只断言 pen 不算数。
- 没设 focus 时一切照原生原色。为了更容易区分，参与的提亮一档、不参与的压得更暗，这一条和原生不同（见第 19 节）。

### 6.16 停用画法

- 原生画的是一条**对角线**（`StandardNodeGadget::renderLayer` 的 Highlighting 层 `b.min → b.max`，Gaffer y 朝上 = 左下到右上，线宽 0.5 单位）。颜色三档：`enabled` 是死值 → 0.1 灰（不参与计算时 0.2 灰）；`enabled` 要算且 ContextTracker 说它关着 → 黄色 `#f0dc28`；要算又没被跟踪 → 什么都不画。

### 6.17 曲线连线照 Houdini 的 rounded

- **现象**：对称三次贝塞尔怎么调控制柄，都出不来 Houdini 那种「横平 + 一个干净大圆角」。
- **原因**：Houdini 的 rounded 连线由**直段 + 正圆弧**组成：出口顺流向走 `min( 0.30 网格单位, 流向距离 / 2 )`，同半径小圆角拐向侧面，横平走一段，再用一个大圆弧拐成流向，直着扎进入口。主圆角半径 `min( 侧向余量, 流向余量, 0.42 * 流向余量 + 常数 )`。拐角圆拟合残差约 0.005 单位（≈1px），确实是正圆弧。目标几乎平齐时画近乎直的横线，不绕回环；真在上游侧才走 5 拐角的回环（阈值 `along < -1px`，`along <= stub` 是想当然）。
- **解决**：`_wirePath` 先在「流向 / 侧向」局部坐标排折线，`_roundedPath()` 把拐角换成正圆弧（`4/3 * tan( φ/4 )` 标准近似，90° 即 0.5523）。进出方向垂直的（filter 那种侧边接口）走单拐点折线。
- **验证**：`tests/houdini_rounded_wire.json` 存了 5 个用例 × 45 个真机采样点（Houdini 21.0.596），测试量「我们的路径离 Houdini 那条线多远」：平均 1.7px、最大 7.1px。量法见 18.14。

### 6.18 方向箭头

- 箭头画在线的中点（Houdini 也是），画在终点会和圆点叠成一坨。中点方向用相邻两点数值求，别用 `angleAtPercent()`：它的角度约定按 y 轴向上，和场景坐标反着。中点要缓存（见 15.6）。选中 / 塞入候选时箭头用线的底色。

### 6.19 连线从两端的节点中间穿过去

- **现象**：节点左右两侧都有连接时，连线有时横穿卡片：filter 接在右侧而 PathFilter 在左边、BoxIn 在右上接左侧参数、节点自己连自己的辅助连线回环。
- **原因**：Houdini rounded 的形状只看两个端点。
- **解决**：只在穿过两端卡片时改走绕行折线 `edge_item._routeAround`：出口顺流向先走一个 `WIRE_STUB`，进口前也留一段直的，中间在「0~2 个拐点」的候选里挑一条不碰两端卡片（外扩 `WIRE_CLEARANCE`）、不走回头路、「长度 + 拐点数」最小的。没穿卡片的连线形状不变（Houdini 对拍数据照旧），Dot 这种接口在卡片里面的不绕，拖线预览走同一套。
- **坑**：「穿没穿」按卡片本身判，绕行时才按外扩后的卡片挑路线。两个判据混用，几乎平齐的 Houdini 横线会被误判成穿过、形状跟着变。
- **量法**：screengrab 里加载一个两侧都有连接的 Box，每条连线沿路径采 400 个点，数落进两端卡片（往里收 2px、端点附近 8px 不算）的有几个：46 条里 10 条 → 0 条。

### 6.20 连线悬停与平移

- 中键平移期间 `setInteractive( False )`，否则画面从鼠标底下滑过，每条连线都亮一下、节点还弹 tooltip。关掉交互后 Qt 不再发 hoverLeave，要自己清一遍已高亮的（`_clearWireHover()`）。
- 连线悬停小框写插口相对名（NameSwitch 每一路都叫 `value`，写名字分不出来）。

### 6.21 连线选中与删除

- 连线不是 Gaffer 对象，进不了 `script.selection()`，自己管一份；选线会清掉节点选择（反之亦然），免得 Delete 时分不清删哪个。点**中段**选中，点两端是改接（6.10）。

---

## 7 选择与拖动

### 7.1 Qt 自带橡皮筋的语义和原生不一样

- Qt 自带橡皮筋只有「相交即选中」+ Ctrl 加选；原生是 Shift 加选、Ctrl 减选。只能 `setDragMode( NoDrag )`，自己拿 `QRubberBand` 画、自己判。
- 原生要求**整个框住**（`GraphGadget::updateDragSelection` → `boxContains`）；本编辑器对节点改成「相交即选」，Backdrop 仍要求整个框住（见 13.7 和第 19 节）。

### 7.2 Shift 多选点完塌回单选

- **原因**：`QGraphicsScene` 在「没有 item 接受这次按下」时 `clearSelection()`；`QGraphicsItem::mouseReleaseEvent` 里有「鼠标没移动又没按 Ctrl 就只留这一个」。
- **解决**：选择按原生规则在按下时就算好；把修饰键抹掉（合成一个 `NoModifier` 的 `QMouseEvent`）再交给基类，拖动照常、选择不被动；再在**按下前后、松手前后各记一次 scene 选择**，对不上就对回去（`_restoreSceneSelection`）。

### 7.3 兜回选择时 node set 的顺序被悄悄换掉

- **现象**：Shift 加选之后，跟着 node set 走的面板先跳到新点的节点，一瞬间又弹回先选的那个。
- **原因**：写回是 diff 式的。Qt 在松手里把选择塌成「只剩点中的那个」时就发了 `selectionChanged`（松手时 `mouseButtons()` 已经是 `NoButton`，按键守卫拦不住），于是先 `remove( A )`；随后兜回来又 `add( A )`，顺序从 `[A, B]` 变成 `[B, A]`。原生 NodeEditor 和所有 NodeSetEditor 子类都只显示 `_lastAddedNode()`。
- **解决**：基类事件 + 兜回来这一整段挂起写回（`_setSelectionSyncSuspended`），只动 scene，结束后统一 flush。
- **教训**：回归测试要断言**顺序**（`[ n.getName() for n in selection ]`），`sorted()` 或 `len() == 2` 抓不到。

### 7.4 拖动吸附（Snap）

- **现象**：老算法对全图分别取 x 最近和 y 最近，两个轴可能来自两个不同节点，而且完全不看距离，视野外的节点能把手上的节点拽走，两轴同吸还会盖到参照节点头上。
- **解决**（Houdini 的做法）：以节点即将去到的位置为圆心，`SNAP_RANGE = 360px` 内才有资格当参照；在「某个轴差在 `SNAP_DISTANCE = 8px` 内」的候选里取最近那个；只吸差得少的那一个轴；参考线只画在两个节点之间（两头各伸出一点）。节点已在同一行时吸的是 y（锁住这一行），x 保持自由。
- **只在单个节点拖动时生效**：多选时每个 item 各收一次 `ItemPositionChange`，各吸各的会把一组的相对位置搅乱。程序改位置时不吸（看视图是否处于拖动模式）。
- 吸附在 `_NodeItem.itemChange( ItemPositionChange )` 里修正位置，所以会一路进到写回 Gaffer 的值里。
- 工具条 Snap 按钮的初始按下状态要跟字段走，否则「默认开着但按钮弹起」，要点两下才关得掉。
- **验证坑**：参考线是 1px 虚线 + 抗锯齿，抓图像素是混过的（纯色红−蓝 = 150，实测最黄只有 95），按精确颜色 ±14 去数一定是 0。要按「偏黄（红−蓝 > 40）」判，而且只在参考线那几列 x 上取样（图里别处有黄色灯光卡片）。

### 7.5 手势不互斥

- **现象**：中键平移中按左键会变成框选，`__endPan` 永远跑不到，`setInteractive( False )` 卡死；拖连线时按中键把临时线留在 scene。
- **解决**：记下发起手势的那个键（`__gestureButton`），手势进行中第二个键的按下 / 松开一律不理。

### 7.6 往外拖：中键把节点拖给别的编辑器

- 原生 `GraphGadget::dragBegin` 里**中键**按在节点上是 `m_dragMode = Sending`（拖的是 `script.selection()`，不在选择里就是那一个节点），左键才是移动。照这个分法，中键按空白处平移不受影响。
- GafferUI 的拖放靠一个**全局唯一**的事件过滤器驱动，它只装在 Editor 的顶层 QWidget 上，事件都被 `QGraphicsView` 这个子控件吃了，要自己往视图和它的 viewport 上再装一遍。
- 起拖不能走 `buttonPressSignal`：返回 True 会把 Qt 事件吃掉，自己的点选 / 拖动全废。只补它需要的两个私有属性（`__lastButtonPressWidget` / `__lastButtonPressEvent`）。

### 7.7 往里拖：从 Viewer / HierarchyView / SetEditor 拖东西进来

- **现象**：拖过来一点反应都没有。
- **原因**：GafferUI 的拖放不走 Qt 的 `QDrag`，它在 `Widget.py` 的 `_EventFilter` 里按鼠标位置找目标控件，发 `dragEnterSignal` / `dragMoveSignal` / `dragLeaveSignal` / `dropSignal`，不接这四个信号就没有反应。
- 三个连带的坑：①`GafferUI.Pointer.getCurrent()` 平时就是 `None`（标准指针），别拿它非空当「拖拽进行中」，否则整套哑掉；②`dragEnter` 只在目标控件变化时发一次，要收得宽，落在哪个节点上在 dragMove 里自己算；③`event.line` 是相对目标控件的像素，要自己换算成场景坐标。
- 落在节点上的优先**转发给原生 NodeGadget 的信号**（那些 gadget 早被 `NodeGadget.instanceCreatedSignal` 挂上了 `PathFilterUI` / `SetFilterUI` 的处理器，pipeline 自己注册的 drop 目标也一起有了）。单条路径落在空白处的语义是「跳到生成这个位置的节点」（换层 + 取景 + 选中）。
- 文件拖放转发给原生去建读取节点（扩展名 → 节点类型那张表在 `startup/gui/graphEditor.py` 的私有 dict 里），本编辑器只负责摆到落点；建节点和摆位放进一个 UndoScope，否则第一次 Ctrl+Z 把节点挪回原生按像素算错的位置。

### 7.8 拖到视口边缘画面自己滚

- 照原生 `ViewportGadget::trackDrag`（GraphEditor 两个轴都开）：不滚区 = 视口往里缩 `min( min(w,h)/8, 60 )` 一圈，速度从 0 线性升到边上最大，出了视口不再更快，门槛取历史最小值（在边缘区里起拖、往中间拖时不会一上手就滚）。定时器滚一步之后要补一次鼠标移动，不然手上拖的东西不知道画面动了。
- **坑**：方向向量要用真实长度归一，夹住的那个只拿来算速度系数。拿夹过的长度去归一，光标拖到视口外老远时方向被放大好几倍（实测速度 460，上限 60）。断言写「拖到视口外速度封顶」，比「能滚」有用。

### 7.9 无头下 QGraphicsScene 偶尔不建立鼠标抓取

- offscreen QPA 下按下之后 `mouseGrabberItem()` 有时是 None（`isInteractive()` 正常、item 也在场景里），后面的 move 谁也收不到，合成事件测拖动随机失败。无头那边只验「进没进拖动模式 + 松手写没写回 Gaffer」，真拖动交给真鼠标 e2e。

### 7.10 X 删除模式

- **手感**：按住 `X` 进入模式，点连线断线、点节点删节点（`reconnect=True`，上下游自动接起来），按住左键划一笔切多根；松开 `X` 退出，`Esc` 取消。按下松开差 ≤ 4px 算「点」。
- **按住式交互**：X11 按住约 0.5 秒后一直发 press / release 对，`keyPressEvent` **和** `keyReleaseEvent` 开头都要 `if event.isAutoRepeat() : return`（Gaffer 自己的 `Widget.__keyRelease` 也这么写）。只挡 press 那边时划线一直闪，看起来像「按住式交互做不成」；两边都挡就稳了。只有真键盘长按测得出来（xdotool `keydown` → 停 1.5 秒 → `keyup`），合成的 `QKeyEvent` 里没有自动重复。
- 中键平移会把划线状态冲掉（提示常驻、虚线留在场景里）：平移期间挂起，松开中键回来（期间松开 X 就退出）。
- 快速双击会打开 NodeEditor：双击事件也走按下判定链。
- 图一重建就退出划线模式：重建只作废没划完的那一笔。
- 切掉一根线后提示被状态栏计数冲掉：提示记成状态，计数刷新后重新写回提示。

---

## 8 平移与缩放

### 8.1 中键拖到内容边缘拖不出去

- **原因**：QGraphicsView 把可视区夹在 sceneRect 里。
- **解决**：sceneRect 每边留 `SCENE_MARGIN = 20000px`。

### 8.2 中键拖了没反应

- **原因**：`AnchorUnderMouse` 会在任何变换改变时重新锚定，把 `translate()` 原样抵消。
- **解决**：平移时临时切 `NoAnchor`。

### 8.3 一拖布局分隔条，图就弹回中心

- **原因**：Qt 内部拿 `lastCenterPoint` 当 resize 锚点，它只在 `centerOn()` / `scrollContentsBy()` 里更新，`NoAnchor` + `translate()` 的平移不更新它。尺寸一变（拖分隔条、换 tab、面板重新 parent），`resizeEvent` 按 `resizeAnchor` 去 `centerOn( 陈旧的点 )`。
- **解决**：自己记视野中心 `__viewCentre`（平移 / 缩放 / 取景 / `scrollContentsBy` 之后都记），在 `resizeEvent` 和 `showEvent` 里 `centerOn` 回去；基类 `resizeEvent` 自己那次复位用 `__restoringCentre` 标志挡掉，别记成一次平移。
- **别做**：「每次平移都 `centerOn` 一下」来顺手刷新 Qt 的锚点。`centerOn` 会把滚动条值取整，连续小步平移每步漂 1px（实测 200 步漂 200px）。

### 8.4 中键拖到一半再滚滚轮，画面横着甩

- **原因**：`AnchorUnderMouse` 锚的是 `lastMouseMoveScenePoint`，只在 `QGraphicsView.mouseMoveEvent` 走到基类时更新。自己接管了鼠标移动（平移、框选、拖线）之后它就过期了，任何 `scale()` 都拿这个过期点当锚把画面甩出去，拖得越远跳得越狠。
- **解决**：缩放一律自己锚：记下光标底下的场景点 → 缩放 → 把画面挪回去。`fitInView` 之后夹缩放上限那一下围着画面中心缩。横向滚轮（`angleDelta().y() == 0`）别当成「往下滚」。

### 8.5 缩放上限

- 原生 GraphEditor 是 `setMaxPlanarZoom( V2f( 25 ) )` = 每单位最多 25 像素 → `MAX_ZOOM = 25 / PX_PER_UNIT`。另设一个很松的下限，`fitInView` 之后也夹一次。

### 8.6 Alt + 右键拖缩放

- 原生 `ViewportGadget.cpp` 的 `cameraMotionType`：Alt + 右键 = Dolly（Alt + 左键原生是 Tumble，2D 视图里等于把相机转歪，本编辑器改成平移）。planar 模式下 `dolly()`：`dv = ( p - motionStart ) / 视口分辨率`、`d = dv.x - dv.y`、`planarScale *= exp( -1.9 * d )`。`planarScale` 是「一像素几个单位」，`QGraphicsView` 的 scale 反过来，所以 `zoom = 起始 zoom * exp( 1.9 * d )`。锚点是**按下那一刻**光标底下的点。
- **坑一**：X11 上右键一按下 Qt 就发 `ContextMenuEvent`，不在 `contextMenuEvent` 里按「当前是缩放手势 / 按着 Alt」挡掉，手势就变成「点一下弹菜单」。
- **坑二**：窗口管理器常把 Alt + 右键绑成「拖着改窗口大小」，合成 `QMouseEvent` 永远测不到被抢。真输入写法：`xdotool keydown alt` → `mousedown 3` → `mousemove` × N → `mouseup 3` → `keyup alt`。

### 8.7 方向键让画面上下挪

- **现象**：不在 Box 里按上下键，画面上下移动。
- **原因**：方向键 / PageUp·Down / Home·End 是 `QAbstractScrollArea` 的滚动键。进不去 / 出不来层级时事件落到基类手里。原生是 GL 视图，没有滚动条。
- **解决**：自己处理完之后把这几个键吞掉（`_GraphView.__scrollKeys`），不交给基类。

### 8.8 平移没有位图滚动可捡

- 试过把平移从 `translate()` 改成动滚动条，期望 Qt 位图滚动、只画新露出的条带。真 X11（xcb）和 offscreen 上 `translate()` / 动滚动条 / `repaint()` 三条路的 paint 次数完全一样。

---

## 9 快捷键与右键菜单

### 9.1 菜单栏 QAction 抢键

- **现象**：`Ctrl+C` / `Delete` / `F2` 在本编辑器里不生效，或作用到错误的层。
- **原因**：菜单栏的 QAction 在 `ShortcutOverride` 阶段就把键抢走了，`keyPressEvent` 收不到。而菜单栏那套走 `EditMenu.scope()`，钻进 Box 时会拿错 parent。
- **解决**：覆盖 `event()`，在 `ShortcutOverride` 时对自己认领的组合 `accept()`。`Ctrl+Z` / `Ctrl+Shift+Z` 别抢，交给全局菜单。

### 9.2 收不到 Tab

- Qt 默认拿 `Tab` 做焦点切换，要覆盖 `focusNextPrevChild()` 返回 False。

### 9.3 弹出的菜单一闪而过

- 菜单对象是局部变量，出作用域被 GC。存到实例属性上（原生 `GraphEditor.__buttonPress` 也是存 `self.__m`）。

### 9.4 借原生的三套右键菜单

- 节点 / 插口 / 连线三套菜单直接借：`GraphEditor.nodeContextMenuSignal()( host, node, definition )` 等，填出来的定义喂 `GafferUI.Menu`。Edit… / Enabled / Connections / Focus / Set Color / Annotate / 书签 / 各插件挂的条目、提升 / 取消提升 / 插入 Dot / 插口挪边，一次全有。
- 这些命令要 `menu.ancestor( GafferUI.GraphEditor )` 当宿主（见第 10 节）；`DotUI.__insertDot( menu, plug )` 还要拿 `menu.popupPosition()` 反算新节点位置，所以弹出去之后把 `_Menu__popupPosition` 改写成「换算回来正好是鼠标那一点」的值，再用 `__finishNodeCreation` 兜住算坏的位置。
- 右键菜单信号是「类级 + 实例级」两份，弹菜单时两份都发（`GraphEditor.py:470-490`）。
- 1.6.5.1 的三个信号访问器是只吃 cls 的 classmethod，传 `True` 要多选那一路直接 TypeError。1.7 的变化见 17.2。
- 菜单标题（多选、插口、连线）照 `GraphEditor.py:470-492` 的写法。

### 9.5 借来的 `Show Contents...` 会现建一个原生 GraphEditor

- **现象**：布局里只放 NetworkEditor，右键 Box → `Show Contents...`，原生节点图面板自己冒了出来（布局里原生 GraphEditor 数 0 → 1）。
- **原因**：原生命令是 `GraphEditor.acquire( node )`（1.7 是 `functools.partial( GraphEditor.__acquireNodes, nodeList )`），layout 里没有原生 GraphEditor 时它会 `addEditor()` 一个。
- **解决**：借完菜单后按**菜单路径**把这条就地换成本编辑器的进层（`__redirectShowContents`），用 `insertBefore` 保位（`append` 同名会挪到末尾）。只给原生本来就给了这一条的节点（标了 `ui:childNodesAreViewable` 的），只有子节点、没标可看的不加。

### 9.6 pipeline 注册的快捷键

- pipeline 往往把自己的快捷键（例如 S / Q 弹的菜单、跳工作区、按名字搜节点）挂在 `GraphEditor.instanceCreatedSignal` 上，连到原生编辑器的 `keyPressSignal`。
- 早期做法：自己没接住的键原样转发给隐藏引擎：
  ```python
  event = GafferUI.KeyEvent( GafferUI.Widget._key( qEvent.key() ), GafferUI.Widget._modifiers( qEvent.modifiers() ) )
  handled = engine.keyPressSignal()( engine, event )
  ```
  转发完看一眼引擎的 root 有没有被切走（跳工作区那类），跟着切过去。
- 现行做法（第 10 节）：接管装着时主动 `GafferUI.GraphEditor.instanceCreatedSignal()( self )`，那些 handler 直接连到本编辑器的 `keyPressSignal`（`__announceInstance()`）；`_forwardShortcutKey` 先发给自己，没人要且确实有引擎时才退回引擎。
- **坑**：快捷键 handler 调 `graphGadget().setRoot()` 换层。`graphGadget()` 给引擎的或借来的原生 gadget 时，本编辑器的视图不动（还可能把另一个原生面板换走）。`graphGadget()` 一律给自己的裸 gadget，并连 `rootChangedSignal` 跟着换层；`frame()` 认节点身份、按卡片取景。

### 9.7 快捷键弹的菜单改用自己的面板画

- 那些处理器都是「造一个 `GafferUI.Menu` 再 `popup()`」。转发按键期间临时把 `GafferUI.Menu.popup` 换掉，截下菜单，用自己的面板画（`_showMenuAsPanel`），用完换回去：
  ```python
  originalPopup = GafferUI.Menu.popup
  captured = []
  GafferUI.Menu.popup = lambda menu, *a, **kw : captured.append( ( menu, a, kw ) )
  try :
      handled = target.keyPressSignal()( target, event )
  finally :
      GafferUI.Menu.popup = originalPopup
  ```
- 定义挂在 Qt 对象上：`menu._qtWidget()._Menu__definition`，标题 `menu._Menu__title`；定义可能是 callable。
- 必须递归钻 `subMenu`：这类菜单顶层常常全是子菜单，不递归一条都拿不到。

### 9.8 菜单条目要照原生 `Menu` 的规矩求值和调用

- **参数名**照 `Menu.__argNames`（`Menu.py:156-168`）：函数、绑定方法、`Gaffer.WeakMethod`、`functools.partial` 都看穿。看不穿 WeakMethod 的话，要 `menu` 的命令被裸调 → TypeError。
- **`active` / `checkBox` / 动态 `subMenu`** 照 `Menu.__evaluateItemValue`（`Menu.py:489-497`），要 `menu` 就带上。建面板时求一次，画出来的 ✓ 和点下去传的勾选状态是同一个值；灰掉的子菜单里的条目照样列出、一律点不动（原生 `subMenu.setEnabled( active )`）；点下去那一刻再问一次 `active`（原生 `__actionTriggered` 也是）。
- **勾选型条目要把勾选状态传给命令**：原生 `Menu.__actionTriggered`（`Menu.py:194-209`）把「点完之后」的状态塞进命令的**第一个位置参数**（命令自己声明了 `checkBox` 参数时走关键字）。pipeline 里常见 `command( state, ... )` 这种签名。面板照 `command()` 裸调 → TypeError。传 `not 当前值`；面板上勾着的条目在名字左边留白里画 `✓`。
- 命令要 `menu` 时，截下来的菜单没真弹过，`Menu.popup()` 本该记下的 `_Menu__popupParent`（**弱引用**）/ `_Menu__popupPosition` 要自己补上。

### 9.9 自己写的退路把「契约不一致」伪装成「功能退化」

- **现象**：点面板里的条目，弹出一个原生的可搜索菜单，看着像「点一下又弹出原生 Tab 栏」。
- **原因**：勾选状态没传（9.8），命令抛 TypeError，落进「命令跑不通就退回原生弹法」的退路；那些菜单是 `searchable=True` 的，弹出来和原生 Tab 菜单一模一样。
- **解决**：去掉退回原生菜单 / 原生 Tab 菜单的所有退路，命令抛异常就照原生那样报出来。
- **教训**：排查「点一下就回到原生」先看退路上吞了什么异常。去掉退路之后还浮出了测试里的假象（用 Python 假对象当 `DragDropEvent` 过不了 Boost 参数检查，以前被吞掉了），改成真的 `GafferUI.DragDropEvent`。

### 9.10 双击与双击信号

- 原生双击节点是开浮动 NodeEditor（`startup/gui/graphEditor.py` 的 `__nodeDoubleClick`），进入是 `↓`，出来是 `↑`。
- `nodeDoubleClickSignal` 要发出来，startup 连的就是「开浮动 NodeEditor」，第三方也可能往上挂东西。接管装着时第一个参数传本编辑器。

### 9.11 `↓` 进得去哪些节点

- 1.7 的正式键是 `ui:childNodesAreViewable`，`graphEditor:childrenViewable` / `nodeGraph:childrenViewable` 是 legacy。照原生 `GraphEditor.py:895-908` 依次查三个键。Gaffer 自带的 Box 三个都写，所以自带节点看不出问题，只写新键的第三方节点才会「按 ↓ 进不去」。

### 9.12 P 键浮动参数面板

- `P` 在节点图视口右上角停靠一块纯参数面板。面板来自可选包 `parameterEditor`（`parameterEditor.popupParameters()`）。
- **import 时机**：扩展的 startup 是按顺序逐个加路径、逐个跑的，本包 startup 运行时 `parameterEditor` 可能还不在 `sys.path` 上，所以 `import parameterEditor` 写在按键处理里。
- **窗口类型**：不能用 `Qt.Popup`，参数控件要弹预设菜单、拾色器、文件浏览器（都是独立窗口），Popup 一见别的窗口激活就自己关。用无边框 `Qt.Tool`，关闭自己管（再按 P / Esc / 节点被删）。调用方要留住返回的窗口引用，否则被 GC 一闪而过。
- **节点认定**：光标底下 → focus（且在本层）→ 最后选中，并把它设为当前选中（不然光标底下是 A、选中的是 B，弹出来是 B 的参数）；已经选上就不动，不把多选压成单选。
- **圆角**：QSS 的 `border-radius` 只管自己那层，四个角会被子控件填成直角，要再加窗口遮罩（`QPainterPath.addRoundedRect` → `QPolygon` → `QRegion` → `setMask`）；尺寸变了要重切遮罩。
- **边框改大小**：窗口留一圈只属于自己的边距（子控件盖不住才收得到鼠标事件），拖左边时固定右边缘（面板停在右上角）。
- **无头坑**：offscreen QPA 不支持窗口遮罩（`setMask` 的值 Qt 侧还记着，断言能过，「角真被切」只能真机数像素）；offscreen 虚拟屏只有 800x800，位置断言别写死「右边缘 == 视口右边缘」，拿纯函数算期望值比。

### 9.13 空格最大化的检测

- Gaffer 的空格不是真全屏：`CompoundEditor.__keyPress`（`CompoundEditor.py:381`）把光标所在面板的所有祖先 `SplitContainer` 手柄推到两端，判据「每一层 `handlePosition == 1 - 自己在父级里的序号`」。照抄成 `isPanelMaximised()`；一个 split 祖先都没有时返回 False（原生那段 `all( [] )` 是 True）。真窗口全屏另问 `isWindowFullScreen()`。

### 9.14 界面语言

- 显示文字一律英文，菜单措辞照抄原生（`/Focus`、`/Enabled`、`/Bookmarked`、`/Connections/Show Input Connections`、`/Show Contents...` 等），借来的菜单和自己拼的菜单才是同一套叫法。悬停小框是中文帮助。
- 中文辅助说明放在 tooltip 里，界面上不出现双语文字。
- **例外：Tab 建节点面板一个 tooltip 都不挂**。那面板是扫着找、找到就回车的用法，划过一行冒一个提示、消失还慢，盖住下面几行；面板常弹在光标底下，搜索框的提示也会挡住。测试里有反向断言：每行 `toolTip()` 必须为空。
- 英文要管单复数（`%d item%s`）。

---

## 10 接管 GraphEditor 与隐藏引擎

### 10.1 官方代码写死了 `GafferUI.GraphEditor`

- **现象**：菜单栏剪切 / 复制 / 粘贴作用在错的层、书签跳转、Ctrl+F、`Show Contents...` 都找不到本编辑器。
- **原因**：`EditMenu.scope()`、`GraphBookmarksUI`、`NodeFinderDialogue`、`BoxUI` 都在找 `GafferUI.GraphEditor`。
- **解决**：把 `GafferUI.GraphEditor` 换成一个元类实现的壳：
  | | 接管后 |
  | --- | --- |
  | `isinstance( x, GafferUI.GraphEditor )` | 对本编辑器和原生都为真（元类 `__instancecheck__`） |
  | 类属性（`plugContextMenuSignal` 等） | 一律转给原生类：startup 里的 `connect()` 早挂在原生类上，必须是同一个信号对象 |
  | `GafferUI.GraphEditor( script )` | 仍然构造原生的：存过的 layout 里写死的就是这句，换掉会让旧布局悄悄变样 |
  | `acquire( node )` | 优先用 layout 里现成的 NetworkEditor 进那一层 |
- 配套在本编辑器上补 `graphGadget()` / `graphGadgetWidget()` / `frame( nodes, extend )`，不补整条 Edit 菜单直接报错。`GAFFER_NETWORK_EDITOR_TAKEOVER=native` 可关掉接管。
- **找引擎时要显式找原生类**（`_nativeGraphEditorClass()`），否则接管后自己借给自己。

### 10.2 隐藏引擎的视口退化，摆位算出 nan

- **现象**：在本编辑器里建节点，节点飞到画面外找不着。
- **原因**：原生摆位拿弹出菜单的 raster 坐标反算图坐标（`popupPosition( relativeTo = gadgetWidget )` → `rasterToGadgetSpace`），隐藏引擎从没显示过，视口是退化的。`ViewportGadget` 默认视口 `V2i( 640, 480 )`，不 `setViewport` 就按它算，退化到 0 时出 nan。
- **解决**：建完统一过 `__finishNodeCreation`：位置不是有限值（`positionUsable`）的、以及没连上任何东西的，一律摆到鼠标那儿。有选中节点时建的 Backdrop 例外，它已经 `nodeGadget.frame()` 把那些节点框住了。

### 10.3 借来的真 GraphEditor 视野被拽走

- 原生 `nodeCreatorWrapper` 最后一句是 `graphEditor.frame( [ node ], extend = True )`。宿主要是借的 layout 里那个真 GraphEditor，那边的视野就被拽走。跑之前把 `engine.frame` 临时换成空函数（实例属性，用完 `__dict__.pop`）。

### 10.4 原生要 editor 的 API 面

- 照源码列全，一共 5 个方法 + 1 个 widget 契约：
  | 命令 | 出处 | 用到 editor 的什么 |
  | --- | --- | --- |
  | `NodeMenu.nodeCreatorWrapper` | `NodeMenu.py:98-150` | `graphGadgetWidget()`、`graphGadget()`（`getRoot` / `getLayout().connectNode` / `positionNode`）、`scriptNode()`、`frame()`；`menu.popupPosition( relativeTo = gadgetWidget )`、`getViewportGadget().rasterToGadgetSpace()` |
  | `DotUI.__insertDot` | `DotUI.py:136` | 同上前四样 |
  | `BoxUI.nodeMenuCreateCommand` | `BoxUI.py:115` | `scriptNode()`、`graphGadget()` |
  | `BackdropUI.nodeMenuCreateCommand` | `BackdropUI.py:50` | 同上 + `graphGadgetWidget()` |
  | `ReferenceUI.nodeMenuCreateCommand` | `ReferenceUI.py:79` | `graphGadget()` + `ancestor( GafferUI.Window )` |

### 10.5 不建原生 GraphEditor 也能当宿主

- **宿主**：`Widget.ancestor( type )` 沿 `parent()` 链做 `isinstance`（`Widget.py:415-423`），接管的元类让本编辑器通过。把菜单的 `_Menu__popupParent` 设成 `weakref.ref( self )`（`Menu.parent()` 解的是弱引用，`Menu.py:131-138`），`menu.ancestor( GafferUI.GraphEditor )` 就返回本编辑器。
- **`graphGadgetWidget()` 的壳**（`_GadgetWidgetShim`）：只实现 `getViewportGadget()` / `bound()` / `size()` / `_qtWidget()`。故意不做成 `GafferUI.Widget`，`Widget.__init__` 会登记全局 owner 表、设 `WA_StyledBackground`。
- **只算不画的取景器**（`_syncedViewport()`）：独立 `GafferUI.ViewportGadget( graphGadget )`，每次用之前 `setViewport( 视口像素 )` + `frame( 可见 scene 矩形换成 Gaffer 单位, y 翻转 )`。往返误差 0.013~0.022 单位（≈0.25px，raster 取整造成），视口正中完全一致。不需要窗口也不需要 GL，永远不 render 它。
- ViewportGadget 四条性质（1.7.1.0 复核）：①默认 2D（`getPlanarMovement() == True`）、默认视口 640x480；②`frame( box )` 把整个框装进去，宽高比不同往长边扩，喂 `mapToScene( viewport.rect() )` 得来的框天生同宽高比；③`setViewport()` 不会自动重新取景，缩放 / 平移 / resize 后都要重新同步，或者「用之前同步一次」；④raster y 向下、gadget y 向上，`rasterToGadgetSpace` 返回 `LineSegment3f`，取 `.p0`。
- **一个 gadget 只有一个父**：挂给第二个 ViewportGadget 会把它从原来的 viewport 上抢走（`getPrimaryChild()` 变 None），绝不挂借来的真 GraphEditor 的 gadget。`rasterToGadgetSpace( gadget = X )` 对不在树里的 X 给同样答案（顶层变换是单位矩阵），所以不必和原生共用 gadget。
- **壳的 `bound()` 和取景器要按整个编辑器那块算**（含工具条）：原生 `EditMenu.paste` / 导入拿 `graphEditor.bound()` 算 raster，按视口算的话落点差一个工具条高度。

### 10.6 宿主换成自己之后三套原生菜单全空

- **原因**：第一版直接调 `host.nodeContextMenuSignal()`，而本编辑器（当时）没有这类实例方法 → AttributeError 被 try 吞掉。
- **解决**：`__hostSignal()` 拿不到实例级信号时返回 None，只发类级那份。1.7 起本编辑器自己补齐了实例级信号（见 17.1）。

### 10.7 诊断「原生要过但我们没有」的 API

- `NetworkEditor.__getattr__` 记一条 Debug 日志再照常抛 `AttributeError`。日志级别调到 Debug，拿生产图把菜单点一遍，缺什么一目了然。

### 10.8 量「还依赖不依赖引擎」的方法

- 直接 `GAFFER_NETWORK_EDITOR_ENGINE=0` 跑测试，挂的那 14 条全在「接管还没装」的那些节里（宿主退回引擎、引擎又被关了）。要先 `installGraphEditorTakeover( force = True )` 再 `exec` 测试文件，这样量出来只剩 3 条，而且全是接管那一节自己的前置断言。
- 结论：`engineEnabled()` 改成「接管装着就不建」（`=1` 强制建、`=0` 强制不建）。引擎代码留着当接管关掉时的退路。最终决定性验证：把引擎整个关掉，再按 pipeline 的快捷键，照样接住、照样弹本编辑器自己的面板。

---

## 11 建节点面板 Tab

### 11.1 创建函数被 `nodeCreatorWrapper` 的 assert 挡住

- **现象**：面板里点条目报 `AssertionError`。
- **原因**：`NodeMenu.nodeCreatorWrapper` 写死了 `assert menu.ancestor( GafferUI.GraphEditor ) is not None`，面板不是菜单。
- **解决**：从闭包里取原生创建函数：`command.__code__.co_freevars` + `command.__closure__` → `nodeCreator` / `plugValues` / `postCreator`，自己在 UndoScope 里跑，再走原生 `connectNode` / `positionNode`（`_unwrapNodeCreator`）。真机 NodeMenu 543 条里 530 条拆得出来。

### 11.2 拆不出创建函数的条目不能退回原生菜单

- **现象**：在面板里打完 "box" 回车，眼前又冒出原生搜索框要重打一遍。
- **原因**：`Box` / `Backdrop` / `Reference` / 图像滤波那几个是 `nodeMenuCreateCommand( menu )`，创建函数自己要 `menu`。`Backdrop` 更特殊，是 `nodeMenu.definition().append( path, { "command" : ... } )` 直接挂的裸函数，没有 `nodeCreatorWrapper` 那层闭包，`_isNodeCreatorCommand()` 认不出它。
- **解决**：判据统一按「命令要不要 `menu` 参数」。要的就现造一个没弹出来的 `GafferUI.Menu( IECore.MenuDefinition() )`，补上 `_Menu__popupParent`（弱引用到宿主）和 `_Menu__popupPosition`，调完还原（`__createWithCommand`）。`Reference` 还要 `ancestor( Window )` 当文件浏览器父窗口，给不了是 None，照样能弹。
- **摆位别包 UndoScope**（原生也写在 scope 外面），否则建一个节点要按两次 Ctrl+Z。

### 11.3 NodeMenu 是非模态的

- 弹出后立刻查「新建了什么」查不到。连 `visibilityChangedSignal`，菜单关掉再 idle 一拍才收尾。

### 11.4 一个大框装所有列，高度两头不讨好

- **现象**：跟着最长那列变就「展开一级长高一次」，定死就「第一列条目少时下面一片留白」。
- **解决**：照原生 QMenu，**一列一个窗口**。根窗口 = 标题 + 搜索框 + 第一列，高度只看第一列条目数；第二列往后各自一个窗口，各自按自己的条目数定高（超过 `MAX_VISIBLE_ROWS` 才出滚动条）。右边放不下就翻到左边。

### 11.5 子列窗口必须是嵌套 `Qt.Popup`

- `Qt.Tool` / `Qt.ToolTip` 会被 Qt 当成「点在 popup 外面」，第一下点击就把整个面板关了；嵌套 popup 被认成「点在另一个 popup 上」。
- **代价**：鼠标事件只发给最上面那个 popup。鼠标退回左边那些列时，事件以窗口外的坐标落在最上面的窗口上，面板要自己按全局坐标派发（`_routeMouse`，QMenu 内部也是这么转发的）。三个连着的坑：
  1. 窗口上不 `setMouseTracking( True )` 就收不到「没按键的移动」，表现是点得动、划回去没反应。只有真鼠标测得出来，无头直接调派发函数是绿的。
  2. 「点在所有列外面就关掉」要把自己窗口的边距 / 标题 / 搜索框排除掉，否则点自己的边框就关了面板。
  3. 右键要自己从 `_routeMouse` 把 button 带进来，Qt 的 `contextMenuEvent` 到不了各列。
- **滚动条**：嵌套 popup 下第一列自己的滚动条也收不到原生 press / move，拖不动。`_routeMouse` 里加 `__scrollBarAt` + `__forwardToScrollBar`（按滚动条本地坐标现造 `QMouseEvent`，`QApplication.sendEvent` 直发）+ 一个拖动状态机。
- **滚轮**：Qt 只发给光标底下那个控件，压在搜索框 / 标题 / 边距上时到不了列表。面板和每个子列窗口各挂 `wheelEvent`，统一派发（`_routeWheel()`）：压着哪列滚哪列 → 没压着列表就滚光标所在窗口的列 → 再不行滚第一列。触摸板的小步滚轮攒够一行再滚。只有真滚轮测得出来（xdotool `click 4` / `click 5`）。

### 11.6 进下一级，上一级不许动

- `QHBoxLayout` 默认把每个控件拉到行高，右边开出一列长的会把左边已摊开的列一起拉高：每列 `setFixedSize( 列宽, 自己的行数 × 行高 )` + `AlignTop`。
- 标题里别写当前层级：从根层往里走一级，标题从无到有，整块面板连第一列一起往下挪一行。
- 已经摆好的子列窗口别重复 `move()`：窗口 map 之前 `move()` 给的是外框位置、map 之后是内容位置，来回 move 每次漂 2px。位置没实质变化就不动它。
- 子列对着「展开它的那一行」开（`__addColumn( path, anchorRow )`，顶端差值 = 行数 × 行高），不要一律对着第一列顶上。
- 验收：逐像素比 `column.geometry()` 前后必须完全相同，面板必须真的 `popupAt()` 弹出来再量（没 `show()` 的面板布局不生效）。

### 11.7 多显示器下面板被拽回主屏

- **现象**：鼠标在副屏按 Tab，面板出现在主屏。
- **原因**：「别让弹窗跑出屏幕」那段写的是 `QtGui.QGuiApplication.screenAt( pos )`（3.19），每次 AttributeError 被 `except` 吞掉，退回主屏按主屏可用区夹坐标。
- **解决**：`QtWidgets.QApplication.screenAt()`，再兜一层遍历 `screens()` 找 `geometry().contains()`；问不出是哪块屏就不夹。双屏实测 Qt 自己跨屏移动 popup 没问题，不用去折腾窗口管理器。

### 11.8 多窗口下面板总贴着同一个窗口

- **原因**：`Qt.Popup` 的原生窗口在**创建那一刻**认下 transient parent。面板缓存在编辑器上，Gaffer 换布局是把编辑器控件整个 reparent 到另一个窗口，控件对象没变，比 `parentWidget()` 看不出来。
- **解决**：每次弹之前比 `view.window()`，变了就 `setParent( window, Qt.Popup )` 重挂（重建原生窗口）。

### 11.9 悬停高亮留残留

- **现象**：第一列划过之后某一行留一道洗不掉的浅蓝；划进第二级菜单，第一行总是亮着。
- **原因**：delegate 里画了 Qt 的 `State_MouseOver`。一列一个窗口之后，非最上层那些列收不到真鼠标事件，Qt 的 hover 状态停在最后划过的那一行上清不掉。新开的列预选了第一行。
- **解决**：高亮只认「当前行」：`itemEntered`（以及派发过来的移动）里把那一行设成该列当前行，更左边的列高亮留在原地，正好显示「现在展开的是哪一条」。新开的列 `setCurrentRow( -1 )`，只有搜过时才预选第一条（回车直接建最匹配的）。
- **验收**：数像素，每一列亮着的行必须恰好等于 `[ currentRow ]`（灰底 r=g=b，高亮偏蓝，`blue > red + 8` 就分得开）。

### 11.10 一行里名字和右边的层级信息叠在一起

- **现象**：层级很深的条目（`B` 找书签右边就是节点在图里的整条路径），左边名字和右边路径互相遮挡。
- **原因**：所有面板共用同一个 `_CreatorDelegate`，`paint` 里两块文字共用同一个矩形各画各的：名字左对齐完全不截、右侧只按 55% 截，谁长压谁；分节标题那两块连 55% 都没截。Tab / B / 菜单转面板 / 拖线选隐藏参数四个入口全中。
- **解决**：纯函数 `_splitRowWidths( available, nameWidth, rightWidth )` 先分宽度再各自截（`_paintTexts()`）：名字 `ElideRight`，路径 `ElideLeft` 截头留尾（`… / Primitives`，后面那几段才有信息量），先给收藏星留位子。
- **教训**：一行里两块文字各自 `drawText` 到同一个矩形，迟早叠在一起，宽度必须先分配。
- **验证坑**：像素测「有没有缝」要跳过前几行 y，分节标题顶上那条 1px 分隔线是通到头的，算进来永远找不到空白列。

### 11.11 节点名被截成 `show_camera_f...`

- **原因**：老分法「右侧固定占 55%、名字拿剩下的」。`show_camera_frustum` 只有 147px，300px 的列本来放得下，是右边那串分类层级抢走了一半。
- **解决**：浏览态（平铺 / 喜爱 / 常用）不写右边的分类层级，只有搜索结果才写；**名字绝对优先**，要多少给多少，右侧拿剩下的、上限 200px，剩不下 30px 就整块不画；列宽按「列里最长那行一个字都不截要多宽」算（`_rowWidthHint()`），下限是原来的固定宽度，上限 720px，行数到滚动条门槛再加一根滚动条宽。
- **坑**：宽度算得「刚刚好」等于没算。`horizontalAdvance()` 和实际排版差一两像素，宽度正好等于文字宽时 Qt 照样 elide。留 `ROW_TEXT_SLACK = 3`，而且分宽度时要把这几像素算进名字那一份，否则右边把余量吃回去。

### 11.12 搜索要按证据强度分档

- **现象**：打 `ass` 想要 aiStandardSurface，先出来一堆名字里含 "ass" 的（Glass、ShaderAssignment），要的那个掉到子序列档。
- **解决**：前缀 0 / **首字母缩写 10** / 缩写前缀 20 / 词中命中 50+ / 首字母串 200+ / 按词头分段 400+（`stdsurf` 段内还能省字母）/ 子序列 1000+。切词 `[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z][a-z0-9]*|[0-9]+`（驼峰 + 连续大写算一个词），`lru_cache`；空格当「与」；单字母不走缩写档。缩写档排在词中命中前面。两条都命中缩写时按名字长度分先后，用过之后「常用」加权会自己把常用的顶上来。
- **坑**：真机 NodeMenu 的叶子标签是带空格的显示名（`Standard Surface`），搜索要认条目自己的 `searchText`（`aiStandardSurface`），找不到再退回显示名和分类名。测试里按显示名断言一定挂。

### 11.13 常用 / 喜爱

- 根层最上面两节：★ 喜爱（右键 / `Ctrl+D` 收藏，顺序 = 加入顺序）、常用（按用过次数排，最多 8 条）。只给建节点面板，快捷键借来的菜单不带（key 认的是 NodeMenu 里的路径）。
- 右键**按下**就收藏，不建节点、不关面板。
- 收藏和次数在搜索结果里只在同一档内往前挪，别越档把「词中命中」抬到「前缀命中」前面。
- 分节标题当一种行画（另一个 data role + `NoItemFlags`），上下键跳过、鼠标划过不高亮、点了什么都不发生。
- 收藏一变行数就变，重填之后按 key 找回选中行，别按下标。
- **持久化**：记录在主目录下的 `.gaffer_network_editor/nodeCreator.json`（`GAFFER_NETWORK_EDITOR_STATE_DIR` 可搬），先写 `.tmp` 再 `os.replace`，写死 UTF-8，失败清 `.tmp` 并报 Warning；读不出 / 坏了当空的，面板绝不因它炸掉；榜单里有、菜单里已经没有的条目（卸了的插件）当场滤掉。测试和 e2e 一律指到临时目录。
- **两个 Gaffer 会话同时开着**时，后存的一方会用旧数据覆盖另一方刚收藏的：文件比手上新就先重读再写。

### 11.14 平铺还是分组

- 条目 ≤ `PANEL_FLAT_LIMIT`（50）时平铺，但还要加一条「只有一个顶层分类」：pipeline 某个菜单是三个分组子菜单、另一个是六个分组，只按条数判就把分组摊成一坨，「这条属于哪一组」被挤成右边一行小字。原生那里就是几个子菜单，照分组分列。
- 条目多（真机 Tab 600 多条）时第一列只列大类，右边写 `229 items ›`，悬停往右级联；输了搜索词收回一列、全局扁平搜，右边写完整分类路径。

### 11.15 键盘导航

- 浏览时没选中行按 ↑ 会落到倒数第二行、PageDown 落到第 9 行、翻页会绕回：起点按方向取头尾，翻页到头停住。
- `←` 只收列，没有可收的就留给搜索框（以前会清空搜索词）。

### 11.16 无头测试面板的两个坑

- 面板 `popupAt()` 之后别 `EventLoop.waitForIdle()`：offscreen 下那一趟事件循环会把 `Qt.Popup` 关掉（看着像「右键把面板关了」），用 `QApplication.processEvents()`。
- `widget.isVisible()` 在面板还没 `show()` 时恒为 False，拿它判「标题占不占一行」会少算一行。改用和显示无关的判据（有没有文字）。
- 出图要自己拼：一列一个窗口之后 `grab()` 只拿得到根窗口，按全局坐标把几个窗口画到一张图上（`grabAll()`）。
- 收藏星这类画法要验，把 delegate 单独渲染进 `QImage` 数像素：真窗口 `grab()` 有亚像素抗锯齿，金色边缘发橙，计数会乱。
- 每次点击后 `__onAccept` 会清掉，同一个面板点第二条要重新弹。

---

## 12 自动排列

自动排列用的是自己的 Sugiyama 分层布局（分层 → 长边打桩 → 定序 → 定位 → 主干拉直），每一步都可通过 `LAYOUT_STRATEGY` / `layoutStrategy()` 换实现，对照台在 `tests/bench_layout.py`。

### 12.1 原生自动布局不够好

- 一张 44 节点的生产材质图上，原生 `StandardGraphLayout` 排完连线交叉 119。分层布局：最长路径分层（迭代 DFS 防爆栈）→ **长边打桩**（不打桩时比原生还差）→ 重心法定序 + 相邻交换、留交叉最少那遍 → 中位数对齐（按真实宽度、每行整体平移消漂移）→ 整块平移回原中心。超过 400 个节点跳过相邻交换那步。

### 12.2 Gaffer 的图有两种流向

- **现象**：材质图从上往下排，乱成一团。
- **原因**：场景节点 `in` 在上、`out` 在下（竖着流）；材质 / OSL 是参数在左、`out` 在右（横着流）。`ShaderAssignment` 两种都有（`in` / `out` 上下 + `shader` 在左），算竖着流，材质从左边喂进来。
- **解决**：按流向分组。同流向的连通分量各自排（分层算法照旧，只是两个轴互换），跨流向的边当挂钩，把其余组贴到主组旁边（材质从左边喂进来 → 整坨摆在 ShaderAssignment 左边、和 `shader` 插口同高），最后做一遍「推开到不重叠」。
- **主组挑最下游的 sink**（组间连线只进不出的那个）。按节点数挑会挑反：材质 40 个、场景 4 个。

### 12.3 流向判据看错了边

- **现象**：一张 36 个 `OSLCode` 的稠密材质图排出 35 组、161 处交叉。
- **原因**：老判据「**有没有**输入挂上边 → 竖着流」。`OSLCode` 的 `code`、`ArnoldDisplacement` 的 `map` / `height` 都是挂在**上边**的输入圆点，整类材质节点被当成场景节点 → 参数挂左边 → `isFlowEdge` 全为 False → 每条边都被当成「侧面喂进来的」，每个节点各成一组。`OSLCode` 在生产节点库里很常见。
- **解决**：`nodeFlowAxis()` 看**输出圆点挂哪条边**（场景 / 图像 `out` 在下、材质 `out` 在右），一个输出圆点都没有（还没 setup 的 Switch）才退回看输入。改完 1 组、63 处交叉（换 BK 后 44）。
- **兜底**：节点在流向那两条边上压根没有输入圆点时，它挂哪儿哪儿就是主流。`ArnoldDisplacement`（`out` 在右算材质，参数全挂上边）不兜一下就一条主流边都没有，被单独拎成一组。

### 12.4 侧面喂进来的边不能算主流

- **现象**：`PathFilter → ShaderAssignment.filter` 把 PathFilter 排进主干上一层，整列挤歪。
- **解决**：`isFlowEdge()` 按**目的插口挂在哪条边**判：`filter`（右）、`shader`（左）这类侧边插口上的边不参与分层；`BoxOut.passThrough` 是脚手架，也不算。过路节点（BoxIO / Dot）的插口一律算主流。

### 12.5 BoxIn / BoxOut / Dot 没有自己的方向

- **现象**：材质 Box 里的 BoxIn / BoxOut 被单独拎出来吊在材质那一坨上下方。
- **原因**：它们的插口默认挂上下边，但在材质 Box 里串的是横着流的材质链。提升出来的 `filter` BoxIn 圆点在左，要特判成竖。
- **解决**：默认竖着流，邻居都朝一个方向就跟着改。第二遍要顺着已定方向的过路邻居往下传（Shader → Dot → Dot → Shader 中间那个），否则第二遍空转。

### 12.6 主干要直

- 分层 + 中位数对齐之后主干还会被同层旁支挤歪。找最长那条流水线（`_layoutSpine`），钉到同一条中线上，同层其它节点往两边推（`_layoutRowPinned`）。

### 12.7 定位换成 Brandes–Köpf

- 中位数来回扫是启发式，长边的桩链每一节都被两边拉扯，扫完仍是折线；BK 先决定谁和谁必须对齐（连成 block），再整块摆，桩链天生落进同一个 block。12 张图交叉 −8.9%、长边直的条数 +88%，耗时不变；收益几乎全在稠密材质图上。
- 主干拉直改成 `align+pin`：先把主干那条边喂给 BK 当优先对齐的候选（不推同层邻居），再补一遍老的 pin。只 pin 不 align 会把 BK 压紧的结果整个搅乱（交叉 165 → 187）。

### 12.8 主干拉直越权，扇入节点被拽到一边

- **现象**：6 个 Sphere 喂一个 Group，`Ctrl+L` 把 Group 贴到最左边那个 Sphere 底下；手摆的标准答案在正中间（`tests/test_layout_group.gfr`）。
- **原因**：主干 = `Sphere → Group → Transform`，两处拿这条边当「必须对齐」：BK 里主干那条边被插到中位数候选之前；拉直阶段再把整条主干钉到一条中线上。中位数是「到所有邻居总横向偏移最小」的位置，Group 在正中间总偏移 126，贴到最左是 210，旧代码在明知更差的位置上放节点。
- **解决**：主干在 BK 里只在中位数之间取舍（偶数个邻居本来就有两个中位数）；拉直时主干**在扇入处断开**，每段各自钉自己的中线；钉完总横向偏移不许上升，升了整段否掉。14 张图：交叉 −20%、总长 −16%、横向偏移 −27%。
- **试过不采用的**：dot 的边权加权中位数（桩—桩 8 / 桩—真 2 / 真—真 1），长边偏移 −7%，但「主干头一个节点同时喂着一条长边」时会把它从主干那一列拽走（主干直 78 → 69）。

### 12.9 PathFilter 这类侧挂节点被一路甩出去

- **挡路判定拿的是整组包围盒**：主干那组的包围盒是从头到尾一整条，一个挂在旁边的 filter 撞上就得整个越过去。改成逐个节点的矩形，平均侧跳 99.8 → 25.5 单位（原生 14.6）。
- **判「撞没撞」用了推开的间距**：`LAYOUT_GROUP_GAP = 6`，而主干上下相邻节点之间只有 5 的空隙，旁边两个 filter 被判成互撞、一个接一个往外让（五个独享 filter 让出 17 / 34 / 17 / 34 / 51）。判用 `LAYOUT_CLEAR_GAP = 1`、推还是 6，改完五个都是 17.3。这条是新写的严格断言（「五个 filter 的跳距不许一个比一个远」）第一次跑就抓到的。
- **一个 filter 喂好几个节点时只按第一条挂钩摆**：挂钩方向取最外面那个（谁都不压），垂直方向取平均（落在这几个消费者中间）。
- 逐节点判定推一次可能又撞上第三个：顺着挂钩方向推到底，推不干净再退回「四个方向挑位移最小」。

### 12.10 推开这类迭代不能逐步贪心

- **现象**：4 坨横着排开时，最右那坨从最右一路挤到最左（位移 41）。
- **原因**：「四个方向各推一次，取推得最少的」，外层再循环：往右让要 27、往左只要 24 → 选左，又撞上 anchor 再往左推 17。
- **解决**：四个方向各推到底，再比总位移（`_layoutPackOffset`）。

### 12.11 互不相连的几坨叠在一起

- **原因**：没有挂钩的组 `offsets.setdefault( index, anchorOffset( index ) )` 落回原位就完事，一次碰撞检测都不做；各坨排完尺寸变了，原来紧挨着的叠在一起（4 坨 x 3 节点，原始间距 8 → 3 对重叠）。
- **解决**：先落回原位，再逐坨摆开；挂上钩的那几坨当障碍物，一个都不动。
- **关于 Hilbert 序**：层内定序是一维问题，用不上空间填充曲线；摆开互不相连的几坨才是它的场合。实测 Hilbert 序在这一步三项指标（总位移 / 最大位移 / 邻居保持率）都不如「按到中心的距离」排（先摆中心拥挤的、外面的有空地可退），Hilbert 会在象限之间跳，常先摆外圈再把内圈那坨挤出去。当前默认用 Hilbert 序，`hilbertIndex` / `hilbertSorted` 是纯函数，换成径向序只改一行。实现前穷举验过 1~4 阶：下标不重不漏、相邻下标在格子上曼哈顿距离恰好 1；流传的 `rot()` 传 `n` 和传 `s` 两版都是合法 Hilbert 曲线（互为反射）。图坐标是浮点且可能为负，按包围盒量化到 `2^16` 格再算；同格要稳定次级排序。

### 12.12 散节点 `Ctrl+L` 一点不动

- **现象**：六个互不相连的节点（`tests/loose_nodes.gfr`），按 `Ctrl+L` 零位移。
- **原因**：没有边 → 每个节点各成一个连通分量，没挂钩的组只做「落回原位 + 撞了才推开」，本来就不重叠 → 什么都不做。
- **解决**：一条边都没有的散节点并成一组（`_layoutLooseGroup`），它们全落在同一层（rank 全 0），分层布局天然排成「等距 + 保持原来的先后」。横排还是竖列先看现在摆成什么样（x 跨度大 → 横排），堆在一起时才按节点类型的流向惯例。少于两个散节点不动。

### 12.13 数交叉是 O(边²)

- 相邻交换每换一次就重数一遍，300 节点稠密图光这一项 4.9 秒。换成树状数组数逆序对（Barth–Jünger–Mutzel）后 1.2 秒；换之前拿两重循环版当 oracle，200 组随机图逐组比对全一致。

### 12.14 对照台自己的交叉数算错了

- `_segmentsCross` 的叉积符号判定在两条边**共用端点**时 `d1 == 0`，另外两个端点分列两侧就被判成交叉，「源摆正中间」比「贴到边上」凭空多出假交叉。共用端点的两条边直接跳过。修完之后历史交叉数据的口径变了，新旧表别混着比。

### 12.15 其它

- `network-simplex` 分层（Graphviz dot 那套）：连线总长只少 1.3%、交叉一个不差，600 节点稠密图多花 5 秒。默认关，`LAYOUT_SIMPLEX_NODE_LIMIT = 250` 超了自动退回。
- `median` 定序和 `barycenter` 在 12 张图上逐项完全相同（层内节点少、邻居也少）。
- Houdini 那套（ALAP 分层 + 按插口顺序 DFS + 树式定位、完全不做交叉优化）：交叉最多，但输入口顺序保持最好、最快。它的长处「`in0` 一定在 `in1` 左边」单独留成 `order = "dfs*"`。
- 别拿一张简单图下结论：12 张里有 8 张所有组合完全打平，差异全在稠密材质图上。
- 尺寸兜底曾把像素当 Gaffer 单位（宽 12 倍）：去掉兜底，尺寸只从原生问。
- 组之间只把出口节点贴过去不够：下游组里别的节点可能正好横在旁边，摆完要按方向推开一次。
- 原生 `StandardGraphLayout.connectNode / positionNode` 只要 gadget、不要 editor，新节点的自动连线与摆位一直走原生。

---

## 13 Backdrop

### 13.1 Backdrop 选得中、拖不动

- **原因**：`_BackdropItem` 只设了 `ItemIsSelectable`，漏了 `ItemIsMovable`。
- **解决**：加 `ItemIsMovable`（`MetadataAlgo.readOnly( node )` 的不给拖，和节点同判据）。选择那半边照原生（点 Backdrop 连它框住的节点一起选、Ctrl 只动它自己，`GraphGadget.cpp:1056`），所以 flag 一给，拖它就是拖整组。
- **教训**：缺这个 flag 时 Qt 一样 accept 按下、一样进 `_MODE_MOVE`、一样调写回函数，只是不挪 item。「自己 `setPos()` 再 commit」那种合成断言在坏代码上照样全绿，必须加一条 xdotool 真按住拖的 e2e。

### 13.2 有偏心的 Backdrop 一拖就跳

- **原因**：Backdrop 的 item 位置是「框的中心」（`__uiPosition` + `__uiBound` 的中心），能写回 script 的只有 `__uiPosition`。
- **解决**：写回时减去 `centerOffset()`（实时从 `__uiBound` 算，和位置无关，所以幂等）。

### 13.3 在 Backdrop 上没法框选

- **原因**：整块都能点，在 Backdrop 上按下拖就是把整组搬走。
- **解决**：照原生，`shape()` 只有四条边 + 顶上的标题条，框身是洞（`BackdropNodeGadget.cpp:350` 的注释：不留洞 GraphGadget 就没法在它上面框选节点）。四条边在角上重叠，必须 `WindingFill`（4.4）。

### 13.4 想搬动却总在拉高

- 上边缘的抓手要比别的边窄（原生 `min( width, g_titleBarMargin )`），顶上那条留给抓着标题条搬动。

### 13.5 拉边缘改大小

- 四条边 + 四个角，最小 12 单位（原生 `g_margin * 4`），光标按方向换（`SizeHor` / `SizeVer` / 两种对角）。拖的时候只改 item 上的预览，松手才写 `__uiBound`，一次拖动一步撤销。
- 拉框途中的三个残影 / 漂移问题见 5.2、5.3、5.4。

### 13.6 文字、层叠与其它插口

- 标题居中 + 描述自动折行（原生 `renderWrappedText`）；`scale` 插口放大文字、不改框；标题下缘被截见 5.10。
- `depth`（[-1, 1]）+ 面积决定谁垫在谁后面：原生用 GL 深度缓冲，这里换算成 `zValue`（`depth` 分档 + 同档面积大的在后），顺序一致。
- 标题、scale、depth 在脚本 context 里取值，读值可能触发计算，异常收窄到 `Gaffer.ProcessException`。
- 鼠标在框身上（不在边缘上）时标题条高亮（原生 `m_hovered` 那两档颜色）。

### 13.7 框选对 Backdrop 要求整个框住

- 节点是「相交即选」，Backdrop 若也相交即选，每次在它上面框几个节点都会顺手把它选上，一拖整组搬走（真鼠标 e2e 当场抓到选择变成 `[Backdrop, Sphere]`）。Backdrop 照原生要求整个框住。

---

## 14 材质节点分栏与类型图标

### 14.1 分栏数据从哪来

- 只对「有 `parameters` 子插口、侧边插口带 `layout:section` 元数据」的节点分栏（`buildSectionData`），按首次出现顺序分组。没显示成 nodule（`noduleLayout:visible = False`）但带 `layout:section` 的参数也收进来，归到 `parameters` 的 `noduleLayout:section` 那一侧，standard_surface 66 个参数 11 栏全显示。
- **输出口不参与分栏**：材质 `out` 身上带着 `layout:section = "Settings"`，照直分栏右边会长出一个只装 `out` 的栏和折叠三角。`direction() == Out` 一律归进不分栏。
- **灯光不走分栏样式**：灯光卡片本来就是暖黄的，加宽色带 + 卡内参数名一上去糊成一块，而且灯光参数一般在参数面板里调。判据用 `isLightNode()`（见 14.8），别另写。
- 测试夹具：`CompoundDataPlug( "parameters" )` + `nodule:type = GafferUI::CompoundNodule` + `noduleLayout:section = left` + NameValuePlug 挂 `noduleLayout:label` / `layout:section`。别在 NameValuePlug 上设 `nodule:type = ""`，会把它藏掉。

### 14.2 折叠状态

- 存成**非持久**节点元数据 `nodeGadget:sectionCollapsed:<side>:<栏名>`，`rebuildOnNodeMetadata` 按前缀重建。
- 默认收起：没有元数据 = 收起（`return True if data is None else bool( data )`）。`setSectionCollapsed` 一律 `registerValue( ... BoolData( bool ) )`，**绝不 deregister**：取消注册读回来是「默认收起」，展开态必须存 `BoolData( False )`。
- `Metadata.value` 把 `BoolData` 解包成 bool（3.5），第一版 `isinstance( data, IECore.BoolData )` 永远为假，挂了 4 条。
- 可见性只有一个来源 `__visibleSidePlugs( side )`，绘制和命中都用它。收起来的参数圆点锚到栏标题行，连线终点停在栏上，不甩出卡片。
- 分栏节点 paint 里读元数据是每帧几百次 C++ 调用：`sectionCollapsed` 在 item 生命期内只读一次（折叠状态一变，元数据信号会重建整个 item）。

### 14.3 点折叠三角没反应

- 两个原因：OddEvenFill 把三角命中框异或成洞（4.4）；`items()` 用 `shape()` 判命中，标题画在 `shape()` 外（4.10）。
- 收放做成 Houdini 式：三角和整条栏名行都能点（`__sectionRowRect( side, y )` = 自己这一侧的半张卡 × 一行高）。参数行不算标题行（点它是连线），圆点命中优先级不变。栏名画在卡片外面时只点三角（否则吃邻居点击），名字搬进卡片、每栏独占一行之后整行可点。

### 14.4 分栏布局必须固定行距

- **现象**：拖线到最下面那个 `+` 时接到参数圆点上（e2e 2 条 FAIL）。
- **原因**：第一版把行均匀铺满整卡，最后一行贴底 12px，`+`（末两插口外推再夹回）被夹回到参数圆点上，`noduleAt` 先命中参数，`+` 分支跑不到。
- **解决**：固定行距、居中排列（`columnTop = center - rows * pitch / 2`），最后一行离底 21.6px，`+` 落在命中半径外。

### 14.5 参数名搬进卡片

- 名字（含图标）独占顶栏；参数行从顶栏下面起排；参数名 / 栏名写在卡片里（左排贴圆点右侧、右排反过来）；卡外只剩圆点和折叠三角。
- **卡片宽度按全部参数算**，只按当前可见行算的话，收起时宽度缩窄、一展开又跳宽，收着的长名字展开还被裁。撑宽必须同步 `__noduleScaleX`。
- 卡内标签夹在 `SECTION_LABEL_MAX = 140px`（超了 `elidedText`，完整名字仍在悬停放大标签里），再加一条「标题条放得下（图标 + 间隙 + 名字 + 边距）」的下限；不夹的话一条 `Transmission Scatter Anisotropy` 就撑成普通节点两倍宽。
- `__sideLabelWidth`（卡外留白）对分栏节点归零（它还管 `boundingRect` 的悬停余量）。第一遍循环只填 `__sideLabels`（悬停标签和连上加粗还要用），宽度累加必须挪到「分栏节点提前返回」之后，顺序写反就永远是老值（实测 283.75）。
- 卡内最长标签宽 `__sectionedLabelWidth` 要在 `__init__` 里初始化：只在某个分支方法里赋值的属性「有时才存在」，非分栏节点上问它就是 AttributeError。
- 分栏节点不画 `+`：只在 `__buildAdders` 里跳过，`plugAdders()` 纯函数（语义照原生、测试直接断言它）一个字不动；接藏起来的参数走圆点右键展开或直接拖到圆点。

### 14.6 改大段缩进后代码静默不执行

- **现象**：分栏节点的行位置全走默认值。
- **原因**：排行那 20 行整块多缩了一级，落到上一个分支的 `continue` 之后，语法合法、静默不执行。脚本化改缩进时锚点若是方法体里的行，按「`def` 在第一层」算出的缩进量一定过深。
- **另一例**：拆缩进时 `painter.drawText` 留在了 `else`（非分栏）分支里，分栏节点压根没画名字。重写成「先按分栏 / 非分栏算出 `centreY` / `left` / `titleColor` / `nameRect`，再统一画一次」。
- **教训**：`py_compile` 过了不代表结构对。改完逐行核嵌套层级；`cat -A | cut` 数列数会被中文注释的字节展开顶歪，别信。

### 14.7 类型图标

- 卡片轮廓只有三档（Dot 小圆点 / AuxiliaryNodeGadget 小方块 / 胶囊或圆角矩形），节点身份靠左侧矢量类型图标表达。类型按 MRO 里的类名判，不用 `isinstance`，也就不用为此 import 一堆可选模块。
- 材质图标按 shader 名字关键字 + `out` 是不是 `ClosurePlug` 分六种（材质球 / 置换 / 体积 / 贴图 / 程序纹理 / 工具），别指望 `type` 插口（3.12）。闭包输出先判，否则 `mix_shader` / `layer_shader` 画成工具图标。
- 图标画法用查表派发（`_GLYPH_PAINTERS`），加一种图标 = 加一个函数 + 表里加一行。
- 渲染输出类节点（`InteractiveRender` / `ArnoldRender`）直接派生 `ComputeNode`，MRO 里没有叫 `Render` 的类，按整名判认不到，要补 `endswith( "Render" )`。

### 14.8 网格光不是 Light 子类

- `ArnoldMeshLight` / `MeshLight` 派生自 `FilteredSceneProcessor`（1.7.1.0 有独立的 `GafferScene::MeshLight`，同样不是 `Light` 子类），只查 `"Light" in MRO` 会漏掉它。`isLightNode()` 加「MRO 里有类名以 `MeshLight` 结尾」。

### 14.9 灯光按类型分图标

- ArnoldLight 顶层 `name` 只是 `"light"`，真正类型在 `__shader.name`（point / quad / spot / distant / disk / cylinder / skydome / photometric / mesh_light）。`lightGlyph()` 读它，认不出的兜底回灯泡。
- 图标照原生 LightEditor 的 16x16 PNG 复刻：逐像素量重心 / 包围盒 / 主轴角 / 面积 + 四个对角极值点，再用矢量画同形状，**渲染回 16x16 和原生逐像素对拍**（重心 < 1px、包围盒 ≤ 1.5px、墨量 ±30%，描边的聚光和弯折的网格光豁免墨量）。这是不看图也能自己迭代的办法。

---

## 15 性能

### 15.1 全量重建太慢

- profile：全量重建 63% 的时间花在逐个建 `_NodeItem`（每个都要问原生 gadget 尺寸 / nodule / `+`），没变的节点根本不用重建。改成按名字 diff 的增量更新：800 节点改一根线 240ms → 18ms。

### 15.2 每次编辑都做的 O(全图)

| 每次编辑都做 | 改成 |
| --- | --- |
| `collectNodes( root )` 扫全图（2000 节点 9.3ms） | 只改线时一次都不扫，用现成的 item 索引 |
| focus / 参与计算扫全图（9ms） | 只在有新 item 时做，新 item 就地上色；focus / tracker 自己变化走各自的信号 |
| `setSceneRect()` | 包围盒没变就不设（会让整个视口失效） |
| 整个视口重绘 | `SmartViewportUpdate` + 背景缓存（5.1） |

- 改一根线 200 / 800 / 2000 节点都是 4.6–5.3ms，和图大小无关（原生数据层 0.08ms，剩下的差距是 Python + 逐 item 光栅的常数）。
- 这些都写成**次数**断言（改一根线 `collectNodes` 0 次、不重建 item、节点重绘 ≤ 20、闲着零重绘），时间换台机器会变，次数不会。

### 15.3 视口虚拟化没有意义

- 曾以为平移时视口外的节点也在画。判据「一帧 `paint()` 次数 ÷ 视口矩形内实际 item 数」实测都是 1.00：`BspTreeIndex` + `SmartViewportUpdate` 正常工作，之前那个「2000 次 paint」是在全景下量的，全景时所有节点本来就都在视口里。虚拟化只能省 item 内存和建 item 的时间，省不到 paint。

### 15.4 `DeviceCoordinateCache` 不值

- 平移一帧 300 节点 5.3 → 4.8ms、800 节点 11 → 7.3ms、2000 节点 26.7 → 25.2ms，代价是每节点一张 pixmap（2000 节点约 50MB）+ 每次缩放全部失效。

### 15.5 平移开销的构成

- 2000 节点、0.36x、视口内 276 个节点，每帧 18.72ms：不画圆点省 31%、不画标题省 33%、节点完全不画只剩 4.54ms（Qt 合成 + 连线）。大头是绘制本身，而 0.18~0.45 这一档画的名字只有 3.5~6px 高，已经读不出字；再插一档「文字小于可读阈值不画」是剩下唯一大收益，属于观感取舍。

### 15.6 `pointAtPercent` 是单项第一

- 每次调用都把整条曲线做一遍弧长参数化，画中点箭头一条边问三次，平移缩放根本不改路径却每帧重算。`_EdgeItem` 覆写 `setPath()` 把中点缓存置空，`midpoint()` 按当前路径缓存。屏幕上 274 / 550 / 495 个箭头时各省 18% / 22% / 23%。
- 回归断言用次数：第一次真算、连问十次只算一次、`updateGeometry()` / `setPath()` 之后必须作废。最后那两条不能省，只缓存不失效的话箭头停在旧位置，而线本身是 Qt 画的、看着正常。

### 15.7 cProfile 排行不能直接当优化清单

- `plugKey`、`horizontalAdvance`、`boundingRect`、`noduleRadius` 在 tottime 榜上很靠前，把它们全换成常量（上界）之后每帧反而 18.72 → 21.92ms。profiler 放大了 Python 函数占比。排行只用来找「调用次数异常」或「单次就很贵」的东西。

### 15.8 热路径缓存（600 节点图）

| 热点 | 之前 | 之后 |
| --- | --- | --- |
| 空着手移动一次鼠标 | 3.3ms | 0.13ms |
| 600 个节点全在视口里画一帧 | 74ms | 51ms |
| 拉远到色块档画一帧 | 18ms | 11ms |
| 首次建 600 个 item | 445ms | 382ms |

- 鼠标移动见 4.12 / 4.13。
- `_NodeItem` 缓存 `boundingRect` / `shape` / `cardPath`（Qt 一帧每个 item 问 4 次 `boundingRect`），作废顺序见 5.8。
- paint 里别调 `relativeName`：`plugKey()` 是一次约 3us 的 C++ 调用，以前每帧每个圆点算三遍。key / 位置 / 半径 / 颜色在构造时一次算进 `__noduleDraw` 表，paint 和 `noduleAt` 共用。
- `QPen` / `QFont` / `QFontMetrics` 按参数 `functools.lru_cache`，`painter.setFont` 按值拷贝所以共享安全，**别改返回值**。名字宽度、侧标颜色、省略号文本只算一次。
- 信号连接也算钱：`connect( scoped=True )` 约 2us，直系插口的 `childAdded/Removed` 只连会长子插口的（`plugMayGrowChildren`：ArrayPlug / CompoundDataPlug / TweaksPlug / 裸 `Gaffer.Plug` 容器），一个节点 20 次 → 2 次。

### 15.9 量性能的两个坑

- 每轮测量前必须 `frameAll()` 复位。连续滚动会把内容滚出视口，后跑的那一组「什么都不用画」，第一版脚本据此量出了「省 98%」的假数字。
- 计数式测试要先泵到「一帧都不画」：首次显示必然全量画一遍，ContextTracker 异步那一拍也会刷整屏。settle 循环要连着两轮零重绘且 `tracker.updatePending()` 为假。

---

## 16 代码组织与重构

### 16.1 11 000 行单文件拆成包，测试一行不改

- 严格一层套一层，下层不许回头引用上层，永远不会有循环 import：`constants → graph（只碰 Gaffer）→ layout → qt → backdrop_item → node_item → edge_item → view → panel → editor → register → __init__`。每个模块 `from .上一层 import *`，和单文件时代同一个命名空间。
- 每个模块结尾：
  ```python
  __all__ = [ name for name in dir() if not name.startswith( "__" ) ]
  ```
  `import *` 默认跳过下划线开头的名字，而测试用的全是 `NE._NodeItem` / `NE._matchScore` 这类私有名；显式列进 `__all__` 就能一层层带上来。
- facade 用 `__init__.py`：包属性访问和名称重整（`_NetworkEditor__nodeItems` 只看类名）都照旧。唯一要改的是「用 `__file__` 数 dirname 找包内资源」的代码，层数变了，给一个 `packageRoot()`。
- **模块级可变全局必须和读写者同文件**：拆完用 `symtable` 扫「引用了下层没有的全局名」，抓到 `editor.py` 调 `_nativeGraphEditorClass()`（读 `_nativeGraphEditor` 全局），而接管那块当时在上层 `register.py`，整块挪下来。facade 里的模块级**值**是拆分那一刻的快照，外部读写一律走函数。
- 分层用 `symtable` 扫比 `ast.Name` 准（后者把函数局部变量全报出来）：递归每个 scope，`symbol.is_global()` 为真的就是引用了全局。

### 16.2 删未用 import 前查 star-import 借用

- 一层层 `from .x import *` + `__all__ = dir()` 的包里，上游的 `import os` 会漏到下游。删 140 个未用 import 前先用 AST 查清有没有模块靠 star-import 借用；`__init__.py` 的 `packageRoot()` 一直靠 `editor.py` 的 `os` 漏过来才没炸，补上显式 import。
- 两处看着像死代码但不能动：`dummyConnection` 是 `scoped=True` 信号的 keep-alive；有 `global` 声明的赋值（AST 扫描不处理 `global` 会假报警）。

### 16.3 PEP 8 与命名

- 格式交给 `black --line-length 88`。命名保持 camelCase，PEP 8 明文允许（"mixedCase is allowed only in contexts where that's already the prevailing style"），而且三重不可动：几十个 Qt 虚函数覆写（`paint` / `shape` / `boundingRect` / `mousePressEvent` / `itemChange` / `eventFilter`…，名字由 Qt 定）、Gaffer / GafferUI API 契约、测试和 startup 引用的公开名。
- 重构方法：让**没改过的 `tests/`** 当独立 oracle，每做一步（black → 删 import → 改占位名 → 拆函数）就跑一遍无头；测试和实现别在同一轮一起重构。

### 16.4 拆巨型函数

- `paint` 459 行 → 58 行 + 十个绘制阶段方法（三处早退留在 `paint`）、`layoutNodes` 275 → 59、`_drawGlyph` 187 → 20（查表）等，只做行为零改动的拆分。扁平的快捷键判定链（一百多行）故意不拆，拆成查表反而看不出修饰键条件；`editor.py` 不拆 mixin，`self.__xxx` 私有方法互调，换类就要改名称重整，风险远大于收益。
- **按行号机械切函数，边界那两行要回头看**：一段跨阶段的注释被切成两半，`ast.parse` / black 都不报。
- 每拆完一个就 `ast.parse` + `black` + 跑无头；画图那几处拆完额外跑 screengrab（像素断言才看得出 `paint` 有没有画歪）。

### 16.5 注释删什么、留什么

- 删历史叙事（「以前是…后来…」）、重复解释、纯装饰横幅；留不变量和源码引用（`StandardStyle.cpp:534`、「`plugInputChangedSignal` 沿下游响 87 次」、「OddEvenFill 异或出洞」这类一删就会有人再踩一遍的）。

### 16.6 吞异常的 try/except

- 约 70 处吞异常的 `try/except`：调用本身不会失败的直接删；可能触发计算的读值收窄到 `Gaffer.ProcessException`；Qt 已销毁对象的 `RuntimeError`、无名按键的 `KeyError` 保留；信号 handler 的异常交给 Gaffer 的 `EventSignalCombiner` 自己打印。去掉之后浮出的问题见 9.9。

### 16.7 改了代码没生效

- 编辑器模块在 Gaffer 启动时 import 一次，关掉再打开编辑器面板**不会**重新加载，必须重启 Gaffer。
- 同一个模块名可能由多个扩展路径提供（例如开发目录一份、部署目录一份），`import networkEditor` 先到先得。确认跑的是哪一份：
  ```python
  # screengrab 的 commandFile 里
  import sys, GafferUI
  print( sys.modules[ "networkEditor" ].__file__ )
  GafferUI.Editor.create( "NetworkEditor", script )
  ```
  「改完测试全绿、实际启动照样报同一个错」，多半就是实际加载的是另一份旧副本。

---

## 17 Gaffer 1.6 到 1.7 迁移

### 17.1 `_PlugVisibilityGadget` 让编辑器构造直接失败

- **现象**：1.7 上本编辑器根本建不出来，报 `AttributeError: plugContextMenuSignal`。
- **原因**：1.7 新增 `_PlugVisibilityGadget`，`startup/gui/editor.py` 在 `Editor.instanceCreatedSignal` 上对每个 Editor 调五个 `connectToEditor`，它的闸门是 `isinstance( editor, GraphEditor )`，接管装着时本编辑器就是 True。接着它要 `editor.plugContextMenuSignal()` / `nodeContextMenuSignal( True )`，本编辑器没有 → `__getattr__` 诊断钩子照约定抛 AttributeError → 在 `Editor._postConstructor` 里炸掉。
- **解决**：把契约真补齐：`__initState` 里建四个 `Gaffer.Signals.Signal3()`（plug / connection / node / multiNode），配三个访问器 `plugContextMenuSignal()` / `connectionContextMenuSignal()` / `nodeContextMenuSignal( multiNode = False )`，签名照 `GraphEditor.py:205/216/264`。原生那三个是 `classOrSelf` 混合式；本编辑器不是它的子类，只给实例那份，弹菜单时类级、实例级两份都发。

### 17.2 单选右键菜单整个空掉

- **原因**：1.7 的 `startup/gui/graphEditor.py:116` 把 `/Edit...` / `/Enabled` / `/Connections` / `/Focus` / `/Show Contents...` / `/Bookmarked` / 注释全部注册到 `nodeContextMenuSignal( True )` 上，参数是节点列表；原生 `__buttonPress`（`GraphEditor.py:487-490`）发它时没有「选了几个」的守卫。照 1.6 写成 `if len( nodeList ) > 1` 才发多选那一路。
- **解决**：无条件发多选那一路，单个那一路也照旧发一遍（第三方可能连它）。

### 17.3 其它变化

- `↓` 能进哪些节点：三个键依次查（9.11）。
- `Show Contents...` 的原生命令变成 `functools.partial( GraphEditor.__acquireNodes, nodeList )`（`GraphEditor.py:375`）。按菜单路径匹配的重定向不受影响，e2e 的前置断言改成看 partial 绑的是不是原生类。
- `OSLShader` 出厂就带一个空的 `out` 容器 `Plug`（1.6 没有）。测试夹具 `if "out" not in children : addChild( Color3fPlug( "out" ) )` 被跳过，接线时 `Plug` 接不上 `Color3fPlug`，测试硬中断在半路。改成先 `removeChild` 再加。
- 1.6 的 `ShaderUI.PlugAdder` 在 1.7 被 `PlugVisibilityGadget` 换掉，相关分支已删。
- `GafferUI.Widget.currentButtons()` 是 1.7 才加的（它就是 `QApplication.mouseButtons()` 的包装），选择同步那处直接问 Qt。

### 17.4 复核过、没变的

| 项 | 1.7.1.0 实测 |
| --- | --- |
| `StandardNodeGadget.bound()` | 11.0000 x 4.1641 |
| Dot / AuxiliaryNodeGadget | 2.5 / 2.0 |
| `Backdrop.depth` 范围 | [-1, 1] |
| 注册过的注释模板 | 仍只有 `performanceMonitor:*` + `contextMonitor` |
| `ViewportGadget` | 默认 planar、默认视口 640x480 |
| 包装对象身份 | 仍不稳定 |
| `BoxIO.direction()` / `Switch.inPlug()` / `Loop.inPlug()` | 仍没绑 Python |
| `Metadata.value` 读 `BoolData` | 仍解包成 bool |
| `PlugAlgo.dependsOnCompute` 那段 | 从 `GraphEditor.py:843` 挪到 `:932`，判据没变 |

### 17.5 升级方法

- 先原样跑一遍测试拿真实失败清单，别先猜。1.6 → 1.7 实测真正打破的只有右键菜单扩展点那两处。
- 「一条 FAIL 都没有」先确认测试跑到了结尾：`grep -c FAIL` 得 0 也可能是中途抛异常崩了（OSLShader 那条就是）。

---

## 18 测试方法论

测试分几套：

| 套 | 文件 | 跑法 |
| --- | --- | --- |
| 无头：数据层 + UI + 编辑 | `tests/test_network_editor.py`、`tests/test_optimizations.py`、`tests/test_review_v070.py` | `QT_QPA_PLATFORM=offscreen gaffer env python tests/test_network_editor.py` |
| 真机端到端 + 出图（含和原生对拍） | `tests/e2e_network_editor.py` | `gaffer screengrab -commandFile tests/e2e_network_editor.py -image <临时目录>/out.png` |
| 真键鼠（xdotool） | `tests/e2e_panel_input.py` | 有显示器的环境下 `gaffer env python tests/e2e_panel_input.py` |
| 接管 | `tests/e2e_show_contents.py` | screengrab |
| 自动排列对照台（只量数据） | `tests/bench_layout.py` | `QT_QPA_PLATFORM=offscreen gaffer env python tests/bench_layout.py`，`NE_BENCH_COMBOS=all` 跑全矩阵 |

### 18.1 无头一定要带 `QT_QPA_PLATFORM=offscreen`

- 不带时 Qt 走真 X11，窗口交给窗口管理器摆布，视口尺寸和可见性都不确定，`frame()` / hide-show 这类靠几何断言的用例稳定挂，拖动和重绘计数随机挂（`Qt.Popup` 的 `isVisible()` 在真 X11 上不稳）。同一份代码重跑就绿，那是跑法不对。没有 GPU 时加 `LIBGL_ALWAYS_SOFTWARE=1`，缺图标资源时设 `GAFFERUI_IMAGE_PATHS` 指到 Gaffer 自带的 `graphics/`。

### 18.2 断言画出来的东西，别只断言数据

- 「NameSwitch 第二个圆点」查了几轮，一直断言 `getInput() is not None`（全绿），该断言的是本编辑器画出来的边（6.4）。
- 「原生有、我们没有」一律先和原生对拍数量。

### 18.3 和原生对拍

- 同一个 root 各建一个本编辑器和一个**真正的原生 GraphEditor**（`_nativeGraphEditorClass()`，别拿接管后的壳），比三样：
  1. 每个圆点：`nodeGadget.nodule( plug )` 非空的插口落在哪条边（`nodule.transformedBound( gadget ).center()` 和 gadget bound 比）、在那条边上排第几。父插口拿到的是容器，要排掉（3.10）。
  2. 每条连线：`graphGadget.connectionGadget( plug )` 的 `srcNodule().plug()` / `dstNodule().plug()`，两边都用 nodule 那一层的相对名。
  3. 节点尺寸：`nodeGadget.bound()`。
- 一张真实的生产材质图（34 个 ArnoldShader + 5 个 OSLShader 装在一个 Box 里，已脱敏放进 `tests/shader_test.gfr`）第一次跑：连线 62 : 62 全中，圆点少了 14 个（3.13）。
- 原生视图是 OpenGL 的，`grab()` 抓出来是黑图，只能比数据，别想着截图对比。
- 分栏材质节点的排布是自己的，对拍时豁免高度和接口逐点比较，宽度仍比（契约是「以原生为下限，放不下就撑宽」）。

### 18.4 只有真输入测得出的

| 问题 | 为什么合成事件测不到 |
| --- | --- |
| 按住 X 长按 | 合成 `QKeyEvent` 没有自动重复 |
| Alt + 右键缩放 | 窗口管理器可能抢走这个手势 |
| 嵌套 popup 鼠标退回左边那列 | 无头直接调派发函数一定是绿的 |
| 滚轮压在搜索框 / 边距上 | 真滚轮发给光标底下那个控件 |
| Backdrop `ItemIsMovable` | 合成路径照样 accept 按下、照样写回 |

- 真鼠标脚本里右键点在节点上会弹原生 `QMenu` 阻塞事件循环，后面所有断言跟着挂（看着像别的功能也坏了），右键点空白处。
- xdotool 光标已经在目标点上时不会发 motion 事件（`itemEntered` 不来，表现为偶发某一列没开出来）：先挪到旁边几像素再挪过去。

### 18.5 残迹只能在真屏幕上验

- 见 5.17：`screen.grabWindow()` vs 强制 `repaint()` 逐像素比；测量本身会重绘；多显示器下这条测量天生不稳。

### 18.6 报告「条数一点没变」= 脚本中途抛异常

- e2e 和对照台都是跑到最后才一次性写报告文件，中途抛异常文件压根不重写，`grep -c PASS` 读到的是**上一轮的旧报告**，看着像「新断言没生效」。对照台曾据旧报告得出「逆流 8、重叠 1」的结论，全是假的（那一版脚本第一行就崩了）。
- 跑前先删旧报告；跑完先看 stderr 有没有 traceback，再看数字；别把 stderr 丢进 `/dev/null`。
- 常见的中途抛异常：新断言引用了文件里**后面**才定义的变量（`NameError`）；插入的代码劈开了一个 `if` 块留下孤立缩进行（插完先 `ast.parse`）；漏了 import；commandFile 是一整个模块作用域，`for group, ... in` 这种循环变量覆盖了上面建的 Group 节点。

### 18.7 用改动前的整包副本当 oracle

- 把整个包拷一份，只还原这一处改动，拿新测试去跑，证明新测试在旧代码上真会挂（例如 Tab 面板行排版那节在旧代码上挂 8 条、`gap=2`）。新测试里引用旧代码还不存在的 API 时，按节单独 `exec` 并 try 包住，一处缺失不至于崩掉整份。
- 拿副本跑时总条数可能偏少：P 键那一节要 import 隔壁的 `parameterEditor` 包，副本位置找不到它就整节跳过。逐条 diff 断言名字就清楚了。同理，无头测试数随机变少，先看依赖包是不是正被改到一半、import 不进来。
- 做副本时改过的测试文件也要拷进副本：先拷副本后改测试，oracle 报的是旧条数，看着像新断言没生效。判据：oracle 的总条数应和主干一样多。

### 18.8 像素断言的几个坑

- 「隔一个采一个」在小目标上会抖：金色角标只落十来个采样点，卡片宽度一变采样数就在阈值上下跳。改成逐像素数（`step = 1`）并提高阈值。
- 抗锯齿虚线的颜色是混过的（7.4）。
- 判「有没有缝」跳过分隔线那几行（11.10）。
- 截 tooltip：`QToolTip.showText()` 后用 `processEvents()` 泵约 1 秒且不关，再 `setGrabWidget`（`grabWindow` 能带上这个独立小窗口）；「拍到没有」开 / 关两张图逐像素比，拿旧图比会全图都在变。
- 关键元素要真渲染数亮像素，几何断言证明不了画出来了（5.9）。

### 18.9 断言要比「不出错」更严

- 「五个 filter 的跳距不许一个比一个远」比「不重叠」严得多，第一次跑就抓到 12.9 那条。
- 「拖到视口外速度封顶」比「能滚」有用（7.8）。
- 「宽度单调递减」抓住了「往左拖框越来越长」（5.3）。
- 选择断言顺序，别 `sorted()`（7.3）。

### 18.10 无头和真机的注册情况不同

- 无头不跑 gui 启动脚本：NodeMenu 空、节点菜单缺 `/Focus` 等、`DotUI` 插入 Dot 要手动打开（3.8）；注释模板没注册（3.18）。
- 反过来，ScenePlug 的 `nodule:color` 在无头环境里也注册着，按「无头没有类型色」写的断言一跑就挂；「没有类型色 = 原生灰」要拿 int 连线测。
- `GafferArnold` 只能在真机验（3.20）。

### 18.11 测试里的 Qt 对象引用

- `__rebuild()` 会换一个新的 item dict，比「item 有没有被重建」要在重建后重新取，持有引用用 `is` 比；光比 `id()` 会被 Python 的 id 复用骗过去。

### 18.12 时间不稳，次数稳

- 性能回归写成次数断言（15.2 / 15.6），并先 settle（15.9）。

### 18.13 Houdini 对拍数据怎么采

- 在 Houdini 里切到 rounded 连线（`View > Change network wiring style`），用 `hou.NetworkEditor.visibleBounds()` / `screenBounds()` 拿图坐标 ↔ 屏幕像素的映射，抓屏后按颜色 + 连通分量抠出连线，换算回图坐标拟合。
- `setVisibleBounds()` 对「大小不变只挪位置」的请求会被静默忽略，而且视口不是立刻到位：先缩到全图 → 再框到目标 → 回读确认到位，再抓图，否则抓到上一个用例的画面。
- 不参与显示的支线 Houdini 画成虚线，追踪连线时连通半径要放宽；给目标节点打显示旗标能得到实线，但多一圈蓝色高亮环，反而污染点云。
- 软件渲染（llvmpipe）的虚拟显示下 Houdini 启动直接段错误，这类采集只能在真实显示器上跑。
- `pkill -f <模式>` 会匹配到发起这条命令的 shell 自己，把自己杀掉。

---

## 19 故意不跟原生的取舍

以下几处和原生行为不同，都是使用中定下来的：

- **框选相交即选**：原生要求整个框住；Backdrop 仍照原生要求整个框住（13.7）。
- **注释默认只画 `user`**：原生默认画全部，会在每个 Arnold 材质下面写一行 `standard_surface`（3.18）。工具条的 Annotations 菜单可切到 All / 逐个挑。
- **接口标签水平画**：原生按连线切线转角度、太竖时掰回 45° 斜着画（`StandardNodule::renderLabel`）。
- **focus 额外画卡片外的角标**，并且参与 / 不参与的明暗双向拉开：原生只压暗不参与的（0.31），差别不够明显。没设 focus 时一切照原生原色。
- **材质节点参数名常驻写在卡片里**（Houdini 式），原生只在悬停或勾了菜单时显示；灯光节点不走这套样式。
- **拖连线的吸附只在靠近圆点时发生**（视觉上），松手接哪个仍照原生（6.9）。
- **Alt + 左键是平移**：原生是 Tumble，在 2D 节点图里等于把相机转歪。
- **自动排列用自己的分层布局**：原生 `StandardGraphLayout` 只用于新节点的自动连线与摆位。

实现方式不同、效果等价的：Backdrop 层叠用 `zValue`（13.6）；文件拖放转发给原生建节点（7.7）；转成面板的勾选型菜单自己画 `✓`（9.8）。
