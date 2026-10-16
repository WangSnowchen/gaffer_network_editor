##########################################################################
#
#  把 NetworkEditor 注册进 layout 的编辑器菜单。
#
#  实现全在 `networkEditor` 模块里（随本扩展的 python/ 自动进 PYTHONPATH），
#  这里只是个薄壳。注册后在任意面板的编辑器菜单里选 "NetworkEditor" 即可。
#
##########################################################################

import networkEditor

networkEditor.registerEditor( application )
