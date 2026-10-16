##########################################################################
# 自动排列对照台：同一批图 × 不同的分层布局实现，量出来再挑
#
# 分层布局是三个独立子问题串起来的（分层 / 定序 / 定位），每一步都有好几种成熟做法。
# 这个脚本把它们**排列组合**跑一遍，量交叉数、连线总长、长边直不直、输入口顺序有没有
# 被打乱、面积、耗时，最后打一张表。原生 `StandardGraphLayout` 也一起跑当参照。
#
#   QT_QPA_PLATFORM=offscreen gaffer env python tests/bench_layout.py
#
# 环境变量：`NE_BENCH_COMBOS=all` 跑全矩阵（默认只跑挑出来的那几个）、
#           `NE_BENCH_OUT=<路径>` 把表另存一份。
##########################################################################

import os
import sys
import time
import itertools

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"),
)

import imath
import Gaffer
import GafferScene
import GafferOSL
import GafferUI

import networkEditor as NE

##########################################################################
# 造图
##########################################################################


def _scenePipeline(script, depth=6, filters=3):
    """典型场景流水线：一条主干 + 几个 PathFilter 从右边喂进来 + 一个 Group 收拢。"""

    previous = None
    for i in range(depth):
        node = GafferScene.Sphere()
        script["sphere%d" % i] = node
        if previous is not None:
            pass
        previous = node

    group = GafferScene.Group()
    script["group"] = group
    for i in range(depth):
        group["in"][i].setInput(script["sphere%d" % i]["out"])

    chain = group
    for i in range(filters):
        isolate = GafferScene.Isolate()
        script["isolate%d" % i] = isolate
        isolate["in"].setInput(chain["out"])
        pathFilter = GafferScene.PathFilter()
        script["filter%d" % i] = pathFilter
        isolate["filter"].setInput(pathFilter["out"])
        chain = isolate

    assignment = GafferScene.ShaderAssignment()
    script["assignment"] = assignment
    assignment["in"].setInput(chain["out"])
    shared = GafferScene.PathFilter()
    script["sharedFilter"] = shared
    assignment["filter"].setInput(shared["out"])

    return script


def _sharedFilterPipeline(script, consumers=5):
    """**一个 PathFilter 喂好几个节点** —— 生产里最常见的那种。"""

    plane = GafferScene.Plane()
    script["plane"] = plane
    pathFilter = GafferScene.PathFilter()
    script["theFilter"] = pathFilter

    chain = plane
    for i in range(consumers):
        node = GafferScene.Isolate()
        script["isolate%d" % i] = node
        node["in"].setInput(chain["out"])
        node["filter"].setInput(pathFilter["out"])
        chain = node

    return script


def _filterChain(script):
    """过滤器自己也串成一条链：PathFilter → UnionFilter → 两个消费者。"""

    plane = GafferScene.Plane()
    script["plane"] = plane
    union = GafferScene.UnionFilter()
    script["union"] = union
    for i in range(3):
        node = GafferScene.PathFilter()
        script["path%d" % i] = node
        union["in"][i].setInput(node["out"])

    chain = plane
    for i in range(3):
        node = GafferScene.Isolate()
        script["isolate%d" % i] = node
        node["in"].setInput(chain["out"])
        node["filter"].setInput(union["out"])
        chain = node

    return script


def _oslMaterial(script, width=8, depth=5):
    """横着流的材质图：一堆 OSLShader 层层混合，外加几条**跳级**的长边
    （一张贴图直接喂给最下游那个）—— 分层布局最吃这个。"""

    def colourOut(node, name="c"):
        node["out"].addChild(
            Gaffer.Color3fPlug(
                name,
                Gaffer.Plug.Direction.Out,
                flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic,
            )
        )
        return node["out"][name]

    def colourIn(node, name):
        node["parameters"].addChild(
            Gaffer.Color3fPlug(
                name, flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
            )
        )
        return node["parameters"][name]

    textures = []
    for i in range(width):
        node = GafferOSL.OSLCode()
        script["tex%d" % i] = node
        colourOut(node)
        textures.append(node)

    current = list(textures)
    for level in range(depth):
        nextLayer = []
        count = max(1, len(current) - 1)
        for i in range(count):
            node = GafferOSL.OSLCode()
            script["mix%d_%d" % (level, i)] = node
            a, b = colourIn(node, "a"), colourIn(node, "b")
            colourOut(node)
            a.setInput(current[i]["out"]["c"])
            b.setInput(current[(i + 1) % len(current)]["out"]["c"])
            # 每层挑一个额外吃一条**跳级**的长边（直接从最上面那层拉下来）
            if i == 0 and level:
                c = colourIn(node, "skip")
                c.setInput(textures[level % width]["out"]["c"])
            nextLayer.append(node)
        current = nextLayer

    plane = GafferScene.Plane()
    script["plane"] = plane
    assignment = GafferScene.ShaderAssignment()
    script["assignment"] = assignment
    assignment["in"].setInput(plane["out"])
    pathFilter = GafferScene.PathFilter()
    script["assignFilter"] = pathFilter
    assignment["filter"].setInput(pathFilter["out"])

    return script


def _sceneBig(script):
    """一张像样的场景流水线：几路资产各自读进来 → 分别隔离 / 赋材质 → Group 合并
    → 再走几个处理器 → 一个 Switch 分档。PathFilter 有独享的也有公用的。"""

    shared = GafferScene.PathFilter()
    script["sharedFilter"] = shared

    branches = []
    for b in range(4):
        source = GafferScene.Sphere()
        script["asset%d" % b] = source
        chain = source
        for s in range(3):
            node = GafferScene.Isolate() if s % 2 else GafferScene.ShaderAssignment()
            script["step%d_%d" % (b, s)] = node
            node["in"].setInput(chain["out"])
            if s == 1:
                own = GafferScene.PathFilter()
                script["filter%d_%d" % (b, s)] = own
                node["filter"].setInput(own["out"])
            else:
                node["filter"].setInput(shared["out"])
            chain = node
        branches.append(chain)

    group = GafferScene.Group()
    script["group"] = group
    for i, branch in enumerate(branches):
        group["in"][i].setInput(branch["out"])

    chain = group
    for i in range(4):
        node = GafferScene.Transform()
        script["post%d" % i] = node
        node["in"].setInput(chain["out"])
        node["filter"].setInput(shared["out"])
        chain = node

    switch = Gaffer.Switch()
    script["quality"] = switch
    switch.setup(chain["out"])
    switch["in"][0].setInput(chain["out"])
    switch["in"][1].setInput(group["out"])

    # 一条跨好几层的长边：最上面那路资产直接喂给最后的 Group
    extra = GafferScene.Group()
    script["merge"] = extra
    extra["in"][0].setInput(switch["out"])
    extra["in"][1].setInput(branches[0]["out"])

    return script


def _diamondsDeep(script, levels=8, width=3):
    """反复汇合的稠密 DAG：每层三个节点交叉喂给下一层（定序最难的那种）。"""

    previous = []
    for level in range(levels):
        current = []
        for i in range(width):
            node = GafferScene.Group()
            script["d%d_%d" % (level, i)] = node
            slot = 0
            for j, source in enumerate(previous):
                if (i + j) % 2 and j != i:
                    continue
                node["in"][slot].setInput(source["out"])
                slot += 1
            current.append(node)
        previous = current
    return script


def _diamonds(script, levels=5):
    """反复汇合的 DAG：每层两个节点交叉喂给下一层（分层布局最难看的那种）。"""

    previous = []
    for level in range(levels):
        current = []
        for i in range(2):
            node = GafferScene.Group()
            script["d%d_%d" % (level, i)] = node
            for j, source in enumerate(previous):
                node["in"][j].setInput(source["out"])
            current.append(node)
        previous = current
    return script


def _wideFan(script, width=12):
    """一个源头扇出到十几个节点再收回来。"""

    plane = GafferScene.Plane()
    script["plane"] = plane
    group = GafferScene.Group()
    script["group"] = group
    for i in range(width):
        node = GafferScene.Isolate()
        script["leaf%d" % i] = node
        node["in"].setInput(plane["out"])
        group["in"][i].setInput(node["out"])
    return script


def _longChain(script, length=30):
    previous = GafferScene.Plane()
    script["plane"] = previous
    for i in range(length):
        node = GafferScene.Isolate()
        script["step%d" % i] = node
        node["in"].setInput(previous["out"])
        previous = node
    return script


def _trunkWithFan(script, before=3, width=6, after=3):
    """一条长主干**中间夹一个扇入**：链 → Group( 6 路 ) → 链。

    用户手摆的那张 `test_layout_group.gfr` 就是这个形状的核心。要的形态是
    「一排上游按插口顺序铺开 + Group 停在这一排正中间 + 主干两头各自笔直」——
    主干拉直如果不在扇入那儿断开，Group 会被贴到最左边那一路上，整排跟着漂。
    """

    previous = GafferScene.Plane()
    script["head"] = previous
    for i in range(before):
        node = GafferScene.Isolate()
        script["up%d" % i] = node
        node["in"].setInput(previous["out"])
        previous = node

    group = GafferScene.Group()
    script["group"] = group
    group["in"][0].setInput(previous["out"])
    for i in range(width):
        leaf = GafferScene.Sphere()
        script["leaf%d" % i] = leaf
        group["in"][i + 1].setInput(leaf["out"])

    previous = group
    for i in range(after):
        node = GafferScene.Transform()
        script["down%d" % i] = node
        node["in"].setInput(previous["out"])
        previous = node

    return script


def buildGraphs():

    graphs = []

    for name, builder in (
        ("scene-pipeline", _scenePipeline),
        ("scene-big", _sceneBig),
        ("shared-filter", _sharedFilterPipeline),
        ("filter-chain", _filterChain),
        ("osl-material", _oslMaterial),
        ("diamonds", _diamonds),
        ("diamonds-deep", _diamondsDeep),
        ("wide-fan", _wideFan),
        ("trunk-fan", _trunkWithFan),
        ("long-chain", _longChain),
    ):
        script = Gaffer.ScriptNode()
        builder(script)
        nodes = list(script.children(Gaffer.Node))
        graphs.append((name, script, nodes))

    # 用户手摆的参照图：一排 Sphere 喂一个 Group 再接 Transform。
    # 他要的形态是「一排按插口顺序铺开 + Group 停在这一排正中间」——
    # 主干拉直如果越过中位数，Group 就会贴到最左边那个 Sphere 底下。
    for fixture in ("test_layout_group.gfr",):
        path = os.path.join(NE.packageRoot(), "tests", fixture)
        if not os.path.isfile(path):
            continue
        script = Gaffer.ScriptNode()
        script["fileName"].setValue(path)
        script.load()
        members = list(script.children(Gaffer.Node))
        if len(members) >= 2:
            graphs.append(("fixture:%s" % fixture[:-4], script, members))

    # 真实生产材质图（用户给的），节点最多的那个 Box
    path = os.path.join(NE.packageRoot(), "tests", "shader_test.gfr")
    if os.path.isfile(path):
        script = Gaffer.ScriptNode()
        script["fileName"].setValue(path)
        script.load()

        def boxes(parent):
            result = []
            for node in parent.children(Gaffer.Node):
                if isinstance(node, Gaffer.Box):
                    result.append(node)
                    result.extend(boxes(node))
            return result

        for box in boxes(script):
            members = list(box.children(Gaffer.Node))
            if len(members) >= 6:
                graphs.append(("real:%s" % box.getName(), box, members))
        top = list(script.children(Gaffer.Node))
        if len(top) >= 6:
            graphs.append(("real:<script>", script, top))

    return graphs


##########################################################################
# 量指标
##########################################################################


def _segmentsCross(p1, p2, p3, p4):

    def side(o, a, b):
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

    d1, d2 = side(p3, p4, p1), side(p3, p4, p2)
    d3, d4 = side(p1, p2, p3), side(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def measure(root, nodes, positions, sizes, axes, elapsed):

    edges = [e for e in NE.collectEdges(root, nodes) if not e.auxiliary]
    edges = [e for e in edges if e.srcNode in positions and e.dstNode in positions]

    segments = [(positions[e.srcNode], positions[e.dstNode]) for e in edges]
    # ⚠️ **共用端点的两条边不算交叉**（一个源扇出 / 一个目的地扇入）。
    # `_segmentsCross` 那套叉积符号判定在共用端点时 d1 == 0，一旦另外两个端点分列
    # 两侧就被判成"交叉" —— 于是"把扇出的源摆在正中间"（对的做法）反而比"贴到最左边
    # 那一路上"（错的做法）多出一堆假交叉：wide-fan 一图就假报 6 处。
    crossings = 0
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            a, b = edges[i], edges[j]
            if (
                a.srcNode.isSame(b.srcNode)
                or a.dstNode.isSame(b.dstNode)
                or a.srcNode.isSame(b.dstNode)
                or a.dstNode.isSame(b.srcNode)
            ):
                continue
            if _segmentsCross(
                segments[i][0], segments[i][1], segments[j][0], segments[j][1]
            ):
                crossings += 1

    length = 0.0
    backwards = 0
    offset = 0.0
    straight = 0
    for edge in edges:
        src, dst = positions[edge.srcNode], positions[edge.dstNode]
        length += (dst - src).length()
        pair = (axes[edge.srcNode.getName()], axes[edge.dstNode.getName()])
        # **只有主流边才谈"逆流"**：`PathFilter → Isolate.filter` 是从**侧面**接进来的，
        # 一个 filter 喂五个消费者时它落在中间高度，对上面那两个自然是"往上走"——
        # 那不是逆流，是这类连线本来的样子。
        flow = NE.isFlowEdge(edge.dstPlug, axes[edge.dstNode.getName()], edge.dstNode)
        if pair == ("vertical", "vertical"):
            if flow and src.y < dst.y - 1e-3:
                backwards += 1
            delta = abs(src.x - dst.x)
        elif pair == ("horizontal", "horizontal"):
            if flow and src.x > dst.x + 1e-3:
                backwards += 1
            delta = abs(src.y - dst.y)
        else:
            delta = 0.0
        offset += delta
        if delta < 0.5:
            straight += 1

    # **长边**（沿流向跨得远的那些）直不直 —— Brandes–Köpf 的卖点就在这儿：
    # 长边的桩链落进同一个 block，整条线是笔直的。短边混在一起算会把它淹掉。
    longOffset = 0.0
    longStraight = 0
    longCount = 0
    for edge in edges:
        src, dst = positions[edge.srcNode], positions[edge.dstNode]
        pair = (axes[edge.srcNode.getName()], axes[edge.dstNode.getName()])
        if pair == ("vertical", "vertical"):
            along, across = abs(src.y - dst.y), abs(src.x - dst.x)
        elif pair == ("horizontal", "horizontal"):
            along, across = abs(src.x - dst.x), abs(src.y - dst.y)
        else:
            continue
        if along < 14.0:  # 一层多一点：再近就是相邻层，不算长边
            continue
        longCount += 1
        longOffset += across
        if across < 0.5:
            longStraight += 1

    # **主干直不直**：找最长那条流水线，数相邻两个是不是钉在同一条中线上。
    # 用户对这条特别敏感（"主流水线要是一条直溜溜的竖列"），所以单独量。
    byNameAll = dict((n.getName(), n) for n in nodes)
    flowEdges = [
        (e.srcNode.getName(), e.dstNode.getName())
        for e in edges
        if axes[e.srcNode.getName()] == axes[e.dstNode.getName()]
        and NE.isFlowEdge(e.dstPlug, axes[e.dstNode.getName()], e.dstNode)
    ]
    spine = NE._layoutSpine(list(byNameAll), flowEdges)
    spineAligned = 0
    spinePairs = 0
    for i in range(len(spine) - 1):
        a, b = byNameAll.get(spine[i]), byNameAll.get(spine[i + 1])
        if a is None or b is None or a not in positions or b not in positions:
            continue
        spinePairs += 1
        delta = (
            abs(positions[a].x - positions[b].x)
            if axes[spine[i]] == "vertical"
            else abs(positions[a].y - positions[b].y)
        )
        if delta < 0.5:
            spineAligned += 1

    xs = [positions[n].x for n in nodes if n in positions]
    ys = [positions[n].y for n in nodes if n in positions]
    area = ((max(xs) - min(xs)) * (max(ys) - min(ys))) if xs else 0.0

    overlaps = 0
    placed = [(positions[n], sizes[n.getName()]) for n in nodes if n in positions]
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            (pa, sa), (pb, sb) = placed[i], placed[j]
            if (
                abs(pa.x - pb.x) < (sa[0] + sb[0]) / 2.0 - 1e-3
                and abs(pa.y - pb.y) < (sa[1] + sb[1]) / 2.0 - 1e-3
            ):
                overlaps += 1

    # 输入口顺序：一个节点的几路上游，画出来是不是还按圆点从左到右
    byName = dict((n.getName(), n) for n in nodes)
    inputOrder = NE._layoutInputOrder(
        byName, [(e.srcNode.getName(), e.dstNode.getName(), e) for e in edges]
    )
    inversions = 0
    for name, sources in inputOrder.items():
        node = byName.get(name)
        if node is None or node not in positions or len(sources) < 2:
            continue
        values = []
        for source in sources:
            other = byName.get(source)
            if other is None or other not in positions:
                continue
            values.append(
                positions[other].x if axes[name] == "vertical" else -positions[other].y
            )
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                if values[i] > values[j] + 1e-3:
                    inversions += 1

    # PathFilter 这类"从侧面喂进来"的：离它喂的那个节点有多远（按节点宽度算）
    filterDistance = []
    for edge in edges:
        if NE.plugSection(edge.dstPlug) not in ("left", "right"):
            continue
        src, dst = positions[edge.srcNode], positions[edge.dstNode]
        filterDistance.append((dst - src).length())

    return {
        "crossings": crossings,
        "length": length,
        "backwards": backwards,
        "offset": offset,
        "straight": straight,
        "edges": len(edges),
        "area": area,
        "overlaps": overlaps,
        "inversions": inversions,
        "spineAligned": spineAligned,
        "spinePairs": spinePairs,
        "longOffset": longOffset,
        "longStraight": longStraight,
        "longCount": longCount,
        "sideHop": (
            (sum(filterDistance) / len(filterDistance)) if filterDistance else 0.0
        ),
        "ms": elapsed * 1000.0,
    }


##########################################################################
# 跑
##########################################################################

RANKS = ["longest-path", "network-simplex", "alap"]
ORDERS = ["barycenter", "median", "dfs", "dfs-barycenter", "dfs-median"]
POSITIONS = ["median", "brandes-kopf", "tidy"]

# 默认只跑这几个有代表性的（全矩阵 45 个太长）
PICKED = [
    # v0.59 之前的默认（最长路径 + 重心法 + 中位数对齐 + 事后钉主干）
    ("longest-path", "barycenter", "median", "pin"),
    # v0.59 起的默认：定位换成 Brandes–Köpf，主干交给它优先对齐、再补一遍钉
    ("longest-path", "barycenter", "brandes-kopf", "align+pin"),
    # 拆开看每一步各值多少
    ("longest-path", "barycenter", "brandes-kopf", "pin"),
    ("longest-path", "barycenter", "brandes-kopf", "align"),
    ("longest-path", "barycenter", "brandes-kopf", "off"),
    ("longest-path", "median", "median", "pin"),
    ("longest-path", "median", "brandes-kopf", "align+pin"),
    # 分层换成 dot 的网络单纯形 / ALAP
    ("network-simplex", "barycenter", "median", "pin"),
    ("network-simplex", "barycenter", "brandes-kopf", "align+pin"),
    ("alap", "barycenter", "brandes-kopf", "align+pin"),
    # Houdini 那味：贴着消费者分层 + 按插口顺序深度优先 + 树式定位（不做交叉优化）
    ("alap", "dfs", "tidy", "pin"),
    ("alap", "dfs", "tidy", "off"),
    ("alap", "dfs-median", "brandes-kopf", "align+pin"),
]


def run():

    # **先把旧报告删掉**：这个脚本是跑完才一次性写文件的，中途抛异常就不写 ——
    # 留着上一轮的报告最容易被看成"改了没生效"（同一个坑踩过好几次了）。
    out = os.environ.get("NE_BENCH_OUT", "/tmp/network_editor_layout_bench.txt")
    if os.path.exists(out):
        os.remove(out)

    graphs = buildGraphs()
    combos = (
        list(itertools.product(RANKS, ORDERS, POSITIONS, ["pin", "align", "off"]))
        if os.environ.get("NE_BENCH_COMBOS") == "all"
        else PICKED
    )

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    totals = {}

    for name, root, nodes in graphs:

        sizes = {}
        axes = {}
        for node in nodes:
            try:
                sizes[node.getName()] = NE.nodeSizeUnits(node, None)
            except Exception:
                sizes[node.getName()] = (11.0, 4.164)
            axes[node.getName()] = NE.nodeFlowAxis(node)

        emit()
        emit("=== %s（%d 个节点）===" % (name, len(nodes)))
        emit(
            "%-46s %7s %8s %6s %8s %7s %7s %8s %6s %7s"
            % (
                "rank / order / position",
                "交叉",
                "总长",
                "逆流",
                "偏移",
                "直边",
                "长边直",
                "主干直",
                "乱序",
                "毫秒",
            )
        )

        # 原生当参照
        try:
            gadget = GafferUI.GraphGadget(root)
            script = root.scriptNode() if hasattr(root, "scriptNode") else root
            before = dict((n, NE.nodePosition(n)) for n in nodes)
            start = time.time()
            gadget.getLayout().layoutNodes(gadget, Gaffer.StandardSet(nodes))
            elapsed = time.time() - start
            nativePositions = dict((n, NE.nodePosition(n)) for n in nodes)
            stats = measure(root, nodes, nativePositions, sizes, axes, elapsed)
            emit(
                "%-46s %7d %8.0f %6d %8.0f %7d %3d/%-3d %3d/%-3d %6d %7.1f"
                % (
                    "[原生 StandardGraphLayout]",
                    stats["crossings"],
                    stats["length"],
                    stats["backwards"],
                    stats["offset"],
                    stats["straight"],
                    stats["longStraight"],
                    stats["longCount"],
                    stats["spineAligned"],
                    stats["spinePairs"],
                    stats["inversions"],
                    stats["ms"],
                )
            )
            for node, position in before.items():
                if position is not None:
                    NE.setNodePosition(node, position)
        except Exception as error:
            emit("[原生 StandardGraphLayout] 跑不了：%s" % error)

        for combo in combos:

            rank, order, position, spine = combo
            label = "%s / %s / %s%s" % (
                rank,
                order,
                position,
                "" if spine == "pin" else " (spine=%s)" % spine,
            )
            with NE.layoutStrategy(
                rank=rank, order=order, position=position, spine=spine
            ):
                start = time.time()
                positions = NE.layoutNodes(nodes, root)
                elapsed = time.time() - start

            stats = measure(root, nodes, positions, sizes, axes, elapsed)
            bucket = totals.setdefault(label, {})
            for metric, value in stats.items():
                bucket[metric] = bucket.get(metric, 0.0) + value

            emit(
                "%-46s %7d %8.0f %6d %8.0f %7d %3d/%-3d %3d/%-3d %6d %7.1f"
                % (
                    label,
                    stats["crossings"],
                    stats["length"],
                    stats["backwards"],
                    stats["offset"],
                    stats["straight"],
                    stats["longStraight"],
                    stats["longCount"],
                    stats["spineAligned"],
                    stats["spinePairs"],
                    stats["inversions"],
                    stats["ms"],
                )
            )

    emit()
    emit("=== 全部图加起来 ===")
    emit(
        "%-46s %7s %8s %6s %8s %7s %7s %8s %7s %6s %7s"
        % (
            "rank / order / position",
            "交叉",
            "总长",
            "逆流",
            "偏移",
            "直边",
            "长边直",
            "长边偏",
            "主干直",
            "乱序",
            "毫秒",
        )
    )
    for key in sorted(
        totals, key=lambda k: (totals[k]["crossings"], totals[k]["longOffset"])
    ):
        stats = totals[key]
        emit(
            "%-46s %7d %8.0f %6d %8.0f %7d %3d/%-3d %8.0f %3d/%-3d %6d %7.1f"
            % (
                key,
                stats["crossings"],
                stats["length"],
                stats["backwards"],
                stats["offset"],
                stats["straight"],
                stats["longStraight"],
                stats["longCount"],
                stats["longOffset"],
                stats["spineAligned"],
                stats["spinePairs"],
                stats["inversions"],
                stats["ms"],
            )
        )

    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\n报告写到 %s" % out)


# `NE_BENCH_IMPORT=1` 时只把造图 / 量指标那几个函数暴露出来（诊断脚本 import 它）
if os.environ.get("NE_BENCH_IMPORT") != "1":
    run()
