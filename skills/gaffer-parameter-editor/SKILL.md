---
name: gaffer-parameter-editor
description: 在 Gaffer 里另做一个参数面板（替代/补充原生 NodeEditor）的标准做法：为什么内核必须复用原生、L1 皮肤 / L2 自己排版 / L3 自绘控件三级怎么选、原生 layout 元数据语义怎么读、以及和原生对齐行高对齐标签必踩的坑。基于一个自建参数面板扩展的实战沉淀（1.6.5.1 实测，1.7 差异单独列出）。
---

# Gaffer 参数面板（另做一个 NodeEditor）

想让参数面板更现代、更适合灯光日常工作时的标准做法。**先读这份，别从零摸索**，
尤其别一上来就重写控件。

参考实现是另一个未开源的扩展，这里只保留方法和坑位。它的结构可以当参照：纯逻辑 +
元数据读取一层、少量自绘控件一层、自己排版一层、外壳（Editor 注册 + 浮动纯参数面板）一层；
参数面板只做参数，找节点回节点图。

**界面语言分层（写出来的字英文、鼠标提示中文）**：标签 / 按钮 / 复选框 /
占位符 / 空态 / **齿轮菜单条目名** / 徽标一律英文；**`setToolTip` 一律中文**，而且
**菜单项的 `description` 也算提示**（Gaffer `Menu.py:457` 把它设成 `setStatusTip`）；
`IECore.msg` 那些诊断留中文。做法：每张标签表存两份 —— `X_LABELS`（英文，界面用）+
`X_LABELS_ZH`（中文，提示用，key 完全一样）；返回"给界面看的字"的纯逻辑函数一次给两份
（如 `plugSource()` 给 `label` 英文徽标 + `labelZh` 中文 + `detail` 中文细节，
tooltip 拼 `labelZh —— detail`）。**别在分支里各自拼标签** —— 把结果收成
`(kind, extra, detail, node, plug, suffix)`，英文/中文两份在一处 compose 出来，
否则加一种语言就要改十个分支。回归要有**整棵控件树的兜底扫描**（单选/多选/批量各态
遍历 `findChildren(QWidget)` 的 `text()`，出现中文就 FAIL）—— 逐个控件断言一定会漏掉
批量表头、提示条那种偶尔才建出来的控件。注意**参数自己的说明**（鼠标停在参数控件上那段）
来自 Gaffer 元数据 `description`，是官方英文原文，不属于这套规矩。

**和原生 `PlugLayout` 对齐时最容易漏的六条**（拿 1.7.1.0 源码逐函数对出来的）：
1. **activator 不是建的时候算一次就完** —— 原生每次 `plugDirtied` / context 变了都在
   `ContextTracker.acquireForFocus(node).context(node)` 里重算 `layout:activator` /
   `visibilityActivator`（Switch / Spreadsheet 命中哪一行都跟 focus 的 context 走）。自排版要
   把每个布局项记成 `(parent 下标, 项, 控件)`，`refresh()` 里逐项 `setEnabled` / 可见；**藏着的
   行也要建出来**（原生也建），可见性两路各记各的（过滤 + activator）合起来才是真可见；递归进去
   的子布局按它在上一层那一项串起来（原生是整个 `LayoutPlugValueWidget` 一起藏 / 灰）；内容
   全藏光的 tab / 分区跟着藏。`changedSignal(node)` 连上，变了 idle 刷。
2. **元数据改了要重排** —— 连 `Metadata.plugValueChangedSignal(node)` / `nodeValueChangedSignal(node)`，
   `layout:section/index/divider/accessory/width/label`、`plugValueWidget:type`、
   `layout:customWidget:*` 变了重建，其余 `layout:*` 只刷（summary / activator 的值 refresh 里重算）。
3. `layout:width` / `layout:minimumWidth`（`__setWidthFromMetadata`），别漏。
4. **自定义控件建不起来 → Error 日志 + 原位一个警告图标**（tooltip 写原因），
   不是 Debug 日志 + 默默跳过。
5. **折叠 / 当前 tab 状态写成和原生同一个 key 的非持久实例元数据**（`layout:section:<相对名>:collapsed`、
   `layout:section::currentTab`，`registerValue(parent, key, v, persistent=False)`，相对名相对布局所属
   的 parent），这样原生面板和自建面板对同一个节点的折叠状态是共享的；读的时候
   `Metadata.value(parent, key, instanceOnly=True)` 优先（类级注册的默认值排在自己的类型记忆后面）；
   程序里收放（搜索命中自动展开）要 `Gaffer.Signals.BlockedConnection` 挡着 `stateChangedSignal`，
   不写记忆。
6. **判「这个插口是不是子布局」别先把控件建出来再看类型** —— 问原生
   `GafferUI.PlugValueWidget._PlugValueWidget__creator(plug, "plugValueWidget:type")` 是不是
   `LayoutPlugValueWidget`，元数据注册的（`parameters` / `user`）和按插口类型注册的
   （`TransformPlug`）一次都认得，省掉一整个嵌套 PlugLayout 的建了又扔。

另外：原生头部那个「Node Name」标签是 `NameLabel`，**能把节点拖出去**，自建头部至少留一个
`NameLabel`（文字走 formatter，`setText` 会把名字跟踪关掉）；`nodeUI().node()` 认面板上显示的
那个节点；`plugDirtied` 照原生忽略输出插口和私有插口。

**无头测试老坑**：编辑器的更新是 `deferUntilVisible` 的，前面哪一节把主窗口 `setVisible(False)`
了，后面选节点 `_updateFromSet` 永远不跑，断言全是过期状态 —— 每一节开头 `window.setVisible(True)`。

**如果做按类型过滤的列表**（一批复选框 + 搜索框），五条实测结论：
1. **搜索 / 收展只改可见性，不重建控件** —— 敲一个字符重建几百个复选框
   既慢又丢滚动位置；只有类型集本身变了才重建，只是节点数变了只 `setText` 改标签。
   测试里取「当前可见」的复选框，判据用控件自己的 `getVisible()`（无头下 `visible()` 恒 False）。
2. **凡是「一次改一批勾选」的入口，都必须逐个 `setState` 复选框**（只改 dict 界面不变）：
   「全部/无」和**模块 master 整组开/关都算**。收口成一个
   `__applyChecked(typeNames, checked)`（改 dict + setState + 存盘 + 同步模块头 + 发信号），
   外面配**一个** `__syncing` 守卫挡 `setState` → 逐条回写的回环。
3. **「全部 / 无」搜索时只作用于命中的类型** —— 否则搜完点「无」把没搜到的也全关了，等于白搜。
4. **类型搜索框要同时收窄上面的列表**（有效类型 = 勾上的 ∩ 搜索命中的）。只筛复选框、列表
   一动不动的话，搜 `arnold` 看到列表没变，第一反应是「过滤没生效」。
   顺带在搜索行右边写一个 `显示/总数` 计数，过滤到底剩多少一眼可见。
5. 刷新开销要和图大小脱钩：列表只显示名字 → **别逐节点连 metadata 信号**；节点的
   `childAdded/Removed` 也会为**插口**发（提升插口 / ArrayPlug 长一路）→ **只认 `isinstance(child, Node)`**；
   **节点集没变就不重连全图信号**（比对 `relativeName` 集合，
   注意 `relativeName(self)` 对脚本节点会抛「不是自己的祖先」）。

信号回调小壳一律 weakref 包装（一个通用 `_WeakSlot(owner, "方法名", *args)` 就够，
别一种控件写一个类），别让 signal 钉死面板。测试遍历用自己存的登记表，
别去 `__checkboxColumn[0][0]` 猜控件结构，也别把数据塞 tooltip 里当数据用。

**先想清楚这块面板值不值得做**（1.6.5.1 实测基准）：
*换来的* —— 参数状态可见 / 值的来源 / 强搜索（**1.6 原生零过滤能力**，`PlugLayout`、`NodeEditor`
里 `setFilter`·`FilterWidget` 命中数都是 0）/ 多节点工作流（原生多选只显示 `_lastAddedNode()`）/
软范围滑条（Arnold 灯参数 `hasMinValue()` 全 False，原生给不出滑条）/
递归进子布局后粒度细一个数量级（point_light 11 个顶层插口 → 30 行、standard_surface 5 → 68 行）。
*付出的* —— ①**追版本**（`layout:*` 那套语义是照抄的，1.6→1.7 已有差异要 backport）；
②`CompoundDataPlugValueWidget` 在 1.6 递归不了（那一行只能整块用原生控件）；③批量遇到表格只能
「一张表带其他表」，改名/加删行列不同步；④**性能 0.9~1.8×**（Sphere 21.5→34.5ms、
point_light 63.4→76.2ms、standard_surface 111.8→**103.7ms 反而更快**、200 行 Spreadsheet
46.4→85.3ms），**状态/来源那一层是纯额外开销**：常规节点每次刷新 0.5~3ms，200 行的表约 **42ms**；
⑤layout 里存的是自定义 Editor 类型，没装扩展的机器打开布局就缺这块；⑥生产 7.7k 行 + 测试 3.1k 行
自己养，而原生 `NodeEditor.py`+`PlugLayout.py` 一共 1051 行由官方养 —— **而且照样依赖**原生
133 个 PlugValueWidget 子类；⑦**原生就是标准**，每处行为差异都要自己向使用者解释。
结论：做「原生做不到的那一层」值，做「重写一遍原生」不值；而且要留一条退回原生的开关。

---

## 一、和 GraphEditor 完全相反：**能改，但绝不能重写内核**

| | GraphEditor | NodeEditor |
| --- | --- | --- |
| 实现 | C++ + 写死 GLSL，`Style`/`GraphGadget`/`GraphLayout` 都不能 Python 子类化 | **100% Python + Qt**，全可子类化 / patch / 注册 |
| 结论 | 改不动，只能另起 Qt 视图 | 能改；从零重写是天文数字 |

量化一下（1.6.5.1）：`NodeEditor.py` 只有 245 行空壳，活都在 `PlugLayout.py`（806 行；1.7 是 939 行）
加 **133 个 PlugValueWidget 子类**、**582 处 `plugValueWidget:type` 注册**，再加站点编译扩展里注册的
**私有控件类**（靠元数据里的类名 import 出来）。重写内核 = 要承载任意第三方控件 +
复刻 `layout:section/index/divider/accessory/width/summary/activator/visibilityActivator/customWidget`
全套语义，还得永远追着官方版本跑。

**所以：控件一律 `PlugValueWidget.create()`，布局语义一律读原生那批 `layout:*` 元数据。**
不做类名替换（`NodeEditor.acquire()` 在官方代码里有 24 处调用点：ExpressionUI / EditScopeUI /
SpreadsheetUI / TransformToolUI / ConnectionPlugValueWidget…），注册一个新 Editor 类型并存。

## 二、三级改造，按需要选

| 层 | 手段 | 能拿到什么 | 代价 |
| --- | --- | --- | --- |
| **L1 皮肤** | 一份挂在自己 root 上的 QSS | 配色 / 圆角 / 分层 / hover / tab 样式 / 字重 | 几乎零风险 |
| **L2 自己排版** | `PlugLayout.layoutSections()/layoutOrder()` 拿分区与顺序 + `PlugValueWidget.create()` 拿控件，**容器全自己写** | 状态条画在行左侧、tab 标签带计数、搜索/过滤、批量编辑、折叠与 tab 记忆 | 要自己实现 activator / visibilityActivator / summary / customWidget / accessory 语义（照抄 `PlugLayout` 私有实现约 40 行） |
| **L3 自绘控件** | 只挑高频的几个自己画 | `Slider` / `ColorSwatch` / `SplineWidget` 是 Gaffer 自己 QPainter 画的，**QSS 完全管不到** | 每个控件一份维护，挑 3~5 个就够 |

**L1 能点到原生控件树，是因为 GafferUI 给每个控件的 QWidget 都挂了 dynamic property**
（`Widget.py` 的 `__styleClassName`）：`gafferClass` / `gafferClasses` / `gafferPlugValueWidget`，
再加 `gafferPlugLabel` / `gafferCollapsibleToggle` 这些 objectName。QSS 挂在自己 root 上只作用于
本面板子树，不污染别的面板。裸 QWidget 要先 `setAttribute( WA_StyledBackground, True )` 才吃背景色，
而折叠分区是**随 tab 懒建**的，换 tab 要再跑一遍这个 pass。

## 三、L2：布局语义照抄哪几个私有实现

自己排版就没人帮你读元数据了，一律照抄 `GafferUI/PlugLayout.py`：

| 要什么 | 抄哪儿 | 关键点 |
| --- | --- | --- |
| 分区名 / 顺序 | `layoutSections()` / `layoutOrder()`（**公开** classmethod，可直接用） | `includeCustomWidgets=True` 才会把 `layout:customWidget:*` 带进来（字符串项） |
| 项的元数据 | `__staticItemMetadataValue` | 插口读 `layout:<name>`，`divider`/`label` 要兼容没前缀的老名字；自定义控件读 `layout:customWidget:<名>:<name>` |
| 分区路径 | `__staticSectionPath` | 先看老名 `nodeUI:section`（`"header"` → `""`），再看 `layout:section`，点号分隔 |
| 置灰 / 隐藏 | `__updateActivations` | activator 值可以是 bool，**也可以是一段会被 `eval` 的 Python 代码字符串**（从 .grf 加载的 Box 全靠这个）；**没注册的 activator 一律当 False** |
| 分区小字 | `__updateSummariesWalk` | `layout:section:<相对名>:summary` |
| 折叠默认值 | `_Section.restoreState("collapsed")` | `layout:section:<相对名>:collapsed` |

**⚠️ summary 和 collapsed 的「相对名」是相对「布局所属的那个 parent」，不是相对节点。**
Arnold 灯的 `Shape` / `Sampling` 默认展开，就是因为 `layout:section:Shape:collapsed=False`
注册在**`parameters` 插口**上。所以每个分区都要一路带着 `(parent, 相对名)` 这一对去查，
否则灯的分区会全默认收起、summary 也全查不到。

再五条照原生的细节：

* **分区里直接放的项排在子分区前面**（`_CollapsibleLayout.update` 先 `section.widgets` 后子折叠块），
  不按 `layoutOrder` 给的先后插。
* **只有节点那一层的顶层分区是 tab**；递归进去的子布局插口（parent 是插口）一律折叠块 ——
  它落在节点「无分区」里时，它的分区摆在 tab 栏上面，别当成新 tab（会打乱 `::currentTab` 下标）。
* activator / summary 在**各自 parent 的** `ContextTracker.context( parent )` 里算；activator 代码写错直接抛、
  没注册报 Warning 再当 False；summary 只接 `Gaffer.ProcessException` 并显示 `errorSmall.png`。
* 折叠默认**收起**；搜索时有命中就展开、**清掉搜索要回到记住的状态**（`not revealChildren and restoreState("collapsed")`）。
  折叠 / 当前 tab 写的是 `layout:section:…` 实例元数据 —— 编辑器监听元数据变化时要**忽略**这两种，否则点一下折叠就整页刷新。
* 自定义的 `GafferUI.Widget` 子类**别起名 `_applyVisibility`**（撞基类，`setVisible` 内部调它）。

## 四、和原生对齐：八个必踩的坑（都是量出来的，不是看出来的）

**验证方法**：别靠看截图。写 commandFile 直接量 Qt 几何 —— 原生 `PlugWidget` 行 vs 自己的行，
逐行打 `y / height / pitch`，再打同名 tab 的内容总高、同名插口的控件高、数值列左边缘 x。
第一版一量就露馅：原生行高清一色 20px，自己的有 92 / 116 / 207 / **480** px 的行。

1. **状态条这类装饰件别用 `QSizePolicy.Expanding`**：整行的竖向策略会被它拉成 Expanding，
   父布局把剩余高度全塞给这一行 → 一行 480px。装饰件用 `Ignored`；
   **行的布局加 `setSizeConstraint( QLayout.SetMinAndMaxSize )`** —— 原生 `PlugWidget.__init__`
   就是靠这句把行永远钉在 20px 的；每个滚动页末尾再垫一个 expand 的 Spacer 吃掉多余高度。
2. **控件自带标签就别再加一列标签**：照原生 `__createPlugWidget` 的规矩 ——
   `isinstance(w, PlugValueWidget) and w.hasLabel()`（或 `layout:label == ""`）就不包标签。
   `transform` / `visualiserAttributes` / `NameValuePlug` 这些都是自带标签的。
3. **标签宽度「自适应」会害了对齐**：复合控件内部那一列是原生写死的
   `PlugWidget.labelWidth()`（**150**）。规则：节点里有自带标签的复合控件 → 宽度钉 150；
   没有 → 才自适应。对齐比省几个像素重要。
4. **递归进「子布局插口」是 L2 的成败关键**：灯的 `parameters`、节点的 `user` 注册的控件类型是
   `GafferUI.LayoutPlugValueWidget`（原生在里面再套一层 PlugLayout）。不递归 → 灯的参数全闷在
   一个原生子布局里，状态条 / 搜索 / 自绘控件全够不着（实测 point_light 从 10 行变 30 行）。
   两个判据都要：①元数据 `plugValueWidget:type == "GafferUI.LayoutPlugValueWidget"`；
   ②**按插口类型注册出来的也算** —— `transform` 就是没注册元数据、
   靠插口类型注册出来的，只看元数据会漏（用开头第 6 条的 `__creator` 判据一次都认得）。
   递归条件**不要求「有子插口」**：空的 `user`/`attributes` 也是子布局，里面挂着原生的「+」新增控件。
5. **递归不要另起一层分区名**：原生的嵌套 PlugLayout 是直接摊在当前分区里的（灯没有
   「Parameters」这个折叠头，它的 Shape/Sampling 直接就是 Settings 页里的折叠块）。
   多套一层就比原生多一个标题框。层级完全由子插口自己的 `layout:section` 决定。

6. **并排项（`layout:accessory`）的宽度要按「这一行有没有标签列」分两种**。
   原生 `_AccessoryRow` 是个干净的横排容器、**整行 stretch 全 0**，宽度纯由 size policy 决定：
   三个 `Minimum` 的按钮 → 平分（实测 560px 窗口 **177/176/177**）；`PlugWidget`（标签+控件）
   是 Expanding → 它独吞、旁边小按钮保持自然大小（实测 36px）。
   自己排版的行是「状态条 + 标签 + 控件 + 并排项 + 徽标」拼在一个容器里，控件那项一般固定
   `expand=True`（普通行靠它撑满）—— 不额外处理的话剩余宽度**全被第一项吃掉**，
   表现就是「一个按钮大、一个按钮小」（实测 417/44/42）。
   照原生的 policy 组合抄不过来（我们多了状态条和标签列），用**结构判据**：
   没有标签列（控件自带标签，两个按钮就是这种）→ 控件和所有并排项**都 expand**、Qt 平分；
   有标签列 → 只有控件 expand。`Fixed` 的项（小标记、图标按钮）不参与平分。
   ⚠️ **判据里别拿 `int(QtWidgets.QSizePolicy.Policy)` 按位算** —— PySide6 的 Qt6 Python 枚举
   `int()` 直接抛 `TypeError`，被 `except` 吞掉就变成「所有项都不能长」，症状会换个样子继续错
   （44/230/229）。枚举之间的 `==` 好用，只用 `policy == QSizePolicy.Fixed` 这种比较。
   触发场景很常见：用 UIEditor 把按钮勾成「Inline」，注册的就是 `layout:accessory`。

7. **别按插口方向过滤 —— 输出插口该显示的原生都显示**。原生 `PlugLayout.layoutOrder`
   **一句 direction 过滤都没有**（1.6.5.1 第 210-240 行），显示与否完全由
   `PlugValueWidget.create( plug )` 决定：没注册控件的（ScenePlug `in`/`out`）返回 None
   自然不显示，注册了的照样显示成**只读行**。一刀切掉 `Direction.Out` 会连带藏掉：
   **InteractiveRender 的 log 框**（`messages` 是 `Plug::Out` 的 ObjectPlug，控件
   `_MessagesPlugValueWidget`，分区 `Settings.Log`）、`resolvedRenderer`、Query 节点的
   `bound`/`center`/`size`（原生在 `Settings.Outputs` 页）、`Gaffer.Random` 的
   `outFloat`/`outColor`、Spreadsheet 的 `enabledRowNames`/`resolvedRows`/`activeRowIndex`。
   正确的跳过判据只有一条：**作者把 `plugValueWidget:type` 注册成空串**（场景处理器的 `in`）。
   状态 / 来源那两层对 Out 插口本来就该返回「默认」（别去 `getValue()` 一个输出插口）。

8. **`SetMinAndMaxSize` 只能钉「自己加了标签」的行，不然大控件被压成一条线**。
   Gaffer 的控件竖向 policy **全是 `Preferred`**（log 框 / Spreadsheet 表格 / 数值框一个样），
   原生让 log 框长到 604px 靠的是**「钉住的行长不了、没钉的那个能长」** ——
   而原生**只把 `hasLabel()` 为假的控件包进 `PlugWidget`**（`__createPlugWidget:442`），
   包了才钉；`hasLabel()` 为真的（log 框、Spreadsheet 的 `rows`）是**裸进列**的。
   所以自排版要么照这条判据分开（钉「我们加了标签」的行、能长的不钉），
   要么就会出现「行在、控件只剩 18px 高」—— 看上去就是「框没了」。
   但「自带标签」不等于「个子大」：`NameValuePlug`、`FilterPlugValueWidget` 自带标签却只有一行高，
   能长的判据要再加一条「里面有 `QAbstractItemView` / `QPlainTextEdit` / `QTextEdit`」。
   配套：**页尾那个吃剩余高度的弹簧带 stretch 会把空间整块拿走**，页里出现能长的行时
   要把 stretch 因子明确交给那一行，否则钉不钉都没用；行里的占位 `Spacer` 要给 `maximumSize`
   （不给就是 `QWIDGETSIZE_MAX`，整行最大高度被顶成无穷，`SetMinAndMaxSize` 等于没钉）。
   对拍方法：同一节点、同尺寸窗口，分别量原生 NodeUI 和自己面板里 `findChildren(QTableView)` 的高度。

对齐完的验收标准：**同一个节点、同一个分区，可见行数与行高和原生一致**
（实测 point_light：Settings 页 10 行 × 20px、Transform 页 4 行 × 20px，标签列 150）。

**量并排项的两个前置动作**（不做的话量到的全是假数据）：①按钮常在非当前 tab（比如 `User` 页），
**非当前 tab 里的控件 Qt 压根不布局**，量出来是 640x480 默认值 → 先把每个 `QTabWidget`
的每一页轮一遍再量；②自排版的 `Row._qtWidget()` 是 `GafferUI.Widget` 包出来的
**QGridLayout 壳**，真正的行布局在里面那层 `ListContainer` 上 —— 直接问壳要
`layout().stretch(i)` 会 AttributeError。

## 四·五、两条照原生做也会中招的

**1. 插口底下加子插口，面板必须跟着刷新。** 只连**节点**的 `childAdded` / `childRemoved`
是不够的 —— `ArrayPlug.resize(n+1)`（如 USD 图层列表点「+」加一个槽）、`user` 区
加参数、Box 上提升插口，子插口都是加在**插口**底下的，节点的信号一声不吭，界面停在旧行数上
（原生面板上看得到，自建面板上看不到）。原生不会有这问题：`PlugLayout`
**每一层都连自己那个 parent 的信号**（`GafferUI/PlugLayout.py:112`），递归进 `layers` 的那层
连的就是 `layers`。自排版要照做 —— 布局报出「这次递归进了哪些 parent」，编辑器逐个连，
**并且每次重建正文之后都重连一遍**（重建后递归进哪些插口可能就变了）。

**2. 顶栏那个节点图标别用原生 `icon` 元数据的 PNG，自己画。** 两个原因都是量出来的：
① **尺寸完全不统一，塞进定死的位子里会被裁**：`GafferUI.Button.setImage()` 把 `iconSize`
设成图片的**原始尺寸**，位子却是 `setFixedSize(16,16)` → 画出来是「从图正中裁一块 16x16」。
实测 `boxNode.png` 189x158、USD 的 logo **332x332**、`cameraOn.png` 25x25 —— 332 那个只露
正中央 1/20，看起来像「图标被旁边的东西盖掉一角」。② **大多数节点压根没注册 `icon`**
（1.6.5.1 全套只有六个节点 + OSLShader），顶栏空着一块。
改成矢量手绘：尺寸自己说了算、缩放不糊、每个节点都有。**分类和画法直接照本仓库节点图编辑器那份搬**
（`networkEditor/graph.py` 的 `nodeGlyph` + `qt.py` 的 `_GLYPH_PAINTERS`）—— 同一个节点在节点图卡片上
和参数面板顶栏上必须长一样；两个包各带一份、互不依赖，改一边同步另一边。参数面板要**每个节点都有图标**，
所以比节点图那边多认一批图操作节点（容器 / 切换 / 层级 / 属性 / 设置 / 读写 / 查询 / 任务）并给一个
「认不出来 = 一张节点卡片」的兜底，不返回 None。⚠️ **`InteractiveRender` / `ArnoldRender` 的类名不是
`Render`**（直接派生 `ComputeNode`，MRO 里没有叫 Render 的类），按整名判会漏，要 `endswith("Render")`。
开销实测可忽略：分类 0.002~0.005ms、换节点换图标 0.013ms、画一次 0.007ms，
对比整块面板重建 32ms。**别做成「每行一个图标」**，那才会有开销。

## 五、L3 自绘控件：两条铁律 + 软范围

1. **不走 `PlugValueWidget.registerType()`** —— 那会改到原生 NodeEditor 和所有别的面板。
   只在自己排版时挑控件（一个 `createValueWidget( plugs )` 收口）。
2. **插口上显式注册过 `plugValueWidget:type` 的一律不碰** —— 那是节点作者指定的控件，
   换掉就是破坏功能。注意判据要用 `Metadata.value()`，**不是 `registeredValues()`**
   （后者会列出一堆通配注册的 key，值其实是 None）。

写值照抄 `NumericPlugValueWidget.__setPlugValues`：`_blockedUpdateFromValues()` +
`Gaffer.UndoScope( self.scriptNode(), mergeGroup=... )`（一次拖动一个 mergeGroup = 一步撤销），
插口有动画就 `Animation.acquire(plug).insertKey( self.context().getTime(), value )` 而不是 setValue。
多插口（批量编辑）用 `sole( values )`（`from GafferUI.PlugValueWidget import sole`）判「值不一致」。
滑条旁边并排一个**原生数值框**最省事 —— 打字、动画样式、右键菜单全归它管。

**所有 `_updateFrom*` 都要能承受「Qt 控件已经销毁」**（换节点时插口的 inputChanged 还会打过来），
统一加个吞 `RuntimeError` 的装饰器。原生 `NumericPlugValueWidget` 自己也会刷这个错，别背锅也别跟着刷。

**软范围**：Arnold 灯的参数（exposure / intensity / samples / spread…）**一个都没声明 min/max**
（实测 point_light 全部 `hasMinValue()==False`），只按硬范围给滑条 → 灯光面板一根滑条都没有。
做一张名字表补软范围，**只在名叫 `parameters` 的复合插口底下生效**（否则 Sphere 的 `radius`
也会被塞进 0..5，帮倒忙）。优先级：硬范围 > 插口上自定义的软范围元数据（如 `parameterEditor:softMin/softMax`）>
名字表。软范围只管拖动区间，打字仍然可以超出去。

## 六、白捡的和还剩的

**白捡**：继承 `GafferUI.NodeSetEditor` 就自动拿到面板角上的原生 pin 控件和 `P` / `N` / `` ` ``
快捷键（`CompoundEditor._PinningWidget.editorKeyPress` 对所有子类生效），默认 node set 就是
`script.selection()`，**多选批量编辑也是免费的**（`PlugValueWidget.create()` 天生吃一组插口，
官方 LightEditor 就这么干）。但 **`PlugWidget` 不支持多插口**（内部 `getPlug()` 会抛），
批量那一行得自己拼 `LabelPlugValueWidget(plugs) + 控件`。

**但批量别当默认**：原生 `NodeEditor._updateFromSet` 多选时**只显示 `self._lastAddedNode()`**
（= node set 的最后一个，`NodeSetEditor._lastAddedNode` 就是 `nodeSet[-1]`），其余节点根本不参与。
自己的面板一多选就换成批量面板 = 和原生行为不一致，点第三个节点却看不到它的参数会以为是坏了。
默认照原生只排最后那个节点（信号连接、状态汇总、`markStates` 也都只对显示中的节点做），
批量做成显式开关（齿轮菜单 checkBox + 环境变量），并在类型标签里写明"已选 N 个（显示最后选中的）"。

**自建面板真正的存在意义在「原生做不到的那一层」，第一个值得做的是「值的来源」**：
每行回答「这个值哪来的 + 该去哪改」—— 表格（哪一列、当前命中哪一行）、表达式（原文）、
动画（关键帧数）、从哪层 Box 提升、哪个 EditScope、还是站点 `userDefault`。
做法是纯逻辑一层（顺着 `getInput()` 走到头，隔多少 Dot/BoxIO/Switch 都认得出源头）+
一个徽标（点了把面板切过去并 `reveal()` 那一行）。用到的 API：Spreadsheet 的
`activeRowIndex`（当前 context 命中哪一行）和 `out.<列名>`、`Expression.getExpression()`
（返回 `(文本, 语言)`）、提升判据是「源插口挂在**祖先** Box 上」、EditScope 判据是
源节点 `ancestor( Gaffer.EditScope )`（**1.6 没有 `Gaffer.EditScopeAlgo`**）。
两条 UI 上的取舍：①「默认值」「本节点直接改的」不给徽标（状态条已经说了，别占地方）；
②徽标默认藏着，但 tooltip 常挂在那条 3px 状态条上 —— 信息密度和可发现性都要。

**批量编辑遇到表格节点：别把表拆开，让一张表带着其他几张改**（很多自研处理器节点就是 Spreadsheet 搭的，
这是刚需）。`Spreadsheet.RowsPlug` 建不出多插口控件（`PlugValueWidget.create` 直接抛），所以"共同参数"
那套会整块跳过它。拆成一格一行（行×列摊平）不可用 —— 两百多行既不像表格也没法用。
正确做法：界面上显示**最后选中那个节点的那张原生表格**，
在它的 `plugSetSignal` 里把值写到其余节点的**同名行 / 同名列**。要点：
① 信号会从叶子一路往上再发一遍（CellPlug / RowPlug 也收到），**只认叶子**（`len(plug)==0`），
否则拿 CellPlug 去 `setValue` 直接报错；② 行按**名字**配对（各节点行顺序可能不同，默认行按位置），
`plug.relativeName( row )` 拿到 `cells.<列>.value` 再去对面 `descendant()`；
③ **在信号里写别的节点会并进当前那一步的 UndoScope**（实测一次 Ctrl+Z 两个节点一起回退），
不用自己开 scope；④ 改名不同步（配对靠名字）、结构变化（加行/删行/加列）不同步，要写在界面上；
⑤ 递归守卫必须有。
**另外：节点自己的 `enabled` 不要放进批量** —— 选中一堆节点按 `D` 就是它
（`GraphEditor.py:472`，本来就一步撤销），判据用 `node.enabledPlug()`。

**把原生的大控件（Spreadsheet 的表格、Expression 的代码框）塞进自己排的行，有两个必踩**：
1. **表格滚动会错行**。Gaffer 的表格是三张 `QTableView`（行名 / 单元格 / 默认行）拼的，
   靠 `SpreadsheetUI._LinkedScrollBar` 绑在一起，那个类为了防递归有个 `__isUpdating` 守卫
   —— **同一轮里的第二次 range 变化会被直接吃掉**。原生 NodeEditor 里表格只经历一次尺寸
   变化所以没事；自己排版的容器（tab 分区一次 + 行的 `SetMinAndMaxSize` 一次）会变两次，
   于是行名表停在旧 pageStep 上：实测行名 `range=[0,20] page=6`、单元格 `range=[0,19] page=7`，
   **滚到底就差一行**（表头错行）。修法是让每张表自己
   `QTableView.updateGeometries()` 重算一遍，两边立刻一致；建好时、刷新时、
   **以及面板尺寸每次变化**（GafferUI 没有 resize 信号，装个 `QObject` 事件过滤器收
   `QEvent.Resize`）都要同步一次。
2. **整行 hover 高亮会把几百像素的一整块点亮**。Qt 的 `:hover` 只要鼠标在**子控件**上
   就为真，所以鼠标一进表格，装着它的那一行整块高亮。判据用「里面有没有
   `QAbstractItemView` / `QPlainTextEdit` / `QTextEdit`」，有就不参与高亮。
   注意**别直接把管行背景的那个 dynamic property 设成 False** —— 那条规则同时管着
   `background: transparent`，一起没了行背景会变成调色板底色；要另挂一个属性给 hover 用。

**多选堆叠（N 个节点 N 块面板纵向叠 + 堆叠上限输入栏）**：叠几块参数面板，
整条塞进 `ScrolledContainer(horizontalMode=Never, verticalMode=Automatic)` 一起滚（1.6 的
`_ScrollArea.sizeHint()` = 子控件自然高度、`setWidgetResizable(True)` 只在子控件小于视口时才
拉伸 → 自然高度 + 外层滚动，无嵌套滚动挤压；1.6 没有 `setScrollPosition`，滚动位置只能走
`_qtWidget().verticalScrollBar().value()/.setValue()`，重建后恢复用 idle 一次性回调）。
顺序 = **MRU**（最近选择优先）：`StandardSet` 的迭代顺序是内部指针序、不是选择先后，自己连
`memberAddedSignal`/`memberRemovedSignal` 维护访问历史（index 0 = 最上层）。

**⚠️ 手感照 Nuke，不要照 Gaffer**：①**取消选择时面板必须留着** ——
`_updateFromSet` 收到空 node set 时**什么都别做**（清空历史 = 点一下空白参数面板就没了）；
空态只留给「面板全新、从没选过」和「面板里那个节点被删了」。②**一次
node set 变化只往堆栈里压一个节点** —— `memberAdded` 只记「这一轮最后加进来的是谁」
（一次多选连发几次、最后一个赢），压栈放到 `_updateFromSet` 里做；否则从节点图框选三个节点，
面板当场摊成三块。③**上限是纯全局容量，绝不跟着选中数走**（默认 1）——
「没手动设过就等于选中数」这种自动跟随会让②失效。④想一次看好几个 → 把上限调大、逐个点选。
⑤历史里的节点**被删掉要丢掉**（`script.isAncestorOf(node)`），
否则面板挂在一个已经不存在的节点上。⑥**「面板留着」之后，所有面板上的动作都要改成认
「面板上那个节点」而不是 node set** —— 齿轮菜单 / Lock / Revert to Defaults / 复制路径 /
文档按钮 / 面包屑全都走同一个「当前节点」，而它要先问「当前显示的是谁」。漏了这条的表现
很迷惑：**点齿轮什么都弹不出来**（菜单里只剩一条灰的「No Node Selected」，Qt 就画不出东西），
看着像面板卡死。「没选中节点」这句话只对**真正的空态**成立
（全新面板、从没选过 / 节点被删），凡是拿 `getNodeSet()` 判空来决定 UI 的地方都要重看一遍。
**测试注意**：取消选择不清历史 → 写一个 `resetStack(limit)` 直接清访问历史当干净起点，否则断言互相污染。

再五个坑：
① **访问历史是堆栈、不是选择集** —— 节点图普通点击是单选切换（C++ 一帧内
`selection()->clear()`+`add()`，`GraphGadget.cpp:1085-1090`），在 `memberRemovedSignal` 里删节点会
让「先选 A 再点 B」时 A 的面板直接消失。`memberRemoved` 里什么都不删；
② **换 node set（pin / 面包屑 / 跳到源头）要清历史**，但基类 `NodeSetEditor.setNodeSet`
（1.6.5.1 `NodeSetEditor.py:257-269`）**先同步调 `_updateFromSet()`、后发 `nodeSetChangedSignal`** ——
在信号里清永远太晚，要在 `_updateFromSet` 开头比对上一次的 node set（`isSame`）自己检测；
③ **拖动上限中途绝不重建**（NumericWidget 拖动每步发 `valueChangedSignal`，同步重建 + 抢焦点 =
嵌套重建 SIGSEGV），DragBegin/DragMove 只改值、DragEnd 才同步文本 + 走基类
`_NodeSetEditor__lazyUpdate()` defer 到 idle 重建；焦点守卫只从即将销毁的正文控件上抢，绝不碰工具条；
④ **每块面板保留自己的节点色**：编辑器整体皮肤只有一份（用最上层节点 accent 挂编辑器 root），
Qt 样式表**子级覆盖父级** —— 给每块面板自己的 `_qtWidget()` 再挂一份同模板的 QSS，
该面板子树里的 tab 下划线 / 输入框聚焦描边 / 选中背景就用它自己的 accent；标题行左边再加一条 3×12
accent 竖条（裸 `GafferUI.Spacer` 要 `WA_StyledBackground` + QSS 才上色）。accent **`nodeGadget:color`
元数据优先**（ArnoldLight 注册的是深金 `#bf8f00`），测试断言用函数动态取色别写死；
⑤ **堆叠列 `borderWidth` 决定面板距窗边距离**：`borderWidth=8, spacing=6` → 距窗边 ~14px，
`borderWidth=0, spacing=4` → ~6px，与单节点模式一致。

**自建面板一定要发 `NodeEditor.toolMenuSignal()`**。这是官方给外部扩展留的正式缝，
1.6.5.1 自带四处（Spreadsheet 的「Create Spreadsheet…/Connect to Spreadsheet」、Camera 的
「Copy From Viewer」、OSLCode 的「Export OSL Shader…」、Box 的「Reset Default Values」），
站点自己注册的菜单项也挂在这里。不发 = 从你的面板打开的节点
这些菜单项**全都不见**，而且不会有任何报错，很难自己发现。发的时候第一个参数传自己就行
（官方槽只用 `ancestor( CompoundEditor )` / `ancestor( Window )` / `context()`，都是 `Editor` 公共接口），
位置照原生放在 Lock 之后。顺带别忘了 `GafferUI.Examples.appendExamplesSubmenuDefinition`。

**浮动窗口撑高那段要 idle 之后再补一次**。`NodeSetEditor.acquire` 里「不到 400px 就撑到 400」
的判据是 `isinstance( editor, GafferUI.NodeEditor )`，自建面板不成立要自己补；但**只补一次不够** ——
原生 NodeEditor 是当场把正文排完的，自建面板的正文多半排在 `_updateFromSet` + idle 里，
随后那轮布局会按 sizeHint 把窗口缩回去（实测 400 → 310，而且时好时坏像 flaky 测试）。
resize 一次 + `addIdleCallback` 里再 resize 一次才稳。

**两条"照抄原生反而不对"的地方**：

1. **状态条别跟着原生小圆点标只读插口**。材质节点的 `name` / `type` 是 `loadShader()` 写的
   （官方元数据里就写着 `"readOnly" : True`、描述里写 "should be considered read-only"），
   插口默认值是空串 —— `_hasUserValue` 照直比就是 True，**新建一个材质节点就顶着一条橙色
   "改过"**。原生那个小圆点不显眼没人计较，换成一条状态条就是误导。判据用
   `Gaffer.MetadataAlgo.getReadOnly( plug )`（插口自己那面旗），**别用 `MetadataAlgo.readOnly()`**
   —— 它会一路问祖先，在齿轮菜单 Lock 一下节点，整块面板的状态条就全没了。
   而且只压"改过"这一态：只读插口照样可能被驱动 / 有动画，那两态是真信息。
   顶部汇总还要跳过 `plugValueWidget:type` 注册成空串的插口（原生压根不建控件，
   界面上看不见却在顶上数了一笔）。
2. **搜索只比 label 不够用**（原生 1.7 `StandardFilterWidget.__plugFilter` 就只比 label）。
   参数塞在一个复合插口里的节点 —— StandardOptions 的 `options`、CustomAttributes 的
   `attributes` —— 界面上**只有一行**，`Motion Blur` 是**子插口的分区名**、`shutter` 是
   **子插口的标签**，只比那一行的 label 就是"输了没反应"。要比的是
   **标签 / 名字 / `layout:section` + 递归底下子插口的同样三样**（带预算上限），
   并且**把 `空格 _ : . -` 压扁再比一次**（会有人输 `motionblur` 找 `Motion Blur`）。
   命中之后还要把同一套过滤**压进那一行控件里面的原生 `PlugLayout`**（`setFilter`，1.6 要 backport），
   否则只是把整行留下、具体哪几项还得自己翻 tab。

**原生已经有的别重复发明**：数值框拖动改值（`NumericWidget` 的 DragBegin/DragMove）、
右键菜单的 Set Key / Default / Preset / Copy·Paste Value / Bookmark（`popupMenuSignal` 是扩展缝，
20+ 官方模块在用）、以及「值改过」小点（`LabelPlugValueWidget._hasUserValue`：out 跳过 →
自身有输入 → 递归子插口有输入 → 比 userDefault → 比 default）。做状态可见就是把这一态
**拆成 动画 / 驱动 / 改过 三态 + 做汇总 + 做过滤**，语义照抄它。

**还剩的边界（1.6）**：`CompoundDataPlugValueWidget`（StandardOptions 的 `options`、CustomAttributes 的
`attributes`…）**不能递归** —— 它内部除了 PlugLayout 还自带一个「+」新增条目按钮，
那按钮写在控件里（不是 `layout:customWidget` 元数据），递归就会弄丢。这类插口整块用原生控件，
代价是拿不到逐项的状态条和搜索。1.7 把这几个插口换成了 `LayoutPlugValueWidget`、「+」改成
`layout:customWidget:addButton` 元数据，可以直接递归。

## 七、版本敏感（1.6.5.1 vs 1.7）

* **1.6 的 `PlugLayout` 没有 `setFilter` / `removeFilter` / `StandardFilterWidget`**（1.7 才加）。
  想在原生布局上做搜索过滤 → 按上游实现 backport：加三个方法（每实例一张 name→函数 表）
  + 包一层 `_PlugLayout__updateActivations`，在原实现跑完后把不匹配的顶层项 `setVisible(False)`。
  补丁要幂等 + `hasattr` 探测，升 1.7 自动让位。撤掉过滤会自动复原（原实现每次都按 activator 重设可见性）。
* `_Layout.update()` 签名 1.6 是 `(section)`、1.7 是 `(section, revealChildren)`。
* **`widget.getVisible()` 是控件自己的可见标记，不是实际可见性** —— 被过滤藏掉的是它外面那一行，
  判断「有没有被过滤掉」必须用 `widget.visible()`，否则测试全绿而功能没生效。
* **`Gaffer.Animation.isAnimated()` 的 C++ 签名只吃 `ValuePlug`** —— 普通 `Plug`（`user`、
  ScenePlug、FilterPlug…）传进去直接 `Boost.Python.ArgumentError`，遍历插口前必须 isinstance。
* **`IECore.StringAlgo.matchMultiple()` 把空格当「多个模式」的分隔符** —— `z min` 匹配不上
  `Z Min`（原生 `StandardFilterWidget` 同病）。把空格换成 `*` 变成「都要包含」更好用。
* **`_StyleSheet.styleColor()` 对不存在的 key 静默返回黑色**（不报错）→ 取色前先查
  `_StyleSheet._styleColors` 名单，否则写错一个 key 得到一片黑。
* **`GafferScene.InteractiveRender()` 在 `gaffer env python` 里构造直接 SIGABRT**
  （`free(): invalid size`）→ 和它有关的验证只能走 `gaffer screengrab`；无头测试拿
  **BoundQuery / Gaffer.Random**（同样带「有控件的输出插口」）代替。
* **tab 标签带计数时（如 `· 2`）别拿标签回头查分区** —— 一定是 None，按对象拿。
* ⚠️**测试变体别拷到别的目录跑**：测试头一句通常是
  `sys.path.insert(0, dirname(dirname(abspath(__file__))) + "/python")`，拷走之后那条路径
  就失效 → 一开头就 `ModuleNotFoundError` 崩掉。如果只 grep 某种错误的条数，
  **0 条会被读成「干净」**，据此做的 bisect 全是错结论。变体放在 `tests/` 下，并且
  先确认它真的跑到了最后那句 `N/N passed`。
* **想判断「某条噪声是不是这轮引入的」**：把整个包拷一份、在副本里把改动还原掉，
  跑同一份测试对比 —— 比盯着代码猜快得多。
* **`nodeGadget:color` 只在 GUI 启动脚本里注册**：`gaffer env python` 无头环境下所有节点
  都取不到颜色（None）。无头测试要自己把「万能灰」塞进缓存才能验规则。
