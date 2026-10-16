"""数据层：只问 Gaffer 要数据，不碰 Qt（可无头测试）。

节点位置 / 连线折叠 / 接口布局 / `+`（PlugAdder）/ 形状与大小 / 图标 / 配色 /
启用状态 / 注释 / 连线收集（`Edge`）/ 连接合法性 —— 几何、配色、行为一律问原生要。
"""

import re
import math
import collections

import imath

import IECore
import Gaffer
import GafferUI
import GafferScene

from Qt import QtGui

from .constants import *

# 数据层（只依赖 Gaffer，不碰 Qt —— 可无头测试）


## 节点在图上的位置（**中心点**，Gaffer 单位，y 向上），没摆过返回 None。
#
# 只读路径千万不要 createIfMissing：那个 plug 是原生 GraphGadget 在 `preRender`
# 里按自动布局算完才建的，我们抢先建会把自动布局搞坏。
def nodePosition(node):

    plug = node.getChild("__uiPosition")
    if plug is None or not isinstance(plug, Gaffer.V2fPlug):
        return None

    return plug.getValue()


## 位置是不是个能用的数。
#
# 原生那些 `nodeMenuCreateCommand` 会拿弹出菜单的 raster 坐标反算图坐标，而我们借的
# 引擎是个**没显示过**的 GraphEditor，视口可能是退化的（0 尺寸）→ 换算出 nan，节点
# 就摆到「无穷远」去了（画面上直接看不见）。建完统一检一遍。
def positionUsable(position):

    return (
        position is not None and math.isfinite(position.x) and math.isfinite(position.y)
    )


## 写位置。和 `GraphGadget::nodePositionPlug( createIfMissing = true )` 一致。
# \undoable
def setNodePosition(node, position):

    plug = node.getChild("__uiPosition")
    if plug is None or not isinstance(plug, Gaffer.V2fPlug):
        plug = Gaffer.V2fPlug(
            "__uiPosition",
            Gaffer.Plug.Direction.In,
            flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic,
        )
        node.addChild(plug)

    plug.setValue(position)


def _boolPlugValue(node, name):

    plug = node.getChild(name)
    return plug.getValue() if isinstance(plug, Gaffer.BoolPlug) else False


## 节点的输入 / 输出连线是不是被折叠了（原生右键 Connections/Show Input|Output）。
# 状态存在 `__uiInputConnectionsMinimised` / `__uiOutputConnectionsMinimised` 上。
def nodeConnectionsMinimised(node, direction):

    if direction == Gaffer.Plug.Direction.In:
        return _boolPlugValue(node, "__uiInputConnectionsMinimised")
    return _boolPlugValue(node, "__uiOutputConnectionsMinimised")


## \undoable
def setNodeConnectionsMinimised(node, direction, minimised):

    name = (
        "__uiInputConnectionsMinimised"
        if direction == Gaffer.Plug.Direction.In
        else "__uiOutputConnectionsMinimised"
    )

    plug = node.getChild(name)
    if not isinstance(plug, Gaffer.BoolPlug):
        plug = Gaffer.BoolPlug(
            name,
            Gaffer.Plug.Direction.In,
            False,
            flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic,
        )
        node.addChild(plug)

    plug.setValue(minimised)


## 一条连线折不折叠。判据抄 `GraphGadget.cpp:1852`：**dst 的输入折叠了，
# 或者 src 的输出折叠了**，这条线就折叠。
def connectionMinimised(edge):

    return nodeConnectionsMinimised(
        edge.dstNode, Gaffer.Plug.Direction.In
    ) or nodeConnectionsMinimised(edge.srcNode, Gaffer.Plug.Direction.Out)


## 这个插口在 GraphEditor 上有没有 nodule（接口圆点）。
# 判据和 `Nodule.cpp` + `NoduleLayout.cpp` 对齐：`nodule:type` 为空字符串就是明确
# 隐藏，`noduleLayout:visible` 为 False 也是隐藏。不这么过滤，照着 `getInput()`
# 全画会冒出一堆原生 GraphEditor 上根本看不见的连线。
def hasNodule(plug):

    # `__` 开头的插口**原生根本不进 nodule 布局**（`NoduleLayout::layoutOrder()` 一进
    # 循环就 `boost::starts_with( name, "__" )` → continue），它下面的子插口同理。
    # Expression 的输入输出就挂在 `__in` / `__out` 里 —— 不判这条的话，表达式那些连线
    # 会被当成「两端都有 nodule」而画成**实线**，实际应该全是虚线（辅助连线）。
    current = plug
    while isinstance(current, Gaffer.Plug):
        if current.getName().startswith(_internalPlugPrefix):
            return False
        current = current.parent()

    noduleType = Gaffer.Metadata.value(plug, "nodule:type")
    if noduleType is not None and noduleType == "":
        return False

    visible = Gaffer.Metadata.value(plug, "noduleLayout:visible")
    if visible is not None and not visible:
        return False

    return True


## 插口挂在节点的哪条边。和 `NoduleLayout.cpp` 的 `section()` 一致：
# 输入默认 top、输出默认 bottom（所以 Gaffer 的图和 Houdini 一样是上→下流的）。
def plugSection(plug):

    section = Gaffer.Metadata.value(plug, "noduleLayout:section")
    if section is None:
        section = Gaffer.Metadata.value(plug, "nodeGadget:nodulePosition")

    if section:
        return section

    return "top" if plug.direction() == Gaffer.Plug.Direction.In else "bottom"


## 这个插口的 nodule 是不是「复合」的 —— 那样 nodule 画在**子插口**上，不画它自己。
# Group / Merge 之类的 ArrayPlug 就靠这个摊成一排接口
# （`GafferSceneUI/SceneProcessorUI.py:58`、`ImageProcessorUI.py:58`）。
def isCompoundNodule(plug):

    noduleType = Gaffer.Metadata.value(plug, "nodule:type")

    if noduleType == "GafferUI::CompoundNodule":
        return True

    # Color3f / V3f 右键「Expand RGB Components」后摊成 r/g/b，原生记在父插口的
    # `compoundNumericNodule:childrenVisible`（`CompoundNumericNoduleUI`）。两条实测：
    # ①**只认这个键**，别要求 `nodule:type` 也写着 CompoundNumericNodule —— Arnold
    # 材质的 `out` 压根没注册 `nodule:type`，卡着它判则菜单点了不长圆点；
    # ②**必须真的有子插口** —— 真机 .grf 会把这个键写到没有子插口的 FloatPlug 上
    # （原生对它画的是普通 StandardNodule），照旧递归会让圆点凭空少一个。
    if not len(plug.children(Gaffer.Plug)):
        return False

    if bool(Gaffer.Metadata.value(plug, "compoundNumericNodule:childrenVisible")):
        return True

    return False


## 右键「Expand RGB / Expand Components」展开的复合**数值**插口（Color3f / V3f …）。
#
# 和 `GafferUI::CompoundNodule`（Group 的 ArrayPlug、材质的 `parameters`）分开看：
# 后者把子接口当兄弟一样**摊开**排在边上，而前者原生是把子接口塞在**父接口那一格**里、
# 整组缩到 **0.75** 挤成一簇（`src/GafferUI/CompoundNumericNodule.cpp` 的
# `NoduleLayout` + `M44f().scale( V3f( 0.75 ) )`）。位置 / 大小要照它来才和原生一样。
def isExpandedCompoundNumeric(plug):

    if Gaffer.Metadata.value(plug, "nodule:type") == "GafferUI::CompoundNodule":
        return False

    return isCompoundNodule(plug)


def _collectNodules(node, parent, section, result):

    for plug in parent.children(Gaffer.Plug):

        if plug.getName().startswith(_internalPlugPrefix):
            continue
        if not hasNodule(plug):
            continue

        if node.isSame(parent):
            childSection = plugSection(plug)
            if childSection not in result:
                childSection = (
                    "top" if plug.direction() == Gaffer.Plug.Direction.In else "bottom"
                )
        else:
            # 复合 nodule 的子接口跟着父接口摆在同一条边上
            childSection = section

        if isCompoundNodule(plug):
            _collectNodules(node, plug, childSection, result)
        else:
            result[childSection].append(plug)


## 节点四条边上各有哪些 nodule，返回 { section : [ plug, ... ] }。
def noduleLayout(node):

    result = {"top": [], "bottom": [], "left": [], "right": []}
    _collectNodules(node, node, "top", result)
    return result


_customGadgetKeyPattern = re.compile(r"^noduleLayout:customGadget:([^:]+):gadgetType$")


## 一份 nodule 布局的"指纹"，用来判断接口有没有变（增量更新时对比用）。
def _noduleSignature(layout):

    # 同样**不能用 `getName()`**：NameSwitch 每一路的圆点都叫 "value"，
    # 拿它当指纹的话"接口变了"看不出来（见 `Edge.key`）。
    return tuple(
        (
            section,
            tuple(
                (
                    plug.relativeName(plug.node())
                    if plug.node() is not None
                    else plug.getName()
                )
                for plug in layout.get(section, [])
            ),
        )
        for section in ("top", "bottom", "left", "right")
    )


def _metadataAdderSections(target, defaultSection):
    """`target`（节点或插口）上按元数据注册了哪些 `+`，返回
    { section : [ ( 名字, gadgetType ) ] }。
    判据抄 `NoduleLayout.cpp` 的 `visible()` / `section()`。"""

    result = {}

    for key in Gaffer.Metadata.registeredValues(target):

        match = _customGadgetKeyPattern.match(key)
        if match is None:
            continue

        name = match.group(1)
        gadgetType = Gaffer.Metadata.value(target, key)
        if not gadgetType:
            continue  # None / "" = 明确关掉

        visible = Gaffer.Metadata.value(
            target, "noduleLayout:customGadget:%s:visible" % name
        )
        if visible is not None and not visible:
            continue

        section = Gaffer.Metadata.value(
            target, "noduleLayout:customGadget:%s:section" % name
        )
        result.setdefault(section or defaultSection, []).append((name, gadgetType))

    return result


## 这个节点是不是「已经 setup 过」了。
#
# 原生那些 PlugAdder 判据出奇一致 —— **setup 过就把 `+` 藏掉**
# （`BoxIONodeGadget.cpp:135` / `SwitchUI.cpp` / `LoopUI.cpp:119` /
# `ContextProcessorUI.cpp:105` / `EditScopeUI.cpp:111`）。只有 `Gaffer.Box` 例外
# （四个 `+` 一直都在）。不照这条判就会「Switch 出口上还挂着 `+`」。
def adderSetupComplete(node):

    if isinstance(node, Gaffer.BoxIO):
        return node.plug() is not None

    # Switch / Loop / ContextProcessor / EditScope 都是「有没有 in 插口」定生死。
    # 原生 C++ 用的是 `inPlug()`，但**到 1.7.1.0 这个方法都没绑 Python**
    # （`'Loop' object has no attribute 'inPlug'`），一律用 `getChild( "in" )`。
    if isinstance(
        node,
        (Gaffer.Switch, Gaffer.EditScope, Gaffer.Loop, Gaffer.ContextProcessor),
    ):
        return node.getChild("in") is not None

    # AttributeQuery 那一类的 `setupButton`：`setVisible( !isSetup() )`
    # （`AttributeQueryUI.cpp:190`）。凡是有 `isSetup()` 的都照这条判。
    isSetup = getattr(node, "isSetup", None)
    if isSetup is not None:
        return bool(isSetup())

    return False


## 某个 gadgetType 的 `+` 现在该不该显示。
#
# 原生每种 PlugAdder 自己管可见性（`updateVisibility()`），但那些类在 C++ 匿名命名空间里
# 没绑 Python（连 `getVisible()` 都问不到），只能把判据抄过来。按「默认可见」来，
# 只有真有规则的才拦：
#
#   Switch / Loop / ContextProcessor / EditScope / AttributeQuery
#       —— **节点级**注册，setup 过就藏，统一在 `adderSetupComplete()` 里拦
#   PlugVisibilityGadget（材质 `parameters` / `out`，外加
#   `plugVisibilityGadget:showable`）/ ShaderTweaksUI.PlugAdder
#       —— 底下有「能显示但现在藏着」的插口才出现
#   NameSwitchUI / CollectUI._InputAdder / GafferOSLUI.*  —— **一直可见**
#
# 「能显示但现在藏着」是**实测反推**的（那些 PlugAdder 只在 .so 里）：原生 NodeGadget 的
# `__noduleContainer` 的 `bound()` **只算可见子项**，「容器长度 − 可见 nodule 占的长度」
# 就看出末尾那个 `+` 在不在（aiStandardSurface 容器 13.0 − 10 个 nodule 的 11.8 = 有；
# OSLShader OutObject 容器 19.0 = 16 个 nodule 正好 = 没有）。
def _customGadgetVisible(gadgetType, plugsParent):

    if gadgetType == "GafferUI.PlugVisibilityGadget":
        return _hasShowablePlug(plugsParent, "visibilityGadget")

    if gadgetType == "GafferSceneUI.ShaderTweaksUI.PlugAdder":
        return _hasShowablePlug(plugsParent, "tweak")

    return True


## ShaderTweaks 的一条 tweak 现在能不能"显示出来"。逐条照
# `ShaderTweaksUI.cpp` 的 `showablePlugs()`：看的是 **value 子插口**是否只读（不是
# TweakPlug 自己），而且 `mode` 是死值时只有 Replace / Create 两种才算。
def _tweakShowable(tweakPlug):

    value = tweakPlug.getChild("value")
    if value is None or Gaffer.MetadataAlgo.readOnly(value):
        return False

    modePlug = tweakPlug.getChild("mode")
    if isinstance(modePlug, Gaffer.IntPlug) and not Gaffer.PlugAlgo.dependsOnCompute(
        modePlug
    ):
        # 不依赖计算的死值，读它不会触发 compute
        mode = modePlug.getValue()
        if mode not in (
            int(Gaffer.TweakPlug.Mode.Replace),
            int(Gaffer.TweakPlug.Mode.Create),
        ):
            return False

    return True


## `plugsParent` 底下有没有「能显示成 nodule、但现在被藏起来」的插口。
# 判据抄 `PlugVisibilityGadget::showablePlugs()` / `ShaderTweaksUI` 的同名函数。
def _hasShowablePlug(plugsParent, mode):

    children = list(plugsParent.children(Gaffer.Plug))
    while children:

        plug = children.pop()

        visible = Gaffer.Metadata.value(plug, "noduleLayout:visible")
        hidden = visible is not None and not visible

        if hidden:

            if mode == "tweak":
                # ShaderTweaks：只看 TweakPlug（只读与否看它的 value 子插口）
                if _tweakShowable(plug):
                    return True
            elif not Gaffer.MetadataAlgo.readOnly(plug):
                noduleType = Gaffer.Metadata.value(plug, "nodule:type")
                showable = Gaffer.Metadata.value(plug, "plugVisibilityGadget:showable")
                if (
                    showable
                    and plug.getFlags(Gaffer.Plug.Flags.AcceptsInputs)
                    and (noduleType is None or noduleType != "")
                ):
                    return True

        if mode != "tweak":
            # 原生是 RecursiveIterator（命中就 prune），我们照着往下找
            children.extend(plug.children(Gaffer.Plug))

    return False


## 节点四条边上各有没有「加插口」的小 `+`（原生的 PlugAdder），返回 { section : [ 名字 ] }。
#
# 判据全部对着原生 `NoduleLayout` 抄，三类：
#
# 1. **节点级注册**（`noduleLayout:customGadget:<名字>:gadgetType`，`GafferUI/BoxUI.py:72`）：
#    `:section` 指定边（缺省 top），`:visible = False` / gadgetType 为空就是关掉
#    （.grf 里藏 `+` 常用的就是它）。**setup 过的一律不画**，见 `adderSetupComplete`。
# 2. **BoxIn / BoxOut** 的 `+` 是 C++ `setEdgeGadget` 挂的、没有元数据，
#    还没 setup 时要自己补出四条边。
# 3. **插口级注册**：画在那个插口所在的边上（接在它最后一个 nodule 后面）——
#    NameSwitch 的 `in`、Collect 的 `in`、材质的 `parameters`、ShaderTweaks 的 `tweaks`。
#    每种还要过 `_customGadgetVisible` 自己的规则。
#
# 这些 gadget 在 C++ 匿名命名空间里没绑 Python（拿回来是光秃秃的 `GraphComponent`，
# 连 `bound()` 都没有），所以只能自己按元数据画。
def plugAdders(node, graphGadget=None):

    result = {}

    if isinstance(node, Gaffer.BoxIO):
        if adderSetupComplete(node):
            return {}
        return dict(
            (section, ["edge"]) for section in ("top", "bottom", "left", "right")
        )

    if not adderSetupComplete(node):
        result = dict(
            (section, [name for name, _ in entries])
            for section, entries in _metadataAdderSections(node, "top").items()
        )

    # 插口级
    for plug in node.children(Gaffer.Plug):

        if not hasNodule(plug):
            continue

        for section, entries in _metadataAdderSections(plug, plugSection(plug)).items():
            for name, gadgetType in entries:
                if not _customGadgetVisible(gadgetType, plug):
                    continue
                result.setdefault(section, []).append(name)

    return result


## 一条边的对边（提升插口时内部那半要挂反方向，抄 `PlugAdder::applyEdgeMetadata`）。
def oppositeSection(section):

    return {
        "top": "bottom",
        "bottom": "top",
        "left": "right",
        "right": "left",
    }.get(section, "bottom")


## 把任意深度的插口上溯到**画着 nodule 的那一层**。
#
# 一般就是节点的直接子插口，但遇到复合 nodule（ArrayPlug）要再往下走一层：
# `group["in"][0]` 的 nodule 画在 `in0` 上，不是 `in` 上。
def nodulePlug(node, plug):

    chain = []
    current = plug
    while current is not None:
        parent = current.parent()
        if parent is None:
            return None
        chain.append(current)
        if node.isSame(parent):
            break
        if not isinstance(parent, Gaffer.Plug):
            return None
        current = parent
    else:
        return None

    chain.reverse()  # [ 节点的直接子插口, ..., plug ]

    result = chain[0]
    index = 0
    while isCompoundNodule(result) and index + 1 < len(chain):
        index += 1
        result = chain[index]

    return result if hasNodule(result) else None


## 这个插口以后还会不会增删子插口（而且子插口可能带圆点）：`ArrayPlug.resize()`
# 长一路、`Gaffer.Plug` 那种裸容器（OSLShader 的 `parameters` / `out` 等 `loadShader`
# 往里塞参数）、`CompoundDataPlug` / `TweaksPlug` 加一条。叶子 `ValuePlug`
# （Float / ScenePlug / V3f / TransformPlug…）的子插口结构是死的，不必听它们的
# `childAdded` —— 一个节点十来个直系插口，全连的话建 item 的时间一半花在连信号上。
def plugMayGrowChildren(plug):

    if isinstance(plug, (Gaffer.ArrayPlug, Gaffer.CompoundDataPlug, Gaffer.TweaksPlug)):
        return True
    return not isinstance(plug, Gaffer.ValuePlug)


## 一个插口在节点里的唯一键。
#
# **不能用 `plug.getName()`** —— NameSwitch 那种节点上，`in.in0.value` / `in.in1.value` /
# `out.value` 全都叫 "value"，拿名字当键会互相覆盖：多个输入接口只剩一个、
# 而且上下还会串位（这就是「多个接口没显示 + 上下反了」的根因）。
def plugKey(node, plug):

    return plug.relativeName(node)


## 上溯到节点的直接子插口（不展开复合 nodule；辅助连线按它认两头）。
def topLevelPlug(node, plug):

    result = plug
    while result is not None:
        parent = result.parent()
        if parent is None:
            return None
        if node.isSame(parent):
            return result
        if not isinstance(parent, Gaffer.Plug):
            return None
        result = parent

    return None


# 节点形状

SHAPE_RECTANGLE = "rectangle"
SHAPE_OVAL = "oval"  # 胶囊：BoxIn / BoxOut / ContextQuery …
SHAPE_DOT = "dot"  # 小圆点：Gaffer.Dot，和原生一样
SHAPE_AUXILIARY = "auxiliary"  # 带首字母的小方块：Expression / Spreadsheet / Random


## 卡片轮廓，只有三档 —— 身份靠类型图标（`nodeGlyph`）表达，不靠把卡片捏成灯泡形
# （卡片还得放得下名字和侧边徽章）。`nodeGadget:shape` 照读原生
# （rectangle / oval 两档，`StandardNodeGadget.cpp:567`）。
def nodeShape(node):

    if isinstance(node, Gaffer.Dot):
        return SHAPE_DOT

    # 原生把 Expression / Spreadsheet / Random 画成 2x2 的小方块（AuxiliaryNodeGadget），
    # 上面只有一个首字母，我们照做。
    if (
        Gaffer.Metadata.value(node, "nodeGadget:type")
        == "GafferUI::AuxiliaryNodeGadget"
    ):
        return SHAPE_AUXILIARY

    if Gaffer.Metadata.value(node, "nodeGadget:shape") == "oval":
        return SHAPE_OVAL

    return SHAPE_RECTANGLE


## 小方块上写的那个字母（`auxiliaryNodeGadget:label`，AuxiliaryNodeGadget.cpp:54）。
def auxiliaryLabel(node):

    label = Gaffer.Metadata.value(node, "auxiliaryNodeGadget:label")
    if label:
        return str(label)

    name = node.getName()
    return name[:1].lower() if name else "?"


# 节点大小（Gaffer 单位）—— 和原生一模一样


## 一行字在原生里占多宽（Gaffer 单位）。用的就是原生画节点名的那套字体度量。
def textWidthUnits(text):

    bound = GafferUI.Style.getDefaultStyle().textBound(
        GafferUI.Style.TextType.LabelText, text
    )
    return bound.max().x - bound.min().x


## 节点在图上的大小（宽, 高，Gaffer 单位）。
#
# 有 `graphGadget` 就**直接问原生 NodeGadget 要 bound** —— 那是一模一样的数字，
# 连 metadata 的 minWidth/padding、自定义 NodeGadget、材质节点的参数行都算进去了。
# 拿不到（无头测试、gadget 还没建好）才走 StandardNodeGadget 的公式回退。
def nodeSizeUnits(node, graphGadget=None):

    if graphGadget is not None:
        gadget = graphGadget.nodeGadget(node)
        if gadget is not None:
            bound = gadget.bound()
            width = bound.max().x - bound.min().x
            height = bound.max().y - bound.min().y
            if width > 0.0 and height > 0.0:
                return (width, height)

    shape = nodeShape(node)
    if shape == SHAPE_DOT:
        return (DOT_SIZE_UNITS, DOT_SIZE_UNITS)
    if shape == SHAPE_AUXILIARY:
        return (AUX_SIZE_UNITS, AUX_SIZE_UNITS)

    minWidth = Gaffer.Metadata.value(node, "nodeGadget:minWidth")
    minWidth = NODE_MIN_WIDTH_UNITS if minWidth is None else float(minWidth)
    padding = Gaffer.Metadata.value(node, "nodeGadget:padding")
    padding = NODE_PADDING_UNITS if padding is None else float(padding)

    contents = max(minWidth, textWidthUnits(node.getName()) + NODE_TEXT_MARGIN_UNITS)
    width = contents + padding * 2.0 - NODE_BORDER_UNITS * 2.0

    layout = noduleLayout(node)
    sideRows = max(len(layout["left"]), len(layout["right"]))
    height = max(NODE_HEIGHT_UNITS, sideRows * SIDE_ROW_UNITS + SIDE_ROWS_BASE_UNITS)

    return (width, height)


# 节点类型图标

GLYPH_LIGHT = "light"  # 灯泡（不认识的灯光兜底）
GLYPH_CAMERA = "camera"  # 相机
GLYPH_FILTER = "filter"  # 漏斗
GLYPH_SHADER = "shader"  # 材质球
GLYPH_RENDER = "render"  # 画面输出
GLYPH_GEOMETRY = "geometry"  # 图元
GLYPH_TRANSFORM = "transform"  # 变换
GLYPH_EXPRESSION = "expression"  # 表达式（Σ）
GLYPH_SPREADSHEET = "spreadsheet"  # 表格（网格）
GLYPH_DISPLACEMENT = "displacement"  # 置换（起伏的面）
GLYPH_VOLUME = "volume"  # 体积（云团）
GLYPH_TEXTURE = "texture"  # 贴图（画片）
GLYPH_PATTERN = "pattern"  # 程序纹理（棋盘）
GLYPH_UTILITY = "utility"  # 工具 / 数学（推子）
GLYPH_POINT_LIGHT = "pointLight"  # 点光源（全向）
GLYPH_DISTANT_LIGHT = "distantLight"  # 平行光（太阳）
GLYPH_QUAD_LIGHT = "quadLight"  # 面光源（矩形面板）
GLYPH_SPOT_LIGHT = "spotLight"  # 聚光（锥形光束）
GLYPH_DISK_LIGHT = "diskLight"  # 圆盘光
GLYPH_CYLINDER_LIGHT = "cylinderLight"  # 圆柱光
GLYPH_SKYDOME_LIGHT = "skydomeLight"  # 穹顶光（半球）
GLYPH_PHOTOMETRIC_LIGHT = "photometricLight"  # 光度学（IES 灯具）
GLYPH_MESH_LIGHT = "meshLight"  # 网格光


## 节点左侧画哪个类型图标，没有就返回 None。
#
# 按 MRO 里的类名判断而不是 isinstance —— ArnoldLight / CyclesLight / USDLight 之类
# 全都派生自 `GafferScene::Light`，这样一次覆盖，也不用为此 import 一堆可选模块
# （`GafferArnold` 在无头环境 import 就 SIGABRT）。
def nodeGlyph(node):

    typeNames = [c.__name__ for c in type(node).__mro__]

    if isLightNode(node):
        return lightGlyph(node)
    if "Camera" in typeNames:
        return GLYPH_CAMERA
    # 材质**不能一律画材质球**：置换 / 体积 / 贴图 / 程序纹理 / 数学工具都是 Shader 子类，
    # 画成材质球一屏全一样。按 shader 自己的 `type` 和 `name` 分。
    if "Shader" in typeNames:
        return shaderGlyph(node)
    if "ShaderAssignment" in typeNames or "ShaderTweaks" in typeNames:
        return GLYPH_SHADER
    if "Filter" in typeNames:
        return GLYPH_FILTER
    if (
        "Render" in typeNames
        or "Outputs" in typeNames
        or "Display" in typeNames
        or "Catalogue" in typeNames
    ):
        return GLYPH_RENDER
    if "ObjectSource" in typeNames:
        return GLYPH_GEOMETRY
    if "Transform" in typeNames or "Constraint" in typeNames:
        return GLYPH_TRANSFORM
    # 这两个默认画成小方块（AuxiliaryNodeGadget），但右键 Show Name 之后就是普通卡片，
    # 那时候得有图标（`nodeGlyph` 在小方块形状下不会被调用）
    if "Expression" in typeNames:
        return GLYPH_EXPRESSION
    if "Spreadsheet" in typeNames:
        return GLYPH_SPREADSHEET

    return None


## 一个材质节点该画什么图标。
#
# 判据取自 Shader 节点自己的两个插口：`type`（"ai:surface" / "ai:displacement" /
# "osl:shader" …）和 `name`（"standard_surface" / "image" / "noise" …）。
# 先看 type 的后缀，剩下那些通用 shader（`ai:shader` / `osl:shader`）再按名字分类。
def shaderGlyph(node):

    # `name` / `type` 是 `loadShader()` 写的死值，读它不会触发 compute
    def plugText(name):

        plug = node.getChild(name)
        return plug.getValue().lower() if isinstance(plug, Gaffer.StringPlug) else ""

    suffix = plugText("type").rpartition(":")[2]
    name = plugText("name").rpartition("/")[2]
    out = node.getChild("out")

    # ⚠️ **别指望 `type` 分得出类型**：`ArnoldShader.loadShader()` 之后 `type` 一律是
    # `ai:surface`（image / noise / color_correct 全一样，1.7.1.0 真机验过）。
    # 真正靠得住的是**名字**，以及 **`out` 是不是 ClosurePlug** ——
    # 是闭包就是真材质（surface / volume / displacement），是 Color/Float 就是纹理或工具。
    if "light" in suffix or name.endswith("_light") or name.startswith("light_"):
        return GLYPH_LIGHT
    if "displacement" in suffix or "displacement" in name or "bump" in name:
        return GLYPH_DISPLACEMENT
    if "volume" in suffix or "volume" in name or "atmosphere" in name or "fog" in name:
        return GLYPH_VOLUME

    # 闭包输出 = 真材质，排在下面那些名字关键词前面 —— 否则 `mix_shader` /
    # `layer_shader` / `switch_shader` 会被 mix / layer / switch 认成工具节点
    if out is not None and type(out).__name__ == "ClosurePlug":
        return GLYPH_SHADER

    if any(
        k in name
        for k in ("image", "texture", "file", "uv_", "triplanar", "map", "sky")
    ):
        return GLYPH_TEXTURE
    if any(
        k in name
        for k in (
            "noise",
            "checker",
            "cell",
            "fractal",
            "wave",
            "ramp",
            "flakes",
            "pattern",
        )
    ):
        return GLYPH_PATTERN
    if any(
        k in name
        for k in (
            "color_",
            "math",
            "range",
            "mix",
            "blend",
            "multiply",
            "add",
            "divide",
            "subtract",
            "clamp",
            "abs",
            "pow",
            "switch",
            "compare",
            "state",
            "user_data",
            "utility",
            "layer",
            "curvature",
            "facing",
            "float_to",
            "to_float",
        )
    ):
        return GLYPH_UTILITY

    if "surface" in name or "shader" in name or "material" in name:
        return GLYPH_SHADER

    return GLYPH_UTILITY if out is not None else GLYPH_SHADER


## 是不是灯光节点（`GafferScene::Light` 子类、灯光过滤器、以及网格光）。
#
# ⚠️ 网格光**不是** `GafferScene::Light` —— 1.7.1.0 的 `GafferScene::MeshLight`
# 派生自 `FilteredSceneProcessor`（`include/GafferScene/MeshLight.h:49`），
# `ArnoldMeshLight` 同理。只查 `"Light" in MRO` 会漏掉它们（ArnoldMeshLight
# 没灯泡、被当成普通场景处理器）。
# 一律按**类名以 `MeshLight` 结尾**认，`MeshLight` / `ArnoldMeshLight` 都覆盖。
def isLightNode(node):

    typeNames = [c.__name__ for c in type(node).__mro__]
    return (
        "Light" in typeNames
        or "LightFilter" in typeNames
        or any(n.endswith("MeshLight") for n in typeNames)
    )


## 灯光节点画哪个图标 —— 每个类型灯一个，不统一画小灯泡。
#
# 灯光类型读 `__shader["name"]`（`GafferScene::Light` 把 shader 存在 `__shader` 子节点里，
# `ArnoldLight` 的 `name` 顶插口只是 "light"，真正的类型在 `__shader.name`：point_light /
# quad_light / spot_light …）。读不到再退回顶层 `name`（某些别的渲染器的灯）。
def lightGlyph(node):

    name = ""
    shader = node.getChild("__shader")
    if shader is not None:
        # `loadShader()` 写的死值
        name = shader["name"].getValue().lower()
    if not name:
        namePlug = node.getChild("name")
        if isinstance(namePlug, Gaffer.StringPlug):
            # 顶层 `name` 常被表达式驱动（`${collect:rootName}` 之类），算出错就当认不出
            try:
                name = namePlug.getValue().lower()
            except Gaffer.ProcessException:
                name = ""

    return {
        "point_light": GLYPH_POINT_LIGHT,
        "distant_light": GLYPH_DISTANT_LIGHT,
        "quad_light": GLYPH_QUAD_LIGHT,
        "spot_light": GLYPH_SPOT_LIGHT,
        "disk_light": GLYPH_DISK_LIGHT,
        "cylinder_light": GLYPH_CYLINDER_LIGHT,
        "skydome_light": GLYPH_SKYDOME_LIGHT,
        "photometric_light": GLYPH_PHOTOMETRIC_LIGHT,
        "mesh_light": GLYPH_MESH_LIGHT,
    }.get(name, GLYPH_LIGHT)


## 这个方向的接口标签要不要常驻显示（节点右键 `/Connections/Show Input·Output Labels`，
# 原生 `StandardNodeGadget::applyNoduleLabelVisibilityMetadata`）。
def noduleLabelsVisible(node, direction):

    key = (
        "nodeGadget:inputNoduleLabelsVisible"
        if direction == Gaffer.Plug.Direction.In
        else "nodeGadget:outputNoduleLabelsVisible"
    )
    return bool(Gaffer.Metadata.value(node, key))


## focus 角标要不要画（原生 `g_focusGadgetVisibleKey`，缺省 = 画）。
def focusGadgetVisible(node):

    value = Gaffer.Metadata.value(node, "nodeGadget:focusGadgetVisible")
    return True if value is None else bool(value)


## nodule 旁边徽章上写什么字。和 `StandardNodule.cpp:236` 一致：
# `noduleLayout:label` 元数据优先，否则用插口名。
def noduleLabel(plug):

    return Gaffer.Metadata.value(plug, "noduleLayout:label") or plug.getName()


## 侧边参数按 `layout:section` 分栏（Houdini 式可收放），返回 { "left" : [...], "right" : [...] }。
#
# 每个侧边一组 `[ ( 栏名或 None, [ plug, ... ] ), ... ]`：带 `layout:section` 的按栏名
# **首次出现顺序**聚拢，没带的分成一条条 `( None, [ plug ] )`。
#
# 三道闸，缺一不可（免得把普通节点带偏）：有 `parameters` 插口、至少一个侧边插口带
# `layout:section`、且**不是灯光节点**。不满足返回空 dict，侧边走原生行为。
def buildSectionData(node, layout):

    if node.getChild("parameters") is None:
        return {}

    # 灯光节点不走分栏那套。灯光卡片本来就是暖黄的，
    # 加宽的色带 + 卡内参数名一上去就糊成一块，而且灯光的参数在 NodeEditor 里调、
    # 图上基本不接线，列出来没意义。`isLightNode` 认三种灯：`GafferScene::Light` 子类、
    # LightFilter、以及 `MeshLight`（ArnoldMeshLight 派生自它而不是 Light）。
    if isLightNode(node):
        return {}

    # 材质参数大多是**隐藏圆点**的（`noduleLayout:visible=False`，standard_surface
    # 66 个参数只有 10 个有圆点，原生图上看不到）。侧边栏要**显示全部属性**，
    # 所以把没圆点的也收进来：它们没有原生 nodule gadget，侧边跟着 `parameters`
    # 那条边走，位置 / 切线由分栏布局自己给。
    parameters = node.getChild("parameters")
    parametersSection = Gaffer.Metadata.value(parameters, "noduleLayout:section")
    hidden = []
    if isinstance(parameters, Gaffer.Plug) and parametersSection in ("left", "right"):
        for plug in parameters.children(Gaffer.Plug):
            if (
                not hasNodule(plug)
                and Gaffer.Metadata.value(plug, "layout:section") is not None
            ):
                hidden.append(plug)

    result = {}
    for side in ("left", "right"):
        bySection = collections.OrderedDict()
        ungrouped = []
        for plug in layout.get(side, []):
            # **输出口不参与分栏**。
            # 材质节点的 `out` 身上带着 `layout:section = "Settings"`，照直分栏的话
            # 右边会长出一个只装 `out` 的 "Settings" 栏 + 一个折叠三角 —— 把唯一的
            # 输出口收起来毫无意义。输出插口一律当"没分栏"处理（照旧一个圆点）。
            if plug.direction() == Gaffer.Plug.Direction.Out:
                ungrouped.append(plug)
                continue
            section = Gaffer.Metadata.value(plug, "layout:section")
            if section is None:
                # 展开的 Color3f / V3f 子接口（`r`/`g`/`b`）自己身上没有分栏元数据 ——
                # 原生把它们留在**父接口那一格**，所以跟父插口进同一栏。
                parent = plug.parent()
                if isinstance(parent, Gaffer.Plug) and isExpandedCompoundNumeric(
                    parent
                ):
                    section = Gaffer.Metadata.value(parent, "layout:section")
            if section is None:
                ungrouped.append(plug)
            else:
                bySection.setdefault(str(section), []).append(plug)
        if side == parametersSection:
            for plug in hidden:
                if plug.direction() == Gaffer.Plug.Direction.Out:
                    continue
                section = Gaffer.Metadata.value(plug, "layout:section")
                bySection.setdefault(str(section), []).append(plug)
        groups = [(None, [p]) for p in ungrouped] + list(bySection.items())
        if any(name is not None for name, _ in groups):
            result[side] = groups

    return result


## 这个分栏收着没有。状态记在节点的**非持久**元数据上：不进 .grf，但重建 item
# （改名 / 换插口 / 撤销）不会丢。**默认收起** —— 只有展开过的（写了
# `BoolData(False)`）才是展开的。
def sectionCollapsed(node, side, section):

    # `Metadata.value` 会把 `IECore.BoolData` 直接解包成 Python bool（1.7.1.0 复核过），
    # 传进来的就是 `True` / `False`；没注册过是 None（= 默认收起）。
    # ⚠️ 所以 `isinstance( data, IECore.BoolData )` 永远为假，别那么写。
    data = Gaffer.Metadata.value(
        node, "nodeGadget:sectionCollapsed:%s:%s" % (side, section)
    )
    return True if data is None else bool(data)


def setSectionCollapsed(node, side, section, collapsed):

    # **永远写显式值**（不 deregister）：默认是收起，展开 = `BoolData(False)` ——
    # 只有写进元数据的才展开，撤掉元数据反而会掉回「收起」。
    key = "nodeGadget:sectionCollapsed:%s:%s" % (side, section)
    Gaffer.Metadata.registerValue(node, key, IECore.BoolData(bool(collapsed)))


# 连线颜色

## 没有类型色的连线 = StandardStyle 默认色（`StandardStyle.cpp:534`，`getColor()`
# 无头复核过）。
_connectionColor = "#999999"
_auxiliaryWireColor = "#4d734d"

## 按类型上色的连线最低亮度。接口圆点的类型色（场景蓝 0.24/0.34/0.485 之类）
# 画成 1.5px 的细线压在深底上太暗，按比例提到这个亮度，色相不变。
_WIRE_MIN_LUMINANCE = 0.42


## 一条连线画什么颜色（"#rrggbb"）。
#
# 和接口圆点同一套类型色（`nodule:color`，源插口优先、没有再看目标插口），一眼看得出
# 是场景流、filter、颜色还是数值；两头都没注册类型色的（int / string 之类）用原生默认灰，
# 表达式这类辅助连线照原生的绿。原生 `StandardConnectionGadget` 还会读目标插口上的
# `connectionGadget:color`（`StandardConnectionGadget.cpp:710`）做覆盖 ——
# **我们故意不读**，否则装了插件的环境里连线会变成插件的配色。
def wireColor(edge):

    if edge.auxiliary:
        return _auxiliaryWireColor

    for plug in (edge.srcPlug, edge.dstPlug):
        color = Gaffer.Metadata.value(plug, "nodule:color")
        # 灰的（比如 UI Editor 里留的默认 0.4 灰）不算类型色
        if isinstance(color, imath.Color3f) and max(color) - min(color) > 0.05:
            return _wireTypeColor(color)

    return _connectionColor


def _wireTypeColor(color):

    rgb = [color[0], color[1], color[2]]
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    if 1e-6 < luminance < _WIRE_MIN_LUMINANCE:
        scale = _WIRE_MIN_LUMINANCE / luminance
        rgb = [min(1.0, v * scale) for v in rgb]

    return _hex(rgb)


## 这个节点上「收路径」的那个插口（PathFilter 的 `paths` 就是靠这条元数据标出来的）。
# 照 `GafferSceneUI/PathFilterUI.py` 的 `__pathsPlug`。
def _pathsPlug(node):

    for plug in node.children(Gaffer.Plug):
        if Gaffer.Metadata.value(plug, "ui:scene:acceptsPaths"):
            return plug

    return None


## 这个节点上唯一的 filter 输入插口（多于一个就不猜）。照 `__filterPlug`。
def _filterPlug(node):

    # 只认**输入**的 filter 插口（`Range` 会把输出的 FilterPlug 也算进去）
    plugs = list(GafferScene.FilterPlug.InputRange(node))
    return plugs[0] if len(plugs) == 1 else None


def _plugEditable(plug):

    return not Gaffer.MetadataAlgo.readOnly(plug) and plug.settable()


def _hex(color):

    return "#%02x%02x%02x" % tuple(
        max(0, min(255, int(round(c * 255.0)))) for c in (color[0], color[1], color[2])
    )


## 两个 "#rrggbb" 按 t 混合（t=0 全取 a）。
def mixColors(a, b, t):

    ca, cb = QtGui.QColor(a), QtGui.QColor(b)
    return "#%02x%02x%02x" % (
        int(round(ca.red() * (1 - t) + cb.red() * t)),
        int(round(ca.green() * (1 - t) + cb.green() * t)),
        int(round(ca.blue() * (1 - t) + cb.blue() * t)),
    )


## 哪些节点元数据一变就得重建（我们的画法依赖它们）。
#
# 右键「Show Name」改的就是 `nodeGadget:type`（`UIEditor.__setNameVisible` 往节点上
# 注册这个键）—— 不听这个信号的话，表达式/表格点了 Show Name 画面不会变。
_rebuildNodeMetadataKeys = frozenset(
    [
        "nodeGadget:type",
        "nodeGadget:shape",
        "nodeGadget:color",
        "nodeGadget:minWidth",
        "nodeGadget:padding",
        "auxiliaryNodeGadget:label",
        "icon",
        "iconScale",
        "bookmarked",
        "readOnly",
        "childNodesAreReadOnly",
        # 节点右键 `/Connections/Show Input·Output Labels` 改的就是这两个
        # （原生 `GraphEditor.__setNoduleLabelsVisible`）
        "nodeGadget:inputNoduleLabelsVisible",
        "nodeGadget:outputNoduleLabelsVisible",
        # focus 角标能不能显示（原生 `StandardNodeGadget` 读它决定要不要建 FocusGadget）
        "nodeGadget:focusGadgetVisible",
    ]
)


## 这个键变了要不要重建。
def rebuildOnNodeMetadata(key):

    key = str(key)
    return (
        key in _rebuildNodeMetadataKeys
        or key.startswith("noduleLayout:")
        or key.startswith("annotation:")
        or key.startswith("numericBookmark")
        or
        # 侧边参数分栏收 / 放（Houdini 式）—— 一变要重排侧边、重算高度
        key.startswith("nodeGadget:sectionCollapsed:")
    )


## 这个**插口**元数据键变了要不要重建 item。
#
# `noduleLayout:visible`（展开 / 收起 RGB 子插口）、`noduleLayout:section`（挪到哪条边）、
# `nodule:type` / `nodule:color`、`noduleLayout:label`（圆点旁边写的字）都会改卡片长相。
def rebuildOnPlugMetadata(key):

    key = str(key)
    return (
        key.startswith("noduleLayout:")
        or key.startswith("nodule:")
        or
        # 圆点右键「Expand / Collapse RGB Components」记的就是这个键
        key == "compoundNumericNodule:childrenVisible"
    )


## 节点的颜色（"#rrggbb"）—— **和原生同一个来源**：`nodeGadget:color` 元数据，
# 没有就是 StandardStyle 的 RaisedColor。原生 `startup/gui/graphEditor.py` 与
# 工作室自己的启动脚本都是往这个键上注册的，所以
# SceneProcessor 紫、GlobalsProcessor 绿、PathFilter 橙、TaskNode 红、灯光黄……
# 全部自动跟着原生走。
def nodeColor(node):

    color = Gaffer.Metadata.value(node, "nodeGadget:color")
    if isinstance(color, imath.Color3f):
        return _hex(color)

    return _raisedColor


__genericNodeColor = []


## 原生给 `Gaffer.Node` 本身注册的那个「万能默认色」（启动脚本也可能把它改成别的灰）。
# 一个节点如果只拿到这个色，说明它其实**没有**类型配色。
def genericNodeColor():

    if not __genericNodeColor:
        color = Gaffer.Metadata.value(Gaffer.Node(), "nodeGadget:color")
        __genericNodeColor.append(
            _hex(color) if isinstance(color, imath.Color3f) else None
        )

    return __genericNodeColor[0]


## 顶部色带的颜色。节点有自己的类型配色就用它（和原生一致）；只有那个万能默认灰的
# 节点（Plane / Camera / SceneReader 之类）用我们按模块分的颜色，免得一屏全灰。
def nodeAccentColor(node):

    color = nodeColor(node)
    generic = genericNodeColor()

    if (generic is not None and color == generic) or color == _raisedColor:
        module = type(node).__module__.split(".")[0]
        return _moduleColors.get(module, _defaultModuleColor)

    return color


## 卡片主体色：节点色压暗，色相保留。
def cardColor(node):

    return mixColors(nodeColor(node), _cardTintTarget, _cardTintAmount)


## 一个接口圆点画什么颜色。**和原生同一个来源**：插口上的 `nodule:color`
# （原生 `startup/gui/graphEditor.py` 按插口类型注册：ScenePlug 蓝、FilterPlug 橙、
# FloatPlug 蓝、Color3fPlug 橙、V3fPlug 红、TaskPlug 红…），没有就是 RaisedColor。
# 这就是「看圆点认类型」的依据，别自己发明。
def noduleColor(plug):

    color = Gaffer.Metadata.value(plug, "nodule:color")
    if isinstance(color, imath.Color3f):
        return _hex(color)

    return _raisedColor


## 按 `D` 要改的到底是哪个插口。逐行抄原生 `GraphEditor.__enabledPlugForEditing`
# （1.7.1.0 装机版 `GraphEditor.py:932` 一带）：`enabled` 被别处驱动时，能改源头就
# 改源头；源头是个 compute，就看看能不能改上游那个节点的 enabled。
def enabledPlugForEditing(node):

    if not isinstance(node, Gaffer.DependencyNode):
        return None

    enabledPlug = node.enabledPlug()
    if enabledPlug is None:
        return None

    if enabledPlug.getInput() is None:
        return enabledPlug

    source = enabledPlug.source()
    if not Gaffer.PlugAlgo.dependsOnCompute(source):
        return source

    # 依赖 compute，但如果那个节点「停用时输出 False」（比如 PatternMatch），
    # 改它的 enabled 是等价的。
    if source.defaultValue() != False:
        return enabledPlug

    sourceNode = source.node()
    if not isinstance(sourceNode, Gaffer.DependencyNode):
        return enabledPlug

    sourceEnabledPlug = sourceNode.enabledPlug()
    if sourceEnabledPlug is not None and sourceNode.correspondingInput(source) is None:
        return sourceEnabledPlug

    return enabledPlug


## 节点的 `enabled` 状态。被表达式驱动时拿不准 → 返回 None（画成第三态）。
# 原生为此专门走 ContextTracker（`StandardNodeGadget.cpp:1379` `hasStaticValue`），
# 我们不跟，只处理静态值。
def nodeEnabled(node):

    if not isinstance(node, Gaffer.DependencyNode):
        return True

    plug = node.enabledPlug()
    if plug is None:
        return True

    # **不要盲目 getValue()**：`enabled` 被上游驱动时那是一次真正的 compute，
    # 在大图上慢，图里有依赖环时还会刷一屏 "Cycle detected"。原生为此有
    # `hasStaticValue()`（`StandardNodeGadget.cpp:520`：不依赖 compute 才敢读），
    # 这里照同一条判据，拿不准就返回 None 画成第三态。
    if Gaffer.PlugAlgo.dependsOnCompute(plug):
        return None
    return plug.getValue()


## 人工写的那条注释的名字（右键 Annotate… 加的就是它）。
#
# 卡片下面**只画这一条**。各家（比如 ArnoldShader 的 `shader_type` = `{name}`）注册的
# 模板注释一律不画 —— 那是自动生成的文字，节点下面不该冒出来。
# （原生是全画的：`AnnotationsGadget` 默认 `m_visibleAnnotations = "*"`。）
_userAnnotation = "user"

_plugValueSubstitutionPattern = re.compile(r"\{([^}]*)\}")


## 注释里的 `{插口路径}` 换成插口的值。抄原生 `AnnotationsGadget.cpp` 的
# `substitutePlugValues`：找得到插口就用它的值，找不到就换成空。
def substituteAnnotationText(text, node):

    if "{" not in text:
        return text

    def replace(match):

        plug = node.descendant(match.group(1))
        if not isinstance(plug, Gaffer.ValuePlug):
            return ""

        # 算出错原生保留 `---` 占位（`AnnotationsGadget.cpp:686`）
        try:
            return _formatPlugValue(plug)
        except Gaffer.ProcessException:
            return "---"

    # 原生在 focus 那条路的 context 里求值（`AnnotationsGadget.cpp:608`），
    # 帧号 / context 变量驱动的值才对得上
    script = node.scriptNode()
    if script is None:
        return _plugValueSubstitutionPattern.sub(replace, text)

    with GafferUI.ContextTracker.acquireForFocus(script).context(node):
        return _plugValueSubstitutionPattern.sub(replace, text)


## 插口值写成注释里那串字。照 `AnnotationsGadget.cpp` 的 `formatPlugValue`：
# BoolPlug 是 On / Off、向量数据按逗号连、复合插口（V3f / Color3f）把子插口
# 逐个格式化再逗号连 —— 直接 `str( value )` 的话写出来是 `True` / `V3f(1, 2, 3)`。
def _formatPlugValue(plug):

    if isinstance(plug, Gaffer.BoolPlug):
        return "On" if plug.getValue() else "Off"
    if isinstance(plug, Gaffer.IntPlug):
        return str(plug.getValue())
    if isinstance(plug, Gaffer.FloatPlug):
        return (
            "%.7g" % plug.getValue()
        )  # 单精度有效位数，和 `fmt::format( "{}" )` 一个量级
    if isinstance(plug, Gaffer.StringPlug):
        return plug.getValue()
    if isinstance(
        plug,
        (
            Gaffer.IntVectorDataPlug,
            Gaffer.FloatVectorDataPlug,
            Gaffer.StringVectorDataPlug,
        ),
    ):
        return ", ".join(
            ("%.7g" % v) if isinstance(v, float) else str(v) for v in plug.getValue()
        )

    children = plug.children(Gaffer.ValuePlug)
    if children:
        return ", ".join(_formatPlugValue(child) for child in children)

    value = plug.getValue()
    if isinstance(value, float):
        return "%.7g" % value
    return str(value)


## 节点上的注释（原生 AnnotationsGadget 那套）。返回 ( text, "#rrggbb" ) 或 None。
# 原生 `AnnotationsGadget::untemplatedAnnotations` —— 菜单里的 "Other"，
# 指「没注册过模板的那些注释」。
UNTEMPLATED_ANNOTATIONS = "__untemplated__"

## 默认显示哪些注释。
#
# 原生默认 `"*"` —— 全画。而 Arnold 材质上那条 `shader_type = {name}` 实测**不是**
# 注册过的注释模板（1.7.1.0 里仍只有 `performanceMonitor:*` / `contextMonitor`），
# 属于「没模板的」那一类，所以原生默认会在每个材质节点下面写一行 `standard_surface`
# —— 这种自动生成的文字不要。所以我们默认**只画 `user`**（人手写的那条），
# 其余走工具条的 Annotations 菜单（`All` / `Other` / 逐个挑）。
DEFAULT_VISIBLE_ANNOTATIONS = "user"


## 注释名字 → 菜单里的标签，照原生（`snake_case` 和 `CamelCase` 都认，`:` 分层）。
def annotationLabel(name):

    parts = str(name).split(":")
    return "/".join(
        (
            (" ".join(x.title() for x in p.split("_")))
            if "_" in p
            else IECore.CamelCase.toSpaced(p)
        )
        for p in parts
    )


## 注册过的注释模板名（原生 `MetadataAlgo.annotationTemplates()`）。
def annotationTemplateNames(userOnly=False):

    return sorted(Gaffer.MetadataAlgo.annotationTemplates(userOnly=userOnly))


## 这个节点身上、在 `visiblePattern` 下看得见的注释，[ ( 名字, 文字, "#rrggbb" ), … ]。
#
# 过滤逐条照原生 `AnnotationsGadget::update()`：名字自己匹配 pattern 就算可见；
# 匹配不上时，只有「没注册模板的」那些才靠 `__untemplated__` 那一条放行。
def nodeAnnotations(node, visiblePattern=None):

    # 绝大多数节点一条注释都没有 —— 别为它们去查模板表（每建一个 item 都走这里）
    names = Gaffer.MetadataAlgo.annotations(node)
    if not names:
        return []

    if visiblePattern is None:
        visiblePattern = DEFAULT_VISIBLE_ANNOTATIONS

    untemplatedVisible = IECore.StringAlgo.matchMultiple(
        UNTEMPLATED_ANNOTATIONS, visiblePattern
    )
    templates = None

    result = []
    for name in names:
        name = str(name)
        if not IECore.StringAlgo.matchMultiple(name, visiblePattern):
            if not untemplatedVisible or name == "user":
                continue
            if templates is None:
                templates = set(annotationTemplateNames())
            if name in templates:
                continue

        annotation = Gaffer.MetadataAlgo.getAnnotation(node, name, True)
        if not annotation:
            continue

        text = substituteAnnotationText(annotation.text(), node).strip()
        if not text:
            continue

        result.append((name, text, _hex(annotation.color())))

    return result


## 只要人工写的那条（`user`）：( text, "#rrggbb" ) 或 None。
def nodeAnnotation(node):

    for name, text, color in nodeAnnotations(node, _userAnnotation):
        if name == _userAnnotation:
            return (text, color)

    return None


# 原生 `BackdropNodeGadget` 的默认框（`g_defaultBound`，`BackdropNodeGadget.cpp:144`）。
BACKDROP_DEFAULT_BOUND = imath.Box2f(imath.V2f(-10), imath.V2f(10))


## Backdrop 的框，**相对 `__uiPosition`**（和原生 `BackdropNodeGadget::getBound()` 同语义）。
def backdropRelativeBound(node):

    plug = node.getChild("__uiBound")
    if isinstance(plug, Gaffer.Box2fPlug):
        return plug.getValue()

    return imath.Box2f(BACKDROP_DEFAULT_BOUND.min(), BACKDROP_DEFAULT_BOUND.max())


## 写框。插口不存在就建（照原生 `acquireBoundPlug( createIfMissing = True )`）。
def setBackdropRelativeBound(node, box):

    plug = node.getChild("__uiBound")
    if not isinstance(plug, Gaffer.Box2fPlug):
        plug = Gaffer.Box2fPlug(
            "__uiBound",
            Gaffer.Plug.Direction.In,
            imath.Box2f(BACKDROP_DEFAULT_BOUND.min(), BACKDROP_DEFAULT_BOUND.max()),
            flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic,
        )
        node.addChild(plug)

    plug.setValue(box)


## 文字缩放（Backdrop 的 `scale` 插口）。原生把整个内容按它缩放，看起来就是
# 「框不变、标题和描述放大」。
def backdropScale(node):

    plug = node.getChild("scale")
    if not isinstance(plug, Gaffer.FloatPlug):
        return 1.0

    # 可能被表达式驱动，算出错就按 1 画
    try:
        return max(0.05, plug.getValue())
    except Gaffer.ProcessException:
        return 1.0


## 层叠深度（`depth` 插口，1.7.1.0 实测范围 [-1, 1]）。
def backdropDepth(node):

    plug = node.getChild("depth")
    if not isinstance(plug, Gaffer.IntPlug):
        return 0

    try:
        return plug.getValue()
    except Gaffer.ProcessException:
        return 0


## Backdrop 的标题 / 描述。原生会拿脚本的 context 做 `${var}` 替换
# （`titleAndDescriptionFromPlugs`），照做。
def backdropTitleAndDescription(node):

    title = node.getChild("title")
    description = node.getChild("description")
    script = node.ancestor(Gaffer.ScriptNode)

    def read():
        return (
            title.getValue() if isinstance(title, Gaffer.StringPlug) else "",
            (
                description.getValue()
                if isinstance(description, Gaffer.StringPlug)
                else ""
            ),
        )

    try:
        # 原生（`BackdropNodeGadget.cpp` 的 `titleAndDescriptionFromPlugs`）是在
        # 脚本 context 里取值的 —— 标题被表达式驱动、表达式又读了 context 变量时
        # 才看得出区别，照做。
        if script is not None:
            with script.context():
                title, description = read()
        else:
            title, description = read()
    except Gaffer.ProcessException as exception:
        return ("ERROR : Getting title", "ERROR:\n%s" % exception)

    if script is not None:
        context = script.context()
        title = context.substitute(title)
        description = context.substitute(description)

    return (title, description)


## Backdrop 的框（Gaffer 单位，中心 + 尺寸）。返回 ( centerV2f, widthUnits, heightUnits )。
def backdropBound(node):

    position = nodePosition(node) or imath.V2f(0)
    box = backdropRelativeBound(node)

    return (
        imath.V2f(
            position.x + (box.min().x + box.max().x) * 0.5,
            position.y + (box.min().y + box.max().y) * 0.5,
        ),
        box.max().x - box.min().x,
        box.max().y - box.min().y,
    )


## 能不能双击钻进去。
def canEnter(node):

    if Gaffer.MetadataAlgo.getChildNodesAreReadOnly(node):
        return False

    return bool(node.children(Gaffer.Node))


## 当前 root 下要画哪些节点 —— 和原生 GraphGadget 一样，只画直接子节点。
def collectNodes(root):

    return list(root.children(Gaffer.Node))


## 一条连线。
class Edge(object):

    def __init__(self, srcNode, srcPlug, dstNode, dstPlug, auxiliary):

        self.srcNode = srcNode
        self.srcPlug = srcPlug  # 节点直接子插口（nodule 所在层）
        self.dstNode = dstNode
        self.dstPlug = dstPlug
        # 端点没有 nodule（典型是 Expression 驱动内部插口）→ 原生画成虚的
        # AuxiliaryConnection，我们照做。
        self.auxiliary = auxiliary

    ## 这条边的身份。**插口一律用节点内的相对名，不能用 `getName()`** ——
    # NameSwitch / Collect 的每一路都是 `NameValuePlug`，圆点在 `in.in0.value` /
    # `in.in1.value` 上，两者 `getName()` **都是 "value"**：拿它当 key 会把
    # 同一个源接到 in0 / in1 的两条线算成同一条，第二条被当重复扔掉。
    def key(self):

        return (
            self.srcNode.getName(),
            plugKey(self.srcNode, self.srcPlug),
            self.dstNode.getName(),
            plugKey(self.dstNode, self.dstPlug),
        )


def _connectedInputPlugs(parent, result, ignorePrivate=True):
    """收集「最外层已连接」的输入插口。父插口连上了就不再往下钻 —— Gaffer 里
    父插口连接会同时给每个子插口都设 input，不挡住会画出一堆重复线。

    `ignorePrivate` 对齐原生 `AuxiliaryConnectionsGadget.cpp:89` 的
    `ignorePrivatePlugs = !runTimeCast<const Expression>( dstNode )` —— **Expression
    的输入就挂在私有的 `__in` 里**，一律跳过 `__` 的话「表达式读了哪些节点」这些线
    就全丢了。"""

    for plug in parent.children(Gaffer.Plug):

        if ignorePrivate and plug.getName().startswith(_internalPlugPrefix):
            continue
        if plug.direction() != Gaffer.Plug.Direction.In:
            continue

        if plug.getInput() is not None:
            result.append(plug)
        else:
            _connectedInputPlugs(plug, result, ignorePrivate)


## 收集 `nodes` 之间的连线。只认两端都在 `nodes` 里的连接 —— 通向 Box 内部的
# 连接在 Box 那一层已经由提升插口代表了。
def collectEdges(root, nodes):

    names = set(node.getName() for node in nodes)

    edges = []
    seen = set()

    for dstNode in nodes:
        _collectEdgesForDestination(root, dstNode, names, edges, seen)

    return edges


## 只收「以 `dstNode` 为目的地」的那些连线。
#
# 增量更新用得着：一根线接上 / 拔掉只会改动目的地那一端（`plugInputChangedSignal`
# 报的就是目的地那个节点），没必要为此把全图的边重收一遍。
def edgesForDestination(root, dstNode, names):

    edges = []
    _collectEdgesForDestination(root, dstNode, names, edges, set())
    return edges


def _collectEdgesForDestination(root, dstNode, names, edges, seen):

    inputs = []
    # Expression 的输入在私有插口里，得钻进去（原生也是这么特判的）
    _connectedInputPlugs(
        dstNode, inputs, ignorePrivate=not isinstance(dstNode, Gaffer.Expression)
    )

    for dstPlug in inputs:

        srcPlug = dstPlug.getInput()
        srcNode = srcPlug.node()
        if srcNode is None:
            continue

        # Gaffer 的 Python 包装对象没有稳定的 `is` 身份（1.7.1.0 实测 `a is a` 为假、
        # `isSame` 为真），一律按名字 + 父级判断。
        parent = srcNode.parent()
        if parent is None or not root.isSame(parent):
            continue
        if srcNode.getName() not in names:
            continue

        srcNodule = nodulePlug(srcNode, srcPlug)
        dstNodule = nodulePlug(dstNode, dstPlug)

        srcTop = srcNodule or topLevelPlug(srcNode, srcPlug)
        dstTop = dstNodule or topLevelPlug(dstNode, dstPlug)
        if srcTop is None or dstTop is None:
            continue

        auxiliary = srcNodule is None or dstNodule is None

        edge = Edge(srcNode, srcTop, dstNode, dstTop, auxiliary)

        if auxiliary:
            # 辅助连线**按端点去重**（原生 AuxiliaryConnectionsGadget 也是一对
            # 端点一条线）：一个表达式驱动同一个节点的三个插口，只画一条。
            k = (
                srcNode.getName(),
                plugKey(srcNode, srcNodule) if srcNodule else "",
                dstNode.getName(),
                plugKey(dstNode, dstNodule) if dstNodule else "",
            )
        else:
            k = edge.key()

        if k in seen:
            continue
        seen.add(k)
        edges.append(edge)


# 连接的合法性 / 目标插口挑选


def _arrayFreeChild(plug):
    """ArrayPlug（Group 的 `in`）要连到第一个空槽上，连 ArrayPlug 本身没意义。"""

    for child in plug.children(Gaffer.Plug):
        if child.getInput() is None:
            return child

    # 全满了 —— Gaffer 会在最后一个被连上时自动加一个新槽，先返回最后一个。
    children = list(plug.children(Gaffer.Plug))
    return children[-1] if children else None


## 把用户指到的插口翻译成真正能 setInput 的那个（ArrayPlug → 空槽）。
def resolveInputPlug(plug):

    if isinstance(plug, Gaffer.ArrayPlug):
        return _arrayFreeChild(plug)
    return plug


## `dstPlug` 能不能接受 `srcPlug`。
def canConnect(srcPlug, dstPlug):

    if srcPlug is None or dstPlug is None:
        return False
    if srcPlug.direction() != Gaffer.Plug.Direction.Out:
        return False
    if dstPlug.direction() != Gaffer.Plug.Direction.In:
        return False
    if srcPlug.node() is not None and dstPlug.node() is not None:
        if srcPlug.node().isSame(dstPlug.node()):
            return False
    if Gaffer.MetadataAlgo.readOnly(dstPlug):
        return False

    target = resolveInputPlug(dstPlug)
    if target is None:
        return False

    return target.acceptsInput(srcPlug)


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
