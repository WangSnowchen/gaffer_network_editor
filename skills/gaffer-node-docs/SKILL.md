---
name: gaffer-node-docs
description: 把 Gaffer 源码里的 test 代码转成艺术家看得懂的 NodeReference 教学页：案例筛选、Viewer 前后对比图/GIF 出图管线、参数特写裁剪、三道验证。适用于批量生产中文节点文档。基于十余个场景节点的实战沉淀（Gaffer 1.6.5.1 实测）。
---

# Gaffer 节点文档：从 test 代码到教学页

批量生产 NodeReference 页面的标准流程。**不要每次从零摸索出图管线**，下面这套已跑通 30+ 案例。

## 参考实现

参考实现未包含在本仓库。它的脚本分工如下，照这个划分写即可：

| 脚本 | 职责 |
|---|---|
| `case_lib.py` | 采集库：抓图 + 案例脚手架（核心） |
| `demo_scene.py` | 共用教学场景 `/world/props/{ball,box}` + `/world/chars/hero` |
| `compose.py` | 并排合成 + GIF（PIL + ffmpeg） |
| `run.sh` | 在 screengrab 里跑 commandFile |
| `cases_*.py` | 按主题分批的案例脚本 |
| `build_*.py` | 成品图合成 + 装进文档 |
| `verify_*_code.py` | 执行文档里的每个代码块 |

另有 `pages/`（写好的示例段 md，再拼进文档页）和中间产物目录（out / final / frames）。

## 页面模板（每个案例）

1. **一句话说清解决什么问题**——艺术家语言，不是 API 语言（"资产读进来位置不对" 而不是 "施加变换矩阵"）
2. **主图**：Viewer 前后对比（并排 + 分割线 + 图内中文标签），或 GIF
3. **关键参数特写**：只截改动的那几行，不是整个面板
4. **节点图**：裁紧的小图
5. **折叠代码**：`{dropdown}`，外层 **4 反引号**、内层 3 反引号（MyST 嵌套 fence 必须外层更长）

**按节点行为分模板，别一刀切**：
- 有画面变化（Prune/Transform/ShaderAssignment）→ Viewer 前后对比
- 只有层级变化（Group/Instancer 的 encapsulate）→ HierarchyView 并排
- 查询类、无画面（AttributeQuery/OptionQuery/Set）→ 参数特写 + 读回数值
- 抽象基类（SceneNode/SceneProcessor/FilteredSceneProcessor）→ **根本不配案例**，保留翻译即可

出图规格：Viewer 单张 800×600，并排约 1600×634，GIF 640 宽；GIF 里相机不动，只让参数变。

## 案例怎么挑

### 从 test 文件挑

Gaffer 源码 `python/GafferSceneTest/<Node>Test.py`，`def test*` 方法名即行为清单。
**跳掉**：`*GIL*` `*Threading*` `*Hash*` `*Perf*` `*DirtyPropagation*` `*Serialisation*` `*Bug*`——Instancer 66 个 test 里只有 8 个对艺术家有价值。
**答案都在测试文件里**（枚举值、默认值、用法），别去翻 C++ 头文件。

### 节点优先级用真实生产图统计，别拍脑袋

```bash
grep -rhoE '\bGafferScene\.[A-Za-z_][A-Za-z0-9_]*\(' --include='*.grf' <生产节点库目录> \
  | sed 's/GafferScene\.//; s/(//' | sort | uniq -c | sort -rn
```
**盲区**：可复用 setup 集合看不见交互工作流节点（`InteractiveRender`/`Render`/`Catalogue`/`Display` 在这类库里往往 0 次但天天用），要按经验补回来。

## 出图管线

### 启动

```bash
gaffer screengrab -commandFile <绝对路径>/cases_xxx.py -image out.png
```
`run.sh` 只是把这条命令包一层。

### 不打扰正在工作的人

抓图**不读屏幕**是关键：GL 视图走 FBO + `glReadPixels`，Qt 控件走 `QWidget.grab()` 的绘制路径——别的窗口盖上来物理上进不了图。窗口另外 `move(-6000,-6000)` 避免弹窗抢焦点。

**别费劲搞独立 X server**：不带 GLX 的 X server（如 Xvnc）上 Gaffer 的 GL 视口起不来直接 SIGSEGV。有 GL 的真实显示加上面两条就够。

装了会写全局连接文件的 GUI 插件（例如 MCP 桥接）时，抓图进程要把它的端口和状态目录隔离到独立值，否则 MCP 工具可能连到正在用的那个 Gaffer 上去改图。

### Viewer 抓图（`case_lib.viewerFor` + `grabGL`）

**必须自建窗口**：layout 里的 Viewer 尺寸由布局决定，`ViewportGadget.setViewport()` 改不动底层 QOpenGLWidget 的 framebuffer，多读的部分是空的（图上方一条黑边）。自建 `GafferUI.Window` + `GafferUI.Viewer(script)`，按 `getViewport()` 与目标的差量迭代 resize 直到正好。

顺序**不能反**：先定视口尺寸 → 再 `view.frame(paths, VIEW_DIRECTION)` 构图 → 最后渲染读回。反了会按旧宽高比算相机，出来黑边 + 几何拉伸。

Viewer 只有焦点落在节点上才创建 view（`script.setFocus(node)`），否则 `viewer.view()` 返回 None。

固定机位：全站统一 `VIEW_DIRECTION = imath.V3f(-1, -0.55, -1).normalized()`，出图 800×600。

**前后对比两张之间绝不重新构图**，否则读者看到的是镜头在动而不是参数在变。GIF 同理，相机在循环外构好。

### GL 离屏读回的两个必踩点

```python
GL.glPixelStorei( GL.GL_PACK_ALIGNMENT, 1 )   # 不设则行尾对齐错位、内容静默损坏
buf = GL.glReadPixels( 0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE )
img = QtGui.QImage( buf, w, h, w*3, QtGui.QImage.Format_RGB888 )  # 必须 5 参显式 bytesPerLine
img.mirrored( False, True ).save( path )      # GL 行 bottom-up
```

### 参数特写（`case_lib.plugCloseUp`）——三个坑叠在一起

1. **必须从自己那个编辑器取控件**：`GafferUI.PlugValueWidget.acquire(plug)` 内部自己 `NodeEditor.acquire(plug.node())`（**不带 floating**），返回的是布局里另一个 NodeEditor 实例的控件；跨两棵不相干的控件树 `mapTo`，坐标是垃圾，裁出来是面板顶部几行。正确做法：`nodeEditor.nodeUI().plugValueWidget(plug)`。
2. **折叠分区要 `reveal()`**：`seed`/`encapsulate` 这类插口默认在折叠分区里，不展开量不到真实位置。
3. **窗口底边会裁掉行**：浮动 NodeEditor 默认才 ~439px，展开后靠后的插口（y=420）卡在底边——**位置量得到、内容抓不到**，裁出来是只剩半个复选框的空白带。先 `resize(740, 1000)` 再量再抓。

配套：横向取面板全宽（否则复选框类插口只有 195px 宽，跟别的图大小不一）；多行编辑器（`setExpression`）要 `maxHeight` 限高，否则拖出上千像素空白；只框**同一分区内相邻**的插口，跨分区会把中间无关内容整段圈进来。

### 节点图裁紧（`case_lib.graphEditorFor`）

**不要用 `graphEditor.frame()`**——内部 zoom 上限 10，三五个节点 frame 完只占画面几个百分点，名字都看不清。自建 GraphEditor 窗口 + 手动算包围盒：
```python
position = graphGadget.getNodePosition( node )      # V2f，节点 UI 中心
nodeBound = graphGadget.nodeGadget( node ).bound()  # 本地 bound，以 position 为中心对称
```
逐节点取并集 → **只扩边不收缩**（padding 5 合适）→ `viewportGadget.frame(bbox)`。

自动布局在 idle 才完成，`addChild` 后必须 `pump()` 再 `getNodePosition`，否则拿默认值 frame 到空白（图仅 ~2KB）。frame 后节点重绘慢，再 `pump(2.0)` 才抓。

自建窗口的额外好处：没有 screengrab 主窗口那些 overlay，右下角不会漏出 `Nodes: 3 / SelectNode Name: None` 调试文字。

### HierarchyView（`case_lib.hierarchyFor`）

展开必须**在这里做完并直接抓图**——screengrab 主流程之后会 `setVisibleSet(script, VisibleSet())` 把展开状态清掉。1.6.5.1 用 `GafferSceneUI.ScriptNodeAlgo.expandInVisibleSet(script, PathMatcher)`（**不是 ContextAlgo**，签名收 script 不收 context）。

按可见行数定高：`52 + rows*21 + 8`，不然下面拖一大片空行。

### 并排合成 / GIF（`compose.py`）

并排：两张图各加顶部标签带（**标签画进图里**，不靠正文说明），中间 2px 分割线。尺寸不一致时**补齐而不是报错**——层级对比里"一边行数多"恰恰是要表达的内容，填充色取图自身底边主色。

GIF：ffmpeg 两遍法 `palettegen=stats_mode=diff` + `paletteuse=dither=bayer`，比 ImageMagick 直转准得多（Gaffer 视口是大片灰阶渐变，调色板不好会出明显色带）。640×480、fps 4-8。

**中文字体**：Noto Sans CJK（`NotoSansCJK-Regular.ttc`），`index=2` 是 SC 字面。

## 三道验证（缺一不可）

1. **案例带断言**：层级 `childNames`、成员数、`fullTransform().translation()`、对象类型——**不靠看图判断**。图上"立方体里嵌着球"这种错误肉眼极易看漏。
2. **文档代码块逐个真的执行**：从 md 里正则抽出 dropdown 的 python 块，每个开一个新 `Gaffer.ScriptNode()` exec 一遍。页面写着"可运行"就不能只是看着像能跑。
   ```python
   re.findall(r"````\{dropdown\}[^\n]*\n\n```python\n(.*?)\n```\n````", text, re.DOTALL)
   ```
3. **构建 + 引用检查**：0 警告、图片引用零缺失、零孤儿（旧图要删干净）。

### 成品图校验：按内容判，别按文件大小

只查尺寸和"是否纯色"会放过一张 724×19 的空白带（只有半个复选框），而且配文写的是完全不相干的参数。有效的断言是在**采集时**做：控件必须 `isVisibleTo(editorWidget)`、高度 > 5px、矩形底边不能贴着面板底边。产出后再拼一张对照表**逐张肉眼核对**内容是否匹配标题。

## 环境坑

- **Python 解释器要明确指定**：合成脚本需要 Pillow ≥ 8（有 `textbbox`）。系统自带的老 Pillow（如 7.0）没有 `textbbox`；Sphinx 的虚拟环境可能根本没装 PIL，且在 PATH 上会把 `python3` 挡掉。靠 PATH 解析时灵时不灵。
- **screengrab 执行 commandFile 时 `__name__ == 'builtins'`**——带 `if __name__ == "__main__":` 守卫的脚本静默不执行。模块级直接跑。
- **工作目录在多次 shell 调用之间不保持**，写文件一律用绝对路径（否则产物会落进文档源码树）。
- **`pkill -f` 会自匹配调用 shell**——命令行里含匹配串会把自己杀掉（exit 144）。用 `pgrep -f 'name[-]core'` 括号技巧或按 pid kill。
- 自建窗口要**持模块级引用**（`_windows = []`），否则被 GC 掉，抓图时报 "Internal C++ object already deleted"。
- `EventLoop.mainEventLoop().start()` 会挂死；已运行的主循环内 `waitForIdle()` 会 assert 失败。用 `QApplication.processEvents()` + `waitForIdle(1)` 循环泵事件。

## API 事实（1.6.5.1 实测，与直觉相反的）

| 事实 | 说明 |
|---|---|
| `Gaffer.NodeAlgo.presets(plug)` | 读枚举预设的正确入口。`Metadata.value(plug,"presetNames")` 返回 **None** |
| `GafferSceneUI.ScriptNodeAlgo` | 1.6.5.1 用它，**不是** `ContextAlgo` |
| `context.get("x", 0)` | Python expression 里 context 是字典风格；`context(...)` 报 `_ContextProxy` 不可调用 |
| `Isolate` 无 `invert` 插口 | 要反选就换用 Prune，两者互为反操作 |
| Interpolation: Vertex=**3**, FaceVarying=**5** | OSLObject 的 `interpolation` 默认已是 Vertex，**别乱设** |
| `inactiveIds`/`prototypeIndex`/`scale`/`id` 是 **StringPlug** | 填的是**图元变量名**不是值 |
| Instancer 原型必须在 prototypes 场景**根层级** | 用 Group 打包会多一层 `/group`，被当成**一个**原型，每个点上所有模型套在一起。用 `MergeScenes` 或 `prototypeRootsList` |
| 场景插口查不存在的路径**不报错** | 返回默认值/过时数据。查胶囊下面会返回旧的子位置列表，看着像"encapsulate 没生效"，其实是问错层级（胶囊在 `/plane/instances`） |
| Isolate 保留**匹配位置的整棵子树** | 集合里混进组位置，下游 Isolate 会连带保留整棵子树 |
| `OpenGLShader` + `Constant` 的 `Cs` | **只有 OpenGL 材质能在 Viewer 里看出颜色**，Arnold 材质视口无变化、做不出前后对比。材质类节点案例用它，正文说明生产里用 ArnoldShader |
| `SceneWriter.execute()` → `SceneReader` | `.scc`/`.usda`/`.abc` 往返都通，用来做自包含的 SceneReader 案例 |
| `Group["in"]` 是动态数组插口 | `in[0].setInput()` 自动长下一个槽。**别** `in.addChild()`，会造幽灵插口 |
| 位置名来自几何体 `name` 插口 | 不是节点名。两个节点叫 SphereA/SphereB，输出位置都叫 `sphere` 会撞名 |

## 出图里的体面问题

- 截图里不要暴露临时工作目录路径。缓存文件写到 `/tmp/gaffer_docs/` 这类中性路径。
- GIF 循环跑完会把参数停在最后一帧的值，抓参数特写前**复位**，否则特写显示的数值和代码块里写的对不上。
- 接了 filter 之后 `Parent` 的 `parent` 插口会置灰——截它只得到一行灰空框，改截 filter 的 `paths` 才说明得了"挂到哪里"。
