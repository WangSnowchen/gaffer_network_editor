"""注册进 layout 的编辑器菜单。

接管 `GafferUI.GraphEditor` 那一套在 `editor.py` 里 —— `NetworkEditor` 自己就要用
`_nativeGraphEditorClass()`，而这个包严格一层套一层、下层不许回头引用上层。
"""

import GafferUI


from .editor import *

# 注册

GafferUI.NetworkEditor = NetworkEditor
GafferUI.Editor.registerType("NetworkEditor", NetworkEditor)

__editorRegistered = False


## 把编辑器加进 layout 菜单。幂等，重复调用无害。


def registerEditor(application):

    global __editorRegistered

    if __editorRegistered:
        return

    GafferUI.Layouts.acquire(application).registerEditor("NetworkEditor")
    installGraphEditorTakeover()

    __editorRegistered = True


# 往上层暴露的名字。**下划线开头的也要列进去** —— `import *` 默认跳过它们，
# 而上层和测试用的就是 `_NodeItem` / `_matchScore` 这些私有名字。
__all__ = [name for name in dir() if not name.startswith("__")]
