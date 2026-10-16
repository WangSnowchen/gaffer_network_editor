# 测试

所有命令都在仓库根目录下执行，`gaffer` 指 Gaffer 1.7 安装目录下的 `bin/gaffer`。

## 测试一览

| 文件 | 类型 | 内容 |
| --- | --- | --- |
| `tests/test_network_editor.py` | 无头 | 数据层 + UI + 编辑操作，主测试，约 1700 条断言 |
| `tests/test_optimizations.py` | 无头 | 热路径优化的专项断言：几何缓存与 `prepareGeometryChange` 顺序、圆点绘制表、一次鼠标移动只查一次 scene、手势互斥、只更新脏节点 |
| `tests/test_review_v070.py` | 无头 | 菜单条目求值照原生 `Menu`、面板键盘与滚轮、Revert 之后 item 换绑、计算线程报错、一步撤销 |
| `tests/e2e_network_editor.py` | 真机（screengrab） | 在真实 GUI 里验证注册、接管、需要 GL / Arnold 的部分，和原生逐个圆点对拍真实材质图，并出截图 |
| `tests/e2e_show_contents.py` | 真机（screengrab） | 原生右键菜单里 *Show Contents...* 的重定向 + 接管 |
| `tests/e2e_panel_input.py` | 真机 + 真输入 | 用 xdotool 真键盘真鼠标：嵌套 popup 的事件派发、高亮残留、视口重绘残影、按住 X、Alt+右键缩放、真滚轮、拖 Backdrop |
| `tests/bench_layout.py` | 量数据 | 自动排列对照台：12 张图 × 多种分层布局组合，量交叉 / 连线总长 / 长边直不直 / 耗时，原生一起跑当参照 |

夹具：

| 文件 | 用途 |
| --- | --- |
| `tests/shader_test.gfr` | 一张真实的材质图（34 个 ArnoldShader + 5 个 OSLShader 装在一个 Box 里，名字与贴图路径已替换），和原生逐个圆点 / 逐条连线对拍 |
| `tests/shader_nameswitch_test.gfr`、`shader_nameswitch_test2.gfr` | NameSwitch 第二路输入接线 / `+` 语义的回归 |
| `tests/test_layout_group.gfr` | 扇入节点自动排列的标准答案（手摆的位置） |
| `tests/loose_nodes.gfr` | 一条连线都没有的散节点，`Ctrl+L` 要排成一排 |
| `tests/houdini_rounded_wire.json` | 从 Houdini 21 网络编辑器量下来的 rounded 连线采样点，曲线连线逐点对拍用 |

## 无头

```bash
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_network_editor.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_optimizations.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_review_v070.py
```

- **一定要带 `QT_QPA_PLATFORM=offscreen`**。不带时 Qt 走真实窗口系统，窗口交给窗口管理器
  摆布，视口尺寸和可见性都不确定，`frame()`、显示隐藏这类靠几何断言的用例会稳定失败，
  拖动和重绘计数会随机失败。
- 没有 GPU 时加 `LIBGL_ALWAYS_SOFTWARE=1`。
- 图标对拍那一节要找 Gaffer 自带的灯光图标，需要 `GAFFERUI_IMAGE_PATHS` 指向安装目录的
  `graphics/`；找不到时那几条打 `SKIP`。
- `P` 键那一节：设 `PARAMETER_EDITOR_PYTHON=<parameterEditor 扩展的 python 目录>` 就连参数面板
  一起测，不设只验「没装时 P 键什么都不弹」。
- 无头环境里不能构造 `GafferArnold.ArnoldLight`（`free(): invalid size` 直接 SIGABRT），这类
  用例用桩类验规则本身，真节点放到真机 e2e 里验。

## 真机

```bash
# 端到端 + 出图（截图目录用 NETWORK_EDITOR_SHOTS 指定，默认临时目录；报告 /tmp/network_editor_e2e.txt）
GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:$PWD" \
    gaffer screengrab -commandFile tests/e2e_network_editor.py -image /tmp/editor.png
grep -c PASS /tmp/network_editor_e2e.txt; grep FAIL /tmp/network_editor_e2e.txt

# Show Contents 重定向（报告 /tmp/show_contents_report.txt）
GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:$PWD" \
    gaffer screengrab -commandFile tests/e2e_show_contents.py -image /tmp/show_contents.png

# 真键盘真鼠标（会真的移动鼠标，跑的时候别碰；报告 /tmp/panel_input_report.txt）
DISPLAY=:0 gaffer env python tests/e2e_panel_input.py
```

- e2e 需要 Arnold（`GafferArnold` 能 import）。
- e2e 自带一段「pipeline 快捷键替身」：照工作室启动脚本的写法往
  `GraphEditor.instanceCreatedSignal` 挂 S / Q / M 三个快捷键，并在类上注册 Filter / 灯光的
  节点色与材质的模板注释，所以在只有 Gaffer 自带启动脚本的干净环境里也能跑全。
- screengrab 执行 commandFile 时 `__name__ == 'builtins'`，脚本里不能加
  `if __name__ == "__main__"` 守卫，否则静默不执行。
- **报告是跑完才一次性写文件的**：脚本中途抛异常就不会重写，读到的会是上一次的旧报告。
  跑之前先删掉旧报告，并且看 stderr 里有没有 Traceback。
- `e2e_panel_input.py` 里「平移不留残迹」比的是真屏幕抓图和强制重绘，窗口被别的窗口盖住或
  跑到副屏时会失败，原地重跑即可。

## 自动排列对照台

```bash
QT_QPA_PLATFORM=offscreen gaffer env python tests/bench_layout.py
# NE_BENCH_COMBOS=all 跑全矩阵；NE_BENCH_OUT=<路径> 另存一份表（默认 /tmp/network_editor_layout_bench.txt）
```

它同样是跑完才写报告，中途出错要先看 stderr。

## 代码风格

```bash
black --check --line-length 88 python/
```

`tests/` 保持 Gaffer 源码的风格（tab 缩进、括号内空格），不参与 black。
