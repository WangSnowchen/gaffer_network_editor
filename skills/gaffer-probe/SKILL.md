---
name: gaffer-probe
description: 无头探测/验证 Gaffer 内部模块与 GUI 的标准流程。适用于站点自己编译的、没有源码的模块（如某个 `.so` 扩展）的 dir() 内省、节点行为验证、NodeEditor/对话框 screengrab 抓图。
---

# Gaffer 无头探测 / 验证 / 抓图（标准流程）

站点自己编译的、没有源码的模块（如某个 `.so` 扩展）只能靠 `dir()` 内省 + 构造实例实测。本技能固化启动命令、脚本骨架、screengrab 抓图、对话框探测的全部坑。

## 0. 铁律

- **无 GUI 上下文（`gaffer env python`）没有 `script` 变量**——只有 screengrab commandFile 上下文才有。无 GUI 脚本里自建 `script = Gaffer.ScriptNode()`，否则 `NameError: script is not defined`。
- **对话框/GUI 对象探测必须在 screengrab 里做**（无 GUI 的 `gaffer env python` 里 setVisible/Qt 交互会崩）。
- 行为以 dir() + 实测为准，别从别人保存的节点图里反推。

## 1. 启动命令（两种上下文，搞混必踩坑）

**A. 无头 Python（`gaffer env python`）**——纯逻辑/数据探测，无 GUI：
```bash
timeout 120 gaffer env python probe.py
```
- 站点扩展模块通常靠 Gaffer 包装脚本注入的环境（PYTHONPATH / 库路径）才 import 得到，直接用外部 python3 import 不到。
- 脚本骨架：`script = Gaffer.ScriptNode()` 自建根；结果 `json.dump(rep, open("out.json","w"), default=str)`，shell 里再读。

**B. screengrab 抓图（带 GUI 上下文）**：
```bash
timeout 180 gaffer screengrab -commandFile probe.py -image out.png -delay N
```
- commandFile 上下文暴露 `application`（ApplicationRoot）和 `script`（根 ScriptNode，**不是 `root`**）。
- **commandFile 别加 `if __name__ == "__main__":` 守卫**（`__name__ == 'builtins'`）——守卫会静默不执行。主逻辑直接模块级跑。
- 截图自动建输出目录。

## 2. dir() 内省编译模块（无源码）

```python
import inspect
import someCompiledModule as mod
cls = mod.SomeDialog
dir(cls)                              # 类方法
inspect.signature(getattr(cls, m))    # 方法签名
# 实例私有属性（name mangling）：dir(instance) 会列出 _Class__attr
```

- 私有方法/属性名 = `_<类名>__<名>`（如 `_SomeDialog__add_btn_clicked`），可直接调用验证行为。
- 数据类：`dir(obj)` + `getattr(obj, a)` 拿字段。
- 枚举/常量：模块属性直接读，`dir(module)` 找。

## 3. 对话框 GUI 探测（screengrab 里）

- 对话框若是 `GafferUI.Dialogue` 子类：`dlg.setVisible(1)` 后必须 pump（`processEvents` + `EventLoop.waitForIdle(1)` 循环 ~1s），model 才加载。
- **树的选中走 GafferUI 层**：`GafferUI.PathListingWidget` 选中用 `widget.setSelection(["/<组>/<项>"])`；Qt `selectionModel().select()` **不映射**到 GafferUI 层（`getSelection()` 仍空）。无头模拟"鼠标选中"困难 → 改用对话框的公共 API 构造状态再截图。
- 读 model 数据：`widget._qtWidget().model()`（rowCount/data/index）。
- 控件从 `dir(dlg)` 的私有属性拿（`_<类名>__xxx_widget`、`_<类名>__xxx_btn` 这类），多栏布局的栏位 x 坐标用 geometry 打出来确认。

## 4. screengrab 抓 NodeEditor / 窗口

- **NodeEditor**：`GafferUI.NodeEditor.acquire(node, floating=True)` + `_qtWidget().setFocus()` + `application.setGrabWidget(nodeEditor)`。尺寸固定（~415x384，resize 会被自动适应内容覆盖）。
- 按钮/控件位置探测（判断是否可见）：遍历 `qt.findChildren(QAbstractButton/QLabel)` 打 geometry。
- 模型读不了图时，验证靠 widget 探测写 JSON + 尺寸/字节数判断；截图直接给文件路径让人看（不做 base64/图集）。

## 5. 常用可复用片段

```python
def pump(ms):
    import time
    end = time.time() + ms/1000.0
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        GafferUI.EventLoop.waitForIdle(1)

def tree_full(view):  # 读 PathListingWidget 的 Qt model 全部行
    m = view._qtWidget().model()
    out = []
    for r in range(m.rowCount()):
        p = m.index(r,0)
        kids = [str(m.data(m.index(k,0,p))) for k in range(m.rowCount(p))]
        out.append((str(m.data(p)), kids))
    return out
```

- 真机 GUI + xdotool 操作尽量少用：没有窗口管理器的环境下找窗口/模拟点击很别扭，且模型读不了屏幕图。截图优先 screengrab 离屏。
