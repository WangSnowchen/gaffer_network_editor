# -*- coding: utf-8 -*-
##########################################################################
#
#  「Show Contents...」重定向的真机验证（screengrab commandFile）。
#
#  跑法（在仓库根目录下）：
#
#    GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:$PWD" \
#        gaffer screengrab -commandFile tests/e2e_show_contents.py \
#            -image /tmp/show_contents.png
#    cat /tmp/show_contents_report.txt
#
#  无头测的是重定向这段逻辑本身（test_network_editor.py 里那一节）；这里测的是
#  **借原生右键菜单**这条真实路径：原生确实会给一条走 `GraphEditor.acquire` 的
#  "Show Contents..."，我们确实把它换掉了，点下去进的是本编辑器的层级，
#  布局里也没有多出原生 GraphEditor。
#
#  `__name__` 在 screengrab 里是 'builtins'，所以模块级直接跑。
#
##########################################################################

import functools
import traceback

import Gaffer
import GafferUI
import GafferScene
import IECore

from Qt import QtWidgets

import networkEditor as NE

REPORT = "/tmp/show_contents_report.txt"

lines = []
results = []
failed = []


def check( name, condition, detail = "" ) :

	lines.append( "%s %s%s" % ( "PASS" if condition else "FAIL", name, ( "  " + detail ) if detail else "" ) )
	results.append( bool( condition ) )
	if not condition :
		failed.append( name )


def pump( n = 3 ) :

	for i in range( n ) :
		QtWidgets.QApplication.processEvents()


scriptWindow = GafferUI.ScriptWindow.acquire( script )

editor = NE.NetworkEditor( script )
viewer = GafferUI.Viewer( script )

layout = GafferUI.CompoundEditor( script, _state = {
	"children" : (
		GafferUI.SplitContainer.Orientation.Horizontal, 0.7,
		(
			{ "tabs" : ( editor, ), "currentTab" : 0, "tabsVisible" : True },
			{ "tabs" : ( viewer, ), "currentTab" : 0, "tabsVisible" : True },
		)
	),
} )
scriptWindow.setLayout( layout )
pump( 5 )

box = Gaffer.Box( "ShowContentsBox" )
script.addChild( box )
box.addChild( GafferScene.Sphere( "inner" ) )
pump( 3 )

# 接管之后 `GafferUI.GraphEditor` 的 isinstance 把我们也算进去了，所以"有没有原生
# GraphEditor"要拿**原生那个类**去数
nativeGraphEditorClass = NE._nativeGraphEditorClass()
check( "接管装上了（startup 里 registerEditor 干的）",
	GafferUI.GraphEditor is not nativeGraphEditorClass )
check( "布局里没有原生 GraphEditor",
	len( layout.editors( type = nativeGraphEditorClass ) ) == 0 )
check( "但按 GafferUI.GraphEditor 找得到我们",
	editor in layout.editors( type = GafferUI.GraphEditor ) )

# ---- 接管的正题：官方那些写死 GraphEditor 的地方现在落到我们身上 ----------------

scopeEditor = layout.editor( GafferUI.GraphEditor, focussedOnly = False )
check( "`EditMenu.scope()` 那句 `layout.editor( GraphEditor )` 找到的是我们",
	scopeEditor is editor, str( scopeEditor ) )
check( "而且 graphGadget().getRoot() 拿得到（菜单栏剪切/粘贴靠它定层级）",
	scopeEditor.graphGadget().getRoot().isSame( script ),
	str( scopeEditor.graphGadget().getRoot() ) )

# ---- 原生菜单本来给的是什么 --------------------------------------------------

native = IECore.MenuDefinition()
borrowed = editor._NetworkEditor__appendNativeNodeMenu( native, box )
check( "借到了原生右键菜单", borrowed, "%d 项" % native.size() )

nativePaths = [ path for path, item in native.items() ]
showContentsPath = None
for path in nativePaths :
	if path.rpartition( "/" )[2].startswith( "Show Contents" ) :
		showContentsPath = path
		break

check( "原生菜单里确实有 Show Contents", showContentsPath is not None, repr( nativePaths ) )

if showContentsPath is not None :
	nativeCommand = native.item( showContentsPath ).command
	# 1.7 这条是 `functools.partial( GraphEditor.__acquireNodes, nodeList )`
	# （`GraphEditor.py:375`，里面对每个节点 `cls.acquire( n )`）—— 一个绑在**原生**
	# GraphEditor 类上的 classmethod。判据就看它绑的是不是原生那个类：是的话不改就会
	# 往布局里插一个原生面板。
	nativeOwner = getattr( getattr( nativeCommand, "func", None ), "__self__", None )
	check( "原生那条最后落到原生 GraphEditor 上（不改就会插原生面板）",
	       isinstance( nativeCommand, functools.partial ) and
	           nativeOwner is nativeGraphEditorClass,
	       repr( nativeCommand ) )

# ---- 我们换掉之后 ------------------------------------------------------------

	redirected = editor._NetworkEditor__redirectShowContents( native, box )
	check( "换掉了", redirected )
	check( "菜单顺序没变", [ path for path, item in native.items() ] == nativePaths )

	item = native.item( showContentsPath )
	check( "命令换成了本编辑器的进层级",
	       isinstance( item.command, functools.partial ) and item.command.func == editor._enterNode )

	check( "点之前 root 是脚本本身", editor.getRootNode().isSame( script ) )
	graphEditorsBefore = len( layout.editors( type = GafferUI.GraphEditor ) )

	item.command()
	pump( 5 )

	check( "点下去进了 Box", editor.getRootNode().isSame( box ) )
	check( "布局里没冒出原生 GraphEditor",
	       len( layout.editors( type = GafferUI.GraphEditor ) ) == graphEditorsBefore,
	       "%d -> %d" % ( graphEditorsBefore, len( layout.editors( type = GafferUI.GraphEditor ) ) ) )

	editor.setRootNode( script )
	pump( 3 )

# ---- acquire 也被接管了：不再往布局里插原生面板，而是让我们进那一层 ------------

nativeBefore = len( layout.editors( type = nativeGraphEditorClass ) )
editor.setRootNode( script )
pump( 3 )
acquired = GafferUI.GraphEditor.acquire( box )
pump( 5 )
check( "GraphEditor.acquire 返回的是我们这个编辑器", acquired is editor, str( acquired ) )
check( "而且它进了那一层", editor.getRootNode().isSame( box ), str( editor.getRootNode() ) )
check( "布局里仍然没有原生 GraphEditor",
	len( layout.editors( type = nativeGraphEditorClass ) ) == nativeBefore,
	"%d -> %d" % ( nativeBefore, len( layout.editors( type = nativeGraphEditorClass ) ) ) )

# 关掉接管，原生行为原样回来（退路还在）
editor.setRootNode( script )
pump( 3 )
NE.uninstallGraphEditorTakeover()
before = len( layout.editors( type = GafferUI.GraphEditor ) )
GafferUI.GraphEditor.acquire( box )
pump( 5 )
after = len( layout.editors( type = GafferUI.GraphEditor ) )
check( "对照组（关掉接管）：原生 acquire 确实会往布局里插一个原生面板", after > before,
       "%d -> %d" % ( before, after ) )
NE.installGraphEditorTakeover( force = True )

lines.append( "" )
lines.append( "==== show contents e2e: %d/%d passed ====" % ( len( results ) - len( failed ), len( results ) ) )
if failed :
	lines.append( "FAILED: %s" % ", ".join( failed ) )

with open( REPORT, "w", encoding = "utf-8" ) as f :
	f.write( "\n".join( lines ) + "\n" )

print( "\n".join( lines ) )

application.setGrabWidget( editor )
