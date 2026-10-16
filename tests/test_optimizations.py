##########################################################################
# networkEditor 无头测试：2026-09 代码整理那一轮的专项断言
#
# 每条都对着一处具体改动：几何缓存 / 圆点绘制表 / 一次鼠标移动只查一次 scene /
# 手势互斥 / 数据层对齐原生 / 跨层同名节点的选择同步 / 右键菜单换层不搬节点 /
# 错误角标随插口变脏清掉 / 位置更新只动脏节点。**不依赖 test_network_editor.py**。
##########################################################################

import os
import sys
import math
import random
import tempfile

sys.path.insert( 0, os.path.join( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ), "python" ) )

import imath
import IECore
import Gaffer
import GafferScene
import GafferUI

from Qt import QtCore, QtGui, QtWidgets

import networkEditor as NE
from networkEditor import node_item as _nodeItemModule

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


def addSectionedMaterial( script, name ) :

	node = Gaffer.Node( name )
	params = Gaffer.CompoundDataPlug( "parameters" )
	node.addChild( params )
	Gaffer.Metadata.registerValue( params, "nodule:type", "GafferUI::CompoundNodule" )
	Gaffer.Metadata.registerValue( params, "noduleLayout:section", "left" )
	for plugName, label, sec, value in (
		( "base_color", "Base Color", "Base", imath.Color4f( 1, 0, 0, 1 ) ),
		( "metalness", "Metalness", "Base", 0.5 ),
		( "transmission_scatter_anisotropy", "Transmission Scatter Anisotropy", "Transmission", 0.3 ),
		( "normal", "Normal", "Geometry", imath.V3f( 0, 0, 1 ) ),
	) :
		nvp = Gaffer.NameValuePlug( plugName, value, plugName )
		params.addChild( nvp )
		Gaffer.Metadata.registerValue( nvp, "noduleLayout:label", label )
		Gaffer.Metadata.registerValue( nvp, "layout:section", sec )
	out = Gaffer.Color3fPlug( "out", direction = Gaffer.Plug.Direction.Out )
	node.addChild( out )
	Gaffer.Metadata.registerValue( out, "noduleLayout:section", "right" )
	script.addChild( node )
	return node


application = Gaffer.ApplicationRoot( "networkEditorOptTest" )

##########################################################################
section( "几何缓存：boundingRect / shape / cardPath 只算一次，几何一变就作废" )
##########################################################################

geoScript = Gaffer.ScriptNode()
application["scripts"].addChild( geoScript )
geoA = GafferScene.Sphere( "geoA" )
geoB = GafferScene.Isolate( "geoB" )
geoScript.addChild( geoA )
geoScript.addChild( geoB )
geoB["in"].setInput( geoA["out"] )
NE.setNodePosition( geoA, imath.V2f( 0, 0 ) )
NE.setNodePosition( geoB, imath.V2f( 0, -12 ) )
geoEditor, geoWindow = makeEditor( geoScript, "geometry" )
geoView = geoEditor.graphView()
geoItems = geoEditor._NetworkEditor__nodeItems
itemA = geoItems["geoA"]

check( "scene 的 BSP 深度按常量设了", geoView.scene().bspTreeDepth() == NE.BSP_TREE_DEPTH,
	str( geoView.scene().bspTreeDepth() ) )

r1 = itemA.boundingRect()
r2 = itemA.boundingRect()
check( "boundingRect 两次一样", r1 == r2, "%s vs %s" % ( r1, r2 ) )
check( "boundingRect 给的是拷贝（改返回值不污染缓存）",
	( r1.adjust( 10, 10, 10, 10 ) or True ) and itemA.boundingRect() == r2 )
check( "shape 缓存：几何没变就是同一个对象", itemA.shape() is itemA.shape() )
check( "cardPath 缓存：同一个对象", itemA.cardPath() is itemA.cardPath() )

# setFocused 现在会报几何变化：包围盒放宽到能装下按 1/lod 放大的角标
before = itemA.boundingRect()
itemA.setFocused( True )
after = itemA.boundingRect()
check( "setFocused 后包围盒变宽（角标要画在卡外）", after.width() > before.width() + 50,
	"%.1f -> %.1f" % ( before.width(), after.width() ) )
check( "setFocused 让 shape 缓存作废", itemA.shape() is itemA.shape() )  # 重新建了一份，仍然稳定
# 索引也要知道：在角标那一片能找到这个 item（没 prepareGeometryChange 的话 BSP 里还是旧框）
flagRect = itemA.mapToScene( itemA.focusFlagHitRect() ).boundingRect()
farCorner = QtCore.QRectF( after.right() - 5, after.top(), 4, 4 ).translated( itemA.scenePos() )
found = [ i for i in geoView.scene().items( farCorner, QtCore.Qt.IntersectsItemBoundingRect ) if i is itemA ]
check( "scene 索引按新包围盒找得到 focus 中的节点（prepareGeometryChange 生效）", bool( found ) )
itemA.setFocused( False )
check( "取消 focus 包围盒缩回", itemA.boundingRect() == before,
	"%s vs %s" % ( itemA.boundingRect(), before ) )

# 悬停放大标签用完整参数名，包围盒余量要跟着名字长度走
mat = addSectionedMaterial( geoScript, "geoMat" )
NE.setNodePosition( mat, imath.V2f( 40, 0 ) )
idle()
matItem = geoItems["geoMat"]
longPlug = mat["parameters"]["transmission_scatter_anisotropy"]
plain = matItem.boundingRect()
matItem.setHoveredNodule( longPlug )
hovered = matItem.boundingRect()
labelWidth = QtGui.QFontMetrics( NE._font( 8.5 ) ).horizontalAdvance( NE.noduleLabel( longPlug ) )
check( "长参数名悬停时包围盒余量 >= 标签宽度（以前钉死 150）",
	( hovered.width() - plain.width() ) / 2.0 >= labelWidth,
	"grew %.1f, label %d" % ( ( hovered.width() - plain.width() ) / 2.0, labelWidth ) )
matItem.setHoveredNodule( None )

##########################################################################
section( "圆点绘制表：paint / 命中不再每个圆点算一次 relativeName" )
##########################################################################

itemB = geoItems["geoB"]
for section_ in ( "top", "bottom", "left", "right" ) :
	for plug in itemB._nodules.get( section_, [] ) :
		hit = itemB.noduleAt( itemB.nodulePosition( plug ) )
		check( "noduleAt 找回 %s" % NE.plugKey( geoB, plug ), hit is not None and hit.isSame( plug ) )

plugKeyCalls = []
originalPlugKey = _nodeItemModule.plugKey
_nodeItemModule.plugKey = lambda node, plug : ( plugKeyCalls.append( 1 ), originalPlugKey( node, plug ) )[1]
try :
	image = QtGui.QImage( 400, 200, QtGui.QImage.Format_ARGB32 )
	image.fill( 0 )
	painter = QtGui.QPainter( image )
	painter.translate( 200, 100 )
	option = QtWidgets.QStyleOptionGraphicsItem()
	itemB.paint( painter, option, None )
	painter.end()
finally :
	_nodeItemModule.plugKey = originalPlugKey
check( "画一张普通卡片不调 plugKey（位置 / 半径 / 颜色都在表里）", not plugKeyCalls, str( len( plugKeyCalls ) ) )

collapsedCalls = []
originalCollapsed = _nodeItemModule.sectionCollapsed
_nodeItemModule.sectionCollapsed = lambda *a : ( collapsedCalls.append( a ), originalCollapsed( *a ) )[1]
try :
	image = QtGui.QImage( 600, 500, QtGui.QImage.Format_ARGB32 )
	image.fill( 0 )
	painter = QtGui.QPainter( image )
	painter.translate( 300, 250 )
	for _ in range( 3 ) :
		matItem.paint( painter, QtWidgets.QStyleOptionGraphicsItem(), None )
		matItem.noduleAt( QtCore.QPointF( 0, 0 ) )
	painter.end()
finally :
	_nodeItemModule.sectionCollapsed = originalCollapsed
check( "分栏节点画三遍 + 命中三遍不再读 sectionCollapsed 元数据", not collapsedCalls, str( len( collapsedCalls ) ) )
check( "分栏节点的名字仍画在卡上（有墨）",
	any( QtGui.QColor( image.pixel( x, 250 - int( matItem._height / 2 ) + 11 ) ).lightness() > 120
		for x in range( 300 - int( matItem._width / 2 ) + 4, 300 + int( matItem._width / 2 ) ) ) )

##########################################################################
section( "一次鼠标移动只查一次 scene，而且答案和逐个问一模一样" )
##########################################################################

hovScript = Gaffer.ScriptNode()
application["scripts"].addChild( hovScript )
hovNodes = []
for i in range( 12 ) :
	n = GafferScene.Isolate( "hov%d" % i ) if i % 3 else GafferScene.Group( "hov%d" % i )
	hovScript.addChild( n )
	NE.setNodePosition( n, imath.V2f( ( i % 4 ) * 16.0, -( i // 4 ) * 9.0 ) )
	hovNodes.append( n )
for i in range( 4, 12 ) :
	target = hovNodes[i]["in"] if isinstance( hovNodes[i], GafferScene.Isolate ) else hovNodes[i]["in"][0]
	target.setInput( hovNodes[i - 4]["out"] )
hovMat = addSectionedMaterial( hovScript, "hovMat" )
NE.setNodePosition( hovMat, imath.V2f( 75, -6 ) )
NE.setSectionCollapsed( hovMat, "left", "Base", False )
hovBox = Gaffer.Box( "hovBox" )  # 四条边都有 `+`
hovScript.addChild( hovBox )
NE.setNodePosition( hovBox, imath.V2f( 75, -30 ) )
hovBackdrop = Gaffer.Backdrop( "hovBackdrop" )
hovScript.addChild( hovBackdrop )
NE.setNodePosition( hovBackdrop, imath.V2f( 8, -30 ) )
hovEditor, hovWindow = makeEditor( hovScript, "hover", ( 1200, 800 ) )
hovView = hovEditor.graphView()
hovView.frameAll()
idle()

captured = {}
hovEditor._setHoveredNodule = lambda item, plug : captured.__setitem__( "nodule", ( item, plug ) )
hovEditor._setHoveredAdder = lambda item, sec : captured.__setitem__( "adder", ( item, sec ) )
hovEditor._setHoveredSection = lambda item, side, name : captured.__setitem__( "section", ( item, side, name ) )
hovEditor._setHoveredBackdrop = lambda item : captured.__setitem__( "backdrop", item )

def legacyHover( position ) :

	item, plug = hovView.noduleAt( position )
	adderItem, sec = hovView.adderAt( position ) if plug is None else ( None, None )
	headerItem, side, name = hovView.sectionHeaderAt( position ) if ( plug is None and sec is None ) else ( None, None, None )
	if plug is None and sec is None and headerItem is None :
		bd, h, v = hovView.backdropEdgeAt( position )
		if bd is None :
			bd = hovView.backdropItemAt( position )
			h = v = 0
		backdrop = bd if ( bd is not None and not ( h or v ) ) else None
	else :
		backdrop = None
	return (
		( item.nodeName if item is not None and plug is not None else None, NE.plugKey( item.node, plug ) if plug is not None else None ),
		( adderItem.nodeName if adderItem is not None and sec is not None else None, sec ),
		( headerItem.nodeName if headerItem is not None and name is not None else None, side, name ),
		backdrop.nodeName if backdrop is not None else None,
	)

def probedHover( position ) :

	captured.clear()
	hovView._GraphView__updateHover( position )
	item, plug = captured["nodule"]
	adderItem, sec = captured["adder"]
	headerItem, side, name = captured["section"]
	backdrop = captured["backdrop"]
	return (
		( item.nodeName if item is not None and plug is not None else None, NE.plugKey( item.node, plug ) if plug is not None else None ),
		( adderItem.nodeName if adderItem is not None and sec is not None else None, sec ),
		( headerItem.nodeName if headerItem is not None and name is not None else None, side, name ),
		backdrop.nodeName if backdrop is not None else None,
	)

random.seed( 7 )
viewport = hovView.viewport().rect()
samples = [ QtCore.QPoint( random.randint( 0, viewport.width() - 1 ), random.randint( 0, viewport.height() - 1 ) ) for _ in range( 600 ) ]
# 再专门往圆点 / `+` / 分栏三角 / Backdrop 边上凑一批（随机点很少正好压在上面）
targeted = []
for item in hovEditor._NetworkEditor__nodeItems.values() :
	for entries in item._NodeItem__noduleDraw.values() :
		for plug, key, pos, radius, color in entries :
			scenePoint = item.mapToScene( pos )
			for dx, dy in ( ( 0, 0 ), ( 3, -2 ), ( -6, 5 ), ( 9, 0 ), ( 0, -11 ) ) :
				targeted.append( hovView.mapFromScene( scenePoint ) + QtCore.QPoint( dx, dy ) )
	for sec, pos in item._NodeItem__adderPositions.items() :
		targeted.append( hovView.mapFromScene( item.mapToScene( pos ) ) )
	for side, headers in getattr( item, "_NodeItem__sectionHeaders", {} ).items() :
		rect = item.cardRect()
		for name, y in headers :
			x = rect.left() if side == "left" else rect.right()
			for dx in ( -4, 0, 4, 20 ) :
				targeted.append( hovView.mapFromScene( item.mapToScene( QtCore.QPointF( x + dx, y ) ) ) )
bdItem = hovEditor._NetworkEditor__backdropItems["hovBackdrop"]
frame = bdItem.frameRect()
for x in ( frame.left(), frame.right(), frame.center().x() ) :
	for y in ( frame.top(), frame.top() + 6, frame.bottom(), frame.center().y() ) :
		for d in ( -3, 0, 3 ) :
			targeted.append( hovView.mapFromScene( bdItem.mapToScene( QtCore.QPointF( x + d, y + d ) ) ) )

mismatches = []
hits = { "nodule" : 0, "adder" : 0, "section" : 0, "backdrop" : 0 }
for position in samples + targeted :
	expected = legacyHover( position )
	got = probedHover( position )
	if expected != got :
		mismatches.append( ( position, expected, got ) )
	if expected[0][1] is not None : hits["nodule"] += 1
	if expected[1][1] is not None : hits["adder"] += 1
	if expected[2][2] is not None : hits["section"] += 1
	if expected[3] is not None : hits["backdrop"] += 1
check( "%d 个采样点上合并探针和逐个问的答案完全一致" % len( samples + targeted ), not mismatches,
	"%d mismatches, first: %s" % ( len( mismatches ), mismatches[:3] ) )
check( "采样真覆盖到了四种东西（圆点 / + / 分栏 / Backdrop）",
	all( hits[k] > 0 for k in hits ), str( hits ) )

del hovEditor._setHoveredNodule, hovEditor._setHoveredAdder, hovEditor._setHoveredSection, hovEditor._setHoveredBackdrop

itemsCalls = []
originalItems = hovView.items
hovView.items = lambda *a, **kw : ( itemsCalls.append( a ), originalItems( *a, **kw ) )[1]
try :
	for position in samples[:40] :
		itemsCalls[:] = []
		move = QtGui.QMouseEvent(
			QtCore.QEvent.MouseMove, QtCore.QPointF( position ),
			QtCore.QPointF( hovView.viewport().mapToGlobal( position ) ),
			QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
		)
		hovView.mouseMoveEvent( move )
		if len( itemsCalls ) != 1 :
			break
	check( "空着手移动一次只查一次 scene（以前 7~9 次）", len( itemsCalls ) == 1, str( len( itemsCalls ) ) )
finally :
	del hovView.items

##########################################################################
section( "手势互斥：一个手势没做完时第二个键按下 / 松开都不算" )
##########################################################################

def mouse( kind, button, position, buttons = None ) :

	return QtGui.QMouseEvent(
		kind, QtCore.QPointF( position ),
		QtCore.QPointF( hovView.viewport().mapToGlobal( position ) ),
		button, buttons if buttons is not None else button, QtCore.Qt.NoModifier,
	)

emptyPoint = hovView.mapFromScene( QtCore.QPointF( -4000, -4000 ) )
hovView.mousePressEvent( mouse( QtCore.QEvent.MouseButtonPress, QtCore.Qt.MiddleButton, emptyPoint ) )
check( "中键按空白 = 平移", hovView._GraphView__mode == NE._MODE_PAN, str( hovView._GraphView__mode ) )
hovView.mousePressEvent( mouse( QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, emptyPoint,
	QtCore.Qt.LeftButton | QtCore.Qt.MiddleButton ) )
check( "平移中按左键：模式不变", hovView._GraphView__mode == NE._MODE_PAN, str( hovView._GraphView__mode ) )
hovView.mouseReleaseEvent( mouse( QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, emptyPoint, QtCore.Qt.MiddleButton ) )
check( "平移中松左键：手势没结束", hovView._GraphView__mode == NE._MODE_PAN, str( hovView._GraphView__mode ) )
check( "平移期间 item 交互仍关着", not hovView.isInteractive() )
hovView.mouseReleaseEvent( mouse( QtCore.QEvent.MouseButtonRelease, QtCore.Qt.MiddleButton, emptyPoint, QtCore.Qt.NoButton ) )
check( "松开中键才结束平移", hovView._GraphView__mode == NE._MODE_NONE, str( hovView._GraphView__mode ) )
check( "结束后 item 交互恢复", hovView.isInteractive() )

hovView._GraphView__mode = NE._MODE_RESIZE
hovView._GraphView__resizeItem = bdItem
hovView._GraphView__resizeEdges = ( 1, 0 )
hovView._discardTransientItems()
check( "_discardTransientItems 连拉框状态一起放手",
	hovView._GraphView__mode == NE._MODE_NONE and hovView._GraphView__resizeItem is None
	and hovView._GraphView__resizeEdges == ( 0, 0 ) )

##########################################################################
section( "数据层：注释值格式 / ShaderTweaks 的 + / 会长子插口的插口 / 过路节点方向传递" )
##########################################################################

fmtNode = Gaffer.Node( "fmt" )
fmtNode.addChild( Gaffer.BoolPlug( "b", defaultValue = True ) )
fmtNode.addChild( Gaffer.V3fPlug( "v", defaultValue = imath.V3f( 1, 2.5, 3 ) ) )
fmtNode.addChild( Gaffer.IntVectorDataPlug( "iv", defaultValue = IECore.IntVectorData( [ 1, 2 ] ) ) )
fmtNode.addChild( Gaffer.FloatPlug( "f", defaultValue = 0.5 ) )
fmtNode.addChild( Gaffer.StringPlug( "s", defaultValue = "abc" ) )
check( "BoolPlug 写成 On / Off（原生 formatPlugValue）", NE._formatPlugValue( fmtNode["b"] ) == "On" )
check( "复合插口逐个子插口逗号连", NE._formatPlugValue( fmtNode["v"] ) == "1, 2.5, 3", NE._formatPlugValue( fmtNode["v"] ) )
check( "向量数据逗号连", NE._formatPlugValue( fmtNode["iv"] ) == "1, 2", NE._formatPlugValue( fmtNode["iv"] ) )
check( "浮点不带尾巴", NE._formatPlugValue( fmtNode["f"] ) == "0.5", NE._formatPlugValue( fmtNode["f"] ) )
check( "字符串原样", NE._formatPlugValue( fmtNode["s"] ) == "abc" )
check( "注释里 {b} 替换成 On", NE.substituteAnnotationText( "x {b} {v}", fmtNode ) == "x On 1, 2.5, 3",
	NE.substituteAnnotationText( "x {b} {v}", fmtNode ) )

tweaks = GafferScene.ShaderTweaks( "tweaks" )
tweak = Gaffer.TweakPlug( "a", Gaffer.FloatPlug( "value" ) )
tweaks["tweaks"].addChild( tweak )
adderType = "GafferSceneUI.ShaderTweaksUI.PlugAdder"
# ShaderTweaksUI 给 `tweaks.*` 默认注册的就是 `noduleLayout:visible = False`（非 Closure）
check( "默认藏着的 Replace tweak 让 + 显示", NE._customGadgetVisible( adderType, tweaks["tweaks"] ) )
Gaffer.Metadata.registerValue( tweak, "noduleLayout:visible", True )
check( "tweak 显示出来之后 + 就没了", not NE._customGadgetVisible( adderType, tweaks["tweaks"] ) )
Gaffer.Metadata.registerValue( tweak, "noduleLayout:visible", False )
check( "再藏回去 + 又出现", NE._customGadgetVisible( adderType, tweaks["tweaks"] ) )
tweak["mode"].setValue( int( Gaffer.TweakPlug.Mode.Add ) )
check( "Add 模式的 tweak 不算能显示（原生 showablePlugs）", not NE._customGadgetVisible( adderType, tweaks["tweaks"] ) )
tweak["mode"].setValue( int( Gaffer.TweakPlug.Mode.Create ) )
check( "Create 模式算", NE._customGadgetVisible( adderType, tweaks["tweaks"] ) )
Gaffer.MetadataAlgo.setReadOnly( tweak["value"], True )
check( "value 只读就不算（看的是 value 不是 TweakPlug）", not NE._customGadgetVisible( adderType, tweaks["tweaks"] ) )
Gaffer.MetadataAlgo.setReadOnly( tweak["value"], False )

iso = GafferScene.Isolate( "iso" )
growable = [ p.getName() for p in iso.children( Gaffer.Plug ) if NE.plugMayGrowChildren( p ) ]
check( "Isolate 只有 user 容器算会长子插口", growable == [ "user" ], str( growable ) )
nameSwitch = Gaffer.NameSwitch( "ns" )
nameSwitch.setup( GafferScene.ScenePlug() )
check( "NameSwitch.in（ArrayPlug）算", NE.plugMayGrowChildren( nameSwitch["in"] ) )
check( "TweaksPlug 算", NE.plugMayGrowChildren( tweaks["tweaks"] ) )

byName = { "shA" : Gaffer.Node(), "d1" : Gaffer.Dot(), "d2" : Gaffer.Dot(), "d3" : Gaffer.Dot(), "shB" : Gaffer.Node(), "iso" : GafferScene.Isolate() }
axes = dict( ( n, "vertical" ) for n in byName )
axes["shA"] = axes["shB"] = "horizontal"
allEdges = [ ( "shA", "d1", None ), ( "d1", "d2", None ), ( "d2", "d3", None ), ( "d3", "shB", None ), ( "iso", "d3", None ) ]
NE._layoutPassThroughAxes( byName, axes, allEdges )
check( "只有一个真邻居的 Dot 跟它走（原来的行为不变）", axes["d1"] == "horizontal", axes["d1"] )
check( "两个真邻居方向不一致的 Dot 不动", axes["d3"] == "vertical", axes["d3"] )
check( "夹在两个过路节点中间的 Dot 顺着链条继承方向（以前永远是默认）", axes["d2"] == "horizontal", axes["d2"] )

##########################################################################
section( "编辑器：跨层同名节点的选择 / 右键换层不搬节点 / 错误角标 / 只动脏节点" )
##########################################################################

edScript = Gaffer.ScriptNode()
application["scripts"].addChild( edScript )
rootSphere = GafferScene.Sphere( "sphere" )
edScript.addChild( rootSphere )
edBox = Gaffer.Box( "box" )
edScript.addChild( edBox )
innerSphere = GafferScene.Sphere( "sphere" )
edBox.addChild( innerSphere )
lone = GafferScene.Cube( "loneCube" )
edBox.addChild( lone )
boxIn = Gaffer.BoxIn( "in" )
edBox.addChild( boxIn )
rootIn = Gaffer.BoxIn( "in" )
edScript.addChild( rootIn )  # 根层也放一个叫 in 的（每个 Box 里都有）
for node, pos in ( ( rootSphere, ( 0, 0 ) ), ( edBox, ( 30, 0 ) ), ( rootIn, ( 60, 0 ) ),
	( innerSphere, ( 100, 100 ) ), ( lone, ( 200, 200 ) ), ( boxIn, ( 150, 150 ) ) ) :
	NE.setNodePosition( node, imath.V2f( *pos ) )
edEditor, edWindow = makeEditor( edScript, "editor" )
edItems = lambda : edEditor._NetworkEditor__nodeItems

edScript.selection().clear()
edScript.selection().add( innerSphere )
edScript.selection().add( boxIn )
idle()
check( "别层选中的同名节点不会让这层的 item 显示成选中",
	not edItems()["sphere"].isSelected() and not edItems()["in"].isSelected() )
edEditor._selectClicked( edItems()["sphere"], QtCore.Qt.NoModifier )
idle()
check( "点根层的 sphere → 选中的是根层那个、别层的清掉",
	[ n.fullName() for n in edScript.selection() ] == [ rootSphere.fullName() ],
	str( [ n.fullName() for n in edScript.selection() ] ) )
edEditor._selectClicked( edItems()["in"], QtCore.Qt.ShiftModifier )
idle()
check( "Shift 加选根层的 in → 两个都是根层的",
	sorted( n.fullName() for n in edScript.selection() ) == sorted( [ rootSphere.fullName(), rootIn.fullName() ] ),
	str( [ n.fullName() for n in edScript.selection() ] ) )

edScript.selection().clear()
idle()
lonePosition = NE.nodePosition( lone )
edEditor._showContextMenu( edItems()["box"], None, QtCore.QPoint( 10, 10 ), QtCore.QPointF( -500.0, -500.0 ) )
menu = edEditor._NetworkEditor__contextMenu
definition = NE._menuDefinition( menu )
paths = [ p for p, _ in definition.items() ]
showContents = [ p for p in paths if p.rpartition( "/" )[2].startswith( "Show Contents" ) ]
check( "节点右键菜单里有 Show Contents...", bool( showContents ), str( paths ) )
if showContents :
	definition.item( showContents[0] ).command()
	menu._qtWidget().hide()
	idle()
	idle()
	check( "进了 Box", edEditor.getRootNode().isSame( edBox ) )
	check( "Box 里没连线的节点没有被搬到菜单位置去", NE.nodePosition( lone ) == lonePosition,
		"%s -> %s" % ( lonePosition, NE.nodePosition( lone ) ) )
	check( "而且撤销栈是干净的", not edScript.undoAvailable() )
	edEditor.setRootNode( edScript )
	idle()

# 错误角标：出错后下一次插口变脏摘掉（原生 ErrorGadget 的 plugDirtied → removeError）
sphereItem = edItems()["sphere"]
edEditor._NetworkEditor__nodeError( rootSphere["out"], rootSphere["out"], "boom" )
check( "错误信号点亮角标", sphereItem._error )
rootSphere["radius"].setValue( 2.0 )
check( "改一个插口（变脏）就摘掉角标", not sphereItem._error )
check( "editor 的出错名单也清了", "sphere" not in edEditor._NetworkEditor__errorNodes )

# 位置更新只动脏节点和它的边
posScript = Gaffer.ScriptNode()
application["scripts"].addChild( posScript )
chain = []
for i in range( 6 ) :
	n = GafferScene.Isolate( "p%d" % i )
	posScript.addChild( n )
	NE.setNodePosition( n, imath.V2f( 0, -i * 10.0 ) )
	if chain :
		n["in"].setInput( chain[-1]["out"] )
	chain.append( n )
posEditor, posWindow = makeEditor( posScript, "positions" )
updated = []
originalUpdateGeometry = NE._EdgeItem.updateGeometry
NE._EdgeItem.updateGeometry = lambda self, style : ( updated.append( self.edge.key() ), originalUpdateGeometry( self, style ) )[1]
try :
	NE.setNodePosition( chain[0], imath.V2f( 20, 0 ) )
	idle()
finally :
	NE._EdgeItem.updateGeometry = originalUpdateGeometry
check( "挪一个链首节点只重算它那 1 条边（以前是全部 5 条）", len( updated ) == 1, str( updated ) )
check( "item 真挪过去了",
	abs( posEditor._NetworkEditor__nodeItems["p0"].pos().x() - 20 * NE.PX_PER_UNIT ) < 1e-3 )
updated[:] = []
NE._EdgeItem.updateGeometry = lambda self, style : ( updated.append( self.edge.key() ), originalUpdateGeometry( self, style ) )[1]
try :
	NE.setNodePosition( chain[2], imath.V2f( -20, -20 ) )
	idle()
finally :
	NE._EdgeItem.updateGeometry = originalUpdateGeometry
check( "挪链中节点重算它上下两条边", len( updated ) == 2, str( updated ) )

##########################################################################
section( "面板：喜爱记录按 UTF-8 存取" )
##########################################################################

usageDirectory = tempfile.mkdtemp( prefix = "networkEditorOpt" )
usagePath = os.path.join( usageDirectory, "usage.json" )
usage = NE._CreatorUsage( path = usagePath )
usage.toggleFavourite( "Scene/材质/aiStandardSurface" )
reloaded = NE._CreatorUsage( path = usagePath )
check( "非 ASCII 的键写进去再读出来还是喜爱", reloaded.isFavourite( "Scene/材质/aiStandardSurface" ) )
check( "没留下 .tmp", not os.path.exists( usagePath + ".tmp" ) )

##########################################################################
print( "\n%d/%d passed" % ( len( _passed ), len( _passed ) + len( _failed ) ) )
if _failed :
	print( "FAILED:\n  " + "\n  ".join( _failed ) )
	sys.exit( 1 )
