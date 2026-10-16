"""坐标换算、阈值、配色 —— 整条链的底座，不依赖包内任何东西。"""

from Qt import QtGui

## Gaffer 图单位 → 像素。一律按图单位算，两个视图里节点一样大、疏密一致。
PX_PER_UNIT = 12.0

## 缩放上限 = 原生的 `setMaxPlanarZoom( 25 )`（每个 Gaffer 单位最多 25 像素）。
MAX_ZOOM = 25.0 / PX_PER_UNIT
## 缩小下限（原生没设）。留得很松：2000 个节点铺开约 0.05 倍，框得下。
MIN_ZOOM = 0.02

## 原生 NodeGadget 的尺寸（Gaffer 图单位，1.7.1.0 无头实测 `nodeGadget.bound()`）：
#
#   StandardNodeGadget    11.000 x 4.164   （minWidth 10 + padding 1*2 - border 0.5*2）
#   DotNodeGadget          2.500 x 2.500
#   AuxiliaryNodeGadget    2.000 x 2.000   （Expression / Spreadsheet / Random）
#
# 拿得到原生 GraphGadget 就直接问它要 bound（见 `nodeSizeUnits`），这些只是回退值。
NODE_HEIGHT_UNITS = 4.1640625  # 标准节点高
NODE_MIN_WIDTH_UNITS = 10.0  # `nodeGadget:minWidth` 默认值
NODE_PADDING_UNITS = 1.0  # `nodeGadget:padding` 默认值
NODE_BORDER_UNITS = 0.5  # StandardNodeGadget.cpp 的 g_borderWidth
NODE_TEXT_MARGIN_UNITS = 2.0  # 名字左右两侧的 spacer
SIDE_ROW_UNITS = 1.2  # 左右每多一个接口，节点长高多少（实测 4.8→6.0→7.2）
SIDE_ROWS_BASE_UNITS = 2.4  # 侧边接口区之外的固定高度
DOT_SIZE_UNITS = 2.5
AUX_SIZE_UNITS = 2.0

# 上面那些换算成像素的现成值，给外部（测试 / 调试）对数用。
NODE_HEIGHT = NODE_HEIGHT_UNITS * PX_PER_UNIT  # 约 50px
DOT_SIZE = DOT_SIZE_UNITS * PX_PER_UNIT  # Gaffer.Dot 的直径

NODE_RADIUS = 4.0
ACCENT_HEIGHT = 3.0  # 顶部类型色带（扁平，不做渐变 / 阴影）
GLYPH_SIZE = 16.0  # 节点左侧类型图标（灯泡 / 相机 …）
GLYPH_GAP = 5.0  # 图标和名字之间
NODE_TEXT_MARGIN = 9.0  # 名字距卡片左右边缘
NODE_FONT_SIZE = 10.0

# 连线太长时中段渐隐（Houdini 的做法，避免长线糊满整张图）
WIRE_FADE_START = 260.0  # 短于此不淡化
WIRE_FADE_FULL = 760.0  # 长于此淡到最透
WIRE_FADE_MIN_ALPHA = 38

## 照原生 `StandardNodule::renderLayer`：悬停时半径翻倍 + 换 HighlightColor。
NODULE_RADIUS = 0.5 * PX_PER_UNIT  # 6px
NODULE_HOVER_RADIUS = 1.0 * PX_PER_UNIT  # 12px

## 侧边圆点旁常驻的参数名（材质节点一排圆点，不写名字认不出谁是谁）。
# 颜色跟着圆点走（`nodule:color` 按插口类型注册），类型也是一眼的事。
SIDE_LABEL_GAP = 6.0  # 圆点到文字的距离
SIDE_LABEL_SIZE = 7.5  # 字号（pt）
SIDE_LABEL_MAX = 120.0  # 太长就截断
SIDE_LABEL_MIN_LOD = 0.85  # 比这更小就不写字了，改画一小截色块
SIDE_LABEL_BLOCK_LOD = 0.45  # 再小连色块都不画

# 分栏折叠三角的命中半径。整条 header 行也算命中（Houdini 式），
# 三角只是"卡片边线外那一小块也算"的兜底。
SECTION_TRIANGLE_HIT = 8.0

## 分栏材质节点的顶栏色带高 —— 加宽成标题条，名字 + 图标画在里面、左对齐。
# 行区仍从 `SIDE_ROWS_BASE_UNITS * PX_PER_UNIT`（28.8px）起排，底下留 6.8px 呼吸。
SECTION_TITLE_HEIGHT = 22.0

## 卡内参数名的宽度上限，超了画省略号（完整名字仍在悬停那个放大标签里）。
# 不夹的话 standard_surface 一条 `Transmission Scatter Anisotropy`（粗体 182.8px）
# 就把整卡撑到 274px —— 普通节点 132px 的两倍多。夹了回到 ~190px。
SECTION_LABEL_MAX = 140.0

## 卡内左右两侧标签之间的额外留白，算进卡片宽度。
SECTION_CARD_PAD = 8.0

## 注释画在节点右边（原生 `AnnotationsGadget` 是 `b.max.x + 0.5` 个单位）
ANNOTATION_GAP = 0.5 * PX_PER_UNIT
## 注释的字号和行距（一个节点可以挂好几条，竖着排）
ANNOTATION_SIZE = 7.5
ANNOTATION_LINE_HEIGHT = 12.0
NODULE_HIT_RADIUS = 10.0

## 原生 `PlugAdder::bound()` 是 1x1 图单位的小方块，画成一个 "+"。
ADDER_SIZE = 1.0 * PX_PER_UNIT
ADDER_HIT_RADIUS = 10.0

## focus 折角 tab：卡片右上角外侧的实心三角，**既是指示也是按钮** ——
# 平时不画，悬停出暗折痕，focus 中画成实心亮金。语义照抄原生 `FocusGadget`
# （`StandardNodeGadget.cpp`），样子换掉。
FOCUS_TAB_SIZE = 18.0
## 命中区在折角外面再放宽这么多，而且**按整个方角算、不按三角形斜边算**。
#
# 角标一律画在卡片外面，方角空着的那半边不占卡片上任何可点区域 —— 按斜边判的话
# 可点面积只有方角的一半，最好瞄的地方（三角那两个尖）恰恰最窄，很难点到。
FOCUS_TAB_HIT_PAD = 5.0
## `shape()` 之外那一圈：在光标周围取一小块再捞一遍（和 `adderAt` /
# `sectionHeaderAt` 同一手法）。镜头拉远时角标按 1/lod 长大，会长到 `shape()`
# 盖不住的地方去（shape 是几何、不能跟着 lod 变）。
FOCUS_TAB_HIT_PROBE = 14.0
## 镜头拉远时折角在**屏幕上**至少要有这么大（不然缩成一个点，看不出谁是 focus）
FOCUS_TAB_MIN_PIXELS = 11.0
## 比这个缩放还小，就改画"卡片外面的小旗"（贴着卡片的折角这时候已经看不清了）
FOCUS_FLAG_LOD = 0.55
## 那面小旗在**屏幕上**的大小（按 1/lod 补偿，所以缩放多少都是这么大）
FOCUS_FLAG_PIXELS = 13.0
## 角标 / 小旗的「拉远补偿」到这个 lod 就不再放大了。
#
# 补偿的意思是"屏幕上大小恒定"，做法是在 item 坐标里按 `1/lod` 放大 —— 而
# `boundingRect()` 是几何、只能在 `prepareGeometryChange()` 之后变，画的时候
# 才知道的 lod 没法回头改它。所以补偿必须有下限，否则缩到 `MIN_ZOOM`（0.02）
# 时角标能长到 650px、跑出包围盒 → 拖动留一串金色拖影。
# 取 `LOD_MEDIUM / 2`：到这一档节点自己也只剩十几个像素宽了。
FOCUS_LOD_FLOOR = 0.09
## 书签旗 / 编号拉远时最多放大几倍（包围盒按它留余量）
BOOKMARK_MAX_SCALE = 2.6

## 停用的对角线（原生 `StandardNodeGadget::renderLayer` 的 strike-through）。
STRIKE_WIDTH = 0.5 * PX_PER_UNIT
## 静态停用（`enabled` 是死值）：照原生，参与计算 0.1 灰、不参与 0.2 灰
STRIKE_STATIC = "#1a1a1a"
STRIKE_STATIC_DIM = "#333333"
## 动态停用（`enabled` 要算，ContextTracker 说它关着）：原生画成黄色
STRIKE_DYNAMIC = "#f0dc28"

## 拖到视口边缘时画面自己跟着滚（原生 `ViewportGadget::trackDrag`）。
# 不滚区 = 视口往里缩 `min( min(w,h)/8, DRAG_TRACK_BORDER )` 一圈。
DRAG_TRACK_BORDER = 60.0
DRAG_TRACK_INTERVAL = 16  # ms，一帧一步
DRAG_TRACK_SPEED = 20.0  # 原生 `m_dragTrackingVelocity * duration * 20`

## Backdrop（全部照 `BackdropNodeGadget.cpp`）
#
# 边上这么宽的一条是「拉框改大小」的抓手（原生 `hoverWidth()` 是 raster 5px，
# 命中判定用它的两倍 = 10px；raster 意味着**不随缩放变粗细**，所以这里也用像素）。
BACKDROP_EDGE_HIT = 10.0
## 标题字号，以及给字下缘留的余量（不留就会截掉几个像素）
## 包围盒要比框本身大出这么多：选中时描边 2px 居中画、往外溢 1px，再加抗锯齿。
# 不留这一圈，拉框时每帧都会留一条 1px 的竖线（屏幕上就是一排细条纹）。
BACKDROP_STROKE_MARGIN = 3.0
BACKDROP_TITLE_SIZE = 11.0
BACKDROP_TITLE_SLACK = 3.0
BACKDROP_DESCRIPTION_SIZE = 9.0
## 顶上那条标题条（`g_titleBarHeight` / `g_titleBarMargin`，单位是 Gaffer 单位）。
BACKDROP_TITLE_BAR_HEIGHT = 1.0 * PX_PER_UNIT
BACKDROP_TITLE_BAR_MARGIN = 1.0 * PX_PER_UNIT
## 内容边距（`g_margin`）。
BACKDROP_MARGIN = 3.0 * PX_PER_UNIT
## 拉框最小尺寸（原生 `g_margin * 4`）。
BACKDROP_MIN_SIZE = 12.0 * PX_PER_UNIT
## 上边缘的抓手比别的窄 —— 原生 `min( width, g_titleBarMargin )`，把顶上那条
# 留给「抓着标题条搬动整个 Backdrop」。
BACKDROP_TOP_EDGE_HIT = 1.0 * PX_PER_UNIT
## 原生 StandardStyle 的 HighlightColor（0.466, 0.612, 0.741）：悬停、选中、拖出来的
# 连线、Backdrop 标题条高亮都是这一个色（`StandardStyle.cpp` / `BackdropNodeGadget.cpp`）。
_highlightColor = "#779cbd"
## 标题条颜色：悬停在框身上时高亮，平时是 15% 白。
BACKDROP_TITLE_BAR_HOVER = _highlightColor
BACKDROP_TITLE_BAR_IDLE_ALPHA = 38  # 0.15 * 255
## 层叠：`depth` 插口一档一档挪，同档里**面积大的在后面**（原生按面积 remap 到
# 各自的深度区间，效果就是大框自动垫在小框后面，只有特殊情况才手动设 depth）。
BACKDROP_Z_BASE = -10.0
BACKDROP_Z_DEPTH_STEP = 1.5
BACKDROP_Z_AREA_REFERENCE = (
    1000.0 * PX_PER_UNIT
) ** 2  # 原生 maxLikelyArea = 1000 单位见方

## X 模式下按下与松开差在这么多像素内算"点一下"，否则算划一笔。
CUT_CLICK_SLOP = 4

## 拖连线松手时，光标离卡片这么近就算"丢在这个节点上"（场景像素）。
#
# 圆点是画在**卡片边界上**的（顶边那排还在卡片外 2px），照着圆点丢过去很容易整个落在
# 卡片外面 —— 只问 `nodeItemAt` 的话就"照着圆点丢却接不上"。
CONNECT_REACH = 28.0

## 拖连线时**多近才吸附**到某个接口上（场景像素）。
#
# 原生是"光标一进节点范围就吸到最近那个接得上的接口"（`StandardNodeGadget::dragMove` →
# `closestDragDestination` → `updateDragEndPoint`）。这个太黏：材质节点一排
# 十几个圆点，光标还在卡片中间线头就"啪"地钉到某一个上（常常是最后那个空槽），
# 手上完全不知道会接到哪。所以**线一直跟着鼠标**，只有真的靠近某个类型接得上的圆点
# （这个距离以内）才吸过去 —— 松手时仍照原生：落在节点身上就接最近那个接得上的。
CONNECT_SNAP_DISTANCE = 26.0

## 拖动时的自动对齐：中心线差在这个像素数以内就吸上去，并画一条对齐参考线。
SNAP_DISTANCE = 8.0
# 拖动自动对齐的**感知半径**（像素）：只有这个圈里的节点才有资格当参照，
# 照 Houdini 那套「只看手边最近那个」，不让视野外的节点把手上的节点拽走。
SNAP_RANGE = 360.0
# 参考线画在两个节点之间，两头各多伸出这么点，好看出来是"对上了谁"。
SNAP_GUIDE_OVERSHOOT = 12.0

## 面板里条目不超过这个数就直接平铺（内部快捷键那些菜单一般几十条，多点一层没必要）；
## 超过就按分类分层浏览（Tab 的节点菜单真机 600+ 条，摊平没法用）。
PANEL_FLAT_LIMIT = 50
NODULE_MARGIN = 14.0  # 第一个/最后一个 nodule 距卡片边缘（只在回退布局里用）

# 原生 minimised 连线 = 从 dst nodule 伸出 1.5 个 Gaffer 单位的小尾巴
MINIMISED_STUB = 1.5 * PX_PER_UNIT

# LOD 档位（levelOfDetailFromTransform 的返回值，1.0 = 1:1）
#
# `LOD_MEDIUM` 是"退化成纯色块"的门槛，取 0.18 ——
# 缩到只剩十分之一大小才变色块，之前一直是正常卡片（名字 + 圆点 + 角标）。
LOD_MEDIUM = 0.18  # 以上画名字与 nodule
LOD_NEAR = 0.75  # 以上画阴影 / 顶部色带 / 徽章

# 平移余量：QGraphicsView 会把可视区夹在 sceneRect 里，不放大就「拖不出去」
SCENE_MARGIN = 20000.0

# scene 的 BSP 空间索引深度。Qt 默认按 item 数自动定（600 个 item 约 11 层），
# 可它切的是**整个 sceneRect** —— 上面留了两万像素余量，整张图挤在正中一两个
# 叶子里，每次 `items()` 命中测试等于把全图过一遍。16 层把叶子切到 ~170px
# （42000 / 256），实测 `items( QPoint )` 123us → 23us；内存多几 MB。
BSP_TREE_DEPTH = 16

WIRE_CURVED = "curved"
WIRE_STRAIGHT = "straight"

# 曲线模式的形状参数，量自 Houdini 21 的 `rounded` 连线（见 edge_item._wirePath）。
# Houdini 用「网格单位」，一个节点高 0.495 单位；按节点高换算过来 1 单位 ≈ 101px，
# 也就是 8.4 个 Gaffer 单位。
WIRE_STUB = 2.5 * PX_PER_UNIT  # 出口直段 / 出口圆角半径（Houdini 的 0.30 单位）
WIRE_TURN_SLOPE = 0.42  # 主圆角半径随流向距离增长的斜率（无量纲）
WIRE_TURN_BASE = 4.2 * PX_PER_UNIT  # 主圆角半径的常数项（对着实测点云调出来的）
# 连线绕开两端节点卡片时离卡片留多远（见 edge_item._routeAround）
WIRE_CLEARANCE = 0.75 * PX_PER_UNIT

_internalPlugPrefix = "__"

# 扁平配色：深灰底、单色卡片（不做渐变 / 投影）、顶部类型色带。
# 选中 / 高亮用的是原生 StandardStyle 的 HighlightColor，和原生一个颜色。
_backgroundColor = "#242424"
_gridColor = "#2b2b2b"
_raisedColor = "#666666"  # StandardStyle RaisedColor ( 0.4 )：原生节点/接口的默认色
_cardBorder = "#1e1e1e"
_selectedBorder = _highlightColor
_focusRing = "#f0b64a"
_textColor = "#f2f2f2"
_dimTextColor = "#8a8a8a"
_dragWireColor = _highlightColor
_errorColor = "#cf6058"
_bookmarkColor = "#e0c04a"
_cutColor = "#cf6058"
_snapGuideColor = "#e0c04a"


## focus 之后「不参与计算」的东西怎么变暗 —— 照原生
## `StandardStyle::colorForState( c, DisabledState )`（`StandardStyle.cpp:1331`），
## 但**压得比原生更狠**（照原生的 0.31 亮度看不出区别）。
def _disabledColor(color, connection=False):

    c = QtGui.QColor(color)
    rgb = [c.redF(), c.greenF(), c.blueF()]
    # 连线 0.31 → 0.20、节点混合量 0.75 → 0.85；配合 `_emphasisColor`
    # 把参与计算的提亮，「参与 / 不参与」双向拉开。
    t = 0.55 if connection else 0.85
    rgb = [v + (0.22 - v) * t for v in rgb]

    if connection:
        luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
        if luminance > 1e-6:
            scale = 0.20 / luminance
            rgb = [min(1.0, v * scale) for v in rgb]

    out = QtGui.QColor()
    out.setRgbF(rgb[0], rgb[1], rgb[2])
    return out


## 色带上的文字用深色还是浅色 —— 亮色带（灯光暖黄 / Arnold 橙）上白字看不清。
def _contrastTextColor(color):

    c = QtGui.QColor(color)
    luminance = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return QtGui.QColor("#15171a") if luminance > 0.55 else QtGui.QColor(_textColor)


_backdropColor = "#3a3a3a"
_toolBarColor = "#2c2c2c"


## 「参与 focus 计算」的提亮一档。只在真的设了 focus 时才用。
def _emphasisColor(color):

    c = QtGui.QColor(color)
    rgb = [c.redF(), c.greenF(), c.blueF()]
    rgb = [min(1.0, v + (1.0 - v) * 0.35) for v in rgb]

    out = QtGui.QColor()
    out.setRgbF(rgb[0], rgb[1], rgb[2])
    return out


## 卡片主体 = 节点色往中性灰上混（0 = 全节点色，1 = 全中性灰）。原生直接拿
# `nodeGadget:color` 平涂，一屏下来明暗乱跳、字也糊；混过之后亮度统一、色相还在，
# 顶部色带再用原色提亮。
_cardTintAmount = 0.58
_cardTintTarget = "#3a3a3a"

## 按模块给一个默认色带颜色。`nodeGadget:color` metadata 优先。
_moduleColors = {
    "GafferScene": "#4f9d78",
    "GafferSceneUI": "#4f9d78",
    "GafferImage": "#4a7fb5",
    "GafferArnold": "#c07f3e",
    "GafferOSL": "#8a72c0",
    "GafferDispatch": "#b05f7a",
    "GafferUSD": "#3f9aa8",
    "GafferML": "#8a72c0",
    "Gaffer": "#7d848c",
}
_defaultModuleColor = "#7d848c"

# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
