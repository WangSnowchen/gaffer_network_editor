"""自动排列：分层布局（Sugiyama 前三步）+ 两条 Gaffer 特有的讲究。

原生 `StandardGraphLayout::layoutNodes` 是"贪心找空位"，多节点时横向拉得很宽、
上下层错开、连线来回穿。这里额外做：**按流向分组**（场景竖着流、材质横着流）
和**主干拉直**。
"""

import collections
import contextlib

import imath

import Gaffer


from .graph import *

# 分层布局（Sugiyama 前三步），按 Gaffer 的习惯上→下流：
#
#   1. **分层**：`rank = max( rank(上游) + 1 )`（最长路径），环上的边忽略；
#   2. **定序**：层内按"上一层邻居的重心"来回扫几遍，减少交叉；
#   3. **定位**：按节点**实际宽度**排开，默认用 Brandes–Köpf（四个方向各对齐、压紧
#      一遍，再取中间值；见 `_layoutSpreadBrandesKopf`），可换成 `median` / `tidy`。
#
# 最后整块平移回原来那堆节点的中心，排完不会跳到别处去。

## 竖着流的图（场景节点）：层内相邻节点之间留多少（Gaffer 单位，按节点**边缘**算）
LAYOUT_HORIZONTAL_GAP = 3.0
## 竖着流的图：层与层之间留多少
LAYOUT_VERTICAL_GAP = 5.0
## 横着流的图（材质节点）：列与列之间留多少。**比竖着的宽**——材质节点的参数名是写在
## 卡片**外面**的（`SIDE_LABEL_MAX` 最长 10 个单位），留窄了字会压到左边那列上。
LAYOUT_SHADER_RANK_GAP = 11.0
## 横着流的图：同一列里上下相邻留多少
LAYOUT_SHADER_SPREAD_GAP = 2.0
## 两个流向不同的组之间留多少（材质那一坨和它喂的那个节点之间）
LAYOUT_GROUP_GAP = 6.0
## 判"两个节点是不是真撞上了"时留的余量。**必须比组内的那几个间距都小**：
## 拿 `LAYOUT_GROUP_GAP`（6）去判的话，主干上下相邻两个节点之间只有 5 个单位的空隙，
## 挂在它们旁边的两个 PathFilter 就会被判成"互相撞上"、一个接一个往外让
## （实测五个各自独享 filter 的图，让出 17 / 34 / 17 / 34 / 51 个单位）。
LAYOUT_CLEAR_GAP = 1.0
## 长边打的那些"桩"占多宽（给长连线留一条自己的通道，别压在节点上）
LAYOUT_DUMMY_WIDTH = 1.5
## 节点数（含长边的桩）超过这个数就不做"相邻交换"那步优化（它是 O(层内²)）
LAYOUT_TRANSPOSE_LIMIT = 400
## 定序 / 定位各来回扫几遍（再多收益很小）
LAYOUT_ORDER_SWEEPS = 8
LAYOUT_POSITION_SWEEPS = 8
## 摆开互不相连的那几坨时，一坨最多推几次（推开一次可能又撞上第三坨）
LAYOUT_PACK_PASSES = 8
## 一条线上至少放几个散节点才值得排（一个节点没什么可排的）
LAYOUT_LINE_MIN = 2
## Hilbert 曲线的阶数：中心点量化到 2^N x 2^N 的格子上再排序。
# 16 阶 = 65536 格，实际图里两坨节点极少会落进同一格。
HILBERT_ORDER = 16


## ---------------------------------------------------------------------------
## Sugiyama 三步各自可换实现（跑对照用）
##
## 分层布局是**三个独立的子问题**串起来的，每一步都有好几种成熟做法：
##
##   | 步骤 | 可选 | 说明 |
##   | --- | --- | --- |
##   | `rank`     | `longest-path` / `network-simplex` / `alap` | 谁在第几层 |
##   | `order`    | `barycenter` / `median` / `dfs`            | 层内谁在谁左边 |
##   | `position` | `median` / `brandes-kopf` / `tidy`         | 层内的具体坐标 |
##
## 换实现走 `layoutStrategy( rank = "...", ... )`（上下文管理器），
## 对照数据见 `tests/bench_layout.py`。
LAYOUT_STRATEGY = {
    "rank": "longest-path",
    "order": "barycenter",
    "position": "brandes-kopf",
    # 主干拉直：`align` = 交给定位那一步优先对齐（BK 专属）、`pin` = 事后钉到
    # 一条中线上、`align+pin` = 两个都做（默认）、`off` = 不管
    "spine": "align+pin",
}
## 网络单纯形是 O(V·E) 一轮，超过这么多节点就退回最长路径。
## 它**默认不开**（`rank = "longest-path"`）—— 实测收益只有连线总长 −1.3%、交叉数一个不差，
## 而 600 个节点的稠密图要多花 5 秒。想跑对照把 `rank` 换成 `"network-simplex"`。
LAYOUT_SIMPLEX_NODE_LIMIT = 250
## 网络单纯形最多换几次边（正常图十几次就收敛了）
LAYOUT_SIMPLEX_ITERATIONS = 200


## 临时换掉分层布局的某一步。
@contextlib.contextmanager
def layoutStrategy(**overrides):

    previous = dict(LAYOUT_STRATEGY)
    LAYOUT_STRATEGY.update(overrides)
    try:
        yield dict(LAYOUT_STRATEGY)
    finally:
        LAYOUT_STRATEGY.clear()
        LAYOUT_STRATEGY.update(previous)


## 这个节点是**竖着流**还是**横着流**。
#
# Gaffer 里两种都有，**按插口挂在哪条边**定（`noduleLayout:section`）：场景 / 图像
# 节点 `in` 上 `out` 下 = 竖着流；材质 / OSL 参数在左 `out` 在右 = **横着流**。
# 一律从上往下排的话材质那一坨的连线全得绕大弯。
#
# 判据：**输出圆点挂下边** → 竖着流，**挂右边** → 横着流；一个输出圆点都没有才退回
# 看输入挂哪儿。`ShaderAssignment` 的 `out` 挂下边（`shader` 输入在左也不影响），
# 算竖着流 —— 它是场景流水线上的一环。
def nodeFlowAxis(node):

    # **过路节点**（BoxIn / BoxOut / Dot）自己不定方向：默认按场景那套竖着流，
    # 邻居都朝一个方向时再跟着改（见 `layoutNodes` 里那段）。
    # 不这么办的话，一个提升出来的 `filter` BoxIn（FilterPlug 的圆点挂在左边）
    # 会被当成"材质"拎到材质那一坨里去。
    if isinstance(node, (Gaffer.BoxIO, Gaffer.Dot)):
        return "vertical"

    layout = noduleLayout(node)

    # **判据是"输出圆点挂在哪条边"** —— 这是 Gaffer 里区分场景节点和材质节点最干净的
    # 一条线：场景 / 图像节点的 `out` 挂**下边**、材质（Shader）的 `out` 挂**右边**。
    #
    # 按"有没有输入挂上边"判的话，两类节点都会踩空：
    #   * `OSLCode` 的 `code` 是挂在**上边**的输入圆点 → 被判成场景节点，
    #     整张 OSLCode 材质图的边全成了"侧面喂进来的"，每个节点各自一组
    #     （实测 36 个节点排出 35 组、161 处交叉）；
    #   * `ArnoldDisplacement` 的 `map` / `height` 这些参数也挂**上边**，同样判反。
    outputs = {
        "bottom": [
            p for p in layout["bottom"] if p.direction() == Gaffer.Plug.Direction.Out
        ],
        "right": [
            p for p in layout["right"] if p.direction() == Gaffer.Plug.Direction.Out
        ],
    }
    if outputs["bottom"]:
        return "vertical"
    if outputs["right"]:
        return "horizontal"

    # 没有输出圆点（还没 `setup()` 的 Switch 那种）：退回来看输入挂哪儿
    inputsTop = [p for p in layout["top"] if p.direction() == Gaffer.Plug.Direction.In]
    inputsLeft = [
        p for p in layout["left"] if p.direction() == Gaffer.Plug.Direction.In
    ]
    if inputsLeft and not inputsTop:
        return "horizontal"
    return "vertical"


## 这条边是**顺着流向的主流边**，还是从**侧面**喂进来的（filter / shader 那种）？
#
# 判据就一条：**目的插口挂在哪条边**。竖着流的节点只有挂上下的（`in`/`out`）算主流，
# `filter` 挂右、`shader` 挂左的都是侧面支线。不分开的话
# `PathFilter → ShaderAssignment.filter` 会把 PathFilter 排进主干上一层、把整列挤歪。
def isFlowEdge(dstPlug, axis, dstNode=None):

    # `BoxOut.passThrough`（Box 停用时的直通口）是**脚手架**，不是主流水线上的一环。
    # 算进去的话，喂它的那个 Dot 会被排进主干的某一层、把整列挤歪。
    if dstPlug.getName() == "passThrough" and isinstance(dstPlug.node(), Gaffer.BoxOut):
        return False

    # **过路节点（BoxIn / BoxOut / Dot）的插口都算主流**：它们压根没有"侧面输入"，
    # 而且插口默认挂上下边 —— 一个材质 Box 里它们跟着材质横着流（见
    # `layoutNodes` 里那段"跟邻居走"），这时候再按插口挂哪条边判就把自己判出去了。
    if isinstance(dstPlug.node(), (Gaffer.BoxIO, Gaffer.Dot)):
        return True

    section = plugSection(dstPlug)
    wanted = ("top", "bottom") if axis == "vertical" else ("left", "right")
    if section in wanted:
        return True

    # 节点在**流向那两条边上压根没有输入圆点**时，它挂哪儿哪儿就是主流。
    # `ArnoldDisplacement` 就是这样：`out` 挂右边（所以按材质算、横着流），
    # 可 `map` / `height` 这些参数全挂**上边** —— 不兜这一下它一条主流边都没有，
    # 会被单独拎成一组吊在材质那一坨外面。
    layout = noduleLayout(dstPlug.node() if dstNode is None else dstNode)
    return not any(
        plug.direction() == Gaffer.Plug.Direction.In
        for side in wanted
        for plug in layout[side]
    )


def _layoutRanks(names, predecessors):
    """最长路径分层。环上的边忽略（不然分不出层）。返回 { 名字 : 层号 }。"""

    rank = {}
    state = {}  # 1 = 还在栈上（环），2 = 算完了

    for start in sorted(names):

        if state.get(start) == 2:
            continue

        # 迭代版深度优先：2000 个节点串成一条链时递归版会爆栈
        stack = [(start, False)]
        while stack:

            name, expanded = stack.pop()

            if expanded:
                best = 0
                for parent in predecessors.get(name, ()):
                    if state.get(parent) == 2:
                        best = max(best, rank[parent] + 1)
                rank[name] = best
                state[name] = 2
                continue

            if state.get(name) == 2:
                continue
            if state.get(name) == 1:
                # 环：先给它一个值，别在这儿死等
                rank.setdefault(name, 0)
                continue

            state[name] = 1
            stack.append((name, True))
            for parent in sorted(predecessors.get(name, ())):
                if state.get(parent) is None:
                    stack.append((parent, False))

    return rank


## 尽量**晚**分层（ALAP）：每个节点贴着它最早的那个下游。
#
# 最长路径（ASAP）把所有源头钉在第 0 层 —— 一张贴图直接喂给最下游的 layer_shader 时，
# 它会孤零零留在最上面、拉一条横穿好几层的长边。ALAP 反过来把它贴到消费者头上。
# Houdini 的自动排列就是这个味道（"每个节点就在用它的那个节点上面一格"）。
def _layoutRanksLatest(names, predecessors, successors):

    base = _layoutRanks(names, predecessors)
    if not base:
        return base

    rank = dict(base)
    bottom = max(base.values())

    # 层号从大到小走：下游一定先算完（它们原本的层号更大）
    for name in sorted(names, key=lambda n: (-base.get(n, 0), n)):
        following = [
            rank[s]
            for s in successors.get(name, ())
            if s in rank and base.get(s, 0) > base.get(name, 0)
        ]
        rank[name] = min(following) - 1 if following else bottom

    base = min(rank.values())
    return dict((name, rank[name] - base) for name in rank)


## 网络单纯形分层（Graphviz `dot` 用的那个，Gansner et al. 1993 第 2.3 节）。
#
# 在"每条边至少跨一层"的约束下**最小化 Σ 边跨的层数**。最长路径只保证图最矮，
# 长边有多少不管；网络单纯形直接把长边压到最短 —— 长边少了，打的桩就少，
# 定序那一步要处理的东西也少，交叉数跟着降。
#
# 三步：① 拿最长路径当可行解 → ② 长出一棵**紧树**（树上每条边的 slack 都是 0）→
# ③ 反复找"割值为负"的树边换掉，直到没有为止。割值 = 把这条树边去掉、图裂成两半之后，
# 顺着这条边方向跨过去的边数减去反着跨的边数；为负说明把这半边整体挪一层更省。
def _layoutRanksNetworkSimplex(names, edges, initial):

    rank = dict(initial)
    nodes = sorted(names)
    if len(nodes) > LAYOUT_SIMPLEX_NODE_LIMIT:
        return rank

    # 环上的边在分层里本来就被忽略，这里同样只认"往下走"的
    arcs = sorted(
        set((u, v) for u, v in edges if u != v and rank.get(v, 0) > rank.get(u, 0))
    )
    if not arcs:
        return rank

    adjacency = {}
    for arc in arcs:
        adjacency.setdefault(arc[0], []).append((arc[1], arc))
        adjacency.setdefault(arc[1], []).append((arc[0], arc))

    def slack(arc):
        return rank[arc[1]] - rank[arc[0]] - 1

    tree = set()

    ## 从 seed 出发，沿 slack 为 0 的边能走到哪儿（顺便把走过的边收进 tree）
    def growTight(seed):
        tree.clear()
        seen = {seed}
        stack = [seed]
        while stack:
            current = stack.pop()
            for other, arc in adjacency.get(current, ()):
                if other in seen or slack(arc):
                    continue
                tree.add(arc)
                seen.add(other)
                stack.append(other)
        return seen

    # --- ① 长出一棵覆盖全部节点的紧树 ---
    component = growTight(nodes[0])
    for _ in range(len(nodes)):
        if len(component) >= len(nodes):
            break
        best = None
        for arc in arcs:
            if (arc[0] in component) == (arc[1] in component):
                continue
            value = slack(arc)
            if best is None or value < best[0]:
                best = (value, arc)
        if best is None:
            return dict(initial)  # 光靠"往下走"的边连不通（有环）：不折腾了
        delta, arc = best
        if arc[1] in component:
            delta = -delta
        for name in component:
            rank[name] += delta
        component = growTight(nodes[0])

    if len(component) < len(nodes):
        return dict(initial)

    ## 去掉 leave 之后，树上还和 `leave[0]` 连着的那半
    def tailSide(leave):
        seen = {leave[0]}
        stack = [leave[0]]
        while stack:
            current = stack.pop()
            for other, arc in adjacency.get(current, ()):
                if arc not in tree or arc == leave or other in seen:
                    continue
                seen.add(other)
                stack.append(other)
        return seen

    def cutValue(tail):
        total = 0
        for u, v in arcs:
            if u in tail and v not in tail:
                total += 1
            elif v in tail and u not in tail:
                total -= 1
        return total

    # --- ② 反复换边 ---
    for _ in range(LAYOUT_SIMPLEX_ITERATIONS):

        leave = None
        for arc in sorted(tree):
            tail = tailSide(arc)
            if cutValue(tail) < 0:
                leave = (arc, tail)
                break
        if leave is None:
            break

        arc, tail = leave

        # 进来的那条：从"另一半"回到 tail 这半、slack 最小的
        enter = None
        for candidate in arcs:
            if candidate[0] in tail or candidate[1] not in tail:
                continue
            value = slack(candidate)
            if enter is None or value < enter[0]:
                enter = (value, candidate)
        if enter is None:
            break

        delta, candidate = enter
        if delta:
            for name in tail:
                rank[name] -= delta
        tree.discard(arc)
        tree.add(candidate)

    base = min(rank[name] for name in nodes)
    return dict((name, rank[name] - base) for name in nodes)


## 按 `LAYOUT_STRATEGY["rank"]` 挑一种分层。
def _layoutRankNodes(names, edges, predecessors, successors):

    method = LAYOUT_STRATEGY.get("rank", "longest-path")

    if method == "alap":
        return _layoutRanksLatest(names, predecessors, successors)

    rank = _layoutRanks(names, predecessors)
    if method == "network-simplex":
        return _layoutRanksNetworkSimplex(names, edges, rank)
    return rank


## 两层之间有多少条连线互相交叉（数逆序对，Sugiyama 那套的标准指标）。
def _layerCrossings(upperOrder, lowerOrder, pairs):

    upperIndex = dict((name, index) for index, name in enumerate(upperOrder))
    lowerIndex = dict((name, index) for index, name in enumerate(lowerOrder))

    entries = sorted(
        (upperIndex[u], lowerIndex[v])
        for u, v in pairs
        if u in upperIndex and v in lowerIndex
    )

    # 逆序对用**树状数组**数（Barth–Jünger–Mutzel 那套），别写成两重循环 ——
    # 相邻交换那一步每换一次就要重数一遍，两重循环在稠密图上是 O(边²)：
    # 实测 300 个节点的稠密图光这一项就 4.9 秒。
    size = len(lowerOrder)
    tree = [0] * (size + 1)
    count = 0
    placed = 0
    for _unused, lower in entries:
        index = lower + 1
        smallerOrEqual = 0
        while index > 0:
            smallerOrEqual += tree[index]
            index -= index & -index
        count += placed - smallerOrEqual
        placed += 1
        index = lower + 1
        while index <= size:
            tree[index] += 1
            index += index & -index

    return count


## 某一层和它上下两层之间的交叉数（相邻交换那一步只需要看这么多）。
def _rowCrossings(rank, members, layerPairs):

    total = 0
    if rank - 1 in members:
        total += _layerCrossings(
            members[rank - 1], members[rank], layerPairs.get(rank - 1, [])
        )
    if rank + 1 in members:
        total += _layerCrossings(
            members[rank], members[rank + 1], layerPairs.get(rank, [])
        )
    return total


## 一行节点里**钉住某一个**，其余的往两边推开（主干拉直用）。
def _layoutRowPinned(members, spreads, extents, gap, pinned, position):

    result = dict(spreads)
    if pinned not in members:
        return result

    index = members.index(pinned)
    result[pinned] = position

    for i in range(index - 1, -1, -1):
        limit = (
            result[members[i + 1]]
            - (extents[members[i + 1]] + extents[members[i]]) / 2.0
            - gap
        )
        result[members[i]] = min(result[members[i]], limit)

    for i in range(index + 1, len(members)):
        limit = (
            result[members[i - 1]]
            + (extents[members[i - 1]] + extents[members[i]]) / 2.0
            + gap
        )
        result[members[i]] = max(result[members[i]], limit)

    return result


## 图里**最长的那条流水线**（按层数），返回节点名列表。给主干拉直用。
def _layoutSpine(names, edges):

    successors = {}
    predecessors = {}
    for src, dst in edges:
        successors.setdefault(src, []).append(dst)
        predecessors.setdefault(dst, []).append(src)

    rank = _layoutRanks(names, predecessors)

    # 按层号从小到大做 DP：depth = 1 + 最深的上游
    depth = {}
    parent = {}
    for name in sorted(names, key=lambda n: (rank.get(n, 0), n)):
        best, bestParent = 0, None
        for previous in sorted(predecessors.get(name, ())):
            if rank.get(previous, 0) >= rank.get(name, 0):
                continue  # 环上的边不算
            if depth.get(previous, 0) > best:
                best, bestParent = depth[previous], previous
        depth[name] = best + 1
        parent[name] = bestParent

    if not depth:
        return []

    end = sorted(names, key=lambda n: (-depth[n], n))[0]
    spine = []
    while end is not None:
        spine.append(end)
        end = parent.get(end)
    spine.reverse()

    return spine


## 一行节点：给定"每个节点想去的位置"，在**保持顺序、不重叠**的前提下尽量满足它。
#
# 左→右扫一遍消重叠，再整行平移把平均误差抹掉 —— 不平移的话一行会被最左边那个
# 顶着一路往右漂。
def _layoutRow(members, desired, extents, gap):

    if not members:
        return {}

    positions = []
    for index, name in enumerate(members):
        want = desired[index]
        if index:
            previous = members[index - 1]
            want = max(
                want, positions[-1] + (extents[previous] + extents[name]) / 2.0 + gap
            )
        positions.append(want)

    offset = sum(d - x for d, x in zip(desired, positions)) / float(len(positions))

    return dict((name, x + offset) for name, x in zip(members, positions))


## 长边打桩：跨了好几层的边（材质图里到处都是：一张贴图直接喂给最下游那个
# layer_shader）如果不管，定序那一步压根"看不见"它，于是它横穿好几行、把交叉数拉爆
# （实测：不打桩 130 处交叉，打桩之后比原生少一半）。
#
# 返回 ( 加了桩的层号, 加了桩的宽度, 桩的名字集合, 桩属于哪条边, 逐层相连的边 )。
def _layoutDummies(names, edges, rank, extent):

    workRank = dict(rank)
    workExtent = dict((name, extent(name)) for name in names)
    dummies = set()
    dummyEdge = {}
    segments = []

    for src, dst in sorted(edges):

        a, b = src, dst
        if workRank[b] < workRank[a]:
            a, b = b, a  # 环上的反向边：翻过来只为排版
        if workRank[b] - workRank[a] <= 1:
            segments.append((a, b))
            continue

        previous = a
        for r in range(workRank[a] + 1, workRank[b]):
            name = "__layoutDummy%d_%d" % (len(dummies), r)
            dummies.add(name)
            dummyEdge[name] = (a, b)
            workRank[name] = r
            workExtent[name] = LAYOUT_DUMMY_WIDTH
            segments.append((previous, name))
            previous = name
        segments.append((previous, b))

    return workRank, workExtent, dummies, dummyEdge, segments


## `dot` 的加权中位数（Gansner et al. 1993 的 `medianvalue`）。
#
# 重心（平均）会被一个跑得很远的邻居整个拽走，中位数不会。偶数个邻居时按左右两半的
# 跨度加权插值 —— 邻居挤在左边就往左靠。没有邻居返回 None（调用方保持原位）。
def _layoutMedianValue(positions):

    positions = sorted(positions)
    count = len(positions)

    if not count:
        return None
    if count % 2:
        return float(positions[count // 2])
    if count == 2:
        return (positions[0] + positions[1]) / 2.0

    left = positions[count // 2 - 1] - positions[0]
    right = positions[-1] - positions[count // 2]
    if left + right == 0:
        return (positions[count // 2 - 1] + positions[count // 2]) / 2.0
    return (positions[count // 2 - 1] * right + positions[count // 2] * left) / (
        left + right
    )


## 按**插口顺序**深度优先走一遍，给层内一个初始次序。
#
# Houdini 的自动排列就只做到这儿：不管交叉，只保证 `in0` 在 `in1` 左边、
# 一棵子树连着摆。`inputOrder( name )` 给出这个节点的上游**按圆点从左到右**的顺序。
# 返回 { 名字 : 序号 }，桩按它所属那条边的两端定序。
def _layoutDfsSequence(names, inputOrder, successorNames, dummyEdge):

    sinks = [name for name in sorted(names) if not successorNames.get(name)]
    if not sinks:
        sinks = sorted(names)

    sequence = {}
    visited = set()
    for sink in sinks:
        stack = [sink]
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            sequence[name] = len(sequence)
            # 反着压栈，弹出来才是插口从左到右的顺序
            for source in reversed(inputOrder(name)):
                if source not in visited:
                    stack.append(source)

    for name in sorted(names):
        if name not in visited:
            visited.add(name)
            sequence[name] = len(sequence)

    # 桩：跟着它那条边的起点走，同一条边上的桩再按层号排开
    for name, (src, dst) in sorted(dummyEdge.items()):
        sequence[name] = sequence.get(src, 0) + 0.5

    return sequence


## 定序：重心法来回扫，**留下交叉最少的那一遍**。members 原地更新，返回最好那一遍。
def _layoutOrderRows(
    members, ranks, dummies, segments, workRank, originalSpread, sequence=None
):

    workSuccessors = {}
    workPredecessors = {}
    for a, b in segments:
        workSuccessors.setdefault(a, set()).add(b)
        workPredecessors.setdefault(b, set()).add(a)

    method = LAYOUT_STRATEGY.get("order", "barycenter")
    # "dfs" = 按插口顺序深度优先当初始次序；"-" 后面是精修方法（没有就是不精修）
    refine = method.split("-")[-1] if "-" in method else method
    if method == "dfs":
        refine = "none"

    # 层内初始顺序：按原来的位置（用户已经摆出来的相对关系尽量留着），
    # 或者按插口顺序的深度优先序（Houdini 那种）
    for r in ranks:
        if method.startswith("dfs") and sequence is not None:
            members[r].sort(key=lambda n: (sequence.get(n, 0.0), n))
        else:
            members[r].sort(
                key=lambda n: (originalSpread(n) if n not in dummies else 0.0, n)
            )

    if refine == "none":
        return (
            dict((r, list(members[r])) for r in ranks),
            workPredecessors,
            workSuccessors,
        )

    layerPairs = {}
    for a, b in segments:
        if workRank[b] == workRank[a] + 1:
            layerPairs.setdefault(workRank[a], []).append((a, b))

    def totalCrossings(order):
        total = 0
        for index in range(len(ranks) - 1):
            r = ranks[index]
            if ranks[index + 1] != r + 1:
                continue
            total += _layerCrossings(order[r], order[r + 1], layerPairs.get(r, []))
        return total

    best = dict((r, list(members[r])) for r in ranks)
    bestCrossings = totalCrossings(members)
    total = sum(len(members[r]) for r in ranks)

    for sweep in range(LAYOUT_ORDER_SWEEPS):

        downward = sweep % 2 == 0
        order = ranks if downward else list(reversed(ranks))
        neighbours = workPredecessors if downward else workSuccessors

        indices = {}
        for r in ranks:
            for index, name in enumerate(members[r]):
                indices[name] = float(index)

        for r in order:
            current = members[r]
            keys = {}
            for index, name in enumerate(current):
                values = [indices[m] for m in neighbours.get(name, ()) if m in indices]
                if refine == "median":
                    value = _layoutMedianValue(values)
                else:
                    value = sum(values) / float(len(values)) if values else None
                keys[name] = float(index) if value is None else value
            members[r] = sorted(current, key=lambda n: (keys[n], n))
            for index, name in enumerate(members[r]):
                indices[name] = float(index)

        # **相邻交换**（Sugiyama 的第三步）：同一层里相邻两个换个位置，交叉少了就留着。
        if total <= LAYOUT_TRANSPOSE_LIMIT:
            _layoutTranspose(members, ranks, layerPairs)

        count = totalCrossings(members)
        if count < bestCrossings:
            bestCrossings = count
            best = dict((r, list(members[r])) for r in ranks)

    return best, workPredecessors, workSuccessors


## 相邻交换：同一层里相邻两个换个位置，交叉少了就留着（members 原地改）。
def _layoutTranspose(members, ranks, layerPairs):

    for _ in range(2):
        improved = False
        for r in ranks:
            row = members[r]
            # 循环里只有这一行在变，换之前的交叉数就是上一次留下来的那个数
            current = _rowCrossings(r, members, layerPairs)
            for index in range(len(row) - 1):
                row[index], row[index + 1] = row[index + 1], row[index]
                after = _rowCrossings(r, members, layerPairs)
                if after < current:
                    current = after
                    improved = True
                else:
                    row[index], row[index + 1] = row[index + 1], row[index]
        if not improved:
            break


## 定位：层内先摊开，再来回把每个节点拉向邻居的中位数。返回 { 名字 : 横向位置 }。
def _layoutSpread(
    members, ranks, workExtent, workPredecessors, workSuccessors, spreadGap
):

    spread = {}
    for r in ranks:
        position = 0.0
        for index, name in enumerate(members[r]):
            if index:
                position += (
                    workExtent[members[r][index - 1]] + workExtent[name]
                ) / 2.0 + spreadGap
            spread[name] = position

    def median(values):
        values = sorted(values)
        count = len(values)
        if not count:
            return None
        if count % 2:
            return values[count // 2]
        return (values[count // 2 - 1] + values[count // 2]) / 2.0

    for sweep in range(LAYOUT_POSITION_SWEEPS):

        downward = sweep % 2 == 0
        order = ranks if downward else list(reversed(ranks))
        neighbours = workPredecessors if downward else workSuccessors

        for r in order:
            current = members[r]
            desired = []
            for name in current:
                value = median(
                    [spread[m] for m in neighbours.get(name, ()) if m in spread]
                )
                desired.append(value if value is not None else spread[name])
            spread.update(_layoutRow(current, desired, workExtent, spreadGap))

    return spread


## Brandes–Köpf 定位（"Fast and Simple Horizontal Coordinate Assignment", GD 2001）。
#
# 中位数来回扫是个**启发式**：长边的桩链每一节都被两边拉扯，扫完仍是一条折线。
# BK 反过来先决定"谁和谁必须对齐"（连成一个 block），再整块一起摆 —— 桩链天生
# 落进同一个 block，于是**长边是一条笔直的线**。
#
# 四遍（上/下 × 左/右）各得一组坐标，最后取中间两个的平均，抵消单方向的偏心。
def _layoutSpreadBrandesKopf(
    members,
    ranks,
    workExtent,
    workPredecessors,
    workSuccessors,
    spreadGap,
    dummies,
    preferred=(),
):

    layerOf = {}
    for r in ranks:
        for name in members[r]:
            layerOf[name] = r

    ## 层内相邻两个之间至少留多少（按各自真实宽度）
    def separation(left, right):
        return (workExtent[left] + workExtent[right]) / 2.0 + spreadGap

    # --- ① 标记"一型冲突"：长边的桩链和普通边打架时，让桩链赢（长边优先走直线）---
    conflicts = set()
    index = {}
    for r in ranks:
        for i, name in enumerate(members[r]):
            index[name] = i

    for i in range(len(ranks) - 1):

        r = ranks[i]
        if ranks[i + 1] != r + 1:
            continue
        upper, lower = members[r], members[r + 1]

        def uppers(name, r=r):
            return sorted(
                index[u] for u in workPredecessors.get(name, ()) if layerOf.get(u) == r
            )

        k0, l = 0, 0
        for l1, v in enumerate(lower):

            innerUpper = None
            if v in dummies:
                for u in workPredecessors.get(v, ()):
                    if layerOf.get(u) == r and u in dummies:
                        innerUpper = index[u]

            if l1 == len(lower) - 1 or innerUpper is not None:
                k1 = innerUpper if innerUpper is not None else len(upper) - 1
                while l <= l1:
                    for k in uppers(lower[l]):
                        if k < k0 or k > k1:
                            conflicts.add((upper[k], lower[l]))
                    l += 1
                k0 = k1

    # --- ② 一个方向的对齐 + 压紧 ---
    def alignment(view, viewIndex, downward):

        root = dict((name, name) for name in layerOf)
        align = dict((name, name) for name in layerOf)

        layers = ranks if downward else list(reversed(ranks))
        neighbours = workPredecessors if downward else workSuccessors

        for r in layers:

            previous = r - 1 if downward else r + 1
            if previous not in members:
                continue

            lastPosition = -1
            for v in view[r]:

                positions = sorted(
                    viewIndex[u]
                    for u in neighbours.get(v, ())
                    if layerOf.get(u) == previous
                )
                if not positions:
                    continue

                # **中位数 = "到所有邻居的总横向偏移最小"那个位置**（L1 中心）。
                # 偶数个邻居有两个中位数，都同样最优 —— 那是 BK 自带的自由度。
                count = len(positions)
                candidates = [positions[(count - 1) // 2]]
                if count % 2 == 0:
                    candidates.append(positions[count // 2])

                # 试过 dot 那套边权（桩—桩 8 / 桩—真 2 / 真—真 1）做**加权**中位数：
                # 长边总偏移 −7%，但主干上"头一个节点同时喂着一条长边"时长边会把它
                # 从主干那一列拽走（bench：主干直 72→69）。长边跨好几行、歪一点看着
                # 还行，一条五个节点的主干断在头上很显眼 —— 所以留普通中位数，长边
                # 靠 BK 自己那套"一型冲突让桩链赢"来拉直。
                # **主干那条边只在中位数之间做取舍，不许越过中位数**。
                #
                # 中位数是"到所有邻居的总横向偏移最小"那个位置（L1 中心）——
                # 6 个 Sphere 喂一个 Group 时，Group 待在这一排正中间总偏移 126，
                # 贴到最左边那个 Sphere 身上是 210。主干（最长那条流水线）随便挑一路
                # 上游就把 Group 拽过去，整条下游跟着歪，这不是"拉直"是"贴边"。
                # 偶数个邻居本来就有两个中位数（BK 的自由度），主干那条边正好用来
                # 决定挑哪个 —— 这是它该管的范围。
                if preferred and len(candidates) > 1:
                    front = [
                        p
                        for p in candidates
                        if (
                            (view[previous][p], v)
                            if downward
                            else (v, view[previous][p])
                        )
                        in preferred
                    ]
                    candidates = front + [m for m in candidates if m not in front]

                for m in candidates:
                    if align[v] != v:
                        break
                    u = view[previous][m]
                    edge = (u, v) if downward else (v, u)
                    if edge in conflicts or m <= lastPosition:
                        continue
                    align[u] = v
                    root[v] = root[u]
                    align[v] = root[v]
                    lastPosition = m

        return root, align

    def compaction(view, viewIndex, root, align):

        blocks = {}
        for name in sorted(layerOf):
            if root[name] != name:
                continue
            chain = []
            current = name
            while True:
                chain.append(current)
                current = align[current]
                if current == name:
                    break
            blocks[name] = chain

        sink = dict((name, name) for name in blocks)
        shift = dict((name, None) for name in blocks)
        x = {}
        cursor = {}

        ## 摆一个 block（`place_block` 的迭代版 —— 一条长链的 block 递归会很深）
        def placeBlock(start):

            stack = [start]
            while stack:

                v = stack[-1]
                if v not in x:
                    x[v] = 0.0
                    cursor[v] = 0

                pushed = False
                while cursor[v] < len(blocks[v]):

                    w = blocks[v][cursor[v]]
                    position = viewIndex[w]
                    if position > 0:
                        left = view[layerOf[w]][position - 1]
                        u = root[left]
                        if u not in x:
                            stack.append(u)
                            pushed = True
                            break
                        delta = separation(left, w)
                        if sink[v] == v:
                            sink[v] = sink[u]
                        if sink[v] != sink[u]:
                            candidate = x[v] - x[u] - delta
                            current = shift[sink[u]]
                            shift[sink[u]] = (
                                candidate
                                if current is None
                                else min(current, candidate)
                            )
                        else:
                            x[v] = max(x[v], x[u] + delta)
                    cursor[v] += 1

                if not pushed:
                    stack.pop()

        for name in sorted(blocks):
            placeBlock(name)

        result = {}
        for name in layerOf:
            block = root[name]
            value = x[block]
            offset = shift.get(sink[block])
            if offset is not None:
                value += offset
            result[name] = value
        return result

    # --- ③ 四遍：上/下 × 左/右（"右"= 把每层反过来排、算完再取负）---
    candidates = []
    for downward in (True, False):
        for mirrored in (False, True):

            view = dict(
                (r, list(reversed(members[r])) if mirrored else list(members[r]))
                for r in ranks
            )
            viewIndex = {}
            for r in ranks:
                for i, name in enumerate(view[r]):
                    viewIndex[name] = i

            root, align = alignment(view, viewIndex, downward)
            values = compaction(view, viewIndex, root, align)
            if mirrored:
                values = dict((name, -value) for name, value in values.items())
            candidates.append((mirrored, values))

    # --- ④ 对齐四组结果（各自平移到最窄那组的边界上），逐点取中间两个的平均 ---
    widths = [max(v.values()) - min(v.values()) for _, v in candidates]
    reference = candidates[widths.index(min(widths))][1]
    low, high = min(reference.values()), max(reference.values())

    aligned = []
    for mirrored, values in candidates:
        offset = (
            (high - max(values.values())) if mirrored else (low - min(values.values()))
        )
        aligned.append(dict((name, value + offset) for name, value in values.items()))

    spread = {}
    for name in layerOf:
        values = sorted(candidate[name] for candidate in aligned)
        spread[name] = (values[1] + values[2]) / 2.0

    return spread


## 树式定位（Houdini 的味道）：每个节点摆在它上游的正中间，撞到左边的就往右让。
#
# 和中位数那套的区别是**不做整行回中**（`_layoutRow` 会把一行整体平移把误差摊掉）——
# 树式的每一层都是从左往右一个挨一个码过去，看起来更像"一棵树"，代价是主干容易右漂。
def _layoutSpreadTidy(
    members, ranks, workExtent, workPredecessors, workSuccessors, spreadGap
):

    spread = {}

    for sweep in range(LAYOUT_POSITION_SWEEPS):

        downward = sweep % 2 == 0
        order = ranks if downward else list(reversed(ranks))
        neighbours = workPredecessors if downward else workSuccessors

        contour = None
        for r in order:
            contour = None
            for name in members[r]:
                values = [spread[m] for m in neighbours.get(name, ()) if m in spread]
                half = workExtent[name] / 2.0
                want = (sum(values) / float(len(values)) - half) if values else None
                if contour is not None:
                    want = contour if want is None else max(want, contour)
                elif want is None:
                    want = spread.get(name, 0.0) - half
                contour = want + workExtent[name] + spreadGap
                spread[name] = want + half

    return spread


## 按 `LAYOUT_STRATEGY["position"]` 挑一种定位。
def _layoutSpreadNodes(
    members,
    ranks,
    workExtent,
    workPredecessors,
    workSuccessors,
    spreadGap,
    dummies,
    preferred=(),
):

    method = LAYOUT_STRATEGY.get("position", "median")

    if method == "brandes-kopf":
        return _layoutSpreadBrandesKopf(
            members,
            ranks,
            workExtent,
            workPredecessors,
            workSuccessors,
            spreadGap,
            dummies,
            preferred,
        )
    if method == "tidy":
        return _layoutSpreadTidy(
            members,
            ranks,
            workExtent,
            workPredecessors,
            workSuccessors,
            spreadGap,
        )
    return _layoutSpread(
        members, ranks, workExtent, workPredecessors, workSuccessors, spreadGap
    )


## 一种摆法的"总横向偏移"（逐层相连的边，含长边的桩）。
#
# 各边同权，和定位那一步的**普通**中位数保持一致。试过 dot 的边权（桩—桩 8 /
# 桩—真 2 / 真—真 1），bench 上一个数都不差，但"主干头一个节点同时喂着一条长边"
# 时长边会把它拽出主干那一列。
def _layoutDeviation(segments, spread):

    total = 0.0
    for a, b in segments:
        if a in spread and b in spread:
            total += abs(spread[a] - spread[b])
    return total


## 主干拉直：分层 + 定位之后，主干上的节点还是会被同层的旁支挤得左右错开，
# 而主流水线应该是一条**直溜溜的竖列**。做法：找出最长的那条
# 流水线，把它上面每个节点都钉到同一条中线上，同层其它节点往两边推开。
#
# 两道闸，缺一个就会把"扇入该居中"排成"扇入贴到某一路上"：
def _layoutStraightenSpine(
    names,
    edges,
    spread,
    members,
    workRank,
    workExtent,
    spreadGap,
    segments,
    spineNames=None,
):

    if spineNames is None:
        spineNames = _layoutSpine(list(names), edges)
    if len(spineNames) < 3:
        return

    # ① **主干在扇入那儿断开**：一个节点有好几路同流向的输入（Group 的 6 个 Sphere）时
    # 它该待在那几路的正中间；硬钉到主干那条线上 = 把它贴到某一路身上，而且
    # `_layoutRowPinned` 会把同层邻居一起推走 —— 整排上游跟着漂。断开之后每段各自钉到
    # **自己那几个节点**的中线上：一条长主干中间夹一个 Group 时两头照样各自拉直，
    # Group 留在它那一排的正中间。
    # 扇**出**（一个源喂十几路）不在这儿断，交给下面那道闸。
    inDegree = {}
    for _unused, dst in edges:
        inDegree[dst] = inDegree.get(dst, 0) + 1

    runs = []
    current = []
    for name in spineNames:
        if inDegree.get(name, 0) <= 1:
            current.append(name)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)

    for run in runs:
        values = sorted(spread[name] for name in run if name in spread)
        if not values:
            continue
        centre = values[len(values) // 2]

        trial = dict(spread)
        for name in run:
            r = workRank.get(name)
            if r is None or r not in members:
                continue
            trial.update(
                _layoutRowPinned(members[r], trial, workExtent, spreadGap, name, centre)
            )

        # ② **总偏移不许上升**。硬推很贵（同层邻居被一起推走），而定位那一步已经是
        # 对齐过的解了 —— 拉直只该补它"一个节点只能跟一个邻居对齐"留下的零头。
        # 一个源扇出到十几路时（`wide-fan`）这道闸会直接否掉，源就留在正中间。
        if (
            _layoutDeviation(segments, trial)
            > _layoutDeviation(segments, spread) + 1e-6
        ):
            continue

        spread.clear()
        spread.update(trial)


## 把一个**流向一致**的连通分量排好。返回 { 名字 : ( 沿流向的坐标, 垂直流向的坐标 ) }。
#
# 分层布局（Sugiyama 的前三步）：分层 → 长边打桩 → 定序 → 定位，每一步用哪种实现
# 看 `LAYOUT_STRATEGY`。`thickness` 是节点在**流向**上的尺寸、`extent` 是垂直流向上的。
def _layoutComponent(
    names, edges, thickness, extent, rankGap, spreadGap, originalSpread, inputOrder=None
):

    predecessors = {}
    successors = {}
    for src, dst in edges:
        predecessors.setdefault(dst, set()).add(src)
        successors.setdefault(src, set()).add(dst)

    rank = _layoutRankNodes(names, edges, predecessors, successors)

    workRank, workExtent, dummies, dummyEdge, segments = _layoutDummies(
        names, edges, rank, extent
    )

    members = {}
    for name in list(names) + sorted(dummies):
        members.setdefault(workRank.get(name, 0), []).append(name)
    ranks = sorted(members)

    sequence = None
    if LAYOUT_STRATEGY.get("order", "").startswith("dfs"):
        order = inputOrder or (lambda n: sorted(predecessors.get(n, ())))
        sequence = _layoutDfsSequence(names, order, successors, dummyEdge)

    members, workPredecessors, workSuccessors = _layoutOrderRows(
        members, ranks, dummies, segments, workRank, originalSpread, sequence
    )

    # 主干（最长那条流水线）：`spine = "align"` 时交给 BK 优先对齐、
    # `"pin"` 时事后把它钉到一条中线上、`"off"` 就不管。
    spineMode = LAYOUT_STRATEGY.get("spine", "align")
    preferred = set()
    spineNames = None  # `_layoutSpine` 要重跑一遍分层，两步共用一份
    if spineMode in ("align", "align+pin"):
        spineNames = _layoutSpine(list(names), edges)
        spineEdges = set(zip(spineNames, spineNames[1:]))
        for a, b in segments:
            real = dummyEdge.get(a) or dummyEdge.get(b) or (a, b)
            if real in spineEdges or (real[1], real[0]) in spineEdges:
                preferred.add((a, b))

    spread = _layoutSpreadNodes(
        members,
        ranks,
        workExtent,
        workPredecessors,
        workSuccessors,
        spreadGap,
        dummies,
        preferred,
    )

    if spineMode in ("pin", "align+pin"):
        _layoutStraightenSpine(
            names,
            edges,
            spread,
            members,
            workRank,
            workExtent,
            spreadGap,
            segments,
            spineNames,
        )

    # --- 沿流向：一层一"行"，行厚度按这一层最厚的**真节点**算 ---
    along = 0.0
    rankAlong = {}
    for r in ranks:
        values = [thickness(name) for name in members[r] if name not in dummies]
        size = max(values) if values else 1.0
        rankAlong[r] = along + size / 2.0
        along += size + rankGap

    result = {}
    for r in ranks:
        for name in members[r]:
            if name in dummies:
                continue
            result[name] = (rankAlong[r], spread[name])

    return result


## 格点 `(x, y)` 在 Hilbert 曲线上排第几（逐条抄标准的 `xy2d`）。
#
# Hilbert 曲线是条**空间填充曲线**：把二维格子串成一条一笔画的线，且**空间上挨着的
# 格子在线上也挨着**（这一点比 Z-order / Morton 强，后者每跨一个象限就跳一大步）。
# 拿它的下标排序 = "空间近的排完也近"，摆开互不相连的那几坨时就是要这个性质。
def hilbertIndex(x, y, order=HILBERT_ORDER):

    side = 1 << order
    x = max(0, min(side - 1, int(x)))
    y = max(0, min(side - 1, int(y)))

    index = 0
    s = side >> 1
    while s > 0:

        rx = 1 if (x & s) > 0 else 0
        ry = 1 if (y & s) > 0 else 0
        index += s * s * ((3 * rx) ^ ry)

        # 每往下一层要把这个象限"转正"，不转的话四段拼不成一条连续的线
        if ry == 0:
            if rx == 1:
                x = side - 1 - x
                y = side - 1 - y
            x, y = y, x

        s >>= 1

    return index


## 把一批东西按 Hilbert 曲线序排好。`position(item)` 给 `imath.V2f`。
#
# 先按所有点的包围盒把坐标量化到格子上（图坐标是浮点、还可能是负的，直接取整不行）。
# 包围盒退化（所有点重合、或只有一个点）时那一维一律取 0。
# `key(item)` 给同格的做稳定的次级排序 —— 少了它，同一格里的先后跟着 dict 顺序跑。
def hilbertSorted(items, position, key=None):

    items = list(items)
    if len(items) < 2:
        return items

    points = dict((index, position(item)) for index, item in enumerate(items))
    minX = min(p.x for p in points.values())
    maxX = max(p.x for p in points.values())
    minY = min(p.y for p in points.values())
    maxY = max(p.y for p in points.values())

    side = 1 << HILBERT_ORDER

    def quantise(value, low, high):
        if high - low < 1e-9:
            return 0
        return int((value - low) / (high - low) * (side - 1))

    def sortKey(pair):
        index, item = pair
        point = points[index]
        return (
            hilbertIndex(quantise(point.x, minX, maxX), quantise(point.y, minY, maxY)),
            key(item) if key is not None else index,
        )

    return [item for _, item in sorted(enumerate(items), key=sortKey)]


## 一个组和已经摆好的那些组撞上了没？撞了就沿 `direction` 推开，返回要额外挪多少。
def _layoutPushClear(rects, placed, direction, gap=LAYOUT_GROUP_GAP):

    shift = imath.V2f(0, 0)

    for bounds in rects:
        for other in placed:

            # 先看是不是真的重叠。**判的余量（`LAYOUT_CLEAR_GAP`）和推开的间距
            # （`gap`）是两回事**：判得太宽就会把"本来挨着但没压上"的也算成撞上。
            if (
                bounds[1] + shift.x <= other[0] - LAYOUT_CLEAR_GAP
                or bounds[0] + shift.x >= other[1] + LAYOUT_CLEAR_GAP
                or bounds[3] + shift.y <= other[2] - LAYOUT_CLEAR_GAP
                or bounds[2] + shift.y >= other[3] + LAYOUT_CLEAR_GAP
            ):
                continue

            if direction.x < 0:
                shift.x = min(shift.x, other[0] - gap - bounds[1])
            elif direction.x > 0:
                shift.x = max(shift.x, other[1] + gap - bounds[0])
            elif direction.y > 0:
                shift.y = max(shift.y, other[3] + gap - bounds[2])
            else:
                shift.y = min(shift.y, other[2] - gap - bounds[3])

    return shift


## 一坨要挪到哪儿才不和已经摆好的那些撞上：四个方向**各推到底**，取总位移最小的落点。
#
# `rects` / `placed` 都是**逐个节点**的矩形列表，不是整组的包围盒（见 `nodeRects`）。
#
# `_layoutPushClear` 一次只认一个方向（挂钩那条路有"该往哪边挂"的先验），而互不相连
# 的那几坨没有先验，只能哪边近往哪边让 —— 这样每坨都尽量待在用户原来摆的地方。
#
# **比的是"推到底以后"的总位移，不是单次推多少**：单次推最少的那个方向后面可能还要
# 再推好几次，一路滚出去反而更远。实测四坨横着排开时，"每次挑最近"会把最右边那坨
# 从最右一路挤到最左边（位移 41），而"推到底再比"就是往右让一格（位移 27）。
def _layoutPackOffset(offset, rectsFor, placed):

    best = None
    bestDistance = None

    for direction in (
        imath.V2f(-1, 0),
        imath.V2f(1, 0),
        imath.V2f(0, 1),
        imath.V2f(0, -1),
    ):
        candidate = imath.V2f(offset)
        clear = False

        for _ in range(LAYOUT_PACK_PASSES):
            shift = _layoutPushClear(rectsFor(candidate), placed, direction)
            if shift.length() < 1e-6:
                clear = True
                break
            candidate = candidate + shift

        if not clear:
            continue  # 推了这么多次还没干净，这条路不算

        distance = (candidate - offset).length()
        if bestDistance is None or distance < bestDistance - 1e-9:
            best, bestDistance = candidate, distance

    return best if best is not None else offset


## 纯"过路"的节点（BoxIn / BoxOut / Dot）跟着邻居走。
#
# `BoxIn` / `BoxOut` 的插口默认挂上下边（竖着流），但一个**材质 Box** 里它们串的是
# 一条横着流的材质链 —— 照默认判就会被单独拎成一组、吊在材质那一坨的上下方。
# 它们本身没有"自己的方向"，
# 邻居都朝一个方向就跟着走。Dot 同理。`axes` 原地更新。
def _layoutPassThroughAxes(byName, axes, allEdges):

    passThrough = set(
        name
        for name, node in byName.items()
        if isinstance(node, (Gaffer.BoxIO, Gaffer.Dot))
    )
    if not passThrough:
        return

    neighbours = {}
    for src, dst, _unused in allEdges:
        neighbours.setdefault(src, set()).add(dst)
        neighbours.setdefault(dst, set()).add(src)

    # 第一遍只问**真节点**邻居（过路的问过路的问不出方向）；还没定下来的，
    # 后面几遍再顺着已经定了方向的过路邻居往下传 —— Shader → Dot → Dot → Shader
    # 中间那个 Dot 只有过路邻居，不传的话它永远是默认的竖着流、被单独拎成一组。
    resolved = {}
    for iteration in range(len(passThrough) + 1):
        changed = False
        for name in sorted(passThrough - set(resolved)):
            neighbourAxes = set()
            for other in neighbours.get(name, ()):
                if other in passThrough:
                    if iteration and other in resolved:
                        neighbourAxes.add(resolved[other])
                    continue
                neighbourAxes.add(axes[other])
            if len(neighbourAxes) == 1:
                resolved[name] = neighbourAxes.pop()
                changed = True
        if not changed:
            break

    axes.update(resolved)


## 按流向切分连通分量：同流向的边留在组内，跨流向的边当"组间挂钩"。
# 返回 ( 每组的成员名字, { 名字 : 组号 } )。
def _layoutFlowGroups(byName, axes, allEdges):

    adjacency = {}
    for src, dst, edge in allEdges:
        # **同流向 + 主流边**才算一组。侧面接进来的（filter / shader）留给"组间挂钩"，
        # 那样它们会贴在主干旁边，而不是被排进主干的某一层里。
        if axes[src] == axes[dst] and isFlowEdge(edge.dstPlug, axes[dst]):
            adjacency.setdefault(src, set()).add(dst)
            adjacency.setdefault(dst, set()).add(src)

    groupOf = {}
    groups = []
    for name in byName:
        if name in groupOf:
            continue
        index = len(groups)
        members = []
        stack = [name]
        groupOf[name] = index
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbour in sorted(adjacency.get(current, ())):
                if neighbour not in groupOf:
                    groupOf[neighbour] = index
                    stack.append(neighbour)
        groups.append(members)

    return groups, groupOf


## 一条连线都没有的散节点，并成**一组**排成一排（或一竖列）。
#
# 不并的话它们每个都是自己一个连通分量，而没有挂钩的分量只会"落回原位 + 撞上了才推开" ——
# 用户按 `Ctrl+L` 看到的就是**一动不动**（六个散着的 Sphere 实测零位移）。并成一组之后
# 它们全在同一层（没有边 → rank 全 0），分层布局那套天然把一层排成「对齐 + 等距 + 按原来
# 的先后」的一条线，不用为这种图另写一套摆法。
#
# 排横的还是竖的：**先看他们现在摆成什么样**（长边就是那条线，用户自己摆出来的意图），
# 方方正正一片 / 堆在一起时才回退到这类节点自己的流向惯例（场景节点竖着流 → 并排成横排；
# 材质节点横着流 → 叠成竖列，和"同级节点垂直于流向排开"一致）。
def _layoutLooseGroup(byName, axes, groups, groupOf, allEdges, position):

    connected = set()
    for src, dst, _unused in allEdges:
        connected.add(src)
        connected.add(dst)

    loose = [name for name in byName if name not in connected]
    if len(loose) < LAYOUT_LINE_MIN:
        return groups, groupOf

    xs = [position(name).x for name in loose]
    ys = [position(name).y for name in loose]
    spreadX, spreadY = max(xs) - min(xs), max(ys) - min(ys)

    if abs(spreadX - spreadY) > 1e-6:
        # "vertical" = 竖着流 → 展开轴是 x → 排成**横排**；"horizontal" 反之。
        axis = "vertical" if spreadX > spreadY else "horizontal"
    else:
        vertical = sum(1 for name in loose if axes[name] == "vertical")
        axis = "vertical" if vertical * 2 >= len(loose) else "horizontal"

    for name in loose:
        axes[name] = axis

    looseSet = set(loose)
    remaining = [members for members in groups if not looseSet.intersection(members)]
    newGroups = remaining + [loose]
    newGroupOf = {}
    for index, members in enumerate(newGroups):
        for name in members:
            newGroupOf[name] = index

    return newGroups, newGroupOf


## 每个节点的上游**按圆点从左到右**排（Group 的 `in0` / `in1` / `in2`）。
#
# 按插口顺序做深度优先（`order = "dfs*"`）时拿它当次序；不这么排的话
# 一个 Group 的三路输入会被重心法随便打乱，用户就会问"为什么 in0 跑到最右边"。
def _layoutInputOrder(byName, allEdges):

    plugRank = {}
    for name, node in byName.items():
        order = {}
        position = 0
        layout = noduleLayout(node)
        for section in ("top", "left", "right", "bottom"):
            for plug in layout.get(section, ()):
                order[plugKey(node, plug)] = position
                position += 1
        plugRank[name] = order

    entries = {}
    for src, dst, edge in allEdges:
        key = plugRank.get(dst, {}).get(plugKey(edge.dstNode, edge.dstPlug), 1 << 20)
        entries.setdefault(dst, []).append((key, src))

    result = {}
    for dst, sources in entries.items():
        seen = set()
        ordered = []
        for _unused, src in sorted(sources):
            if src not in seen:
                seen.add(src)
                ordered.append(src)
        result[dst] = ordered

    return result


## 每组各自排一遍，返回 { 组号 : { 名字 : ( 沿流向, 横向 ) } }。
def _layoutLocalGroups(groups, axes, sizes, allEdges, originalPosition, byName=None):

    # 插口顺序只有 `order = "dfs*"` 那几种定序才用 —— 默认的重心法不看它，
    # 而算它要对每个节点问一遍 `noduleLayout`（每个插口四五次元数据查询）
    wantsInputOrder = bool(byName) and LAYOUT_STRATEGY.get("order", "").startswith(
        "dfs"
    )
    inputOrder = _layoutInputOrder(byName, allEdges) if wantsInputOrder else {}

    # 每组的组内主流边**一次**分好桶。每组各扫一遍全部边、每条边再判一次
    # `isFlowEdge`（元数据查询）的话，一百个各自成组的 PathFilter 乘一千条边就是十万次。
    groupOf = {}
    for index, members in enumerate(groups):
        for name in members:
            groupOf[name] = index
    groupEdges = dict((index, set()) for index in range(len(groups)))
    for src, dst, edge in allEdges:
        index = groupOf.get(src)
        if (
            index is not None
            and groupOf.get(dst) == index
            and axes[src] == axes[dst]
            and isFlowEdge(edge.dstPlug, axes[dst])
        ):
            groupEdges[index].add((src, dst))

    local = {}
    for index, members in enumerate(groups):

        axis = axes[members[0]]
        memberSet = set(members)
        edges = groupEdges[index]

        if axis == "vertical":
            thickness = lambda n: sizes[n][1]
            extent = lambda n: sizes[n][0]
            rankGap, spreadGap = LAYOUT_VERTICAL_GAP, LAYOUT_HORIZONTAL_GAP
            originalSpread = lambda n: originalPosition(n).x
        else:
            thickness = lambda n: sizes[n][0]
            extent = lambda n: sizes[n][1]
            rankGap, spreadGap = LAYOUT_SHADER_RANK_GAP, LAYOUT_SHADER_SPREAD_GAP
            originalSpread = lambda n: -originalPosition(n).y

        local[index] = _layoutComponent(
            members,
            edges,
            thickness,
            extent,
            rankGap,
            spreadGap,
            originalSpread,
            lambda n: [s for s in inputOrder.get(n, ()) if s in memberSet],
        )

    return local


## 组内坐标 → 世界坐标（还没平移）。竖着流：沿流向往 −y 走；横着流：往 +x 走。
def _layoutToWorld(localGroup, axis, name):

    along, spread = localGroup[name]
    if axis == "vertical":
        return imath.V2f(spread, -along)
    return imath.V2f(along, -spread)


## 组之间：先钉住"主组"，其余的挂到它们喂的那个节点旁边。返回 { 组号 : 偏移 }。
#
# **主组要挑"最下游"那个**，不是最大那个：材质要以最终 ShaderAssignment 的位置为核心
# 做左右排布。材质图里材质那一坨有 40 个节点、场景那条流水线只有
# 4 个，按大小挑就会把材质钉死、反过来去挪 ShaderAssignment —— 正好挑反。
# 判据：组间连线只进不出的那个组（sink），并列时取节点多的。
def _layoutGroupOffsets(groups, sizes, links, originalPosition, toWorld):

    outgoing = set(link[0] for link in links)
    sinks = [index for index in range(len(groups)) if index not in outgoing]
    if not sinks:
        sinks = list(range(len(groups)))  # 有环，随便挑
    anchorIndex = sorted(sinks, key=lambda i: (-len(groups[i]), i))[0]

    def anchorOffset(index):

        members = groups[index]
        originals = [originalPosition(n) for n in members]
        originalCentre = imath.V2f(
            sum(p.x for p in originals) / float(len(originals)),
            sum(p.y for p in originals) / float(len(originals)),
        )
        placed = [toWorld(index, n) for n in members]
        newCentre = imath.V2f(
            sum(p.x for p in placed) / float(len(placed)),
            sum(p.y for p in placed) / float(len(placed)),
        )
        return originalCentre - newCentre

    offsets = {anchorIndex: anchorOffset(anchorIndex)}

    ## 一组节点（带上偏移）占的矩形：( minX, maxX, minY, maxY )，算进节点自己的尺寸。
    def groupBounds(index, offset):

        members = groups[index]
        placed = [(toWorld(index, n) + offset, n) for n in members]
        return (
            min(p.x - sizes[n][0] / 2.0 for p, n in placed),
            max(p.x + sizes[n][0] / 2.0 for p, n in placed),
            min(p.y - sizes[n][1] / 2.0 for p, n in placed),
            max(p.y + sizes[n][1] / 2.0 for p, n in placed),
        )

    ## 一组节点（带上偏移）**逐个节点**占的矩形。
    #
    # 挡路判定绝不能拿整组的包围盒来做：一个 PathFilter 挂在主干某个节点右边时，
    # 主干那一组的包围盒是从头到尾一整条 —— 撞上就得整个越过去，几个 filter 接连
    # 让下去能甩出几十个单位（实测平均"侧跳" 99.8，原生才 14.6）。
    def nodeRects(index, offset):

        result = []
        for name in groups[index]:
            centre = toWorld(index, name) + offset
            width, height = sizes[name]
            result.append(
                (
                    centre.x - width / 2.0,
                    centre.x + width / 2.0,
                    centre.y - height / 2.0,
                    centre.y + height / 2.0,
                )
            )
        return result

    for _ in range(len(groups)):

        progressed = False

        pending = {}
        for srcGroup, srcName, dstGroup, dstName, dstPlug in links:
            if srcGroup in offsets or dstGroup not in offsets:
                continue
            pending.setdefault(srcGroup, []).append(
                (srcName, dstGroup, dstName, dstPlug)
            )

        for srcGroup in sorted(pending):

            # **这一坨喂的可能不止一个节点**（一个 PathFilter 驱动一整串处理器就是这样）。
            # 只按第一条挂钩摆的话它会贴死在其中一个消费者旁边、离别的老远，
            # 连线还会**倒着往回走**。做法：挂钩方向上取最外面那个（保证谁都不压），
            # 垂直方向取**平均**（落在这几个消费者的正中间）。
            candidates = {}
            for srcName, dstGroup, dstName, dstPlug in pending[srcGroup]:
                direction = _layoutSideDirection(dstPlug)
                dstWorld = toWorld(dstGroup, dstName) + offsets[dstGroup]
                exitWorld = toWorld(srcGroup, srcName)
                offset = (
                    _layoutHookTarget(
                        direction,
                        dstWorld,
                        exitWorld,
                        sizes[dstName],
                        groupBounds(srcGroup, imath.V2f(0, 0)),
                    )
                    - exitWorld
                )
                candidates.setdefault((direction.x, direction.y), []).append(offset)

            # 好几个方向都有的话，跟条数最多的那个走
            key = sorted(candidates, key=lambda k: (-len(candidates[k]), k))[0]
            direction = imath.V2f(key[0], key[1])
            values = candidates[key]

            offset = imath.V2f(0, 0)
            average = imath.V2f(
                sum(v.x for v in values) / float(len(values)),
                sum(v.y for v in values) / float(len(values)),
            )
            if direction.x < 0:
                offset = imath.V2f(min(v.x for v in values), average.y)
            elif direction.x > 0:
                offset = imath.V2f(max(v.x for v in values), average.y)
            elif direction.y > 0:
                offset = imath.V2f(average.x, max(v.y for v in values))
            else:
                offset = imath.V2f(average.x, min(v.y for v in values))

            # **别和已经摆好的节点撞上**：挂钩只对齐到那几个节点，别的（场景那串里的
            # Dot 之类）可能正好横在旁边。先顺着挂钩那个方向**推到底**（推一次可能
            # 又撞上第三个节点）；推不干净再退回"四个方向挑位移最小的"那套。
            obstacles = [
                rect
                for other in offsets
                if other != srcGroup
                for rect in nodeRects(other, offsets[other])
            ]

            candidate = imath.V2f(offset)
            for _unused in range(LAYOUT_PACK_PASSES):
                shift = _layoutPushClear(
                    nodeRects(srcGroup, candidate), obstacles, direction
                )
                if shift.length() < 1e-6:
                    break
                candidate = candidate + shift
            else:
                candidate = _layoutPackOffset(
                    offset,
                    lambda value, index=srcGroup: nodeRects(index, value),
                    obstacles,
                )

            offsets[srcGroup] = candidate

            progressed = True

        if not progressed:
            break

    # 挂不上的（和别的组没有连线）：先落回自己原来的位置，再**按 Hilbert 序**逐坨
    # 摆开，撞上就往最近的方向让。
    #
    # 只 `setdefault(anchorOffset(index))` 不够 —— 排完各坨的**尺寸变了**
    # （分层布局按真实宽度重新摊开），原来紧挨着的两坨就会**叠在一起**；一批刚建出来
    # 或刚粘贴进来的节点原始位置几乎重合，叠得最厉害。
    #
    # 顺序为什么走 Hilbert（空间填充曲线序，`hilbertSorted`）：摆的顺序决定谁给谁让路，
    # 而 Hilbert 序里**先后摆的两坨在画面上就是邻居**。
    #
    # **不过实测它并不是最优的**（同规则只换排序，4 张随机图 8~20 坨）：径向序（按到中心
    # 的距离，先摆中心拥挤的）总位移 586.7 / 邻居保持率 71.0%，Hilbert 是 740.8 / 58.0%，
    # 组号序 609.3 / 69.6%。原因是这一步**每坨都已经有目标位置**（用户原来摆的地方），
    # 撞了才往外让 —— 这种规则下"先摆中心、外面的有空地可退"才对，而 Hilbert 在象限之间
    # 跳，常常先摆外圈再把内圈那坨一路挤出去。**重叠归零靠的是"摆开"这一步本身，跟顺序
    # 无关。** 这里有意按 Hilbert 序摆；要换径向序，
    # 把下面那句 `hilbertSorted(...)` 换成按 `islandCentre(i).length()` 排即可。
    islands = [index for index in range(len(groups)) if index not in offsets]
    placed = [
        rect for index in sorted(offsets) for rect in nodeRects(index, offsets[index])
    ]

    def islandCentre(index):
        originals = [originalPosition(name) for name in groups[index]]
        return imath.V2f(
            sum(p.x for p in originals) / float(len(originals)),
            sum(p.y for p in originals) / float(len(originals)),
        )

    for index in hilbertSorted(islands, islandCentre, key=lambda i: i):

        offset = _layoutPackOffset(
            anchorOffset(index),
            lambda candidate, index=index: nodeRects(index, candidate),
            placed,
        )

        offsets[index] = offset
        placed.extend(nodeRects(index, offset))

    return offsets


## 目的插口挂在哪条边 → 上游那一坨该摆在它的哪一侧
def _layoutSideDirection(plug):

    section = plugSection(plug)
    return {
        "left": imath.V2f(-1, 0),
        "right": imath.V2f(1, 0),
        "top": imath.V2f(0, 1),
        "bottom": imath.V2f(0, -1),
    }.get(section, imath.V2f(0, 1))


## 上游那一坨的出口节点该落在哪：贴着下游节点的那一侧、留一个组间间隔。
# `bounds` 是上游组还没平移时占的矩形（minX, maxX, minY, maxY）。
def _layoutHookTarget(direction, dstWorld, exitWorld, dstSize, bounds):

    minX, maxX, minY, maxY = bounds
    target = imath.V2f(dstWorld)

    if direction.x < 0:  # 从左边喂进来：整坨摆在它左边
        target.x = (
            dstWorld.x - dstSize[0] / 2.0 - LAYOUT_GROUP_GAP - (maxX - exitWorld.x)
        )
        target.y = dstWorld.y
    elif direction.x > 0:
        target.x = (
            dstWorld.x + dstSize[0] / 2.0 + LAYOUT_GROUP_GAP + (exitWorld.x - minX)
        )
        target.y = dstWorld.y
    elif direction.y > 0:  # 从上面喂进来：整坨摆在它上面
        target.y = (
            dstWorld.y + dstSize[1] / 2.0 + LAYOUT_GROUP_GAP + (exitWorld.y - minY)
        )
        target.x = dstWorld.x
    else:
        target.y = (
            dstWorld.y - dstSize[1] / 2.0 - LAYOUT_GROUP_GAP - (maxY - exitWorld.y)
        )
        target.x = dstWorld.x

    return target


## 自动排列：把 `nodes` 排成分层图，返回 { 节点 : 新位置 }（Gaffer 单位、y 向上；
## **不写回**，调用方自己决定怎么落盘）。
#
# **按流向分组**：场景节点竖着排（上游在上），材质 / OSL 节点横着排（上游在左），
# 两种混在一张图里就各排各的，再把材质那一坨挂到它喂的那个节点旁边
# （材质以最终 ShaderAssignment 为核心做左右排布）。
def layoutNodes(nodes, root, graphGadget=None):

    nodes = [node for node in nodes if not isinstance(node, Gaffer.Backdrop)]
    if len(nodes) < 2:
        return {}

    byName = collections.OrderedDict((node.getName(), node) for node in nodes)

    sizes = {}
    axes = {}
    for name, node in byName.items():
        sizes[name] = nodeSizeUnits(node, graphGadget)
        axes[name] = nodeFlowAxis(node)

    # --- 边（只算这批节点之间的）---
    allEdges = []
    for edge in collectEdges(root, list(byName.values())):
        if edge.auxiliary:
            continue
        src, dst = edge.srcNode.getName(), edge.dstNode.getName()
        if src == dst or src not in byName or dst not in byName:
            continue
        allEdges.append((src, dst, edge))

    _layoutPassThroughAxes(byName, axes, allEdges)

    def originalPosition(name):
        position = nodePosition(byName[name])
        return position if position is not None else imath.V2f(0, 0)

    groups, groupOf = _layoutFlowGroups(byName, axes, allEdges)
    groups, groupOf = _layoutLooseGroup(
        byName, axes, groups, groupOf, allEdges, originalPosition
    )

    local = _layoutLocalGroups(groups, axes, sizes, allEdges, originalPosition, byName)

    def toWorld(index, name):
        return _layoutToWorld(local[index], axes[groups[index][0]], name)

    # 组间挂钩：( 上游组, 上游节点, 下游组, 下游节点, 目的插口 )。
    # 既包括跨流向的（材质 → ShaderAssignment.shader），也包括同流向但**从侧面**
    # 接进来的（PathFilter → ShaderAssignment.filter）。
    links = []
    for src, dst, edge in allEdges:
        if groupOf[src] != groupOf[dst]:
            links.append((groupOf[src], src, groupOf[dst], dst, edge.dstPlug))
    links.sort(key=lambda l: (l[0], l[2], l[1], l[3]))

    offsets = _layoutGroupOffsets(groups, sizes, links, originalPosition, toWorld)

    result = {}
    for index, members in enumerate(groups):
        for name in members:
            result[byName[name]] = toWorld(index, name) + offsets[index]

    return result


## 能不能把 `node` 塞进「`srcPlug` → `dstPlug`」这条连线里？
#
# 能的话返回 ( 接源的输入插口, 驱动目的地的输出插口 )，不能返回 None。
# 逐条抄原生 `GraphGadget::updateDragReconnectCandidate`（`GraphGadget.cpp:1273`）：
# 只看**有 `correspondingInput`** 的输出插口（= 这节点是直通处理器）；两头都得
# `acceptsInput`；输入插口**必须还是空的**、输出插口在**这张图里**不能已经接了别人
# （图外的 UI 组件不算，比如 Viewer 的 View）；两个插口都得**画着圆点**。
def insertionPlugs(node, srcPlug, dstPlug, root=None):

    if not isinstance(node, Gaffer.DependencyNode):
        return None
    if srcPlug is None or dstPlug is None:
        return None
    if srcPlug.node() is None or dstPlug.node() is None:
        return None
    if srcPlug.node().isSame(node) or dstPlug.node().isSame(node):
        return None
    if Gaffer.MetadataAlgo.readOnly(node):
        return None

    for outPlug in Gaffer.Plug.RecursiveRange(node):

        if outPlug.direction() != Gaffer.Plug.Direction.Out:
            continue

        inPlug = node.correspondingInput(outPlug)
        if inPlug is None:
            continue

        if not hasNodule(inPlug) or not hasNodule(outPlug):
            continue

        if not dstPlug.acceptsInput(outPlug) or not inPlug.acceptsInput(srcPlug):
            continue

        if inPlug.getInput() is not None:
            continue

        if root is not None and any(
            root.isAncestorOf(output) for output in outPlug.outputs()
        ):
            continue

        return (inPlug, outPlug)

    return None


## 拖到某个节点身上时，它有哪些插口能接。返回画着 nodule 的那一层的插口。
#
# ArrayPlug 展开后会有一排 in0/in1/in2…，全塞进菜单没意义 —— 同一个 ArrayPlug
# 只留**第一个空槽**（都满了就留最后一个，Gaffer 会自动加新槽）。
def candidatePlugs(node, otherPlug):

    wantDirection = (
        Gaffer.Plug.Direction.In
        if otherPlug.direction() == Gaffer.Plug.Direction.Out
        else Gaffer.Plug.Direction.Out
    )

    candidates = []
    for section in noduleLayout(node).values():
        for plug in section:

            if plug.direction() != wantDirection:
                continue

            if wantDirection == Gaffer.Plug.Direction.In:
                ok = canConnect(otherPlug, plug)
            else:
                ok = canConnect(plug, otherPlug)

            if ok:
                candidates.append(plug)

    result = []
    seenArrays = set()
    for plug in candidates:

        parent = plug.parent()
        if isinstance(parent, Gaffer.ArrayPlug):
            if parent.getName() in seenArrays:
                continue
            seenArrays.add(parent.getName())
            free = [
                p
                for p in candidates
                if p.parent() is not None
                and isinstance(p.parent(), Gaffer.ArrayPlug)
                and p.parent().getName() == parent.getName()
                and p.getInput() is None
            ]
            result.append(free[0] if free else plug)
        else:
            result.append(plug)

    return result


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
