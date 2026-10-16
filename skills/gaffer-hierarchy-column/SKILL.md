---
name: gaffer-hierarchy-column
description: 给 Gaffer HierarchyView / PathListingWidget 添加自定义列（按 object 类型显示图标、行标记颜色等）的标准做法：Python PathColumn 子类 + patch HierarchyView + 类型识别 + 图标管线。Gaffer 1.6.5.1 实测。
---

# Gaffer HierarchyView 自定义列（PathColumn 子类化）

给 HierarchyView 的行加自定义显示（类型图标/颜色/文字）的标准做法。**不需要改 Gaffer 源码**——实现模块放在 PYTHONPATH 上，startup/gui 脚本做薄包装。

## 参考实现

参考实现未包含在本仓库。它是一个"按 object 类型自动显示图标"的模块：替换 Name 列为自定义 PathColumn 子类（名字 + 图标），图标统一生成为 16x16 png 放进自己的 graphics 目录。

## 核心机制（1.6.5.1 实测）

### 1. PathColumn 可 Python 子类化，StandardPathColumn 不能

- `_GafferUI.PathColumn` 绑定带 `PathColumnWrapper` → Python 子类 override `cellData(path, canceller=None)` / `headerData(rootPath, canceller=None)` 会被 C++ 派发。
- `StandardPathColumn`（`GafferUI.PathListingWidget.StandardColumn`）是 `RefCountedClass` **无 wrapper** → 不能 Python 子类化 override。要替换 Name 列就自己写 PathColumn 子类复刻名字（`path.property("name")` 取叶子名）。
- 构造：`_GafferUI.PathColumn( _GafferUI.PathColumn.SizeMode.Stretch )`（SizeMode：Stretch 占满剩余宽度 / Interactive 固定）。

### 2. CellData 字段与渲染

```python
CellData( value, icon, background, toolTip, sortValue, foreground )
```
- `icon` 支持：`StringData(图标名)` → 从 GAFFERUI_IMAGE_PATHS 加载 QPixmap；`Color3fData/Color4fData` → 色块。**取值器解包 Data**：getter 返回 `str`/`imath.Color3f` 而非 Data 对象。
- `background`/`foreground` 支持 Color3f/4fData（行背景/文字色）。

### 3. 列注入 + 自动刷新

- patch `GafferSceneUI.HierarchyView.__init__`（包装原 init）→ `hv.sceneListing().setColumns([自定义列] + 其余列)`，幂等（记录 listing id）。
- **`PathModel.setColumns` 会连接每列的 `changedSignal()`** → 改数据后 `column.changedSignal()(column)` 触发模型自动重查，无需手动刷新。
- 右键菜单：`listing.columnContextMenuSignal().connect(handler)`（signal 签名 `(column, listing, menuDefinition)`，用 `IECore.MenuDefinition` append，路径 `/子菜单/项` 自动建子菜单）。

### 4. 类型识别（ScenePath）

- cellData 的 path 是 `GafferScene.ScenePath`，**Python 绑定有 `getScene()`/`getContext()`**。
- `scene.object(pathNames).typeName()` 判断类型（pathNames = `str(path).strip("/").split("/")`）。
- **灯光判断照抄 LightEditor**（C++ LocationNameColumn）：`scene.fullAttributes(pathNames)` → 遍历灯光相关 attribute（`light`/`*:light`/`lightFilter`/`*:lightFilter`）→ `ShaderNetwork` → `outputShader().name` → metadata `"<attr>:<shader名>"` 的 "type" 优先，shader 名关键字兜底（spot/point/dome/disk/...→ 对应 `*Light.png`）。
- NullObject（空位置）三级：灯光 → `ai:volume` 类属性（key==`volume` 或 endswith `:volume`）→ 空位置图标。

### 5. 图标管线（统一 16x16）

- 所有图标源文件统一 16x16（官方图标尺寸不统一：25/16/14）。
- svg → png 用 **QtSvg**（`QSvgRenderer.render(painter, QRectF(0,0,16,16))` 必须传目标矩形，否则按 svg 默认尺寸画会裁切）。
- png 缩放：`QImage.scaled(16,16, IgnoreAspectRatio, SmoothTransformation)`。
- **不能占用官方图标名**（GAFFERUI_IMAGE_PATHS 是全局查找，自定义目录 prepend 后会劫持 Gaffer 其它 UI 的同名图标）——生成的图标用新名字（如 `typeCamera.png`）。
- install 时 `os.environ["GAFFERUI_IMAGE_PATHS"]` prepend 自定义目录（`os.environ` 赋值 → setenv → C++ `g_pixmapCache` 每次 getenv 生效；**但 `GafferUI.Image` 的 SearchPath 是模块导入时缓存的**——菜单预览图标要传**绝对路径**）。

## 文件布局

1. `python/<name>.py`：实现模块（列类 + install()）
2. `startup/gui/<name>.py` 薄包装：`import <name>; <name>.install()`
3. install() 幂等（模块级 `_installed` 标志）；`python/` 进 PYTHONPATH，`startup/` 进 `GAFFER_STARTUP_PATHS`

## 验证

- **无头单测**：`gaffer env python test.py`（模块直接 import，构造真实 ScenePath + 场景断言 cellData；duck-typed 假 listing 测 patch 幂等；图标尺寸断言用 Qt `QImage` 读——Gaffer env **无 PIL**）。
- **screengrab GUI**：`gaffer screengrab -commandFile t.py -image out.png -delay 4 -editor GafferSceneUI.HierarchyView -scene.expandedPaths /group`；commandFile 里 `application.setGrabWidget(hierarchyView)` 抓编辑器（多显示器下抓 window 会漏副屏内容）。看不懂的截图交给人确认观感，不要硬看像素。

## 坑位清单（全实测）

1. **checkable 菜单项命令多收 toggled 参数**：`Menu.__actionTriggered` 对 checkable action 把勾选状态 append 进 args → 命令签名要 `*unused`。
2. **子菜单懒构建**：MenuDefinition 路径只建空壳 `_Menu`，内容 `aboutToShow` 才构建——测试要 `menu._buildFully()` 后再找 QAction。
3. **`Menu.popup(position)` 的 position 是全局屏幕坐标**；非模态菜单可能在长 delay 后自动关闭，截图要在 commandFile 内菜单开着时抓。
4. **Gaffer 基本体节点（Sphere/Cube/Plane/Text/Capsule）输出都是 MeshPrimitive**（网格化）；`SpherePrimitive` 存在但 **Box/Cone/PlanePrimitive 在 IECoreScene 1.6.5.1 不存在**（映射前先枚举确认）；Grid 输出 NullObject。
5. **`GafferScene::Capsule` 不是节点**，是封装场景片段的 Object 类型（构造带 scene/path/context/hash/bound）。
6. `IECoreScene.Shader` 名字是 `.name` 属性（无 getName()）；`ShaderNetwork` 要 `setOutput("out")` 才有 outputShader()；attributes 里放 ShaderNetwork 直接赋值（无 ShaderNetworkData 类型）。
7. `CustomAttributes`/`StandardAttributes` 是原地修改型 SceneProcessor、**无 name 插口**——造"带属性的 NullObject 位置"用 Group → CustomAttributes 链。
8. `Metadata.value(strTarget, key)` 支持字符串 target，但内置灯光 shader 查不到 "type"（依赖外部 shader 注册）→ 必须留关键字兜底。
9. **批量 patch 脚本中途 assert 失败整段不写盘**（前面已替换的修改全丢）——每段改动独立确认写盘，或先核对再执行。
10. Group 的根子是 `/group`（以 Group 节点名命名），子路径是 `/group/xxx`。
