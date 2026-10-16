##########################################################################
# networkEditor 无头测试：2026-10 复审那一轮的专项断言
#
# 每条都对着一处具体改动（菜单条目求值照抄原生 Menu / 喜爱跨会话 / 面板键盘与滚轮 /
# 项目快捷键换层 / Revert 之后 item 换绑 / 计算线程的错误 / 一步撤销 / 原生菜单栏
# 粘贴位置 / 按住 X 时平移 / 包围盒余量 / 数据层对齐原生）。**不依赖其它测试文件**。
##########################################################################

import os
import sys
import json
import time
import tempfile
import functools
import threading

sys.path.insert( 0, os.path.join( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ), "python" ) )

import imath
import IECore
import Gaffer
import GafferScene
import GafferUI

from Qt import QtCore, QtGui, QtWidgets

import networkEditor as NE

_passed = []
_failed = []


def check( name, condition, detail = "" ) :

	if condition :
		_passed.append( name )
	else :
		_failed.append( "%s  %s" % ( name, detail ) )
		print( "FAIL  %s  %s" % ( name, detail ) )


def section( title ) :

	print( "\n---- %s ----" % title )


def idle() :

	GafferUI.EventLoop.waitForIdle()


def makeEditor( script, name, size = ( 1000, 700 ) ) :

	editor = NE.NetworkEditor( script )
	window = GafferUI.Window( name )
	window.setChild( editor )
	window._qtWidget().resize( *size )
	window.setVisible( True )
	idle()
	return editor, window


def keyEvent( key, modifiers = QtCore.Qt.NoModifier, kind = QtCore.QEvent.KeyPress ) :

	return QtGui.QKeyEvent( kind, key, modifiers )


##########################################################################
section( "菜单条目求值照抄原生 `Menu`（WeakMethod / active / checkBox / 灰掉的子菜单）" )
##########################################################################

class _Commands( object ) :

	def __init__( self ) :

		self.calls = []

	def withMenu( self, menu ) :

		self.calls.append( ( "withMenu", menu ) )

	def checkState( self, menu ) :

		# 只有拿到 menu 才说勾着 —— 面板画的 ✓ 和传给命令的状态都得是带 menu 求的这个
		return menu is not None

	def toggled( self, checkBox ) :

		self.calls.append( ( "toggled", checkBox ) )

commands = _Commands()
weak = Gaffer.WeakMethod( commands.withMenu )
check( "WeakMethod 看得穿（原生 `Menu.__argNames`）", NE._commandArgNames( weak ) == [ "menu" ],
	str( NE._commandArgNames( weak ) ) )
check( "partial 套 WeakMethod 也看得穿",
	NE._commandWantsMenu( functools.partial( Gaffer.WeakMethod( commands.withMenu ) ) ) )
check( "绑定方法去掉 self", NE._commandArgNames( commands.withMenu ) == [ "menu" ] )
check( "认不出来的可调用对象当没参数", NE._commandArgNames( len ) == [] )

check( "active 是函数时照原生求值（不是一律当可用）",
	NE._entryDisabled( IECore.MenuItemDefinition( command = lambda : None, active = lambda : False ) ) )

menuDefinition = IECore.MenuDefinition()
menuDefinition.append( "/Group/Checked", {
	"command" : Gaffer.WeakMethod( commands.toggled ),
	"checkBox" : Gaffer.WeakMethod( commands.checkState ),
} )
menuDefinition.append( "/Group/NeedsMenu", { "command" : Gaffer.WeakMethod( commands.withMenu ) } )
menuDefinition.append( "/Dead/Child", { "command" : lambda : None } )
menuDefinition.append( "/Off", { "command" : lambda : None, "active" : lambda menu : menu is None } )

deadSub = IECore.MenuDefinition()
deadSub.append( "/inside", { "command" : lambda : None } )
menuDefinition.append( "/DeadSub", { "subMenu" : deadSub, "active" : False } )

nativeMenu = GafferUI.Menu( menuDefinition, title = "Probe" )
entries = NE._entriesFromDefinition( NE._menuDefinition( nativeMenu ), nativeMenu )
byName = dict( ( e[0], e[3] ) for e in entries )

check( "checkBox 带着 menu 求值（✓ 和真菜单一致）", byName[ "Checked" ].checked is True,
	str( byName[ "Checked" ].checked ) )
check( "active 带着 menu 求值", NE._entryDisabled( byName[ "Off" ] ) )
check( "灰掉的子菜单里的条目也列出来、但一律点不动",
	"inside" in byName and NE._entryDisabled( byName[ "inside" ] ) )
check( "正常条目不灰", not NE._entryDisabled( byName[ "NeedsMenu" ] ) )
check( "摊平后的条目照样拿得到原来的属性（command / searchText）",
	byName[ "NeedsMenu" ].command is not None )

# 通过编辑器的面板真的点一下：勾选状态按原生传「点完之后」的值，WeakMethod 命令也拿到 menu
script = Gaffer.ScriptNode()
editor, window = makeEditor( script, "menuEval" )
editor._showMenuAsPanel( nativeMenu )
popup = editor._NetworkEditor__creatorPopup
popup.setSearchText( "Checked" )
popup.activateRow( 0 )
check( "勾着的那条点下去传 False", commands.calls == [ ( "toggled", False ) ], str( commands.calls ) )

editor._showMenuAsPanel( nativeMenu )
popup.setSearchText( "NeedsMenu" )
popup.activateRow( 0 )
check( "WeakMethod 命令拿到了 menu（以前当成不要参数 → TypeError）",
	len( commands.calls ) == 2 and commands.calls[1][0] == "withMenu" and commands.calls[1][1] is nativeMenu,
	str( commands.calls ) )
check( "截下来的菜单补上了宿主（命令里 `menu.ancestor( GraphEditor )` 有东西可拿）",
	nativeMenu.parent() is not None )

# 建面板到点下去之间 active 变了：原生在 `__actionTriggered` 里再问一遍
flipping = { "active" : True }
lateDefinition = IECore.MenuDefinition()
lateRan = []
lateDefinition.append( "/Late", { "command" : lambda : lateRan.append( True ), "active" : lambda : flipping[ "active" ] } )
lateMenu = GafferUI.Menu( lateDefinition )
editor._showMenuAsPanel( lateMenu )
flipping[ "active" ] = False
popup.activateRow( 0 )
check( "点下去那一刻再问一遍 active（变灰了就不跑）", lateRan == [], str( lateRan ) )

window.setVisible( False )

##########################################################################
section( "Tab 面板：喜爱 / 常用跨会话不互相覆盖，坏文件当空" )
##########################################################################

stateDirectory = tempfile.mkdtemp( prefix = "networkEditorReview" )
statePath = os.path.join( stateDirectory, "nodeCreator.json" )

sessionA = NE._CreatorUsage( path = statePath )
sessionB = NE._CreatorUsage( path = statePath )
sessionA.record( "Scene / Sphere" )              # A 先读进来
time.sleep( 0.01 )
sessionB.toggleFavourite( "Scene / Group" )      # B 后钉了一个喜爱
time.sleep( 0.01 )
sessionA.record( "Scene / Plane" )               # A 再存一次
check( "另一个会话钉的喜爱没被这边的存盘盖掉",
	NE._CreatorUsage( path = statePath ).isFavourite( "Scene / Group" ) )
check( "这边自己的使用次数也都在",
	NE._CreatorUsage( path = statePath ).count( "Scene / Plane" ) == 1 and
	NE._CreatorUsage( path = statePath ).count( "Scene / Sphere" ) == 1 )

with open( statePath, "w", encoding = "utf-8" ) as handle :
	handle.write( "{ not json" )
broken = NE._CreatorUsage( path = statePath )
check( "坏 JSON 当空的", broken.favourites() == [] and broken.count( "Scene / Plane" ) == 0 )
broken.toggleFavourite( "Scene / Cube" )
with open( statePath, encoding = "utf-8" ) as handle :
	repaired = json.load( handle )
check( "下一次存盘写回一份好的", repaired[ "favourites" ] == [ "Scene / Cube" ], str( repaired ) )

##########################################################################
section( "Tab 面板：搜索加分只在同一档里挪" )
##########################################################################

tierScript = Gaffer.ScriptNode()
tierEditor, tierWindow = makeEditor( tierScript, "tiers" )
tierUsage = NE._CreatorUsage( path = os.path.join( stateDirectory, "tiers.json" ) )
for _ in range( 10 ) :
	tierUsage.record( "Scene / SubTree" )
tierUsage.toggleFavourite( "Scene / SubTree" )

tierDefinition = IECore.MenuDefinition()
for name in ( "StandardOptions", "SubTree" ) :
	tierDefinition.append( "/Scene/%s" % name, { "command" : lambda : None } )
tierEditor._showPanel( NE._entriesFromDefinition( tierDefinition ), lambda item : None, usage = tierUsage )
tierPopup = tierEditor._NetworkEditor__creatorPopup
tierPopup.setSearchText( "st" )
tierOrder = [ tierPopup.rowAt( i )[0] for i in range( tierPopup.rowCount() ) ]
check( "常用又钉住的缩写命中（SubTree）也越不过名字前缀命中（StandardOptions）",
	tierOrder == [ "StandardOptions", "SubTree" ], str( tierOrder ) )
check( "打分档位确实不同", NE._matchScore( "st", "StandardOptions" ) < NE._matchScore( "st", "SubTree" ) )
tierWindow.setVisible( False )

##########################################################################
section( "Tab 面板：键盘（没选中时的上下 / 翻页不绕圈 / 左键不清搜索词）与滚轮" )
##########################################################################

keyScript = Gaffer.ScriptNode()
keyEditor, keyWindow = makeEditor( keyScript, "keys" )
keyDefinition = IECore.MenuDefinition()
for i in range( 40 ) :
	keyDefinition.append( "/Item%02d" % i, { "command" : lambda : None } )
keyEditor._showPanel( NE._entriesFromDefinition( keyDefinition ), lambda item : None )
keyPopup = keyEditor._NetworkEditor__creatorPopup
column = keyPopup._NodeCreatorPopup__columnWidget( 0 )
count = column.count()

column.setCurrentRow( -1 )
keyPopup._handleKeyEvent( keyEvent( QtCore.Qt.Key_Up ) )
check( "没选中时按 ↑ 落到最后一行", column.currentRow() == count - 1, str( column.currentRow() ) )
column.setCurrentRow( -1 )
keyPopup._handleKeyEvent( keyEvent( QtCore.Qt.Key_PageDown ) )
check( "没选中时 PageDown 落到第一行", column.currentRow() == 0, str( column.currentRow() ) )
column.setCurrentRow( count - 3 )
keyPopup._handleKeyEvent( keyEvent( QtCore.Qt.Key_PageDown ) )
check( "PageDown 到底停住、不绕回开头", column.currentRow() == count - 1, str( column.currentRow() ) )
column.setCurrentRow( count - 1 )
keyPopup._handleKeyEvent( keyEvent( QtCore.Qt.Key_Down ) )
check( "↓ 单步照旧绕回开头", column.currentRow() == 0, str( column.currentRow() ) )

keyPopup.setSearchText( "item1" )
search = keyPopup._NodeCreatorPopup__search
check( "← 在只有一列时不吃键（留给搜索框挪光标）",
	not keyPopup._handleKeyEvent( keyEvent( QtCore.Qt.Key_Left ) ) and search.text() == "item1",
	search.text() )
check( "退格在有字时也不吃键（留给搜索框删字）",
	not keyPopup._handleKeyEvent( keyEvent( QtCore.Qt.Key_Backspace ) ) and search.text() == "item1" )
keyPopup.setSearchText( "" )

scrollBar = column.verticalScrollBar()
scrollBar.setValue( 0 )
centre = column.viewport().mapToGlobal( column.viewport().rect().center() )
for _ in range( 8 ) :
	keyPopup._routeWheel( centre, -15 )   # 触摸板 / 平滑滚轮一次只报 15
check( "小增量攒够一行就滚（以前每次都四舍五入成 0）", scrollBar.value() > 0, str( scrollBar.value() ) )

# 划过叶子行：右边没列可收时什么都不重算
geometryCalls = []
originalGeometry = NE._NodeCreatorPopup._NodeCreatorPopup__updateGeometry
NE._NodeCreatorPopup._NodeCreatorPopup__updateGeometry = lambda self : geometryCalls.append( 1 ) or originalGeometry( self )
keyPopup.hoverRow( 3 )
keyPopup.hoverRow( 4 )
NE._NodeCreatorPopup._NodeCreatorPopup__updateGeometry = originalGeometry
check( "划过叶子行不重算整块面板尺寸", geometryCalls == [], str( geometryCalls ) )
keyPopup.hide()
keyWindow.setVisible( False )

##########################################################################
section( "项目快捷键换层：`graphGadget().setRoot()` 换的是我们自己的视图" )
##########################################################################

layerScript = Gaffer.ScriptNode()
layerBox = Gaffer.Box( "layerBox" )
layerScript.addChild( layerBox )
layerInner = GafferScene.Sphere( "layerInner" )
layerBox.addChild( layerInner )
layerEditor, layerWindow = makeEditor( layerScript, "layers" )

gadget = layerEditor.graphGadget()
check( "graphGadget() 交出去的是我们自己那个", gadget.getRoot().isSame( layerScript ) )
gadget.setRoot( layerBox )      # 项目 `jump_to_workspace` 就是这么干的
idle()
check( "视图跟着换进了 Box", layerEditor.getRootNode().isSame( layerBox ) )
layerEditor.frame( Gaffer.StandardSet( [ layerInner ] ) )   # `select_and_frame_node` 接着这么干
check( "frame() 在新层里认得出那个节点",
	layerEditor.graphView().viewedSceneRect().contains(
		layerEditor._NetworkEditor__nodeItems[ "layerInner" ].sceneBoundingRect().center() ) )
layerEditor.setRootNode( layerScript )
idle()
check( "自己换层时 gadget 跟着走", layerEditor.graphGadget().getRoot().isSame( layerScript ) )

# frame() 只框卡片本身：鼠标悬不悬停，框出来一样大
frameScript = Gaffer.ScriptNode()
frameScript.addChild( GafferScene.Sphere( "frameA" ) )
NE.setNodePosition( frameScript[ "frameA" ], imath.V2f( 0, 0 ) )
frameEditor, frameWindow = makeEditor( frameScript, "frame" )
frameItem = frameEditor._NetworkEditor__nodeItems[ "frameA" ]
frameEditor.graphView().frameItems( [ frameItem ] )
plainZoom = frameEditor.graphView().zoom()
frameItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
frameItem.setHoveredNodule( frameItem._nodules[ "bottom" ][0] )
frameEditor.graphView().frameItems( [ frameItem ] )
hoverZoom = frameEditor.graphView().zoom()
check( "悬停时取景和平时一样紧（不再按悬停余量框松）", abs( plainZoom - hoverZoom ) < 1e-6,
	"%s vs %s" % ( plainZoom, hoverZoom ) )
frameWindow.setVisible( False )
layerWindow.setVisible( False )

##########################################################################
section( "节点被同名的另一个换掉（Revert / Reference 重载）：item 换绑到新节点" )
##########################################################################

revertScript = Gaffer.ScriptNode()
revertScript.addChild( GafferScene.Sphere( "same" ) )
revertEditor, revertWindow = makeEditor( revertScript, "revert" )
oldItem = revertEditor._NetworkEditor__nodeItems[ "same" ]

with Gaffer.UndoScope( revertScript ) :
	revertScript.removeChild( revertScript[ "same" ] )
	revertScript.addChild( GafferScene.Plane( "same" ) )
idle()
newItem = revertEditor._NetworkEditor__nodeItems[ "same" ]
check( "同名换了节点就重建 item", newItem is not oldItem )
check( "新 item 连的是新节点", newItem.node.isSame( revertScript[ "same" ] ) )

##########################################################################
section( "错误角标：计算线程上报的错误回 UI 线程再画；换层 / 同名新节点不继承" )
##########################################################################

errorPlug = revertScript[ "same" ][ "out" ]
worker = threading.Thread(
	target = lambda : revertEditor._NetworkEditor__nodeError( errorPlug, errorPlug, "boom" )
)
worker.start()
worker.join()
check( "工作线程里没直接碰 item", not newItem._error if hasattr( newItem, "_error" ) else True )
idle()
errorNodes = revertEditor._NetworkEditor__errorNodes
check( "回到 UI 线程后挂上了错误角标", "same" in errorNodes, str( errorNodes ) )

with Gaffer.UndoScope( revertScript ) :
	revertScript.removeChild( revertScript[ "same" ] )
	revertScript.addChild( GafferScene.Cube( "same" ) )
idle()
check( "同名新节点不继承旧节点的错误角标", "same" not in revertEditor._NetworkEditor__errorNodes,
	str( revertEditor._NetworkEditor__errorNodes ) )

revertEditor._NetworkEditor__showNodeError( revertScript[ "same" ], "again" )
revertBox = Gaffer.Box( "revertBox" )
revertScript.addChild( revertBox )
revertEditor.setRootNode( revertBox )
idle()
check( "换层之后错误记录清空", not revertEditor._NetworkEditor__errorNodes )
revertWindow.setVisible( False )

##########################################################################
section( "拖到线上松手：摆位和塞进线里是同一步撤销" )
##########################################################################

dropScript = Gaffer.ScriptNode()
dropA = GafferScene.Sphere( "dropA" ) ; dropScript.addChild( dropA )
dropB = GafferScene.Group( "dropB" ) ; dropScript.addChild( dropB )
dropMid = GafferScene.Transform( "dropMid" ) ; dropScript.addChild( dropMid )
dropB[ "in" ][ 0 ].setInput( dropA[ "out" ] )
NE.setNodePosition( dropA, imath.V2f( 0, 20 ) )
NE.setNodePosition( dropB, imath.V2f( 0, 0 ) )
NE.setNodePosition( dropMid, imath.V2f( 30, 10 ) )
dropEditor, dropWindow = makeEditor( dropScript, "dropWire" )
midItem = dropEditor._NetworkEditor__nodeItems[ "dropMid" ]
edgeItem = next( e for e in dropEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "dropB" )

dropScript.selection().add( dropMid )
idle()
midItem.setSelected( True )
midItem.setPos( edgeItem.midpoint()[0] )
dropEditor._updateInsertCandidate()
check( "压在线上有候选", dropEditor._NetworkEditor__insertCandidate is not None )
dropEditor._commitDrag()
idle()
check( "塞进去了", dropMid[ "in" ].getInput() is not None and dropB[ "in" ][ 0 ].getInput().node().isSame( dropMid ) )
dropScript.undo()
idle()
check( "一次 Ctrl+Z：连线回到原样", dropB[ "in" ][ 0 ].getInput().node().isSame( dropA ) and dropMid[ "in" ].getInput() is None )
check( "同一次 Ctrl+Z：位置也回去了", NE.nodePosition( dropMid ) == imath.V2f( 30, 10 ), str( NE.nodePosition( dropMid ) ) )
dropWindow.setVisible( False )

##########################################################################
section( "写回位置只看选中的 item；Spreadsheet 里的 enabled 不重建节点卡片" )
##########################################################################

commitScript = Gaffer.ScriptNode()
commitScript.addChild( GafferScene.Sphere( "commitA" ) )
commitScript.addChild( Gaffer.Spreadsheet( "sheet" ) )
commitScript[ "sheet" ][ "rows" ].addRows( 2 )
NE.setNodePosition( commitScript[ "commitA" ], imath.V2f( 0, 0 ) )
commitEditor, commitWindow = makeEditor( commitScript, "commit" )
commitItem = commitEditor._NetworkEditor__nodeItems[ "commitA" ]
commitItem.setPos( QtCore.QPointF( 240, 0 ) )   # 没选中的 item 被程序挪了
commitEditor._commitNodePositions()
check( "没选中的不写回（Qt 拖动只挪选中的）", NE.nodePosition( commitScript[ "commitA" ] ) == imath.V2f( 0, 0 ) )

sheetItem = commitEditor._NetworkEditor__nodeItems[ "sheet" ]
commitScript[ "sheet" ][ "rows" ][ 1 ][ "enabled" ].setValue( False )
idle()
check( "表格里某一行的 enabled 不会让节点卡片重建",
	commitEditor._NetworkEditor__nodeItems[ "sheet" ] is sheetItem )
commitScript[ "sheet" ][ "enabled" ].setValue( False )
idle()
check( "节点自己的 enabled 才重建", commitEditor._NetworkEditor__nodeItems[ "sheet" ] is not sheetItem )
commitWindow.setVisible( False )

##########################################################################
section( "右键菜单：标题照原生；没标 childNodesAreViewable 的不给 Show Contents" )
##########################################################################

menuScript = Gaffer.ScriptNode()
opaque = Gaffer.Node( "opaque" )      # 有子节点、但不让看 —— 原生不给 Show Contents
opaque.addChild( Gaffer.Node( "inner" ) )
menuScript.addChild( opaque )
menuScript.addChild( GafferScene.Sphere( "m1" ) )
menuScript.addChild( GafferScene.Sphere( "m2" ) )
menuEditor, menuWindow = makeEditor( menuScript, "menus" )

menuEditor._NetworkEditor__popupNodeMenuFor( opaque, QtCore.QPoint( 10, 10 ), None )
paths = [ p for p, _ in NE._menuDefinition( menuEditor._NetworkEditor__contextMenu ).items() ]
check( "不可看的节点没有 Show Contents...", not any( "Show Contents" in p for p in paths ), str( paths ) )
menuEditor._NetworkEditor__contextMenu._qtWidget().hide()

menuScript.selection().add( menuScript[ "m1" ] )
menuScript.selection().add( menuScript[ "m2" ] )
idle()
menuEditor._NetworkEditor__popupNodeMenuFor( menuScript[ "m1" ], QtCore.QPoint( 10, 10 ), None )
check( "右键多选里的一个：标题是「2 Nodes」", menuEditor._NetworkEditor__contextMenu._Menu__title == "2 Nodes",
	str( menuEditor._NetworkEditor__contextMenu._Menu__title ) )
menuEditor._NetworkEditor__contextMenu._qtWidget().hide()
menuWindow.setVisible( False )

##########################################################################
section( "原生菜单栏粘贴：raster 是整个编辑器（含工具条），落点不差一个工具条" )
##########################################################################

pasteScript = Gaffer.ScriptNode()
pasteScript.addChild( GafferScene.Sphere( "p" ) )
pasteEditor, pasteWindow = makeEditor( pasteScript, "paste" )
view = pasteEditor.graphView()
viewport = pasteEditor._syncedViewport()
mouseInView = QtCore.QPoint( view.viewport().width() // 4, view.viewport().height() // 4 )
mouseGlobal = view.viewport().mapToGlobal( mouseInView )
bound = pasteEditor.bound()        # `EditMenu.paste` 用的就是它
gadgetPoint = viewport.rasterToGadgetSpace(
	imath.V2f( mouseGlobal.x() - bound.min().x, mouseGlobal.y() - bound.min().y ),
	gadget = pasteEditor.graphGadget()
).p0
seen = view.mapToScene( mouseInView )
check( "和鼠标在我们视图里指的那点一致",
	abs( gadgetPoint.x - seen.x() / NE.PX_PER_UNIT ) < 0.05 and abs( gadgetPoint.y + seen.y() / NE.PX_PER_UNIT ) < 0.05,
	"(%.3f, %.3f) vs (%.3f, %.3f)" % ( gadgetPoint.x, gadgetPoint.y, seen.x() / NE.PX_PER_UNIT, -seen.y() / NE.PX_PER_UNIT ) )
pasteWindow.setVisible( False )

##########################################################################
section( "按住 X：中键平移后回到划线模式；平移中松 X 就退出；双击照样算点；提示不被冲掉" )
##########################################################################

cutScript = Gaffer.ScriptNode()
cutA = GafferScene.Sphere( "cutA" ) ; cutScript.addChild( cutA )
cutB = GafferScene.Group( "cutB" ) ; cutScript.addChild( cutB )
cutB[ "in" ][ 0 ].setInput( cutA[ "out" ] )
NE.setNodePosition( cutA, imath.V2f( 0, 10 ) )
NE.setNodePosition( cutB, imath.V2f( 0, 0 ) )
cutEditor, cutWindow = makeEditor( cutScript, "cut" )
cutView = cutEditor.graphView()
status = cutEditor._NetworkEditor__statusLabel


def mouse( kind, position, button, buttons ) :

	event = QtGui.QMouseEvent( kind, QtCore.QPointF( position ), QtCore.QPointF( cutView.viewport().mapToGlobal( position ) ),
		button, buttons, QtCore.Qt.NoModifier )
	{
		QtCore.QEvent.MouseButtonPress : cutView.mousePressEvent,
		QtCore.QEvent.MouseMove : cutView.mouseMoveEvent,
		QtCore.QEvent.MouseButtonRelease : cutView.mouseReleaseEvent,
		QtCore.QEvent.MouseButtonDblClick : cutView.mouseDoubleClickEvent,
	}[ kind ]( event )


def key( kind, k ) :

	( cutView.keyPressEvent if kind == QtCore.QEvent.KeyPress else cutView.keyReleaseEvent )( keyEvent( k, kind = kind ) )

empty = QtCore.QPoint( 20, 20 )
key( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
check( "按下 X 进入划线模式", cutView.isCutting() and "Delete mode" in status.text() )
mouse( QtCore.QEvent.MouseButtonPress, empty, QtCore.Qt.MiddleButton, QtCore.Qt.MiddleButton )
mouse( QtCore.QEvent.MouseMove, empty + QtCore.QPoint( 30, 0 ), QtCore.Qt.NoButton, QtCore.Qt.MiddleButton )
check( "中键照旧平移", not cutView.isCutting() )
mouse( QtCore.QEvent.MouseButtonRelease, empty + QtCore.QPoint( 30, 0 ), QtCore.Qt.MiddleButton, QtCore.Qt.NoButton )
check( "松开中键回到划线模式（X 还按着）", cutView.isCutting() and "Delete mode" in status.text() )

mouse( QtCore.QEvent.MouseButtonPress, empty, QtCore.Qt.MiddleButton, QtCore.Qt.MiddleButton )
key( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
check( "平移中松 X：提示马上收掉", "Delete mode" not in status.text(), status.text() )
mouse( QtCore.QEvent.MouseButtonRelease, empty, QtCore.Qt.MiddleButton, QtCore.Qt.NoButton )
check( "平移结束后不再回到划线模式", not cutView.isCutting() )

# 划线模式里快速点两下：第二下是 DoubleClick 事件，照样算一次「点」（切线），不开 NodeEditor
edgeMid = cutView.mapFromScene( cutEditor._NetworkEditor__edgeItems[0].midpoint()[0] )
opened = []
originalEdit = NE.NetworkEditor._editNode
NE.NetworkEditor._editNode = lambda self, node : opened.append( node.getName() )
key( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
mouse( QtCore.QEvent.MouseButtonDblClick, edgeMid, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
mouse( QtCore.QEvent.MouseButtonRelease, edgeMid, QtCore.Qt.LeftButton, QtCore.Qt.NoButton )
NE.NetworkEditor._editNode = originalEdit
check( "双击那一下没开 NodeEditor", opened == [], str( opened ) )
check( "而是当成一次点击切掉了线", cutB[ "in" ][ 0 ].getInput() is None )
idle()
check( "图更新（刷计数）之后划线提示还在", cutView.isCutting() and "Delete mode" in status.text(), status.text() )
key( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
check( "松开 X 后回到计数", "nodes" in status.text() and "Delete mode" not in status.text(), status.text() )
cutWindow.setVisible( False )

##########################################################################
section( "包围盒 / 命中形状：书签编号放得下；悬停不作废 shape" )
##########################################################################

bookScript = Gaffer.ScriptNode()
bookScript.addChild( GafferScene.Sphere( "book" ) )
Gaffer.MetadataAlgo.setNumericBookmark( bookScript, 3, bookScript[ "book" ] )
bookEditor, bookWindow = makeEditor( bookScript, "bookmark" )
bookItem = bookEditor._NetworkEditor__nodeItems[ "book" ]
leftmost = bookItem.cardRect().left() - 28.0 * NE.BOOKMARK_MAX_SCALE
check( "拉远时编号最远画到的地方在包围盒里", bookItem.boundingRect().left() <= leftmost,
	"%s vs %s" % ( bookItem.boundingRect().left(), leftmost ) )

shapeBefore = bookItem.shape()
bookItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
bookItem.hoverLeaveEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "悬停进出不重建 shape（它和悬停无关）", bookItem.shape() is shapeBefore )
bookWindow.setVisible( False )

##########################################################################
section( "连线：箭头和线同一个颜色；悬停小框写插口相对名" )
##########################################################################

wireScript = Gaffer.ScriptNode()
wireSource = GafferScene.Sphere( "wireSource" ) ; wireScript.addChild( wireSource )
nameSwitch = Gaffer.NameSwitch( "wireSwitch" ) ; wireScript.addChild( nameSwitch )
nameSwitch.setup( GafferScene.ScenePlug() )
nameSwitch[ "in" ][ 1 ][ "value" ].setInput( wireSource[ "out" ] )
wireEditor, wireWindow = makeEditor( wireScript, "wire" )
wireItem = wireEditor._NetworkEditor__edgeItems[0]
check( "悬停小框写的是 in.in1.value 而不是一个 value",
	"in.in1.value" in wireItem.toolTip(), wireItem.toolTip() )

wireItem.setWireSelected( True )
image = QtGui.QImage( 400, 400, QtGui.QImage.Format_ARGB32 )
image.fill( 0 )
painter = QtGui.QPainter( image )
painter.translate( 200 - wireItem.midpoint()[0].x(), 200 - wireItem.midpoint()[0].y() )
option = QtWidgets.QStyleOptionGraphicsItem()
wireItem.paint( painter, option )
painter.end()
arrowPixel = QtGui.QColor( image.pixel( 200, 200 ) )
selected = QtGui.QColor( NE._selectedBorder )
check( "选中时中点箭头也是选中色（以前停在普通线色）",
	abs( arrowPixel.red() - selected.red() ) < 30 and abs( arrowPixel.blue() - selected.blue() ) < 30,
	"%s vs %s" % ( arrowPixel.name(), selected.name() ) )
wireWindow.setVisible( False )

##########################################################################
section( "数据层：filter 插口只认输入；闭包输出的混合材质算材质；注释在 focus context 里求值" )
##########################################################################

class _FilterHolder( Gaffer.Node ) :

	def __init__( self, name = "_FilterHolder" ) :

		Gaffer.Node.__init__( self, name )
		self["filter"] = GafferScene.FilterPlug()
		self["filterOut"] = GafferScene.FilterPlug( direction = Gaffer.Plug.Direction.Out )

holder = _FilterHolder()
check( "输出的 FilterPlug 不算（原生 `FilterPlug.InputRange`）",
	NE._filterPlug( holder ) is not None and NE._filterPlug( holder ).getName() == "filter" )

mixShader = Gaffer.Node( "mixShader" )
mixShader[ "name" ] = Gaffer.StringPlug( defaultValue = "mix_shader" )
mixShader[ "type" ] = Gaffer.StringPlug( defaultValue = "ai:surface" )
mixShader[ "out" ] = GafferScene.ClosurePlug( direction = Gaffer.Plug.Direction.Out )
check( "mix_shader（闭包输出）是材质图标，不是工具图标",
	NE.shaderGlyph( mixShader ) == NE.GLYPH_SHADER, str( NE.shaderGlyph( mixShader ) ) )

annotationScript = Gaffer.ScriptNode()
annotated = Gaffer.Node( "annotated" )
annotated[ "user" ][ "f" ] = Gaffer.FloatPlug( flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
annotationScript.addChild( annotated )
annotationScript[ "e" ] = Gaffer.Expression()
annotationScript[ "e" ].setExpression( 'parent["annotated"]["user"]["f"] = context.getFrame()' )
annotationScript.context().setFrame( 7 )
check( "注释里的 {插口} 按 focus 那条路的 context 求值（脚本当前帧 7）",
	NE.substituteAnnotationText( "f={user.f}", annotated ) == "f=7.0" or
	NE.substituteAnnotationText( "f={user.f}", annotated ) == "f=7",
	NE.substituteAnnotationText( "f={user.f}", annotated ) )

##########################################################################
print( "\n%d/%d passed" % ( len( _passed ), len( _passed ) + len( _failed ) ) )
if _failed :
	print( "FAILED:\n  " + "\n  ".join( _failed ) )
	sys.exit( 1 )
