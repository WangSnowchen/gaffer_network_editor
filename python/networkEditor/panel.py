"""Tab 建节点面板：级联多列（一列一个窗口）、分档搜索、常用 / 喜爱。"""

import os
import re
import math
import json
import bisect
import time
import collections
import functools
import inspect
import traceback
import types

import IECore
import Gaffer


from Qt import QtCore, QtGui, QtWidgets

from .view import *

# Qt：Tab 建节点面板


## 从 `NodeMenu.nodeCreatorWrapper` 的闭包里把真正的创建函数取出来。
#
# 原生那个包装里有 `assert menu.ancestor( GafferUI.GraphEditor ) is not None`，逼着你
# 用挂在 GraphEditor 下的 QMenu。把闭包里的 `nodeCreator` / `plugValues` /
# `postCreator` 拆出来自己跑（自动连接、摆位仍用原生 `StandardGraphLayout`）。
# 拆不出来、或者创建函数自己要 `menu` 参数的返回 None，调用方另想办法。
def _unwrapNodeCreator(command):

    if command is None:
        return None

    closure = getattr(command, "__closure__", None)
    code = getattr(command, "__code__", None)
    if not closure or code is None:
        return None

    freeVariables = dict(
        zip(code.co_freevars, [cell.cell_contents for cell in closure])
    )

    creator = freeVariables.get("nodeCreator")
    if creator is None:
        return None

    try:
        if "menu" in inspect.getfullargspec(creator).args:
            return None
    except TypeError:
        # 内建 / C++ 可调用对象，问不出签名 —— 当它不要 menu
        pass

    return (
        creator,
        freeVariables.get("plugValues") or {},
        freeVariables.get("postCreator"),
    )


## 把一个名字切成词。驼峰、数字、`_ - . / 空格` 都算边界：
#
#   "aiStandardSurface" → [ "ai", "Standard", "Surface" ]
#   "OSLCode"           → [ "OSL", "Code" ]          （连续大写算一个词）
#   "ai_standard_surface" → [ "ai", "standard", "surface" ]
_wordPattern = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z][a-z0-9]*|[0-9]+")


@functools.lru_cache(maxsize=8192)
def _words(text):

    return tuple(w.lower() for w in _wordPattern.findall(text))


## 首字母缩写。"aiStandardSurface" → "ass"（搜索时常见的打法）。
@functools.lru_cache(maxsize=8192)
def _initials(text):

    return "".join(w[0] for w in _words(text))


## `needle` 是不是 `text` 的子序列。是的话返回 ( 第一个命中的位置, 中间跳过多少字符 )。
def _subsequence(needle, text):

    position = 0
    first = None
    gaps = 0
    for character in needle:
        found = text.find(character, position)
        if found < 0:
            return None
        if first is None:
            first = found
        gaps += found - position
        position = found + 1

    return (first or 0, gaps)


## `needle` 能不能**按词头**切开吃掉（"aistand" → `ai` + `Stand`，两段都压在词头上）。
#
# 每一段都得从某个词的**第一个字母**开始，段内允许跳字符（"std" 吃掉 "standard"，
# 中间跳了 `a` `n`）—— 打字的人省字母都是这么省的。
# 能吃完返回 ( 跳过了几个词, 段内跳过了几个字符 )；吃不完返回 None。
def _wordPrefixSkips(needle, text):

    words = _words(text)
    if not words:
        return None

    consumed = 0
    skipped = 0
    inner = 0

    for word in words:

        if consumed >= len(needle):
            break

        if word[0] != needle[consumed]:
            skipped += 1
            continue

        # 这个词里能顺着吃掉多少（子序列，记下中间跳了几个字符）
        position = 0
        while consumed < len(needle):
            found = word.find(needle[consumed], position)
            if found < 0:
                break
            inner += found - position
            position = found + 1
            consumed += 1

    return (skipped, inner) if consumed >= len(needle) else None


## 模糊匹配。返回分数（越小越靠前），不匹配返回 None。
#
# 分档按「证据强度」而不是字符距离（低的排前面）：
#
#   0        前缀（"sph" → Sphere）
#   10 / 20  **首字母缩写**（"ass" → aiStandardSurface）
#   50+      词中命中（"ass" → ShaderAssignment）
#   200+     首字母串 / 首字母子序列
#   400+     按词头分段吃掉（"aistand" → ai|StandardSurface，段内可省字母）
#   1000+    任意子序列（"prf" → PathFilter，兜底）
#
# **缩写档故意排在「词中命中」前面** —— 打 `ass` 想要的是 aiStandardSurface，
# 不是名字里正好含 "ass" 的节点。空格分词是**与**关系，分数相加。
def _matchScore(needle, text):

    if not needle:
        return 0

    tokens = needle.split()
    if not tokens:
        return 0

    if len(tokens) > 1:
        total = 0
        for token in tokens:
            score = _matchScore(token, text)
            if score is None:
                return None
            total += score
        return total + 20 * (len(tokens) - 1)

    needle = tokens[0].lower()
    lower = text.lower()

    index = lower.find(needle)
    if index == 0:
        return 0  # 前缀，最优

    initials = _initials(text)
    if len(needle) >= 2 and initials:
        if needle == initials:
            return 10  # 正好就是首字母缩写
        if initials.startswith(needle):
            return 20 + len(initials) - len(needle)

    if index > 0:
        return 50 + index  # 词中命中，越靠前越好

    if len(needle) >= 2 and initials:
        position = initials.find(needle)
        if position > 0:
            return 200 + position
        found = _subsequence(needle, initials)
        if found is not None:
            return 260 + found[0] + found[1]

    skips = _wordPrefixSkips(needle, text)
    if skips is not None:
        return 400 + 4 * skips[0] + skips[1]

    found = _subsequence(needle, lower)
    if found is not None:
        return 1000 + found[1] + found[0]

    return None


## `_matchScore` 各档的下边界（类目命中整体再 +2000）。搜索结果先按档排。
_SCORE_TIERS = (10, 20, 50, 200, 400, 1000, 2000, 2050, 2200, 2400, 3000)


## 「常用 / 喜爱」记在哪：`$GAFFER_NETWORK_EDITOR_STATE_DIR`，默认 `~/.gaffer_network_editor`。
#
# 不往 `~/gaffer`（用户自己的 startup 目录）里写东西，也不进 .gfr —— 这是**跟人走**的
# 偏好，不是跟文件走的数据。
def _stateDirectory():

    return os.environ.get("GAFFER_NETWORK_EDITOR_STATE_DIR") or os.path.join(
        os.path.expanduser("~"), ".gaffer_network_editor"
    )


## 面板里一条条目的身份：分类 + 名字（`Arnold / Shader` + `aiStandardSurface`）。
#
# 用路径而不是名字：不同分类下重名的条目（`Image` 和 `Scene` 各有一个 `Constant`）
# 不能混成一条。
def _entryKey(name, category):

    return (category + " / " + name) if category else name


## 建节点面板的「常用 / 喜爱」。
#
# * **喜爱**：用户自己钉的，永远排在最上面，顺序 = 加入顺序。
# * **常用**：按用过多少次排（次数一样看谁更近），自动的、不用管。
#
# 落盘成一个 JSON，坏了 / 读不出来一律当空的 —— 面板绝不能因为这个文件炸掉。
class _CreatorUsage(object):

    ## 「常用」最多列几条（喜爱不限，用户自己钉的自己负责）
    FREQUENT_LIMIT = 8
    ## 存盘时保留多少条使用记录（再多也没意义，纯占地方）
    KEEP = 300

    def __init__(self, path=None):

        self.__path = path
        self.__favourites = []  # [ key ]，有序
        self.__counts = {}  # key -> [ 次数, 上次用的时间戳 ]
        self.__mtime = None  # 上次读进来那份文件的修改时间

    def path(self):

        if self.__path is None:
            self.__path = os.path.join(_stateDirectory(), "nodeCreator.json")

        return self.__path

    ##########################################################################
    # 读写
    ##########################################################################

    ## 文件比手上这份新就重读 —— 同时开着几个 Gaffer 时，别的会话刚钉的喜爱
    # 不能被这边下一次存盘用旧数据盖掉。
    def __load(self):

        try:
            mtime = os.stat(self.path()).st_mtime
        except FileNotFoundError:
            return

        if mtime == self.__mtime:
            return

        self.__mtime = mtime

        try:
            with open(self.path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except ValueError:
            # 坏 JSON 当空的；下一次存盘把它覆盖成好的
            data = {}

        if not isinstance(data, dict):
            data = {}

        favourites = data.get("favourites")
        self.__favourites = (
            [k for k in favourites if isinstance(k, str)]
            if isinstance(favourites, list)
            else []
        )

        self.__counts = {}
        usage = data.get("usage")
        if isinstance(usage, dict):
            for key, value in usage.items():
                if (
                    isinstance(value, list)
                    and len(value) == 2
                    and all(isinstance(v, (int, float)) for v in value)
                ):
                    self.__counts[key] = [int(value[0]), float(value[1])]

    def __save(self):

        # 次数最多的留下，其余丢掉
        keys = sorted(self.__counts, key=lambda k: self.__counts[k], reverse=True)[
            : self.KEEP
        ]

        data = {
            "favourites": list(self.__favourites),
            "usage": {k: self.__counts[k] for k in keys},
        }

        path = self.path()
        # 先写临时文件再改名：写一半被打断也不会留个坏 JSON。
        # `ensure_ascii=False` 写的是 UTF-8，编码要写死 —— 靠 locale 的话
        # 非 ASCII 的节点菜单标签在 C locale 下会写失败，喜爱就再也存不上
        temporary = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=1, ensure_ascii=False)
            os.replace(temporary, path)
        except OSError:
            # 磁盘满 / 没权限：建节点不能因为记不下次数就失败，但要让人看得见
            IECore.msg(
                IECore.Msg.Level.Warning,
                "NetworkEditor",
                "Could not save %s:\n%s" % (path, traceback.format_exc()),
            )
            if os.path.exists(temporary):
                os.remove(temporary)
            return

        self.__mtime = os.stat(path).st_mtime

    ##########################################################################
    # 对外
    ##########################################################################

    ## 用了一条 —— 次数 +1、记下时间。
    def record(self, key):

        if not key:
            return

        self.__load()
        entry = self.__counts.setdefault(key, [0, 0.0])
        entry[0] += 1
        entry[1] = time.time()
        self.__save()

    def isFavourite(self, key):

        self.__load()
        return key in self.__favourites

    ## 钉上 / 取消钉。返回钉完之后是不是喜爱。
    def toggleFavourite(self, key):

        if not key:
            return False

        self.__load()
        if key in self.__favourites:
            self.__favourites.remove(key)
            favourite = False
        else:
            self.__favourites.append(key)
            favourite = True

        self.__save()
        return favourite

    def favourites(self):

        self.__load()
        return list(self.__favourites)

    ## 最常用的几条（`exclude` 里的不算 —— 已经在喜爱里的不用再列一遍）。
    def frequent(self, limit=None, exclude=()):

        self.__load()
        exclude = set(exclude)

        keys = [k for k in self.__counts if k not in exclude]
        # 次数多的在前，一样多看谁更近
        keys.sort(key=lambda k: (-self.__counts[k][0], -self.__counts[k][1], k))

        return keys[: self.FREQUENT_LIMIT if limit is None else limit]

    def count(self, key):

        self.__load()
        return self.__counts.get(key, [0, 0.0])[0]


_creatorUsage = None


## 全局那一份「常用 / 喜爱」（所有 NetworkEditor 共用）。
def creatorUsage():

    global _creatorUsage
    if _creatorUsage is None:
        _creatorUsage = _CreatorUsage()

    return _creatorUsage


## 换掉全局那一份（测试用：指到临时文件上去，别动用户自己的）。
def setCreatorUsage(usage):

    global _creatorUsage
    _creatorUsage = usage


## 这个菜单命令收哪些命名参数（照搬 `Menu.__argNames`，`Menu.py:156-168`：
# 函数、绑定方法、`Gaffer.WeakMethod`、`functools.partial` 都看穿，别的一律当没参数）。
def _commandArgNames(function):

    if isinstance(function, types.FunctionType):
        return inspect.getfullargspec(function).args
    if isinstance(function, types.MethodType):
        return _commandArgNames(function.__func__)[1:]
    if isinstance(function, Gaffer.WeakMethod):
        return _commandArgNames(function.method())[1:]
    if isinstance(function, functools.partial):
        return _commandArgNames(function.func)

    return []


## 这个菜单命令要不要 `menu` 参数（`GafferUI.Menu` 就是这么判的）。
def _commandWantsMenu(command):

    return "menu" in _commandArgNames(command)


## 这个菜单命令自己收 `checkBox` 参数吗（原生那样用关键字传勾选状态）。
def _commandWantsCheckBox(command):

    return "checkBox" in _commandArgNames(command)


## 菜单条目上可以是值也可以是函数的那几项（`active` / `checkBox` / `subMenu` /
# 动态定义）怎么求值 —— 照搬 `Menu.__evaluateItemValue`（`Menu.py:489-497`）。
def _evaluateItemValue(value, menu):

    if callable(value):
        return value(menu=menu) if _commandWantsMenu(value) else value()

    return value


## 摊平之后的一条菜单条目：`active` / `checkBox` 在建面板那一刻按原生的规矩求好值
# （原生 `Menu.__build` 也是弹出来那一刻求），其余属性原样转给原来的条目。
class _MenuEntryItem(object):

    def __init__(self, item, active, checked):

        self.__item = item
        self.active = active
        ## 勾着没；不是勾选型条目为 None
        self.checked = checked

    def __getattr__(self, name):

        return getattr(self.__item, name)

    ## 原来那个 `IECore.MenuItemDefinition`（点下去时要拿它的 `active` 再求一次值）。
    def definition(self):

        return self.__item


## 点下去那一刻这条还能不能执行 —— 原生 `Menu.__actionTriggered` 会再求一次 `active`
# （建菜单到点下去之间状态可能变了）。摊平条目要问它原来那个定义，不是建面板时存的值。
def _entryActiveNow(item, menu):

    definition = item.definition() if isinstance(item, _MenuEntryItem) else item
    return bool(_evaluateItemValue(getattr(definition, "active", True), menu))


## 一条菜单条目是不是灰的（不可执行）。
def _entryDisabled(item):

    return (
        not _evaluateItemValue(getattr(item, "active", True), None)
        or getattr(item, "command", None) is None
    )


## 一条菜单条目现在勾着没。不是勾选型条目返回 None。
#
# 摊平出来的条目在建面板时已经带着 `menu` 求过值，直接用那份 —— 面板上画的 ✓
# 和点下去传给命令的勾选状态必须是同一个。
def _entryCheckState(item, menu=None):

    if isinstance(item, _MenuEntryItem):
        return item.checked

    checkBox = getattr(item, "checkBox", None)
    if checkBox is None:
        return None

    return bool(_evaluateItemValue(checkBox, menu))


## 把一个 `IECore.MenuDefinition` 摊平成面板要的条目：
# ( 叶子名, 所在分类, 搜索用文本, `_MenuEntryItem` )。
#
# **灰掉的条目也收进来**（画成灰的、点不动）—— `T` 键菜单没有书签时只有一条
# `No bookmarks available`（`active = False`），全过滤掉就成了空菜单。
# 灰掉的子菜单整个灰（原生 `subMenu.setEnabled( active )`，`Menu.py:317`），
# 里面的条目照样列出来、一律点不动。
#
# **子菜单要钻进去** —— 内部那些快捷键菜单顶层清一色是 `subMenu`，不递归一条都拿不到。
def _entriesFromDefinition(definition, menu=None, prefix="", depth=0, active=True):

    entries = []
    for path, item in definition.items():

        fullPath = prefix + path
        itemActive = active and bool(
            _evaluateItemValue(getattr(item, "active", True), menu)
        )

        subMenu = getattr(item, "subMenu", None)
        if subMenu is not None:

            if depth >= 4:
                continue

            entries.extend(
                _entriesFromDefinition(
                    _evaluateItemValue(subMenu, menu),
                    menu,
                    fullPath,
                    depth + 1,
                    itemActive,
                )
            )
            continue

        if getattr(item, "divider", False):
            continue
        if getattr(item, "command", None) is None and itemActive:
            continue

        parts = [p for p in fullPath.split("/") if p]
        if not parts:
            continue

        checkBox = getattr(item, "checkBox", None)
        checked = None if checkBox is None else bool(_evaluateItemValue(checkBox, menu))

        searchText = getattr(item, "searchText", None) or parts[-1]
        entries.append(
            (
                parts[-1],
                " / ".join(parts[:-1]),
                searchText,
                _MenuEntryItem(item, itemActive, checked),
            )
        )

    return entries


## 自己造的面板条目（面板只认 `.command`，和 `IECore.MenuItemDefinition` 对齐）。
class _PanelCommand(object):

    def __init__(self, command):

        self.command = command


## 从一个 `GafferUI.Menu` 里把它的 MenuDefinition 掏出来。
#
# `Menu.__init__` 是把定义挂在**Qt 对象**上的：
# `self._qtWidget().__definition = definition`（类体里写的，所以真名是
# `_Menu__definition`）。定义还可能是个 callable（动态菜单）。
def _menuDefinition(menu):

    return _evaluateItemValue(menu._qtWidget()._Menu__definition, menu)


## 这条命令是不是 `NodeMenu` 包装出来的「建节点」命令。
#
# 那个包装（`NodeMenu.nodeCreatorWrapper`）里有一句
# `assert menu.ancestor( GafferUI.GraphEditor ) is not None` —— 我们的面板不是菜单，
# 直接调它必然 AssertionError（内部快捷键菜单里一大半条目都是这种）。认出来之后走
# 我们自己的建节点通道就行。
def _isNodeCreatorCommand(command):

    code = getattr(command, "__code__", None)
    return bool(code is not None and "nodeCreator" in getattr(code, "co_freevars", ()))


## 喜爱条目名字后面那颗星（`★`）。
STAR = "\u2605"
STAR_WIDTH = 12

## 勾选型条目名字左边那个对勾（`✓`）。
CHECK_MARK = "\u2713"


## 名字和右侧那串信息之间至少留这么宽，免得两串字贴在一起分不出边界。
ROW_TEXT_GAP = 8

## 右侧那串层级信息最多占这么宽（再长就从左边截，`… / Primitives`）。
# 它只是"这条在菜单里的哪儿"的提示，不该跟名字抢地方。
ROW_RIGHT_MAX_WIDTH = 200

## 算「一点不截要多宽」时多留这么点余量（宽度刚好相等时 Qt 仍会 elide）。
ROW_TEXT_SLACK = 3

## 右侧信息窄到这个程度就整块不画 —— 只剩一个省略号没有任何信息量，还占着名字的地方。
ROW_RIGHT_MIN_WIDTH = 30


## 一行里「左边名字」和「右边层级信息」各分多少宽度，返回 ( 名字宽, 右侧宽 )。
#
# **名字优先，而且是绝对优先**：名字要多少给多少，右侧拿剩下的（剩得太少就整块不画）。
# 名字是拿来认节点的，`show_camera_f...` 这种截断等于没显示。配合列宽自适应
# （`_rowWidthHint` / `__columnContentWidth`），正常情况下两块都放得下、谁也不用截。
def _splitRowWidths(available, nameWidth, rightWidth):

    room = available - ROW_TEXT_GAP
    if rightWidth <= 0 or room <= 0:
        return max(0, available), 0

    # 名字要的宽度**多算 `ROW_TEXT_SLACK`**：Qt 在「宽度刚好等于文字宽度」时照样 elide，
    # 不留这一两像素，按 `_rowWidthHint` 那么宽画出来最长那行仍带省略号。
    # 右侧那块也照 `ROW_RIGHT_MAX_WIDTH` 收，和 `_rowWidthHint` 用同一个上限。
    claim = min(nameWidth + ROW_TEXT_SLACK, room)
    right = max(0, min(rightWidth, ROW_RIGHT_MAX_WIDTH, room - claim))
    if right < ROW_RIGHT_MIN_WIDTH:
        return max(0, available), 0

    return max(0, room - right), right


## 这一行**一点都不截断**要多宽（名字全展开 + 右侧最多 `ROW_RIGHT_MAX_WIDTH`），
# 列宽自适应就是按它算的。字体要和 `_CreatorDelegate.paint` 里用的完全一致。
def _rowWidthHint(label, rightText="", header=False, category=False, favourite=False):

    nameFont = _font(8.0, bold=True) if header else _font(9.5, bold=category)
    width = QtGui.QFontMetrics(nameFont).horizontalAdvance(label or "")
    if favourite:
        width += STAR_WIDTH + 5

    if rightText:
        rightFont = _font(7.5) if header else _font(8.0)
        width += ROW_TEXT_GAP + min(
            QtGui.QFontMetrics(rightFont).horizontalAdvance(rightText),
            ROW_RIGHT_MAX_WIDTH,
        )

    # `paint()` 里 `nameRect = rect.adjusted( 12, 0, -12, 0 )`，另外多留 3px 余量 ——
    # 宽度**刚好等于**文字宽度时 Qt 照样会 elide（`horizontalAdvance` 和实际排版差
    # 一两个像素），实测最长那行会因此仍然带一个省略号。
    return width + 24 + ROW_TEXT_SLACK


class _CreatorDelegate(QtWidgets.QStyledItemDelegate):

    ## 画一行的「左边名字 + 右边信息」。两块先分好宽度再各自截断，绝不重叠。
    #
    # `reserve` 是名字后面还要留给别的东西（那颗星）的宽度。
    # 返回 ( 名字实际画了多宽, 右侧占了多宽 )。
    def _paintTexts(
        self,
        painter,
        rect,
        name,
        nameFont,
        namePen,
        right,
        rightFont,
        rightPen,
        reserve=0,
    ):

        nameMetrics = QtGui.QFontMetrics(nameFont)
        rightMetrics = QtGui.QFontMetrics(rightFont)

        nameWidth, rightWidth = _splitRowWidths(
            rect.width(),
            nameMetrics.horizontalAdvance(name) + reserve,
            rightMetrics.horizontalAdvance(right) if right else 0,
        )

        painter.setFont(nameFont)
        painter.setPen(namePen)
        elidedName = nameMetrics.elidedText(
            name, QtCore.Qt.ElideRight, max(0, nameWidth - reserve)
        )
        painter.drawText(
            QtCore.QRect(rect.left(), rect.top(), nameWidth, rect.height()),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            elidedName,
        )

        if rightWidth > 0:
            painter.setFont(rightFont)
            painter.setPen(rightPen)
            # 右边是层级路径，越靠后越有用 → 从**左边**截（`… / Primitives`）
            painter.drawText(
                QtCore.QRect(
                    rect.left() + rect.width() - rightWidth,
                    rect.top(),
                    rightWidth,
                    rect.height(),
                ),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                rightMetrics.elidedText(right, QtCore.Qt.ElideLeft, rightWidth),
            )

        return nameMetrics.horizontalAdvance(elidedName), rightWidth

    def paint(self, painter, option, index):

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        rect = option.rect
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)

        # **只认"当前行"这一种高亮，绝不画 `State_MouseOver`**：一列一个窗口之后，
        # 不是最上面那个 popup 的列收不到真的鼠标事件，Qt 内部那个 hover 状态就**停在
        # 最后划过的那一行清不掉** —— 画面上留下一道洗不掉的浅蓝。悬停高亮一律靠 `__hovered` 里的
        # `setCurrentItem`，那是我们自己控制的、每次都会跟着走。
        if selected:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(_selectedBorder))
            painter.drawRoundedRect(rect.adjusted(3, 1, -3, -1), 3, 3)

        name = index.data(QtCore.Qt.DisplayRole) or ""
        category = index.data(QtCore.Qt.UserRole + 1) or ""
        header = bool(index.data(QtCore.Qt.UserRole + 3))
        isCategory = bool(index.data(QtCore.Qt.UserRole + 2)) or header
        favourite = bool(index.data(QtCore.Qt.UserRole + 6))

        disabled = bool(index.data(QtCore.Qt.UserRole + 4))
        checked = bool(index.data(QtCore.Qt.UserRole + 7))

        nameRect = rect.adjusted(12, 0, -12, 0)

        # 「★ 喜爱」/「常用」/「全部」这种分节标题：小字、暗色，上面压一条细分隔线，
        # 点不动也选不中（`__moveSelection` 会跳过它）。
        if header:
            # 1px 的线不要抗锯齿 —— 开着的话半个像素落在矩形外面，淡得看不见
            painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
            painter.setPen(QtGui.QPen(QtGui.QColor(_cardBorder), 1))
            painter.drawLine(rect.left() + 8, rect.top(), rect.right() - 8, rect.top())
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            dimPen = QtGui.QColor(_dimTextColor)
            self._paintTexts(
                painter,
                nameRect,
                name,
                _font(8.0, bold=True),
                dimPen,
                category,
                _font(7.5),
                dimPen,
            )
            painter.restore()
            return

        nameFont = _font(9.5, bold=isCategory)
        if selected:
            # 高亮上的灰条目仍要看得出是灰的
            namePen = QtGui.QColor("#4a5560" if disabled else "#14161a")
        else:
            namePen = QtGui.QColor(_dimTextColor if disabled else _textColor)

        nameAdvance, categoryWidth = self._paintTexts(
            painter,
            nameRect,
            name,
            nameFont,
            namePen,
            category,
            _font(8.0),
            QtGui.QColor("#2b3138" if selected else _dimTextColor),
            reserve=(STAR_WIDTH + 5) if favourite else 0,
        )

        # 勾着的那条在名字左边的留白里点一个对勾（**不挤名字**，不然一列里
        # 勾着的和没勾的两种缩进）
        if checked:
            painter.setFont(_font(9.5, bold=True))
            painter.setPen(QtGui.QColor("#2b3138" if selected else _textColor))
            painter.drawText(
                QtCore.QRect(rect.left() + 1, rect.top(), 11, rect.height()),
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                CHECK_MARK,
            )

        # 钉住的条目在名字后面点一颗星（**跟着名字走**，不占固定的左边空槽 ——
        # 占了的话没钉住的行也得跟着缩进，一列里两种缩进反而难看）。
        if favourite:
            starX = nameRect.left() + nameAdvance + 5
            if starX + STAR_WIDTH < nameRect.right() - categoryWidth - 4:
                painter.setFont(_font(8.5))
                painter.setPen(QtGui.QColor("#7a6a2a" if selected else _bookmarkColor))
                painter.drawText(
                    QtCore.QRect(int(starX), rect.top(), STAR_WIDTH, rect.height()),
                    QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                    STAR,
                )

        painter.restore()

    def sizeHint(self, option, index):

        return QtCore.QSize(200, 22)


## 全局坐标落在哪块屏上。拿不准返回 None。
#
# **千万别写 `QtGui.QGuiApplication`** —— Qt.py 这层壳的 `QtGui` 里**根本没有它**
# （本机实测 `hasattr( QtGui, "QGuiApplication" ) == False`）。写了就是 AttributeError，
# 被 `except` 一吞就退回"主屏"，接着按主屏的可用区去夹坐标 —— 鼠标在副屏上按 Tab，
# 面板被硬夹回主屏。用户看到的就是「换了显示器，Tab 栏还是开在另一个显示器上」。
def _screenAt(position):

    if QtWidgets.QApplication.instance() is None:
        return None

    return QtWidgets.QApplication.screenAt(position)


## 把弹出位置夹进某块矩形（屏幕可用区），别让面板跑出屏幕。
#
# `rect` 是 None（问不出在哪块屏）就**原样返回** —— 夹到一块猜的屏上比不夹危险得多。
def _clampToRect(position, size, rect):

    if rect is None or rect.isEmpty():
        return QtCore.QPoint(position)

    return QtCore.QPoint(
        max(rect.left(), min(position.x(), rect.right() - size.width())),
        max(rect.top(), min(position.y(), rect.bottom() - size.height())),
    )


## 级联出来的第二列往后，**每一列自己一个窗口** —— 原生 QMenu 就是这样：每一级菜单
# 一个窗口、各自按自己的内容定高，展开下一级不会动上一级分毫。
#
# 必须是 `Qt.Popup`，不能是 `Qt.Tool` / `Qt.ToolTip`（真机实测：后两者会被当成
# 「点在 popup 外」，第一下点击就关掉整个面板）。代价是**鼠标事件只发给最上面那个
# popup**，所以一律交给面板按全局坐标自己派发（`_routeMouse`）—— QMenu 也是这么干的。
class _ColumnWindow(QtWidgets.QWidget):

    MARGIN = 4

    def __init__(self, panel, listWidget):

        QtWidgets.QWidget.__init__(self, panel, QtCore.Qt.Popup)

        self.__panel = panel

        # **没有 `setMouseTracking` 就收不到「没按键的移动」** —— 鼠标退回左边那些列上时，
        # 事件是以窗口外的坐标发给最上面这个窗口的，不开 tracking 这条路直接哑掉
        # （真机真鼠标测出来的：点得动、划回去没反应）。
        self.setMouseTracking(True)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(panel.styleSheet())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        layout.setSpacing(0)
        layout.addWidget(listWidget)

    def mouseMoveEvent(self, event):

        self.__panel._routeMouse("move", _globalPos(event), event.buttons())

    def mousePressEvent(self, event):

        self.__panel._routeMouse("press", _globalPos(event), event.button())

    def mouseReleaseEvent(self, event):

        self.__panel._routeMouse("release", _globalPos(event), event.button())

    def wheelEvent(self, event):

        self.__panel._routeWheel(_globalPos(event), event.angleDelta().y())
        event.accept()

    def keyPressEvent(self, event):

        # 键盘 grab 也在最上面那个 popup 上 —— 认得的快捷键自己处理，剩下的（打字）
        # 送回搜索框，不然子列一开就打不了字了。
        if self.__panel._handleKeyEvent(event):
            event.accept()
            return

        self.__panel._forwardToSearch(event)


## 面板里的一行。`key` 是「常用 / 喜爱」的身份（分类行 / 标题行没有），
# `header` 是分节标题（「★ 喜爱」这种，点不动也选不中）。
_Row = collections.namedtuple(
    "_Row",
    "label rightText item category key header",
    defaults=("", None, None, None, False),
)


# **这个面板里一律不挂悬停小框（tooltip）**：Tab 面板是"扫着找、找到就回车"的东西，
# 鼠标一路划过去，Qt 的提示框会一个接一个冒出来、而且**消失得慢**，直接盖住下面几行。
# 要说明的话都写在行右边那列小字里（菜单位置 / 条目数），
# 不占额外的浮层。


## Tab / 快捷键弹出来的面板：一排**级联的列**（原生 QMenu 那个手感）。
#
# 第一列是根层，鼠标停在哪个分类上就往右多开一列，一直下去。尺寸跟着内容走
# （到上限才出滚动条）。上下键选、回车建、Esc 关。
class _NodeCreatorPopup(QtWidgets.QWidget):

    ROW_HEIGHT = 22
    MAX_VISIBLE_ROWS = 18
    MIN_VISIBLE_ROWS = 1
    FIRST_COLUMN_WIDTH = (
        300  # 列宽的**下限**，内容长了会自己撑宽（见 __columnContentWidth）
    )
    COLUMN_WIDTH = 250
    COLUMN_MAX_WIDTH = 720  # 再长也就到这儿，免得一条离谱的名字把面板撑满屏
    COLUMN_SPACING = 4
    SCROLL_BAR_WIDTH = 8  # 和样式表里 `QScrollBar:vertical { width: 8px }` 对齐

    def __init__(self, parent):

        QtWidgets.QWidget.__init__(self, parent, QtCore.Qt.Popup)

        self.__entries = []  # ( 名字, 分类, 搜索文本, item, 分类各段, key )
        self.__onAccept = None
        self.__baseTitle = None
        # 「常用 / 喜爱」那份记录。None = 这个面板不带这功能（内部快捷键弹出来的
        # 那些菜单就不带 —— 它们的条目和建节点不是一回事，混进一个榜里没意义）。
        self.__usage = None
        # [ [ QListWidget, path, window, anchorRow ] ]；第 0 列在根窗口里
        # （window = None），第 1 列往后各自一个 `_ColumnWindow`
        self.__columns = []
        self.__focused = 0
        # 正在拖某一列的滚动条（滚动条收不到 popup 派发来的事件，只能自己喂）——
        # 非 None 期间所有鼠标事件都转发给它，拖出滚动条范围也有效。
        self.__scrollDrag = None
        # 滚轮还没攒够一行的那点增量（触摸板一次只报十几）
        self.__wheelRemainder = 0.0

        self.setMouseTracking(True)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            """
			QWidget { background-color: %s; }
			QLineEdit {
				background-color: %s; color: %s; border: 1px solid %s;
				border-radius: 3px; padding: 4px 6px; selection-background-color: %s;
			}
			QListWidget { background-color: %s; border: none; outline: none; }
			QScrollBar:vertical { background: %s; width: 8px; margin: 0; }
			QScrollBar::handle:vertical { background: #4a4a4a; border-radius: 4px; min-height: 24px; }
			QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
			"""
            % (
                _toolBarColor,
                _backgroundColor,
                _textColor,
                _cardBorder,
                _selectedBorder,
                _toolBarColor,
                _toolBarColor,
            )
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.__title = QtWidgets.QLabel()
        self.__title.setStyleSheet("color: %s; font-weight: bold;" % _dimTextColor)
        self.__title.setVisible(False)
        layout.addWidget(self.__title)

        self.__search = QtWidgets.QLineEdit()
        self.__search.setPlaceholderText(
            "Search (Enter to accept, ← → to navigate, right-click / Ctrl+D to favourite)"
        )
        self.__search.textChanged.connect(self.__searchChanged)
        self.__search.installEventFilter(self)
        layout.addWidget(self.__search)

        self.__columnsLayout = QtWidgets.QHBoxLayout()
        self.__columnsLayout.setContentsMargins(0, 0, 0, 0)
        self.__columnsLayout.setSpacing(6)
        layout.addLayout(self.__columnsLayout, 1)

        self.__addColumn([])

    ##########################################################################
    # 对外
    ##########################################################################

    ## `usage` 给一份 `_CreatorUsage` 就在根层多出「★ 喜爱」「常用」两节，
    # 并且搜索时把它们往前排、选中时记一笔。None = 不带这功能。
    def setEntries(self, entries, usage=None):

        self.__usage = usage

        # 顺手把分类拆成段（走层级时要用）和 key（「常用 / 喜爱」认这个）
        self.__entries = [
            (
                name,
                category,
                searchText,
                item,
                tuple(p for p in category.split(" / ") if p),
                _entryKey(name, category),
            )
            for name, category, searchText, item in entries
        ]

        self.__reset()

    ## 面板顶上那行小标题（比如「切换上下文」）。None = 不显示。
    def setTitle(self, title):

        self.__baseTitle = title
        self.__updateTitle()

    ## `onAccept( menuItem )` 在选中一条时调用。
    def popupAt(self, globalPosition, onAccept):

        self.__onAccept = onAccept

        self.__search.blockSignals(True)
        self.__search.setText("")
        self.__search.blockSignals(False)
        self.__reset()

        # 别让面板跑出**鼠标所在那块**屏幕（问不出是哪块就不夹，见 `_clampToRect`）
        screen = _screenAt(QtCore.QPoint(globalPosition))
        position = _clampToRect(
            globalPosition,
            self.size(),
            screen.availableGeometry() if screen is not None else None,
        )

        self.move(position)
        self.show()
        self.__search.setFocus(QtCore.Qt.PopupFocusReason)

    ## 直接设搜索词（等同于用户在搜索框里打字）。
    def setSearchText(self, text):

        # 文字没变时 `textChanged` 不发，那时也要按现在的条目重排一遍
        if self.__search.text() == (text or ""):
            self.__refresh()
        else:
            self.__search.setText(text or "")

    ##########################################################################
    # 测试 / 调试用的读写口
    ##########################################################################

    def columnCount(self):

        return len(self.__columns)

    def rowCount(self, column=0):

        widget = self.__columnWidget(column)
        return widget.count() if widget is not None else 0

    def rowAt(self, index, column=0):

        widget = self.__columnWidget(column)
        listItem = widget.item(index) if widget is not None else None
        if listItem is None:
            return None

        return (
            listItem.text(),
            listItem.data(QtCore.Qt.UserRole + 1),
            listItem.data(QtCore.Qt.UserRole),
            listItem.data(QtCore.Qt.UserRole + 2),
        )

    ## 这一行的「常用 / 喜爱」身份（分类行 / 标题行是 None）。
    def rowKey(self, index, column=0):

        return self.__rowData(index, column, QtCore.Qt.UserRole + 5)

    ## 这一行钉住了没。
    def rowIsFavourite(self, index, column=0):

        return bool(self.__rowData(index, column, QtCore.Qt.UserRole + 6))

    ## 这一行勾着没（勾选型菜单条目才有）。
    def rowChecked(self, index, column=0):

        return bool(self.__rowData(index, column, QtCore.Qt.UserRole + 7))

    ## 这一行是不是分节标题（「★ 喜爱」那种）。
    def rowIsHeader(self, index, column=0):

        return bool(self.__rowData(index, column, QtCore.Qt.UserRole + 3))

    ## 钉住 / 取消钉住这一行（= 在它身上右键）。
    def toggleFavouriteRow(self, index, column=0):

        widget = self.__columnWidget(column)
        if widget is not None:
            self.__toggleFavourite(column, widget.item(index))

    def __rowData(self, index, column, role):

        widget = self.__columnWidget(column)
        listItem = widget.item(index) if widget is not None else None
        return listItem.data(role) if listItem is not None else None

    def hoverRow(self, index, column=0):

        widget = self.__columnWidget(column)
        if widget is not None:
            self.__hovered(column, widget.item(index))

    def activateRow(self, index, column=0):

        widget = self.__columnWidget(column)
        if widget is not None:
            self.__activated(column, widget.item(index))

    ## 把根窗口和所有子列窗口拼成一张图（出图 / 截图用 —— 现在一列一个窗口，
    # 光 `grab()` 根窗口只拿得到第一列）。
    def grabAll(self):

        pieces = [(self, QtCore.QRect(self.geometry()))]
        bounds = QtCore.QRect(self.geometry())

        for index in range(1, len(self.__columns)):
            window = self.__columns[index][2]
            if window is None or not window.isVisible():
                continue
            pieces.append((window, QtCore.QRect(window.geometry())))
            bounds = bounds.united(window.geometry())

        image = QtGui.QImage(bounds.size(), QtGui.QImage.Format_ARGB32)
        image.fill(QtGui.QColor(0, 0, 0, 0))

        painter = QtGui.QPainter(image)
        for window, geometry in pieces:
            painter.drawPixmap(geometry.topLeft() - bounds.topLeft(), window.grab())
        painter.end()

        return image

    ## 某一列自己那个窗口（第 0 列在根窗口里，返回 None）。
    def columnWindow(self, column):

        if 0 <= column < len(self.__columns):
            return self.__columns[column][2]
        return None

    ## 某一列显示的是哪一层。
    def columnPath(self, column):

        if 0 <= column < len(self.__columns):
            return list(self.__columns[column][1])
        return None

    ## 最深那一列的层级。
    def path(self):

        return list(self.__columns[-1][1]) if self.__columns else []

    ##########################################################################
    # 列
    ##########################################################################

    def __columnWidget(self, column):

        if 0 <= column < len(self.__columns):
            return self.__columns[column][0]
        return None

    ## 加一列。`anchorRow` = 它是从上一列**哪一行**展开出来的（子列的第一行要和那一行
    # 对齐，原生 QMenu 就是这样）。
    def __addColumn(self, path, anchorRow=None):

        widget = QtWidgets.QListWidget()
        widget.setItemDelegate(_CreatorDelegate(widget))
        widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        widget.setFrameShape(QtWidgets.QFrame.NoFrame)
        widget.setMouseTracking(True)
        widget.setUniformItemSizes(True)

        # **右键得靠事件过滤器**：popup grab 之下，落在某一列上的鼠标事件是直接发给
        # 那个 `QListWidget` 的（左键靠 `itemClicked` 接住），右键 `QAbstractItemView`
        # 自己吃掉、什么信号都不发 —— `_ColumnWindow.mousePressEvent` 只在事件落在
        # 列表**外面**时才轮得到。装在 viewport 上先截一手。
        widget.viewport().installEventFilter(self)

        index = len(self.__columns)
        widget.itemEntered.connect(functools.partial(self.__hovered, index))
        widget.itemClicked.connect(functools.partial(self.__activated, index))
        widget.itemActivated.connect(functools.partial(self.__activated, index))

        if index:
            # 第二列往后各自一个窗口（原生 QMenu 就是这样），高度只看自己的内容
            widget.setStyleSheet(
                "QListWidget { background-color: %s; }" % _backgroundColor
            )
            self.__columns.append(
                [widget, list(path), _ColumnWindow(self, widget), anchorRow]
            )
        else:
            self.__columnsLayout.addWidget(widget, 0, QtCore.Qt.AlignTop)
            self.__columns.append([widget, list(path), None, None])

        return index

    def __trimColumns(self, count):

        # 第 0 列（根层，嵌在面板里）永远留着；收的都是各自一个窗口的子列
        count = max(1, count)
        while len(self.__columns) > count:
            window = self.__columns.pop()[2]
            # 可能正在这个窗口自己的事件处理里收它 —— 一律 deleteLater
            window.hide()
            window.deleteLater()

        self.__focused = min(self.__focused, len(self.__columns) - 1)

    def __reset(self):

        self.__trimColumns(1)
        self.__focused = 0
        self.__refresh()

    def __searchChanged(self, text):

        self.__refresh()

    def __refresh(self):

        text = self.__search.text().strip()

        if text:
            self.__trimColumns(1)
            self.__fill(0, self.__searchRows(text))
        else:
            self.__fill(0, self.__browseRows([]))

        self.__updateTitle()
        self.__updateGeometry()

    def __fill(self, column, rows):

        widget = self.__columnWidget(column)
        if widget is None:
            return

        widget.clear()
        for row in rows:
            listItem = QtWidgets.QListWidgetItem(row.label)
            listItem.setData(QtCore.Qt.UserRole, row.item)
            listItem.setData(QtCore.Qt.UserRole + 1, row.rightText)
            listItem.setData(QtCore.Qt.UserRole + 2, row.category)
            listItem.setData(QtCore.Qt.UserRole + 3, row.header)
            listItem.setData(
                QtCore.Qt.UserRole + 4,
                row.header or (row.item is not None and _entryDisabled(row.item)),
            )
            listItem.setData(QtCore.Qt.UserRole + 5, row.key)
            listItem.setData(
                QtCore.Qt.UserRole + 6,
                bool(
                    row.key
                    and self.__usage is not None
                    and self.__usage.isFavourite(row.key)
                ),
            )
            # 勾选型条目（S 键那种「当前是哪个 shot / layer / quality」）现在勾着没 ——
            # 原生菜单画的是复选框，我们在左边留白里点一个对勾
            listItem.setData(
                QtCore.Qt.UserRole + 7,
                bool(row.item is not None and _entryCheckState(row.item)),
            )
            if row.header:
                listItem.setFlags(QtCore.Qt.NoItemFlags)
            widget.addItem(listItem)

        # **别预选第一行**：鼠标还没进这一列，第一行就亮着，看着就是"残留"。原生 QMenu 打开
        # 子菜单也不预选。只有**搜过**的时候预选第一条，好让回车直接建出最匹配的那个。
        if widget.count() and self.__search.text().strip():
            widget.setCurrentRow(0)
        else:
            widget.setCurrentRow(-1)

    ##########################################################################
    # 内容
    ##########################################################################

    def __searchRows(self, text):

        usage = self.__usage

        scored = []
        for name, category, searchText, item, _, key in self.__entries:

            score = _matchScore(text, searchText)
            if score is None:
                score = _matchScore(text, name)
            if score is None:
                score = _matchScore(text, category)
                if score is not None:
                    score += 2000
            if score is None:
                continue

            # 用得多的、钉住的只在**同一档里**往前挪：先按档排，档内再算加分，
            # 一个「词中命中」再常用也抬不到「名字前缀命中」前面去。
            tier = bisect.bisect_right(_SCORE_TIERS, score)
            if usage is not None:
                score -= (8 if usage.isFavourite(key) else 0) + min(usage.count(key), 6)

            scored.append((tier, score, len(name), name, category, item, key))

        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3].lower()))

        return [
            _Row(label=name, rightText=category, item=item, key=key)
            for _, _, _, name, category, item, key in scored[:200]
        ]

    ## 根层最上面那两节：「★ 喜爱」（用户自己钉的）和「常用」（用得最多的几个）。
    #
    # 只在**根层**出现，而且只有带 `usage` 的面板才有（Tab 建节点那个）。
    def __pinnedRows(self):

        usage = self.__usage
        if usage is None:
            return []

        byKey = {entry[5]: entry for entry in self.__entries}

        favourites = [byKey[k] for k in usage.favourites() if k in byKey]
        frequent = [
            byKey[k]
            for k in usage.frequent(exclude=[e[5] for e in favourites])
            if k in byKey
        ]

        rows = []

        if favourites:
            # ★ Favourites = 喜爱（右键 / Ctrl+D 增删）
            rows.append(
                _Row(
                    label="★ Favourites", rightText="right-click / Ctrl+D", header=True
                )
            )
            rows.extend(self.__leafRow(entry, rightText="") for entry in favourites)

        if frequent:
            # Frequent = 常用（按用过多少次排）
            rows.append(_Row(label="Frequent", rightText="by usage count", header=True))
            rows.extend(self.__leafRow(entry, rightText="") for entry in frequent)

        return rows

    ## 一条条目摊成一行。
    #
    # **浏览态（没搜索）一律不写右边那串分类层级**：层级本来就摆在眼前（一列就是一级、
    # 平铺的那种也只有一层），右边再写一遍纯属挤名字 —— 名字才是拿来认节点的。
    # 只有**搜索结果**才写（那时条目来自全图各处，得告诉你它在哪儿），见 `__searchRows`。
    def __leafRow(self, entry, rightText=None):

        name, category, _, item, _, key = entry
        return _Row(
            label=name,
            rightText=category if rightText is None else rightText,
            item=item,
            key=key,
        )

    ## 所有条目一共分几个顶层分类（没有分类的条目不算）。
    def __topLevelCategoryCount(self):

        return len({entry[4][0] for entry in self.__entries if entry[4]})

    ## 某一层要列哪些行，返回 [ `_Row` ]。
    def __browseRows(self, path):

        # 「★ 喜爱」/「常用」只钉在根层最上面
        rows = self.__pinnedRows() if not path else []
        pinned = bool(rows)

        # 条目不多、而且本来就是一堆同类的东西 → 平铺，别逼着人一层层点。
        # **顶层分类多于一个就照分类分列**（原生菜单在这里是几个分组子菜单）——
        # 一股脑摊平会把"这条属于哪一组"挤成右边一行小字，「切换上下文」那类分组
        # 菜单（Switch To Shot / Layer / …）就成了几十条堆在一起。
        if (
            not path
            and len(self.__entries) <= PANEL_FLAT_LIMIT
            and self.__topLevelCategoryCount() <= 1
        ):
            if pinned:
                rows.append(_Row(label="All", header=True))
            for entry in sorted(
                self.__entries, key=lambda e: (e[1].lower(), e[0].lower())
            ):
                rows.append(self.__leafRow(entry, rightText=""))
            return rows

        pathTuple = tuple(path)
        depth = len(pathTuple)

        categories = {}
        leaves = []

        for entry in self.__entries:

            parts = entry[4]
            if parts[:depth] != pathTuple:
                continue

            if len(parts) == depth:
                leaves.append(entry)
            else:
                label = parts[depth]
                categories[label] = categories.get(label, 0) + 1

        if pinned:
            rows.append(_Row(label="All", header=True))

        for label in sorted(categories, key=lambda l: l.lower()):
            rows.append(
                _Row(
                    label=label,
                    rightText="%d items  ›" % categories[label],
                    category=label,
                )
            )

        for entry in sorted(leaves, key=lambda e: e[0].lower()):
            rows.append(self.__leafRow(entry, rightText=""))

        return rows

    ##########################################################################
    # 交互
    ##########################################################################

    ## 鼠标停在第 `column` 列的某一行上：是分类就往右再开一列，不是就把右边的收掉。
    def __hovered(self, column, listItem):

        if listItem is None or listItem.data(QtCore.Qt.UserRole + 3):
            # 分节标题：不高亮、不展开，右边那些列也别收（鼠标只是路过）
            return

        self.__focused = column

        # 鼠标停在哪行，哪行就是这一列的当前行 —— 高亮跟着鼠标走（QMenu 就是这手感）。
        # 更左边那些列的高亮**不动**，正好把「现在展开的是哪一条」留在原地。
        widget = self.__columnWidget(column)
        if widget is not None and widget.currentItem() is not listItem:
            widget.setCurrentItem(listItem)

        category = listItem.data(QtCore.Qt.UserRole + 2)
        if category:
            self.__cascade(column, category)
        elif len(self.__columns) > column + 1:
            # 划过叶子：右边开着的列收掉。没有可收的就什么都不用重算（鼠标每动一下都进这里）
            self.__trimColumns(column + 1)
            self.__updateGeometry()

    def __cascade(self, column, category):

        path = list(self.__columns[column][1]) + [category]

        # 已经开着同一层就别重建了（不然鼠标一动就闪）
        if len(self.__columns) > column + 1 and self.__columns[column + 1][1] == path:
            return column + 1

        self.__trimColumns(column + 1)

        # 列数不设上限：每列自己一个窗口，右边放不下就翻到左边去（`__layoutColumnWindows`），
        # 不用再像"一个大框装所有列"那样把最左边那列顶掉。
        # 从上一列的**哪一行**展开的 —— 子列要对着这一行开（不是对着面板顶上）
        parentWidget = self.__columnWidget(column)
        anchorRow = None
        if parentWidget is not None:
            for row in range(parentWidget.count()):
                if parentWidget.item(row).data(QtCore.Qt.UserRole + 2) == category:
                    anchorRow = row
                    break

        index = self.__addColumn(path, anchorRow)
        self.__fill(index, self.__browseRows(path))
        self.__updateTitle()
        self.__updateGeometry()

        return index

    def __activated(self, column, listItem):

        if listItem is None or listItem.data(QtCore.Qt.UserRole + 4):
            return

        category = listItem.data(QtCore.Qt.UserRole + 2)
        if category:
            index = self.__cascade(column, category)
            widget = self.__columnWidget(index)
            if widget is not None and widget.count():
                self.__focused = index
                widget.setCurrentRow(0)
            return

        item = listItem.data(QtCore.Qt.UserRole)
        if item is None:
            return

        # 记一笔「用过」 —— 「常用」那一节就是这么排出来的
        if self.__usage is not None:
            self.__usage.record(listItem.data(QtCore.Qt.UserRole + 5))

        onAccept = self.__onAccept
        self.__onAccept = None
        self.hide()

        if onAccept is not None:
            onAccept(item)

    ## 钉住 / 取消钉住一行（右键，或 Ctrl+D 打在当前行上）。
    #
    # **不关面板** —— 收藏是顺手干的事，干完还在原地接着挑。
    def __toggleFavourite(self, column, listItem):

        if listItem is None or self.__usage is None:
            return

        key = listItem.data(QtCore.Qt.UserRole + 5)
        if not key:
            return

        self.__usage.toggleFavourite(key)
        self.__focused = column
        self.__refill()

    ## 把现在开着的这几列**按各自的层级原地重填一遍**，选中的那行跟着走。
    #
    # 收藏一变，根层「★ 喜爱」那一节的行数就变了 —— 按下标记选中行会串位，
    # 所以记的是 key（分类行记它的分类名）。
    def __refill(self):

        marks = []
        for widget, _, _, _ in self.__columns:
            listItem = widget.currentItem()
            marks.append(
                (
                    listItem.data(QtCore.Qt.UserRole + 5),
                    listItem.data(QtCore.Qt.UserRole + 2),
                )
                if listItem is not None
                else (None, None)
            )

        searching = bool(self.__search.text().strip())

        for index, (widget, path, _, _) in enumerate(self.__columns):
            if index == 0 and searching:
                self.__fill(0, self.__searchRows(self.__search.text().strip()))
            else:
                self.__fill(index, self.__browseRows(path))

        for index, (key, category) in enumerate(marks):

            widget = self.__columnWidget(index)
            if widget is None or (key is None and category is None):
                continue

            for row in range(widget.count()):
                listItem = widget.item(row)
                if (
                    key is not None and listItem.data(QtCore.Qt.UserRole + 5) == key
                ) or (
                    key is None and listItem.data(QtCore.Qt.UserRole + 2) == category
                ):
                    widget.setCurrentRow(row)
                    break

        self.__updateGeometry()

    ## 往左收一列。返回 True 表示确实动了。
    def __goUp(self):

        if len(self.__columns) > 1:
            self.__trimColumns(len(self.__columns) - 1)
            self.__focused = len(self.__columns) - 1
            self.__updateTitle()
            self.__updateGeometry()
            return True

        return False

    ##########################################################################
    # 外观
    ##########################################################################

    ## 顶上那行小标题。
    #
    # **不写当前层级**：写了的话，从根层往里走一级标题就从「没有」变成「有」，整块面板
    # 连带第一列一起往下挪 20px —— 「进下一级，上一级不动」就破了。层级本来就摆在眼前
    # （一列就是一级）。
    def __updateTitle(self):

        text = self.__baseTitle or ""
        self.__title.setText(text)
        self.__title.setVisible(bool(text))

    ## 这一列要多宽：按**里面最长那行**算（名字一个字都不截 + 右侧最多占
    # `ROW_RIGHT_MAX_WIDTH`），下限 `FIRST_COLUMN_WIDTH` / `COLUMN_WIDTH`，上限 `COLUMN_MAX_WIDTH`。
    def __columnContentWidth(self, column):

        widget = self.__columnWidget(column)
        minimum = self.FIRST_COLUMN_WIDTH if column == 0 else self.COLUMN_WIDTH
        if widget is None:
            return minimum

        need = 0
        for index in range(widget.count()):
            listItem = widget.item(index)
            header = bool(listItem.data(QtCore.Qt.UserRole + 3))
            need = max(
                need,
                _rowWidthHint(
                    listItem.text(),
                    listItem.data(QtCore.Qt.UserRole + 1) or "",
                    header=header,
                    category=bool(listItem.data(QtCore.Qt.UserRole + 2)) or header,
                    favourite=bool(listItem.data(QtCore.Qt.UserRole + 6)),
                ),
            )

        # 行数到上限会出滚动条，它压在 viewport 右边，得把这点宽度加回去
        if widget.count() > self.MAX_VISIBLE_ROWS:
            need += self.SCROLL_BAR_WIDTH + 2

        return max(minimum, min(need, self.COLUMN_MAX_WIDTH))

    ## 一列显示几行（超过上限就出滚动条）。
    def __rowsFor(self, widget):

        return max(self.MIN_VISIBLE_ROWS, min(self.MAX_VISIBLE_ROWS, widget.count()))

    ## 根窗口 = 标题 + 搜索框 + **第一列**。高度只看第一列自己有多少行 ——
    # 按下 Tab 是几条就多高，往右展开多少级都不会再动它一下（原生 QMenu 同款）。
    def __updateGeometry(self):

        widget = self.__columnWidget(0)
        rows = self.__rowsFor(widget)
        columnWidth = self.__columnContentWidth(0)
        widget.setFixedSize(columnWidth, rows * self.ROW_HEIGHT + 4)

        margins = self.layout().contentsMargins()

        width = columnWidth + margins.left() + margins.right()

        height = margins.top() + margins.bottom()
        height += self.__search.sizeHint().height()
        height += self.layout().spacing()
        # 用「有没有文字」判，不能用 `isVisible()` —— 面板还没 `show()` 时它恒为 False，
        # 算出来的高度会少一行（无头测试里就是这么发现的）。
        if self.__title.text():
            height += self.__title.sizeHint().height() + self.layout().spacing()
        height += rows * self.ROW_HEIGHT + 4

        self.setFixedSize(width, height)
        self.__layoutColumnWindows()

    ## 把第二列往后那些窗口摆好：顶端和第一列对齐，一列接一列往右排；
    # 右边放不下就翻到左边去（QMenu 也是这么干的），下边放不下就往上挪。
    def __layoutColumnWindows(self):

        anchor = self.__columnWidget(0)
        if anchor is None:
            return

        # 顶端对齐第一列的第一行；左右从**根窗口的边**算起（不是列表控件的边，
        # 不然子列会压在根窗口边框上）
        origin = anchor.mapToGlobal(QtCore.QPoint(0, 0))
        rootGeometry = self.geometry()
        top = origin.y() - _ColumnWindow.MARGIN
        left = rootGeometry.left()
        right = rootGeometry.right() + 1

        screen = _screenAt(QtCore.QPoint(right, origin.y()))
        available = screen.availableGeometry() if screen is not None else None

        for index in range(1, len(self.__columns)):

            widget, _, window, anchorRow = self.__columns[index]
            if window is None:
                continue

            # **从展开它的那一行开始**（原生 QMenu 的子菜单就是对着那一行弹的）。
            anchorWidget = self.__columnWidget(index - 1)
            if (
                anchorRow is not None
                and anchorWidget is not None
                and anchorRow < anchorWidget.count()
            ):
                anchorItem = anchorWidget.item(anchorRow)
                rect = anchorWidget.visualItemRect(anchorItem)
                top = (
                    anchorWidget.viewport().mapToGlobal(rect.topLeft()).y()
                    - _ColumnWindow.MARGIN
                )

            rows = self.__rowsFor(widget)
            columnWidth = self.__columnContentWidth(index)
            widget.setFixedSize(columnWidth, rows * self.ROW_HEIGHT + 4)
            window.setFixedSize(
                columnWidth + 2 * _ColumnWindow.MARGIN,
                rows * self.ROW_HEIGHT + 4 + 2 * _ColumnWindow.MARGIN,
            )

            x = right + self.COLUMN_SPACING
            y = top

            if available is not None:
                if x + window.width() > available.right():
                    x = left - window.width() - self.COLUMN_SPACING
                x = max(available.left(), min(x, available.right() - window.width()))
                y = max(available.top(), min(y, available.bottom() - window.height()))

            # **已经摆好的窗口别重复 move**：窗口没 map 之前 `move()` 给的是外框位置、
            # map 之后给的是内容位置，来回 move 每次漂 2px（实测），于是"上一级"又动了。
            target = QtCore.QPoint(x, y)
            if not window.isVisible():
                window.move(target)
                window.show()
            elif (
                window.geometry().topLeft() - target
            ).manhattanLength() > 2 * _ColumnWindow.MARGIN:
                window.move(target)

            placed = window.geometry()
            left = placed.left()
            right = placed.right() + 1

    ##########################################################################
    # 键盘
    ##########################################################################

    def __focusedWidget(self):

        return self.__columnWidget(min(self.__focused, len(self.__columns) - 1))

    def __moveSelection(self, delta):

        widget = self.__focusedWidget()
        if widget is None or not widget.count():
            return

        count = widget.count()
        current = widget.currentRow()
        if current < 0:
            # 还没选中任何一行（浏览时不预选）：往下从第一行起、往上从最后一行起
            row = 0 if delta > 0 else count - 1
        elif abs(delta) > 1:
            # 翻页到头就停在头上，不绕回去
            row = max(0, min(count - 1, current + delta))
        else:
            row = (current + delta) % count

        # 分节标题（「★ 喜爱」这些）选不中 —— 顺着方向继续走
        step = 1 if delta >= 0 else -1
        for _ in range(count):
            if not widget.item(row).data(QtCore.Qt.UserRole + 3):
                break
            row = (row + step) % count
        else:
            return

        widget.setCurrentRow(row)

        # 走到分类上就顺手把右边那列开出来（和鼠标悬停一致）
        listItem = widget.currentItem()
        if listItem is not None:
            category = listItem.data(QtCore.Qt.UserRole + 2)
            if category:
                self.__cascade(self.__focused, category)
            else:
                self.__trimColumns(self.__focused + 1)
                self.__updateGeometry()

    ##########################################################################
    # 嵌套 popup 的事件派发
    ##########################################################################

    ## 全局坐标落在哪一列上，返回 ( 列号, 那一行 )。都不在返回 ( None, None )。
    def __columnAt(self, globalPosition):

        for index in range(len(self.__columns) - 1, -1, -1):
            widget = self.__columns[index][0]
            viewport = widget.viewport()
            local = viewport.mapFromGlobal(globalPosition)
            if viewport.rect().contains(local):
                return index, widget.itemAt(local)

        return None, None

    ## 鼠标事件只发给**最上面**那个 popup（真机实测），所以鼠标退回左边那些列上时，
    # 事件是以「窗口外的坐标」落在最上面那个子列窗口上的。统一在这儿按全局坐标派发，
    # 左边的列照样有高亮、点得动。QMenu 内部也是这么转发的。
    def _routeMouse(self, kind, globalPosition, button=QtCore.Qt.LeftButton):

        # **右键 = 钉住 / 取消钉住**，不建节点、不关面板（滚动条上右键也一样）。
        # 按下就干（不等松手）—— 和右键菜单一个手感。
        if button == QtCore.Qt.RightButton:
            if kind == "press":
                column, listItem = self.__columnAt(globalPosition)
                if column is not None:
                    self.__toggleFavourite(column, listItem)
            return

        # 正在拖某一列的滚动条：期间所有事件（含拖出滚动条范围之后）都转发给它，
        # 别再落到列表 / 关面板的判据上。
        if self.__scrollDrag is not None:
            self.__forwardToScrollBar(self.__scrollDrag, kind, globalPosition, button)
            if kind == "release":
                self.__scrollDrag = None
            return

        column, listItem = self.__columnAt(globalPosition)

        if column is None:
            # 点在某一列的滚动条上：press 按下就喂给它（开拖），move / release 也照发。
            scrollBar = self.__scrollBarAt(globalPosition)
            if scrollBar is not None:
                self.__forwardToScrollBar(scrollBar, kind, globalPosition, button)
                if kind == "press":
                    self.__scrollDrag = scrollBar
                return
            # 点在自己窗口里（标题 / 搜索框 / 边距上）不算"点外面"，别把面板关了
            if kind == "press" and not self.__insideAnyWindow(globalPosition):
                self.__onAccept = None
                self.hide()
            return

        if kind == "move":
            self.__hovered(column, listItem)
        elif kind == "release":
            self.__activated(column, listItem)

    ## 滚轮。**鼠标在面板上任何地方都能滚**（标题、搜索框、边距、滚动条上都算）——
    # Qt 只把滚轮发给光标正下方那个控件，所以不这么派发的话只有压在列表上才滚得动。
    #
    # 滚哪一列：光标压着哪一列就滚哪一列；都没压着就滚**光标所在那个窗口**的列；
    # 再不行就滚第一列（根窗口的标题 / 搜索框 / 边距上滚，滚的就是它）。
    def _routeWheel(self, globalPosition, delta):

        column, _ = self.__columnAt(globalPosition)

        if column is None:
            for index in range(len(self.__columns) - 1, 0, -1):
                window = self.__columns[index][2]
                if (
                    window is not None
                    and window.isVisible()
                    and window.geometry().contains(globalPosition)
                ):
                    column = index
                    break

        if column is None:
            column = 0

        widget = self.__columnWidget(column)
        if widget is None:
            return

        scrollBar = widget.verticalScrollBar()
        if scrollBar is None or scrollBar.maximum() <= scrollBar.minimum():
            return

        # 一格滚轮（120）= 系统设定的行数，和别处滚起来一个手感。触摸板 / 平滑滚轮
        # 一次只报十几的增量，攒够一行再滚，否则这些设备上永远滚不动。
        lines = QtWidgets.QApplication.wheelScrollLines() or 3
        self.__wheelRemainder += delta / 120.0 * lines
        steps = math.trunc(self.__wheelRemainder)
        self.__wheelRemainder -= steps
        if steps:
            scrollBar.setValue(scrollBar.value() - steps * scrollBar.singleStep())

    ## 这个全局坐标落在哪一列的可视滚动条上（`__columnAt` 只认 viewport，滚动条在
    # viewport 外面、永远够不着）。注意第 0 列在根窗口里，子列各自一个窗口 ——
    # 子列一开，所有鼠标事件都到最上面那个 popup，这根滚动条只能靠转发。
    def __scrollBarAt(self, globalPosition):

        for index in range(len(self.__columns) - 1, -1, -1):
            widget = self.__columns[index][0]
            scrollBar = widget.verticalScrollBar()
            if scrollBar is not None and scrollBar.isVisible():
                local = scrollBar.mapFromGlobal(globalPosition)
                if scrollBar.rect().contains(local):
                    return scrollBar

        return None

    ## 把一次鼠标事件（按下 / 移动 / 松手）转发给某根滚动条 —— 滚动条自己就会处理
    # 拖把手、点滑轨翻页这些。坐标转成滚动条自己的局部坐标。
    def __forwardToScrollBar(
        self, scrollBar, kind, globalPosition, button=QtCore.Qt.LeftButton
    ):

        local = scrollBar.mapFromGlobal(globalPosition)
        modifiers = QtWidgets.QApplication.keyboardModifiers()

        if kind == "press":
            qevent = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonPress,
                local,
                globalPosition,
                button,
                button,
                modifiers,
            )
        elif kind == "move":
            qevent = QtGui.QMouseEvent(
                QtCore.QEvent.MouseMove,
                local,
                globalPosition,
                QtCore.Qt.NoButton,
                button,
                modifiers,
            )
        else:  # release
            qevent = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonRelease,
                local,
                globalPosition,
                button,
                QtCore.Qt.NoButton,
                modifiers,
            )

        QtWidgets.QApplication.sendEvent(scrollBar, qevent)

    ## 这个全局坐标是不是落在我们自己某个窗口上（根窗口或任一子列窗口）。
    def __insideAnyWindow(self, globalPosition):

        if self.isVisible() and self.geometry().contains(globalPosition):
            return True

        for _, _, window, _ in self.__columns:
            if (
                window is not None
                and window.isVisible()
                and window.geometry().contains(globalPosition)
            ):
                return True

        return False

    ## 把打字送回搜索框（子列窗口在最上面时键盘 grab 在它那儿）。
    def _forwardToSearch(self, event):

        if not event.text():
            return

        self.__search.setFocus(QtCore.Qt.PopupFocusReason)
        QtWidgets.QApplication.sendEvent(
            self.__search,
            QtGui.QKeyEvent(
                QtCore.QEvent.KeyPress,
                event.key(),
                QtCore.Qt.KeyboardModifiers(event.modifiers()),
                event.text(),
            ),
        )

    def mouseMoveEvent(self, event):

        self._routeMouse("move", _globalPos(event), event.buttons())

    def mousePressEvent(self, event):

        self._routeMouse("press", _globalPos(event), event.button())

    def mouseReleaseEvent(self, event):

        self._routeMouse("release", _globalPos(event), event.button())

    def wheelEvent(self, event):

        self._routeWheel(_globalPos(event), event.angleDelta().y())
        event.accept()

    ## 面板关掉时把子列窗口一起收掉。
    def hideEvent(self, event):

        self.__scrollDrag = None
        self.__trimColumns(1)
        QtWidgets.QWidget.hideEvent(self, event)

    def eventFilter(self, watched, event):

        if event.type() == QtCore.QEvent.KeyPress:
            if self._handleKeyEvent(event):
                return True

        # 右键 = 钉住 / 取消钉住。按下就干，并且**吃掉**这一串事件（别让列表再去改选中行、
        # 也别冒出 Qt 自己的上下文菜单）。搜索框上的右键不动它 —— 那是复制粘贴菜单。
        if watched is not self.__search:

            if (
                event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.RightButton
            ):
                self._routeMouse("press", _globalPos(event), QtCore.Qt.RightButton)
                return True

            if (
                event.type() == QtCore.QEvent.MouseButtonRelease
                and event.button() == QtCore.Qt.RightButton
            ):
                return True

            if event.type() == QtCore.QEvent.ContextMenu:
                return True

        return QtWidgets.QWidget.eventFilter(self, watched, event)

    ## 认得的快捷键在这儿处理；返回 True 表示我们接了。
    def _handleKeyEvent(self, event):

        key = event.key()

        if key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Tab):
            self.__moveSelection(1)
            return True
        if key in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Backtab):
            self.__moveSelection(-1)
            return True
        if key == QtCore.Qt.Key_PageDown:
            self.__moveSelection(10)
            return True
        if key == QtCore.Qt.Key_PageUp:
            self.__moveSelection(-10)
            return True

        if key == QtCore.Qt.Key_Right:
            widget = self.__focusedWidget()
            listItem = widget.currentItem() if widget is not None else None
            if listItem is not None and listItem.data(QtCore.Qt.UserRole + 2):
                index = self.__cascade(
                    self.__focused, listItem.data(QtCore.Qt.UserRole + 2)
                )
                nextWidget = self.__columnWidget(index)
                if nextWidget is not None and nextWidget.count():
                    self.__focused = index
                    nextWidget.setCurrentRow(0)
                return True
            return False

        # ← 收一列；没有可收的就留给搜索框挪光标（改错字时别把整个搜索词清掉）。
        # 退格只在搜索框空着时收列，否则就是删字。
        if key == QtCore.Qt.Key_Left:
            return self.__goUp()
        if key == QtCore.Qt.Key_Backspace:
            return not self.__search.text() and self.__goUp()

        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            widget = self.__focusedWidget()
            if widget is not None:
                self.__activated(self.__focused, widget.currentItem())
            return True

        # Ctrl+D：把当前这行钉住 / 取消钉住（右键干的是同一件事）
        if key == QtCore.Qt.Key_D and (event.modifiers() & QtCore.Qt.ControlModifier):
            widget = self.__focusedWidget()
            if widget is not None:
                self.__toggleFavourite(self.__focused, widget.currentItem())
            return True

        if key == QtCore.Qt.Key_Escape:
            self.__onAccept = None
            self.hide()
            return True

        return False


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
