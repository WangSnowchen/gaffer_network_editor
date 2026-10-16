---
name: gaffer-color-chooser
description: 把 Gaffer 原生 ColorChooser/ColorChooserDialogue 替换为自定义拾色器（UE 风格）+ 跨软件屏幕取色（eyeDropper）的标准做法：类名替换机制、接口契约、Qt 自绘坑、X11/Windows 取色后端。Gaffer 1.6.5.1 + PySide6 6.5.6 实测。
---

# Gaffer 自定义拾色器 + 跨软件吸管

把 UE 的 SColorPicker 移植成 Gaffer 拾色器（替换原生 ColorChooser），含跨软件吸管取色、Recents 随文件记录、弹窗 OK 提交语义。**不需要改 Gaffer 源码、不需要编译**——纯 Python + Gaffer 自带 Qt（PySide6），实现模块放在 PYTHONPATH 上，startup/gui 脚本做薄包装。

## 参考实现

参考实现未包含在本仓库。它由四部分组成，照这个划分写即可：

- **替换类模块**：`UEColorChooser` + `UEColorChooserDialogue`，实现原生 ColorChooser 全部公开接口。
- **UI 组件库**：色轮 / 光谱 / SV 竖条 / 渐变滑条 / 预览色块 / 吸管按钮 / 主题条，纯 Qt 自绘，不依赖 GafferUI（可复用）。
- **eyeDropper 采样后端**：X11 窗口级 XGetImage / Windows GetDC+GetPixel / macOS 预留，任何 Gaffer 工具可直接 import。
- **startup/gui 安装脚本**：换类名 + 安装。

源码参考：UE `Engine/Source/Runtime/AppFramework/Private/Widgets/Colors/`（SColorPicker.cpp ~1600 行 / SEyeDropperButton.cpp 246 行 / SColorThemes.cpp）；Gaffer `python/GafferUI/ColorChooser.py`。

## 核心机制（1.6.5.1 实测）

### 1. 替换机制 —— 换一个类，两条入口同时生效

- 内联（Node Editor 内嵌）`ColorChooserPlugValueWidget` 与弹窗 `ColorChooserDialogue` **都是运行时** `GafferUI.ColorChooser(...)` 构造 → startup 里换名一处全生效。
- **`from xxx import` 绑定的是 import 时的旧类，不受替换影响**——没生效先看是不是被 import 绑定了。
- install() 幂等：模块级 `_installed` 标志；留一个 `GAFFER_<NAME>_DISABLE` 环境变量做逃生舱。

### 2. 接口契约（替换类必须实现）

- 方法：`setColor/getColor/setInitialColor/setSwatchesVisible/setVisibleComponents/setColorFieldStaticComponent/setColorFieldVisible/setDynamicSliderBackgrounds/setErrored`
- **类方法** `changesShouldBeMerged`：直接委托 `GafferUI.Slider/NumericWidget.changesShouldBeMerged`，保证 undo merge 行为与原生一致。
- 6 信号：`colorChanged/visibleComponentsChanged/staticComponentChanged/colorFieldVisibleChanged/dynamicSliderBackgroundsChanged/optionsMenu`。

### 3. 替换类内的关键坑

| 坑 | 解法 |
|---|---|
| 类体内 `__x` 常量报 `_ClassName__x` 不存在 | Python 名称重整：类体内双下划线自动前缀类名 → 模块级常量用**单下划线** |
| `Signal has no attribute 'connect'` | PySide6 信号必须定义在**类体**（类属性），不能写进 `__init__` |
| dialogue 替换类方法找不到 | 子类代理构造时（`GafferUI.ColorChooserDialogue.__init__(self,...)`）self 的 MRO 不含替换类 → 回调一律用**闭包**（捕获引用），不用 `Gaffer.WeakMethod(self.__x)` |
| install() 后 `__init__` 无限递归 | 类定义时存原类 `__base = GafferUI.ColorChooserDialogue`，`__init__` 里调它 |
| 弹窗 OK 不生效 | `_ColorPlugValueDialogue` 靠 `colorChangedSignal` 写 plug；OK 时 `commitPreview()` 必须**发信号**（顺序：先 commit → 再 recents → 再子类回调） |
| 延迟回调控件已销毁崩 | 所有 `QTimer.singleShot(0)` 延迟/重建路径包 `try/except RuntimeError` |

### 4. UI 绘制语义

- **预览/提交分离**：内部 `__color`（正式）+ `__previewColor`（预览），交互只改预览；`commitOnDrag`：内联 True（松开提交）、弹窗 False（OK 才提交，对应 UE 的 `bOnlyRefreshOnOk`）。
- **色轮映射（QConicalGradient）**：`QConicalGradient(center, 0)` 渲染色相是 `hue=(360−θ)%360`（θ=屏幕角，0=右，顺时针，y 向下）。取色公式 `hue=(360-atan2(dy,dx))%360`，指示器用同一映射画。**渐变渲染方向必须与交互取色公式严格一致**，否则错位 ~90°。
- **Recents 随文件**：存 script 节点 metadata `Gaffer.Metadata.registerValue(script, key, IECore.Color3fVectorData([...]), persistent=True)`，随 .gfr 保存加载；`__scriptNode()` = ancestor(ScriptWindow)，拿不到时取顶层可见 ScriptWindow。
- **颜色空间纪律**：Gaffer 契约是**线性** imath 色（`Color3f/Color4f`），屏幕像素是 sRGB 8bit → 吸管提交时 sRGB→线性分段解码（UE `FromPow22Color`）。imath `rgb2hsv/hsv2rgb` 与 Qt `fromHsv` 一致（已验证），但组件内部统一走 Qt HSV 路径避免混用。
- 内联压缩：`setSwatchesVisible(False)` 时隐藏预览列和主题面板。
- 吸管图标用 Gaffer 自带 `gafferImageUIColorInspectorTool.png`（GafferImage ColorInspectorTool 在用），`IECore.SearchPath(GAFFERUI_IMAGE_PATHS).find()` 解析。

## 跨软件吸管（eyeDropper）

### 交互（照搬 UE，XTest 实测）

- 点吸管按钮 → 按住 → 移动实时预览 → 松开提交 / Esc 取消还原。
- **Qt 无需显式 grab**：按下后自动隐式抓取（X11=XGrabPointer、Windows=SetCapture、macOS=Cocoa mouseDragged 语义），按住期间移出窗口 move/release 仍持续送达本进程，**松开的一击被吞掉、不会点穿到下面的软件**。
- 配 ~30ms `QTimer` 轮询 `QCursor.pos()` + 采样实时预览；Esc 在 X11 按住期间仍送到聚焦窗口，用 QShortcut/事件过滤器捕获。

### X11 采样（关键结论）

```python
# ① 不能 XGetImage(root)：KWin 这类 GL 合成器下，根窗口读回全是 (30,30,30) 脏数据
# ② 正确做法：下钻到光标下真实客户端窗口再窗口级采样
XQueryPointer(root) → 光标下 child，沿 reparent 链递归下钻到真实客户端窗口
XGetImage(win, 局部坐标, 1x1, ZPixmap)   # ctypes 调 libX11，零第三方依赖
```

- **每次采样别 `XOpenDisplay()` 新开连接**（~30ms 一次很快耗尽 X 服务器 ~256 客户端上限，终端狂刷 `Maximum number of clients reached`）→ display 连接做**进程级单例缓存**复用。
- Windows：ctypes `GetDC(HWND_DESKTOP)` + `GetPixel`（UE 那 10 行直译）。
- macOS：pyobjc ScreenCaptureKit 需"屏幕录制"权限、~50ms 一次，列为"尽力而为"（Gaffer 自带 Python 3.11 未捆绑 pyobjc）。
- **`QScreen.grabWindow` 不行**：X11 下抓根窗口同样被合成器坑，macOS 不支持。

### 已知局限（平台共性，任何同类实现都有）

GPU/DX/GL 直绘窗口读到黑或旧帧（UE 同样存在）；Wayland 原生窗口（非 XWayland，如浏览器）读不到；多显示器 HiDPI 坐标需乘 `devicePixelRatio`。

## 文件布局

1. `python/<name>.py`：实现模块（UI 组件库 + 替换类 + install()）
2. `python/eyeDropper.py`：跨软件采样后端（可独立 import）
3. `startup/gui/<name>.py` 薄包装：`import <name>; <name>.install()`；`python/` 进 PYTHONPATH、`startup/` 进 `GAFFER_STARTUP_PATHS`

## 验证（GafferUI 无头）

- **裸 `bin/python3` 跑 GafferUI 不可靠**：缺图形资源（`colorFieldEmptyIcon.png`/logo）→ 设 `GAFFERUI_IMAGE_PATHS=$GAFFER_ROOT/graphics`；`qEvent.ToolTip` 等 PySide6 兼容问题在裸环境是假象，真实 gaffer 无此问题。
- 沙箱/无 GPU：`LIBGL_ALWAYS_SOFTWARE=1` 软件渲染可跑。
- **无法注入真实环境时**：写**临时 startup/gui 测试脚本**——import → 断言 → 结果写日志文件 → `sys.exit(0)`，`gaffer` 启动后读日志。测完删除。
- **UI 渲染验证**：`QMainWindow` 包目标 widget → `grab().save(png)`；看不了图就做 **ASCII 像素渲染**；颜色映射用像素级采样验证（固定若干 θ 采样渲染色相，拟合公式）。

## 坑位清单（全实测）

1. 名称重整、Signal 类体、MRO 不含替换类、`__base` 存原类——见上表。
2. 色轮渐变方向与取色公式必须一致（错位 ~90° 是第一版必踩）。
3. 弹窗 OK 必须发信号，连接顺序 commit → recents → 子类回调。
4. X11 合成器下抓根窗口全是脏数据——只能窗口级下钻采样。
5. XOpenDisplay 不关会耗尽客户端上限——display 单例缓存。
6. 裸 python 环境是假象——设 GAFFERUI_IMAGE_PATHS 或走真实 gaffer 启动脚本测试。
7. Qt 按住隐式抓取保证跨软件不点穿——别手动 grab，也别用 QScreen.grabWindow。
