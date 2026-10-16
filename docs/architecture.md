# 代码导读

这份文档写给只会一点基础 Python 的读者（知道变量、`if`、`for`、函数长什么样）。
读完之后，打开 `python/networkEditor/` 里任何一个文件，应该能说出：它管什么、里面分几块、
某一段为什么要那样写。

文中引用代码一律用函数名 / 类名，不写行号（行号会随改动漂移）。引用 Gaffer 自己的源码时，
同样写文件名和函数名，方便到 Gaffer 源码里搜。

## 目录

- [0. 几个先要认识的词](#0-几个先要认识的词)
- [1. 这个项目是什么](#1-这个项目是什么)
- [2. 怎么被 Gaffer 加载](#2-怎么被-gaffer-加载)
- [3. 文件全景](#3-文件全景)
- [4. Python / Qt 语法小抄](#4-python--qt-语法小抄)
- [5. 逐个文件](#5-逐个文件)
- [6. tests/](#6-tests)
- [7. 贯穿全局的几个概念](#7-贯穿全局的几个概念)
- [8. 跟着走三遍：一次操作在代码里怎么流动](#8-跟着走三遍一次操作在代码里怎么流动)
- [9. 想改点东西，从哪下手](#9-想改点东西从哪下手)
- [10. 术语表](#10-术语表)

---

## 0. 几个先要认识的词

| 词 | 是什么 |
| --- | --- |
| **node（节点）** | 图上的一张卡片，比如 Sphere、Group、ShaderAssignment |
| **plug（插口）** | 节点上的一个参数或接口，比如 `sphere["radius"]`、`group["in"]` |
| **nodule（圆点）** | 插口画在卡片边上的小圆点。**不是每个插口都有圆点**（一个材质节点几十个参数，通常只有十来个有） |
| **edge / connection（连线）** | 两个插口之间的那根线 |
| **gadget** | Gaffer 原生 OpenGL 界面里的"零件"。原生节点卡片叫 `NodeGadget`，整张图叫 `GraphGadget` |
| **metadata（元数据）** | 挂在节点 / 插口上的小纸条，比如 `nodeGadget:color`（节点颜色）、`noduleLayout:section`（圆点画在哪条边）。**本项目几乎所有外观都读元数据** |
| **script（脚本）** | 打开的 `.gfr` 文件在内存里的样子，即 `ScriptNode`，所有节点都在它里面 |
| **root（当前层）** | 图上现在显示哪一层：整个 script，或者某个 Box 的内部 |
| **item** | Qt 画布上画出来的东西。一个节点在 Gaffer 里是 node，在我们的画布上是 `_NodeItem` |
| **LOD** | level of detail：镜头拉得越远画得越简单（远了就不写字） |

---

## 1. 这个项目是什么

Gaffer 自带的节点图编辑器（GraphEditor）用 OpenGL 加写死的 GLSL 着色器画，从 Python 改不动。
本项目另起一个**用 Qt（`QGraphicsView`）画的节点图编辑器**，Editor 类型名 `NetworkEditor`。
外观更现代，**数据、尺寸、配色、快捷键全部和原生共用**，两个编辑器可以同时开、互相同步。

### 为什么原生改不动

原生那套里 `Style`、`GraphGadget`、`GraphLayout` 三个类在 Python 绑定里没有留可继承的接口，
能改的只有几个元数据旋钮（颜色、形状、最小宽度、内边距、图标）和 `StandardStyle` 的几个全局颜色。
渐变、阴影、多层描边、任意字号、矢量图标都做不到。

### 为什么不全部自己写

"用起来和原生没区别"比"长得好看"更重要，所以有一条贯穿全项目的规矩：

> **几何、配色、行为一律问原生要，别自己发明。**

| 要什么 | 从哪拿 |
| --- | --- |
| 节点摆在哪 | 节点上的隐藏插口 `__uiPosition`（节点中心，Gaffer 单位，y 向上） |
| 节点多大 | 原生 `nodeGadget.bound()` |
| 圆点在哪、线从哪个方向出来 | 原生 `nodule.transformedBound()` / `nodeGadget.connectionTangent()` |
| 节点颜色 | 元数据 `nodeGadget:color` |
| 圆点颜色 | 元数据 `nodule:color` |
| 连线折叠 | `__uiInputConnectionsMinimised` / `__uiOutputConnectionsMinimised` |
| Backdrop 的框 | `__uiBound` |
| 选中了谁 / focus 是谁 | `script.selection()` / `script.getFocus()` |
| 建节点、自动连接、自动摆位 | 原生 `NodeMenu` + `StandardGraphLayout` |

位置、选择这些都存在**同一份数据**里。在原生编辑器里拖一个节点，这边立刻跟着动，
因为两边读的本来就是同一个插口。

---

## 2. 怎么被 Gaffer 加载

仓库根目录有两个 Gaffer 认得的目录：

```
python/networkEditor/        实现（一个 Python 包）
startup/gui/networkEditor.py 启动脚本，只有两句
```

启动脚本：

```python
import networkEditor
networkEditor.registerEditor( application )
```

Gaffer 启动 GUI 时会执行 `startup/gui/` 下所有 `.py`，并提供一个现成变量 `application`。
`registerEditor()` 把 `NetworkEditor` 加进每个面板的编辑器菜单，并装上"接管"（见 [5.12](#512-editorpy--总控)）。

两种装法任选其一：

1. **当成 Gaffer 扩展**：把仓库根目录加进 `GAFFER_EXTENSION_PATHS`。Gaffer 会自动把
   `python/` 放进 `PYTHONPATH`、把 `startup/` 放进启动路径。
2. **手动**：把 `python/` 加进 `PYTHONPATH`，把 `startup/` 加进 `GAFFER_STARTUP_PATHS`。

仓库里另有一个可选的 rez `package.py`（要求 `gaffer-1.7+`），用 rez 管环境时可以直接用它。
只支持 Gaffer 1.7。

**改了 Python 要重启 Gaffer。** `networkEditor` 在启动时只 import 一次，关掉面板再开不会重新加载。

### 可选依赖：P 键参数面板

按 `P` 会弹出一块浮动的纯参数面板，这块面板由另一个独立模块 `parameterEditor` 提供
（调用 `parameterEditor.popupParameters( node, anchor = ... )`）。按键处理
`NetworkEditor._popupParameters()` 在按 P 的那一刻先用 `importlib.util.find_spec("parameterEditor")`
看这个模块在不在，在才导入。不在时这个键不接，编辑器其余部分照常工作。

### 环境变量开关

| 变量 | 作用 |
| --- | --- |
| `GAFFER_NETWORK_EDITOR_TAKEOVER=native` | 不接管 `GafferUI.GraphEditor`（见 [5.12](#512-editorpy--总控)） |
| `GAFFER_NETWORK_EDITOR_ENGINE=0` / `=1` | 强制不建 / 强制建隐藏的原生 GraphEditor（默认：接管装上就不建） |
| `GAFFER_NETWORK_EDITOR_GADGET=0` | 不向原生 `GraphGadget` 问几何，尺寸和圆点位置全走公式 |
| `GAFFER_NETWORK_EDITOR_STATE_DIR` | Tab 面板"收藏 / 常用"记录存放的目录，默认 `~/.gaffer_network_editor` |

`ENGINE` 和 `GADGET` 两个开关既是功能开关，也是一把尺子：关掉跑一遍测试，挂掉的那几条
就是"到底还依赖原生多少"。

---

## 3. 文件全景

```
python/networkEditor/
├── __init__.py        包的入口，对外 API 清单
├── constants.py       数字、阈值、颜色
├── graph.py           数据层（只跟 Gaffer 打交道，不碰 Qt）
├── layout.py          自动排列（Ctrl+L）
├── qt.py              Qt 小工具 + 手绘类型图标
├── backdrop_item.py   Backdrop 的画法、命中、拉框改大小
├── node_item.py       节点卡片的画法 + 命中测试
├── edge_item.py       连线的路径和画法
├── view.py            画布：鼠标、键盘、平移缩放
├── panel.py           Tab 建节点面板（也用来显示别的菜单）
├── editor.py          总控：信号、更新、菜单、编辑操作、接管
└── register.py        注册进编辑器菜单
startup/gui/networkEditor.py
tests/                 无头测试、截图测试、真输入测试、布局对照台
```

`editor.py` 最大（约 5000 行），`node_item.py` / `panel.py` / `layout.py` 各两千行上下，
`graph.py` / `view.py` 一千六到两千行，其余几百行。

### 依赖一层套一层

```mermaid
flowchart LR
    constants --> graph --> layout --> qt --> backdrop_item --> node_item --> edge_item --> view --> panel --> editor --> register --> init["__init__"]
```

每个模块用 `from .上一层 import *` 拿到下面所有层的名字。**下层绝不回头引用上层**，
比如 `graph.py` 里不会出现 `import view`。好处有两个：

- 不会出现"A 要 B、B 又要 A"的循环 import；
- 最底下的 `constants` / `graph` / `layout` 不碰界面，可以在无头命令行里测试。

还有一条从拆包时留下的规矩：**模块级的可变全局变量必须和读写它的函数在同一个文件里**。
比如接管用的 `_nativeGraphEditor` 和读它的 `_nativeGraphEditorClass()`、`NetworkEditor`
都在 `editor.py`，`register.py` 只负责调用。

每个模块最后都是同一句：

```python
__all__ = [name for name in dir() if not name.startswith("__")]
```

`dir()` 列出模块里所有名字，挑出不以 `__` 开头的放进 `__all__`。`__all__` 告诉 Python：
别人写 `from 我 import *` 时给这些名字。

这样写的原因：`import *` 默认跳过单下划线开头的名字（比如 `_NodeItem`），而上层模块和测试
用的正好是这些私有名字。一层层传上去，最外面 `networkEditor._NodeItem` 就能直接拿到。

`__init__.py` 是例外：它的 `__all__` 是**手写清单**（`NetworkEditor`、`registerEditor`、
`collectNodes`、`nodeColor`、`canConnect` …），表示"推荐对外使用的这些"。私有名字照样是包属性，
只是不在推荐清单里。它还提供 `packageRoot()`（仓库根目录），测试靠它找 `tests/` 里的 `.gfr` 夹具。

---

## 4. Python / Qt 语法小抄

读到不认识的写法，回来查这一节。

### 4.1 类和 self

```python
class _NodeItem(QtWidgets.QGraphicsItem):          # 括号里 = 继承谁

    def __init__(self, node, owner, graphGadget=None):   # 创建对象时跑一次
        QtWidgets.QGraphicsItem.__init__(self)           # 先让父类初始化它那部分
        self.node = node                                 # self = 这一个具体的对象
```

`self.node` 是挂在对象身上的变量，别的方法里也能用。`graphGadget=None` 是默认参数，调用时不传就是 `None`。

### 4.2 名字前面的下划线

| 写法 | 含义 |
| --- | --- |
| `width` | 公开 |
| `_width` | 约定的"内部用"，Python 不拦，但外面不该碰 |
| `__hoveredNodule` | 双下划线开头：Python 会自动改名成 `_NodeItem__hoveredNodule` |

最后那条叫**名称重整（name mangling）**，用来防止子类撞名。后果是从类外面访问要写全名，
测试里常见：

```python
editor._NetworkEditor__dragEnter(editor, event)
```

类体里出现的双下划线名字**也会被重整**，所以类体里要引用的模块级常量只用一个下划线。

### 4.3 装饰器 `@`

```python
@staticmethod
def __plugConnected(plug):          # 不需要 self，挂在类里的普通函数
    ...

@functools.lru_cache(maxsize=8192)
def _words(text):                   # 结果缓存起来，同样的输入第二次直接返回
    ...
```

### 4.4 lambda（一次性小函数）

```python
button.clicked.connect(lambda *unused: self.__view.frameSelection())
```

`lambda 参数: 返回值` 是没有名字的小函数。`*unused` 表示"传几个参数都收下、一个都不用"
—— Qt 信号会带参数过来，不收会报错。

### 4.5 闭包（函数里套函数）

```python
def __endConnect(self, position):
    detachItem = self.__connectDetachItem

    def restoreDetached():          # 里层函数看得见外层变量
        if detachItem is None:
            return
        detachItem.setVisible(True)
```

`panel.py` 里有一段专门**拆开别人的闭包**取变量：

```python
freeVariables = dict(zip(code.co_freevars, [cell.cell_contents for cell in closure]))
creator = freeVariables.get("nodeCreator")
```

原生"建节点"的包装函数把真正的创建函数藏在闭包里，而那层包装强制要一个菜单对象；
我们的面板不是菜单，所以把闭包里的 `nodeCreator` 取出来自己调用（见 [5.11](#511-panelpy--tab-建节点面板)）。

### 4.6 `functools.partial`（先塞几个参数）

```python
functools.partial(self._disconnect, [edgeItem.edge])
```

"记住这个函数和这些参数，稍后再调"。菜单条目就是这样绑命令的。

### 4.7 推导式

```python
nodes = [node for node in nodes if not isinstance(node, Gaffer.Backdrop)]
byName = dict((node.getName(), node) for node in nodes)
```

读法："对每个 x，做 y，如果满足 z"。

### 4.8 `try / except` 用得很克制

这个项目只在**确实可能失败、而且失败有明确含义**的地方捕获异常，例如：

- 读一个可能触发计算的插口值，只接 `Gaffer.ProcessException`；
- 碰一个可能已被 Qt 销毁的 item，只接 `RuntimeError`（报错信息是 `Internal C++ object already deleted`）。

不要拿宽泛的 `except Exception` 掩盖问题：异常被吞掉之后，表现常常是"点了没反应"，很难查。

### 4.9 Qt 三件套

```
QGraphicsScene   一张无限大的画布，装着一堆 item
QGraphicsItem    画布上的一个东西（一张卡片 / 一根线）
QGraphicsView    取景框，把画布的某一块显示在屏幕上
```

画布用**场景坐标**；视图负责缩放平移，`mapToScene()` / `mapFromScene()` 在屏幕像素和场景坐标之间换算。

每个自定义 item 要实现三个方法：

| 方法 | 作用 | 坑 |
| --- | --- | --- |
| `boundingRect()` | 我最大占多大，Qt 靠它决定重画哪块 | 说小了会留残影；pen 宽的一半也要算进去 |
| `shape()` | 我的**命中区**，点击 / 拖放算不算点到我 | 不写就默认用 boundingRect，会抢隔壁的点击 |
| `paint()` | 画自己 | 只管画，别在里面改数据 |

### 4.10 信号

"某件事发生了，通知所有登记过的人"。两套写法：

```python
# Gaffer
node.nameChangedSignal().connect(Gaffer.WeakMethod(self.__nodeNameChanged), scoped=True)

# Qt
self.__search.textChanged.connect(self.__searchChanged)
```

`Gaffer.WeakMethod` 是弱引用：信号不会拽住编辑器不放，编辑器关掉就能回收。
`scoped=True` 表示连接的寿命跟着返回的那个对象走，所以代码里总是把连接**存进列表**
（例如 `self.__scriptConnections = [...]`），不存的话连接马上就断了。

Gaffer 信号的形参个数必须和信号签名严格一致。多写一个参数会 `TypeError`，被 Gaffer 的信号
合并器吞掉，表现是回调**静默无效果**。

---

## 5. 逐个文件

### 5.1 `register.py` — 挂进菜单

```python
GafferUI.NetworkEditor = NetworkEditor
GafferUI.Editor.registerType("NetworkEditor", NetworkEditor)

__editorRegistered = False

def registerEditor(application):
    global __editorRegistered
    if __editorRegistered:
        return                                   # 重复调用无害
    GafferUI.Layouts.acquire(application).registerEditor("NetworkEditor")
    installGraphEditorTakeover()
    __editorRegistered = True
```

`global` 表示要改的是模块级那个变量，不写的话 `__editorRegistered = True` 只会建一个用完就扔的局部变量。
做成可重复调用，是因为启动脚本可能被不同的 startup 路径执行两次。

`installGraphEditorTakeover()` 定义在 `editor.py`，见 [5.12](#512-editorpy--总控) 最后一节。

### 5.2 `constants.py` — 数字和颜色

不依赖包里任何东西，整条链的底座。

**坐标换算**

```python
PX_PER_UNIT = 12.0                 # 1 个 Gaffer 单位 = 12 像素
MAX_ZOOM = 25.0 / PX_PER_UNIT      # 原生缩放上限是每单位 25 像素
MIN_ZOOM = 0.02
```

几何一律先按 Gaffer 单位算、最后乘 `PX_PER_UNIT`，两个编辑器里节点一样大。

⚠️ **y 轴相反**：Gaffer 的 y 向上，Qt 的 y 向下。到处能看到这种写法：

```python
item.setPos(position.x * PX_PER_UNIT, -position.y * PX_PER_UNIT)
```

**原生尺寸**（`NODE_HEIGHT_UNITS = 4.1640625`、`NODE_MIN_WIDTH_UNITS = 10.0`、`SIDE_ROW_UNITS = 1.2` …）
是量原生 `nodeGadget.bound()` 得来的**回退值**：能问到原生 gadget 就问它，问不到（例如关掉了 `GADGET` 开关）才用这些。

**阈值**，每个都带注释写明为什么取这个数，例如：

```python
CONNECT_SNAP_DISTANCE = 26.0   # 拖连线时离圆点多近才吸过去
CONNECT_REACH = 28.0           # 松手时离卡片这么近算"丢在这个节点上"
SNAP_RANGE = 360.0             # 拖动吸附只看这个半径内的节点
LOD_MEDIUM = 0.18              # 比这更小就退化成纯色块
CUT_CLICK_SLOP = 4             # X 模式下按下和松开差 4 像素内算"点一下"
WIRE_STUB = 2.5 * PX_PER_UNIT  # 连线出口直段长度
```

**配色**：`_backgroundColor`、`_highlightColor`（等于原生 `StandardStyle` 的高亮色）、`_focusRing` 等，
外加三个颜色函数：

- `_disabledColor(color, connection=False)`：focus 之后不参与计算的东西怎么变暗，往 0.22 的灰上线性插值
  （`v + (目标 - v) * t`），连线再把亮度压到 0.20；
- `_emphasisColor(color)`：有 focus 时参与计算的东西提亮一档；
- `_contrastTextColor(color)`：按亮度（`0.2126 R + 0.7152 G + 0.0722 B`，人眼对绿最敏感）挑深字还是浅字，
  亮黄、亮橙的色带上写白字看不清。

改配色、改手感阈值，大多数情况只动这个文件。

### 5.3 `graph.py` — 数据层

> 只问 Gaffer 要数据，不碰 Qt。

每个函数都是"给我一个节点 / 插口，我告诉你一件关于它的事"。它是界面和 Gaffer 数据之间唯一的翻译层。

| 块 | 主要函数 |
| --- | --- |
| 位置 | `nodePosition` / `setNodePosition` / `positionUsable` |
| 连线折叠 | `nodeConnectionsMinimised` / `connectionMinimised` |
| 圆点布局 | `hasNodule` / `plugSection` / `isCompoundNodule` / `isExpandedCompoundNumeric` / `noduleLayout` |
| `+` 号 | `plugAdders` / `adderSetupComplete` / `oppositeSection` |
| 插口身份 | `nodulePlug` / `plugKey` / `topLevelPlug` |
| 形状尺寸 | `nodeShape` / `nodeSizeUnits` / `textWidthUnits` |
| 图标 | `nodeGlyph` / `shaderGlyph` / `isLightNode` / `lightGlyph` |
| 分栏 | `buildSectionData` / `sectionCollapsed` / `setSectionCollapsed` |
| 配色 | `nodeColor` / `nodeAccentColor` / `cardColor` / `noduleColor` / `wireColor` |
| 状态 | `nodeEnabled` / `enabledPlugForEditing` / `nodeAnnotations` / `canEnter` |
| Backdrop | `backdropRelativeBound` / `setBackdropRelativeBound` / `backdropScale` / `backdropDepth` |
| 元数据白名单 | `rebuildOnNodeMetadata` / `rebuildOnPlugMetadata` |
| 连线收集 | `Edge` / `collectNodes` / `collectEdges` / `edgesForDestination` |
| 连接合法性 | `canConnect` / `resolveInputPlug` |

**位置：只读时不能顺手创建**

```python
def nodePosition(node):
    plug = node.getChild("__uiPosition")
    if plug is None or not isinstance(plug, Gaffer.V2fPlug):
        return None
    return plug.getValue()
```

`__uiPosition` 是原生自动布局算完才建的。只读路径上抢先创建，会把原生的自动布局搞坏。
写的时候（`setNodePosition`）才建，而且要带 `Dynamic` 标志：

```python
plug = Gaffer.V2fPlug("__uiPosition", Gaffer.Plug.Direction.In,
                      flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic)
```

`Dynamic` 的意思是"我是运行时加上去的，存盘时把我写进文件"。忘了加的话存盘再打开会报
`X is not a child of Y`。`positionUsable()` 检查位置是不是有限数，原生摆位算法在退化视口下会算出 `nan`。

**哪些插口有圆点**（`hasNodule`），三条判据全部照原生 `NoduleLayout`：

1. 名字以 `__` 开头的插口（以及它下面的子插口）不进圆点布局。Expression 的输入输出挂在
   `__in` / `__out` 里，不判这条的话表达式那些线会被画成实线，实际应该是虚线（辅助连线）；
2. `nodule:type` 是空字符串 = 明确隐藏；
3. `noduleLayout:visible` 为假 = 隐藏。

**插口身份不能用 `plug.getName()`**

```python
def plugKey(node, plug):
    return plug.relativeName(node)      # 例如 "in.in1.value"
```

NameSwitch 每一路输入都是 `NameValuePlug`，圆点画在 `in.in0.value`、`in.in1.value` 上，
两者的 `getName()` 都是 `"value"`。拿名字当身份，两条线会被算成同一条、第二条被当重复扔掉，
表现是"第二个圆点连不上"。测这类问题要断言**画出来的边**（`_EdgeItem` 的条数），
光断言 `getInput() is not None` 抓不到，数据层本来是对的。

**`Edge` 类**

```python
class Edge(object):
    def __init__(self, srcNode, srcPlug, dstNode, dstPlug, auxiliary):
        ...
        self.auxiliary = auxiliary       # 端点没有圆点 → 画成虚线

    def key(self):
        return (self.srcNode.getName(), plugKey(self.srcNode, self.srcPlug),
                self.dstNode.getName(), plugKey(self.dstNode, self.dstPlug))
```

`key()` 返回元组，可以放进 `set` 去重、可以当字典键，增量更新时靠它判断"这条边还是不是原来那条"。

**连线按目的地收集**

`collectEdges(root, nodes)` 对每个节点调 `_collectEdgesForDestination`。按目的地收集，是因为
`plugInputChangedSignal`（接上 / 拔掉一根线）报的就是目的地节点，增量更新时只要重收这一个节点的入边
（`edgesForDestination`），不用扫全图。

⚠️ Gaffer 的 Python 包装对象**没有稳定的 `is` 身份**：同一个 C++ 节点每次访问都拿到一个新的
Python 对象。判断"是不是同一个"要用 `a.isSame(b)`，或者比名字加父级。

**颜色**

```python
def nodeColor(node):
    color = Gaffer.Metadata.value(node, "nodeGadget:color")
    if isinstance(color, imath.Color3f):
        return _hex(color)
    return _raisedColor
```

只读元数据。所以无论是 Gaffer 自带还是工作室启动脚本注册的配色，都自动生效，这边一行不用维护。

- `nodeAccentColor()`：节点只拿到 `Gaffer.Node` 那个通用默认色时，按它所属的 Python 模块
  （GafferScene、GafferImage …）给一个颜色，免得一屏全灰；
- `cardColor()`：节点色往中性灰混 58%（`_cardTintAmount`）。原生直接平涂 `nodeGadget:color`，
  一屏下来明暗乱跳、字也看不清；混过之后亮度统一、色相保留，顶部色带再用原色。这是少数**故意不跟原生**的地方；
- `noduleColor()`：读插口上的 `nodule:color`（原生按插口类型注册：场景蓝、filter 橙……），"看圆点认类型"靠它；
- `wireColor()`：连线和圆点同一套类型色（源插口优先），太暗的提亮到 `_WIRE_MIN_LUMINANCE`。
  原生还会读目标插口上的 `connectionGadget:color`，**这里故意不读**，免得装了别的插件后连线变成插件的配色。

**`enabled` 不能盲目读**

```python
def nodeEnabled(node):
    ...
    if Gaffer.PlugAlgo.dependsOnCompute(plug):
        return None                  # 第三态："说不准"
    return plug.getValue()
```

`enabled` 被上游驱动时，`getValue()` 是一次真正的计算：大图上慢，图里有依赖环时还会刷一屏
`Cycle detected`。原生 `StandardNodeGadget` 用同一条判据，拿不准就交给 `ContextTracker`
（见 [5.12](#512-editorpy--总控) 的 focus 一节）。按 `D` 时改哪个插口由 `enabledPlugForEditing()` 决定，
逐行照原生 `GraphEditor.__enabledPlugForEditing`。

**类型图标**

```python
def nodeGlyph(node):
    typeNames = [c.__name__ for c in type(node).__mro__]
    if isLightNode(node):
        return lightGlyph(node)
    if "Camera" in typeNames:
        return GLYPH_CAMERA
    if "Shader" in typeNames:
        return shaderGlyph(node)
    ...
```

`type(node).__mro__` 是这个类的继承链。用类名字符串判断而不用 `isinstance`：一次覆盖所有渲染器的
灯光子类，也不用为此 import 一堆可选模块（有的渲染器模块在无头环境 import 就崩）。

- `isLightNode()` 认三种：`GafferScene::Light` 子类、`LightFilter`、类名以 `MeshLight` 结尾的
  （网格光派生自 `FilteredSceneProcessor`，继承链里没有 `Light`）；
- `lightGlyph()` 读 `__shader` 子节点的 `name`（`point_light` / `quad_light` / `spot_light` …）选九种灯光图标之一，
  认不出就画通用灯泡；
- `shaderGlyph()` 给材质节点分六类（材质球 / 置换 / 体积 / 贴图 / 程序纹理 / 工具）。⚠️ 有的渲染器
  `loadShader()` 之后 `type` 一律是同一个值，分不出类型；靠得住的是**名字关键词**加
  **`out` 是不是 `ClosurePlug`**（闭包输出就是真材质）。

**分栏**：`buildSectionData(node, layout)` 把材质节点侧边的参数按 `layout:section` 元数据分栏（Houdini 式可收放）。
三道闸：有 `parameters` 插口、至少一个侧边插口带 `layout:section`、不是灯光节点。输出口不参与分栏。
没圆点的隐藏参数也收进来，所以侧边栏能显示全部属性。收放状态存在节点的**非持久**元数据
`nodeGadget:sectionCollapsed:<边>:<栏名>` 上（不进 `.gfr`，重建 item 不会丢），默认收起。

**元数据白名单**：`rebuildOnNodeMetadata(key)` / `rebuildOnPlugMetadata(key)` 决定某个元数据键变了要不要重建 item。
不筛的话任何一条元数据变动都触发重建，大图上会卡。

### 5.4 `layout.py` — 自动排列

`Ctrl+L` 跑的算法，入口 `layoutNodes(nodes, root, graphGadget=None)`，返回 `{ 节点 : 新位置 }`，
**不写回**，由调用方 `NetworkEditor._arrange()` 在一个 UndoScope 里写。

用的是图论里经典的 **Sugiyama 分层布局**：

1. **分层**：每个节点在第几层（最长路径法：`rank = max(上游的 rank) + 1`，环上的边忽略）；
2. **打桩**：跨好几层的长边中间插"假节点"（`_layoutDummies`）；
3. **定序**：层内按"上一层邻居的重心"来回扫几遍，减少交叉（`_layoutOrderRows` + `_layoutTranspose`）；
4. **定位**：Brandes–Köpf（`_layoutSpreadBrandesKopf`），先决定哪些节点竖向连成一块（block），再整块摆。

**为什么要打桩**：材质图里一张贴图常常直接喂给最下游的节点，这条线横穿五六层。不打桩的话第 3 步"看不见"它，
交叉数会翻倍。假节点名字以 `__layoutDummy` 开头、带一点宽度占出通道，`_layoutComponent` 返回结果时跳过它们。

**每一步都能换实现**（`LAYOUT_STRATEGY` + 上下文管理器 `layoutStrategy()`）：

| 键 | 可选 | 默认 |
| --- | --- | --- |
| `rank` | `longest-path` / `network-simplex` / `alap` | `longest-path` |
| `order` | `barycenter` / `median` / `dfs` / `dfs-barycenter` / `dfs-median` | `barycenter` |
| `position` | `median` / `brandes-kopf` / `tidy` | `brandes-kopf` |
| `spine` | `pin` / `align` / `align+pin` / `off` | `align+pin` |

```python
import networkEditor as NE

with NE.layoutStrategy(position="median", spine="pin"):
    positions = NE.layoutNodes(nodes, root)
```

对照数据用 `tests/bench_layout.py` 量（见 [第 6 节](#6-tests)）。默认组合的取舍：

- `brandes-kopf` 比 `median` 定位交叉少约 9%、长边笔直的条数多近一倍，耗时不变，收益主要在稠密材质图上；
- `network-simplex` 分层连线总长只少约 1%、交叉不减，大图上慢好几秒，所以默认不开，
  超过 `LAYOUT_SIMPLEX_NODE_LIMIT` 个节点自动退回最长路径；
- `median` 定序和 `barycenter` 在测试图上结果完全相同；
- `alap` + `dfs` + `tidy`（Houdini 风格：贴着下游分层、按插口顺序深度优先、树式摆放、不做交叉优化）交叉最多，
  但**输入口顺序保持得最好**、最快。它"`in0` 一定在 `in1` 左边"的长处保留成 `order = "dfs*"` 可选。

**Gaffer 特有的讲究一：按流向分组**

```python
def nodeFlowAxis(node):
    # 输出圆点挂下边 → "vertical"（场景 / 图像节点：上 → 下）
    # 输出圆点挂右边 → "horizontal"（材质：左 → 右）
    # 一个输出圆点都没有（还没 setup() 的 Switch）才看输入挂哪儿
```

判据是**输出圆点挂在哪条边**。用"有没有输入挂上边"判会踩空：`OSLCode` 的 `code`、置换节点的
`map` / `height` 都是挂在上边的输入，会被误判成场景节点，整张材质图被拆成一个节点一组，交叉数爆炸。

一张镜头文件里两种流向都有：场景流水线竖着走，材质那一坨横着走。所以**同流向的节点各自分组各自排**
（`_layoutFlowGroups`），跨流向的边当"挂钩"，最后把材质那一坨挂到它喂的那个 ShaderAssignment 旁边
（`_layoutGroupOffsets`）。

BoxIn / BoxOut / Dot 是纯过路节点，自己没有方向，`_layoutPassThroughAxes` 让它们"邻居朝哪就跟着朝哪"。
完全没有连线的散节点由 `_layoutLooseGroup` 并成一组排成一行（或一列），否则按 `Ctrl+L` 它们一动不动。

**讲究二：侧面喂进来的不算主流**

```python
def isFlowEdge(dstPlug, axis, dstNode=None):
    if dstPlug.getName() == "passThrough" and isinstance(dstPlug.node(), Gaffer.BoxOut):
        return False                 # Box 停用时的直通口
    if isinstance(dstPlug.node(), (Gaffer.BoxIO, Gaffer.Dot)):
        return True                  # 过路节点的插口都算主流
    wanted = ("top", "bottom") if axis == "vertical" else ("left", "right")
    if plugSection(dstPlug) in wanted:
        return True
    # 兜底：节点在流向那两条边上压根没有输入圆点时，它挂哪儿哪儿就是主流
    ...
```

`PathFilter → ShaderAssignment.filter` 这条线，`filter` 挂在右边。算成主流的话 PathFilter 会被排进主干的某一层、
把整列挤歪；判成侧面支线，它就贴在主干旁边。

**侧面那一坨摆在哪**（`_layoutGroupOffsets`）：

- 挡路判定按**逐个节点的矩形**，不按整组包围盒（主干那组的包围盒从头到尾一整条，按它判会把旁边的 filter 甩出老远）；
- "撞上没有"的余量 `LAYOUT_CLEAR_GAP = 1` 和推开的间距 `LAYOUT_GROUP_GAP = 6` 是两个数。拿 6 去判的话，
  主干上相邻两个节点之间只有 5 的空隙，挂在旁边的几个 filter 会被判成互撞、一个接一个往外让；
- 一个 filter 喂好几个节点时，挂钩方向取最外面那个、垂直方向取平均。

**讲究三：主干拉直**（`spine = "align+pin"`）

分层排完，主流水线常被同层旁支挤得左右错开。两步：

1. `align`：把主干那条边交给 Brandes–Köpf 当"优先连成一块"的候选，大部分主干段直接笔直，而且不硬推同层邻居；
2. `pin`：剩下的几段由 `_layoutStraightenSpine` 找出最长流水线，用 `_layoutRowPinned` 把它每个节点固定到同一条中线上，
   同层其它节点往两边推。

只做 `pin` 的话，硬推会把 Brandes–Köpf 压紧的结果搅乱，交叉明显增多。

**另外两个函数**

- `insertionPlugs(node, srcPlug, dstPlug)`：能不能把这个节点塞进这根线，逐条照原生
  `GraphGadget::updateDragReconnectCandidate`（只看有 `correspondingInput` 的输出、两头都要 `acceptsInput`、
  输入必须空着、两个插口都得有圆点……）；
- `candidatePlugs(node, otherPlug)`：拖到某个节点上时它有哪些插口能接。ArrayPlug 展开后的一排
  `in0` / `in1` / `in2` 只留第一个空槽。

### 5.5 `qt.py` — Qt 小工具 + 手绘图标

**上半段：小工具**

```python
def _font(pointSize, bold=False): ...     # 造字体
def _lod(option, painter): ...            # 当前缩放倍数（1.0 = 1:1）
def _eventPos(event): ...                 # 新版 Qt 用 position()，旧版用 pos()
def _globalPos(event): ...
def _sectionTangent(section): ...         # 某条边上的圆点，线朝哪个方向出去
```

```python
def _gafferUIEventFilter():
    module = sys.modules.get("GafferUI.Widget")
    return getattr(module, "_eventFilter", None) if module is not None else None
```

`sys.modules` 是"所有已经 import 过的模块"的字典。这里从 `GafferUI.Widget` 里取出模块级私有变量 `_eventFilter`。
GafferUI 整套拖放靠这个全局事件过滤器驱动，但它只装在 Editor 的顶层控件上，事件被我们的 `QGraphicsView`
子控件吃掉了，所以要自己往视图上再装一遍，否则从别的编辑器拖东西过来没反应。

**下半段：手绘类型图标**

每个图标一个函数（`_glyphCamera`、`_glyphFilter`、`_glyphShader`、`_glyphPointLight`、`_glyphSpotLight` …），
都在中心为 (0, 0) 的 16×16 坐标系里画。`_drawGlyph` 查表、平移缩放、调用：

```python
def _drawGlyph(painter, kind, centre, size, color):
    paint = _GLYPH_PAINTERS.get(kind)
    if paint is None:
        return
    painter.save()                    # 记住当前画笔 / 变换
    painter.translate(centre)
    painter.scale(size / 16.0, size / 16.0)
    ...
    paint(painter, pen, color)
    painter.restore()                 # 还原
```

`save()` / `restore()` 是 Qt 绘图的基本功：改了变换和画笔必须还原，不然后面画的全歪。

`_GLYPH_PAINTERS` 是一张字典表 `{ GLYPH_CAMERA: _glyphCamera, ... }`（`GLYPH_*` 常量定义在 `graph.py`）。
**加一种图标 = 写一个函数 + 表里加一行。**

矢量画的图标缩放不糊，也不用往包里塞 PNG。九个灯光图标的形状照 Gaffer 自带的 16×16 灯光 PNG
逐像素测量（重心、包围盒、主轴角度、面积）后复刻，测试拿那些 PNG 逐张对比。
原生图标里的"缝"（圆柱顶盖、球的经纬线）在 PNG 里是把填充挖掉露出底色；这里只有一个前景色，
`_glyphSeamColor()` 按亮度往黑或往白混一档来画缝。

### 5.6 `backdrop_item.py` — Backdrop

语义逐条照原生 `BackdropNodeGadget`，适合拿来学 `QGraphicsItem` 的三件套。

```python
class _BackdropItem(QtWidgets.QGraphicsItem):
    def __init__(self, node, owner=None):
        ...
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, not self._readOnly)
        self.refresh()
```

- `refresh()`：把框、`scale`、`depth`、标题、描述重新读一遍。item 摆在**框的中心**上
  （`__uiPosition` + `__uiBound` 的中心）；
- `frameRect()`：框本身，绘制、命中、框选判定都用它；
- `boundingRect()`：比框本身大出 `BACKDROP_STROKE_MARGIN`。⚠️ 选中时描边 2px、居中画在路径上，往外溢 1px，
  包围盒不放大的话那一圈永远不会被重画，拉框时留一排细竖线；
- `shape()`：**只有四条边和顶上的标题条，框身是空的**。原生也是这样，这样才能在 Backdrop 上框选它框住的节点。
  四条边在角上重叠，必须 `path.setFillRule(QtCore.Qt.WindingFill)`，默认的 `OddEvenFill` 会把重叠处异或成洞；
- `edgeAt(position)` / `boundForEdgeDrag(...)`：拉边缘改大小。上边的抓手比别的窄，顶上留给搬动。
  换算走"场景坐标 → 节点位置"，不经过 item 局部坐标（拉框时框中心一直在动，会累积偏移）；
- `setPreviewBound()` / `commitPreviewBound()`：拉框途中只改预览，松手才写回 `__uiBound`，一次拉框一步撤销；
- `centerOffset()`：item 位置和 `__uiPosition` 之间差的那个偏移，拖动松手写回时要减掉；
- `__zValue()`：层叠顺序照原生，`depth` 分段、段内面积大的更靠后，大框自动垫在小框后面。

`paint()` 是 LOD 的典型写法：先画便宜的部分，拉得太远就 `return`，不写标题。

整个项目的 z 值大致是：Backdrop 在 -10 附近（按深度和面积细分），辅助连线 1，普通连线 2，节点 10，
悬停圆点的节点临时抬高，正在拖的连线和 X 模式的划线在最上面。

### 5.7 `node_item.py` — 节点卡片

分三块：**建**（`__init__` 那一串）→ **问**（几何 / 命中）→ **画**（`paint`）。

**建**

```python
def __init__(self, node, owner, graphGadget=None):
    ...
    self._nodules = noduleLayout(node)     # 四条边各有哪些插口
    self._shape = nodeShape(node)          # 矩形 / 胶囊 / 小圆点 / 小方块
    self._glyph = nodeGlyph(node)

    widthUnits, heightUnits = nodeSizeUnits(node, graphGadget)
    self.__nativeWidth = widthUnits * PX_PER_UNIT
    self._height = heightUnits * PX_PER_UNIT
    self._width = max(self.__nativeWidth, self.__contentsWidth())   # 原生宽度只当下限
    self.__noduleScaleX = self._width / self.__nativeWidth          # 撑宽了圆点跟着拉开
```

一路问 `graph.py` 要数据，答案缓存在自己身上：`paint()` 每秒可能被调几十次，不能每次都查元数据。
代价是数据变了要重建这个 item（编辑器负责，见增量更新）。

原生宽度按它自己的字体算、没有图标，死守它就会截字。所以**高度照原生，宽度取"原生"和"放得下名字 + 图标"的较大者**，
撑宽后原生给的圆点 x 坐标按比例拉开。

几何还有一层缓存：`boundingRect()` / `shape()` / `cardPath()` 都只在 `__geometryChanged()` 时作废。
⚠️ 顺序是**先 `prepareGeometryChange()` 再清缓存**，Qt 在前者里要拿旧框把 item 从索引里摘下来。

**圆点位置：能问原生就问原生**（`__buildNodules`）

```python
gadget = graphGadget.nodeGadget(self.node)
nodule = gadget.nodule(plug)
bound = nodule.transformedBound(gadget)          # 原生画这个圆点的地方
t = gadget.connectionTangent(nodule)             # 线从这儿朝哪个方向出去
```

`transformedBound(gadget)` 是这个圆点在卡片坐标系里的框，取中心就是位置。切线决定连线从哪个方向甩出去。
拿不到原生 gadget 就退回 `__sectionPoint()` 的均分公式。

⚠️ 在测试里拿原生 gadget 量子圆点之前，先调一次 `nodeGadget.bound()`：里面的容器是懒排版的，
没问过尺寸拿回来的是父容器局部坐标。

`__rebucketNodules()` 再按原生切线**重新分边**（切线 x 分量大就是左 / 右，否则上 / 下）。
元数据推出来的边偶尔和原生对不上，切线是原生真正画在哪条边的证据。

展开的 Color3f / V3f 子圆点（右键 Expand RGB）照原生 `CompoundNumericNodule`：子圆点缩到 0.75，
整簇待在父接口原来那一格（`_noduleClusters` / `__placeCluster`）。⚠️ 这和 `GafferUI::CompoundNodule`
（ArrayPlug、材质 `parameters`，子插口摊开成兄弟）是两回事，判据是 `isExpandedCompoundNumeric()`。

**材质节点的分栏**

| 方法 | 干什么 |
| --- | --- |
| `__sectionRows(side)` | 这一侧有几行（栏名一行，展开的栏再加参数行） |
| `__visibleSidePlugs(side)` | 现在**画得出来**的参数，画和命中都用它，两者才一致 |
| `__applySectionedSize()` | 按行数算高度、按全部参数里最长的标签算宽度（只按可见行算，收放时宽度会跳） |
| `__placeSectionRows()` | 一行一行摆圆点；收起的栏，参数圆点锚到栏名那一行，连线终点停在栏上 |
| `sectionAt(point)` | 这个点落在哪个栏的折叠三角 / 栏名行上 |

分栏节点的名字和图标画在加宽的标题条里（`SECTION_TITLE_HEIGHT`），参数名写在卡片里面，
卡内标签按 `SECTION_LABEL_MAX` 截断（完整名字在悬停放大标签里）。分栏节点不画 `+`。

**问：三个必须自己写的方法**

`boundingRect()`（`__computeBoundingRect`）一层层取最大值，因为卡片外面画了不少东西：侧边参数名、
悬停放大的圆点和标签、focus 角标、折叠三角、书签、顶底接口标签、注释。**少算一样，拖动时那一块就留残影。**

⚠️ `boundingRect()` 是几何，只能在 `prepareGeometryChange()` 之后变，而缩放倍数是 `paint()` 时才知道的。
所以任何按 `1/lod` 放大的绘制（focus 角标、书签）都要夹上限（`FOCUS_LOD_FLOOR`、`BOOKMARK_MAX_SCALE`），
包围盒按上限留余量。

`shape()`（`__computeShape`）：

```python
path = QtGui.QPainterPath()
path.setFillRule(QtCore.Qt.WindingFill)        # 不能省
path.addRect(self.cardRect().adjusted(-NODULE_HIT_RADIUS, -NODULE_HIT_RADIUS,
                                      NODULE_HIT_RADIUS, NODULE_HIT_RADIUS))
for side in ("left", "right"):
    for _, y in self.__sectionHeaders.get(side, []):
        path.addRect(self.__sectionTriangleRect(side, y))
if self._focusFlagEnabled:
    path.addRect(self.focusFlagHitRect())
```

1. **必须重写**，不能跟着 `boundingRect()`。悬停时包围盒会撑到 ±150 像素，不重写的话刚悬停过的节点
   会把周围一大片的点击都吃掉，表现是"挨得近的两个节点连不上"；
2. **`WindingFill` 不能省**。`QPainterPath` 默认奇偶填充，往同一条路径里加两个重叠矩形，重叠那块会被异或成洞。
   折叠三角贴在卡片边线上、和卡片重叠，结果三角那块反而不算命中，"点展开三角没反应"。
   排查办法：沿一条水平线扫 `shape().contains()` 打表，会看到中间被挖空的一段。

`paint()` 是十几个阶段函数的调度表：

```python
def paint(self, painter, option, widget=None):
    lod = _lod(option, painter)
    if lod < LOD_MEDIUM:
        self.__paintFar(painter, path, selected, lod)   # 远景：一个色块
        return
    self.__paintCardBody(...)        # 卡片本体 + 描边
    self.__paintAccentBand(...)      # 顶部类型色带 / 分栏节点的标题条
    self.__paintNodules(...)         # 圆点
    self.__paintSideLabels(...)      # 侧边参数名
    self.__paintEndLabels(...)       # 顶底接口标签
    self.__paintSectionHeaders(...)  # 栏名 + 折叠三角
    self.__paintAdders(...)          # `+`
    if self.focusFlagVisible():
        self.__paintFocusTab(...)    # focus 角标
    if self._bookmarked or self._bookmark:
        self.__paintBookmark(...)    # 书签
    if self._shape == SHAPE_DOT:
        return                       # Dot 到此为止
    if self._shape == SHAPE_AUXILIARY:
        写一个首字母; return
    self.__paintTitle(...)           # 图标 + 名字
    self.__paintStrikeThrough(...)   # 停用的对角线
    if lod < LOD_NEAR:
        return
    self.__paintDetails(...)         # 徽章、注释、可进入的小三角
```

focus 角标和书签必须画在 Dot 早退**之前**，放到末尾的话 Dot 上永远看不到角标、没法设 focus。

LOD 分三档：`< LOD_MEDIUM`（0.18）一个色块（focus 不刷整块金色，免得和黄色的灯光节点混淆）；
到 `LOD_NEAR`（0.75）画卡片、名字、圆点、角标；再往上加徽章和注释。侧边参数名自己还有三档：
够大写字 → 小了退化成一小截类型色块 → 再小不画。

停用的对角线（`__paintStrikeThrough`）三种颜色：`enabled` 是死值的灰、不参与计算的更暗、
`ContextTracker` 算出来关着的黄（`STRIKE_DYNAMIC`）。

**拖动吸附**的钩子在 `itemChange()`：

```python
def itemChange(self, change, value):
    if change == QtWidgets.QGraphicsItem.ItemPositionChange and self._owner is not None:
        return self._owner._snapNodePosition(self, value)    # 返回修正后的位置
    if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged and self._owner is not None:
        self._owner._nodeItemMoved(self)
    return QtWidgets.QGraphicsItem.itemChange(self, change, value)
```

`ItemPositionChange` 是 Qt 给的时机："这个 item 即将挪到 value，你可以改一下再返回"。

**故意不跟原生的几处**

| 地方 | 原生 | 这里 | 原因 |
| --- | --- | --- | --- |
| focus 表达 | 节点外的一个 gadget | 卡片右上角**外侧**的折角，拉远按 `1/lod` 补偿 | 整块刷金色会和黄色灯光节点混淆；画在卡片里会吃掉小节点的可点区域 |
| focus 命中 | — | 按三角形斜边 `dx + dy <= size` 判 | 包围盒是三角形的两倍面积，Dot 上容易误触 |
| 卡片主体色 | 平涂 `nodeGadget:color` | 往中性灰混 58% | 原生一屏明暗乱跳、字看不清 |
| 变暗程度 | 较轻 | 更重（配合参与计算的提亮） | 原生力度下"参与 / 不参与"区别不明显 |

**悬停小框**：界面标签用英文，悬停小框（tooltip）用中文。`setHoveredNodule(plug)`（参数名、输入 / 输出、类型、
接没接上、插口 `description`）、`setHoveredAdder(section)`（拖线过来会发生什么）、`setHoveredSection(side, name)`
（点一下展开 / 收起），清空时恢复成节点自己那份 `__toolTip()`。

### 5.8 `edge_item.py` — 连线

**`_wirePath(p0, t0, p1, t1, style, avoid=())`**：曲线模式照 Houdini 的 rounded 连线，形状由**直段和正圆弧**组成：
出口先顺流向走一小段（`WIRE_STUB`），用一个小圆角拐向侧面，横平地走过去，
再用一个大圆弧拐成流向，直着扎进入口。

拆成几个函数：

- `_houdiniWirePoints(p0, f, p1, g)`：算折线拐点和每个拐角的圆角半径。几种情况：
  正上正下一条直线；出入方向垂直（filter 那种侧边接口）走一个拐点；目标在上游侧绕出去再绕回来；
  常规情况是"直段 → 小圆角 → 横段 → 大圆角 → 直段"，主圆角半径按
  `WIRE_TURN_SLOPE * 流向距离 + WIRE_TURN_BASE` 增长；
- `_roundedPath(points, *radii)`：把折线拐角换成正圆弧（用 `4/3 * tan(φ/4)` 的标准贝塞尔近似画圆弧，
  90° 就是常见的 0.5523），半径按相邻两段长度自动收；
- `_routeAround(...)`：Houdini 那套只看两个端点。接口在卡片侧边、上游又在另一边时
  （filter 接在右侧而源节点在左边、节点自己连自己），折线会从卡片中间横穿过去。
  这时 `_cardsToAvoid` + `_polylineCrossesCards` 判出"穿过两端的卡片了"，改走横平竖直、绕开卡片
  （外扩 `WIRE_CLEARANCE`）的折线：候选里挑长度加拐点数最小、不掉头的那条。
  "穿没穿"按卡片本身判，绕行按外扩判；Dot 的端点在卡片里面，不绕。没穿的连线形状不变；
- `_segmentHitsRect`：线段和矩形求交（Liang–Barsky 裁剪）。

直线模式（工具条切换 `WIRE_STRAIGHT`）就是一句 `path.lineTo(p1)`。

**`_EdgeItem` 类**继承 `QGraphicsPathItem`（Qt 自带的"画一条路径"的 item），只在 `paint()` 末尾加一个方向箭头，
箭头画在线的**中点**（画在终点会和圆点叠成一团）。

`__applyPen()` 按优先级决定颜色：

```python
if self._insertTarget:   base = 金色        # 松手就把节点塞进这根线
elif self._selected:     base = 选中色
elif self._hovered:      base = 高亮色
elif not self._active:   base = 变暗色      # focus 之后不参与计算
elif self._emphasis:     base = 提亮色      # 有 focus 时参与计算的
else:                    base = 类型色
```

再加**长线中段渐隐**（Houdini 的做法，否则大图上连线糊成一片）：

```python
gradient = QtGui.QLinearGradient(p0, p1)
gradient.setColorAt(0.0, base)
gradient.setColorAt(0.16, base)
gradient.setColorAt(0.5, mid)       # 中间最透
gradient.setColorAt(0.84, base)
gradient.setColorAt(1.0, base)
pen = QtGui.QPen(QtGui.QBrush(gradient), width, style, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
```

画笔可以吃渐变，这是 Qt 的一个小技巧。

- `shape()`：用 `QPainterPathStroker` 把线加粗成 10 像素宽的面，细线也好点中，结果缓存；
- `endAt(scenePosition)`：照原生 `StandardConnectionGadget::endAt`，**只有靠近两端才算抓住连线**，
  灵敏区按线长的 1/4、夹在 2.5 到 25 个 Gaffer 单位之间。中间那段是"选中这条线"；
- 折叠（右键 `Connections/Show Input…`）：从目的地圆点伸出 `MINIMISED_STUB` 长的小尾巴，悬停时才画完整；
- `hoverEnterEvent`：有键按着（平移、拖节点、框选）时不高亮，不然平移扫过的每条线都亮一下，看着像图在闪；
- `setPath()` 被覆写：路径一变就作废中点、命中形状、路径长度三份缓存。平移缩放不改路径，不用重算。

### 5.9 `view.py` — 画布（所有输入的入口）

**模式状态机**

```python
_MODE_NONE = 0
_MODE_PAN = 1        # 平移
_MODE_CONNECT = 2    # 拉连线
_MODE_CUT = 3        # X 划线删除
_MODE_MOVE = 4       # 拖节点
_MODE_BAND = 5       # 框选
_MODE_ZOOM = 6       # Alt + 右键拖缩放
_MODE_RESIZE = 7     # 拉 Backdrop 的边
```

`self.__mode` 记着"现在手上在干什么"，鼠标移动和松手都先看它。写交互的常用套路：一个状态变量 + 每个事件里按状态分派。
`self.__gestureButton` 记着是哪个键开始的手势：一个手势没做完时按第二个键一律不理，松开的不是那个键也不算结束。

**构造里的关键设置**

```python
self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
self.setDragMode(QtWidgets.QGraphicsView.NoDrag)                    # 橡皮筋自己画
self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
self.setCacheMode(QtWidgets.QGraphicsView.CacheBackground)
self.setMouseTracking(True)                                         # 不按键也收到移动
```

`SmartViewportUpdate` + `CacheBackground` 是一处重要的性能选择：`FullViewportUpdate` 让任何一点变化都重绘整个视口，
几百个节点改一根线就要重绘几百张卡片。场景的索引深度另外设成 `BSP_TREE_DEPTH`，Qt 自动选的深度太浅，
整张图挤在一两个格子里，命中测试慢。

**平移**

```python
def __pan(self, delta):
    anchor = self.transformationAnchor()
    self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)   # 必须临时切
    self.translate(...)
    self.setTransformationAnchor(anchor)
    self._rememberCentre()
```

1. `AnchorUnderMouse` 会在变换改变时重新锚定，把 `translate()` 原样抵消，表现是"中键拖了没反应"，所以临时切 `NoAnchor`；
2. 场景矩形留足余量（`SCENE_MARGIN`），否则拖到内容边缘会被夹住；
3. `__beginPan()` 里 `self.setInteractive(False)`：平移期间关掉 item 交互，否则画面在鼠标底下滑过去，
   扫到的线会亮、节点会弹提示。

**滚轮缩放：锚点自己算**

```python
def wheelEvent(self, event):
    before = self.mapToScene(position)       # 光标底下是哪个场景点
    self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
    self.scaleBy(1.15 if delta > 0 else 1.0 / 1.15)
    after = self.mapToScene(position)
    self.translate(after.x() - before.x(), after.y() - before.y())   # 挪回去
```

不能用 `AnchorUnderMouse`：它锚在 Qt 自己记的 `lastMouseMoveScenePoint` 上，只有 Qt 自己的 `mouseMoveEvent` 才更新它，
而平移那条路自己处理完就 `return` 了。横向滚轮（`angleDelta().y() == 0`）直接忽略。

**Alt + 右键拖 = 缩放**（`__beginZoom` / `__updateZoom`），照原生 `ViewportGadget` 的 dolly：
往右 / 往上放大，`zoom = 起始 zoom * exp(1.9 * d)`，锚点固定在按下那一刻光标底下的点。
`contextMenuEvent` 里要挡掉 Alt + 右键，否则手势会变成"点一下弹菜单"。

**视野中心自己记**（`_rememberCentre` / `__restoreCentre`）：平移直接改变换，Qt 内部的视野中心不会跟着更新，
尺寸一变（拖分隔条、换 tab）`QGraphicsView` 就跳回平移之前的位置。所以自己记一份，`resizeEvent` / `showEvent` 时对回去。

**拖到视口边缘画面自己滚**（`__updateDragTracking` / `__trackDragIdle`），照原生 `ViewportGadget::trackDrag`：
不滚区是视口往里缩一圈，越靠边越快，拖到视口外速度封顶。

**命中测试：画在卡片外的东西都要在周围再找一遍**

```python
def noduleAt(self, position):
    item = self.nodeItemAt(position)
    if item is None:
        probe = QtCore.QRect(position.x() - NODULE_HIT_RADIUS, ..., NODULE_HIT_RADIUS * 2, ...)
        for candidate in self.items(probe):       # 光标周围一小块里找最近的圆点
            ...
```

`adderAt()`、`sectionHeaderAt()`、`focusTabAt()`、`backdropEdgeAt()` 都是这个套路。
圆点、`+`、折叠三角、focus 角标都画在卡片边界上甚至外面，`shape()` 只包到卡片加一点余量，
光标正压在 `+` 上时 `nodeItemAt` 反而是 `None`。

鼠标移动时的悬停判定集中在 `__updateHover()`：一次 `items(probe)` 拿到附近的候选，判据照 Qt `items(QPoint)`
（一个像素映射到场景的小矩形和 `shape()` 求交），圆点 → `+` → 分栏 → Backdrop 边依次判，
不再每种东西各查一遍场景。

**左键按下的判定链**（`__leftPress`）

1. 圆点 → `__pressNodule`（拉线 / 改接）
2. 分栏三角或栏名行 → 收起 / 展开
3. focus 角标 → 切换 focus
4. 连线 → `__pressEdge`（两端改接，中段选中）
5. Backdrop 的边 → `__beginResize`
6. 节点 / Backdrop → `__pressItem`（选中 + 准备拖动）
7. 空白 → `__beginBand`（框选）

连线的命中区很宽，所以放在圆点之后、节点之前，并且只在光标没压着节点时才判。

**按在已连接的圆点上 = 断开 / 改接**

```python
def __pressNodule(self, item, plug, position):
    edgeItem, end = self.__owner._edgeItemForPlug(plug)
    if edgeItem is not None and self.__beginReconnect(edgeItem, end, position):
        return
    self.__beginConnect(item, plug, position)
```

`__beginReconnect` 把原来那条线 `setVisible(False)` 藏起来，否则屏幕上同时有两条（一条跟着鼠标、一条在原地）。
松手没接成的话 `restoreDetached()` 再把它显示回来；拖到空白处才是真断开。

**选择：要防着 Qt 在两处插手**（`__pressItem` 和 `__mouseReleaseEvent`）

```python
selectionBefore = self.__owner._selectedSceneItems()
self.__owner._setSelectionSyncSuspended(True)
try:
    QtWidgets.QGraphicsView.mousePressEvent(self, self.__withoutModifiers(event))
    self.__owner._restoreSceneSelection(selectionBefore)
finally:
    self.__owner._setSelectionSyncSuspended(False)
self.__owner._flushSelectionToScript()
```

1. **抹掉修饰键**再交给 Qt（`__withoutModifiers` 造一个不带 Ctrl / Shift 的事件），选择规则已经由
   `_selectClicked` 照原生 `GraphGadget::buttonPress` 算好了；
2. **前后各记一次选择、对不上就对回去**：`QGraphicsScene` 在没有 item 接受按下时会 `clearSelection()`，
   松手时还会"没移动就只留一个"，把 Shift 多选塌回单选；
3. **兜回来这一整段挂起"写回 script"**：写回是差异式的（remove + add），一来一回会把选择集从 `[A, B]`
   变成 `[B, A]`，跟着"最后选中那个"走的参数面板就会来回跳。

`try / finally` 保证标志一定复位。

**框选**自己画（`__beginBand` / `__endBand` → `_applyBandSelection`）：Shift 加选、Ctrl 减选照原生。
节点**相交即选**（故意不跟原生，原生要完全框住），Backdrop 照原生要**整个框住**才选，
否则在 Backdrop 上框几个节点必然把它一起选上、一拖整组搬走。

**键盘：几层拦截**

```python
def event(self, event):
    if event.type() == QtCore.QEvent.ShortcutOverride:
        if (event.key(), modifiers) in self.__overrideKeys:
            event.accept(); return True        # 从菜单栏手里把键抢回来
```

菜单栏 `QAction` 的快捷键在 `ShortcutOverride` 阶段就把键截走，控件的 `keyPressEvent` 收不到。
`Ctrl+C/V/X/D/A/L/F`、`Delete`、`F2` 这些要在这一步抢下来。

```python
def keyPressEvent(self, event):
    if event.isAutoRepeat():
        event.accept(); return                          # 自动重复一律不管
    if self.__handleKey(event): return                  # 1. 我们自己认得的
    if self.__owner._forwardShortcutKey(event): return  # 2. 转发给注册在 GraphEditor 上的快捷键
    if event.key() in self.__scrollKeys:
        event.accept(); return                          # 3. 方向键吞掉
    QtWidgets.QGraphicsView.keyPressEvent(self, event)  # 4. 往上传
```

第 3 步：`QGraphicsView` 继承 `QAbstractScrollArea`，方向键 / PageUp·Down / Home·End 默认用来滚画面。
原生 GraphEditor 是 GL 视图，按上下键一动不动，这边要手动吞掉。

`__handleKey()` 是一条扁平的判定链，修饰键组合写在条件里一目了然，所以没有拆成查表：

| 键 | 动作 |
| --- | --- |
| `F` / `` ` `` / `Ctrl+`` ` `` | 框选中 / 框 focus / 把选中设为 focus |
| `↓` / `↑` / `[` / `]` | 进入选中的 Box / 回上一层 / 层级历史前后 |
| `Tab` | 建节点面板 |
| `D` | 停用 / 启用 |
| `P` | 浮动参数面板（可选依赖，见第 2 节） |
| 按住 `X` | 划线删除 |
| `B` / `0`~`9` / `Ctrl+0`~`9` | 找书签 / 跳到编号书签 / 设编号书签 |
| `Delete` `Backspace` `F2` | 删除 / 删除 / 改名 |
| `Ctrl+C/X/V/D/A/L/F`、`Ctrl+Shift+A` | 复制 / 剪切 / 粘贴 / 带输入复制 / 全选 / 自动排列 / 查找 / 全不选 |

**X 模式：按住 X 划线删除**

```python
def keyPressEvent(self, event):
    if event.isAutoRepeat(): ...        # 两边
def keyReleaseEvent(self, event):
    if event.isAutoRepeat(): ...        # 都要挡
```

X11 的按键自动重复（按住约 0.5 秒后开始）会不停发 press / release 对。只挡 press 的话，
release 会把划线收掉、下一个 press 又重开，表现是"划到一半一直闪"。合成事件里没有自动重复，
只有真键盘长按测得出来（所以有 `e2e_panel_input.py`）。

按着 X 时：左键按下开始划，松开左键这一笔切下去（`__applyCut`），可以接着划下一笔；
按下松开差 `CUT_CLICK_SLOP` 像素以内算"点一下"（`__cutWasClick` → `__cutClick`：点线删线、点节点删节点）；
右键取消；中键照旧平移，平移期间划线模式挂起。划过的线靠 `item.shape().intersects(划线路径)` 判。

**临时 item 的生命周期**（`_discardTransientItems`）：重建时 `scene.clear()` 会销毁临时 item（拖拽中的连线、划线）的 C++ 对象，
Python 变量还指着它，下次 `setPath()` 就报 `Internal C++ object already deleted`。所以重建前先让视图忘掉它们，
用的地方也包 `try / except RuntimeError`。

### 5.10 `panel.py` 顶部的纯函数

`panel.py` 顶部是一组不依赖界面的函数，测试直接调：

- `_unwrapNodeCreator(command)`：从原生 `NodeMenu.nodeCreatorWrapper` 的闭包里取出 `nodeCreator` / `plugValues` / `postCreator`；
  创建函数自己要 `menu` 参数的返回 `None`；
- `_matchScore(needle, text)` 及其助手 `_words` / `_initials` / `_subsequence` / `_wordPrefixSkips`：搜索打分；
- `_entriesFromDefinition(definition, menu=None)`：把一份 `IECore.MenuDefinition` 摊平成面板条目；
- `_entryActiveNow` / `_entryCheckState` / `_commandWantsMenu` / `_commandWantsCheckBox`：照原生 `Menu` 的规则
  求值条目的 `active`、`checkBox`，判断命令要不要 `menu` / `checkBox` 参数；
- `_splitRowWidths` / `_rowWidthHint`：一行里名字和右侧信息怎么分宽度、一行不截断要多宽。

### 5.11 `panel.py` — Tab 建节点面板

按 Tab 弹出的级联多列面板。`B`（找书签）、拖线到 `+` 选隐藏参数、以及被截下来的原生快捷键菜单，
也都用它显示（`NetworkEditor._showPanel` / `_showMenuAsPanel`）。

**搜索打分**

```python
_wordPattern = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z][a-z0-9]*|[0-9]+")
```

这条正则把名字切成词，认驼峰、连续大写、数字：`aiStandardSurface` → `ai / Standard / Surface`，
`OSLCode` → `OSL / Code`。`_words` 加了 `@lru_cache`，每敲一个字符都要给几百个条目打分。

`_matchScore()` 的档位（**分数越小越靠前**）：

| 分数 | 命中方式 |
| --- | --- |
| 0 | 前缀 |
| 10 | 正好是首字母缩写 |
| 20+ | 首字母缩写的前缀 |
| 50+ | 词中间命中 |
| 200+ / 260+ | 首字母串里命中 / 首字母子序列 |
| 400+ | 每段都从某个词的词头开始（`stdsurf`） |
| 1000+ | 任意子序列，兜底 |

**缩写档故意排在"词中命中"前面**：打 `ass` 时 aiStandardSurface 排第一，名字里碰巧含 "ass" 的节点排在后面。
空格是"与"，各段分数相加。

**`_CreatorUsage`：收藏 / 常用**

```python
class _CreatorUsage(object):
    FREQUENT_LIMIT = 8
    KEEP = 300
    def record(self, key): ...           # 用了一次：次数 +1，记时间
    def toggleFavourite(self, key): ...  # 右键收藏 / 取消
    def frequent(self, limit=None, exclude=()): ...
```

记录存成 JSON（`$GAFFER_NETWORK_EDITOR_STATE_DIR/nodeCreator.json`），根层最上面显示"★ 收藏"和"常用"两节。
存盘先写临时文件再 `os.replace` 改名，写一半被打断也不会留坏文件；读不出来就当空的，面板不能因为这个文件出错。
文件比内存里那份新就重读，同时开着几个 Gaffer 时收藏能互通。测试一律用 `setCreatorUsage()` 指到临时目录。

**建节点命令为什么要拆开**

原生 `NodeMenu.nodeCreatorWrapper` 里有一句 `assert menu.ancestor( GafferUI.GraphEditor ) is not None`，
逼着调用方用挂在 GraphEditor 底下的菜单。面板不是菜单，所以用 `_unwrapNodeCreator` 取出创建函数自己跑
（自动连接、摆位仍用原生的）。拆不出来的（Box / Backdrop / Reference 那几个，创建函数自己要 `menu`）
走 `NetworkEditor.__createWithCommand`：现造一个**不弹出来的** `GafferUI.Menu`，把它的 popup parent
指到宿主上（宿主是谁见 [5.12](#512-editorpy--总控)）。

**面板本体：一列一个窗口**

```python
class _ColumnWindow(QtWidgets.QWidget):
    def __init__(self, panel, listWidget):
        QtWidgets.QWidget.__init__(self, panel, QtCore.Qt.Popup)
        self.setMouseTracking(True)
```

第一列在根窗口 `_NodeCreatorPopup` 里，往后每一列各自一个窗口，原生 QMenu 也是每一级一个窗口。
一个大框装所有列的话高度两头不讨好：跟着最长那列变就"展开一级长高一次"，定死就"条目少时一片留白"。

窗口必须是 `Qt.Popup`。`Qt.Tool` / `Qt.ToolTip` 会被当成"点在 popup 外"，第一下点击就关掉整个面板。
代价是**鼠标事件只发给最上面那个 popup**，所以有 `_routeMouse`：

```python
def _routeMouse(self, kind, globalPosition, button=QtCore.Qt.LeftButton):
    if button == QtCore.Qt.RightButton:  → 收藏 / 取消，不关面板
    if self.__scrollDrag is not None:    → 正在拖某列的滚动条，全部转发给它
    column, listItem = self.__columnAt(globalPosition)     # 按全局坐标自己找列
    if column is None:
        落在滚动条上 → __forwardToScrollBar（现造 QMouseEvent 直接 sendEvent）
        真的点在所有窗口外面 → 关面板
    if kind == "move":      self.__hovered(column, listItem)
    elif kind == "release": self.__activated(column, listItem)
```

`_routeWheel` 同理：滚轮发给光标底下的控件，不派发的话只有压在列表上才滚得动。
窗口不开 `setMouseTracking(True)` 就收不到"没按键的移动"，鼠标划回左边那些列没反应。

**`_CreatorDelegate`：每一行怎么画**

`QStyledItemDelegate` 是 Qt 里自定义列表每一行外观的标准做法。要点：

- **只认"当前行"这一种高亮，不画 `State_MouseOver`**：一列一个窗口之后，不在最上层的列收不到真鼠标事件，
  Qt 内部的 hover 状态会停在最后划过的那一行清不掉。悬停高亮靠 `__hovered()` 里 `setCurrentItem()`；
- 名字和右侧层级信息**先分宽度再各自截断**（`_splitRowWidths`：名字优先，右侧拿剩下的、最多
  `ROW_RIGHT_MAX_WIDTH`，剩得太少整块不画；右侧用 `ElideLeft` 截头留尾）。两块文字各自往同一个矩形里
  `drawText`，迟早叠在一起；
- 画 1 像素分隔线前关掉抗锯齿，否则线会淡到看不见；
- 勾选型条目在名字左边留白处画 `✓`，收藏的条目名字后面画 `★`。

**数据挂在行上**：`listItem.setData(QtCore.Qt.UserRole + n, ...)`，`UserRole` 是 Qt 留给自定义数据的起点。
`+0` 菜单条目对象、`+1` 右侧小字、`+2` 是不是分类、`+3` 是不是分节标题、`+4` 灰掉、`+5` 收藏 / 常用的身份键、
`+6` 收藏了没、`+7` 勾选状态。

**布局规矩**

| 规矩 | 原因 |
| --- | --- |
| 每列固定大小（列宽 × 自己的行数 × 行高）+ 靠上排 | 否则布局会把左边的列一起拉高 |
| 列宽跟内容走（`__columnContentWidth`，有上下限） | 长名字不截断 |
| 子列对着"展开它的那一行"弹（`__addColumn(path, anchorRow)`） | 越深越对不上 |
| 标题里不写当前层级 | 从无到有会把整块面板下移一行 |
| 新开的列不预选（`setCurrentRow(-1)`），搜索过才预选第一条 | 鼠标还没进来第一行就亮着，像残留 |
| 一条 tooltip 都不挂 | 面板是扫着找的，提示一个接一个冒出来会糊住下面几行 |
| 只有一个顶层分类、条目又不多时才平铺（`PANEL_FLAT_LIMIT`） | 多分组的菜单照分组分列 |

```python
def _screenAt(position):
    if QtWidgets.QApplication.instance() is None:
        return None
    return QtWidgets.QApplication.screenAt(position)
```

⚠️ 别写成 `QtGui.QGuiApplication`：Qt.py 这层兼容壳里没有它。`_clampToRect` 在问不出是哪块屏时**原样返回**，
夹到一块猜的屏上比不夹危险（多显示器下面板会被拽回主屏）。

**勾选型条目**：原生 `Menu` 对勾选型条目把"点完之后"的状态塞进命令的第一个位置参数
（命令自己声明 `checkBox` 参数时走关键字）。面板照做（`NetworkEditor.__invokeMenuItem`），
否则那类命令一调就 `TypeError`。

### 5.12 `editor.py` — 总控

唯一知道全局的地方：拿着 script、拿着所有 item、听所有信号、指挥所有更新。

**`NetworkEditor.__init__`**

```python
def __init__(self, scriptNode, **kw):
    root = QtWidgets.QWidget()
    root.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    root.setStyleSheet("background-color: %s;" % _backgroundColor)
    GafferUI.Editor.__init__(self, GafferUI.Widget(root), scriptNode, **kw)

    self.__initState(scriptNode)       # 所有实例变量一次列清楚
    self.__buildWidgets(root)          # 工具条 + scene + view
    self.__connectScript(scriptNode)   # 接信号
    self.__announceInstance()          # 把自己当成 GraphEditor 宣布出去
    self.__rebuild()                   # 画第一遍
```

`**kw` = 剩下的关键字参数原样传给父类。裸 `QWidget` 要包一层 `GafferUI.Widget` 再交给 `Editor`。

`__initState` 里有四十多个 `self.__xxx = ...`，全部集中在一处：这个类有哪些状态一眼看得完，
不会出现"只在某个分支里才存在的属性"（别处一问就 AttributeError）。

**信号 → 标脏 → idle 重建（全项目最重要的机制）**

```python
def __scheduleUpdate(self):
    if self.__idleScheduled:
        return                       # 一轮里挂一次就够
    self.__idleScheduled = True
    GafferUI.EventLoop.addIdleCallback(
        Gaffer.WeakMethod(self.__idleUpdate, fallbackResult=False))
```

**绝不能在信号处理里同步重建 UI**。原生 GraphEditor 每帧渲染前会写 `__uiPosition` → 发 `childAdded` →
同步重建 → 重建又触发渲染 → 事件循环永远空不下来，CPU 100%、内存一路涨。只开一个编辑器不一定触发，开两个必然触发。
所以信号里**只标记哪里脏了**，挂一个一次性 idle 回调，事件循环空下来再统一处理。

脏标记从粗到细：

```python
self.__structureDirty      # 节点增删改名 → 节点集合要比对
self.__dirtyItems          # 这些节点的卡片要重建
self.__dirtyEdges          # 这些节点作为目的地的入边要重收
self.__dirtyPositions      # 这些节点的 __uiPosition 变了，只挪它们
self.__selectionDirty
```

| 信号 | 标什么 |
| --- | --- |
| 当前层的 `childAddedSignal` / `childRemovedSignal`（只认节点） | `__structureDirty` |
| `nameChangedSignal` | `__structureDirty` + 那一个 item |
| `plugInputChangedSignal` | 目的地节点的 `__dirtyEdges`；`enabled` 接上 / 拔掉驱动时也标 item |
| `plugSetSignal`（`__uiPosition`） | `__dirtyPositions` |
| `plugSetSignal`（折叠、`__uiBound`、Backdrop 标题等、节点自己的 `enabled`） | 那个 item |
| `Metadata.nodeValueChangedSignal` | 那个 item（先过 `rebuildOnNodeMetadata`） |
| `Metadata.plugValueChangedSignal` | 那个 item（先过 `rebuildOnPlugMetadata`） |
| 插口的 `childAdded` / `childRemoved`（ArrayPlug 长一路 / 少一路） | 那个 item |
| `errorSignal` | 先 `executeOnUIThread` 回 UI 线程，再在卡片上画错误角标（计算线程发的信号不能直接碰 Qt） |

插口的 `childAdded` 只连在**可能长出子插口**的插口上（`plugMayGrowChildren`：ArrayPlug、CompoundDataPlug 之类），
大图上逐个连所有插口太贵。

`__idleUpdate` 里两条守卫：

```python
if not self.__viewAlive():
    return False                     # 编辑器已被拆掉：Qt 那边的视图销毁了，回调还会再响一次
if self.__view.interacting() and QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton:
    self.__updatePostponed = True
    return False                     # 拖动期间不重建
```

**拖动期间绝不重建**：重建把 item 删了重做，Qt 的隐式鼠标抓取跟着丢，这一下拖动静默失效（"拖了但节点没动"）。
松手时 `_flushPostponedUpdate()` 补上。判据要**同时**看模式标记和真实按键状态，只看模式标记的话，
万一哪条路松手没走到，重建会被永久冻住。

`__viewAlive()` 真去碰一下 `self.__view.viewport()`：Python 属性还指着壳，`is not None` 判不出 C++ 对象是否已销毁。

**增量更新：三条路**（`__applyGraphChanges`）

1. **只有几根线变了**（最常见）→ `__applyEdgeChangesOnly()`：全图一个节点都不扫，只重收那几个节点的入边；
2. **节点集合变了 / 有 item 要重建** → 按名字比对：只删该删的、只建该建的，然后边整体对一遍（`__syncEdges`）；
3. **当前层没了 / 第一次** → `__rebuild()`：`scene.clear()` 全部重来。

全量重建慢，大头花在逐个建 `_NodeItem`（每个都要问原生 gadget 要尺寸、圆点、`+`）。
走第 1 条路时，改一根线的耗时和图有多大基本无关。

第 1 条路里有一道核对：

```python
if _noduleSignature(noduleLayout(node)) != _noduleSignature(item._nodules):
    self.__dirtyItems.add(name)
    return False              # 接口真的变了 → 退回第 2 条路
```

NameSwitch / Collect 那种 ArrayPlug 是"丢一根线上去自动长一路"，只发 `plugInputChangedSignal`，不核对的话卡片上少一个圆点。

第 2 条路还要检查"名字还在、节点已经换了一个"（File > Revert、Reference 重载、删掉再建同名）：
按 `isSame()` 比，换了就重建 item。

```python
self.__scene.blockSignals(True)
try:
    ...动 item...
finally:
    self.__scene.blockSignals(False)
```

动 item 期间屏蔽 scene 的信号：删掉一个选中的 item，`QGraphicsScene` 会发 `selectionChanged`，
被当成"手动改了选择"写回 script，选择就丢了。

收尾 `__finishUpdate(structural, created)` 里每项都要扫全图，所以按需做：`structural` 才更新场景矩形和面包屑
（`setSceneRect` 会让整个视口失效，没变就别设），`created` 才补选择和 focus 状态。

**focus 之后谁"参与计算"**

```python
def __contextTracker(self):
    self.__tracker = GafferUI.ContextTracker.acquireForFocus(self.scriptNode())
    self.__trackerConnection = self.__tracker.changedSignal().connect(...)
```

原生的做法是**把不参与的变暗**。"参与"的集合**只有 `ContextTracker` 算得对**：它只算 focus 的上游，
而且只算当前 context 真正走到的那条路（Switch 没选中的那支不算）。自己写 BFS 找上下游必然不对。
连线看的是**目标插口**（`tracker.isTracked(edge.dstPlug)`），和原生一致。

它是异步的：

```python
if tracker.updatePending():
    return          # 还在算，什么都别动
```

不加的话刚设 focus 那一下它还没算完，`isTracked()` 全是 False，整张图先刷暗一帧再亮回来，看着就是"点 focus 会闪一下"。

**拖放（四条信号，不接就没反应）**

```python
self.dragEnterSignal().connect(...)
self.dragMoveSignal().connect(...)
self.dragLeaveSignal().connect(...)
self.dropSignal().connect(...)
```

GafferUI 的拖放不走 Qt 的 `QDrag`，是它自己按鼠标位置找目标控件、发这四条信号。

| 拖进来的 | 怎么处理 |
| --- | --- |
| 场景路径（从 Viewer / HierarchyView 拖） | 落在节点上 → 转发给原生 NodeGadget 的信号（`PathFilterUI` 等早已挂好处理函数）；落在空白 → 建 PathFilter，单条路径则跳到生成它的节点 |
| 节点 | 揭示 / 跳过去 |
| 文件 | 建对应的读取节点，整批一步撤销 |

往外拖（中键按住节点拖给别的编辑器）走 `dragBeginSignal`，还要 `__installDragSourceFilter()` 把 GafferUI 的全局过滤器装到视图上。
中键按在节点上是拖出去，按在空白处才是平移，和原生分得一样。

**拖动吸附**（`_snapNodePosition`，被 `_NodeItem.itemChange` 回调）

- 只在拖单个节点时生效；
- `__snapReference` 只看 `SNAP_RANGE` 内的节点，在里面挑"横平或竖直能对上"（差 `SNAP_DISTANCE` 以内）的**最近那一个**；
- **只吸一个轴**：`|dx| <= |dy|` 就吸 x 成竖列，否则吸 y 成横行，另一个轴保持自由；
- 参考线（`__snapGuide`）只画在两个节点之间，由 `view.drawForeground` 画。

按全图分别找 x 最近和 y 最近的做法不行：两个轴可能来自两个不同的节点，而且不看距离，大图上会被视野外的节点拽走。

**借原生的右键菜单**

```python
def _showContextMenu(self, nodeItem, edgeItem, globalPosition, scenePosition, plug=None):
    空白     → _popupNodeMenu（建节点面板）
    圆点     → __popupPlugMenu
    连线     → __popupEdgeMenu
    节点     → __popupNodeMenuFor
```

三套菜单（节点 / 插口 / 连线）的内容全部向原生要：`__appendNativeNodeMenu` / `__appendNativePlugMenu` /
`__appendNativeConnectionMenu` 发原生 GraphEditor 的那几个菜单信号，让 Gaffer 和各插件往菜单里加条目。
这些信号的第一个参数要一个 GraphEditor，`__menuHost()` 给：

```python
def __menuHost(self):
    if isinstance(self, GafferUI.GraphEditor):
        return self                 # 接管装上之后我们自己就算
    return self.__engine()          # 否则借隐藏的原生 GraphEditor
```

原生那几个信号访问器类上和实例上各有一份，弹菜单时两份都发（`_contextMenuSignals`）。
`NetworkEditor` 自己也提供 `plugContextMenuSignal()` / `connectionContextMenuSignal()` / `nodeContextMenuSignal(multiNode=False)`，
签名照原生，往实例上连菜单的 Gaffer 组件因此也能连到我们身上。
`__appendOwnNodeMenu` 补上原生由 GraphEditor 自己提供的那几条（Focus、Enabled、Bookmarked、Connections …），措辞照抄原生。

一处就地改写：原生节点菜单里的 `Show Contents...` 会往布局里塞一个原生 GraphEditor（没有就现建一个）。
`__redirectShowContents()` 把它换成本编辑器的进层级（`_enterNode`），位置和标签都不动：

```python
definition.remove(target)
if following is not None:
    definition.insertBefore(target, item, following)     # 保住原来的位置
else:
    definition.append(target, item)
```

用 `insertBefore`，因为 `append` 同名条目会被挪到菜单末尾。

**建节点流程**

1. 按 Tab → `_popupNodeMenu()`
2. `__nodeMenuEntries()` 把原生 `NodeMenu` 的定义摊平成条目
3. `_showPanel(...)` 用面板显示，选中一条 → `__invokeMenuItem`
4. 是建节点命令 → `__createFromMenuItem()`：
   - `_unwrapNodeCreator()` 拆得出创建函数 → 在一个 UndoScope 里建节点、应用用户默认值、加进当前层、
     原生 `StandardGraphLayout.connectNode()` 自动接到选中的节点上；然后 `positionNode()` 摆位（和原生一样不进撤销）；
   - 拆不出来 → `__createWithCommand()` 现造一个不弹出的菜单当参数，临时把宿主的 `frame` 换成空函数
     （原生包装最后会 `frame` 新节点，拽走正在看的视野）；
5. `__finishNodeCreation()` 检查新节点位置是不是有限数，没连线的摆到鼠标位置。

**接管 `GafferUI.GraphEditor`**（文件末尾）

```python
class _GraphEditorTakeoverMeta(type):
    def __instancecheck__(cls, instance):
        return isinstance(instance, (NetworkEditor, _nativeGraphEditorClass()))
    def __subclasscheck__(cls, subclass): ...
    def __getattr__(cls, name):
        return getattr(_nativeGraphEditorClass(), name)     # 类属性一律转给原生
    def __call__(cls, *args, **kw):
        return _nativeGraphEditorClass()(*args, **kw)       # 构造仍然构造原生的

class _GraphEditorProxy(metaclass=_GraphEditorTakeoverMeta):
    @staticmethod
    def acquire(rootNode):
        ...优先落到布局里现成的 NetworkEditor 上...
```

元类是"类的类"，能改写类本身的行为。这里改了四样：

| 改什么 | 效果 |
| --- | --- |
| `__instancecheck__` | `isinstance(我们, GafferUI.GraphEditor)` 为 **True** |
| `__getattr__` | 类属性（那些信号）一律转给原生类：启动脚本里的 `connect()` 早挂在原生类上，必须是同一个对象 |
| `__call__` | 构造仍然构造原生的：存过的布局里写死的就是这一句，换掉会让旧布局悄悄变样 |
| `acquire` | 优先用布局里现成的 NetworkEditor |

安装就是一句替换：

```python
def installGraphEditorTakeover(force=False):
    global _nativeGraphEditor
    ...
    _nativeGraphEditor = native                 # 先把真的存起来
    GafferUI.GraphEditor = _GraphEditorProxy    # 再换成壳
```

换来的好处：菜单栏的剪切 / 复制 / 粘贴（`EditMenu.scope()` 靠 `isinstance` 找 GraphEditor 决定作用在哪一层）、
书签跳转、`Ctrl+F` 找节点、Show Contents 都落到本编辑器上；原生编辑器不受影响，`uninstallGraphEditorTakeover()` 随时切回。

因为 `isinstance` 成立，本编辑器还能**自己当自己的宿主**：

```python
def __announceInstance(self):
    if not isinstance(self, GafferUI.GraphEditor):
        return
    GafferUI.GraphEditor.instanceCreatedSignal()(self)
```

工作室或管线常把自己的快捷键（比如弹出切换菜单的单键）注册在 `GraphEditor.instanceCreatedSignal` 上，
处理函数会连到编辑器的 `keyPressSignal`。主动发一次，那些处理函数就直接连到本编辑器上。
`_forwardShortcutKey()` 先发给自己；没人要、而且确实有隐藏引擎时才转给引擎。
`__emitKeyPress()` 在发信号期间临时替换 `GafferUI.Menu.popup`，把处理函数想弹的菜单截下来用面板显示。

所以接管装上之后，默认**一个原生 GraphEditor 实例都不建**（`engineEnabled()` 返回 False）。
接管被关掉时 `isinstance` 不成立，才需要隐藏引擎 `__engine()` 当宿主。

**`_GadgetWidgetShim`：冒充原生 `GadgetWidget` 的壳**

原生菜单命令只碰它三样东西：

```python
class _GadgetWidgetShim(object):
    def getViewportGadget(self): ...    # 问"这个像素是图里哪个点"
    def bound(self): ...                # 编辑器在屏幕上占哪块（菜单定位、粘贴位置要）
    def size(self): ...
```

`graphGadgetWidget()` 返回它。故意不做成 `GafferUI.Widget`（`Widget.__init__` 会把被包的 QWidget 登记进全局表），
鸭子类型就够：Python 只看有没有这几个方法。

配套的 `_syncedViewport()` 是一个"只算不画"的独立 `ViewportGadget`，每次用之前把视口尺寸和取景同步成
"本编辑器现在看到的那块"（`__syncViewportGadget`）。几条性质：

1. 默认是 2D 相机，默认视口 640×480，不设就按它算；
2. `frame(box)` 把整个框装进视口；
3. 改视口尺寸不会自动重新取景，所以每次用前都同步；
4. raster 坐标 y 向下，gadget 坐标 y 向上。

⚠️ **一个 gadget 只有一个父**，挂给第二个 `ViewportGadget` 会把它从原来那个上抢走。所以取景器只挂本编辑器自己的
裸 `GraphGadget`（`__ownGraphGadget`），绝不碰借来的原生编辑器的 gadget。`graphGadget()` 也返回这个裸 gadget，
并连着它的 `rootChangedSignal`：别的代码对它 `setRoot()`，视图跟着换层。

**`__getattr__` 诊断钩子**

```python
def __getattr__(self, name):
    if not name.startswith("_"):
        IECore.msg(IECore.Msg.Level.Debug, "NetworkEditor",
                   "Something asked for '%s', which this editor does not implement ..." % name)
    raise AttributeError(name)
```

`__getattr__` 只在"找不到这个属性"时才被调用。把日志级别调到 Debug、把常用菜单都点一遍，
缺哪个 GraphEditor API 一目了然。

**其余公开接口**：`getRootNode()` / `setRootNode()`（换层时记住每一层的视野，回来时恢复）、`frame(nodes, extend=False)`、
`getWireStyle()` / `setWireStyle()`、`getVisibleAnnotations()` / `setVisibleAnnotations()`、`getSnapEnabled()` / `setSnapEnabled()`、
`isPanelMaximised()`（照 `CompoundEditor` 空格最大化的判据）、`readOnly()`、`graphView()`。

---

## 6. tests/

| 文件 | 怎么跑 | 测什么 |
| --- | --- | --- |
| `test_network_editor.py` | 无头 | 数据层 + UI + 编辑操作，主测试 |
| `test_optimizations.py` | 无头 | 几何缓存、一次鼠标移动只查一次场景、手势互斥、位置更新只动脏节点等专项 |
| `test_review_v070.py` | 无头 | 菜单条目求值、收藏跨会话、Revert 后 item 换绑、计算线程报错、粘贴位置等专项 |
| `e2e_network_editor.py` | `gaffer screengrab -commandFile` | 真 Gaffer GUI 里、需要 GL 上下文的功能 |
| `e2e_show_contents.py` | `gaffer screengrab -commandFile` | 借原生右键菜单那条真实路径 |
| `e2e_panel_input.py` | 真显示器 + xdotool | 只有真屏幕、真鼠标、真键盘测得出来的事 |
| `bench_layout.py` | 无头 | 自动排列对照台（只量数据，不判通过与否） |
| `*.gfr` | — | 测试夹具，测试用 `NE.packageRoot()` 找到它们 |

无头测试自己会把仓库的 `python/` 插进 `sys.path`。测试写法很朴素：

```python
def check(name, condition, detail=""):
    if condition:
        _passed.append(name)
    else:
        _failed.append("%s  %s" % (name, detail))
        print("FAIL  %s  %s" % (name, detail))
...
sys.exit(1 if _failed else 0)
```

不用 pytest 之类的框架，因为要在 Gaffer 自己的 Python 里跑。

`test_network_editor.py` 里 P 键那一节：环境变量 `PARAMETER_EDITOR_PYTHON` 指向 `parameterEditor`
扩展的 `python/` 目录时连参数面板一起测，不设时只验「没装时 P 键什么都不弹」。

**为什么需要真输入测试**：合成事件（代码里造一个 `QMouseEvent` 发出去）测不出三件事：

1. 嵌套 popup 下的事件派发（真鼠标才走那条路）；
2. 平移 / 缩放留不留残迹（`grab()` 永远重新渲染一遍，看不到屏幕上真正显示的内容，要 `screen.grabWindow()`
   抓屏幕再和强制重绘逐像素比）；
3. X11 的按键自动重复。

**`bench_layout.py`**：一批造出来的图加 `tests/` 里的 `.gfr`，× 若干种"分层 / 定序 / 定位 / 主干"组合各排一遍，
量交叉数、连线总长、逆流、长边直不直、主干直不直、输入口顺序有没有被打乱、重叠、耗时，原生 `StandardGraphLayout`
一起跑当参照。`NE_BENCH_COMBOS=all` 跑全矩阵，`NE_BENCH_OUT=<路径>` 指定报告位置。换算法之前先跑一遍。

几条测试自己的坑：

- 无头跑带 `QT_QPA_PLATFORM=offscreen`，否则 `Qt.Popup` 的 `isVisible()` 在真 X11 下不稳；
- screengrab 执行 commandFile 时 `__name__ == "builtins"`，不能加 `if __name__ == "__main__":` 守卫，否则静默不执行；
- 截图测试和对照台都是**跑完才一次性写报告**：中途抛异常就不写，留着的旧报告很容易被当成"改了没生效"。
  跑之前先删旧报告，别把 stderr 丢进 `/dev/null`；
- 往 e2e 里插断言，要插在它引用的变量**定义之后**；commandFile 是一整个模块作用域，循环变量会覆盖前面同名的变量；
- `e2e_panel_input.py` 的"平移不留残迹"比的是真屏幕抓图，别的窗口盖上来就会失败，失败先原样重跑一次。

---

## 7. 贯穿全局的几个概念

### 7.1 坐标：三套系统

| 换算 | 怎么换 |
| --- | --- |
| Gaffer 单位 → 场景坐标 | × `PX_PER_UNIT`，y 取反 |
| 场景坐标 ↔ 视图像素 | `view.mapToScene()` / `view.mapFromScene()` |
| item 局部坐标 ↔ 场景坐标 | `item.mapToScene()` / `item.mapFromScene()` |

看变量名判断在哪一套里：`position`（多为 Gaffer 单位或视图像素，看上下文）、`scenePosition`、`localPosition`、
`globalPosition`（屏幕全局）。**y 轴取反只在 Gaffer 单位和场景坐标之间发生一次**，其余都是 Qt 的 y 向下。

### 7.2 元数据是外观的唯一来源

节点颜色、圆点颜色、插口挂在哪条边、节点画成胶囊形、某一栏收起来了，全是元数据。好处是别处注册的配色自动生效；
代价是要听 `Metadata.nodeValueChangedSignal` / `plugValueChangedSignal` 才能在改动后刷新，
并用 `rebuildOnNodeMetadata` / `rebuildOnPlugMetadata` 过滤。

⚠️ `Gaffer.Metadata.value()` 会把 `IECore.BoolData` 解包成 Python `bool`，读出来直接当 bool 用，
写 `isinstance(data, IECore.BoolData)` 永远是 False。

### 7.3 信号 → 标脏 → idle 重建

见 [5.12](#512-editorpy--总控)。任何信号处理函数里都不许同步重建 UI。

### 7.4 三层"借原生"

| 层 | 是什么 | 开销 | 现在用不用 |
| --- | --- | --- | --- |
| L1 隐藏 GraphEditor | 一个真的原生编辑器，不显示 | 贵（真建一个 OpenGL 控件） | 默认不建，接管之后本编辑器自己就是宿主 |
| L2 裸 GraphGadget | 只有图内容，没有窗口、不要 GL | 几乎为零 | 一直用（尺寸、圆点位置、自动摆位） |
| L3 菜单内容 + 元数据 | 纯数据 | 免费 | 一直用 |

代码里 `__engine()` 是 L1，`__graphGadget()` / `__ownGraphGadget()` 是 L2，别搞混。

### 7.5 命中测试的通用套路

凡是画在卡片外面的东西（`+`、focus 角标、侧边标签、折叠三角、Backdrop 边），命中都要在光标周围取一小块再找一遍：

```python
probe = QtCore.QRect(position.x() - 14, position.y() - 14, 28, 28)
for candidate in self.items(probe):
    ...
```

`shape()` 里要加多个互相重叠的矩形时，先 `setFillRule(QtCore.Qt.WindingFill)`。

### 7.6 Gaffer Python 绑定的通用坑

1. 包装对象没有稳定身份：`a is b` 不可靠，用 `a.isSame(b)` 或比名字；
2. 信号形参个数必须严格匹配，多一个参数回调会静默失效；
3. `imath.Box2f` 的 `min` / `max` 是方法，要写 `box.min()`；
4. 勾选型菜单项的命令会多收一个勾选状态参数，命令签名要用 `*unused` 兜住。

---

## 8. 跟着走三遍：一次操作在代码里怎么流动

### 8.1 从一个圆点拖一根线到另一个节点

1. `view.mousePressEvent` → `__leftPress` → `noduleAt()` 命中一个圆点 → `__pressNodule`：
   圆点已经连着线就 `__beginReconnect`（藏起旧线，攥着另一头），否则 `__beginConnect`；
   模式变成 `_MODE_CONNECT`，建一个临时的连线 item。
2. `view.mouseMoveEvent`（每一帧）→ `__updateConnectWire`：
   - `__dragDestination()` 照原生 `closestDragDestination`：光标落在某个节点上（卡片外 `CONNECT_REACH` 以内也算）
     就在它身上挑一个最近的、接得上的插口；
   - `__withinSnapDistance()`：只有真靠近圆点（`CONNECT_SNAP_DISTANCE`）才把线吸过去，否则线继续跟着鼠标；
   - 压在 `+` 上就点亮 `+`；
   - `_wirePath()` 重算路径。
3. `view.mouseReleaseEvent` → `__endConnect`：
   - 丢在 `+` 上（而且光标没压着圆点）→ `editor._createPromotedConnection()`：
     还没 setup 的 Switch / NameSwitch / BoxIO 走 `__setupFromAdder()`；Box 建 BoxIn / BoxOut 并提升；
     材质弹面板挑隐藏参数（`__connectToHiddenPlug`）；ArrayPlug 照原生 `resize(n + 1)` 长一路（`__growArrayPlug`）；
   - 丢在空白 → 改接时断开旧线，否则什么都不做；
   - 丢在节点上 → `editor._createConnection()` → `plug.setInput()`（改接时断旧接新在同一步撤销里）。
4. Gaffer 发 `plugInputChangedSignal` → `editor.__plugInputChanged` → `__dirtyEdges.add(目的地节点名)` → `__scheduleUpdate()`。
5. 事件循环空闲 → `__idleUpdate` → `__applyGraphChanges` → `__applyEdgeChangesOnly` → 只重收那一个节点的入边 → 建一个 `_EdgeItem`。

### 8.2 按 Tab 建一个节点

1. `view.keyPressEvent` → `__handleKey` → `Key_Tab` → `editor._popupNodeMenu(光标位置)`。
2. `__nodeMenuEntries()` 把原生 `NodeMenu` 的定义摊平成条目。
3. `_showPanel(...)` → `_NodeCreatorPopup.setEntries()` → `popupAt()`，根层最上面插入"★ 收藏"和"常用"。
4. 打字 → `__searchChanged` → `__searchRows` → 每条算 `_matchScore()` → 排序。
5. 回车 → `__activated` → `usage.record(key)` → 面板关闭 → 回调 `__invokeMenuItem`。
6. `editor.__createFromMenuItem`：拆出创建函数 → 建节点、加进当前层 → `connectNode()` 自动接上 → `positionNode()` 摆位。
7. `childAdded` 信号 → `__structureDirty` → idle → `__applyGraphChanges` → 建一个 `_NodeItem`。

### 8.3 拖动一个节点

1. `mousePressEvent` → `__pressItem` → `_selectClicked`（选择规则照原生）→ 模式 `_MODE_MOVE`。
2. Qt 自己挪 item，每挪一次触发 `itemChange(ItemPositionChange)` → `editor._snapNodePosition()` 返回吸附后的位置，
   顺手更新参考线，`view.drawForeground` 画出来。
3. `itemChange(ItemPositionHasChanged)` → `editor._nodeItemMoved()`：只更新这个节点自己那几条线的几何。
4. `mouseMoveEvent` 末尾 → `_updateInsertCandidate()`：压在某根线上就把它点亮成金色（松手塞进去）。
5. `mouseReleaseEvent`：
   - `_clearSnapGuides()`；
   - `_commitDrag()`：在一个 UndoScope 里 `_commitNodePositions()`（位置这时才写回 `__uiPosition`，只看选中的 item，
     Backdrop 减掉 `centerOffset()`）+ `_applyInsertCandidate()`（塞进连线）；
   - `_flushSelectionToScript()`：选择这时才写回；
   - `_flushPostponedUpdate()`：拖动期间攒下的重建现在补上。

拖动过程中**不写回 Gaffer**，松手才写。中途写的话每一帧都产生一个撤销步骤，参数面板也跟着刷新，非常卡。

---

## 9. 想改点东西，从哪下手

| 想干什么 | 改哪 |
| --- | --- |
| 配色 / 圆角 / 字号 | `constants.py` |
| 手感阈值（吸附距离、LOD 门槛、吸附范围） | `constants.py` |
| 加一种节点类型图标 | `graph.py` 加 `GLYPH_*` 常量并在 `nodeGlyph()` / `shaderGlyph()` 里加判据；`qt.py` 写一个画图函数，往 `_GLYPH_PAINTERS` 加一行 |
| 连线形状 | `edge_item.py` 的 `_wirePath()` / `_houdiniWirePoints()`；对拍数据在 `tests/houdini_rounded_wire.json` |
| 加快捷键 | `view.py` 的 `__handleKey()`；会和菜单栏冲突的，还要加进 `__overrideKeys` |
| 加一条右键菜单 | `editor.py` 的 `__appendOwnNodeMenu()`（措辞照抄原生） |
| 自动排列 | `layout.py`；间距常量在文件顶部，换算法走 `LAYOUT_STRATEGY`，换之前先跑 `tests/bench_layout.py` |
| 卡片上画的东西 | `node_item.py` 的某个 `__paint…()`；**同步检查 `__computeBoundingRect()`** |
| 新增"什么变了要重画" | `graph.py` 的 `rebuildOnNodeMetadata` / `rebuildOnPlugMetadata`，或 `editor.py` 里多连一条信号 |

### 改完要跑的命令

以下命令在装好 Gaffer 1.7 的环境里、仓库根目录下执行（`gaffer` 指 Gaffer 的启动脚本）。

```bash
# 1. 无头（最快，改数据层 / 逻辑必跑）
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_network_editor.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_optimizations.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_review_v070.py

# 2. 格式（整个包按 black 排过）
black --check --line-length 88 python

# 3. 真 GUI 截图测试（改了画法必跑），报告写 /tmp/network_editor_e2e.txt
GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:$PWD" \
    gaffer screengrab -commandFile tests/e2e_network_editor.py -image /tmp/out.png

# 4. 真输入（改了面板 / 输入 / 视口更新方式必跑，需要真显示器和 xdotool）
DISPLAY=:0 gaffer env python tests/e2e_panel_input.py

# 附：改了自动排列，跑对照台看指标有没有变差
QT_QPA_PLATFORM=offscreen gaffer env python tests/bench_layout.py
```

### 实际操作上的提醒

1. **改了 Python 要重启 Gaffer**，"改了没生效"先查这条。
2. **命名风格用 camelCase**：大量方法是 Qt 虚函数覆写（`paint`、`shape`、`mousePressEvent`…，名字由 Qt 定），
   还有一批要和 Gaffer API 保持一致。PEP 8 本身也允许沿用已有的主流风格。格式统一交给 `black`。
3. **注释里带 ⚠️ 的都是踩过的坑**，删代码前先读那段注释。

---

## 10. 术语表

| 词 | 解释 |
| --- | --- |
| **adder（`+`）** | 卡片边上的加号，原生叫 PlugAdder。三种作用：Box 提升插口 / Switch 类节点加一路 / 材质显示一个藏起来的参数 |
| **auxiliary connection** | 辅助连线，画成虚线。两端至少一头没有圆点的连接（典型是 Expression 驱动别的节点） |
| **backdrop** | 图上半透明的大框，用来给节点分组 |
| **ContextTracker** | 原生对象，回答"focus 这个节点时，哪些节点 / 插口真的参与了计算" |
| **crumbs（面包屑）** | 工具条上那行 `script › myBox › innerBox` |
| **engine（引擎）** | 隐藏的原生 GraphEditor，只在接管关掉时用来当原生菜单命令的宿主 |
| **focus** | Gaffer 的"当前关注节点"，Viewer 显示的就是它。这里画成卡片右上角的金色折角 |
| **gadget** | 原生 OpenGL 界面里的零件 |
| **item** | Qt 画布上的东西（`_NodeItem` / `_EdgeItem` / `_BackdropItem`） |
| **LOD** | 缩放级别，拉远了画得简单 |
| **minimised（折叠）** | 原生右键 `Connections/Show Input…`，把连线收成一个小尾巴 |
| **nodule** | 插口画在卡片边上的小圆点 |
| **rank（层）** | 自动排列里的"第几层" |
| **section** | 两个意思：①插口挂在卡片的哪条边（top / bottom / left / right）；②材质节点侧边的参数分栏 |
| **shim** | 冒充某个东西的一层壳，这里指 `_GadgetWidgetShim` |
| **spine（主干）** | 自动排列里最长的那条流水线 |
| **takeover（接管）** | 把 `GafferUI.GraphEditor` 换成一个壳，让 `isinstance` 对本编辑器也成立 |
| **tangent（切线）** | 连线从圆点出去的方向 |
| **UndoScope** | `with Gaffer.UndoScope(script):` 包起来的一段操作，撤销时作为一步回退 |
