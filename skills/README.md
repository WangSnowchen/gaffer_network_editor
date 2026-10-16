# Gaffer skills

做这个编辑器和其它几个 Gaffer 扩展时沉淀下来的 [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills)。
每个目录一份 `SKILL.md`：开头的 frontmatter 说明什么时候用，正文是做法和实测过的坑位。
不用 Claude Code 也可以直接当文档读。

| Skill | 内容 |
| --- | --- |
| [gaffer-qt-network-editor](gaffer-qt-network-editor/SKILL.md) | 用 Qt `QGraphicsView` 另做一个节点图编辑器：为什么原生 GraphEditor 改不动、和原生共用哪些数据、几何/配色/行为怎么问原生要、整套坑位。参考实现就是本仓库 |
| [gaffer-parameter-editor](gaffer-parameter-editor/SKILL.md) | 另做一个参数面板（替代 / 补充原生 NodeEditor）：内核为什么必须复用原生、三级改造怎么选、原生 `layout:*` 元数据语义、和原生对齐行高与标签的坑 |
| [gaffer-hierarchy-column](gaffer-hierarchy-column/SKILL.md) | 给 HierarchyView / PathListingWidget 加自定义列（按对象类型显示图标等）：`PathColumn` 子类化、图标管线、类型识别 |
| [gaffer-color-chooser](gaffer-color-chooser/SKILL.md) | 替换原生拾色器 + 跨软件屏幕取色：类名替换机制、接口契约、Qt 自绘坑、X11 / Windows 取色后端 |
| [gaffer-node-menu](gaffer-node-menu/SKILL.md) | 把自定义节点注册进节点创建菜单（Tab / 右键空白） |
| [gaffer-node-docs](gaffer-node-docs/SKILL.md) | 把 Gaffer 源码里的测试改写成给艺术家看的节点文档：案例筛选、Viewer 前后对比图 / GIF 出图、验证 |
| [gaffer-probe](gaffer-probe/SKILL.md) | 无头探测 / 验证 Gaffer 模块与 GUI：没有源码的编译模块怎么内省、screengrab 抓图 |
| [gaffer-headless-delivery](gaffer-headless-delivery/SKILL.md) | 一句话需求全程无头跑完并交付 `.gfr` / 渲染图：插口名探针、「报错了照样出图」的检测、数值求解校准 |

## 安装

把需要的目录拷进 `~/.claude/skills/`（个人）或项目里的 `.claude/skills/`：

```bash
cp -r skills/gaffer-qt-network-editor ~/.claude/skills/
```

除 `gaffer-qt-network-editor` 外，其余几份的参考实现没有包含在本仓库里，保留的是方法和坑位。
