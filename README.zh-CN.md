# gaffer_network_editor

给 [Gaffer](https://github.com/GafferHQ/gaffer) 另做的一个节点图编辑器，用 Qt（`QGraphicsView`）
矢量绘制，代替原生基于 OpenGL 的 `GraphEditor` 来看图和编辑。

**目标：看起来更现代，用起来和原生没区别。**

[English](README.md)

## 功能

- **观感**：扁平卡片 + 节点类型图标 + 按插口类型上色的接口圆点 + 曲线连线（照 Houdini 的
  rounded 样式）/ 直线 + 缩放分级显示（LOD）+ Backdrop。
- **尺寸 / 接口位置 / 配色全部问原生要**（`NodeGadget.bound()`、nodule 的变换与切线、
  `nodeGadget:color`、`nodule:color`、StandardStyle 默认色），两个编辑器同开时节点一样大、
  一样的颜色。
- **编辑与快捷键逐条照原生** `GraphEditor` + `EditMenu` + `GraphBookmarksUI`；节点 / 插口 /
  连线三套右键菜单直接借原生的，其他扩展挂上去的条目也都在。
- **pipeline 快捷键照常可用**：工作室启动脚本通过 `GraphEditor.instanceCreatedSignal` 注册的
  快捷键都接得住，它们弹的菜单由本编辑器自己的面板来画。
- **接管 `GafferUI.GraphEditor`**：菜单栏的剪切 / 复制 / 粘贴、书签跳转、`Ctrl+F` 找节点、
  Box 的 *Show Contents...* 都落到本编辑器上；原生编辑器照常能用。
- **额外的功能**：级联多列建节点面板（首字母缩写搜索，打 `ass` 出 aiStandardSurface；
  「★ 喜爱」「常用」）、拖动自动对齐、连线吸附、focus 后按原生 `ContextTracker` 把不参与计算
  的部分变暗、自己的分层自动排列（`Ctrl+L`，连线交叉比原生少）、`X` 删除模式、
  材质节点参数分栏（Houdini 式收放）、从 Viewer / HierarchyView 拖路径进来建 PathFilter。
- **增量更新**：改一根线只动那几条边，200 / 800 / 2000 个节点的图上都是 5ms 左右。

界面文字是英文，鼠标悬停的提示是中文。

## 环境要求

- Gaffer **1.7**（在 1.7.1.0 上测过），不支持 1.6。
- 可选：另装一个提供 Python 模块 `parameterEditor`（含 `popupParameters( node, anchor = QRect )`）
  的扩展，`P` 键才会在节点图右上角弹出纯参数面板；没装时 `P` 键什么都不做。

## 安装

仓库本身就是一个 Gaffer 扩展：`python/` 进 `PYTHONPATH`，`startup/gui/` 负责注册编辑器。

```bash
export GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:/path/to/gaffer_network_editor"
gaffer
```

不用扩展机制也可以：

```bash
export PYTHONPATH="/path/to/gaffer_network_editor/python:$PYTHONPATH"
export GAFFER_STARTUP_PATHS="/path/to/gaffer_network_editor/startup:$GAFFER_STARTUP_PATHS"
```

仓库里另带一个 rez 用的 `package.py`。

启动后在任意面板的编辑器菜单里选 **NetworkEditor**。

### 环境变量

| 变量 | 作用 |
| --- | --- |
| `GAFFER_NETWORK_EDITOR_TAKEOVER=native` | 不接管 `GafferUI.GraphEditor` |
| `GAFFER_NETWORK_EDITOR_ENGINE=0/1` | 强制不建 / 强制建隐藏的原生 GraphEditor（默认只在接管关掉时建） |
| `GAFFER_NETWORK_EDITOR_GADGET=0` | 不用裸 `GraphGadget` 问原生尺寸和摆位（诊断用） |
| `GAFFER_NETWORK_EDITOR_STATE_DIR` | 「喜爱 / 常用」记录存放的目录（默认 `~/.gaffer_network_editor`） |

## 快捷键（未注明的都和原生一样）

| 操作 | 效果 |
| --- | --- |
| 点 / Shift+点 / Ctrl+点 | 选中 / 加选 / 取消选中 |
| Alt+Shift+点 / Alt+Ctrl+点 | 连同上游 / 下游一起选 |
| 左键拖空白 | 框选（**擦到一部分就算**，原生要整个框住） |
| 拖单个节点压到连线上松手 | 塞进这根连线 |
| 中键拖 / Alt+左键拖 | 平移 |
| 滚轮 / Alt+右键拖 | 缩放 |
| `F` | 框住选中的 / 全部 |
| `` ` `` / `Ctrl+` `` ` `` | 框住 focus 节点 / 把选中的设为 focus |
| `↓` / `↑` / `[` `]` | 进入节点 / 回上一层 / 在去过的层之间来回 |
| `Tab`、右键空白 | 建节点面板（面板里右键或 `Ctrl+D` 钉进「★ 喜爱」） |
| `X` | 删除模式：点连线删线、点节点删节点（上下游自动接上），按住左键划一笔切多根 |
| `D` | 停用 / 启用 |
| `P` | 纯参数面板（可选，见上） |
| `B` | 找书签（含 Box 里的） |
| `1`–`9` / `Ctrl+1`–`9` | 跳到 / 设置编号书签 |
| `Delete`、`Ctrl+C/X/V`、`Ctrl+D` | 删除、复制 / 剪切 / 粘贴、连输入一起复制 |
| `Ctrl+L` | 自动排列（自己的分层布局） |
| `F2` / `Ctrl+F` | 改名 / 查找节点 |

## 文档

| 文件 | 内容 |
| --- | --- |
| [docs/design-and-comparison.md](docs/design-and-comparison.md) | 设计原则、依赖原生到什么程度、和原生 GraphEditor 的对比、已知差异、风险、还没做的 |
| [docs/architecture.md](docs/architecture.md) | 代码导读：模块分层、每个文件和关键类 |
| [docs/pitfalls.md](docs/pitfalls.md) | 开发中遇到的所有问题：现象、根因、解决、验证 |
| [docs/gaffer-knowledge.md](docs/gaffer-knowledge.md) | 过程中整理出来的 Gaffer 知识：GraphEditor 结构、元数据、ContextTracker、NodeMenu、ViewportGadget、拖放协议、版本差异、测试方法 |
| [docs/testing.md](docs/testing.md) | 测试怎么跑 |
| [skills/](skills/README.md) | 做 Gaffer UI 扩展的 Claude Code skills（本编辑器、参数面板、HierarchyView 自定义列、拾色器、节点菜单、节点文档、探测、无头交付） |

## 许可证

BSD 3-Clause，见 [LICENSE](LICENSE)。
