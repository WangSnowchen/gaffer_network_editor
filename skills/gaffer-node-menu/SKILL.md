---
name: gaffer-node-menu
description: 把自定义 Gaffer 节点注册进节点创建菜单（按 Tab / 图空白右键弹出的 NodeMenu）。适用于站点内部共享的节点库：Node 子类和 .grf 保存的 Box 两种写法。
---

# Gaffer 自定义节点注册到 Tab 菜单（NodeMenu）

站点内部共享的节点库注册进 NodeMenu 的标准做法。**不要猜 Gaffer 原生机制、不要重新摸索**——照本技能做。

## 前置

参考实现未包含在本仓库。一个注册单元由两个文件组成：实现模块 + startup 钩子。典型例子有两类：一个 Node 子类节点、一个从 .grf 加载的 Box 节点。

## 结构

1. **实现模块** `python/<name>.py`（目录进 PYTHONPATH）
   - 定义节点（Node 子类）或 Box 构建/加载逻辑
   - 末尾定义 `def registerNodeMenu( application )`：
     ```python
     def registerNodeMenu( application ):
         import GafferUI
         nodeMenu = GafferUI.NodeMenu.acquire( application )
         nodeMenu.append( "/Scene/Utility/My Node", MyNodeClass, searchText = "MyNode" )
     ```
2. **startup 钩子** `startup/gui/<name>.py`（`startup/` 进 `GAFFER_STARTUP_PATHS`；gui 目录的 startup 脚本里有全局 `application` 变量）：
   ```python
   import myNode
   myNode.registerNodeMenu( application )
   ```

## Node 子类 vs Box

- **Node 子类**：`nodeMenu.append( path, NodeClass, searchText=... )`，creator 直接传类。
- **Box（非 Node 子类，如 .grf 保存的节点）**：creator 必须是一个**返回 Box 实例的函数**，例如从同目录 .grf 加载：
  ```python
  _DIR = os.path.dirname( os.path.abspath( __file__ ) )
  def _createBox():
      script = Gaffer.ScriptNode()
      script["fileName"].setValue( os.path.join( _DIR, "Box.grf" ) )
      script.load()
      box = script["BoxName"]
      script.removeChild( box )   # 关键：detach 使 parent() is None
      return box
  nodeMenu.append( "/Scene/Utility/My Box", _createBox, searchText = "MyBox" )
  ```
  关键点：creator 返回的节点 `parent()` 必须为 None，`nodeCreatorWrapper` 才会 `addChild` 进图。

## 验证（无头）

- creator 单测：在 Gaffer 安装目录下 `export LD_LIBRARY_PATH=$PWD/lib; export PYTHONPATH=$PWD/python; export OSLHOME=$PWD; export OSL_SHADER_PATHS=$PWD/shaders; ./bin/python test.py`，或直接 `gaffer env python test.py`。模块顶层**不要 import GafferUI**（无头可测 creator）。
- 注册验证：模块内 import GafferUI 构造 `Gaffer.Application("test")` → `registerNodeMenu(app)` → diff `nodeMenu.definition().items()`（会打印 `FontLoader : Couldn't find Vera*.ttf` 警告，忽略即可）。
- GUI 观感：`gaffer` 打开后按 Tab 或图空白右键 → 输入 searchText 或浏览分类路径。

## Box 序列化要点

- Box 上自定义的 Out 插口、辅助节点上的 ObjectPlug / StringVectorDataPlug 输出、CompoundDataPlug 里的 NameValuePlug（`NameValuePlug(key, value, "name", Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic)`）都要带 `Dynamic` 标志，否则 .grf 回读报 "X is not a child of Y"。
- 一个 Expression 同时写某些插口又读依赖这些插口算出来的值 → 求值成环，表现为 SIGSEGV（exit 139 无输出）。拆成两个 Expression 切断回路。
