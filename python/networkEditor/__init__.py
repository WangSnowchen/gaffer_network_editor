"""networkEditor —— 另起一个 Qt 节点图编辑器（Editor 类型 "NetworkEditor"）。

目标：看起来更现代，用起来和原生没区别。

原生 GraphEditor 改不动（OpenGL + 写死的 GLSL，`Style` / `GraphGadget` /
`GraphLayout` 都不能从 Python 子类化），所以另起一个 QGraphicsScene 视图，
但**数据、几何、配色、行为全部和原生共用 / 问原生要**，两个视图可以同开互通：

    位置          `node["__uiPosition"]`（中心点，Gaffer y 向上）
    连线折叠      `__uiInput|OutputConnectionsMinimised`
    Backdrop 框   `node["__uiBound"]`
    选择 / focus  `script.selection()` / `script.getFocus()`
    尺寸 / 接口   `nodeGadget.bound()` / `nodule().transformedBound()`
    配色          `nodeGadget:color` / `nodule:color` / StandardStyle
    建节点 / 摆位 原生 `NodeMenu` + `StandardGraphLayout`（靠隐藏的 GraphEditor 当宿主）

包内**严格一层套一层、下层不回头引用上层**，所以不会有循环 import：

    constants -> graph -> layout -> qt -> backdrop_item -> node_item
              -> edge_item -> view -> panel -> editor -> register

每个模块结尾的 `__all__ = [ name for name in dir() if not name.startswith( "__" ) ]`
把**私有名字也往上传**（上层和测试用的就是 `_NodeItem` / `_matchScore` 这些）。

设计、坑位与 Gaffer 相关知识见仓库 `docs/`。
"""

import os

from .register import *


## 扩展包根目录（`.../gaffer_network_editor/0.1.0`），用来找包里的资源。
def packageRoot():

    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# `from networkEditor import *` 只给这一批；私有名字照旧是包属性
# （`networkEditor._NodeItem` 随时拿得到，测试就是这么用的）。
__all__ = [
    # 包本身
    "packageRoot",
    # 编辑器本身
    "NetworkEditor",
    "registerEditor",
    # 坐标 / 尺寸
    "PX_PER_UNIT",
    "nodeSizeUnits",
    "textWidthUnits",
    # 图与连线
    "collectNodes",
    "collectEdges",
    "Edge",
    "nodePosition",
    "setNodePosition",
    "connectionMinimised",
    # 接口（nodule）与 `+`
    "noduleLayout",
    "nodulePlug",
    "plugKey",
    "plugSection",
    "noduleLabel",
    "noduleColor",
    "plugAdders",
    "adderSetupComplete",
    "oppositeSection",
    # 外观
    "nodeShape",
    "auxiliaryLabel",
    "nodeGlyph",
    "nodeColor",
    "nodeAccentColor",
    "cardColor",
    "wireColor",
    "nodeAnnotation",
    "substituteAnnotationText",
    # 连接
    "canConnect",
    "candidatePlugs",
    "resolveInputPlug",
]
