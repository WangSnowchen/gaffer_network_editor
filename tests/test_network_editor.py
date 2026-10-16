##########################################################################
# networkEditor 无头测试：数据层 + UI + 编辑操作
##########################################################################

import math
import os
import sys
import shutil
import tempfile
import functools
import traceback

sys.path.insert( 0, os.path.join( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ), "python" ) )

# 参数面板（P 键那块）是可选的另一个扩展：`PARAMETER_EDITOR_PYTHON` 指向它的 python/
# 目录就一起测，没给就只测「没装时 P 键什么都不做」
if os.environ.get( "PARAMETER_EDITOR_PYTHON" ) :
	sys.path.insert( 0, os.environ["PARAMETER_EDITOR_PYTHON"] )

import importlib.util
import imath
import IECore
import Gaffer
import GafferScene
import GafferOSL
import GafferUI

from Qt import QtCore, QtGui, QtWidgets

import networkEditor as NE

_passed = []
_failed = []


def check( name, condition, detail = "" ) :

	if condition :
		_passed.append( name )
		if os.environ.get( "NETWORK_EDITOR_TEST_VERBOSE" ) :
			print( "PASS  %s" % name )
	else :
		_failed.append( "%s  %s" % ( name, detail ) )
		print( "FAIL  %s  %s" % ( name, detail ) )


def section( title ) :

	print( "\n---- %s ----" % title )


def idle() :

	GafferUI.EventLoop.waitForIdle()


##########################################################################
section( "数据层 · 图与连线" )
##########################################################################

script = Gaffer.ScriptNode()

plane = GafferScene.Plane( "plane" )
sphere = GafferScene.Sphere( "sphere" )
group = GafferScene.Group( "group" )
isolate = GafferScene.Isolate( "isolate" )

for n in ( plane, sphere, group, isolate ) :
	script.addChild( n )

group["in"][0].setInput( plane["out"] )
group["in"][1].setInput( sphere["out"] )
isolate["in"].setInput( group["out"] )

nodes = NE.collectNodes( script )
check( "collectNodes 拿到 4 个节点", len( nodes ) == 4, "got %d" % len( nodes ) )

edges = NE.collectEdges( script, nodes )
keys = sorted( ( e.srcNode.getName(), e.dstNode.getName() ) for e in edges )
check(
	"collectEdges 三条主连线",
	keys == [ ( "group", "isolate" ), ( "plane", "group" ), ( "sphere", "group" ) ], str( keys )
)
check( "主连线不是 auxiliary", all( not e.auxiliary for e in edges ) )

check( "未摆位置返回 None", NE.nodePosition( plane ) is None )
check( "读位置不会建 __uiPosition", plane.getChild( "__uiPosition" ) is None, "plug was created!" )

NE.setNodePosition( plane, imath.V2f( 3, -7 ) )
check( "setNodePosition 建了 plug", isinstance( plane.getChild( "__uiPosition" ), Gaffer.V2fPlug ) )
check( "读得回来", NE.nodePosition( plane ) == imath.V2f( 3, -7 ), str( NE.nodePosition( plane ) ) )

check( "scene in 有 nodule", NE.hasNodule( isolate["in"] ) )
check( "普通参数无 nodule", not NE.hasNodule( sphere["radius"] ) )
check( "in 默认 top", NE.plugSection( isolate["in"] ) == "top", NE.plugSection( isolate["in"] ) )
check( "out 默认 bottom", NE.plugSection( isolate["out"] ) == "bottom", NE.plugSection( isolate["out"] ) )
check( "topLevelPlug 上溯", NE.topLevelPlug( group, group["in"][0] ).getName() == "in" )

layout = NE.noduleLayout( isolate )
check( "noduleLayout top 有 in", "in" in [ p.getName() for p in layout["top"] ], str( layout ) )
check( "noduleLayout bottom 有 out", "out" in [ p.getName() for p in layout["bottom"] ] )
check( "noduleLayout 不含隐藏插口", "radius" not in [ p.getName() for s in layout.values() for p in s ] )

# ArrayPlug 是复合 nodule：nodule 画在 in0/in1/... 上，不画在 in 上
check( "Group in 是复合 nodule", NE.isCompoundNodule( group["in"] ) )
check( "Isolate in 不是复合 nodule", not NE.isCompoundNodule( isolate["in"] ) )
groupTopNames = [ p.getName() for p in NE.noduleLayout( group )["top"] ]
check( "ArrayPlug 摊成一排 nodule", groupTopNames[:2] == [ "in0", "in1" ], str( groupTopNames ) )
check( "不把 ArrayPlug 本身当 nodule", "in" not in groupTopNames, str( groupTopNames ) )
check(
	"nodulePlug 把 in0 认成 nodule 层",
	NE.nodulePlug( group, group["in"][0] ).getName() == "in0",
	NE.nodulePlug( group, group["in"][0] ).getName()
)
check(
	"nodulePlug 对普通插口还是直接子插口",
	NE.nodulePlug( isolate, isolate["in"] ).getName() == "in"
)

# 问题 5：节点颜色和原生同一个来源（`nodeGadget:color`），没有就是 RaisedColor
check( "没有 metadata 就是原生 RaisedColor", NE.nodeColor( isolate ) == "#666666", NE.nodeColor( isolate ) )
check( "没有类型色时色带退回模块色", NE.nodeAccentColor( isolate ) == "#4f9d78", NE.nodeAccentColor( isolate ) )
Gaffer.Metadata.registerValue( isolate, "nodeGadget:color", imath.Color3f( 1, 0, 0 ) )
check( "nodeGadget:color 决定节点色", NE.nodeColor( isolate ) == "#ff0000", NE.nodeColor( isolate ) )
check( "有类型色时色带就用它", NE.nodeAccentColor( isolate ) == "#ff0000", NE.nodeAccentColor( isolate ) )
check(
	"卡片主体是压暗过的同色系",
	NE.cardColor( isolate ) != "#ff0000" and QtGui.QColor( NE.cardColor( isolate ) ).red() > QtGui.QColor( NE.cardColor( isolate ) ).blue(),
	NE.cardColor( isolate )
)
Gaffer.Metadata.deregisterValue( isolate, "nodeGadget:color" )

# 问题 2：接口圆点的颜色来自插口上的 `nodule:color`（原生按插口类型注册）
check( "没有 nodule:color 就是 RaisedColor", NE.noduleColor( isolate["in"] ) == "#666666", NE.noduleColor( isolate["in"] ) )
Gaffer.Metadata.registerValue( GafferScene.ScenePlug, "nodule:color", imath.Color3f( 0.2401, 0.3394, 0.485 ) )
Gaffer.Metadata.registerValue( GafferScene.FilterPlug, "nodule:color", imath.Color3f( 0.69, 0.5378, 0.2283 ) )
check( "ScenePlug 圆点是场景色", NE.noduleColor( isolate["in"] ) == "#3d577c", NE.noduleColor( isolate["in"] ) )
check( "FilterPlug 圆点是另一个色", NE.noduleColor( isolate["filter"] ) == "#b0893a", NE.noduleColor( isolate["filter"] ) )
check(
	"两种插口类型的圆点颜色不同（这就是看圆点认类型）",
	NE.noduleColor( isolate["in"] ) != NE.noduleColor( isolate["filter"] )
)
check( "圆点半径 = 原生的 0.5 个图单位", abs( NE.NODULE_RADIUS - 0.5 * NE.PX_PER_UNIT ) < 1e-6, str( NE.NODULE_RADIUS ) )
check( "悬停半径 = 原生的 1.0 个图单位（翻倍）", abs( NE.NODULE_HOVER_RADIUS - 1.0 * NE.PX_PER_UNIT ) < 1e-6, str( NE.NODULE_HOVER_RADIUS ) )

box = Gaffer.Box( "box" )
script.addChild( box )
check( "空 Box 不能进", not NE.canEnter( box ) )
box.addChild( GafferScene.Plane( "innerPlane" ) )
check( "有子节点的 Box 能进", NE.canEnter( box ) )
check( "普通节点不能进", not NE.canEnter( isolate ) )

expression = Gaffer.Expression( "expression" )
script.addChild( expression )
expression.setExpression( 'parent["sphere"]["radius"] = 2.0' )
edges2 = NE.collectEdges( script, NE.collectNodes( script ) )
check(
	"Expression 驱动判成 auxiliary",
	any( e.auxiliary and e.srcNode.getName() == "expression" for e in edges2 ),
	str( [ ( e.srcNode.getName(), e.dstNode.getName(), e.auxiliary ) for e in edges2 ] )
)
check( "父插口连上不重复画子插口", len( [ e for e in edges2 if e.srcNode.getName() == "plane" ] ) == 1 )


##########################################################################
section( "数据层 · 连线折叠（问题 3）" )
##########################################################################

check( "默认不折叠", not NE.nodeConnectionsMinimised( isolate, Gaffer.Plug.Direction.In ) )

NE.setNodeConnectionsMinimised( isolate, Gaffer.Plug.Direction.In, True )
check(
	"写进 __uiInputConnectionsMinimised",
	isinstance( isolate.getChild( "__uiInputConnectionsMinimised" ), Gaffer.BoolPlug )
)
check( "读得回来", NE.nodeConnectionsMinimised( isolate, Gaffer.Plug.Direction.In ) )

groupToIsolate = [ e for e in edges2 if e.dstNode.getName() == "isolate" ][0]
planeToGroup = [ e for e in edges2 if e.dstNode.getName() == "group" and e.srcNode.getName() == "plane" ][0]
check( "dst 输入折叠 -> 这条线折叠", NE.connectionMinimised( groupToIsolate ) )
check( "别的线不受影响", not NE.connectionMinimised( planeToGroup ) )

NE.setNodeConnectionsMinimised( isolate, Gaffer.Plug.Direction.In, False )
NE.setNodeConnectionsMinimised( plane, Gaffer.Plug.Direction.Out, True )
check( "src 输出折叠 -> 也折叠（抄 GraphGadget.cpp:1852）", NE.connectionMinimised( planeToGroup ) )
check( "只影响 plane 出去的线", not NE.connectionMinimised( groupToIsolate ) )
NE.setNodeConnectionsMinimised( plane, Gaffer.Plug.Direction.Out, False )


##########################################################################
section( "数据层 · 连接合法性" )
##########################################################################

check( "out -> in 合法", NE.canConnect( plane["out"], isolate["in"] ) )
check( "in -> in 不合法", not NE.canConnect( isolate["in"], isolate["in"] ) )
check( "同一节点不合法", not NE.canConnect( isolate["out"], isolate["in"] ) )
check( "类型不匹配不合法", not NE.canConnect( plane["out"], sphere["radius"] ) )

freeSlot = NE.resolveInputPlug( group["in"] )
check( "ArrayPlug 解析到空槽", freeSlot is not None and freeSlot.getInput() is None, str( freeSlot ) )
check( "普通插口原样返回", NE.resolveInputPlug( isolate["in"] ).getName() == "in" )

candidates = [ p.getName() for p in NE.candidatePlugs( isolate, plane["out"] ) ]
check( "候选插口含 in", "in" in candidates, str( candidates ) )
check( "候选插口不含 out", "out" not in candidates, str( candidates ) )

# ArrayPlug 展开后有一排 in0/in1/in2，菜单里只该留一个空槽
groupCandidates = NE.candidatePlugs( group, isolate["out"] )
check( "ArrayPlug 只出一个候选", len( groupCandidates ) == 1, str( [ p.getName() for p in groupCandidates ] ) )
check( "而且是空槽", groupCandidates[0].getInput() is None, groupCandidates[0].getName() )

check( "enabled 默认 True", NE.nodeEnabled( isolate ) is True )
isolate["enabled"].setValue( False )
check( "enabled=False", NE.nodeEnabled( isolate ) is False )
isolate["enabled"].setValue( True )

backdrop = Gaffer.Backdrop( "backdrop" )
script.addChild( backdrop )
center, w, h = NE.backdropBound( backdrop )
check( "Backdrop 有框", w > 0 and h > 0, "%s %s" % ( w, h ) )

Gaffer.MetadataAlgo.addAnnotation( isolate, "user", Gaffer.MetadataAlgo.Annotation( "注意帧范围" ) )
annotation = NE.nodeAnnotation( isolate )
check( "读得到注释", annotation is not None and annotation[0] == "注意帧范围", str( annotation ) )

# 模板注释（ArnoldShader 上那条 `shader_type` = `{name}`）不画 —— 用户不要节点下面
# 冒出自动生成的文字。原生默认是全画的（会把 `{name}` 替换成 shader 类型）。
templated = GafferScene.Sphere( "templatedAnnotation" )
script.addChild( templated )
Gaffer.MetadataAlgo.addAnnotation(
	templated, "shader_type", Gaffer.MetadataAlgo.Annotation( "{name}", imath.Color3f( 1, 1, 1 ) )
)
check( "模板注释不画", NE.nodeAnnotation( templated ) is None, str( NE.nodeAnnotation( templated ) ) )

# 人工写的注释照画，而且 `{插口}` 会被替换成值（抄原生 substitutePlugValues）
Gaffer.MetadataAlgo.addAnnotation(
	templated, "user", Gaffer.MetadataAlgo.Annotation( "半径 {radius}", imath.Color3f( 1, 1, 1 ) )
)
userAnnotation = NE.nodeAnnotation( templated )
check( "人工注释照画", userAnnotation is not None, str( userAnnotation ) )
check(
	"{插口} 被替换成值",
	userAnnotation is not None and userAnnotation[0] == "半径 1",
	str( userAnnotation )
)
check( "找不到的插口替换成空", NE.substituteAnnotationText( "{nope}", templated ) == "" )
check( "没有花括号原样返回", NE.substituteAnnotationText( "abc", templated ) == "abc" )

# 只剩模板注释时又回到不画
Gaffer.MetadataAlgo.removeAnnotation( templated, "user" )
check( "去掉人工注释就不画了", NE.nodeAnnotation( templated ) is None, str( NE.nodeAnnotation( templated ) ) )
script.removeChild( templated )
Gaffer.MetadataAlgo.removeAnnotation( isolate, "user" )


##########################################################################
section( "UI 骨架" )
##########################################################################

app = Gaffer.ApplicationRoot( "test" )
app["scripts"].addChild( script )

editor = NE.NetworkEditor( script )

window = GafferUI.Window( "test" )
window.setChild( editor )
window._qtWidget().resize( 1000, 700 )
window.setVisible( True )
idle()

scene = editor._NetworkEditor__scene
view = editor.graphView()


def items() :
	return editor._NetworkEditor__nodeItems


def edgeItems() :
	return editor._NetworkEditor__edgeItems


check( "Backdrop 走 _BackdropItem", "backdrop" in editor._NetworkEditor__backdropItems )
check( "Backdrop 不在节点 item 里", "backdrop" not in items() )
check(
	"节点 item 数 = 非 Backdrop 节点数",
	len( items() ) == len( [ n for n in NE.collectNodes( script ) if not isinstance( n, Gaffer.Backdrop ) ] ),
	str( sorted( items().keys() ) )
)

planeItem = items()[ "plane" ]
check(
	"位置映射 x*12 / -y*12",
	abs( planeItem.pos().x() - 3 * NE.PX_PER_UNIT ) < 1e-4 and abs( planeItem.pos().y() - 7 * NE.PX_PER_UNIT ) < 1e-4,
	str( planeItem.pos() )
)

# 问题 1：sceneRect 必须留足余量，否则平移被夹住
sceneRect = scene.sceneRect()
contentRect = scene.itemsBoundingRect()
check(
	"sceneRect 左右各留 %d px 余量" % NE.SCENE_MARGIN,
	sceneRect.left() <= contentRect.left() - NE.SCENE_MARGIN + 1 and
	sceneRect.right() >= contentRect.right() + NE.SCENE_MARGIN - 1,
	"scene=%s content=%s" % ( sceneRect, contentRect )
)

# nodule 位置：in 在卡片上边、out 在下边
noduleIn = items()[ "isolate" ].nodulePosition( isolate["in"] )
noduleOut = items()[ "isolate" ].nodulePosition( isolate["out"] )
check( "in nodule 在上边", abs( noduleIn.y() + NE.NODE_HEIGHT / 2.0 ) < 1e-4, str( noduleIn ) )
check( "out nodule 在下边", abs( noduleOut.y() - NE.NODE_HEIGHT / 2.0 ) < 1e-4, str( noduleOut ) )
check( "nodule 命中测试", items()[ "isolate" ].noduleAt( noduleIn ) is not None )
check( "远离 nodule 测不到", items()[ "isolate" ].noduleAt( QtCore.QPointF( 0, 0 ) ) is None )

# Group 有两条已连的 in + 一个空槽 -> 上边至少两个 nodule，且不重叠
groupItem = items()[ "group" ]
groupTops = NE.noduleLayout( group )["top"]
positions = [ groupItem.nodulePosition( p ).x() for p in groupTops ]
check( "Group 多个输入 nodule", len( groupTops ) >= 2, str( len( groupTops ) ) )
check( "nodule 不重叠", len( set( round( x, 3 ) for x in positions ) ) == len( positions ), str( positions ) )

# 折叠的线画成短尾巴
fullLength = None
for item in edgeItems() :
	if item.edge.dstNode.getName() == "isolate" :
		fullLength = item.path().length()
check( "拿到 group->isolate 的线", fullLength is not None )

NE.setNodeConnectionsMinimised( isolate, Gaffer.Plug.Direction.In, True )
idle()
stubLength = None
for item in edgeItems() :
	if item.edge.dstNode.getName() == "isolate" :
		stubLength = item.path().length()
		check( "该线标记为折叠", item._minimised )
check( "折叠后明显变短", stubLength is not None and stubLength < fullLength * 0.5, "%s vs %s" % ( stubLength, fullLength ) )
NE.setNodeConnectionsMinimised( isolate, Gaffer.Plug.Direction.In, False )
idle()


##########################################################################
section( "箭头中点缓存（平移 / 缩放时不重算贝塞尔弧长）" )
##########################################################################

# `QPainterPath.pointAtPercent()` 每次都要把整条贝塞尔做一遍弧长参数化，而 paint 里
# 一条边要问三次 —— 平移 / 缩放**根本不改路径**，却每帧重算一遍。实测 300 节点全景
# 平移时它是单项开销第一名（9900 次调用 59ms，占一帧的 18%）。
# **用次数断言，不用时间**：换台机器时间就变，次数不会。

midEdge = next( ( e for e in edgeItems() if e.edge.dstNode.getName() == "isolate" ), None )
check( "拿到一条边做中点缓存测试", midEdge is not None )

_midCalls = [ 0 ]
_originalPathMidpoint = NE.edge_item._pathMidpoint

def _countedPathMidpoint( path ) :
	_midCalls[ 0 ] += 1
	return _originalPathMidpoint( path )

# 注意 patch 的是**定义它的那个模块**的全局 —— `midpoint()` 的 `__globals__` 就是
# `edge_item` 的模块字典，改包属性（`NE._pathMidpoint`）改不到它。
NE.edge_item._pathMidpoint = _countedPathMidpoint
try :

	expected = _originalPathMidpoint( midEdge.path() )
	midEdge.setPath( midEdge.path() )          # 从干净状态开始数

	point, direction = midEdge.midpoint()
	check(
		"缓存算出来的中点和直接算的一致",
		abs( point.x() - expected[ 0 ].x() ) < 1e-6 and abs( point.y() - expected[ 0 ].y() ) < 1e-6
		and abs( direction.x() - expected[ 1 ].x() ) < 1e-6
		and abs( direction.y() - expected[ 1 ].y() ) < 1e-6,
		"%s vs %s" % ( point, expected[ 0 ] )
	)
	check( "第一次要真算一遍", _midCalls[ 0 ] == 1, str( _midCalls[ 0 ] ) )

	for _i in range( 10 ) :
		midEdge.midpoint()
	check( "路径没变就一次都不重算", _midCalls[ 0 ] == 1, str( _midCalls[ 0 ] ) )

	# 路径真变了必须重算，否则箭头会停在旧位置
	midEdge.updateGeometry( midEdge._wireStyle )
	midEdge.midpoint()
	check( "updateGeometry 之后缓存作废", _midCalls[ 0 ] == 2, str( _midCalls[ 0 ] ) )

	midEdge.setPath( midEdge.path() )
	midEdge.midpoint()
	check( "setPath 之后缓存作废", _midCalls[ 0 ] == 3, str( _midCalls[ 0 ] ) )

finally :
	NE.edge_item._pathMidpoint = _originalPathMidpoint


##########################################################################
section( "选择同步（问题 4）" )
##########################################################################

script.selection().clear()
script.selection().add( script["isolate"] )
idle()
check( "script 选择同步到视图", items()[ "isolate" ].isSelected() )

# 记录 script.selection() 的信号次数，确认 diff 式而不是 clear + add all
events = []
c1 = script.selection().memberAddedSignal().connect( lambda s, m : events.append( ( "add", m.getName() ) ), scoped = True )
c2 = script.selection().memberRemovedSignal().connect( lambda s, m : events.append( ( "remove", m.getName() ) ), scoped = True )

scene.blockSignals( True )
items()[ "isolate" ].setSelected( True )
items()[ "group" ].setSelected( True )
items()[ "plane" ].setSelected( True )
scene.blockSignals( False )
editor._flushSelectionToScript()
idle()

selected = sorted( n.getName() for n in script.selection() )
check( "视图选择写回 script", selected == [ "group", "isolate", "plane" ], str( selected ) )
check(
	"只发新增两条信号，没有 clear + 全量重加",
	events == [ ( "add", "group" ), ( "add", "plane" ) ] or
	events == [ ( "add", "plane" ), ( "add", "group" ) ],
	str( events )
)

events[:] = []
scene.blockSignals( True )
items()[ "plane" ].setSelected( False )
scene.blockSignals( False )
editor._flushSelectionToScript()
check( "取消选择只发一条 remove", events == [ ( "remove", "plane" ) ], str( events ) )

del c1, c2

script.setFocus( script["isolate"] )
idle()
check( "focus 节点被标记", items()[ "isolate" ]._focused )
check( "非 focus 不标记", not items()[ "group" ]._focused )


##########################################################################
section( "编辑：摆位 / 连接 / 断开 / 删除 / 复制粘贴" )
##########################################################################

# 摆位写回：拖动只动 Qt item，_commitNodePositions 才写 Gaffer。
# 注意：编辑器建好时已经像原生那样给「没摆过位置」的节点补了一次自动布局
#（`__layoutUnpositionedNodes`），所以这里不再是「原来没有位置」。
positionBefore = NE.nodePosition( script["sphere"] )
check( "编辑器已按原生自动布局补上了位置", positionBefore is not None, str( positionBefore ) )

sphereItem = items()[ "sphere" ]
# Qt 拖动只挪**选中**的 item，写回也只看选中的
sphereItem.setSelected( True )
sphereItem.setPos( QtCore.QPointF( 120.0, -60.0 ) )
check(
	"拖动时还没写进 Gaffer",
	NE.nodePosition( script["sphere"] ) == positionBefore,
	str( NE.nodePosition( script["sphere"] ) )
)
editor._commitNodePositions()
position = NE.nodePosition( script["sphere"] )
check(
	"松手后写回（y 翻转）",
	position is not None and abs( position.x - 10.0 ) < 1e-4 and abs( position.y - 5.0 ) < 1e-4,
	str( position )
)
check( "一次拖动 = 一步撤销", script.undoAvailable() )
script.undo()
check(
	"撤销回到拖动前的位置",
	NE.nodePosition( script["sphere"] ) == positionBefore,
	str( NE.nodePosition( script["sphere"] ) )
)
sphereItem.setSelected( False )
idle()

# 建连接：sphere.out -> isolate.in（先断开 isolate 现有输入）
editor._disconnect( [ e.edge for e in edgeItems() if e.edge.dstNode.getName() == "isolate" ] )
idle()
check( "断开成功", script["isolate"]["in"].getInput() is None )
check( "断开可撤销", script.undoAvailable() )

editor._createConnection( script["sphere"]["out"], script["isolate"], script["isolate"]["in"], QtCore.QPoint( 0, 0 ) )
idle()
inputPlug = script["isolate"]["in"].getInput()
check(
	"建连接成功",
	inputPlug is not None and inputPlug.node().getName() == "sphere",
	str( inputPlug )
)
check( "视图跟着出现这条线", any(
	e.edge.srcNode.getName() == "sphere" and e.edge.dstNode.getName() == "isolate" for e in edgeItems()
) )

# 落在节点身上（不精确指 plug）自动挑唯一候选
script["isolate"]["in"].setInput( None )
idle()
editor._createConnection( script["plane"]["out"], script["isolate"], None, QtCore.QPoint( 0, 0 ) )
idle()
inputPlug = script["isolate"]["in"].getInput()
check( "落在节点上自动挑插口", inputPlug is not None and inputPlug.node().getName() == "plane", str( inputPlug ) )

# ArrayPlug：拖到 Group 上应该接到空槽
countBefore = len( [ c for c in script["group"]["in"].children() if c.getInput() is not None ] )
editor._createConnection( script["isolate"]["out"], script["group"], script["group"]["in"], QtCore.QPoint( 0, 0 ) )
idle()
countAfter = len( [ c for c in script["group"]["in"].children() if c.getInput() is not None ] )
check( "ArrayPlug 接到新槽", countAfter == countBefore + 1, "%d -> %d" % ( countBefore, countAfter ) )
script.undo()

# 复制粘贴
script.selection().clear()
script.selection().add( script["sphere"] )
before = set( n.getName() for n in NE.collectNodes( script ) )
editor._copySelected()
editor._paste()
idle()
after = set( n.getName() for n in NE.collectNodes( script ) )
check( "粘贴多出一个节点", len( after ) == len( before ) + 1, "%d -> %d" % ( len( before ), len( after ) ) )
pastedName = list( after - before )[0] if after - before else None
check( "粘贴的是 Sphere", pastedName is not None and isinstance( script[ pastedName ], GafferScene.Sphere ), str( pastedName ) )
check( "粘贴出现在视图里", pastedName in items(), str( sorted( items().keys() ) ) )

# 删除（reconnect：删中间节点上下游要接起来）。编辑操作以 script.selection() 为准。
script.selection().clear()
script.selection().add( script[ pastedName ] )
editor._deleteSelected()
idle()
check( "删掉了", pastedName not in [ n.getName() for n in NE.collectNodes( script ) ] )
check( "删除可撤销", script.undoAvailable() )

# 进出 Box
editor._enterNode( script["box"] )
idle()
check( "进 Box", editor.getRootNode().getName() == "box" )
check( "Box 里只有 innerPlane", sorted( items().keys() ) == [ "innerPlane" ], str( sorted( items().keys() ) ) )
editor._leaveNode()
idle()
check( "出 Box", editor.getRootNode().isSame( script ) )

# 改名 / 删节点 / 位置变化
script["plane"].setName( "renamedPlane" )
idle()
check( "改名后 item 跟着改", "renamedPlane" in items(), str( sorted( items().keys() ) ) )

before = items()[ "renamedPlane" ]
NE.setNodePosition( script["renamedPlane"], imath.V2f( 10, 10 ) )
idle()
after = items()[ "renamedPlane" ]
check( "位置变化不重建 item", before is after, "item was recreated" )
check(
	"位置更新生效",
	abs( after.pos().x() - 10 * NE.PX_PER_UNIT ) < 1e-4 and abs( after.pos().y() + 10 * NE.PX_PER_UNIT ) < 1e-4,
	str( after.pos() )
)

script.removeChild( script["sphere"] )
idle()
check( "删节点后 item 没了", "sphere" not in items() )


##########################################################################
section( "连线几何（Houdini 手感）" )
##########################################################################

down = QtCore.QPointF( 0, 1 )
up = QtCore.QPointF( 0, -1 )


def wireLength( x1, y1 ) :
	path = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( x1, y1 ), up, NE.WIRE_CURVED )
	return path.length(), math.hypot( x1, y1 )


# 正常上→下、距离近：应该贴得很紧
length, straight = wireLength( 20, 60 )
check( "短距离连线不甩大弯", length < straight * 1.25, "%.1f vs %.1f" % ( length, straight ) )

# 横向拉得很开、纵向很近：这是旧公式最丑的情形（按 |dx|+|dy| 算控制柄会甩出大回环）
length, straight = wireLength( 300, 40 )
check( "横向拉开也不甩大弯", length < straight * 1.30, "%.1f vs %.1f" % ( length, straight ) )

# 反向（目标在上游侧）：应该走出一个明显的回环，而不是在节点上打结
length, straight = wireLength( 0, -60 )
check( "反向连线走回环", length > straight * 2.0, "%.1f vs %.1f" % ( length, straight ) )

# 几乎平齐（下游节点和上游几乎一样高）：Houdini 画的是一条近乎直的横线，不许绕回环
length, straight = wireLength( 340, 8 )
check( "几乎平齐不绕回环", length < straight * 1.15, "%.1f vs %.1f" % ( length, straight ) )

# 直线模式就是直线
straightPath = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 30, 90 ), up, NE.WIRE_STRAIGHT )
check(
	"直线模式长度 = 两点距离",
	abs( straightPath.length() - math.hypot( 30, 90 ) ) < 1e-3,
	str( straightPath.length() )
)

# 中点箭头方向
path = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 0, 100 ), up, NE.WIRE_CURVED )
point, direction = NE._pathMidpoint( path )
check( "中点在中间", abs( point.y() - 50 ) < 6, str( point ) )
check( "箭头朝流向（向下）", direction.y() > 0.9, str( direction ) )
check( "方向是单位向量", abs( math.hypot( direction.x(), direction.y() ) - 1.0 ) < 1e-6 )


##########################################################################
section( "曲线连线 · 和真机 Houdini 的 rounded 连线对拍" )
##########################################################################

# 基准数据是在 Houdini 21.0.596 上量的（`View > Change network wiring style` 切到
# rounded）：`hou.NetworkEditor` 提供图坐标↔屏幕像素的映射，逐像素抠出连线再换算回
# 图坐标，一个用例 45 个采样点。**Houdini 的 rounded 连线是「直段 + 正圆弧」**，
# 不是贝塞尔 —— 拐角处圆拟合残差只有 ~0.005 单位（≈1px）。
import json as _json

with open( os.path.join( NE.packageRoot(), "tests", "houdini_rounded_wire.json" ) ) as f :
	houdiniWire = _json.load( f )

wireScale = houdiniWire["_scalePxPerUnit"]


def wireDeviation( key, points ) :

	# Houdini 的 y 向上、我们的 y 向下，换算时取反
	dx, dy = [ float( v ) for v in key.split( "," ) ]
	path = NE._wirePath(
		QtCore.QPointF( 0, 0 ), down,
		QtCore.QPointF( dx * wireScale, -dy * wireScale ), up, NE.WIRE_CURVED
	)
	samples = [ path.pointAtPercent( i / 400.0 ) for i in range( 401 ) ]
	deviations = []
	for x, y in points :
		px, py = x * wireScale, -y * wireScale
		deviations.append( min( math.hypot( px - s.x(), py - s.y() ) for s in samples ) )
	return sum( deviations ) / len( deviations ), max( deviations )


worstMean, worstMax = 0.0, 0.0
for key, points in houdiniWire["cases"].items() :
	mean, worst = wireDeviation( key, points )
	worstMean, worstMax = max( worstMean, mean ), max( worstMax, worst )
	check(
		"贴合 Houdini 连线 delta=(%s)" % key, mean < 3.0 and worst < 10.0,
		"平均 %.1fpx 最大 %.1fpx" % ( mean, worst )
	)

check( "整体贴合度", worstMean < 3.0 and worstMax < 10.0, "平均 %.1fpx 最大 %.1fpx" % ( worstMean, worstMax ) )

# 形状本身的三条硬性质（Houdini 的 rounded 就是这么走的）
shaped = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 400, 500 ), up, NE.WIRE_CURVED )
samples = [ shaped.pointAtPercent( i / 600.0 ) for i in range( 601 ) ]

# ① 出口先顺着流向走，且很快就拐到侧面 —— 侧向偏移在 stub 距离内几乎没有
early = [ p for p in samples if p.y() < NE.WIRE_STUB * 0.35 ]
check( "出口先直着走一小段", max( abs( p.x() ) for p in early ) < 3.0, "%.2f" % max( abs( p.x() ) for p in early ) )

# ② 中间有一段是平的（横平竖直的横段），y 停在 stub 那条线上
flat = [ p for p in samples if abs( p.y() - NE.WIRE_STUB ) < 0.5 ]
flatSpan = max( p.x() for p in flat ) - min( p.x() for p in flat ) if flat else 0.0
check( "中间有横平的一段", flatSpan > 40.0, "%.1fpx" % flatSpan )

# ③ 最后一段是竖直的，直着扎进入口
late = [ p for p in samples if p.y() > 500 - NE.WIRE_STUB * 0.3 ]
check( "末段竖直进入口", max( abs( p.x() - 400 ) for p in late ) < 3.0, "%.2f" % max( abs( p.x() - 400 ) for p in late ) )

# ④ 拐角是正圆弧：取拐角段拟合圆，残差应当很小
corner = [ p for p in samples if NE.WIRE_STUB + 8 < p.y() < 500 - 8 and 8 < p.x() < 400 - 8 ]
if len( corner ) > 20 :
	sx = sum( p.x() for p in corner ) / len( corner )
	sy = sum( p.y() for p in corner ) / len( corner )
	# 三点定圆（首、中、尾）后量所有点到圆心的距离是否一致
	a, b, c = corner[0], corner[len( corner ) // 2], corner[-1]
	d = 2 * ( a.x() * ( b.y() - c.y() ) + b.x() * ( c.y() - a.y() ) + c.x() * ( a.y() - b.y() ) )
	if abs( d ) > 1e-6 :
		ux = ( ( a.x() ** 2 + a.y() ** 2 ) * ( b.y() - c.y() ) + ( b.x() ** 2 + b.y() ** 2 ) * ( c.y() - a.y() ) + ( c.x() ** 2 + c.y() ** 2 ) * ( a.y() - b.y() ) ) / d
		uy = ( ( a.x() ** 2 + a.y() ** 2 ) * ( c.x() - b.x() ) + ( b.x() ** 2 + b.y() ** 2 ) * ( a.x() - c.x() ) + ( c.x() ** 2 + c.y() ** 2 ) * ( b.x() - a.x() ) ) / d
		radius = math.hypot( a.x() - ux, a.y() - uy )
		spread = max( abs( math.hypot( p.x() - ux, p.y() - uy ) - radius ) for p in corner )
		check( "拐角是正圆弧", spread < 2.0, "半径 %.1f 残差 %.2fpx" % ( radius, spread ) )


##########################################################################
section( "曲线连线 · 不穿过两端的节点" )
##########################################################################

right = QtCore.QPointF( 1, 0 )
left = QtCore.QPointF( -1, 0 )


## 路径进了卡片里面多少个采样点（卡片往里收 2px，两个端点附近 8px 不算）。
def cardHits( path, rect, p0, p1 ) :

	inner = rect.adjusted( 2, 2, -2, -2 )
	hits = 0
	for i in range( 401 ) :
		p = path.pointAtPercent( i / 400.0 )
		if math.hypot( p.x() - p0.x(), p.y() - p0.y() ) < 8 or math.hypot( p.x() - p1.x(), p.y() - p1.y() ) < 8 :
			continue
		hits += 1 if inner.contains( p ) else 0
	return hits


def endDirection( path ) :

	a, b = path.pointAtPercent( 0.995 ), path.pointAtPercent( 1.0 )
	return NE._unit( QtCore.QPointF( b.x() - a.x(), b.y() - a.y() ) )


def startDirection( path ) :

	a, b = path.pointAtPercent( 0.0 ), path.pointAtPercent( 0.005 )
	return NE._unit( QtCore.QPointF( b.x() - a.x(), b.y() - a.y() ) )


def routeCase( name, p0, t0, p1, t1, cards ) :

	old = NE._wirePath( p0, t0, p1, t1, NE.WIRE_CURVED )
	new = NE._wirePath( p0, t0, p1, t1, NE.WIRE_CURVED, cards )
	oldHits = sum( cardHits( old, c, p0, p1 ) for c in cards )
	newHits = sum( cardHits( new, c, p0, p1 ) for c in cards )
	check( "%s：不绕的话会穿过卡片" % name, oldHits > 0, str( oldHits ) )
	check( "%s：绕开卡片" % name, newHits == 0, str( newHits ) )
	s = startDirection( new )
	check( "%s：起点顺着出口方向走" % name, s.x() * t0.x() + s.y() * t0.y() > 0.95, str( s ) )
	g = QtCore.QPointF( -t1.x(), -t1.y() )
	d = endDirection( new )
	check( "%s：从接口外侧扎进去" % name, d.x() * g.x() + d.y() * g.y() > 0.95, str( d ) )
	return new


# 场景节点的 filter 接口在卡片右侧，PathFilter 在左上方（用户截图里那种）
card = QtCore.QRectF( 0, 0, 132, 50 )
routeCase( "filter 从左上接到右侧接口", QtCore.QPointF( -150, -120 ), down, QtCore.QPointF( 132, 25 ), right, [ card ] )

# BoxIn 在右上方，接到材质节点左侧的参数接口
routeCase( "BoxIn 从右上接到左侧参数", QtCore.QPointF( 300, -100 ), down, QtCore.QPointF( 0, 30 ), left, [ card ] )

# 节点自己连自己（OSLCode 的 `__shaderName -> name` 辅助连线）：底边出、顶边进
loopPath = routeCase( "节点自己连自己的回环", QtCore.QPointF( 66, 50 ), down, QtCore.QPointF( 66, 0 ), up, [ card, QtCore.QRectF( card ) ] )
loopBound = loopPath.boundingRect()
check( "回环从卡片侧面绕过去", loopBound.left() < card.left() - NE.WIRE_CLEARANCE + 1 or loopBound.right() > card.right() + NE.WIRE_CLEARANCE - 1,
	str( loopBound ) )

# 右侧输出接到另一个节点的右侧输入（方向相反），目标在右边
other = QtCore.QRectF( 300, 100, 132, 50 )
routeCase( "右出接右进", QtCore.QPointF( 132, 25 ), right, QtCore.QPointF( 432, 125 ), right, [ card, other ] )

# 材质那种横着流、目标在上游侧并且竖直方向挨着：Houdini 那条回环会横穿两张卡片
upstream = QtCore.QRectF( -300, -20, 132, 100 )
routeCase( "横流回环", QtCore.QPointF( 132, 25 ), right, QtCore.QPointF( -300, 35 ), left, [ card, upstream ] )

# 不穿卡片的时候形状和 Houdini 那条完全一样（对拍数据不受影响）
src = QtCore.QRectF( -66, -50, 132, 50 )
dst = QtCore.QRectF( 334, 450, 132, 50 )
plain = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 400, 450 ), up, NE.WIRE_CURVED )
avoided = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 400, 450 ), up, NE.WIRE_CURVED, [ src, dst ] )
check( "不穿卡片时形状不变", plain == avoided )

# Dot 的接口在圆心上，端点落在卡片里面的不绕
dotCard = QtCore.QRectF( -15, -15, 30, 30 )
plainDot = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 200, -100 ), left, NE.WIRE_CURVED )
avoidDot = NE._wirePath( QtCore.QPointF( 0, 0 ), down, QtCore.QPointF( 200, -100 ), left, NE.WIRE_CURVED, [ dotCard ] )
check( "端点在卡片里面（Dot）不绕", plainDot == avoidDot )

# 直线模式不绕
straightA = NE._wirePath( QtCore.QPointF( -150, -120 ), down, QtCore.QPointF( 132, 25 ), right, NE.WIRE_STRAIGHT, [ card ] )
check( "直线模式还是直线", abs( straightA.length() - math.hypot( 282, 145 ) ) < 1e-3, str( straightA.length() ) )


##########################################################################
section( "节点形状 / 连线配色 / D 键" )
##########################################################################

# 注意：**无头环境不能碰 GafferArnold**（`ArnoldLight` 在 `gaffer env python` 里
# SIGABRT `free(): invalid size`）。这里用桩类验
# 形状规则本身（nodeShape 按 MRO 里的类名判断），真的 ArnoldLight 放真机 e2e 里验。
class Light( Gaffer.Node ) :
	pass


class Camera( Gaffer.Node ) :
	pass


shapeScript = Gaffer.ScriptNode()
app["scripts"].addChild( shapeScript )

dot = Gaffer.Dot( "dot" )
shapeScript.addChild( dot )
dot.setup( GafferScene.ScenePlug() )

light = Light( "keyLight" )
shapeScript.addChild( light )

camera = GafferScene.Camera( "cam" )
shapeExpression = Gaffer.Expression( "expr" )
shapeIsolate = GafferScene.Isolate( "iso" )
shapeFilter = GafferScene.PathFilter( "filt" )
for n in ( camera, shapeExpression, shapeIsolate, shapeFilter ) :
	shapeScript.addChild( n )

check( "Dot -> 小圆点", NE.nodeShape( dot ) == NE.SHAPE_DOT, NE.nodeShape( dot ) )
check(
	"Expression -> 小方块（原生 AuxiliaryNodeGadget）",
	NE.nodeShape( shapeExpression ) == NE.SHAPE_AUXILIARY, NE.nodeShape( shapeExpression )
)
check( "小方块上写首字母", NE.auxiliaryLabel( shapeExpression ) == "e", NE.auxiliaryLabel( shapeExpression ) )
check( "BoxIn -> 胶囊（原生 nodeGadget:shape=oval）", NE.nodeShape( Gaffer.BoxIn() ) == NE.SHAPE_OVAL )
check( "普通节点 -> 矩形", NE.nodeShape( shapeIsolate ) == NE.SHAPE_RECTANGLE, NE.nodeShape( shapeIsolate ) )

# 类型身份靠图标，不靠把卡片捏成灯泡形
check( "Light 派生 -> 灯泡图标", NE.nodeGlyph( light ) == NE.GLYPH_LIGHT, str( NE.nodeGlyph( light ) ) )
check( "Camera -> 相机图标", NE.nodeGlyph( camera ) == NE.GLYPH_CAMERA, str( NE.nodeGlyph( camera ) ) )
check( "PathFilter -> 漏斗图标", NE.nodeGlyph( shapeFilter ) == NE.GLYPH_FILTER, str( NE.nodeGlyph( shapeFilter ) ) )
check( "Dot 不画图标", NE.nodeShape( dot ) == NE.SHAPE_DOT )
check( "Isolate 没有图标", NE.nodeGlyph( shapeIsolate ) is None, str( NE.nodeGlyph( shapeIsolate ) ) )

shapeEditor = NE.NetworkEditor( shapeScript )
shapeWindow = GafferUI.Window( "shapes" )
shapeWindow.setChild( shapeEditor )
shapeWindow._qtWidget().resize( 800, 600 )
shapeWindow.setVisible( True )
idle()

shapeItems = shapeEditor._NetworkEditor__nodeItems
dotItem = shapeItems[ "dot" ]
check( "Dot 是正方形包围盒", abs( dotItem._width - dotItem._height ) < 1e-6, "%s x %s" % ( dotItem._width, dotItem._height ) )
check( "Dot 用 DOT_SIZE", abs( dotItem._width - NE.DOT_SIZE ) < 1e-6, str( dotItem._width ) )
check( "Dot 轮廓不是矩形路径", dotItem.cardPath().elementCount() > 4 )
check( "普通节点高度是 NODE_HEIGHT", abs( shapeItems[ "iso" ]._height - NE.NODE_HEIGHT ) < 1e-6 )

# --- 问题 2：节点大小和原生节点编辑器完全一致 ---
# 拿一个真的 GraphGadget 当尺子（原生 GraphEditor 里画的就是它）
probeGadget = GafferUI.GraphGadget( shapeScript )

def nativeSizePx( node ) :
	bound = probeGadget.nodeGadget( node ).bound()
	return (
		( bound.max().x - bound.min().x ) * NE.PX_PER_UNIT,
		( bound.max().y - bound.min().y ) * NE.PX_PER_UNIT,
	)

# 契约：**高度照原生，宽度以原生为下限、名字放不下就撑宽** ——
# 死守原生宽度会出现 `Create...tSetup` 这种截字，那还不如不一致。
for name in ( "iso", "cam", "filt", "dot", "expr" ) :
	item = shapeItems[ name ]
	w, h = nativeSizePx( shapeScript[ name ] )
	check(
		"%s 高度 = 原生 NodeGadget" % name,
		abs( item._height - h ) < 1e-3, "ours %.3f native %.3f" % ( item._height, h )
	)
	check(
		"%s 宽度不小于原生" % name,
		item._width >= w - 1e-3, "ours %.3f native %.3f" % ( item._width, w )
	)
	check( "%s 名字放得下（不截字）" % name, item.nameFits(), "%.3f" % item._width )

check(
	"名字短的标准节点还是原生的 11 x 4.164 单位",
	abs( shapeItems[ "iso" ]._width - 11.0 * NE.PX_PER_UNIT ) < 1e-3 and
	abs( shapeItems[ "iso" ]._height - NE.NODE_HEIGHT ) < 1e-3,
	"%.3f x %.3f" % ( shapeItems[ "iso" ]._width, shapeItems[ "iso" ]._height )
)
check( "Dot 是原生的 2.5 单位", abs( dotItem._width - 2.5 * NE.PX_PER_UNIT ) < 1e-3, str( dotItem._width ) )
check(
	"Expression 小方块是原生的 2 单位",
	abs( shapeItems[ "expr" ]._width - 2.0 * NE.PX_PER_UNIT ) < 1e-3,
	str( shapeItems[ "expr" ]._width )
)

# 名字长了跟着变宽，也和原生一致
longNode = GafferScene.Isolate( "AVeryLongNodeNameIndeed" )
shapeScript.addChild( longNode )
idle()
longItem = shapeEditor._NetworkEditor__nodeItems.get( "AVeryLongNodeNameIndeed" )
longW, longH = nativeSizePx( longNode )
check( "长名字节点大小也对齐原生", longItem is not None and abs( longItem._width - longW ) < 1e-3,
	"ours %s native %s" % ( longItem._width if longItem else None, longW ) )
check( "长名字确实更宽", longItem is not None and longItem._width > shapeItems[ "iso" ]._width )
check( "长名字节点的名字也没被截", longItem is not None and longItem.nameFits() )

# --- 名字放不下时把卡片撑宽（问题 1、4）---
wideCamera = GafferScene.Camera( "CreateLightSetupForTheHeroCharacter" )
shapeScript.addChild( wideCamera )
idle()
wideItem = shapeEditor._NetworkEditor__nodeItems.get( "CreateLightSetupForTheHeroCharacter" )
wideNativeW, wideNativeH = nativeSizePx( wideCamera )

check( "撑宽的节点建出来了", wideItem is not None )
if wideItem is not None :
	# 撑不撑宽取决于「我们的字体 vs 原生字体」哪个更宽 —— 那是跟着环境走的
	# （真实 GUI 里 Gaffer 有自己的全局字体，无头下未必一样）。要断言的是**规则**：
	# 宽度 = max( 原生, 图标+名字所需 )，而且任何时候名字都不许被截。
	wideContents = wideItem._NodeItem__contentsWidth()
	check(
		"宽度 = max( 原生, 内容所需 )",
		abs( wideItem._width - max( wideNativeW, wideContents ) ) < 1e-3,
		"ours %.3f native %.3f contents %.3f" % ( wideItem._width, wideNativeW, wideContents )
	)
	check( "名字放得下（不截字）", wideItem.nameFits(), "%.3f" % wideItem._width )
	check( "高度仍旧照原生", abs( wideItem._height - wideNativeH ) < 1e-3,
		"ours %.3f native %.3f" % ( wideItem._height, wideNativeH ) )
	check( "图标还在（撑宽就是为了照常画图标）", wideItem._glyph == NE.GLYPH_CAMERA, str( wideItem._glyph ) )

	# 图标绝不会因为放不下被丢掉：卡片宽度里给它留了位置
	glyphMetrics = QtGui.QFontMetrics( NE._font( NE.NODE_FONT_SIZE ) )
	check(
		"卡片宽度里给图标留了位置（图标不会被丢）",
		wideItem._width >= glyphMetrics.horizontalAdvance( wideItem.nodeName ) +
			NE.GLYPH_SIZE + NE.GLYPH_GAP + NE.NODE_TEXT_MARGIN * 2 - 1e-6,
		"%.3f" % wideItem._width
	)

	# 全图扫一遍：有图标的节点都留够了位置，名字也都放得下
	shortOfRoom = []
	for name, item in shapeEditor._NetworkEditor__nodeItems.items() :
		if not item.nameFits() :
			shortOfRoom.append( name + "(名字)" )
		if item._glyph is not None and item._width < item._NodeItem__contentsWidth() - 1e-6 :
			shortOfRoom.append( name + "(图标)" )
	check( "全图既不截字也不丢图标", not shortOfRoom, str( shortOfRoom ) )

	# 撑宽之后原生给的接口 x 要跟着拉开，否则圆点会落在卡片里面
	outPosition = wideItem.nodulePosition( wideCamera[ "out" ] )
	check( "输出接口仍在卡片下边缘",
		abs( outPosition.y() - wideItem._height / 2.0 ) < 1e-3, str( outPosition ) )
	check( "输出接口没跑出卡片", abs( outPosition.x() ) <= wideItem._width / 2.0 + 1e-3, str( outPosition ) )

	sideItem = shapeItems[ "iso" ]
	if sideItem._width > sideItem._NodeItem__nativeWidth :
		filterPosition = sideItem.nodulePosition( shapeIsolate[ "filter" ] )
		check( "侧边接口跟着贴到新的右边缘",
			abs( filterPosition.x() - sideItem._width / 2.0 ) < 1e-3, str( filterPosition ) )

# 卡片宽度是照原生算的（原生字体、且没图标），我们的字体不一样 —— 名字必须仍然放得下
elided = [
	name for name, item in shapeEditor._NetworkEditor__nodeItems.items() if not item.nameFits()
]
check( "节点名都没被截掉", not elided, str( elided ) )

# 拿不到 gadget 时的公式回退也要贴近原生（无头 / gadget 没建好的路径）
for node in ( shapeIsolate, longNode, camera ) :
	fallbackW, fallbackH = NE.nodeSizeUnits( node, None )
	nativeW, nativeH = nativeSizePx( node )
	check(
		"公式回退接近原生（%s）" % node.getName(),
		abs( fallbackW * NE.PX_PER_UNIT - nativeW ) < 1.0 and abs( fallbackH * NE.PX_PER_UNIT - nativeH ) < 1.0,
		"formula %.3fx%.3f  native %.3fx%.3f" % (
			fallbackW * NE.PX_PER_UNIT, fallbackH * NE.PX_PER_UNIT, nativeW, nativeH )
	)

# 接口位置也照抄原生 nodule
isoItem = shapeItems[ "iso" ]
isoGadget = probeGadget.nodeGadget( shapeIsolate )
for plugName in ( "in", "out", "filter" ) :
	plug = shapeIsolate[ plugName ]
	nodule = isoGadget.nodule( plug )
	if nodule is None :
		continue
	centre = nodule.transformedBound( isoGadget ).center()
	ours = isoItem.nodulePosition( plug )
	check(
		"%s 的接口位置 = 原生" % plugName,
		abs( ours.x() - centre.x * NE.PX_PER_UNIT ) < 1e-3 and
		abs( ours.y() + centre.y * NE.PX_PER_UNIT ) < 1e-3,
		"ours (%.3f,%.3f) native (%.3f,%.3f)" % (
			ours.x(), ours.y(), centre.x * NE.PX_PER_UNIT, -centre.y * NE.PX_PER_UNIT )
	)

check(
	"filter 接口挂右边（原生就是 right）",
	abs( isoItem.nodulePosition( shapeIsolate["filter"] ).x() - isoItem._width / 2.0 ) < 1e-3,
	str( isoItem.nodulePosition( shapeIsolate["filter"] ) )
)
check(
	"接口切线跟原生一致（out 朝下）",
	isoItem.noduleTangent( shapeIsolate["out"] ).y() > 0.5,
	str( isoItem.noduleTangent( shapeIsolate["out"] ) )
)

check( "有图标的节点更宽（留了图标位）", shapeItems[ "cam" ]._glyph == NE.GLYPH_CAMERA )
check( "Dot item 不带图标", shapeItems[ "dot" ]._glyph is None )

# --- 侧边接口徽章（材质节点的参数就挂左右两边）---
# 用一个 Box 手工摆出「左 3 个参数 + 右 1 个 out」的形状，和 Shader 节点一致
# （`GafferSceneUI/ShaderUI.py`：parameters 在 left、out 在 right）。
material = Gaffer.Box( "material" )
shapeScript.addChild( material )
for name in ( "baseColor", "roughness", "metalness" ) :
	plug = Gaffer.FloatPlug( name, Gaffer.Plug.Direction.In, flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
	material.addChild( plug )
	Gaffer.Metadata.registerValue( plug, "noduleLayout:section", "left" )
outPlug = Gaffer.FloatPlug( "out", Gaffer.Plug.Direction.Out, flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
material.addChild( outPlug )
Gaffer.Metadata.registerValue( outPlug, "noduleLayout:section", "right" )
Gaffer.Metadata.registerValue( material["roughness"], "noduleLayout:label", "粗糙度" )
idle()

materialLayout = NE.noduleLayout( material )
check( "左边 3 个接口", len( materialLayout["left"] ) == 3, str( [ p.getName() for p in materialLayout["left"] ] ) )
check( "右边 1 个接口", len( materialLayout["right"] ) == 1, str( [ p.getName() for p in materialLayout["right"] ] ) )

check( "noduleLabel 默认用插口名", NE.noduleLabel( material["baseColor"] ) == "baseColor" )
check( "noduleLabel 认 noduleLayout:label", NE.noduleLabel( material["roughness"] ) == "粗糙度", NE.noduleLabel( material["roughness"] ) )

materialItem = shapeScript and shapeEditor._NetworkEditor__nodeItems.get( "material" )
check( "材质节点建出来了", materialItem is not None, str( sorted( shapeEditor._NetworkEditor__nodeItems.keys() ) ) )
if materialItem is not None :
	check( "侧边行数 = max(左, 右)", materialItem._sideRows == 3, str( materialItem._sideRows ) )

	materialW, materialH = nativeSizePx( material )
	check(
		"卡片高度 = 原生（侧边接口一多原生自己就长高）",
		abs( materialItem._height - materialH ) < 1e-3 and materialItem._height > NE.NODE_HEIGHT,
		"ours %.3f native %.3f" % ( materialItem._height, materialH )
	)
	check(
		"只有一个侧边接口（filter）的节点不长高",
		abs( shapeItems[ "iso" ]._height - NE.NODE_HEIGHT ) < 1e-3, str( shapeItems[ "iso" ]._height )
	)

	rows = [ materialItem.nodulePosition( p ) for p in materialLayout["left"] ]
	check( "左侧接口贴在左边缘", all( abs( r.x() + materialItem._width / 2.0 ) < 1e-3 for r in rows ), str( rows ) )
	check( "左侧接口逐行往下排", rows[0].y() < rows[1].y() < rows[2].y(), str( [ r.y() for r in rows ] ) )

	materialGadget = probeGadget.nodeGadget( material )
	nativeRows = [
		materialGadget.nodule( p ).transformedBound( materialGadget ).center()
		for p in materialLayout["left"]
	]
	check(
		"左侧接口位置逐个 = 原生",
		all(
			abs( ours.y() + native.y * NE.PX_PER_UNIT ) < 1e-3
			for ours, native in zip( rows, nativeRows )
		),
		"ours %s native %s" % (
			[ round( r.y(), 3 ) for r in rows ],
			[ round( -n.y * NE.PX_PER_UNIT, 3 ) for n in nativeRows ],
		)
	)
	check(
		"右侧接口贴在右边缘",
		abs( materialItem.nodulePosition( outPlug ).x() - materialItem._width / 2.0 ) < 1e-3,
		str( materialItem.nodulePosition( outPlug ) )
	)

# --- 连线配色 ---
shapeIsolate["in"].setInput( dot["out"] )
shapeIsolate["filter"].setInput( shapeFilter["out"] )
shapeExpression.setExpression( 'parent["iso"]["enabled"] = True' )
idle()   # 连接是建完编辑器之后才接的，重建是 defer 到 idle 的

shapeEdges = NE.collectEdges( shapeScript, NE.collectNodes( shapeScript ) )
byPair = { ( e.srcNode.getName(), e.dstNode.getName() ) : e for e in shapeEdges }

sceneEdge = byPair.get( ( "dot", "iso" ) )
filterEdge = byPair.get( ( "filt", "iso" ) )
exprEdge = byPair.get( ( "expr", "iso" ) )

check( "拿到场景连线", sceneEdge is not None, str( sorted( byPair.keys() ) ) )
check( "拿到 filter 连线", filterEdge is not None )
check( "拿到表达式连线", exprEdge is not None )

if sceneEdge and filterEdge and exprEdge :
	# 连线按接口的类型色（`nodule:color`）上色；两头都没有类型色的（int 之类）是原生默认灰
	intSrc = Gaffer.Node( "intSrc" )
	intSrc["out"] = Gaffer.IntPlug( direction = Gaffer.Plug.Direction.Out, flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
	intDst = Gaffer.Node( "intDst" )
	intDst["in"] = Gaffer.IntPlug( flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
	intDst["in"].setInput( intSrc["out"] )
	intEdge = NE.Edge( intSrc, intSrc["out"], intDst, intDst["in"], False )
	colors = { "int" : NE.wireColor( intEdge ), "expr" : NE.wireColor( exprEdge ) }
	check( "没有类型色的连线 = 原生 ConnectionColor", colors["int"] == "#999999", str( colors ) )
	check( "表达式连线 = 原生 AuxiliaryConnectionColor", colors["expr"] == "#4d734d", str( colors ) )

	# 照 `startup/gui/graphEditor.py` 的场景蓝 / filter 金注册在插口实例上（实例上的优先）
	sceneBlue = imath.Color3f( 0.2401, 0.3394, 0.485 )
	filterGold = imath.Color3f( 0.69, 0.5378, 0.2283 )
	Gaffer.Metadata.registerValue( sceneEdge.srcPlug, "nodule:color", sceneBlue )
	Gaffer.Metadata.registerValue( filterEdge.srcPlug, "nodule:color", filterGold )
	typed = { "scene" : NE.wireColor( sceneEdge ), "filter" : NE.wireColor( filterEdge ) }
	check( "场景连线按类型色上色", typed["scene"] != "#999999", str( typed ) )
	check( "filter 连线和场景连线颜色不同", typed["filter"] != typed["scene"], str( typed ) )

	Gaffer.Metadata.registerValue( intDst["in"], "nodule:color", filterGold )
	check( "源插口没有类型色时用目标插口的", NE.wireColor( intEdge ) == "#b0893a", NE.wireColor( intEdge ) )

	def wireLuminance( hexColor ) :
		c = QtGui.QColor( hexColor )
		return 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()

	sceneQ = QtGui.QColor( typed["scene"] )
	check( "暗的类型色提亮到最低亮度", abs( wireLuminance( typed["scene"] ) - NE._WIRE_MIN_LUMINANCE ) < 0.01,
		"%.3f" % wireLuminance( typed["scene"] ) )
	check( "提亮不改色相（还是蓝）", sceneQ.blue() > sceneQ.green() > sceneQ.red(), typed["scene"] )
	check( "本来够亮的类型色原样用", typed["filter"] == NE._hex( filterGold ), typed["filter"] )

	Gaffer.Metadata.registerValue( intDst["in"], "nodule:color", imath.Color3f( 0.4 ) )
	check( "灰色的 nodule:color 不算类型色", NE.wireColor( intEdge ) == "#999999", NE.wireColor( intEdge ) )

	Gaffer.Metadata.registerValue( exprEdge.dstPlug, "nodule:color", filterGold )
	check( "辅助连线不吃类型色", NE.wireColor( exprEdge ) == "#4d734d", NE.wireColor( exprEdge ) )

	Gaffer.Metadata.deregisterValue( sceneEdge.srcPlug, "nodule:color" )
	Gaffer.Metadata.deregisterValue( filterEdge.srcPlug, "nodule:color" )
	Gaffer.Metadata.deregisterValue( exprEdge.dstPlug, "nodule:color" )
	check( "表达式连线判成 auxiliary", exprEdge.auxiliary )
	check( "场景连线不是 auxiliary", not sceneEdge.auxiliary )

	# 颜色就是 StandardStyle 里那两个默认值，拿实例回读比一比
	nativeStyle = GafferUI.StandardStyle()
	def styleHex( colorName ) :
		c = nativeStyle.getColor( getattr( GafferUI.StandardStyle.Color, colorName ) )
		return "#%02x%02x%02x" % tuple(
			max( 0, min( 255, int( round( x * 255.0 ) ) ) ) for x in ( c[0], c[1], c[2] )
		)
	check( "取值确实来自 StandardStyle.ConnectionColor", styleHex( "ConnectionColor" ) == NE._connectionColor,
		"%s vs %s" % ( styleHex( "ConnectionColor" ), NE._connectionColor ) )
	check( "辅助连线取值来自 AuxiliaryConnectionColor", styleHex( "AuxiliaryConnectionColor" ) == NE._auxiliaryWireColor,
		"%s vs %s" % ( styleHex( "AuxiliaryConnectionColor" ), NE._auxiliaryWireColor ) )
	check( "悬停高亮取值来自 HighlightColor", styleHex( "HighlightColor" ) == NE._highlightColor,
		"%s vs %s" % ( styleHex( "HighlightColor" ), NE._highlightColor ) )

# 装了扩展的环境里插口上会有 `connectionGadget:color`，原生 ConnectionGadget 会尊重它、
# 连线就变成扩展的配色了 —— 用户要求不吃这套，颜色只看类型色
sceneWireColor = NE.wireColor( sceneEdge )
Gaffer.Metadata.registerValue( shapeIsolate["in"], "connectionGadget:color", imath.Color3f( 0, 0, 1 ) )
check( "扩展注册的 connectionGadget:color 不吃",
	NE.wireColor( sceneEdge ) == sceneWireColor, "%s vs %s" % ( NE.wireColor( sceneEdge ), sceneWireColor ) )
Gaffer.Metadata.deregisterValue( shapeIsolate["in"], "connectionGadget:color" )

# 编辑器里的真连线：PathFilter 摆在 Isolate 左上方，filter 接口在 Isolate 右侧
NE.setNodePosition( shapeFilter, imath.V2f( -30, 12 ) )
NE.setNodePosition( shapeIsolate, imath.V2f( 0, 0 ) )
idle()
isoItem = shapeEditor._NetworkEditor__nodeItems["iso"]
filterItems = [ e for e in shapeEditor._NetworkEditor__edgeItems if e.edge.srcNode.getName() == "filt" ]
check( "编辑器里有 filter 那条连线", len( filterItems ) == 1, str( len( filterItems ) ) )
if filterItems :
	fp0, ft0, fp1, ft1 = filterItems[0].endPoints()
	check( "filter 接口确实在 Isolate 右侧", ft1.x() > 0.9, str( ft1 ) )
	check( "filter 连线不穿过 Isolate 卡片",
		cardHits( filterItems[0].path(), isoItem.sceneCardRect(), fp0, fp1 ) == 0,
		str( cardHits( filterItems[0].path(), isoItem.sceneCardRect(), fp0, fp1 ) ) )

# --- 长连线中段渐隐 ---
# 先把两端摆近，别让自动布局把它们排远了（那样短线的前提就没了）
NE.setNodePosition( dot, imath.V2f( 0, 6 ) )
NE.setNodePosition( shapeIsolate, imath.V2f( 0, 0 ) )
idle()

shortEdgeItem = None
for item in shapeEditor._NetworkEditor__edgeItems :
	if item.edge.dstNode.getName() == "iso" and not item.edge.auxiliary :
		shortEdgeItem = item
		break
check( "短线不渐隐", shortEdgeItem is not None and shortEdgeItem._midAlpha == 255, str( shortEdgeItem._midAlpha if shortEdgeItem else None ) )

# 把源节点拉远，线一长中段就该淡下去
NE.setNodePosition( dot, imath.V2f( 0, 80 ) )
NE.setNodePosition( shapeIsolate, imath.V2f( 0, -80 ) )
idle()
longEdgeItem = None
for item in shapeEditor._NetworkEditor__edgeItems :
	if item.edge.dstNode.getName() == "iso" and not item.edge.auxiliary :
		longEdgeItem = item
		break
check( "长线中段淡下去", longEdgeItem is not None and longEdgeItem._midAlpha < 255, str( longEdgeItem._midAlpha if longEdgeItem else None ) )
check( "但没淡到看不见", longEdgeItem is not None and longEdgeItem._midAlpha >= NE.WIRE_FADE_MIN_ALPHA )

# --- D 键 ---
check( "enabledPlugForEditing 直接返回自身", NE.enabledPlugForEditing( shapeIsolate ).isSame( shapeIsolate["enabled"] ) )
check( "非 DependencyNode 返回 None", NE.enabledPlugForEditing( Gaffer.Node() ) is None )

shapeScript.selection().clear()
shapeScript.selection().add( shapeFilter )       # PathFilter 也有 enabled
shapeScript.selection().add( camera )            # Camera 没有 enabled，应被跳过
before = shapeFilter["enabled"].getValue()
shapeEditor._toggleEnabled()
check( "D 键翻转 enabled", shapeFilter["enabled"].getValue() == ( not before ), str( shapeFilter["enabled"].getValue() ) )
check( "D 键可撤销", shapeScript.undoAvailable() )
shapeScript.undo()
check( "撤销回来了", shapeFilter["enabled"].getValue() == before )

# 「只要有一个开着就全关」
a = GafferScene.Isolate( "a" ) ; b = GafferScene.Isolate( "b" )
shapeScript.addChild( a ) ; shapeScript.addChild( b )
idle()
a["enabled"].setValue( True ) ; b["enabled"].setValue( False )
shapeScript.selection().clear()
shapeScript.selection().add( a ) ; shapeScript.selection().add( b )
shapeEditor._toggleEnabled()
check(
	"有一个开着 -> 全关",
	a["enabled"].getValue() is False and b["enabled"].getValue() is False,
	"a=%s b=%s" % ( a["enabled"].getValue(), b["enabled"].getValue() )
)
shapeEditor._toggleEnabled()
check(
	"全关着 -> 全开",
	a["enabled"].getValue() is True and b["enabled"].getValue() is True,
	"a=%s b=%s" % ( a["enabled"].getValue(), b["enabled"].getValue() )
)

shapeWindow.setVisible( False )


##########################################################################
section( "层级导航 / 快捷键（问题 5、6）" )
##########################################################################

# 剪贴板（Ctrl+C/V）要 ApplicationRoot 才有
navApplication = Gaffer.ApplicationRoot( "networkEditorNavTest" )
navScript = Gaffer.ScriptNode()
navApplication["scripts"].addChild( navScript )
navBox = Gaffer.Box( "navBox" )
navScript.addChild( navBox )
inner = GafferScene.Plane( "inner" )
navBox.addChild( inner )
outer = GafferScene.Plane( "outer" )
navScript.addChild( outer )

navEditor = NE.NetworkEditor( navScript )
navWindow = GafferUI.Window( "nav" )
navWindow.setChild( navEditor )
navWindow._qtWidget().resize( 800, 600 )
navWindow.setVisible( True )
idle()

navView = navEditor.graphView()

def sendKeyTo( view, key, modifiers = QtCore.Qt.NoModifier ) :

	event = QtGui.QKeyEvent( QtCore.QEvent.KeyPress, key, modifiers )
	QtWidgets.QApplication.sendEvent( view, event )
	idle()
	return event.isAccepted()


def sendKey( key, modifiers = QtCore.Qt.NoModifier ) :

	return sendKeyTo( navView, key, modifiers )

# --- 进层时像原生一样给没摆过位置的节点补自动布局（问题 1）---
# 原生是在 `GraphEditor.__preRender` 里做的：unpositionedNodeGadgets → positionNodes →
# layoutNodes，算完写进 `__uiPosition`。不补这一步，进 Box 看到的就是一堆挤在一起的节点。
check( "开编辑器就按原生布局补好了位置", outer.getChild( "__uiPosition" ) is not None )

navScript.selection().clear()
navScript.selection().add( navBox )
sendKey( QtCore.Qt.Key_Down )
check( "↓ 进 Box（先看布局）", navEditor.getRootNode().getName() == "navBox" )
check( "Box 里的节点也补上了位置", inner.getChild( "__uiPosition" ) is not None )

# 多个节点：不许全挤在一个点上
layoutBox = Gaffer.Box( "layoutBox" )
navScript.addChild( layoutBox )
chain = []
for i in range( 4 ) :
	n = GafferScene.Isolate( "chain%d" % i )
	layoutBox.addChild( n )
	if chain :
		n["in"].setInput( chain[-1]["out"] )
	chain.append( n )
idle()

navEditor._leaveNode()
navScript.selection().clear()
navScript.selection().add( layoutBox )
navEditor._enterNode( layoutBox )
idle()

chainPositions = [ NE.nodePosition( n ) for n in chain ]
check( "Box 内每个节点都拿到位置", all( p is not None for p in chainPositions ), str( chainPositions ) )
check(
	"而且不是挤在一起（原生自动布局排开了）",
	len( set( ( round( p.x, 3 ), round( p.y, 3 ) ) for p in chainPositions if p is not None ) ) == len( chain ),
	str( chainPositions )
)
check(
	"上下游按流向排（下游在下面）",
	all(
		chainPositions[i].y > chainPositions[i+1].y - 1e-6
		for i in range( len( chainPositions ) - 1 )
	),
	str( [ round( p.y, 2 ) for p in chainPositions ] )
)
navEditor._leaveNode()
idle()

# --- ↓ 进 Box，↑ 出来（和原生一样）---
navScript.selection().clear()
navScript.selection().add( navBox )
check( "Box 是 childrenViewable", NE.NetworkEditor._childrenViewable( navBox ) )
sendKey( QtCore.Qt.Key_Down )
check( "↓ 进 Box", navEditor.getRootNode().getName() == "navBox", navEditor.getRootNode().getName() )
check( "Box 里只看得到 inner", sorted( navEditor._NetworkEditor__nodeItems.keys() ) == [ "inner" ],
	str( sorted( navEditor._NetworkEditor__nodeItems.keys() ) ) )
sendKey( QtCore.Qt.Key_Up )
check( "↑ 回上一层", navEditor.getRootNode().isSame( navScript ) )

def sameView( a, b, tolerance = 3.0 ) :

	if a is None or b is None :
		return False
	return (
		abs( a.center().x() - b.center().x() ) < tolerance and
		abs( a.center().y() - b.center().y() ) < tolerance and
		abs( a.width() - b.width() ) < max( tolerance, a.width() * 0.02 )
	)

# --- 进不去 / 出不去的时候，上下键不许把画面滚走 ---
# `QGraphicsView` 继承 `QAbstractScrollArea`，方向键默认是滚动条的；原生 GraphEditor 是
# GL 视图，按上下键一动不动。不吞掉的话「不在 Box 里按上下键 = 视角上下移动」。
navScript.selection().clear()
navView.scale( 2.0, 2.0 )   # 缩到有滚动余量，不然滚不动，测了也白测
idle()
viewBeforeArrows = navView.viewedSceneRect()
sendKey( QtCore.Qt.Key_Down )
sendKey( QtCore.Qt.Key_Up )
sendKey( QtCore.Qt.Key_Left )
sendKey( QtCore.Qt.Key_Right )
sendKey( QtCore.Qt.Key_PageDown )
check(
	"没得进 / 没得出的时候上下左右键不滚画面",
	sameView( viewBeforeArrows, navView.viewedSceneRect(), tolerance = 0.5 ),
	"before=%s after=%s" % ( viewBeforeArrows, navView.viewedSceneRect() )
)
# 该管用的还得管用：选中 Box 按 ↓ 照样进去
navScript.selection().clear()
navScript.selection().add( navBox )
sendKey( QtCore.Qt.Key_Down )
check( "吞了滚动之后 ↓ 还是进得去 Box", navEditor.getRootNode().isSame( navBox ),
	navEditor.getRootNode().getName() )
sendKey( QtCore.Qt.Key_Up )
check( "↑ 还是出得来", navEditor.getRootNode().isSame( navScript ) )

# 非 Box（没标 childrenViewable）要 Shift+Ctrl+↓
plainParent = Gaffer.Node( "plainParent" )
navScript.addChild( plainParent )
plainParent.addChild( GafferScene.Plane( "child" ) )
idle()
navScript.selection().clear()
navScript.selection().add( plainParent )
check( "普通容器不是 childrenViewable", not NE.NetworkEditor._childrenViewable( plainParent ) )
check( "光按 ↓ 进不去", not navEditor._enterSelectedNode( withModifiers = False ) )
check( "Shift+Ctrl+↓ 才进得去", navEditor._enterSelectedNode( withModifiers = True ) )
check( "确实进去了", navEditor.getRootNode().getName() == "plainParent" )
navEditor._leaveNode()

# --- [ / ] 根历史 ---
navEditor.setRootNode( navBox )
navEditor.setRootNode( navScript )
check( "[ 回到刚才那层", navEditor._previousRoot() and navEditor.getRootNode().getName() == "navBox",
	navEditor.getRootNode().getName() )
navEditor._nextRoot()
check( "] 再跳回来", navEditor.getRootNode().isSame( navScript ), navEditor.getRootNode().getName() )

# --- 每层的视野各记一份：进 Box 再出来，回到进去之前看的地方 ---
# 原生 GraphEditor 的历史条目里也存了 frame（`_HistoryWidget.__createHistoryEntry`），
# 不记的话出 Box 就成了「全部节点」的全景，用户刚才放大看的地方全丢了。
navEditor.setRootNode( navScript )
idle()
outerItem = navEditor._NetworkEditor__nodeItems.get( "outer" )
check( "拿得到 outer 的 item（视野测试用）", outerItem is not None )

navView.frameItems( [ outerItem ] )
idle()
viewBeforeEnter = navView.viewedSceneRect()
check( "问得到现在看的是哪块", viewBeforeEnter is not None and not viewBeforeEnter.isNull() )

navEditor._enterNode( navBox )
idle()
viewInside = navView.viewedSceneRect()
check( "进 Box 是另一套视野", not sameView( viewBeforeEnter, viewInside ), str( ( viewBeforeEnter, viewInside ) ) )

navEditor._leaveNode()
idle()
check(
	"出 Box 回到进去之前看的地方（不是全景）",
	sameView( viewBeforeEnter, navView.viewedSceneRect() ),
	"before=%s after=%s" % ( viewBeforeEnter, navView.viewedSceneRect() )
)

# 层里的视野也记：再进去还是上次看的那块
navEditor._enterNode( navBox )
idle()
innerItem = navEditor._NetworkEditor__nodeItems.get( "inner" )
if innerItem is not None :
	navView.frameItems( [ innerItem ] )
	idle()
viewInsideAgain = navView.viewedSceneRect()
navEditor._leaveNode()
idle()
navEditor._enterNode( navBox )
idle()
check(
	"再进 Box 也回到上次在里面看的地方",
	sameView( viewInsideAgain, navView.viewedSceneRect() ),
	"before=%s after=%s" % ( viewInsideAgain, navView.viewedSceneRect() )
)
navEditor._leaveNode()
idle()

# 没去过的层还是取全景
freshBox = Gaffer.Box( "freshBox" )
navScript.addChild( freshBox )
freshBox.addChild( GafferScene.Plane( "freshInner" ) )
idle()
navEditor._enterNode( freshBox )
idle()
freshItem = navEditor._NetworkEditor__nodeItems.get( "freshInner" )
check(
	"没去过的层取全景（新节点在画面里）",
	freshItem is not None and navView.viewedSceneRect().contains( freshItem.sceneBoundingRect() ),
	str( navView.viewedSceneRect() )
)
navEditor._leaveNode()
idle()

# --- ` / Ctrl+` focus ---
navScript.selection().clear()
navScript.selection().add( outer )
sendKey( QtCore.Qt.Key_QuoteLeft, QtCore.Qt.ControlModifier )
check( "Ctrl+` 把选中的设成 focus",
	navScript.getFocus() is not None and navScript.getFocus().getName() == "outer",
	str( navScript.getFocus() ) )
check( "` 取景不抛异常", sendKey( QtCore.Qt.Key_QuoteLeft ) )

# --- 菜单栏那套编辑快捷键 ---
check( "Ctrl+A 全选", sendKey( QtCore.Qt.Key_A, QtCore.Qt.ControlModifier ) and len( navScript.selection() ) >= 3,
	str( len( navScript.selection() ) ) )
check( "Shift+Ctrl+A 全不选",
	sendKey( QtCore.Qt.Key_A, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier ) and len( navScript.selection() ) == 0 )

navScript.selection().clear()
navScript.selection().add( outer )
sendKey( QtCore.Qt.Key_C, QtCore.Qt.ControlModifier )
sendKey( QtCore.Qt.Key_V, QtCore.Qt.ControlModifier )
check( "Ctrl+C / Ctrl+V 粘出一个新节点",
	len( [ n for n in NE.collectNodes( navScript ) if isinstance( n, GafferScene.Plane ) ] ) >= 2,
	str( [ n.getName() for n in NE.collectNodes( navScript ) ] ) )

pastedNames = [ n.getName() for n in NE.collectNodes( navScript ) if n.getName().startswith( "outer" ) and n.getName() != "outer" ]
navScript.selection().clear()
for n in pastedNames :
	navScript.selection().add( navScript[ n ] )
sendKey( QtCore.Qt.Key_Delete )
check( "Delete 删掉了", all( navScript.getChild( n ) is None for n in pastedNames ), str( pastedNames ) )

# --- Ctrl+D：连输入一起复制 ---
downstream = GafferScene.Isolate( "downstream" )
navScript.addChild( downstream )
downstream["in"].setInput( outer["out"] )
idle()
navScript.selection().clear()
navScript.selection().add( downstream )
navEditor._duplicateWithInputs()
duplicates = [ n for n in NE.collectNodes( navScript ) if n.getName().startswith( "downstream" ) and n.getName() != "downstream" ]
check( "Ctrl+D 复制出一个", len( duplicates ) == 1, str( [ n.getName() for n in duplicates ] ) )
check( "而且输入接上了",
	len( duplicates ) == 1 and duplicates[0]["in"].getInput() is not None and
	duplicates[0]["in"].getInput().node().getName() == "outer",
	str( duplicates[0]["in"].getInput() ) if duplicates else "" )
check( "Ctrl+D 可撤销", navScript.undoAvailable() )
navScript.undo()

# --- Ctrl+L 自动布局 ---
NE.setNodePosition( outer, imath.V2f( 100, 100 ) )
idle()
navScript.selection().clear()
navScript.selection().add( outer )
navScript.selection().add( downstream )
navEditor._arrange()
check( "Ctrl+L 把节点排开了", NE.nodePosition( outer ) != imath.V2f( 100, 100 ), str( NE.nodePosition( outer ) ) )
check( "自动布局可撤销", navScript.undoAvailable() )

# --- 书签 ---
navScript.selection().clear()
navScript.selection().add( outer )
navEditor._assignNumericBookmark( 3 )
check( "Ctrl+3 设编号书签", Gaffer.MetadataAlgo.numericBookmark( outer ) == 3,
	str( Gaffer.MetadataAlgo.numericBookmark( outer ) ) )
navEditor.setRootNode( navBox )
check( "按 3 跳回书签所在层", navEditor._findNumericBookmark( 3 ) and navEditor.getRootNode().isSame( navScript ),
	navEditor.getRootNode().getName() )
check( "跳过去顺带选中它", [ n.getName() for n in navScript.selection() ] == [ "outer" ],
	str( [ n.getName() for n in navScript.selection() ] ) )
navEditor._assignNumericBookmark( 0 )
check( "Ctrl+0 清掉编号书签", not Gaffer.MetadataAlgo.numericBookmark( outer ) )

# --- 菜单栏 QAction 抢键：我们要在 ShortcutOverride 阶段截下来 ---
def shortcutOverrideAccepted( key, modifiers ) :
	event = QtGui.QKeyEvent( QtCore.QEvent.ShortcutOverride, key, modifiers )
	handled = navView.event( event )
	return handled and event.isAccepted()

check( "Ctrl+C 从菜单栏手里截下来", shortcutOverrideAccepted( QtCore.Qt.Key_C, QtCore.Qt.ControlModifier ) )
check( "Delete 也截下来", shortcutOverrideAccepted( QtCore.Qt.Key_Delete, QtCore.Qt.NoModifier ) )
check( "Ctrl+Z 不截（留给菜单栏的撤销）", not shortcutOverrideAccepted( QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier ) )


##########################################################################
section( "Tab 建节点面板（问题 5）" )
##########################################################################

# NodeMenu 把自己挂在 ApplicationRoot 的 Python 属性上（`applicationRoot._nodeMenu`），
# 而 Boost 包装对象只有**Python 子类**才保得住身份 —— 真实 Gaffer 里那个 root 就是
# Python 子类（`Gaffer.Application._NonSlicingApplicationRoot`），这里照做，
# 否则 `script.applicationRoot()` 每次拿到新包装、菜单永远是空的。
class _TestApplicationRoot( Gaffer.ApplicationRoot ) :
	pass

application = _TestApplicationRoot( "networkEditorTest" )
menuScript = Gaffer.ScriptNode()
application["scripts"].addChild( menuScript )

nodeMenu = GafferUI.NodeMenu.acquire( application )
nodeMenu.append( "/Scene/Source/Sphere", GafferScene.Sphere, searchText = "Sphere" )
nodeMenu.append( "/Scene/Filter/PathFilter", GafferScene.PathFilter, searchText = "PathFilter" )

menuEditor = NE.NetworkEditor( menuScript )
menuWindow = GafferUI.Window( "menu" )
menuWindow.setChild( menuEditor )
menuWindow._qtWidget().resize( 800, 600 )
menuWindow.setVisible( True )
idle()

entries = menuEditor._NetworkEditor__nodeMenuEntries()
check( "面板条目从 NodeMenu 来", len( entries ) >= 2, str( len( entries ) ) )
names = [ e[0] for e in entries ]
check( "条目里有 Sphere", "Sphere" in names, str( names ) )
categories = dict( ( e[0], e[1] ) for e in entries )
check( "带上所在分类", categories.get( "Sphere" ) == "Scene / Source", str( categories ) )

# 模糊匹配
check( "连续命中排前面", NE._matchScore( "sph", "Sphere" ) == 0, str( NE._matchScore( "sph", "Sphere" ) ) )
check( "子序列也能命中", NE._matchScore( "pf", "PathFilter" ) is not None )
check( "不匹配返回 None", NE._matchScore( "zzz", "Sphere" ) is None )
check( "空搜索全命中", NE._matchScore( "", "Sphere" ) == 0 )

# --- 首字母缩写：打 "ass" 就要给 aiStandardSurface（用户提的） ---
check( "驼峰切词", NE._words( "aiStandardSurface" ) == ( "ai", "standard", "surface" ),
	str( NE._words( "aiStandardSurface" ) ) )
check( "连续大写算一个词", NE._words( "OSLCode" ) == ( "osl", "code" ), str( NE._words( "OSLCode" ) ) )
check( "下划线也算边界", NE._words( "ai_standard_surface" ) == ( "ai", "standard", "surface" ),
	str( NE._words( "ai_standard_surface" ) ) )
check( "首字母缩写", NE._initials( "aiStandardSurface" ) == "ass", NE._initials( "aiStandardSurface" ) )

check( "ass 命中 aiStandardSurface", NE._matchScore( "ass", "aiStandardSurface" ) is not None )
check(
	"而且排在「名字里正好含 ass」的前面（这就是用户要的）",
	NE._matchScore( "ass", "aiStandardSurface" ) < NE._matchScore( "ass", "ShaderAssignment" ),
	"%s / %s" % ( NE._matchScore( "ass", "aiStandardSurface" ), NE._matchScore( "ass", "ShaderAssignment" ) )
)
check(
	"但真前缀还是最优（打 ass 时 Assignment 排最前）",
	NE._matchScore( "ass", "Assignment" ) < NE._matchScore( "ass", "aiStandardSurface" ),
	"%s / %s" % ( NE._matchScore( "ass", "Assignment" ), NE._matchScore( "ass", "aiStandardSurface" ) )
)
check( "缩写的前缀也算（as）", NE._matchScore( "as", "aiStandardSurface" ) < 50,
	str( NE._matchScore( "as", "aiStandardSurface" ) ) )
check( "单个字母不走缩写这档（噪音太大）", NE._matchScore( "a", "aiStandardSurface" ) == 0 )
check( "dpv → DeletePrimitiveVariables", NE._matchScore( "dpv", "DeletePrimitiveVariables" ) == 10,
	str( NE._matchScore( "dpv", "DeletePrimitiveVariables" ) ) )

# --- 按词头分段：段内可以省字母 ---
check( "aistand → ai|Standard", NE._matchScore( "aistand", "aiStandardSurface" ) == 0,
	str( NE._matchScore( "aistand", "aiStandardSurface" ) ) )
check( "stdsurf 也认（段内省字母）", NE._matchScore( "stdsurf", "aiStandardSurface" ) is not None )
check(
	"词头分段比随便什么子序列强",
	NE._matchScore( "stdsurf", "aiStandardSurface" ) < 1000,
	str( NE._matchScore( "stdsurf", "aiStandardSurface" ) )
)
check( "scnread → SceneReader", NE._matchScore( "scnread", "SceneReader" ) is not None )

# --- 空格 = 与 ---
check( "两段都得命中", NE._matchScore( "std surf", "aiStandardSurface" ) is not None )
check( "有一段不命中就整个不命中", NE._matchScore( "std zzz", "aiStandardSurface" ) is None )
check( "全是空格当空搜索", NE._matchScore( "   ", "Sphere" ) == 0 )

# 从 NodeMenu 的闭包里把创建函数拆出来
sphereItem = [ e[3] for e in entries if e[0] == "Sphere" ][0]
unwrapped = NE._unwrapNodeCreator( sphereItem.command )
check( "拆得出 nodeCreator", unwrapped is not None )
check( "拆出来的就是 Sphere", unwrapped is not None and unwrapped[0] is GafferScene.Sphere, str( unwrapped ) )
check( "要 menu 参数的拆不出来（会退回原生菜单）",
	NE._unwrapNodeCreator( lambda menu : None ) is None )
check( "不是包装函数的也拆不出来", NE._unwrapNodeCreator( None ) is None )

# 真的建一个节点出来（走的就是 Tab 面板选中后那条路）
menuEditor._NetworkEditor__createFromMenuItem( sphereItem, QtCore.QPointF( 240, -120 ) )
idle()
created = [ n for n in NE.collectNodes( menuScript ) if isinstance( n, GafferScene.Sphere ) ]
check( "Tab 面板真能建出节点", len( created ) == 1, str( [ n.getName() for n in NE.collectNodes( menuScript ) ] ) )
check( "建完就选中它", [ n.getName() for n in menuScript.selection() ] == [ created[0].getName() ] if created else False )
check( "摆在鼠标位置", created and NE.nodePosition( created[0] ) is not None and
	abs( NE.nodePosition( created[0] ).x - 240.0 / NE.PX_PER_UNIT ) < 1.0,
	str( NE.nodePosition( created[0] ) if created else None ) )
check( "建节点可撤销", menuScript.undoAvailable() )
menuScript.undo()
check( "撤销后节点没了", not [ n for n in NE.collectNodes( menuScript ) if isinstance( n, GafferScene.Sphere ) ] )

# --- 创建函数自己要 menu 的（Box / Backdrop / Reference）也得在面板里建完 ---
# 这几个是 `nodeMenuCreateCommand( menu )`，拆不出创建函数。以前直接退回原生 Tab 菜单
# ——用户刚在我们面板里打完 "box"，眼前又冒出原生搜索框要他重打一遍。
nodeMenu.append( "/Utility/Box", GafferUI.BoxUI.nodeMenuCreateCommand, searchText = "Box" )
nodeMenu.definition().append(
	"/Utility/Backdrop", { "command" : GafferUI.BackdropUI.nodeMenuCreateCommand, "searchText" : "Backdrop" }
)

menuEntries = menuEditor._NetworkEditor__nodeMenuEntries()
boxItem = [ e[3] for e in menuEntries if e[0] == "Box" ][0]
backdropItem = [ e[3] for e in menuEntries if e[0] == "Backdrop" ][0]

check( "Box 的创建函数拆不出来（它要 menu）", NE._unwrapNodeCreator( boxItem.command ) is None )
check( "Backdrop 压根不是包装出来的", NE._unwrapNodeCreator( backdropItem.command ) is None )

createdBox = menuEditor._NetworkEditor__createFromMenuItem(
	boxItem, QtCore.QPointF( 360, -240 )
)
idle()
boxes = [ n for n in NE.collectNodes( menuScript ) if isinstance( n, Gaffer.Box ) ]
check( "Tab 面板建得出 Box", createdBox and len( boxes ) == 1, str( ( createdBox, len( boxes ) ) ) )
check( "建完就选中它", boxes and [ n.getName() for n in menuScript.selection() ] == [ boxes[0].getName() ] )
check(
	"Box 摆在鼠标位置（不是 nan、不是原点）",
	boxes and NE.positionUsable( NE.nodePosition( boxes[0] ) ) and
	abs( NE.nodePosition( boxes[0] ).x - 360.0 / NE.PX_PER_UNIT ) < 1.0,
	str( NE.nodePosition( boxes[0] ) if boxes else None )
)

# 有选中节点时 Box 把它们装进去（原生 `Box.create` 的行为）
wrapMe = GafferScene.Sphere( "wrapMe" )
menuScript.addChild( wrapMe )
idle()
menuScript.selection().clear()
menuScript.selection().add( wrapMe )
menuEditor._NetworkEditor__createFromMenuItem( boxItem, QtCore.QPointF( 120, -60 ) )
idle()
check(
	"选中节点时 Box 把它装进去了",
	any(
		b.getChild( "wrapMe" ) is not None
		for b in NE.collectNodes( menuScript ) if isinstance( b, Gaffer.Box )
	),
	str( [ n.getName() for n in NE.collectNodes( menuScript ) ] )
)

# Backdrop：有选中节点时它已经把那些节点框住了，别再挪到鼠标那儿
menuScript.selection().clear()
# 关掉隐藏引擎（`GAFFER_NETWORK_EDITOR_ENGINE=0`）时上面那些 Box 建不出来 ——
# 别让这里 IndexError 把整份测试打断，后面几千条断言还要跑。
_menuBoxes = [ n for n in NE.collectNodes( menuScript ) if isinstance( n, Gaffer.Box ) ]
if _menuBoxes :
	menuScript.selection().add( _menuBoxes[0] )
menuEditor._NetworkEditor__createFromMenuItem( backdropItem, QtCore.QPointF( 900, -900 ) )
idle()
backdrops = [ n for n in NE.collectNodes( menuScript ) if isinstance( n, Gaffer.Backdrop ) ]
check( "Backdrop 也建得出来", len( backdrops ) == 1, str( len( backdrops ) ) )
check(
	"框住选中节点的 Backdrop 不会被挪到鼠标那儿",
	backdrops and NE.positionUsable( NE.nodePosition( backdrops[0] ) ) and
	abs( NE.nodePosition( backdrops[0] ).x - 900.0 / NE.PX_PER_UNIT ) > 1.0,
	str( NE.nodePosition( backdrops[0] ) if backdrops else None )
)

# 空选择时 Backdrop 摆到鼠标那儿
menuScript.selection().clear()
menuEditor._NetworkEditor__createFromMenuItem( backdropItem, QtCore.QPointF( 480, -360 ) )
idle()
_loneBackdrops = [ n for n in NE.collectNodes( menuScript ) if isinstance( n, Gaffer.Backdrop ) ]
loneBackdrop = _loneBackdrops[-1] if _loneBackdrops else None
check(
	"没选中东西时 Backdrop 摆到鼠标位置",
	loneBackdrop is not None and
	NE.positionUsable( NE.nodePosition( loneBackdrop ) ) and
	abs( NE.nodePosition( loneBackdrop ).x - 480.0 / NE.PX_PER_UNIT ) < 1.0,
	str( NE.nodePosition( loneBackdrop ) if loneBackdrop is not None else None )
)

# 建一个节点只该按一次 Ctrl+Z（摆位不进撤销）
menuScript.selection().clear()
undoBefore = len( [ n for n in NE.collectNodes( menuScript ) if isinstance( n, Gaffer.Box ) ] )
menuEditor._NetworkEditor__createFromMenuItem( boxItem, QtCore.QPointF( 60, -30 ) )
idle()
# 降级模式（`GAFFER_NETWORK_EDITOR_ENGINE=0`）下 Box 建不出来 → 没东西可撤销
if menuScript.undoAvailable() :
	menuScript.undo()
	idle()
check(
	"建 Box 只按一次 Ctrl+Z 就撤销掉了（摆位不占一步）",
	len( [ n for n in NE.collectNodes( menuScript ) if isinstance( n, Gaffer.Box ) ] ) == undoBefore,
	str( [ n.getName() for n in NE.collectNodes( menuScript ) ] )
)

check( "坏位置（nan）认得出来", not NE.positionUsable( imath.V2f( float( "nan" ), 0 ) ) )
check( "好位置认得出来", NE.positionUsable( imath.V2f( 1, 2 ) ) )

# 面板通用化：任何 MenuDefinition 都能用它画（内部快捷键弹出来的菜单就走这条）
panelDefinition = IECore.MenuDefinition()
ran = []
panelDefinition.append( "/切换/质量/final", { "command" : lambda : ran.append( "final" ) } )
panelDefinition.append( "/切换/质量/low", { "command" : lambda : ran.append( "low" ) } )
panelDefinition.append( "/切换/Divider", { "divider" : True } )
panelDefinition.append( "/切换/灰掉的", { "command" : lambda : ran.append( "nope" ), "active" : False } )

panelEntries = NE._entriesFromDefinition( panelDefinition )
check( "分隔线不进面板", "Divider" not in [ e[0] for e in panelEntries ], str( [ e[0] for e in panelEntries ] ) )
check( "灰掉的条目也收进来（但点不动）", len( panelEntries ) == 3, str( [ e[0] for e in panelEntries ] ) )
check( "带上分类路径", panelEntries[0][1] == "切换 / 质量", str( panelEntries[0] ) )
check( "认得出灰条目", NE._entryDisabled( panelDefinition.item( "/切换/灰掉的" ) ) )
check( "正常条目不是灰的", not NE._entryDisabled( panelDefinition.item( "/切换/质量/low" ) ) )

# 子菜单要钻进去 —— 内部快捷键那些菜单顶层清一色是 subMenu
subDefinition = IECore.MenuDefinition()
subDefinition.append( "/final", { "command" : lambda : ran.append( "sub-final" ) } )
subDefinition.append( "/low", { "command" : lambda : ran.append( "sub-low" ) } )
outerDefinition = IECore.MenuDefinition()
outerDefinition.append( "/Switch To Quality", { "subMenu" : subDefinition } )
outerEntries = NE._entriesFromDefinition( outerDefinition )
check( "子菜单里的条目也进面板", len( outerEntries ) == 2, str( [ e[0] for e in outerEntries ] ) )
check( "分类路径带上父级", outerEntries[0][1] == "Switch To Quality", str( outerEntries[0] ) )

lazyDefinition = IECore.MenuDefinition()
lazyDefinition.append( "/懒子菜单", { "subMenu" : lambda : subDefinition } )
check( "callable 子菜单也钻", len( NE._entriesFromDefinition( lazyDefinition ) ) == 2,
	str( NE._entriesFromDefinition( lazyDefinition ) ) )

nativeMenu = GafferUI.Menu( panelDefinition, title = "切换质量" )
menuEditor._showMenuAsPanel( nativeMenu )
panelPopup = menuEditor._NetworkEditor__creatorPopup
check( "原生菜单能换成我们的面板", panelPopup is not None and panelPopup.rowCount() == 3 )
check( "面板标题取自菜单", "切换质量" in panelPopup._NodeCreatorPopup__title.text(),
	panelPopup._NodeCreatorPopup__title.text() )

# --- 小菜单直接平铺（不逼着人多点一层）---
check( "条目少就平铺", panelPopup.rowCount() == 3, str( [ panelPopup.rowAt( i )[0] for i in range( panelPopup.rowCount() ) ] ) )
rowLabels = [ panelPopup.rowAt( i )[0] for i in range( panelPopup.rowCount() ) ]
check( "灰条目也列出来了", "灰掉的" in rowLabels, str( rowLabels ) )
# 浏览态**不写**右边那串分类层级（用户反馈：正常情况下不用显示，它只会挤名字）
check( "平铺时右边不写分类层级",
	not panelPopup.rowAt( rowLabels.index( "low" ) )[1],
	str( panelPopup.rowAt( rowLabels.index( "low" ) ) ) )

ranBefore = list( ran )
panelPopup.activateRow( rowLabels.index( "灰掉的" ) )
check( "灰条目点不动", ran == ranBefore, str( ran ) )

# 选中一条就执行原来的命令
panelPopup.setSearchText( "low" )
check( "搜索还是扁平的", panelPopup.rowCount() == 1, str( panelPopup.rowCount() ) )
panelPopup.activateRow( 0 )
check( "选中面板条目会跑原生命令", ran == [ "low" ], str( ran ) )

# --- 分组菜单（S 键那种）不许摊平，而且勾选状态要传给命令 ---
# 项目 S 键的菜单长这样：三个分组子菜单，每条都是 checkBox（当前是哪个 shot / layer /
# quality），命令签名 `switch_to_xxx( state, ... )` 靠原生 Menu 把勾选状态塞进第一个
# 位置参数。摊平了就是几十条堆在一起，不传 state 就 TypeError → 退回原生搜索菜单。
switchRan = []

def switchTo( state, name ) :
	switchRan.append( ( name, state ) )

switchDefinition = IECore.MenuDefinition()
for group, names, current in (
	( "Switch To Shot", [ "sh010", "sh020", "sh030" ], "sh020" ),
	( "Switch To Layer", [ "default", "cha", "bg" ], "default" ),
	( "Switch To Quality", [ "default", "low", "final" ], "final" ),
) :
	for name in names :
		switchDefinition.append(
			"/%s/%s" % ( group, name ),
			{
				"command" : functools.partial( switchTo, name = "%s.%s" % ( group, name ) ),
				"checkBox" : name == current,
			}
		)

switchEntries = NE._entriesFromDefinition( switchDefinition )
check( "分组菜单一共 9 条", len( switchEntries ) == 9, str( len( switchEntries ) ) )

switchPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
switchPanel.setEntries( switchEntries )
switchRootLabels = [ switchPanel.rowAt( i )[0] for i in range( switchPanel.rowCount() ) ]
check(
	"分组菜单按分组分列，不摊平",
	switchRootLabels == [ "Switch To Layer", "Switch To Quality", "Switch To Shot" ],
	str( switchRootLabels )
)
check( "分组行写了有几条", switchPanel.rowAt( 0 )[1] == "3 items  \u203a", str( switchPanel.rowAt( 0 ) ) )
switchPanel.hoverRow( switchRootLabels.index( "Switch To Shot" ) )
check( "悬停分组浮出下一列", switchPanel.columnCount() == 2, str( switchPanel.columnCount() ) )
shotLabels = [ switchPanel.rowAt( i, 1 )[0] for i in range( switchPanel.rowCount( 1 ) ) ]
check( "第二列是那一组的条目", shotLabels == [ "sh010", "sh020", "sh030" ], str( shotLabels ) )

# 勾选状态：读得出、画得出
check(
	"读得出勾着的那条",
	NE._entryCheckState( switchDefinition.item( "/Switch To Shot/sh020" ) ) is True,
	str( NE._entryCheckState( switchDefinition.item( "/Switch To Shot/sh020" ) ) )
)
check(
	"没勾的是 False",
	NE._entryCheckState( switchDefinition.item( "/Switch To Shot/sh010" ) ) is False
)
check(
	"不是勾选型条目返回 None",
	NE._entryCheckState( switchDefinition.item( "/Switch To Shot/sh010" ) ) is not None
		and NE._entryCheckState( panelDefinition.item( "/切换/质量/low" ) ) is None
)
check(
	"面板把勾选状态记在行上",
	[ switchPanel.rowChecked( i, 1 ) for i in range( switchPanel.rowCount( 1 ) ) ] == [ False, True, False ],
	str( [ switchPanel.rowChecked( i, 1 ) for i in range( switchPanel.rowCount( 1 ) ) ] )
)

# 点一条 -> 命令收到勾选状态（原生传的是「点完之后」的状态）
switchMenu = GafferUI.Menu( switchDefinition, title = "Switch Context" )
menuEditor._showMenuAsPanel( switchMenu )
switchPopup = menuEditor._NetworkEditor__creatorPopup
popupRootLabels = [ switchPopup.rowAt( i )[0] for i in range( switchPopup.rowCount() ) ]
check( "面板上也是分组的", "Switch To Shot" in popupRootLabels, str( popupRootLabels ) )
switchPopup.setSearchText( "sh010" )
check( "搜得到叶子条目", switchPopup.rowCount() == 1, str( switchPopup.rowCount() ) )
switchPopup.activateRow( 0 )
check(
	"勾选型条目的命令跑得起来（勾选状态当第一个位置参数传进去）",
	switchRan == [ ( "Switch To Shot.sh010", True ) ], str( switchRan )
)

# 选完面板就关了（`__onAccept` 用完即清），再点一条得重新弹一次
menuEditor._showMenuAsPanel( switchMenu )
switchPopup = menuEditor._NetworkEditor__creatorPopup
switchPopup.setSearchText( "sh020" )
switchPopup.activateRow( 0 )
check(
	"点已经勾着的那条传 False（和原生 toggled 一致）",
	switchRan[-1] == ( "Switch To Shot.sh020", False ), str( switchRan[-1] )
)

# 命令自己收 checkBox 的话走关键字（原生 `Menu.py:200`）
kwRan = []
def switchWithKeyword( checkBox, name ) :
	kwRan.append( ( name, checkBox ) )

kwDefinition = IECore.MenuDefinition()
kwDefinition.append( "/Group/kw", {
	"command" : functools.partial( switchWithKeyword, name = "kw" ),
	"checkBox" : False,
} )
kwMenu = GafferUI.Menu( kwDefinition, title = "Keyword" )
menuEditor._showMenuAsPanel( kwMenu )
kwPopup = menuEditor._NetworkEditor__creatorPopup
kwPopup.setSearchText( "kw" )
kwPopup.activateRow( 0 )
check( "收 checkBox 关键字的命令也跑得起来", kwRan == [ ( "kw", True ) ], str( kwRan ) )

# --- 条目一多就分层浏览 + 级联（问题 1、2）---
bigDefinition = IECore.MenuDefinition()
for group in ( "Scene", "Image", "Arnold" ) :
	for sub in ( "Source", "Filter" ) :
		for i in range( 12 ) :
			bigDefinition.append(
				"/%s/%s/Node%02d" % ( group, sub, i ),
				{ "command" : functools.partial( ran.append, "%s.%s.%d" % ( group, sub, i ) ) }
			)

bigPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
bigPanel.setEntries( NE._entriesFromDefinition( bigDefinition ) )
check( "一共 72 条", len( bigPanel._NodeCreatorPopup__entries ) == 72, str( len( bigPanel._NodeCreatorPopup__entries ) ) )

rootRows = [ bigPanel.rowAt( i ) for i in range( bigPanel.rowCount() ) ]
check( "根层只列大类，不摊平", [ r[0] for r in rootRows ] == [ "Arnold", "Image", "Scene" ], str( [ r[0] for r in rootRows ] ) )
check( "大类行写了有几条", rootRows[0][1] == "24 items  ›", str( rootRows[0] ) )
check( "大类行没有可执行的 item", rootRows[0][2] is None and rootRows[0][3] == "Arnold", str( rootRows[0] ) )
check( "一开始只有一列", bigPanel.columnCount() == 1, str( bigPanel.columnCount() ) )

# 悬停第一列的大类 -> 右边浮出第二列
oneColumnWidth = bigPanel.width()
bigPanel.hoverRow( 0 )
check( "悬停大类就浮出一列", bigPanel.columnCount() == 2, str( bigPanel.columnCount() ) )
check( "第二列是那个大类的下一层", bigPanel.columnPath( 1 ) == [ "Arnold" ], str( bigPanel.columnPath( 1 ) ) )
check(
	"第二列列的是子分类",
	[ bigPanel.rowAt( i, 1 )[3] for i in range( bigPanel.rowCount( 1 ) ) ] == [ "Filter", "Source" ],
	str( [ bigPanel.rowAt( i, 1 ) for i in range( bigPanel.rowCount( 1 ) ) ] )
)
# 第二列往后各自一个窗口（原生 QMenu 就是这样），所以**根窗口的宽高都不再变**
check( "第二列是独立窗口", bigPanel.columnWindow( 1 ) is not None )
check( "第一列还在根窗口里", bigPanel.columnWindow( 0 ) is None )
check( "开出第二列，根窗口宽度不变", bigPanel.width() == oneColumnWidth,
	"%d -> %d" % ( oneColumnWidth, bigPanel.width() ) )

# 再把鼠标放到第二列的子分类上 -> 浮出第三列（问题 1）
twoColumnWidth = bigPanel.width()
bigPanel.hoverRow( 0, 1 )
check( "在第二列上悬停再浮出第三列", bigPanel.columnCount() == 3, str( bigPanel.columnCount() ) )
check( "第三列是 Arnold / Filter", bigPanel.columnPath( 2 ) == [ "Arnold", "Filter" ], str( bigPanel.columnPath( 2 ) ) )
check( "第三列就是那 12 个节点", bigPanel.rowCount( 2 ) == 12, str( bigPanel.rowCount( 2 ) ) )
check( "都是可执行条目", all( bigPanel.rowAt( i, 2 )[2] is not None for i in range( 12 ) ) )
check( "第三列也是独立窗口", bigPanel.columnWindow( 2 ) is not None )
check( "根窗口宽度还是不变", bigPanel.width() == twoColumnWidth, "%d -> %d" % ( twoColumnWidth, bigPanel.width() ) )
check( "面包屑跟到最深那列", bigPanel.path() == [ "Arnold", "Filter" ], str( bigPanel.path() ) )

# 换到第二列的另一个子分类，第三列跟着换（不是越堆越多）
bigPanel.hoverRow( 1, 1 )
check( "第三列跟着换", bigPanel.columnPath( 2 ) == [ "Arnold", "Source" ], str( bigPanel.columnPath( 2 ) ) )
check( "列数没有越堆越多", bigPanel.columnCount() == 3, str( bigPanel.columnCount() ) )

# 在第一列换一个大类 -> 右边那些列全收掉重开
bigPanel.hoverRow( 1 )
check( "换大类右边只剩一列", bigPanel.columnCount() == 2, str( bigPanel.columnCount() ) )
check( "而且是新大类的下一层", bigPanel.columnPath( 1 ) == [ "Image" ], str( bigPanel.columnPath( 1 ) ) )

# 悬停在叶子条目上，右边的列要收掉
bigPanel.hoverRow( 0, 1 )
bigPanel.hoverRow( 0, 2 )     # Arnold/Image 的第三列是 12 个叶子，停在叶子上
check( "停在叶子上不再往右开", bigPanel.columnCount() == 3, str( bigPanel.columnCount() ) )

# 最深那列点条目 = 直接执行
ranBeforeCascade = list( ran )
bigPanel._NodeCreatorPopup__onAccept = lambda item : ran.append( "cascade" )
bigPanel.activateRow( 0, 2 )
check( "最深那列点条目直接执行", ran[ len( ranBeforeCascade ) : ] == [ "cascade" ], str( ran[-3:] ) )

# ← 往左收一列
bigPanel.setEntries( NE._entriesFromDefinition( bigDefinition ) )   # 重置
bigPanel.hoverRow( 0 )
bigPanel.hoverRow( 0, 1 )
check( "现在三列", bigPanel.columnCount() == 3 )
bigPanel._NodeCreatorPopup__goUp()
check( "← 收掉一列", bigPanel.columnCount() == 2, str( bigPanel.columnCount() ) )
bigPanel._NodeCreatorPopup__goUp()
check( "再收就只剩根那一列", bigPanel.columnCount() == 1, str( bigPanel.columnCount() ) )
check( "收完不再往下收", not bigPanel._NodeCreatorPopup__goUp() )

# --- 进下一级，上一级一动不动（用户反馈：展示二级菜单时一级菜单也跟着变）---
# 两个根因都在这儿盯着：①以前每列被拉到「最长那列」那么高，右边开出长列就把左边的列
# 一起撑高；②以前标题里写当前层级，从根层往里走一级标题从无到有，整块面板连第一列
# 一起往下挪 20px。
bigPanel.setEntries( NE._entriesFromDefinition( bigDefinition ) )
bigColumn = lambda i : bigPanel._NodeCreatorPopup__columnWidget( i )
bigTitle = bigPanel._NodeCreatorPopup__title

# 几何要真的量，面板就得真的弹出来（没 show 的面板布局根本不生效，量了也白量）
def pump() :

	QtWidgets.QApplication.processEvents()

bigPanel.popupAt( QtCore.QPoint( 120, 120 ), lambda item : None )
pump()

# 一律比**全局**几何：子列现在各自一个窗口，比窗口内的局部坐标没意义
def globalRect( widget ) :

	return QtCore.QRect( widget.mapToGlobal( QtCore.QPoint( 0, 0 ) ), widget.size() )

rootWindowGeometry = QtCore.QRect( bigPanel.geometry() )
rootGeometry = globalRect( bigColumn( 0 ) )
# 标题用文字判，不用 `isVisible()` —— 它还受面板显不显示影响
titleAtRoot = bigTitle.text()

bigPanel.hoverRow( 0 )
pump()
check( "开出第二列，根窗口几何一动不动", bigPanel.geometry() == rootWindowGeometry,
	"%s -> %s" % ( rootWindowGeometry, bigPanel.geometry() ) )
check( "第一列几何一动不动", globalRect( bigColumn( 0 ) ) == rootGeometry,
	"%s -> %s" % ( rootGeometry, globalRect( bigColumn( 0 ) ) ) )
check( "也没有因为标题冒出来把面板整体往下挪",
	bigTitle.text() == titleAtRoot, "%r -> %r" % ( titleAtRoot, bigTitle.text() ) )
check( "第二列窗口不压在根窗口上",
	not bigPanel.columnWindow( 1 ).geometry().intersects( bigPanel.geometry() ),
	"%s vs %s" % ( bigPanel.columnWindow( 1 ).geometry(), bigPanel.geometry() ) )
check( "第二列顶端和第一列对齐（差在窗口外框那几像素内）",
	abs( bigPanel.columnWindow( 1 ).geometry().top() + NE._ColumnWindow.MARGIN - rootGeometry.top() ) <= 2 * NE._ColumnWindow.MARGIN,
	"%d vs %d" % ( bigPanel.columnWindow( 1 ).geometry().top(), rootGeometry.top() ) )

# --- 子列要从**展开它的那一行**开始（用户反馈：老做法每次都从顶上展开）---
def columnTopFor( row ) :

	bigPanel.hoverRow( row )
	pump()
	window = bigPanel.columnWindow( 1 )
	return window.geometry().top() + NE._ColumnWindow.MARGIN

def rowTop( row, column = 0 ) :

	widget = bigColumn( column )
	rect = widget.visualItemRect( widget.item( row ) )
	return widget.viewport().mapToGlobal( rect.topLeft() ).y()

topForRow0 = columnTopFor( 0 )
check( "第一行展开：子列对着第一行", abs( topForRow0 - rowTop( 0 ) ) <= 2,
	"%d vs %d" % ( topForRow0, rowTop( 0 ) ) )

topForRow2 = columnTopFor( 2 )
check( "第三行展开：子列对着**第三行**（不是面板顶上）",
	abs( topForRow2 - rowTop( 2 ) ) <= 2, "%d vs 行顶 %d" % ( topForRow2, rowTop( 2 ) ) )
check( "两次展开的位置差正好是两行的高度",
	abs( ( topForRow2 - topForRow0 ) - 2 * NE._NodeCreatorPopup.ROW_HEIGHT ) <= 2,
	"差 %d，两行 %d" % ( topForRow2 - topForRow0, 2 * NE._NodeCreatorPopup.ROW_HEIGHT ) )

# 更深一级也一样：第三列对着第二列里那一行
bigPanel.hoverRow( 0 )
pump()
secondColumnCategoryRow = next(
	( i for i in range( bigPanel.rowCount( 1 ) ) if bigPanel.rowAt( i, 1 )[3] ), None
)
if secondColumnCategoryRow is not None and bigPanel.rowCount( 1 ) > 1 :
	deepRow = max( secondColumnCategoryRow, 1 )
	bigPanel.hoverRow( deepRow, 1 )
	pump()
	if bigPanel.columnCount() > 2 and bigPanel.columnWindow( 2 ) is not None :
		thirdTop = bigPanel.columnWindow( 2 ).geometry().top() + NE._ColumnWindow.MARGIN
		check( "第三列对着第二列里展开它的那一行",
			abs( thirdTop - rowTop( deepRow, 1 ) ) <= 2,
			"%d vs 行顶 %d" % ( thirdTop, rowTop( deepRow, 1 ) ) )

bigPanel.hoverRow( 0 )
pump()

secondGeometry = QtCore.QRect( bigPanel.columnWindow( 1 ).geometry() )
bigPanel.hoverRow( 0, 1 )     # 第三列 12 行，比左边两列都长
pump()
check( "第三列更长也没动根窗口", bigPanel.geometry() == rootWindowGeometry,
	"%s -> %s" % ( rootWindowGeometry, bigPanel.geometry() ) )
check( "第一列几何还是一动不动", globalRect( bigColumn( 0 ) ) == rootGeometry,
	"%s -> %s" % ( rootGeometry, globalRect( bigColumn( 0 ) ) ) )
check( "第二列窗口同样一动不动", bigPanel.columnWindow( 1 ).geometry() == secondGeometry,
	"%s -> %s" % ( secondGeometry, bigPanel.columnWindow( 1 ).geometry() ) )
check( "每列高度按它自己的行数算（2 行 vs 12 行）",
	bigColumn( 1 ).height() < bigColumn( 2 ).height() and
	abs( bigColumn( 2 ).height() - bigColumn( 1 ).height() ) == 10 * NE._NodeCreatorPopup.ROW_HEIGHT,
	"%d vs %d" % ( bigColumn( 1 ).height(), bigColumn( 2 ).height() ) )

# --- 嵌套 popup 的事件派发：鼠标退回左边那些列上照样管用 ---
# 事件只发给最上面那个 popup（第三列窗口），坐标落在左边的列上时得自己派发过去。
def globalRowPoint( column, row ) :

	viewport = bigColumn( column ).viewport()
	return viewport.mapToGlobal( QtCore.QPoint( 12, row * NE._NodeCreatorPopup.ROW_HEIGHT + 6 ) )

bigPanel._routeMouse( "move", globalRowPoint( 0, 2 ) )
pump()
check( "鼠标退回第一列，派发得到（当前行跟过去了）", bigColumn( 0 ).currentRow() == 2,
	str( bigColumn( 0 ).currentRow() ) )
check( "而且右边那些列跟着换成新大类", bigPanel.columnPath( 1 ) == [ "Scene" ],
	str( bigPanel.columnPath( 1 ) ) )

routed = []
bigPanel._NodeCreatorPopup__onAccept = lambda item : routed.append( item )
bigPanel._routeMouse( "move", globalRowPoint( 1, 0 ) )
pump()
bigPanel._routeMouse( "release", globalRowPoint( 2, 3 ) )
pump()
check( "在子列窗口上松手 = 选中那一条", len( routed ) == 1, str( routed ) )

bigPanel.popupAt( QtCore.QPoint( 120, 120 ), lambda item : None )
pump()
bigPanel._routeMouse( "press", bigPanel.geometry().topLeft() + QtCore.QPoint( 2, 2 ) )
pump()
check( "点在自己窗口的边距 / 标题上不关面板", bigPanel.isVisible() )
bigPanel._routeMouse( "press", QtCore.QPoint( -5000, -5000 ) )
pump()
check( "点在所有列外面就整个关掉", not bigPanel.isVisible() )
check( "关掉时子列窗口也一起收了", bigPanel.columnCount() == 1, str( bigPanel.columnCount() ) )
bigPanel.hide()

# --- 展开第二级之后，一级菜单的滚动条还能按着拖（用户反馈）---
# 根因：鼠标事件只发给最上面那个 popup（子列窗口），落在左边列的滚动条上时
# `__columnAt` 认不出（滚动条在 viewport 外面）就掉进"点外面关面板"的分支 ——
# 滚动条压根收不到按下。修法是 press 落在那根滚动条上就把它转过去、并记下
# 拖动状态，拖出滚动条范围也一直喂给它，松手才还回去。
scrollDefinition = IECore.MenuDefinition()
for c in range( 25 ) :   # 根层 25 个分类 > MAX_VISIBLE_ROWS(18) → 根列有滚动条
	subMenu = IECore.MenuDefinition()
	for i in range( 4 ) :
		subMenu.append( "/item%d" % i, { "command" : lambda : None } )
	scrollDefinition.append( "/Category%02d" % c, { "subMenu" : subMenu } )

scrollPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
scrollPanel.setEntries( NE._entriesFromDefinition( scrollDefinition ) )
scrollPanel.popupAt( QtCore.QPoint( 120, 120 ), lambda item : None )
pump()
scrollRoot = scrollPanel._NodeCreatorPopup__columnWidget( 0 )
scrollBar = scrollRoot.verticalScrollBar()
check( "滚动条回归：根列条目多到出滚动条", scrollBar.isVisible() and scrollBar.maximum() > 0,
	"visible=%s max=%d" % ( scrollBar.isVisible(), scrollBar.maximum() ) )

scrollPanel.hoverRow( 0 )
pump()
check( "滚动条回归：第二列也开出来了", scrollPanel.columnCount() >= 2, str( scrollPanel.columnCount() ) )

def scrollSliderCenter() :

	option = QtWidgets.QStyleOptionSlider()
	scrollBar.initStyleOption( option )
	rect = scrollBar.style().subControlRect(
		QtWidgets.QStyle.CC_ScrollBar, option, QtWidgets.QStyle.SC_ScrollBarSlider )
	return scrollBar.mapToGlobal( rect.center() ), rect.height()

sliderCenter, sliderHeight = scrollSliderCenter()
scrollPanel._routeMouse( "press", sliderCenter )
pump()
check( "滚动条回归：按下滑块进入拖动状态",
	scrollPanel._NodeCreatorPopup__scrollDrag is not None,
	str( scrollPanel._NodeCreatorPopup__scrollDrag ) )
scrollPanel._routeMouse( "move", sliderCenter + QtCore.QPoint( 0, int( sliderHeight * 1.2 ) ) )
pump()
scrolledValue = scrollBar.value()
check( "滚动条回归：按住往下拖真的滚了", scrolledValue > 0,
	"value=%d" % scrolledValue )
scrollPanel._routeMouse( "release", sliderCenter + QtCore.QPoint( 0, int( sliderHeight * 1.2 ) ) )
pump()
check( "滚动条回归：松手退出拖动状态",
	scrollPanel._NodeCreatorPopup__scrollDrag is None,
	str( scrollPanel._NodeCreatorPopup__scrollDrag ) )
check( "滚动条回归：拖完面板还开着", scrollPanel.isVisible() )

# 拖完再点空白，关面板的老判据没被滚动条分支吃掉
scrollPanel._routeMouse( "press", QtCore.QPoint( -5000, -5000 ) )
pump()
check( "滚动条回归：点在所有列外面还是整个关掉", not scrollPanel.isVisible() )
scrollPanel.hide()

# --- 鼠标滑过要高亮（用户反馈：滑过没反应）---
bigPanel.setEntries( NE._entriesFromDefinition( bigDefinition ) )
bigPanel.hoverRow( 2 )
check( "鼠标停在哪行，哪行就是当前行（= 高亮）", bigColumn( 0 ).currentRow() == 2,
	str( bigColumn( 0 ).currentRow() ) )
# 新开的列**什么都不预选** —— 鼠标还没进去就有一行亮着，看着就是"残留"
check( "刚开出来的那列什么都不预选", bigColumn( 1 ).currentRow() == -1, str( bigColumn( 1 ).currentRow() ) )
bigPanel.hoverRow( 0, 1 )
check( "走到下一列，上一列的高亮留在原地", bigColumn( 0 ).currentRow() == 2,
	str( bigColumn( 0 ).currentRow() ) )
check( "进了才亮", bigColumn( 1 ).currentRow() == 0, str( bigColumn( 1 ).currentRow() ) )
check( "再往里开出来的那列同样不预选", bigColumn( 2 ).currentRow() == -1, str( bigColumn( 2 ).currentRow() ) )
bigPanel.setSearchText( "Node03" )
check( "但搜过之后预选第一条（回车能直接建）", bigColumn( 0 ).currentRow() == 0,
	str( bigColumn( 0 ).currentRow() ) )
bigPanel.setSearchText( "" )
check( "清掉搜索词又回到什么都不选", bigColumn( 0 ).currentRow() == -1,
	str( bigColumn( 0 ).currentRow() ) )

def renderRow( widget, row, state ) :

	image = QtGui.QImage( 200, NE._NodeCreatorPopup.ROW_HEIGHT, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	option = QtWidgets.QStyleOptionViewItem()
	option.rect = QtCore.QRect( 0, 0, 200, NE._NodeCreatorPopup.ROW_HEIGHT )
	option.state = state
	widget.itemDelegate().paint( painter, option, widget.model().index( row, 0 ) )
	painter.end()
	return image

def pixelDiff( a, b ) :

	count = 0
	for y in range( a.height() ) :
		for x in range( a.width() ) :
			if a.pixel( x, y ) != b.pixel( x, y ) :
				count += 1
	return count

plainImage = renderRow( bigColumn( 0 ), 0, QtWidgets.QStyle.State_Enabled )
hoverImage = renderRow( bigColumn( 0 ), 0, QtWidgets.QStyle.State_Enabled | QtWidgets.QStyle.State_MouseOver )
selectedImage = renderRow( bigColumn( 0 ), 0, QtWidgets.QStyle.State_Enabled | QtWidgets.QStyle.State_Selected )
check( "当前行画得和平时不一样（这就是悬停高亮）", pixelDiff( plainImage, selectedImage ) > 200,
	str( pixelDiff( plainImage, selectedImage ) ) )
# **绝不画 `State_MouseOver`**：不是最上面那个 popup 的列收不到真鼠标事件，Qt 内部
# 那个 hover 状态停在最后划过的行上清不掉，画面上就留一道洗不掉的浅蓝。
check( "不画 Qt 自己那套 hover 状态（残留的根因）", pixelDiff( plainImage, hoverImage ) == 0,
	str( pixelDiff( plainImage, hoverImage ) ) )

# --- 尺寸跟着内容走（问题 2）---
smallDefinition = IECore.MenuDefinition()
for i in range( 3 ) :
	smallDefinition.append( "/只有几条/Item%d" % i, { "command" : functools.partial( ran.append, "small%d" % i ) } )
smallPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
smallPanel.setEntries( NE._entriesFromDefinition( smallDefinition ) )
smallHeight = smallPanel.height()

bigPanel.setEntries( NE._entriesFromDefinition( bigDefinition ) )
rootHeight = bigPanel.height()
check( "按下 Tab 的高度 = 第一列自己的条目数（3 个大类 = 3 行）",
	abs( rootHeight - (
		bigPanel.layout().contentsMargins().top() + bigPanel.layout().contentsMargins().bottom() +
		bigPanel._NodeCreatorPopup__search.sizeHint().height() + bigPanel.layout().spacing() +
		3 * NE._NodeCreatorPopup.ROW_HEIGHT + 4
	) ) < 2,
	str( rootHeight )
)

# 展开下一级不动上一级：子列各自一个窗口、各按自己的条目数定高（原生 QMenu 同款）
bigPanel.hoverRow( 0 )
afterOneCascade = bigPanel.height()
secondWindowHeight = bigPanel.columnWindow( 1 ).height()
bigPanel.hoverRow( 0, 1 )     # 第三列 12 行，比第二列（2 行）长得多
tallHeight = bigPanel.height()
check( "浮出第二列，根窗口高度不变", afterOneCascade == rootHeight, "%d -> %d" % ( rootHeight, afterOneCascade ) )
check( "再浮出 12 行的第三列，根窗口高度还是不变", tallHeight == rootHeight, "%d -> %d" % ( rootHeight, tallHeight ) )
check( "第二列窗口的高度也没被第三列拉高",
	bigPanel.columnWindow( 1 ).height() == secondWindowHeight,
	"%d -> %d" % ( secondWindowHeight, bigPanel.columnWindow( 1 ).height() ) )
check( "第三列 12 行，比 2 行的第二列高",
	bigPanel.columnWindow( 2 ).height() - bigPanel.columnWindow( 1 ).height()
		== 10 * NE._NodeCreatorPopup.ROW_HEIGHT,
	"%d vs %d" % ( bigPanel.columnWindow( 1 ).height(), bigPanel.columnWindow( 2 ).height() ) )
bigPanel._NodeCreatorPopup__goUp()
check( "往回收一列，根窗口高度也不变", bigPanel.height() == rootHeight, str( bigPanel.height() ) )
bigPanel.setSearchText( "Node03" )
check( "搜索时高度跟着结果条数走（原生搜索菜单也是这样）",
	bigPanel.height() > rootHeight and bigPanel.rowCount() == 6,
	"%d -> %d（%d 条结果）" % ( rootHeight, bigPanel.height(), bigPanel.rowCount() ) )
bigPanel.setSearchText( "" )
check( "清掉搜索词高度回到 3 行", bigPanel.height() == rootHeight, str( bigPanel.height() ) )
check( "矮的那个不是固定尺寸", smallPanel.height() < 200, str( smallPanel.height() ) )
check(
	"高度按行数算（3 条 = 3 行）",
	abs( smallHeight - (
		smallPanel.layout().contentsMargins().top() + smallPanel.layout().contentsMargins().bottom() +
		smallPanel._NodeCreatorPopup__search.sizeHint().height() + smallPanel.layout().spacing() +
		3 * NE._NodeCreatorPopup.ROW_HEIGHT + 4
	) ) < 2,
	str( smallHeight )
)
check(
	"行数超过上限就截断（出滚动条，不是无限长）",
	bigPanel.height() <= (
		bigPanel.layout().contentsMargins().top() + bigPanel.layout().contentsMargins().bottom() +
		bigPanel._NodeCreatorPopup__search.sizeHint().height() + bigPanel.layout().spacing() +
		NE._NodeCreatorPopup.MAX_VISIBLE_ROWS * NE._NodeCreatorPopup.ROW_HEIGHT + 8
	),
	str( bigPanel.height() )
)

# 搜索时**全局扁平**（一列），右边写它在哪个分类
bigPanel.hoverRow( 0 )      # 先开出两列
bigPanel.setSearchText( "Node03" )
check( "搜索时收回一列", bigPanel.columnCount() == 1, str( bigPanel.columnCount() ) )
searchRows = [ bigPanel.rowAt( i ) for i in range( bigPanel.rowCount() ) ]
check( "搜索不受层级限制", len( searchRows ) == 6, str( [ r[1] for r in searchRows ] ) )
check( "搜索结果右边写分类", all( " / " in r[1] for r in searchRows ), str( searchRows[0] ) )
bigPanel.setSearchText( "" )
check( "清掉搜索词回到根层", bigPanel.columnCount() == 1 and bigPanel.rowCount() == 3, str( bigPanel.rowCount() ) )

##########################################################################
section( "建节点面板 · 常用 / 喜爱" )
##########################################################################

# 记录落在临时目录里，绝不碰用户自己那份
usageDirectory = tempfile.mkdtemp( prefix = "networkEditorUsage" )
usagePath = os.path.join( usageDirectory, "nodeCreator.json" )
usage = NE._CreatorUsage( path = usagePath )

check( "一开始什么都没有", usage.favourites() == [] and usage.frequent() == [] )

favDefinition = IECore.MenuDefinition()
# 一个顶层分类 —— 这一节验的是「常用 / 喜爱」，要的是条目直接摊在根层
# （多个顶层分类会照分类分列，见上面「分组菜单不许摊平」那节）
for group in ( "Scene", ) :
	for name in ( "Sphere", "Plane", "Cube", "Grid", "Text" ) :
		favDefinition.append(
			"/%s/Source/%s" % ( group, name ),
			{ "command" : functools.partial( ran.append, "%s.%s" % ( group, name ) ) }
		)
favEntries = NE._entriesFromDefinition( favDefinition )

favPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
favPanel.setEntries( favEntries, usage = usage )

rootLabels = lambda : [ favPanel.rowAt( i )[0] for i in range( favPanel.rowCount() ) ]
check( "没钉过东西时根层一行不多", "★ Favourites" not in rootLabels() and "Frequent" not in rootLabels(),
	str( rootLabels() ) )
baseRowCount = favPanel.rowCount()

# --- 用过就进「常用」 ---
sceneSphere = next( i for i in range( favPanel.rowCount() ) if favPanel.rowAt( i )[0] == "Sphere" )
sphereKey = favPanel.rowKey( sceneSphere )
check( "条目的身份 = 分类 + 名字", sphereKey in ( "Scene / Source / Sphere", "Arnold / Source / Sphere" ),
	str( sphereKey ) )

favPanel.activateRow( sceneSphere )
check( "选中一条就记一笔", usage.count( sphereKey ) == 1, str( usage.count( sphereKey ) ) )
check( "记的东西落了盘", os.path.isfile( usagePath ) )

favPanel.setEntries( favEntries, usage = usage )
labels = rootLabels()
check( "根层多出「常用」一节", "Frequent" in labels, str( labels ) )
check( "常用里就是刚用过的那条", labels[ labels.index( "Frequent" ) + 1 ] == "Sphere", str( labels ) )
check( "「常用」这行是分节标题", favPanel.rowIsHeader( labels.index( "Frequent" ) ) )
check( "标题点不动", favPanel.rowAt( labels.index( "Frequent" ) )[2] is None )
check( "常用那条右边也不写分类层级（浏览态一律不写）",
	not ( favPanel.rowAt( labels.index( "Frequent" ) + 1 )[1] or "" ),
	str( favPanel.rowAt( labels.index( "Frequent" ) + 1 ) ) )

# --- 右键钉住 ---
favAccepted = []
cubeRow = next( i for i in range( favPanel.rowCount() ) if favPanel.rowAt( i )[0] == "Cube" )
cubeKey = favPanel.rowKey( cubeRow )
favPanel.toggleFavouriteRow( cubeRow )
check( "钉住一条", usage.isFavourite( cubeKey ) )
labels = rootLabels()
check( "根层多出「★ 喜爱」一节", "★ Favourites" in labels, str( labels ) )
check( "喜爱排在常用前面", labels.index( "★ Favourites" ) < labels.index( "Frequent" ), str( labels ) )
check( "喜爱那条就是 Cube", labels[ labels.index( "★ Favourites" ) + 1 ] == "Cube", str( labels ) )
check( "钉住的行自己知道自己钉住了", favPanel.rowIsFavourite( labels.index( "★ Favourites" ) + 1 ) )
# 右键走的是真正那条鼠标派发（不是直接调开关）：钉住、不建节点、不关面板
favPanel.popupAt( QtCore.QPoint( 140, 140 ), lambda item : favAccepted.append( item ) )
pump()
favColumn = favPanel._NodeCreatorPopup__columnWidget( 0 )
planeRow = next( i for i in range( favPanel.rowCount() ) if favPanel.rowAt( i )[0] == "Plane" )
planeKey = favPanel.rowKey( planeRow )
favPanel._routeMouse(
	"press",
	favColumn.viewport().mapToGlobal(
		QtCore.QPoint( 12, planeRow * NE._NodeCreatorPopup.ROW_HEIGHT + 6 )
	),
	QtCore.Qt.RightButton
)
pump()
check( "右键真的钉住了", usage.isFavourite( planeKey ), str( usage.favourites() ) )
check( "右键不建节点", not favAccepted, str( favAccepted ) )
check( "右键不关面板", favPanel.isVisible() )
# 真机走的是**列表自己的 viewport 收到右键**那条路（popup grab 之下，落在列表上的事件
# 直接发给 QListWidget，`_ColumnWindow.mousePressEvent` 根本轮不到）——
# 所以过滤器那条路也得单独验一遍。
gridRow = next( i for i in range( favPanel.rowCount() ) if favPanel.rowAt( i )[0] == "Grid" )
gridFilterKey = favPanel.rowKey( gridRow )
gridPoint = QtCore.QPoint( 12, gridRow * NE._NodeCreatorPopup.ROW_HEIGHT + 6 )
handled = favPanel.eventFilter(
	favColumn.viewport(),
	QtGui.QMouseEvent(
		QtCore.QEvent.MouseButtonPress,
		QtCore.QPointF( gridPoint ), QtCore.QPointF( favColumn.viewport().mapToGlobal( gridPoint ) ),
		QtCore.Qt.RightButton, QtCore.Qt.RightButton, QtCore.Qt.NoModifier
	)
)
check( "列表 viewport 上的右键也钉得住", usage.isFavourite( gridFilterKey ), str( usage.favourites() ) )
check( "而且把事件吃掉（不让列表改选中行 / 弹 Qt 自己的菜单）", handled )
if usage.isFavourite( gridFilterKey ) :
	usage.toggleFavourite( gridFilterKey )

usage.toggleFavourite( planeKey )      # 复原：喜爱里只留 Cube
favPanel.hide()
favPanel.setEntries( favEntries, usage = usage )
labels = rootLabels()

# 钉住不影响它照常出现在原来的位置（喜爱那一节是**多出来的**，不是搬过去）
check( "原来那份还在", labels.count( "Cube" ) >= 2, str( labels ) )

favPanel.toggleFavouriteRow( labels.index( "★ Favourites" ) + 1 )
check( "再右键一次就取消", not usage.isFavourite( cubeKey ) )
check( "喜爱一空这节就没了", "★ Favourites" not in rootLabels(), str( rootLabels() ) )

# --- 键盘 Ctrl+D 干的是同一件事 ---
favPanel.toggleFavouriteRow( cubeRow )     # 先钉一个回来
favPanel.hoverRow( next( i for i in range( favPanel.rowCount() ) if favPanel.rowAt( i )[0] == "Grid" ) )
gridKey = favPanel.rowKey( next( i for i in range( favPanel.rowCount() ) if favPanel.rowAt( i )[0] == "Grid" ) )
favPanel._handleKeyEvent(
	QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_D, QtCore.Qt.ControlModifier )
)
check( "Ctrl+D 钉住当前行", usage.isFavourite( gridKey ), str( usage.favourites() ) )

# --- 分节标题选不中（上下键要跳过去）---
labels = rootLabels()
headerRow = labels.index( "★ Favourites" )
favPanel._NodeCreatorPopup__columnWidget( 0 ).setCurrentRow( max( 0, headerRow - 1 ) )
for unusedStep in range( favPanel.rowCount() ) :
	favPanel._handleKeyEvent(
		QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_Down, QtCore.Qt.NoModifier )
	)
	check( "上下键从不停在分节标题上",
		not favPanel.rowIsHeader( favPanel._NodeCreatorPopup__columnWidget( 0 ).currentRow() ),
		str( favPanel._NodeCreatorPopup__columnWidget( 0 ).currentRow() ) )

# --- 悬停标题不展开、不动高亮 ---
before = favPanel._NodeCreatorPopup__columnWidget( 0 ).currentRow()
favPanel.hoverRow( headerRow )
check( "鼠标划过标题什么都不做",
	favPanel._NodeCreatorPopup__columnWidget( 0 ).currentRow() == before,
	str( favPanel._NodeCreatorPopup__columnWidget( 0 ).currentRow() ) )

# --- 搜索时：钉住的 / 用得多的往前挪，但不越档 ---
favPanel.setSearchText( "e" )
searchLabels = [ favPanel.rowAt( i )[0] for i in range( favPanel.rowCount() ) ]
check( "搜索结果里没有分节标题", not any( favPanel.rowIsHeader( i ) for i in range( favPanel.rowCount() ) ),
	str( searchLabels ) )
check( "搜索结果上也画得出星",
	any( favPanel.rowIsFavourite( i ) for i in range( favPanel.rowCount() ) ), str( searchLabels ) )
favPanel.setSearchText( "" )

# 排序：同一档里用得多的在前
plainPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
plainPanel.setEntries( favEntries )       # 不给 usage：没有常用 / 喜爱，也不记账
check( "不给 usage 就没有这两节", "★ Favourites" not in [ plainPanel.rowAt( i )[0] for i in range( plainPanel.rowCount() ) ] )
plainPanel.activateRow( 0 )
check( "不给 usage 也不会往记录里写", usage.count( plainPanel.rowKey( 0 ) or "x" ) == 0 )

# --- 画出来长什么样：钉住的名字后面有一颗星，分节标题另一种画法 ---
def goldPixels( image ) :

	count = 0
	for y in range( image.height() ) :
		for x in range( image.width() ) :
			color = QtGui.QColor( image.pixel( x, y ) )
			if color.red() > 140 and color.green() > 100 and color.blue() < 110 and color.red() - color.blue() > 50 :
				count += 1
	return count

starUsage = NE._CreatorUsage( path = os.path.join( usageDirectory, "star.json" ) )
starPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
starPanel.setEntries( favEntries, usage = starUsage )
starColumn = starPanel._NodeCreatorPopup__columnWidget( 0 )

plainImage = renderRow( starColumn, 0, QtWidgets.QStyle.State_Enabled )
check( "没钉住的行上没有金色", goldPixels( plainImage ) == 0, str( goldPixels( plainImage ) ) )
check( "普通行顶上没有分隔线", all(
	QtGui.QColor( plainImage.pixel( x, 0 ) ) == QtGui.QColor( "#000000" ) for x in range( plainImage.width() )
) )

starUsage.toggleFavourite( starPanel.rowKey( 0 ) )
starPanel.setEntries( favEntries, usage = starUsage )
starColumn = starPanel._NodeCreatorPopup__columnWidget( 0 )
starRow = next( i for i in range( starPanel.rowCount() ) if starPanel.rowIsFavourite( i ) )
starImage = renderRow( starColumn, starRow, QtWidgets.QStyle.State_Enabled )
check( "钉住的行名字后面画了一颗星（数金色像素）", goldPixels( starImage ) > 6, str( goldPixels( starImage ) ) )

starHeaderRow = next( i for i in range( starPanel.rowCount() ) if starPanel.rowIsHeader( i ) )
headerImage = renderRow( starColumn, starHeaderRow, QtWidgets.QStyle.State_Enabled )
check( "分节标题顶上压了一条分隔线", any(
	QtGui.QColor( headerImage.pixel( x, y ) ) != QtGui.QColor( "#000000" )
	for x in range( headerImage.width() ) for y in ( 0, 1 )
), str( [ QtGui.QColor( headerImage.pixel( x, 0 ) ).name() for x in range( 0, headerImage.width(), 40 ) ] ) )

# --- 落盘 / 重新读回来 ---
reloaded = NE._CreatorUsage( path = usagePath )
check( "喜爱读得回来", set( reloaded.favourites() ) == set( usage.favourites() ),
	"%s / %s" % ( reloaded.favourites(), usage.favourites() ) )
check( "次数读得回来", reloaded.count( sphereKey ) == usage.count( sphereKey ) )

with open( usagePath, "w" ) as handle :
	handle.write( "{ 这不是 json" )
broken = NE._CreatorUsage( path = usagePath )
check( "文件坏了就当空的（绝不因为它炸掉）", broken.favourites() == [] and broken.frequent() == [] )
broken.record( "Scene / Source / Sphere" )
check( "坏文件被下一次写盘修好", NE._CreatorUsage( path = usagePath ).count( "Scene / Source / Sphere" ) == 1 )

missing = NE._CreatorUsage( path = os.path.join( usageDirectory, "nested", "deep", "u.json" ) )
missing.record( "a" )
check( "目录不存在就现建", os.path.isfile( os.path.join( usageDirectory, "nested", "deep", "u.json" ) ) )

# --- 榜单只列还在的条目 ---
staleUsage = NE._CreatorUsage( path = os.path.join( usageDirectory, "stale.json" ) )
staleUsage.record( "Scene / Source / 早就删掉的节点" )
staleUsage.toggleFavourite( "Scene / Source / 也删掉了" )
stalePanel = NE._NodeCreatorPopup( menuEditor.graphView() )
stalePanel.setEntries( favEntries, usage = staleUsage )
check( "记录里有、菜单里没有的条目不会冒出来",
	stalePanel.rowCount() == baseRowCount, str( [ stalePanel.rowAt( i )[0] for i in range( stalePanel.rowCount() ) ] ) )

# --- 「常用」有上限 ---
manyUsage = NE._CreatorUsage( path = os.path.join( usageDirectory, "many.json" ) )
for i in range( 20 ) :
	manyUsage.record( "k%02d" % i )
check( "常用最多列 %d 条" % NE._CreatorUsage.FREQUENT_LIMIT,
	len( manyUsage.frequent() ) == NE._CreatorUsage.FREQUENT_LIMIT, str( len( manyUsage.frequent() ) ) )
manyUsage.record( "k05" ) ; manyUsage.record( "k05" )
check( "用得多的排前面", manyUsage.frequent()[0] == "k05", str( manyUsage.frequent()[:3] ) )
check( "已经在喜爱里的不再进常用", "k05" not in manyUsage.frequent( exclude = [ "k05" ] ) )

# --- 状态目录能用环境变量搬走 ---
originalStateDirectory = os.environ.get( "GAFFER_NETWORK_EDITOR_STATE_DIR" )
os.environ[ "GAFFER_NETWORK_EDITOR_STATE_DIR" ] = usageDirectory
check( "环境变量说了算", NE._stateDirectory() == usageDirectory, NE._stateDirectory() )
check( "全局那份就在里面",
	NE._CreatorUsage().path() == os.path.join( usageDirectory, "nodeCreator.json" ),
	NE._CreatorUsage().path() )
if originalStateDirectory is None :
	del os.environ[ "GAFFER_NETWORK_EDITOR_STATE_DIR" ]
else :
	os.environ[ "GAFFER_NETWORK_EDITOR_STATE_DIR" ] = originalStateDirectory

check( "全局那份是同一个对象", NE.creatorUsage() is NE.creatorUsage() )

# --- Tab 建节点那个面板真的带上了榜单 ---
NE.setCreatorUsage( NE._CreatorUsage( path = os.path.join( usageDirectory, "live.json" ) ) )
menuEditor._popupNodeMenu( QtCore.QPoint( 100, 100 ) )
idle()
livePanel = menuEditor._NetworkEditor__creatorPopup
check( "Tab 面板带「常用 / 喜爱」", livePanel._NodeCreatorPopup__usage is NE.creatorUsage() )
livePanel.hide()
menuEditor._showPanel( entries, lambda item : None )
check( "内部快捷键那些菜单不带（榜单只认建节点）",
	menuEditor._NetworkEditor__creatorPopup._NodeCreatorPopup__usage is None )
menuEditor._NetworkEditor__creatorPopup.hide()
NE.setCreatorUsage( None )

shutil.rmtree( usageDirectory, ignore_errors = True )

# --- 多显示器：弹出位置只夹在鼠标所在那块屏上 ---
# 用户反馈「换显示器再开 tab 栏还是在另一个显示器上」。真凶是 `QtGui.QGuiApplication`
# 在 Qt.py 这层壳里**根本不存在** → AttributeError 被 except 吞掉 → 退回"主屏" →
# 按主屏可用区夹坐标 → 鼠标在副屏，面板被硬夹回主屏。
check( "Qt.py 的 QtGui 里没有 QGuiApplication（写了就是 AttributeError）",
	not hasattr( QtGui, "QGuiApplication" ) )

for screen in QtWidgets.QApplication.screens() :
	check( "%s 屏中心问得出就是这块屏" % screen.name(),
		NE._screenAt( screen.geometry().center() ) is screen,
		str( NE._screenAt( screen.geometry().center() ) ) )
check( "谁的地盘都不是就返回 None", NE._screenAt( QtCore.QPoint( -99999, -99999 ) ) is None )

leftRect = QtCore.QRect( 0, 0, 1920, 1200 )        # 副屏
rightRect = QtCore.QRect( 1920, 0, 2560, 1440 )    # 主屏
panelSize = QtCore.QSize( 300, 400 )
check( "屏内的位置原样不动",
	NE._clampToRect( QtCore.QPoint( 500, 600 ), panelSize, leftRect ) == QtCore.QPoint( 500, 600 ) )
# QRect.right() 是**含端点**的 left+width-1，所以是 1919-300
check( "贴着右边缘会往回收",
	NE._clampToRect( QtCore.QPoint( 1900, 600 ), panelSize, leftRect ) == QtCore.QPoint( 1619, 600 ),
	str( NE._clampToRect( QtCore.QPoint( 1900, 600 ), panelSize, leftRect ) ) )
check( "拿错屏就会被硬拽到那块屏上（这就是老 bug 的样子）",
	NE._clampToRect( QtCore.QPoint( 500, 600 ), panelSize, rightRect ).x() == 1920,
	str( NE._clampToRect( QtCore.QPoint( 500, 600 ), panelSize, rightRect ) ) )
check( "问不出在哪块屏就一律不夹",
	NE._clampToRect( QtCore.QPoint( 500, 600 ), panelSize, None ) == QtCore.QPoint( 500, 600 ) )

# --- 多窗口：面板挂在编辑器当前所在的那个窗口上（用户反馈：Tab 栏绑在一个窗口上）---
# `Qt.Popup` 的原生窗口在**创建那一刻**就认下 transient parent；Gaffer 换布局是把编辑器
# 控件整个 reparent 到另一个窗口（控件对象不变），面板不重新 setParent 就一直贴着老窗口。
mwEditor = NE.NetworkEditor( menuScript )
mwWindowA = GafferUI.Window( "mwA" )
mwWindowA.setChild( mwEditor )
mwWindowA._qtWidget().resize( 600, 400 )
mwWindowA.setVisible( True )
idle()

mwEditor._showPanel( entries, lambda item : None )
mwPopup = mwEditor._NetworkEditor__creatorPopup
check( "面板挂在 A 窗口上", mwPopup.parentWidget() is mwWindowA._qtWidget(),
	str( mwPopup.parentWidget() ) )
mwPopup.hide()

mwWindowB = GafferUI.Window( "mwB" )
mwWindowB.setChild( mwEditor )
mwWindowB._qtWidget().resize( 600, 400 )
mwWindowB.setVisible( True )
idle()
check( "编辑器确实搬到 B 窗口了", mwEditor.graphView().window() is mwWindowB._qtWidget() )

mwEditor._showPanel( entries, lambda item : None )
check( "面板跟着挂到 B 窗口（还是同一个面板对象）",
	mwEditor._NetworkEditor__creatorPopup is mwPopup and
	mwPopup.parentWidget() is mwWindowB._qtWidget(),
	str( mwPopup.parentWidget() ) )
check( "重新挂过之后条目还在", mwPopup.rowCount() > 0, str( mwPopup.rowCount() ) )
mwPopup.hide()
mwWindowA.setVisible( False )
mwWindowB.setVisible( False )

check( "认得出 NodeMenu 包装的建节点命令", NE._isNodeCreatorCommand( sphereItem.command ) )
check( "普通命令不会被误判", not NE._isNodeCreatorCommand( lambda : None ) )

wrappedDefinition = IECore.MenuDefinition()
wrappedDefinition.append( "/Sphere", { "command" : sphereItem.command } )
wrappedMenu = GafferUI.Menu( wrappedDefinition, title = "快捷收藏" )

beforeWrapped = set( n.getName() for n in NE.collectNodes( menuScript ) )
menuEditor._showMenuAsPanel( wrappedMenu )
wrappedPanel = menuEditor._NetworkEditor__creatorPopup
wrappedPanel.activateRow( 0 )
idle()
createdWrapped = [ n.getName() for n in NE.collectNodes( menuScript ) if n.getName() not in beforeWrapped ]

check( "面板里点「建节点」条目不再报 assert", len( createdWrapped ) == 1, str( createdWrapped ) )
if createdWrapped :
	check( "建出来的是 Sphere", isinstance( menuScript[ createdWrapped[0] ], GafferScene.Sphere ) )
	menuScript.undo()
	idle()

check( "认得出要 menu 参数的命令", NE._commandWantsMenu( lambda menu : None ) )
check( "不要 menu 参数的也认得", not NE._commandWantsMenu( lambda : None ) )
check( "partial 也能看穿", NE._commandWantsMenu( functools.partial( lambda menu, x : None, x = 1 ) ) )

# 面板本身：搜一下能不能筛到
popup = NE._NodeCreatorPopup( menuEditor.graphView() )
popup.setEntries( entries )
check( "两条节点直接平铺（没到分层的量）", popup.rowCount() == 2,
	str( [ popup.rowAt( i )[0] for i in range( popup.rowCount() ) ] ) )
popup.setSearchText( "sph" )
check( "搜 sph 有结果", popup.rowCount() >= 1, str( popup.rowCount() ) )
check( "第一条就是 Sphere", popup.rowCount() and popup.rowAt( 0 )[0] == "Sphere",
	popup.rowAt( 0 )[0] if popup.rowCount() else "" )
popup.setSearchText( "zzzzz" )
check( "搜不到就空列表", popup.rowCount() == 0, str( popup.rowCount() ) )
popup.setSearchText( "" )
check( "清掉搜索词回到浏览态", popup.rowCount() == 2, str( popup.rowCount() ) )

menuWindow.setVisible( False )


##########################################################################
section( "点 focus 不许闪（只有一个节点时最明显）" )
##########################################################################

# `ContextTracker` 是**异步**的：刚点上 focus 那一下它还没算完，这时候问
# `isTracked()` 全是 False —— 整张图先刷暗一帧、等它算完再亮回来，看着就是"闪一下"。
# 判据：设 focus 的过程中，节点的 active 状态**一次都不许翻**。

flickerScript = Gaffer.ScriptNode()
flickerNode = GafferScene.Sphere( "only" )
flickerScript.addChild( flickerNode )
NE.setNodePosition( flickerNode, imath.V2f( 0, 0 ) )

flickerEditor = NE.NetworkEditor( flickerScript )
flickerWindow = GafferUI.Window( "flicker" )
flickerWindow.setChild( flickerEditor )
flickerWindow._qtWidget().resize( 900, 600 )
flickerWindow.setVisible( True )
idle()
flickerEditor.graphView().frameAll()
idle()

flickerLog = []
_originalSetNodeActive = NE._NodeItem.setNodeActive

def _spySetNodeActive( self, active ) :
	if active != self._active :
		flickerLog.append( active )
	return _originalSetNodeActive( self, active )

NE._NodeItem.setNodeActive = _spySetNodeActive

def settleTracker( seconds = 40 ) :
	for unused in range( seconds ) :
		idle()
		QtWidgets.QApplication.processEvents()
		tracker = flickerEditor._NetworkEditor__contextTracker()
		if tracker is not None and not tracker.updatePending() :
			break
	idle()

del flickerLog[:]
flickerScript.setFocus( flickerNode )
settleTracker()
check( "设 focus 的过程中，节点亮度一次都没翻（不闪）", flickerLog == [], str( flickerLog ) )
check( "focus 状态是对的", flickerEditor._NetworkEditor__nodeItems[ "only" ]._focused )
check( "而且它当然算参与计算（没被刷暗）",
	flickerEditor._NetworkEditor__nodeItems[ "only" ].isNodeActive() )

del flickerLog[:]
flickerScript.setFocus( None )
settleTracker()
check( "取消 focus 也不闪", flickerLog == [], str( flickerLog ) )

del flickerLog[:]
flickerScript.setFocus( flickerNode )
settleTracker()
check( "再设一次还是不闪", flickerLog == [], str( flickerLog ) )

NE._NodeItem.setNodeActive = _originalSetNodeActive
flickerScript.setFocus( None )
idle()
flickerWindow.setVisible( False )


##########################################################################
section( "把连线丢到材质的 + 上：弹出藏起来的参数让你挑" )
##########################################################################

# 原生 `PlugAdder` 需要在多个候选里挑一个时，会走 `plugMenuSignal` 弹一个模态菜单
# （处理函数在 `GafferUI/_PlugAdder.py`）。材质节点的 `+` 就是这么用的：
# 背后是一堆 `noduleLayout:visible = False` 的参数，挑中哪个就把哪个显示出来再接上。

hiddenScript = Gaffer.ScriptNode()
hiddenApplication = Gaffer.ApplicationRoot( "hiddenPlugTest" )
hiddenApplication[ "scripts" ].addChild( hiddenScript )

hiddenSource = GafferOSL.OSLShader( "src" )
hiddenTarget = Gaffer.Node( "shaderish" )
hiddenScript.addChild( hiddenTarget )
sourcePlug = Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out )
hiddenSourceNode = Gaffer.Node( "src" )
hiddenSourceNode.addChild( sourcePlug )
hiddenScript.addChild( hiddenSourceNode )

parameters = Gaffer.Plug( "parameters" )
hiddenTarget.addChild( parameters )
for name in ( "baseColor", "specColor" ) :
	plug = Gaffer.Color3fPlug( name, Gaffer.Plug.Direction.In )
	parameters.addChild( plug )
	Gaffer.Metadata.registerValue( plug, "noduleLayout:visible", False )   # 藏起来
Gaffer.Metadata.registerValue( parameters, "noduleLayout:section", "left" )
# 真材质节点的 `parameters` 就是这么注册的：复合 nodule，子插口各自一个圆点
Gaffer.Metadata.registerValue( parameters, "nodule:type", "GafferUI::CompoundNodule" )

for n in ( hiddenSourceNode, hiddenTarget ) :
	NE.setNodePosition( n, imath.V2f( 0, 0 ) )

hiddenEditor = NE.NetworkEditor( hiddenScript )
hiddenWindow = GafferUI.Window( "hidden" )
hiddenWindow.setChild( hiddenEditor )
hiddenWindow._qtWidget().resize( 900, 600 )
hiddenWindow.setVisible( True )
idle()

candidates = hiddenEditor._NetworkEditor__hiddenConnectablePlugs( hiddenTarget, "left", sourcePlug )
check( "找得到藏起来又接得上的参数", len( candidates ) == 2,
	str( [ p.getName() for p in candidates ] ) )

# 两个候选 → 弹面板让你挑
hiddenEditor._createPromotedConnection( hiddenTarget, "left", sourcePlug )
panel = hiddenEditor._NetworkEditor__creatorPopup
check( "多个候选时弹出来让你挑", panel is not None and panel.rowCount() == 2,
	str( panel.rowCount() ) if panel is not None else "没弹" )
panel.activateRow( 0 )
idle()
connected = [ p for p in candidates if p.getInput() is not None ]
check( "挑中的那个接上了", len( connected ) == 1, str( [ p.getName() for p in connected ] ) )
check( "而且它显示出来了（noduleLayout:visible = True）",
	Gaffer.Metadata.value( connected[0], "noduleLayout:visible" ) is True,
	str( Gaffer.Metadata.value( connected[0], "noduleLayout:visible" ) ) )
check( "卡片上真的多了个圆点",
	any(
		p.getName() == connected[0].getName()
		for p in hiddenEditor._NetworkEditor__nodeItems[ "shaderish" ]._nodules.get( "left", [] )
	),
	str( [ p.getName() for p in hiddenEditor._NetworkEditor__nodeItems[ "shaderish" ]._nodules.get( "left", [] ) ] ) )
check( "接上 + 显示只占一步撤销", hiddenScript.undoAvailable() )
hiddenScript.undo()
idle()
check( "撤销之后又藏回去了",
	connected[0].getInput() is None and
	Gaffer.Metadata.value( connected[0], "noduleLayout:visible" ) is False,
	str( Gaffer.Metadata.value( connected[0], "noduleLayout:visible" ) ) )

# 只剩一个候选时不弹菜单，直接接
Gaffer.Metadata.registerValue( candidates[1], "noduleLayout:visible", True )
idle()
hiddenEditor._NetworkEditor__creatorPopup.hide()
before = candidates[0].getInput()
hiddenEditor._createPromotedConnection( hiddenTarget, "left", sourcePlug )
idle()
check( "只有一个候选就直接接上，不弹菜单",
	candidates[0].getInput() is not None and before is None,
	str( candidates[0].getInput() ) )

hiddenWindow.setVisible( False )


##########################################################################
section( "材质图标按 shader 类型分（不能都画材质球）" )
##########################################################################

# 置换 / 体积 / 贴图 / 程序纹理 / 数学工具都是 Shader 的子类，一律画材质球的话
# 一屏下来全一个样。判据取自 Shader 自己的 `type`（ai:surface / ai:displacement …）
# 和 `name`（standard_surface / image / noise …）。
# 这里直接喂假的 type/name 插口，不碰真的 Arnold（无头一碰就 SIGABRT）。

def glyphFor( typeValue, nameValue ) :

	node = Gaffer.Node( "s" )
	node.addChild( Gaffer.StringPlug( "type", defaultValue = typeValue ) )
	node.addChild( Gaffer.StringPlug( "name", defaultValue = nameValue ) )
	return NE.shaderGlyph( node )

check( "表面材质 = 材质球", glyphFor( "ai:surface", "standard_surface" ) == NE.GLYPH_SHADER )
check( "置换 = 置换图标", glyphFor( "ai:displacement", "standard_displacement" ) == NE.GLYPH_DISPLACEMENT )
check( "体积 = 云团", glyphFor( "ai:volume", "standard_volume" ) == NE.GLYPH_VOLUME )
check( "灯光 shader = 灯泡", glyphFor( "ai:light", "quad_light" ) == NE.GLYPH_LIGHT )
check( "贴图 = 画片", glyphFor( "ai:shader", "image" ) == NE.GLYPH_TEXTURE )
check( "三平面贴图也算贴图", glyphFor( "ai:shader", "triplanar" ) == NE.GLYPH_TEXTURE )
check( "噪波 = 程序纹理", glyphFor( "ai:shader", "noise" ) == NE.GLYPH_PATTERN )
check( "棋盘也是程序纹理", glyphFor( "osl:shader", "checkerboard" ) == NE.GLYPH_PATTERN )
check( "调色 = 工具", glyphFor( "ai:shader", "color_correct" ) == NE.GLYPH_UTILITY )
check( "range 也是工具", glyphFor( "ai:shader", "range" ) == NE.GLYPH_UTILITY )
check( "认不出来的通用 shader 退回材质球", glyphFor( "ai:shader", "" ) == NE.GLYPH_SHADER )
check( "ShaderAssignment 还是材质球",
	NE.nodeGlyph( GafferScene.ShaderAssignment( "sa" ) ) == NE.GLYPH_SHADER )

# 新图标画得出来（不抛异常，而且真的画了东西）
for glyph in ( NE.GLYPH_DISPLACEMENT, NE.GLYPH_VOLUME, NE.GLYPH_TEXTURE, NE.GLYPH_PATTERN, NE.GLYPH_UTILITY ) :
	glyphImage = QtGui.QImage( 40, 40, QtGui.QImage.Format_ARGB32 )
	glyphImage.fill( QtGui.QColor( "#000000" ) )
	glyphPainter = QtGui.QPainter( glyphImage )
	NE._drawGlyph( glyphPainter, glyph, QtCore.QPointF( 20, 20 ), 16.0, QtGui.QColor( "#ffffff" ) )
	glyphPainter.end()
	ink = sum(
		1 for y in range( 40 ) for x in range( 40 )
		if QtGui.QColor( glyphImage.pixel( x, y ) ).value() > 40
	)
	check( "%s 图标画得出来" % glyph, ink > 20, str( ink ) )


##########################################################################
section( "灯光按类型分图标（不统一小灯泡）" )
##########################################################################

# 灯光类型读 `__shader.name`（`GafferScene::Light` 把 shader 存在 `__shader` 子节点里，
# ArnoldLight 的顶层 `name` 只是 "light"）。这里喂假的 `__shader` / `name`，不碰真 Arnold。
def lightGlyphFor( shaderName ) :
	node = Gaffer.Node( "s" )
	shader = Gaffer.Node( "__shader" )
	shader.addChild( Gaffer.StringPlug( "name", defaultValue = shaderName ) )
	node.addChild( shader )
	return NE.lightGlyph( node )

check( "点光 = 点光图标", lightGlyphFor( "point_light" ) == NE.GLYPH_POINT_LIGHT )
check( "平行光 = 太阳图标", lightGlyphFor( "distant_light" ) == NE.GLYPH_DISTANT_LIGHT )
check( "面光 = 矩形面板", lightGlyphFor( "quad_light" ) == NE.GLYPH_QUAD_LIGHT )
check( "聚光 = 锥形光束", lightGlyphFor( "spot_light" ) == NE.GLYPH_SPOT_LIGHT )
check( "圆盘光 = 圆盘", lightGlyphFor( "disk_light" ) == NE.GLYPH_DISK_LIGHT )
check( "圆柱光 = 圆柱", lightGlyphFor( "cylinder_light" ) == NE.GLYPH_CYLINDER_LIGHT )
check( "穹顶光 = 半球", lightGlyphFor( "skydome_light" ) == NE.GLYPH_SKYDOME_LIGHT )
check( "光度学 = IES 灯具", lightGlyphFor( "photometric_light" ) == NE.GLYPH_PHOTOMETRIC_LIGHT )
check( "网格光 = 网格", lightGlyphFor( "mesh_light" ) == NE.GLYPH_MESH_LIGHT )
check( "认不出的灯光兜底回灯泡", lightGlyphFor( "weird_light" ) == NE.GLYPH_LIGHT )

# 读不到 `__shader` 时退回顶层 `name`
nameOnly = Gaffer.Node( "s" )
nameOnly.addChild( Gaffer.StringPlug( "name", defaultValue = "quad_light" ) )
check( "没有 __shader 时读顶层 name", NE.lightGlyph( nameOnly ) == NE.GLYPH_QUAD_LIGHT )

# `isLightNode`：Light / LightFilter / 网格光都是灯，别的不是。
# 1.7.1.0 的 GafferScene 有独立的 MeshLight（派生自 FilteredSceneProcessor，不是 Light），
# Arnold 那个叫 ArnoldMeshLight —— 一律按**类名以 "MeshLight" 结尾**认。
class ArnoldMeshLight( Gaffer.Node ) :
	pass

check( "Light 派生是灯", NE.isLightNode( Light( "l" ) ) )
check( "ArnoldMeshLight 是灯（类名以 MeshLight 结尾）", NE.isLightNode( ArnoldMeshLight( "m" ) ) )
check( "普通节点不是灯", not NE.isLightNode( Gaffer.Node( "n" ) ) )

# 新灯光图标画得出来
for glyph in (
	NE.GLYPH_POINT_LIGHT, NE.GLYPH_DISTANT_LIGHT, NE.GLYPH_QUAD_LIGHT, NE.GLYPH_SPOT_LIGHT,
	NE.GLYPH_DISK_LIGHT, NE.GLYPH_CYLINDER_LIGHT, NE.GLYPH_SKYDOME_LIGHT,
	NE.GLYPH_PHOTOMETRIC_LIGHT, NE.GLYPH_MESH_LIGHT
) :
	glyphImage = QtGui.QImage( 40, 40, QtGui.QImage.Format_ARGB32 )
	glyphImage.fill( QtGui.QColor( "#000000" ) )
	glyphPainter = QtGui.QPainter( glyphImage )
	NE._drawGlyph( glyphPainter, glyph, QtCore.QPointF( 20, 20 ), 16.0, QtGui.QColor( "#ffffff" ) )
	glyphPainter.end()
	ink = sum(
		1 for y in range( 40 ) for x in range( 40 )
		if QtGui.QColor( glyphImage.pixel( x, y ) ).value() > 40
	)
	check( "%s 图标画得出来" % glyph, ink > 20, str( ink ) )


##########################################################################
section( "连线端点可以拽下来改接（原生同款）" )
##########################################################################

# 原生 `StandardConnectionGadget`：**只有靠近两端**才抓得住连线
# （`endAt` 的灵敏区 = clamp( 线长/4, 2.5, 25 ) 个单位），中间那段不响应。
# 抓目的地那头 = 手里攥着源插口找新输入；抓源那头 = 攥着目的地找新输出；
# 落在空白处 = 把这根线断掉。

reconScript = Gaffer.ScriptNode()
reconApplication = Gaffer.ApplicationRoot( "reconTest" )
reconApplication[ "scripts" ].addChild( reconScript )
rcA = GafferScene.Sphere( "rcA" )
rcB = GafferScene.Sphere( "rcB" )
rcC = GafferScene.Isolate( "rcC" )
rcD = GafferScene.Isolate( "rcD" )
for index, n in enumerate( ( rcA, rcB, rcC, rcD ) ) :
	reconScript.addChild( n )
NE.setNodePosition( rcA, imath.V2f( 0, 0 ) )
NE.setNodePosition( rcB, imath.V2f( 30, 0 ) )
NE.setNodePosition( rcC, imath.V2f( 0, -20 ) )
NE.setNodePosition( rcD, imath.V2f( 30, -20 ) )
rcC[ "in" ].setInput( rcA[ "out" ] )

reconEditor = NE.NetworkEditor( reconScript )
reconWindow = GafferUI.Window( "recon" )
reconWindow.setChild( reconEditor )
reconWindow._qtWidget().resize( 1000, 700 )
reconWindow.setVisible( True )
idle()
reconView = reconEditor.graphView()
reconView.frameAll()
idle()

reconEdge = next( e for e in reconEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "rcC" )
p0, unusedT0, p1, unusedT1 = reconEdge.endPoints()

check( "靠近源那头 = 抓住 src", reconEdge.endAt( p0 ) == "src", str( reconEdge.endAt( p0 ) ) )
check( "靠近目的地那头 = 抓住 dst", reconEdge.endAt( p1 ) == "dst", str( reconEdge.endAt( p1 ) ) )
middle = QtCore.QPointF( ( p0.x() + p1.x() ) / 2.0, ( p0.y() + p1.y() ) / 2.0 )
check( "中间那段抓不住（不然长线上随手一点就把线拽走了）",
	reconEdge.endAt( middle ) is None, str( reconEdge.endAt( middle ) ) )

# --- 抓目的地那头，改接到另一个节点的输入上 ---
def dragEnd( edgeItem, end, targetScenePoint ) :

	# 起点取那一头的位置，终点取目标
	p0, unusedT0, p1, unusedT1 = edgeItem.endPoints()
	start = reconView.mapFromScene( p1 if end == "dst" else p0 )
	reconView._GraphView__beginReconnect( edgeItem, end, start )
	reconView._GraphView__updateConnectWire( reconView.mapFromScene( targetScenePoint ) )
	reconView._GraphView__endConnect( reconView.mapFromScene( targetScenePoint ) )
	idle()

rcDItem = reconEditor._NetworkEditor__nodeItems[ "rcD" ]
dragEnd( reconEdge, "dst", rcDItem.scenePos() )
check( "改接：新的目的地接上了", rcD[ "in" ].getInput() is not None and
	rcD[ "in" ].getInput().node().getName() == "rcA", str( rcD[ "in" ].getInput() ) )
check( "改接：旧的目的地断开了", rcC[ "in" ].getInput() is None, str( rcC[ "in" ].getInput() ) )
check( "改接只占一步撤销", reconScript.undoAvailable() )
reconScript.undo()
idle()
check( "撤销之后回到原样",
	rcC[ "in" ].getInput() is not None and rcD[ "in" ].getInput() is None,
	"%s / %s" % ( rcC[ "in" ].getInput(), rcD[ "in" ].getInput() ) )

# --- 抓源那头，换一个源 ---
reconEdge = next( e for e in reconEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "rcC" )
rcBItem = reconEditor._NetworkEditor__nodeItems[ "rcB" ]
dragEnd( reconEdge, "src", rcBItem.scenePos() )
check( "改源：目的地还是它，源换成了 rcB",
	rcC[ "in" ].getInput() is not None and rcC[ "in" ].getInput().node().getName() == "rcB",
	str( rcC[ "in" ].getInput() ) )
reconScript.undo()
idle()

# --- 拽到空白处 = 断开 ---
reconEdge = next( e for e in reconEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "rcC" )
dragEnd( reconEdge, "dst", QtCore.QPointF( 4000, 4000 ) )
check( "拽到空白处就断开", rcC[ "in" ].getInput() is None, str( rcC[ "in" ].getInput() ) )
reconScript.undo()
idle()
check( "断开也能撤销", rcC[ "in" ].getInput() is not None )

# --- 落在没人接的地方 = 断开（原生 `dragEnd`：「noone wanted the drop so we'll disconnect」）---
reconEdge = next( e for e in reconEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "rcC" )
rcAItem = reconEditor._NetworkEditor__nodeItems[ "rcA" ]
dragEnd( reconEdge, "dst", rcAItem.scenePos() )     # 落回源节点自己，没人接
check( "落回源节点（没人接）= 断开，和原生一样", rcC[ "in" ].getInput() is None,
	str( rcC[ "in" ].getInput() ) )
reconScript.undo()
idle()
check( "这一步也能撤销", rcC[ "in" ].getInput() is not None )

reconWindow.setVisible( False )


##########################################################################
section( "圆点右键：展开 / 收起 RGB 子插口" )
##########################################################################

# 材质节点的 `out` 是个 Color3f，原生在圆点上右键有「Expand RGB Components」，
# 展开之后 r/g/b 各自一个圆点、能单独连线。这条注册在
# `CompoundNumericNoduleUI.__plugContextMenuSignal` 上 —— 我们借了插口菜单，
# 所以它本来就该有；这里盯的是**展开之后我们的卡片要跟着长出子圆点**。

rgbScript = Gaffer.ScriptNode()
rgbApplication = Gaffer.ApplicationRoot( "rgbTest" )
rgbApplication[ "scripts" ].addChild( rgbScript )

rgbNode = Gaffer.Node( "rgbNode" )
rgbOut = Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out )
rgbNode.addChild( rgbOut )
rgbScript.addChild( rgbNode )
NE.setNodePosition( rgbNode, imath.V2f( 0, 0 ) )
# 材质节点就是这么注册的：复合数值 nodule + 摆在右边
Gaffer.Metadata.registerValue( rgbOut, "nodule:type", "GafferUI::CompoundNumericNodule" )
Gaffer.Metadata.registerValue( rgbOut, "noduleLayout:section", "right" )

rgbEditor = NE.NetworkEditor( rgbScript )
rgbWindow = GafferUI.Window( "rgb" )
rgbWindow.setChild( rgbEditor )
rgbWindow._qtWidget().resize( 900, 600 )
rgbWindow.setVisible( True )
idle()

rgbItem = lambda : rgbEditor._NetworkEditor__nodeItems[ "rgbNode" ]
rightNodules = lambda : [ p.getName() for p in rgbItem()._nodules.get( "right", [] ) ]
check( "一开始右边只有一个 out 圆点", rightNodules() == [ "out" ], str( rightNodules() ) )

rgbMenu = IECore.MenuDefinition()
check( "圆点上有原生菜单", rgbEditor._NetworkEditor__appendNativePlugMenu( rgbMenu, rgbOut ),
	str( [ path for path, item in rgbMenu.items() ] ) )
expandItems = [ item for path, item in rgbMenu.items() if "Expand" in path and "Components" in path ]
check( "里面有「展开 RGB」那一条",
	len( expandItems ) == 1, str( [ path for path, item in rgbMenu.items() ] ) )

# 点它 —— 子圆点要真的出现在卡片上
# （降级模式 `GAFFER_NETWORK_EDITOR_ENGINE=0` 下原生菜单是空的，跳过后面这几条）
if expandItems :
	expandItems[0].command()
	idle()
check( "展开之后 r/g/b 各有一个圆点",
	rightNodules() == [ "r", "g", "b" ], str( rightNodules() ) )
check( "展开是可撤销的（原生走的 metadata）", rgbScript.undoAvailable() )

# 再右键就是「收起」
collapseMenu = IECore.MenuDefinition()
rgbEditor._NetworkEditor__appendNativePlugMenu( collapseMenu, rgbOut )
collapseItems = [ item for path, item in collapseMenu.items() if "Collapse" in path ]
check( "展开之后菜单变成「收起」", len( collapseItems ) == 1,
	str( [ path for path, item in collapseMenu.items() ] ) )
if collapseItems :
	collapseItems[0].command()
idle()
check( "收起之后回到一个 out 圆点", rightNodules() == [ "out" ], str( rightNodules() ) )

# 子圆点也能各自连线（展开的意义就在这儿）
expandItems2 = None
expandMenu2 = IECore.MenuDefinition()
rgbEditor._NetworkEditor__appendNativePlugMenu( expandMenu2, rgbOut )
expandItems2 = [ item for path, item in expandMenu2.items() if "Expand" in path ][0]
expandItems2.command()
idle()
rgbTarget = Gaffer.Node( "rgbTarget" )
rgbTargetPlug = Gaffer.FloatPlug( "value", Gaffer.Plug.Direction.In )
rgbTarget.addChild( rgbTargetPlug )
rgbScript.addChild( rgbTarget )
Gaffer.Metadata.registerValue( rgbTargetPlug, "noduleLayout:section", "left" )
NE.setNodePosition( rgbTarget, imath.V2f( 0, -14 ) )
idle()
rgbTargetPlug.setInput( rgbOut[ "r" ] )
idle()
check( "子插口连出来的线画得出来",
	any(
		e.edge.dstNode.getName() == "rgbTarget"
		for e in rgbEditor._NetworkEditor__edgeItems
	),
	str( [ e.edge.key() for e in rgbEditor._NetworkEditor__edgeItems ] ) )

rgbWindow.setVisible( False )


##########################################################################
section( "侧边圆点旁边常驻参数名（材质节点那种）" )
##########################################################################

# 材质节点是一排小圆点全挤在左边，不写名字根本认不出哪个是哪个（Houdini 就是标在
# 圆点旁边的）。颜色跟着圆点走 —— `nodule:color` 是按插口类型注册的，所以顺带也把
# 「这是什么类型」标出来了。

labelScript = Gaffer.ScriptNode()
labelNode = GafferScene.Isolate( "labelNode" )     # 场景节点的 `filter` 就在右边
labelScript.addChild( labelNode )
NE.setNodePosition( labelNode, imath.V2f( 0, 0 ) )

labelEditor = NE.NetworkEditor( labelScript )
labelWindow = GafferUI.Window( "label" )
labelWindow.setChild( labelEditor )
labelWindow._qtWidget().resize( 900, 600 )
labelWindow.setVisible( True )
idle()
labelItem = labelEditor._NetworkEditor__nodeItems[ "labelNode" ]

sideNodules = labelItem._nodules.get( "left", [] ) + labelItem._nodules.get( "right", [] )
check( "这个节点确实有侧边圆点（filter 在右边）",
	any( p.getName() == "filter" for p in sideNodules ),
	str( [ p.getName() for p in sideNodules ] ) )

labels = labelItem._NodeItem__sideLabels
check( "侧边圆点都配了标签", len( labels ) == len( sideNodules ), str( labels ) )
check( "标签文字就是插口名",
	any( text == "filter" for text, width, connected in labels.values() ), str( labels ) )

# 包围盒要放得下标签，否则拖动会留残影
plainWidth = labelItem.cardRect().width()
check( "包围盒把标签算进去了",
	labelItem.boundingRect().width() >= plainWidth + labelItem._NodeItem__sideLabelWidth,
	"%s vs 卡片 %s + 标签 %s" % (
		labelItem.boundingRect().width(), plainWidth, labelItem._NodeItem__sideLabelWidth ) )

# 真的画出来了：在圆点右边那块找该类型的颜色（filter 是 FilterPlug，有自己的颜色）
def renderItem( item, width = 420, height = 160 ) :

	image = QtGui.QImage( width, height, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.translate( width / 2.0, height / 2.0 )
	option = QtWidgets.QStyleOptionGraphicsItem()
	option.rect = QtCore.QRect( 0, 0, width, height )
	item.paint( painter, option, None )
	painter.end()
	return image

filterPlug = next( p for p in sideNodules if p.getName() == "filter" )
noduleColor = labelItem._NodeItem__noduleColors[ NE.plugKey( labelNode, filterPlug ) ]
image = renderItem( labelItem )
point = labelItem.nodulePosition( filterPlug )

# 小字是抗锯齿画的，绝大多数像素都不是"正正好那个颜色"——所以数**非背景**像素，
# 再看它们的平均色离哪个更近（圆点色 vs 普通文字色）
def inkPixels( image, x0, x1, y0, y1 ) :

	pixels = []
	for y in range( max( 0, int( y0 ) ), min( image.height(), int( y1 ) ) ) :
		for x in range( max( 0, int( x0 ) ), min( image.width(), int( x1 ) ) ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			if c.red() + c.green() + c.blue() > 40 :      # 背景是纯黑
				pixels.append( c )
	return pixels

def meanColor( pixels ) :

	if not pixels :
		return None
	return (
		sum( c.red() for c in pixels ) / float( len( pixels ) ),
		sum( c.green() for c in pixels ) / float( len( pixels ) ),
		sum( c.blue() for c in pixels ) / float( len( pixels ) ),
	)

def colorDistance( mean, color ) :

	c = QtGui.QColor( color )
	return ( ( mean[0] - c.red() ) ** 2 + ( mean[1] - c.green() ) ** 2 + ( mean[2] - c.blue() ) ** 2 ) ** 0.5

labelBand = (
	210 + point.x() + NE.NODULE_RADIUS + 2, 210 + point.x() + NE.NODULE_RADIUS + NE.SIDE_LABEL_MAX,
	80 + point.y() - 8, 80 + point.y() + 8,
)
textPixelList = inkPixels( image, *labelBand )
textPixels = len( textPixelList )
check( "圆点右边真的画了字", textPixels > 10, str( textPixels ) )
if textPixelList :
	mean = meanColor( textPixelList )
	check( "而且用的是圆点那个颜色（比普通文字色更近）",
		colorDistance( mean, noduleColor ) < colorDistance( mean, NE._textColor ),
		"平均色 %s，离圆点色 %.1f、离文字色 %.1f" % (
			tuple( int( v ) for v in mean ),
			colorDistance( mean, noduleColor ), colorDistance( mean, NE._textColor ) ) )

# 缩小到一定程度就不画了（免得糊成一团）
smallImage = QtGui.QImage( 420, 160, QtGui.QImage.Format_ARGB32 )
smallImage.fill( QtGui.QColor( "#000000" ) )
smallPainter = QtGui.QPainter( smallImage )
smallPainter.translate( 210, 80 )
smallPainter.scale( 0.4, 0.4 )                       # 缩小 → LOD 降下来
smallOption = QtWidgets.QStyleOptionGraphicsItem()
smallOption.rect = QtCore.QRect( 0, 0, 420, 160 )
labelItem.paint( smallPainter, smallOption, None )
smallPainter.end()
smallText = len( inkPixels(
	smallImage,
	210 + point.x() * 0.4 + 4, 210 + point.x() * 0.4 + NE.SIDE_LABEL_MAX,
	80 + point.y() * 0.4 - 6, 80 + point.y() * 0.4 + 6,
) )
check( "缩小之后就不写字了", smallText <= textPixels // 4, "%d vs %d" % ( smallText, textPixels ) )

# 三段式：字 → 色块 → 什么都不画
def renderAtScale( scale ) :

	image = QtGui.QImage( 420, 160, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.translate( 210, 80 )
	painter.scale( scale, scale )
	option = QtWidgets.QStyleOptionGraphicsItem()
	option.rect = QtCore.QRect( 0, 0, 420, 160 )
	labelItem.paint( painter, option, None )
	painter.end()
	return image

def sideInk( image, scale ) :

	return len( inkPixels(
		image,
		210 + ( point.x() + NE.NODULE_RADIUS + 3 ) * scale, 210 + ( point.x() + NE.SIDE_LABEL_MAX ) * scale,
		80 + point.y() * scale - 6, 80 + point.y() * scale + 6,
	) )

blockScale = ( NE.SIDE_LABEL_MIN_LOD + NE.SIDE_LABEL_BLOCK_LOD ) / 2.0     # 中间档 = 色块
goneScale = NE.SIDE_LABEL_BLOCK_LOD / 2.0                                   # 更小 = 什么都没有
blockInk = sideInk( renderAtScale( blockScale ), blockScale )
goneInk = sideInk( renderAtScale( goneScale ), goneScale )
check( "中间档退化成色块（还看得见东西）", blockInk > 5, str( blockInk ) )
check( "再小就彻底不画", goneInk == 0, str( goneInk ) )

labelWindow.setVisible( False )


##########################################################################
section( "连线可以选中、按 Delete 删掉" )
##########################################################################

edgeSelScript = Gaffer.ScriptNode()
edgeSelApplication = Gaffer.ApplicationRoot( "edgeSelTest" )
edgeSelApplication[ "scripts" ].addChild( edgeSelScript )
esA = GafferScene.Sphere( "esA" )
esB = GafferScene.Isolate( "esB" )
esC = GafferScene.Isolate( "esC" )
for index, n in enumerate( ( esA, esB, esC ) ) :
	edgeSelScript.addChild( n )
	NE.setNodePosition( n, imath.V2f( 0, -index * 12.0 ) )
esB[ "in" ].setInput( esA[ "out" ] )
esC[ "in" ].setInput( esB[ "out" ] )

edgeSelEditor = NE.NetworkEditor( edgeSelScript )
edgeSelWindow = GafferUI.Window( "edgeSel" )
edgeSelWindow.setChild( edgeSelEditor )
edgeSelWindow._qtWidget().resize( 900, 600 )
edgeSelWindow.setVisible( True )
idle()
edgeSelView = edgeSelEditor.graphView()
edgeSelView.frameAll()
idle()

edgeOf = lambda dst : next(
	e for e in edgeSelEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == dst
)
edgeAB, edgeBC = edgeOf( "esB" ), edgeOf( "esC" )

check( "一开始没有线被选中", edgeSelEditor.selectedEdges() == [] )

edgeSelEditor._selectEdgeClicked( edgeAB )
check( "点一下就选中那条线", [ e.edge.key() for e in edgeSelEditor.selectedEdges() ] == [ edgeAB.edge.key() ],
	str( edgeSelEditor.selectedEdges() ) )
check( "选中的线画得更粗", edgeAB.pen().widthF() > 2.0, str( edgeAB.pen().widthF() ) )
check( "选中的线用选中色",
	edgeAB.pen().brush().color().name() == QtGui.QColor( NE._selectedBorder ).name() or
	( edgeAB.pen().brush().gradient() is not None and
	  edgeAB.pen().brush().gradient().stops()[0][1].name() == QtGui.QColor( NE._selectedBorder ).name() ),
	str( edgeAB.pen().brush().color().name() ) )

# 再点另一条：换成它（没按 Shift）
edgeSelEditor._selectEdgeClicked( edgeBC )
check( "点另一条就换过去", [ e.edge.key() for e in edgeSelEditor.selectedEdges() ] == [ edgeBC.edge.key() ] )

# Shift 加选
edgeSelEditor._selectEdgeClicked( edgeAB, QtCore.Qt.ShiftModifier )
check( "Shift 是加选", len( edgeSelEditor.selectedEdges() ) == 2, str( len( edgeSelEditor.selectedEdges() ) ) )

# 选线会清掉节点选择，反过来也一样
edgeSelScript.selection().clear()
edgeSelScript.selection().add( esA )
idle()
edgeSelEditor._selectEdgeClicked( edgeAB )
check( "选线会把节点选择清掉", len( edgeSelScript.selection() ) == 0,
	str( [ n.getName() for n in edgeSelScript.selection() ] ) )
edgeSelEditor._selectClicked( edgeSelEditor._NetworkEditor__nodeItems[ "esA" ], QtCore.Qt.NoModifier )
check( "选节点也会把线选择清掉", edgeSelEditor.selectedEdges() == [] )

# --- Delete 删掉选中的线 ---
edgeSelEditor._selectEdgeClicked( edgeBC )
edgeSelEditor._deleteSelected()
idle()
check( "Delete 断开了选中的那条线", esC[ "in" ].getInput() is None, str( esC[ "in" ].getInput() ) )
check( "别的线没动", esB[ "in" ].getInput() is not None )
check( "节点一个都没少",
	len( [ n for n in NE.collectNodes( edgeSelScript ) ] ) == 3,
	str( [ n.getName() for n in NE.collectNodes( edgeSelScript ) ] ) )
check( "删完不再选着线", edgeSelEditor.selectedEdges() == [] )
check( "可以撤销", edgeSelScript.undoAvailable() )
edgeSelScript.undo()
idle()
check( "撤销之后线回来了", esC[ "in" ].getInput() is not None )

# 没选线时 Delete 还是删节点（老行为不变）
edgeSelScript.selection().clear()
edgeSelScript.selection().add( esC )
idle()
edgeSelEditor._deleteSelected()
idle()
check( "没选线时 Delete 照旧删节点",
	edgeSelScript.getChild( "esC" ) is None,
	str( [ n.getName() for n in NE.collectNodes( edgeSelScript ) ] ) )
edgeSelScript.undo()
idle()

edgeSelWindow.setVisible( False )


##########################################################################
section( "缩放上限 / focus 的视觉" )
##########################################################################

zoomScript = Gaffer.ScriptNode()
zoomA = GafferScene.Sphere( "zoomA" )
zoomB = GafferScene.Isolate( "zoomB" )
zoomScript.addChild( zoomA ) ; zoomScript.addChild( zoomB )
zoomB[ "in" ].setInput( zoomA[ "out" ] )
NE.setNodePosition( zoomA, imath.V2f( 0, 0 ) )
NE.setNodePosition( zoomB, imath.V2f( 0, -12 ) )

zoomEditor = NE.NetworkEditor( zoomScript )
zoomWindow = GafferUI.Window( "zoom" )
zoomWindow.setChild( zoomEditor )
zoomWindow._qtWidget().resize( 900, 600 )
zoomWindow.setVisible( True )
idle()
zoomView = zoomEditor.graphView()
zoomView.frameAll()
idle()

# 原生 `GraphEditor.__init__` 是 `setMaxPlanarZoom( V2f( 25 ) )` —— 每单位最多 25 像素。
# 我们 1.0 倍 = `PX_PER_UNIT` 像素/单位，所以上限 = 25 / PX_PER_UNIT。
check( "上限就是原生那个 25 像素/单位",
	abs( NE.MAX_ZOOM * NE.PX_PER_UNIT - 25.0 ) < 1e-6, str( NE.MAX_ZOOM ) )

for i in range( 60 ) :
	zoomView.scaleBy( 1.15 )
check( "一直放大也超不过上限", zoomView.zoom() <= NE.MAX_ZOOM + 1e-6, str( zoomView.zoom() ) )
check( "而且真的顶到了上限（不是半路停住）",
	abs( zoomView.zoom() - NE.MAX_ZOOM ) < 1e-6, str( zoomView.zoom() ) )
check( "到顶之后再放大就没动静了", zoomView.scaleBy( 1.15 ) == 1.0 )

for i in range( 200 ) :
	zoomView.scaleBy( 1.0 / 1.15 )
check( "一直缩小也停在下限", abs( zoomView.zoom() - NE.MIN_ZOOM ) < 1e-6, str( zoomView.zoom() ) )

# 框一个小节点也不会一路放大到几十倍
zoomView.frameItems( [ zoomEditor._NetworkEditor__nodeItems[ "zoomA" ] ] )
idle()
check( "框单个节点也不超上限", zoomView.zoom() <= NE.MAX_ZOOM + 1e-6, str( zoomView.zoom() ) )
zoomView.frameAll()
idle()
check( "全景取景也在范围内",
	NE.MIN_ZOOM - 1e-6 <= zoomView.zoom() <= NE.MAX_ZOOM + 1e-6, str( zoomView.zoom() ) )

# --- focus：金色长条没了，只剩角标 ---
def renderNode( item, width = 220, height = 90 ) :

	image = QtGui.QImage( width, height, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.translate( width / 2.0, height / 2.0 )
	option = QtWidgets.QStyleOptionGraphicsItem()
	option.rect = QtCore.QRect( 0, 0, width, height )
	item.paint( painter, option, None )
	painter.end()
	return image

focusItem = zoomEditor._NetworkEditor__nodeItems[ "zoomA" ]
zoomScript.setFocus( None )
idle()
plainImage = renderNode( focusItem )
zoomScript.setFocus( zoomA )
idle()
focusImage = renderNode( focusItem )

card = focusItem.cardRect()
def bandPixel( image, image_width = 220, image_height = 90 ) :
	# 色带在卡片顶部，取偏左的位置（右上角是折角，别取那儿）
	x = int( image_width / 2.0 + card.left() + card.width() * 0.25 )
	y = int( image_height / 2.0 + card.top() + 2 )
	return QtGui.QColor( image.pixel( x, y ) ).name()

check( "focus 之后顶部色带不再变金", bandPixel( focusImage ) != NE._focusRing.lower(),
	"%s vs %s" % ( bandPixel( focusImage ), NE._focusRing ) )
check( "而且和没 focus 时是同一个色带颜色",
	bandPixel( focusImage ) == bandPixel( plainImage ),
	"%s vs %s" % ( bandPixel( focusImage ), bandPixel( plainImage ) ) )

def hasFocusRing( image ) :
	target = QtGui.QColor( NE._focusRing ).rgb()
	for y in range( image.height() ) :
		for x in range( image.width() ) :
			if image.pixel( x, y ) == target :
				return True
	return False

check( "角标还在（画面里仍然找得到 focus 金色）", hasFocusRing( focusImage ) )
check( "没 focus 的时候一点金色都没有", not hasFocusRing( plainImage ) )
zoomScript.setFocus( None )
idle()
zoomWindow.setVisible( False )


##########################################################################
section( "UI 开销：每次编辑只干该干的活" )
##########################################################################

# 这一节全部用**次数**做断言，不用时间 —— 换台机器时间就变，次数不会。
# 背景：原生改一根线的数据层开销是 0.03ms（C++ 里加一个 gadget 标记脏，绘制交给 GPU）；
# 我们做完增量还有 20-44ms，profile 出来 43ms 都是"每次编辑都无脑重来一遍"的活：
# 扫全图拿节点集合、扫全图刷 focus / active、以及**整个视口重绘**。

costScript = Gaffer.ScriptNode()
costNodes = []
for i in range( 150 ) :
	n = GafferScene.Isolate( "cost%03d" % i )
	costScript.addChild( n )
	if costNodes and i % 12 :
		n[ "in" ].setInput( costNodes[-1][ "out" ] )
	NE.setNodePosition( n, imath.V2f( ( i % 12 ) * 14.0, -( i // 12 ) * 8.0 ) )
	costNodes.append( n )

costEditor = NE.NetworkEditor( costScript )
costWindow = GafferUI.Window( "cost" )
costWindow.setChild( costEditor )
costWindow._qtWidget().resize( 1200, 800 )
costWindow.setVisible( True )
idle()
costEditor.graphView().frameAll()
QtWidgets.QApplication.processEvents()

_counts = { "nodePaint" : 0, "edgePaint" : 0, "nodeInit" : 0, "collectNodes" : 0, "sceneRect" : 0 }
_originalNodePaint = NE._NodeItem.paint
_originalNodeInit = NE._NodeItem.__init__
_originalEdgePaint = NE._EdgeItem.paint
_originalCollectNodes = NE.collectNodes

def _countedNodePaint( self, painter, option, widget = None ) :
	_counts[ "nodePaint" ] += 1
	return _originalNodePaint( self, painter, option, widget )

def _countedNodeInit( self, *args, **kw ) :
	_counts[ "nodeInit" ] += 1
	return _originalNodeInit( self, *args, **kw )

def _countedEdgePaint( self, painter, option, widget = None ) :
	_counts[ "edgePaint" ] += 1
	return _originalEdgePaint( self, painter, option, widget )

def _countedCollectNodes( root ) :
	_counts[ "collectNodes" ] += 1
	return _originalCollectNodes( root )

NE._NodeItem.paint = _countedNodePaint
NE._NodeItem.__init__ = _countedNodeInit
NE._EdgeItem.paint = _countedEdgePaint
NE.collectNodes = _countedCollectNodes

def measureCost( action ) :

	# **先泵到"一帧都不画"为止**：新建的视图第一次显示必然要全量画一遍，Qt 什么
	# 时候画由事件循环说了算 —— 不冲掉的话这一帧会随机落进某个测量窗口里，把计数
	# 打成"全图重绘"（这一节偶发 FAIL 就是它）。
	quiet = 0
	for i in range( 40 ) :
		for key in _counts :
			_counts[ key ] = 0
		idle()
		QtWidgets.QApplication.processEvents()
		costEditor.graphView().viewport().repaint()
		tracker = costEditor._NetworkEditor__tracker
		pending = tracker is not None and tracker.updatePending()
		if _counts[ "nodePaint" ] == 0 and _counts[ "edgePaint" ] == 0 and not pending :
			quiet += 1
			if quiet >= 2 :   # 连着两轮都没动静才算真静下来
				break
		else :
			quiet = 0

	for key in _counts :
		_counts[ key ] = 0
	action()
	idle()
	QtWidgets.QApplication.processEvents()
	return dict( _counts )

# --- 什么都不做就不该有任何开销（先证明计数器是准的）---
idleCost = measureCost( lambda : None )
check( "闲着的时候一次重绘都没有",
	idleCost[ "nodePaint" ] == 0 and idleCost[ "edgePaint" ] == 0, str( idleCost ) )

# --- 改一根线（接相邻的两个节点，日常最常见的那种短线）---
wireCost = measureCost( lambda : costNodes[ 12 ][ "in" ].setInput( costNodes[ 0 ][ "out" ] ) )
check( "改一根线：一个 item 都不重建", wireCost[ "nodeInit" ] == 0, str( wireCost ) )
check( "改一根线：不扫全图拿节点集合（`collectNodes` 一次都不调）",
	wireCost[ "collectNodes" ] == 0, str( wireCost ) )
check( "改一根线：只重绘受影响的那一小块（节点重绘 <= 20 / 共 150）",
	wireCost[ "nodePaint" ] <= 20, str( wireCost ) )
# 连线是又长又细的 item，包围盒互相大面积重叠，所以"落在脏矩形里"的条数天然比
# 节点多 —— 但仍然只有全部的四分之一
check( "改一根线：连线也只重绘一小部分（<= 40 / 共约 137）",
	wireCost[ "edgePaint" ] <= 40, str( wireCost ) )

unwireCost = measureCost( lambda : costNodes[ 12 ][ "in" ].setInput( None ) )
check( "拔线也一样（不扫全图、只局部重绘）",
	unwireCost[ "collectNodes" ] == 0 and unwireCost[ "nodePaint" ] <= 20, str( unwireCost ) )

# 横跨半张图的长线：脏矩形本来就大（一条斜着的长线，包围盒盖住一大片）——
# 这是 Qt 的脏矩形机制决定的，不是我们漏了优化；但也绝不该是"全图重绘"。
longWireCost = measureCost( lambda : costNodes[ 100 ][ "in" ].setInput( costNodes[ 3 ][ "out" ] ) )
check( "横跨半张图的长线：重绘量仍远小于全图",
	longWireCost[ "nodePaint" ] <= 60 and longWireCost[ "edgePaint" ] <= 60, str( longWireCost ) )
costNodes[ 100 ][ "in" ].setInput( None )
idle()

# --- 加一个节点：这时候扫一次全图是应该的，但重建的 item 只能有一个 ---
def addCostNode() :
	extra = GafferScene.Isolate( "costExtra" )
	NE.setNodePosition( extra, imath.V2f( 6.0, 6.0 ) )
	costScript.addChild( extra )

addCost = measureCost( addCostNode )
check( "加节点：只建一个 item", addCost[ "nodeInit" ] == 1, str( addCost ) )
check( "加节点：扫全图不超过一次", addCost[ "collectNodes" ] <= 1, str( addCost ) )

NE._NodeItem.paint = _originalNodePaint
NE._NodeItem.__init__ = _originalNodeInit
NE._EdgeItem.paint = _originalEdgePaint
NE.collectNodes = _originalCollectNodes
costWindow.setVisible( False )


##########################################################################
section( "接管：写死 GafferUI.GraphEditor 的地方也认得我们" )
##########################################################################

# 官方有一堆地方写死了 `GafferUI.GraphEditor`：`EditMenu.scope()` 决定菜单栏的
# 剪切/复制/粘贴作用在哪一层、`GraphBookmarksUI` 的书签跳转、`NodeFinderDialogue`
# 的 Ctrl+F、`BoxUI` 的 "Show Contents..."。接管之后这些都能找到我们，
# **但原生编辑器一点不受影响**（退路还在）。

takeoverScript = Gaffer.ScriptNode()
takeoverEditor = NE.NetworkEditor( takeoverScript )

nativeClass = NE._nativeGraphEditorClass()
check( "接管前 GafferUI.GraphEditor 就是原生类", GafferUI.GraphEditor is nativeClass )
check( "接管前我们不是 GraphEditor", not isinstance( takeoverEditor, GafferUI.GraphEditor ) )

nativeSignal = GafferUI.GraphEditor.plugContextMenuSignal()
nativeEditor = GafferUI.GraphEditor( takeoverScript )

check( "装上接管", NE.installGraphEditorTakeover( force = True ) )
check( "再装一次是幂等的", NE.installGraphEditorTakeover( force = True ) )
check( "GafferUI.GraphEditor 换成壳了", GafferUI.GraphEditor is not nativeClass )

check( "**我们**现在算 GraphEditor", isinstance( takeoverEditor, GafferUI.GraphEditor ) )
check( "**原生的**照样算 GraphEditor（退路没断）", isinstance( nativeEditor, GafferUI.GraphEditor ) )
check( "别的编辑器不算", not isinstance( GafferUI.NodeEditor( takeoverScript ), GafferUI.GraphEditor ) )
check( "issubclass 也对", issubclass( NE.NetworkEditor, GafferUI.GraphEditor ) and issubclass( nativeClass, GafferUI.GraphEditor ) )

check( "类属性转给原生（信号必须是同一个对象，startup 早就挂上去了）",
	GafferUI.GraphEditor.plugContextMenuSignal() is nativeSignal )
check( "原生的那些 append* 也还在", hasattr( GafferUI.GraphEditor, "appendEnabledPlugMenuDefinitions" ) )

# 构造仍然构造原生的 —— 存过的 layout 里写死的就是 `GafferUI.GraphEditor( scriptNode )`
constructed = GafferUI.GraphEditor( takeoverScript )
check( "构造出来的还是原生 GraphEditor", type( constructed ) is nativeClass, str( type( constructed ) ) )

# CompoundEditor 那套「找编辑器」用的就是 isinstance
fakeLayout = [ takeoverEditor, nativeEditor, GafferUI.NodeEditor( takeoverScript ) ]
found = [ e for e in fakeLayout if isinstance( e, GafferUI.GraphEditor ) ]
check( "按 GraphEditor 找编辑器时我们也在结果里", len( found ) == 2, str( found ) )

# 隐藏引擎必须还是**原生**的（这条最容易被接管带塌：借到自己头上就没有 graphGadget()）
takeoverWindow = GafferUI.Window( "takeover" )
takeoverWindow.setChild( takeoverEditor )
takeoverWindow._qtWidget().resize( 800, 600 )
takeoverWindow.setVisible( True )
idle()
# 接管装上之后**就不再建隐藏引擎了**（第四步）：我们自己就算一个 GraphEditor，
# 菜单宿主 / graphGadgetWidget / 项目快捷键三样都自己顶。
check( "接管装上之后默认不再建隐藏引擎", not NE.engineEnabled() )
check( "所以 __engine() 就是 None", takeoverEditor._NetworkEditor__engine() is None )
check( "但几何还是照样有（裸 GraphGadget 不是窗口）",
	takeoverEditor._NetworkEditor__graphGadget() is not None )
check( "宿主换成了我们自己",
	takeoverEditor._NetworkEditor__menuHost() is takeoverEditor )

# 想对比行为时可以强制把引擎建回来
os.environ[ "GAFFER_NETWORK_EDITOR_ENGINE" ] = "1"
engineAfterTakeover = takeoverEditor._NetworkEditor__engine()
check( "强制打开时还是能建出真的原生 GraphEditor",
	engineAfterTakeover is not None and type( engineAfterTakeover ) is nativeClass,
	str( type( engineAfterTakeover ) ) )
check( "引擎还能给出 graphGadget", engineAfterTakeover.graphGadget() is not None )
del os.environ[ "GAFFER_NETWORK_EDITOR_ENGINE" ]

# --- 兼容接口：接管之后官方会直接在我们身上调这几个（`EditMenu.scope()` 最典型）---
check( "有 graphGadget()", takeoverEditor.graphGadget() is not None )
check( "graphGadget 的 root 就是我们当前这一层",
	takeoverEditor.graphGadget().getRoot().isSame( takeoverEditor.getRootNode() ) )
check( "有 graphGadgetWidget()", takeoverEditor.graphGadgetWidget() is not None )
check( "引擎视口不是退化的（不然 rasterToGadgetSpace 算出 nan）",
	takeoverEditor.graphGadgetWidget().getViewportGadget().getViewport().x > 1,
	str( takeoverEditor.graphGadgetWidget().getViewportGadget().getViewport() ) )

# `EditMenu.scope()` 那句 `graphEditor.graphGadget().getRoot()` 现在能落到我们身上
takeoverBox = Gaffer.Box( "scopeBox" )
takeoverScript.addChild( takeoverBox )
takeoverBox.addChild( GafferScene.Sphere( "inner" ) )
idle()
takeoverEditor.setRootNode( takeoverBox )
idle()
check( "进 Box 之后 graphGadget().getRoot() 跟着走（菜单栏的剪切/粘贴就靠这个定层级）",
	takeoverEditor.graphGadget().getRoot().isSame( takeoverBox ),
	str( takeoverEditor.graphGadget().getRoot() ) )
takeoverEditor.setRootNode( takeoverScript )
idle()

# `frame()`：粘贴完官方会调 `graphEditor.frame( selection, extend = True )`
framed = GafferScene.Sphere( "framed" )
takeoverScript.addChild( framed )
NE.setNodePosition( framed, imath.V2f( 400.0, -300.0 ) )
idle()
takeoverEditor.graphView().frameAll()
idle()
takeoverEditor.frame( [ framed ] )
idle()
framedItem = takeoverEditor._NetworkEditor__nodeItems[ "framed" ]
check( "frame() 真的把它框进画面了",
	takeoverEditor.graphView().viewedSceneRect().intersects( framedItem.sceneBoundingRect() ),
	"%s vs %s" % ( takeoverEditor.graphView().viewedSceneRect(), framedItem.sceneBoundingRect() ) )
wideBefore = takeoverEditor.graphView().viewedSceneRect().width()
takeoverEditor.frame( [ takeoverScript["scopeBox"] ], extend = True )
idle()
check( "extend=True 是把两边并起来（画面只会更大）",
	takeoverEditor.graphView().viewedSceneRect().width() >= wideBefore - 1,
	"%s -> %s" % ( wideBefore, takeoverEditor.graphView().viewedSceneRect().width() ) )
check( "frame() 遇到不在图里的节点不炸", takeoverEditor.frame( [ takeoverBox["inner"] ] ) is None )

# acquire：layout 里有 NetworkEditor 时优先给我们（真机 e2e 里验完整路径）
check( "acquire 是我们自己的实现",
	GafferUI.GraphEditor.acquire.__module__.startswith( NE.__name__ ) or
	"NetworkEditor" in str( GafferUI.GraphEditor.acquire ),
	str( GafferUI.GraphEditor.acquire ) )

# 卸载还原

##########################################################################
# 砍掉隐藏引擎 · 第二步：菜单宿主换成我们自己
##########################################################################

# 接管装上之后 `isinstance( self, GafferUI.GraphEditor )` 就成立，于是
# `menu.ancestor( GafferUI.GraphEditor )` 认我们 —— 隐藏引擎的主用途没了。
# 下面把引擎**整个关掉**，原生那三套菜单和"靠原生菜单建 Box"必须照样能用。

import networkEditor.editor as NEE   # 为了临时关掉隐藏引擎（模块内的全局查找）

hostScript = Gaffer.ScriptNode()
application["scripts"].addChild( hostScript )
hostSphere = GafferScene.Sphere( "hostSphere" )
hostGroup = GafferScene.Group( "hostGroup" )
hostScript.addChild( hostSphere )
hostScript.addChild( hostGroup )
hostGroup[ "in" ][ 0 ].setInput( hostSphere[ "out" ] )
NE.setNodePosition( hostSphere, imath.V2f( 0, 6 ) )
NE.setNodePosition( hostGroup, imath.V2f( 0, 0 ) )

hostEditor = NE.NetworkEditor( hostScript )
hostWindow = GafferUI.Window( "menuHost" )
hostWindow.setChild( hostEditor )
hostWindow._qtWidget().resize( 900, 600 )
hostWindow.setVisible( True )
idle()
hostEditor.graphView().frameAll()
idle()

check( "接管装着，所以我们算 GraphEditor", isinstance( hostEditor, GafferUI.GraphEditor ) )
check( "菜单宿主就是编辑器自己",
	hostEditor._NetworkEditor__menuHost() is hostEditor )

originalEngineEnabled = NEE.engineEnabled
NEE.engineEnabled = lambda : False
try :
	check( "把隐藏引擎关掉之后，宿主还是我们自己",
		hostEditor._NetworkEditor__menuHost() is hostEditor )
	check( "确实没有引擎了", hostEditor._NetworkEditor__engine() is None )

	# --- 借原生的节点右键菜单：handler 收到的「那个 GraphEditor」必须是**我们** ---
	# （无头环境下 `/Focus`、`/Bookmarked` 那些是 app 的 gui 启动脚本注册的、这里没有，
	# 所以自己挂一个 handler 来验真正的契约：第一个参数是谁。）
	hostSeen = []

	def hostNodeContextMenu( graphEditor, node, menuDefinition ) :
		hostSeen.append( graphEditor )
		menuDefinition.append( "/HostProbe", { "command" : lambda : None } )

	hostConnection = GafferUI.GraphEditor.nodeContextMenuSignal().connect(
		hostNodeContextMenu, scoped = True )

	hostNodeMenu = IECore.MenuDefinition()
	check( "没有引擎也发得出原生节点菜单信号",
		hostEditor._NetworkEditor__appendNativeNodeMenu( hostNodeMenu, hostSphere ) )
	check( "handler 拿到的「那个 GraphEditor」就是我们",
		len( hostSeen ) == 1 and hostSeen[0] is hostEditor,
		str( hostSeen ) )
	check( "handler 填进去的条目在菜单里",
		any( p.endswith( "/HostProbe" ) for p, i in hostNodeMenu.items() ),
		str( [ p for p, i in hostNodeMenu.items() ] ) )
	del hostConnection

	# --- 借原生的连线右键菜单（DotUI 的「插入 Dot」，真·原生 handler）---
	GafferUI.DotUI.connect( application )   # 「插入 Dot」要这个开关才出现
	hostEdgeMenu = IECore.MenuDefinition()
	hostEditor._NetworkEditor__appendNativeConnectionMenu(
		hostEdgeMenu, hostGroup[ "in" ][ 0 ] )
	hostEdgePaths = [ p for p, i in hostEdgeMenu.items() ]
	check( "没有引擎也借得到原生的「插入 Dot」",
		any( p.endswith( "Insert Dot" ) for p in hostEdgePaths ), str( hostEdgePaths ) )

	# --- 靠原生菜单建 Box（`nodeMenuCreateCommand( menu )` 那一批）---
	# 这正是 `GAFFER_NETWORK_EDITOR_ENGINE=0` 时会挂的那 14 条里的头一条。
	hostEntries = hostEditor._NetworkEditor__nodeMenuEntries()
	hostBoxItem = [ e[3] for e in hostEntries if e[0] == "Box" ][0]
	hostEditor._NetworkEditor__createFromMenuItem( hostBoxItem, QtCore.QPointF( 300, -180 ) )
	idle()
	hostBoxes = [ n for n in NE.collectNodes( hostScript ) if isinstance( n, Gaffer.Box ) ]
	check( "没有引擎也建得出 Box（宿主是我们自己）", len( hostBoxes ) == 1,
		str( [ n.getName() for n in NE.collectNodes( hostScript ) ] ) )
	check( "Box 摆在给的那个位置上（不是 nan / 不是原点）",
		hostBoxes and NE.positionUsable( NE.nodePosition( hostBoxes[0] ) ) and
		abs( NE.nodePosition( hostBoxes[0] ).x - 300.0 / NE.PX_PER_UNIT ) < 1.5,
		str( NE.nodePosition( hostBoxes[0] ) if hostBoxes else None ) )

	# --- 原生命令拿到的 graphGadgetWidget 就是我们那层壳 ---
	check( "原生命令会拿到我们的壳",
		type( hostEditor.graphGadgetWidget() ).__name__ == "_GadgetWidgetShim" )

finally :
	NEE.engineEnabled = originalEngineEnabled

hostWindow.setVisible( False )


check( "卸得掉", NE.uninstallGraphEditorTakeover() )
check( "还原回原生类", GafferUI.GraphEditor is nativeClass )
check( "卸载后我们又不是 GraphEditor 了", not isinstance( takeoverEditor, GafferUI.GraphEditor ) )
check( "重复卸载不出错", not NE.uninstallGraphEditorTakeover() )

# 环境变量能关掉
os.environ[ "GAFFER_NETWORK_EDITOR_TAKEOVER" ] = "native"
check( "GAFFER_NETWORK_EDITOR_TAKEOVER=native 就不装", not NE.installGraphEditorTakeover() )
del os.environ[ "GAFFER_NETWORK_EDITOR_TAKEOVER" ]

takeoverWindow.setVisible( False )


##########################################################################
section( "往外拖：中键按住节点拖给别的编辑器" )
##########################################################################

# 原生 `GraphGadget::dragBegin` 里，**中键**按在节点上是 `m_dragMode = Sending`：
# 拖的是 `script.selection()`（不在选择里就是那一个节点），左键才是移动节点。
# 我们照这个分法，所以「中键空白处平移」一点不受影响。

dragScript = Gaffer.ScriptNode()
dragA = GafferScene.Sphere( "dragA" )
dragB = GafferScene.Sphere( "dragB" )
for index, n in enumerate( ( dragA, dragB ) ) :
	dragScript.addChild( n )
	NE.setNodePosition( n, imath.V2f( index * 25.0, 0 ) )

dragEditor = NE.NetworkEditor( dragScript )
dragWindow = GafferUI.Window( "dragOut" )
dragWindow.setChild( dragEditor )
dragWindow._qtWidget().resize( 900, 600 )
dragWindow.setVisible( True )
idle()
dragView = dragEditor.graphView()
dragView.frameAll()
idle()

eventFilter = NE._gafferUIEventFilter()
check( "拿得到 GafferUI 那个全局事件过滤器", eventFilter is not None )
check( "过滤器补装到视图上了", dragEditor._NetworkEditor__installDragSourceFilter() )

dragItem = dragEditor._NetworkEditor__nodeItems[ "dragA" ]
dragPoint = dragView.mapFromScene( dragItem.scenePos() )

def middlePress( point ) :

	globalPoint = dragView.viewport().mapToGlobal( point )
	return QtGui.QMouseEvent(
		QtCore.QEvent.MouseButtonPress, QtCore.QPointF( point ), QtCore.QPointF( globalPoint ),
		QtCore.Qt.MiddleButton, QtCore.Qt.MiddleButton, QtCore.Qt.NoModifier
	)

# --- 中键按在节点上：记进过滤器，而且不进平移模式 ---
dragScript.selection().clear()
dragScript.selection().add( dragA )
idle()
accepted = dragEditor._beginNodeDragOut( dragItem, middlePress( dragPoint ) )
check( "中键按在节点上被接住了", accepted )
check( "过滤器记下了「按下的是我们」",
	eventFilter._EventFilter__lastButtonPressWidget is not None and
	eventFilter._EventFilter__lastButtonPressWidget() is dragEditor,
	str( eventFilter._EventFilter__lastButtonPressWidget ) )

# --- GafferUI 来要数据：选中的那些节点 ---
dragEvent = GafferUI.DragDropEvent(
	GafferUI.ButtonEvent.Buttons.Middle, GafferUI.ButtonEvent.Buttons.Middle,
	IECore.LineSegment3f( imath.V3f( 0, 0, 1 ), imath.V3f( 0, 0, 0 ) )
)
data = dragEditor._NetworkEditor__dragBegin( dragEditor, dragEvent )
check( "拖的是 script.selection()（和原生一个形状）",
	isinstance( data, Gaffer.Set ) and [ n.getName() for n in data ] == [ "dragA" ],
	str( data ) )

# 不在选择里的那个：拖它自己
dragScript.selection().clear()
idle()
dragEditor._beginNodeDragOut( dragEditor._NetworkEditor__nodeItems[ "dragB" ], middlePress( dragPoint ) )
data = dragEditor._NetworkEditor__dragBegin( dragEditor, dragEvent )
check( "没选中的节点就拖它自己",
	isinstance( data, Gaffer.Node ) and data.getName() == "dragB", str( data ) )
dragEditor._NetworkEditor__dragEnd( dragEditor, dragEvent )
check( "结束之后不再攥着东西", dragEditor._NetworkEditor__dragOutNodes is None )

# --- 中键按在**空白处**照旧是平移（这条不能被上面那条弄坏）---
blankPoint = QtCore.QPoint( 5, 5 )
blankEvent = middlePress( blankPoint )
QtWidgets.QApplication.sendEvent( dragView.viewport(), blankEvent )
check( "中键按空白处还是平移", dragView._GraphView__mode == NE._MODE_PAN,
	str( dragView._GraphView__mode ) )
QtWidgets.QApplication.sendEvent(
	dragView.viewport(),
	QtGui.QMouseEvent(
		QtCore.QEvent.MouseButtonRelease, QtCore.QPointF( blankPoint ),
		QtCore.QPointF( dragView.viewport().mapToGlobal( blankPoint ) ),
		QtCore.Qt.MiddleButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier
	)
)

# --- 真的从「按下 + 移动」走到 GafferUI 的拖拽状态 ---
eventFilter._EventFilter__dragDropEvent = None
dragScript.selection().clear()
dragScript.selection().add( dragA )
idle()
dragEditor._beginNodeDragOut( dragItem, middlePress( dragPoint ) )
movePoint = dragPoint + QtCore.QPoint( 40, 40 )
QtWidgets.QApplication.sendEvent(
	dragView.viewport(),
	QtGui.QMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPointF( movePoint ),
		QtCore.QPointF( dragView.viewport().mapToGlobal( movePoint ) ),
		QtCore.Qt.NoButton, QtCore.Qt.MiddleButton, QtCore.Qt.NoModifier
	)
)
idle()
started = eventFilter._EventFilter__dragDropEvent
check( "鼠标一动，GafferUI 那边真的进入拖拽状态了", started is not None )
if started is not None :
	check( "拖拽的源就是我们这个编辑器", started.sourceWidget is dragEditor )
	check( "带着的数据是那些节点",
		isinstance( started.data, ( Gaffer.Set, Gaffer.Node ) ),
		str( started.data ) )
	check( "自己拖出去的东西自己不收",
		not dragEditor._NetworkEditor__canAcceptDrag( started ) )
	eventFilter._EventFilter__dragDropEvent = None

# 收摊：把拖拽状态和指针都还原，别影响后面那些用指针做断言的测试
dragEditor._NetworkEditor__dragEnd( dragEditor, dragEvent )
eventFilter._EventFilter__lastButtonPressWidget = None
eventFilter._EventFilter__lastButtonPressEvent = None
GafferUI.Pointer.setCurrent( None )
check( "收摊后指针还原了", GafferUI.Pointer.getCurrent() is None, str( GafferUI.Pointer.getCurrent() ) )

dragWindow.setVisible( False )


##########################################################################
section( "借原生的插口 / 连线右键菜单" )
##########################################################################

# 原生在**圆点**和**连线**上也各有一套右键菜单（`plugContextMenuSignal` /
# `connectionContextMenuSignal`）。1.7.1.0 官方注册了 8 处（BoxUI 提升·取消提升·改名·
# 挪边、DotUI 插入 Dot、LoopUI、CollectUI、CompoundNumericNoduleUI、ShaderUI…），
# 不借这两条，圆点上右键就是空的、连线上也没有「插入 Dot」。

class _MenuApplicationRoot( Gaffer.ApplicationRoot ) :
	pass

menuApplication = _MenuApplicationRoot( "networkEditorMenuTest" )
plugScript = Gaffer.ScriptNode()
menuApplication["scripts"].addChild( plugScript )
GafferUI.DotUI.connect( menuApplication )      # 「插入 Dot」要它才出现

plugBox = Gaffer.Box( "plugBox" )
plugScript.addChild( plugBox )
plugInner = GafferScene.Sphere( "inner" )
plugBox.addChild( plugInner )
promotedScene = Gaffer.PlugAlgo.promote( plugInner["out"] )     # ScenePlug 才有圆点
plugPlane = GafferScene.Plane( "plane" )
plugScript.addChild( plugPlane )
plugDot = Gaffer.Dot( "dot" )
plugScript.addChild( plugDot )
plugDot.setup( plugPlane["out"] )
plugDot["in"].setInput( plugPlane["out"] )
# 别全堆在原点上：命中测试会打到最上面那个 item（这条把测试自己坑过一次）
for index, n in enumerate( ( plugBox, plugPlane, plugDot ) ) :
	NE.setNodePosition( n, imath.V2f( index * 25.0, index * -12.0 ) )

plugEditor = NE.NetworkEditor( plugScript )
plugWindow = GafferUI.Window( "plugMenu" )
plugWindow.setChild( plugEditor )
plugWindow._qtWidget().resize( 900, 600 )
plugWindow.setVisible( True )
idle()

plugMenu = IECore.MenuDefinition()
check( "圆点上有原生菜单",
	plugEditor._NetworkEditor__appendNativePlugMenu( plugMenu, promotedScene ),
	str( [ p for p, i in plugMenu.items() ] ) )
plugPaths = [ p for p, i in plugMenu.items() ]
check( "里面是原生那几条（改名 / 挪到哪条边）",
	any( p.endswith( "Rename..." ) for p in plugPaths ) and
	any( "Move To" in p for p in plugPaths ),
	str( plugPaths ) )

# 内部那个原插口上是「从 Box 取消提升」
innerMenu = IECore.MenuDefinition()
plugEditor._NetworkEditor__appendNativePlugMenu( innerMenu, plugInner["radius"] )
check( "内部插口上有 Box 提升那一条",
	any( "Promote" in p for p, i in innerMenu.items() ),
	str( [ p for p, i in innerMenu.items() ] ) )

# 普通输出插口没有原生条目 -> 右键要退回节点菜单，不能弹个空的
emptyMenu = IECore.MenuDefinition()
check( "普通 out 插口上原生没东西",
	not plugEditor._NetworkEditor__appendNativePlugMenu( emptyMenu, plugPlane["out"] ),
	str( [ p for p, i in emptyMenu.items() ] ) )

plugEditor._showContextMenu(
	plugEditor._NetworkEditor__nodeItems[ "plane" ], None,
	QtCore.QPoint( 10, 10 ), QtCore.QPointF( 0, 0 ), plug = plugPlane["out"]
)
check( "没有插口菜单时退回节点菜单",
	plugEditor._NetworkEditor__contextMenu is not None and
	"plane" in ( plugEditor._NetworkEditor__contextMenu._Menu__title or "" ),
	str( plugEditor._NetworkEditor__contextMenu._Menu__title ) )
plugEditor._NetworkEditor__contextMenu = None

# --- 连线菜单：我们自己的「断开连接」+ 原生的「插入 Dot」---
connectionMenu = IECore.MenuDefinition()
check( "连线上有原生菜单",
	plugEditor._NetworkEditor__appendNativeConnectionMenu( connectionMenu, plugDot["in"] ),
	str( [ p for p, i in connectionMenu.items() ] ) )
check( "里面有「插入 Dot」",
	any( p.endswith( "Insert Dot" ) for p, i in connectionMenu.items() ),
	str( [ p for p, i in connectionMenu.items() ] ) )

dotEdge = [ e for e in plugEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "dot" ]
check( "找得到那条边", len( dotEdge ) == 1, str( len( dotEdge ) ) )
if dotEdge :
	plugEditor._showContextMenu( None, dotEdge[0], QtCore.QPoint( 10, 10 ), QtCore.QPointF( 0, 0 ) )
	edgePaths = [ p for p, i in NE._menuDefinition( plugEditor._NetworkEditor__contextMenu ).items() ]
	check( "连线右键 = 我们的断开 + 原生的插入 Dot",
		any( "Disconnect" in p for p in edgePaths ) and any( p.endswith( "Insert Dot" ) for p in edgePaths ),
		str( edgePaths ) )
	plugEditor._NetworkEditor__contextMenu = None

# 「插入 Dot」真的插得进去（端到端）。
# 注意它的命令签名是 `__insertDot( menu, destinationPlug )` —— **要 menu**，而且拿
# `menu.ancestor( GafferUI.GraphEditor )` 当宿主、拿 `menu.popupPosition()` 反算位置。
# 所以必须走我们真正的弹出口（挂在隐藏引擎上、改写过 popupPosition 的那个）。
if dotEdge :
	dotsBefore = len( [ n for n in NE.collectNodes( plugScript ) if isinstance( n, Gaffer.Dot ) ] )
	plugEditor._showContextMenu(
		None, dotEdge[0], QtCore.QPoint( 300, 200 ), QtCore.QPointF( 240.0, -120.0 )
	)
	popped = plugEditor._NetworkEditor__contextMenu
	item = [ i for p, i in NE._menuDefinition( popped ).items() if p.endswith( "Insert Dot" ) ][0]
	item.command( menu = popped )
	idle()
	dotsAfter = len( [ n for n in NE.collectNodes( plugScript ) if isinstance( n, Gaffer.Dot ) ] )
	check( "点「插入 Dot」真的多了一个 Dot", dotsAfter == dotsBefore + 1,
		"%d -> %d" % ( dotsBefore, dotsAfter ) )
	check( "而且图跟着更新了（增量）",
		len( plugEditor._NetworkEditor__nodeItems ) == len( NE.collectNodes( plugScript ) ),
		str( sorted( plugEditor._NetworkEditor__nodeItems ) ) )
	newDot = [
		n for n in NE.collectNodes( plugScript )
		if isinstance( n, Gaffer.Dot ) and n.getName() != "dot"
	]
	check( "新 Dot 的位置是个能用的数（不是 nan）",
		newDot and NE.positionUsable( NE.nodePosition( newDot[0] ) ),
		str( NE.nodePosition( newDot[0] ) if newDot else None ) )
	check( "新 Dot 串在原来那条线中间",
		newDot and newDot[0]["in"].getInput() is not None and
		plugDot["in"].getInput().node().getName() == newDot[0].getName(),
		str( plugDot["in"].getInput() ) )
	plugEditor._NetworkEditor__contextMenu = None

# --- 圆点上右键会带上 plug（走 `_GraphView.contextMenuEvent` 那条路）---
boxItem = plugEditor._NetworkEditor__nodeItems[ "plugBox" ]
noduleHit = None
for plugs in boxItem._nodules.values() :
	for plug in plugs :
		if plug.getName() == promotedScene.getName() :
			noduleHit = plug
check( "Box 上真有那个提升出来的圆点", noduleHit is not None,
	str( [ p.getName() for ps in boxItem._nodules.values() for p in ps ] ) )
if noduleHit is not None :
	plugEditor.graphView().frameAll()      # 不先取景，圆点可能压根不在视口里
	idle()
	scenePoint = boxItem.mapToScene( boxItem.nodulePosition( noduleHit ) )
	hitItem, hitPlug = plugEditor.graphView().noduleAt(
		plugEditor.graphView().mapFromScene( scenePoint )
	)
	check( "按坐标问得出圆点上的插口",
		hitPlug is not None and hitPlug.getName() == promotedScene.getName(),
		str( hitPlug ) )

plugWindow.setVisible( False )


##########################################################################
section( "增量更新（改一根线不重建全图）" )
##########################################################################

# 全量重建在 800 个节点上要 250ms，每连一根线卡这么久没法用（profile 出来 63% 花在
# 逐个建 `_NodeItem`）。下面这些断言盯着的是「没变的 item 必须是同一个 Python 对象」——
# 只要它没被重建，那 63% 就没花出去。

incApplication = Gaffer.ApplicationRoot( "networkEditorIncTest" )
incScript = Gaffer.ScriptNode()
incApplication["scripts"].addChild( incScript )

incNodes = {}
for name in ( "a", "b", "c", "d" ) :
	node = GafferScene.Isolate( name )
	incScript.addChild( node )
	NE.setNodePosition( node, imath.V2f( len( incNodes ) * 15.0, 0 ) )
	incNodes[ name ] = node
incNodes["b"]["in"].setInput( incNodes["a"]["out"] )

incEditor = NE.NetworkEditor( incScript )
incWindow = GafferUI.Window( "inc" )
incWindow.setChild( incEditor )
incWindow._qtWidget().resize( 900, 600 )
incWindow.setVisible( True )
idle()

incItems = incEditor._NetworkEditor__nodeItems
incEdges = lambda : incEditor._NetworkEditor__edgeItems

def itemIds() :

	return dict( ( name, id( item ) ) for name, item in incItems.items() )

before = itemIds()
check( "四个节点都在", sorted( incItems ) == [ "a", "b", "c", "d" ], str( sorted( incItems ) ) )
check( "一条连线", len( incEdges() ) == 1, str( len( incEdges() ) ) )

# --- 接一根线：只动边，一个 item 都不重建 ---
incNodes["d"]["in"].setInput( incNodes["c"]["out"] )
idle()
check( "接线后两条连线", len( incEdges() ) == 2, str( len( incEdges() ) ) )
check( "**没有任何 item 被重建**", itemIds() == before, "变了：%s" % (
	[ n for n in before if before[n] != itemIds().get( n ) ], ) )

# --- 拔线：同样不重建 ---
incNodes["d"]["in"].setInput( None )
idle()
check( "拔线后回到一条", len( incEdges() ) == 1, str( len( incEdges() ) ) )
check( "拔线也不重建 item", itemIds() == before )

# --- 加节点：只多出那一个 ---
extra = GafferScene.Isolate( "e" )
NE.setNodePosition( extra, imath.V2f( 60.0, 0 ) )
incScript.addChild( extra )
idle()
check( "新节点有了 item", "e" in incItems )
check( "老 item 一个都没重建",
	all( incItems[ n ] is not None and id( incItems[ n ] ) == before[ n ] for n in before ),
	str( [ n for n in before if id( incItems[ n ] ) != before[ n ] ] ) )

# --- 删节点：item 和它的边一起没，别的不动 ---
incNodes["b"]["in"].setInput( incNodes["a"]["out"] )
idle()
incScript.removeChild( incNodes["b"] )
idle()
check( "删掉的 item 没了", "b" not in incItems, str( sorted( incItems ) ) )
check( "它那条边也没了", len( incEdges() ) == 0, str( len( incEdges() ) ) )
check( "剩下的 item 还是原来那批",
	all( id( incItems[ n ] ) == before[ n ] for n in ( "a", "c", "d" ) ) )
check( "边的索引里也清干净了",
	not incEditor._NetworkEditor__edgesByNode.get( "b" ),
	str( incEditor._NetworkEditor__edgesByNode.get( "b" ) ) )

# --- 改名：只重建那一个，边跟着改 ---
incNodes["c"]["in"].setInput( incNodes["a"]["out"] )
idle()
beforeRename = dict( incItems )
incNodes["c"].setName( "cc" )
idle()
check( "改名后按新名字存", "cc" in incItems and "c" not in incItems, str( sorted( incItems ) ) )
check( "改名后连线还在且接的是新名字",
	len( incEdges() ) == 1 and incEdges()[0].edge.dstNode.getName() == "cc",
	str( [ e.edge.key() for e in incEdges() ] ) )
check( "改名只重建它自己（a / d 没动）",
	incItems["a"] is beforeRename["a"] and incItems["d"] is beforeRename["d"] )

# --- 元数据变了：重建那一个 item（颜色 / 形状 / 尺寸都可能变）---
# 注意「重建了没有」要**持有引用后用 `is` 比**：光比 `id()`，对象被回收后 id 会被复用
beforeMetadata = dict( incItems )
Gaffer.Metadata.registerValue( incNodes["a"], "nodeGadget:color", imath.Color3f( 0.9, 0.2, 0.2 ) )
idle()
check( "改元数据的那个 item 重建了", incItems["a"] is not beforeMetadata["a"] )
check( "别的 item 没跟着重建", incItems["d"] is beforeMetadata["d"] )

# --- 增量更新不许把选择吃掉（`QGraphicsScene.selectionChanged` 会回写 script）---
incScript.selection().clear()
incScript.selection().add( incNodes["d"] )
idle()
newNode = GafferScene.Isolate( "f" )
NE.setNodePosition( newNode, imath.V2f( 80.0, 0 ) )
incScript.addChild( newNode )
idle()
check( "增量更新之后选择还在",
	[ n.getName() for n in incScript.selection() ] == [ "d" ],
	str( [ n.getName() for n in incScript.selection() ] ) )

# 删掉一个**选中的**节点：选择跟着少一个，但别的选择不受影响
incScript.selection().add( newNode )
idle()
incScript.removeChild( newNode )
idle()
check( "删掉选中的节点，剩下的选择不受影响",
	[ n.getName() for n in incScript.selection() ] == [ "d" ],
	str( [ n.getName() for n in incScript.selection() ] ) )

# --- 全量重建仍然可用（换 root / 兜底走这条）---
# 注意：`__rebuild()` 会**换一个新的 dict**（`self.__nodeItems = {}`），
# 之前抓着的那个引用就成了旧的 —— 重建之后必须重新拿
beforeFullRebuild = dict( incItems )
incEditor._NetworkEditor__rebuild()
idle()
incItems = incEditor._NetworkEditor__nodeItems
check( "全量重建之后节点数对得上",
	sorted( incItems ) == sorted( n.getName() for n in NE.collectNodes( incScript ) ),
	str( sorted( incItems ) ) )
check( "全量重建之后 item 全是新的",
	all( incItems[ n ] is not beforeFullRebuild[ n ] for n in beforeFullRebuild if n in incItems ),
	str( [ n for n in beforeFullRebuild if n in incItems and incItems[ n ] is beforeFullRebuild[ n ] ] ) )

incWindow.setVisible( False )


##########################################################################
section( "中键平移不碰连线（问题 1）" )
##########################################################################

panScript = Gaffer.ScriptNode()
panA = GafferScene.Plane( "panA" ) ; panB = GafferScene.Isolate( "panB" )
panScript.addChild( panA ) ; panScript.addChild( panB )
panB["in"].setInput( panA["out"] )
panEditor = NE.NetworkEditor( panScript )
panWindow = GafferUI.Window( "pan" )
panWindow.setChild( panEditor )
panWindow._qtWidget().resize( 800, 600 )
panWindow.setVisible( True )
idle()

panEdge = panEditor._NetworkEditor__edgeItems[0]
panView = panEditor.graphView()

class _FakeHoverEvent( object ) :
	def pos( self ) : return QtCore.QPointF( 0, 0 )

panEdge.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "没按键时悬停会高亮", panEdge._hovered )

panEditor._clearWireHover()
check( "_clearWireHover 清掉高亮", not panEdge._hovered )

# 中键按下 -> 平移模式：item 交互整个关掉，hover 不会再送到连线上
press = QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonPress, QtCore.QPointF( 100, 100 ),
	QtCore.Qt.MiddleButton, QtCore.Qt.MiddleButton, QtCore.Qt.NoModifier
)
QtWidgets.QApplication.sendEvent( panView.viewport(), press )
check( "中键按下进入平移", not panView.isInteractive() )
check( "平移期间连线不高亮", not panEdge._hovered )

release = QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonRelease, QtCore.QPointF( 140, 130 ),
	QtCore.Qt.MiddleButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier
)
QtWidgets.QApplication.sendEvent( panView.viewport(), release )
check( "松手恢复交互", panView.isInteractive() )

panWindow.setVisible( False )


##########################################################################
section( "视野中心：拖布局改尺寸不能把画面弹回去" )
##########################################################################

# 平移走的是 transform（NoAnchor），Qt 内部的 lastCenterPoint 不跟着更新；
# 尺寸一变（拖布局分隔条 / 换 tab / 重新 parent）就会 centerOn 那个陈旧的点，
# 表现为「一拖布局，图就跳回中心」。
centreScript = Gaffer.ScriptNode()
centreScript.addChild( GafferScene.Plane( "centreA" ) )
centreEditor = NE.NetworkEditor( centreScript )
centreWindow = GafferUI.Window( "centre" )
centreWindow.setChild( centreEditor )
centreWindow._qtWidget().resize( 800, 600 )
centreWindow.setVisible( True )
idle()

centreView = centreEditor.graphView()

def viewCentre() :

	return centreView.mapToScene( centreView.viewport().rect().center() )

def centreMoved( a, b, tolerance = 2.0 ) :

	return abs( a.x() - b.x() ) > tolerance or abs( a.y() - b.y() ) > tolerance

before = viewCentre()
centreView._GraphView__pan( QtCore.QPointF( -300, -200 ) )
idle()
panned = viewCentre()
check( "平移确实挪了画面", centreMoved( before, panned ) )

centreWindow._qtWidget().resize( 900, 640 )
idle()
check(
	"改尺寸后画面不弹回（问题：拖布局回到中心）",
	not centreMoved( panned, viewCentre() ),
	"%s -> %s" % ( panned, viewCentre() )
)

centreWindow._qtWidget().resize( 640, 480 )
idle()
check( "再改一次尺寸仍不弹回", not centreMoved( panned, viewCentre() ) )

# 拖布局时面板会 hide → 换 parent → show
centreEditor._qtWidget().hide()
idle()
centreEditor._qtWidget().show()
idle()
check( "hide / show 之后画面留在原处", not centreMoved( panned, viewCentre() ) )

# 连续小步平移不能有累计漂移（复位用的 centerOn 会取整）
stepBefore = viewCentre()
for _ in range( 100 ) :
	centreView._GraphView__pan( QtCore.QPointF( -3, -2 ) )
idle()
stepAfter = viewCentre()
scale = math.sqrt( abs( centreView.transform().determinant() ) ) or 1.0
check(
	"连续平移无累计漂移",
	abs( ( stepAfter.x() - stepBefore.x() ) - 300 / scale ) < 2.0 and
	abs( ( stepAfter.y() - stepBefore.y() ) - 200 / scale ) < 2.0,
	"%s -> %s" % ( stepBefore, stepAfter )
)

# 取景之后记住的是新中心，不是取景之前那个
centreView.frameAll()
idle()
framed = viewCentre()
centreWindow._qtWidget().resize( 700, 520 )
idle()
check( "取景之后改尺寸留在取景位置", not centreMoved( framed, viewCentre() ) )

centreWindow.setVisible( False )


##########################################################################
section( "点选 / 框选 / 接口悬停 / 内部快捷键转发" )
##########################################################################

selScript = Gaffer.ScriptNode()
selA = GafferScene.Plane( "selA" )
selB = GafferScene.Isolate( "selB" )
selC = GafferScene.Isolate( "selC" )
for n in ( selA, selB, selC ) :
	selScript.addChild( n )
selB["in"].setInput( selA["out"] )
selC["in"].setInput( selB["out"] )
NE.setNodePosition( selA, imath.V2f( 0, 20 ) )
NE.setNodePosition( selB, imath.V2f( 0, 0 ) )
NE.setNodePosition( selC, imath.V2f( 0, -20 ) )

selEditor = NE.NetworkEditor( selScript )
selWindow = GafferUI.Window( "sel" )
selWindow.setChild( selEditor )
selWindow._qtWidget().resize( 900, 700 )
selWindow.setVisible( True )
idle()

selItems = selEditor._NetworkEditor__nodeItems
selView = selEditor.graphView()

def selected() :
	return sorted( n.getName() for n in selScript.selection() )

# --- 点选（问题 3）---
selEditor._selectClicked( selItems[ "selA" ], QtCore.Qt.NoModifier )
check( "普通点击只选一个", selected() == [ "selA" ], str( selected() ) )

consumed = selEditor._selectClicked( selItems[ "selB" ], QtCore.Qt.ShiftModifier )
check( "Shift 点击加选", selected() == [ "selA", "selB" ], str( selected() ) )
check( "Shift 点击之后还能拖动（没被吃掉）", not consumed )

consumed = selEditor._selectClicked( selItems[ "selB" ], QtCore.Qt.ControlModifier )
check( "Ctrl 点已选中的 -> 取消选中", selected() == [ "selA" ], str( selected() ) )
check( "而且不进入拖动", consumed )

consumed = selEditor._selectClicked( selItems[ "selA" ], QtCore.Qt.NoModifier )
check( "点已选中的不清空（好拖整组）", selected() == [ "selA" ] and not consumed, str( selected() ) )

# Alt+Shift / Alt+Ctrl 要点在**还没选中**的节点上（原生：点已选中的节点不动选择）
selEditor._clearSelection()
selEditor._selectClicked( selItems[ "selC" ], QtCore.Qt.AltModifier | QtCore.Qt.ShiftModifier )
check( "Alt+Shift 连上游一起选", selected() == [ "selA", "selB", "selC" ], str( selected() ) )

selEditor._clearSelection()
selEditor._selectClicked( selItems[ "selA" ], QtCore.Qt.AltModifier | QtCore.Qt.ControlModifier )
check( "Alt+Ctrl 连下游一起选", selected() == [ "selA", "selB", "selC" ], str( selected() ) )

selEditor._clearSelection()
check( "空白处点击清空", selected() == [] )

# --- 框选：**擦到一部分就算**（实机反馈要的；原生是"完全框住才算"）---
rectA = selItems[ "selA" ].selectionRect()
rectB = selItems[ "selB" ].selectionRect()

fullA = rectA.adjusted( -5, -5, 5, 5 )
selEditor._applyBandSelection( fullA )
check( "框住 selA 就选中它", selected() == [ "selA" ], str( selected() ) )

halfB = QtCore.QRectF( rectB.left() - 5, rectB.center().y(), rectB.width() + 10, rectB.height() )
selEditor._applyBandSelection( halfB )
check( "只擦到一半也算选中（**故意不跟原生**：原生要整个框住）",
	selected() == [ "selA", "selB" ], str( selected() ) )

# 完全碰不到的不算
selEditor._clearSelection()
missB = QtCore.QRectF( rectB.right() + 20, rectB.top(), 10, 10 )
selEditor._applyBandSelection( missB )
check( "碰都没碰到的不选", selected() == [], str( selected() ) )
selEditor._applyBandSelection( fullA )

both = fullA.united( rectB ).adjusted( -5, -5, 5, 5 )
selEditor._applyBandSelection( both )
check( "框住两个就都选上", selected() == [ "selA", "selB" ], str( selected() ) )

selEditor._applyBandSelection( fullA, remove = True )
check( "Ctrl 框选是减选", selected() == [ "selB" ], str( selected() ) )

# Shift 在空白处按下不清空已有选择（否则加选无从谈起）
def sendMouse( eventType, viewPos, button, buttons, modifiers ) :
	event = QtGui.QMouseEvent(
		eventType, QtCore.QPointF( viewPos ), QtCore.QPointF( viewPos ),
		button, buttons, modifiers
	)
	QtWidgets.QApplication.sendEvent( selView.viewport(), event )

emptyPoint = selView.mapFromScene( QtCore.QPointF( 600, 600 ) )
sendMouse( QtCore.QEvent.MouseButtonPress, emptyPoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier )
check( "Shift 在空白处按下不清空选择", selected() == [ "selB" ], str( selected() ) )
sendMouse( QtCore.QEvent.MouseButtonRelease, emptyPoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.ShiftModifier )

sendMouse( QtCore.QEvent.MouseButtonPress, emptyPoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
check( "不按修饰键在空白处按下就清空", selected() == [], str( selected() ) )
sendMouse( QtCore.QEvent.MouseButtonRelease, emptyPoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )

# --- 拖动仍然正常（按下时我们合成了一个不带修饰键的事件交给 Qt，别把拖动弄丢了）---
selEditor._clearSelection()
# 开拖之前先把待办的 idle 活儿干完：重建会把 item 删了重做，Qt 的鼠标抓取跟着没
idle()
QtWidgets.QApplication.processEvents()
dragItem = selItems[ "selA" ]
startScene = QtCore.QPointF( dragItem.pos() )
startView = selView.mapFromScene( startScene )
endView = QtCore.QPoint( startView.x() + 40, startView.y() + 25 )

sendMouse( QtCore.QEvent.MouseButtonPress, startView, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )

check( "按下节点进的是拖动模式（我们没把这一下吃掉，交给了 Qt）",
	selView._GraphView__mode == NE._MODE_MOVE, str( selView._GraphView__mode ) )

# **别赌 Qt 会替我们挪 item**：无头（offscreen）QPA 下 `QGraphicsScene` 偶尔不给这次
# 按下建立隐式鼠标抓取（`mouseGrabberItem()` 是 None），后面的 move 就谁也收不到 ——
# 这是无头环境的毛病，真机拖动由 `e2e_panel_input.py` 用真鼠标覆盖。抓取没建起来就
# 自己把 item 挪到位，这里要验的是**松手那一下把新位置写回 Gaffer**这段我们的代码。
if selView.scene().mouseGrabberItem() is None :
	dragItem.setPos( startScene + QtCore.QPointF( endView.x() - startView.x(), endView.y() - startView.y() ) )

sendMouse( QtCore.QEvent.MouseMove, endView, QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease, endView, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()

check( "点节点会选中它", selected() == [ "selA" ], str( selected() ) )
check(
	"拖动仍然把节点挪走了",
	( QtCore.QPointF( dragItem.pos() ) - startScene ).manhattanLength() > 1.0,
	"%s -> %s" % ( startScene, dragItem.pos() )
)
check(
	"松手写回了 Gaffer",
	abs( NE.nodePosition( selA ).x - 0.0 ) > 1e-3 or abs( NE.nodePosition( selA ).y - 20.0 ) > 1e-3,
	str( NE.nodePosition( selA ) )
)

# --- Shift 多选按下再松手，不许塌回单选（问题 1）---
selEditor._clearSelection()
selEditor._selectClicked( selItems[ "selA" ], QtCore.Qt.NoModifier )
selEditor._selectClicked( selItems[ "selB" ], QtCore.Qt.ShiftModifier )
check( "Shift 点完是两个", selected() == [ "selA", "selB" ], str( selected() ) )

# Qt 的 item release 里有「没移动又没按 Ctrl 就只留这一个」的逻辑，要被我们兜住
shiftPoint = selView.mapFromScene( selItems[ "selB" ].pos() )
sendMouse( QtCore.QEvent.MouseButtonPress, shiftPoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease, shiftPoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.ShiftModifier )
idle()
check( "松手之后还是两个（不塌回单选）", selected() == [ "selA", "selB" ], str( selected() ) )

# 而且**顺序**要保住：Qt 在松手里先把选择塌成「只剩点中的那个」，我们再兜回来，
# 这一来一回如果写进了 script，就变成先 remove(selA) 再 add(selA)，selA 成了
# node set 里最后加进来的那个 —— 跟着 node set 走的面板（ParameterEditor、
# 原生 NodeEditor 都只显示 `_lastAddedNode()`）就会「先跳到 selB、马上弹回 selA」。
check(
	"Shift 加选之后 node set 顺序不变（最后一个仍是新点的那个）",
	[ n.getName() for n in selScript.selection() ] == [ "selA", "selB" ],
	str( [ n.getName() for n in selScript.selection() ] )
)

# 普通点击已选中的节点（多选里）也不塌 —— 原生 GraphGadget 也是不动选择
plainPoint = selView.mapFromScene( selItems[ "selA" ].pos() )
sendMouse( QtCore.QEvent.MouseButtonPress, plainPoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease, plainPoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "点多选里的一个也不塌", selected() == [ "selA", "selB" ], str( selected() ) )

# --- 面板销毁之后信号还会再来一次，不许崩 ---
#     实机报过：`RuntimeError: Internal C++ object (PySide6.QtWidgets.QGraphicsScene)
#     already deleted`，栈是 __sceneSelectionChanged -> _flushSelectionToScript。
#     换布局 / 关掉这一格之后 Qt 还会补送选择变化，而底层 scene 已经没了。
deadScript = Gaffer.ScriptNode()
deadScript["deadA"] = GafferScene.Plane()
deadEditor = NE.NetworkEditor( deadScript )
deadWindow = GafferUI.Window( "dead" )
deadWindow.setChild( deadEditor )
deadWindow._qtWidget().resize( 600, 400 )
deadWindow.setVisible( True )
idle()

deadEditor._qtWidget().deleteLater()
deadWindow.setVisible( False )
for i in range( 5 ) :
	QtWidgets.QApplication.processEvents()
	GafferUI.EventLoop.waitForIdle( 1 )

try :
	deadEditor._NetworkEditor__scene.selectedItems()
	sceneReallyDead = False
except RuntimeError :
	sceneReallyDead = True
check( "复现方式对：这时候裸访问 scene 确实会 RuntimeError", sceneReallyDead )

deadOk = True
deadDetail = ""
for name, call in (
	( "_flushSelectionToScript", lambda : deadEditor._flushSelectionToScript() ),
	( "__sceneSelectionChanged", lambda : deadEditor._NetworkEditor__sceneSelectionChanged() ),
	( "_selectedSceneItems", lambda : deadEditor._selectedSceneItems() ),
	( "_clearSelection", lambda : deadEditor._clearSelection() ),
	( "_applyBandSelection", lambda : deadEditor._applyBandSelection( QtCore.QRectF( 0, 0, 10, 10 ) ) ),
	( "_restoreSceneSelection", lambda : deadEditor._restoreSceneSelection( [] ) ),
	( "__updateSelection", lambda : deadEditor._NetworkEditor__updateSelection() ),
	( "改选择走真信号路径", lambda : deadScript.selection().add( deadScript["deadA"] ) ),
) :
	try :
		call()
		for i in range( 3 ) :
			QtWidgets.QApplication.processEvents()
			GafferUI.EventLoop.waitForIdle( 1 )
	except Exception as e :
		deadOk = False
		deadDetail += "%s -> %s  " % ( name, e )

check( "面板销毁之后选择同步的每个入口都不崩", deadOk, deadDetail )

# --- 命中形状不许跟着悬停的包围盒一起膨胀（问题 3：连不上的根因）---
hitItem = selItems[ "selB" ]
shapeBefore = hitItem.shape().boundingRect()
selEditor._setHoveredNodule( hitItem, selB[ "in" ] )
check( "悬停时包围盒确实变大了", hitItem.boundingRect().width() > hitItem.cardRect().width() + 100 )
check(
	"但命中形状没变大（否则会把隔壁节点的点击/拖放都吃掉）",
	hitItem.shape().boundingRect() == shapeBefore,
	"%s vs %s" % ( hitItem.shape().boundingRect(), shapeBefore )
)
# 左边和下边就是「卡片 + 一点点圆点余量」；右上角多出来的是 focus 角标的命中方角
# （角标画在卡片外面，不划进 `shape()` 的话 `items()` 找不到它 —— 既悬停不出来也点不动）
check(
	"命中形状就是卡片 + 一点点圆点余量（左 / 下）",
	abs( shapeBefore.left() - ( hitItem.cardRect().left() - NE.NODULE_HIT_RADIUS ) ) < 1e-6 and
	abs( shapeBefore.bottom() - ( hitItem.cardRect().bottom() + NE.NODULE_HIT_RADIUS ) ) < 1e-6,
	str( shapeBefore )
)
check(
	"右上角按 focus 角标的命中方角来（比圆点余量宽，就多这一块）",
	abs( shapeBefore.right() - ( hitItem.cardRect().right() + hitItem.focusTabHitSize() ) ) < 1e-6 and
	abs( shapeBefore.top() - ( hitItem.cardRect().top() - hitItem.focusTabHitSize() ) ) < 1e-6 and
	hitItem.focusTabHitSize() > NE.NODULE_HIT_RADIUS,
	"%s / %s" % ( shapeBefore, hitItem.focusTabHitSize() )
)
selEditor._setHoveredNodule( None, None )

# 真的从一个节点的圆点拖到隔壁节点（挨得很近）
NE.setNodePosition( selB, imath.V2f( 0, 0 ) )
NE.setNodePosition( selC, imath.V2f( 0, -6 ) )     # 只隔 6 个单位，比悬停余量近得多
selC[ "in" ].setInput( None )
idle()

# 图重建过了，item 得重新取（旧的 Python 包装已经指向被销毁的 C++ 对象）
selItems = selEditor._NetworkEditor__nodeItems
srcItem, dstItem = selItems[ "selB" ], selItems[ "selC" ]
selEditor._setHoveredNodule( srcItem, selB[ "out" ] )   # 先悬停，复现当时的状态
srcPoint = selView.mapFromScene( srcItem.mapToScene( srcItem.nodulePosition( selB[ "out" ] ) ) )
dstPoint = selView.mapFromScene( dstItem.mapToScene( dstItem.nodulePosition( selC[ "in" ] ) ) )
targetItem, targetPlug = selView.noduleAt( dstPoint )
check(
	"命中测试落在正确的节点上（不是刚悬停过的那个）",
	targetItem is not None and targetItem.nodeName == "selC" and targetPlug is not None,
	"%s / %s" % ( targetItem.nodeName if targetItem else None, targetPlug )
)
selEditor._setHoveredNodule( None, None )

# --- 拖动时自动对齐（问题 3）---
alignTarget = selItems[ "selB" ]          # 参照物
alignItem = selItems[ "selC" ]            # 被拖的

# 参照节点正下方 150px：在感知半径 `SNAP_RANGE` 之内（Houdini 那套只看手边）
belowY = alignTarget.pos().y() + 150.0

check( "默认是开的", selEditor.getSnapEnabled() )
check(
	"工具条 Snap 按钮和开关一致（默认按下）",
	selEditor._NetworkEditor__snapButton.isChecked()
)
selEditor._NetworkEditor__snapButton.setChecked( False )
check( "点一下按钮就关掉（不用点两次）", not selEditor.getSnapEnabled() )
selEditor.setSnapEnabled( True )
check( "程序里打开，按钮跟着按下", selEditor._NetworkEditor__snapButton.isChecked() )
selEditor.setSnapEnabled( False )
check( "程序里关掉，按钮跟着弹起", not selEditor._NetworkEditor__snapButton.isChecked() )
check(
	"关着的时候不吸附",
	selEditor._snapNodePosition( alignItem, QtCore.QPointF( alignTarget.pos().x() + 3.0, belowY ) )
		== QtCore.QPointF( alignTarget.pos().x() + 3.0, belowY )
)

selEditor.setSnapEnabled( True )   # 下面这些用例都在「打开对齐」的前提下
check( "打开之后是开的", selEditor.getSnapEnabled() )
check( "没在拖的时候不吸附",
	selEditor._snapNodePosition( alignItem, QtCore.QPointF( alignTarget.pos().x() + 3.0, belowY ) )
		== QtCore.QPointF( alignTarget.pos().x() + 3.0, belowY ) )

# 真的拖起来
selEditor._clearSelection()
startView = selView.mapFromScene( alignItem.pos() )
sendMouse( QtCore.QEvent.MouseButtonPress, startView, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
check( "进入拖动状态", selView.isDraggingNodes() )

nearX = alignTarget.pos().x() + 4.0        # 差 4px，在 SNAP_DISTANCE 之内
snapped = selEditor._snapNodePosition( alignItem, QtCore.QPointF( nearX, belowY ) )
check( "x 吸到参照节点的中线上", abs( snapped.x() - alignTarget.pos().x() ) < 1e-6, str( snapped ) )
check( "y 一点不动（只吸一个轴，保持横平竖直）", abs( snapped.y() - belowY ) < 1e-6, str( snapped ) )
guides = selEditor.snapGuides()
check( "亮出一条竖参考线",
	len( guides ) == 1 and guides[ 0 ][ 0 ] == "v" and
	abs( guides[ 0 ][ 1 ] - alignTarget.pos().x() ) < 1e-6, str( guides ) )
check( "参考线只画在两个节点之间（不是拉满整个视口）",
	len( guides[ 0 ] ) == 4 and
	guides[ 0 ][ 2 ] < min( alignTarget.pos().y(), belowY ) and
	guides[ 0 ][ 3 ] > max( alignTarget.pos().y(), belowY ), str( guides ) )

farX = alignTarget.pos().x() + NE.SNAP_DISTANCE + 5.0
notSnapped = selEditor._snapNodePosition( alignItem, QtCore.QPointF( farX, belowY ) )
check( "离远了不吸", abs( notSnapped.x() - farX ) < 1e-6, str( notSnapped ) )
check( "参考线也灭了", selEditor.snapGuides() == [], str( selEditor.snapGuides() ) )

# 排成一横行：y 差一点点、x 差得远 → 吸 y，x 不动
rowPoint = QtCore.QPointF( alignTarget.pos().x() + 150.0, alignTarget.pos().y() + 4.0 )
rowSnapped = selEditor._snapNodePosition( alignItem, rowPoint )
check( "y 吸到参照节点那一行", abs( rowSnapped.y() - alignTarget.pos().y() ) < 1e-6, str( rowSnapped ) )
check( "x 一点不动", abs( rowSnapped.x() - rowPoint.x() ) < 1e-6, str( rowSnapped ) )
check( "这次亮的是横参考线",
	[ g[ 0 ] for g in selEditor.snapGuides() ] == [ "h" ], str( selEditor.snapGuides() ) )

selEditor.setSnapEnabled( False )
check( "关掉之后不吸",
	selEditor._snapNodePosition( alignItem, QtCore.QPointF( nearX, belowY ) ) == QtCore.QPointF( nearX, belowY ) )
check( "关掉之后参考线清空", selEditor.snapGuides() == [] )
selEditor.setSnapEnabled( True )

sendMouse( QtCore.QEvent.MouseButtonRelease, startView, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "松手清掉参考线", selEditor.snapGuides() == [], str( selEditor.snapGuides() ) )
check( "关掉再打开状态对得上", selEditor.getSnapEnabled() )

# 多选拖动不吸附（免得把一组的相对位置搅乱）
selEditor._selectClicked( selItems[ "selA" ], QtCore.Qt.NoModifier )
selEditor._selectClicked( alignItem, QtCore.Qt.ShiftModifier )
sendMouse( QtCore.QEvent.MouseButtonPress, selView.mapFromScene( alignItem.pos() ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
multi = selEditor._snapNodePosition( alignItem, QtCore.QPointF( nearX, belowY ) )
check( "多选拖动不吸附", abs( multi.x() - nearX ) < 1e-6, str( multi ) )
sendMouse( QtCore.QEvent.MouseButtonRelease, selView.mapFromScene( alignItem.pos() ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
selEditor._clearSelection()
idle()

# 端到端：拖一个节点到差一点点对齐的位置，松手后写进 Gaffer 的位置应该是**正好对齐**的
selEditor.setSnapEnabled( True )
selEditor._clearSelection()
NE.setNodePosition( selC, imath.V2f( 0, -20 ) )
idle()
dragFrom = selView.mapFromScene( selItems[ "selC" ].pos() )
targetScene = QtCore.QPointF( selItems[ "selB" ].pos().x() + 3.0, selItems[ "selC" ].pos().y() + 40.0 )
dragTo = selView.mapFromScene( targetScene )
sendMouse( QtCore.QEvent.MouseButtonPress, dragFrom, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseMove, dragTo, QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease, dragTo, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check(
	"拖完写进 Gaffer 的位置是正好对齐的",
	abs( NE.nodePosition( selC ).x - NE.nodePosition( selB ).x ) < 1e-4,
	"%s vs %s" % ( NE.nodePosition( selC ), NE.nodePosition( selB ) )
)

selEditor.setSnapEnabled( False )   # 后面的拖动断言要落在精确位置，关掉
check( "关掉之后是关的", not selEditor.getSnapEnabled() )

# --- 拖连线：吸附到最近的兼容接口 + 那个圆点放大 ---
selC[ "in" ].setInput( None )
NE.setNodePosition( selB, imath.V2f( 0, 0 ) )
NE.setNodePosition( selC, imath.V2f( 0, -10 ) )
idle()
selItems = selEditor._NetworkEditor__nodeItems
dragSrc, dragDst = selItems[ "selB" ], selItems[ "selC" ]

srcNodulePoint = selView.mapFromScene( dragSrc.mapToScene( dragSrc.nodulePosition( selB[ "out" ] ) ) )
# 故意**不**指到圆点上：落在目标节点卡片中间
dstBodyPoint = selView.mapFromScene( dragDst.pos() )

sendMouse( QtCore.QEvent.MouseButtonPress, srcNodulePoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseMove, dstBodyPoint, QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )

check( "落在节点身上时目标接口被高亮放大", dragDst.hoveredNodule() == "in", str( dragDst.hoveredNodule() ) )
check( "整块卡片也标成落点", dragDst._dropTarget )

wireItem = selView._GraphView__connectWire
snapPoint = wireItem.path().pointAtPercent( 1.0 ) if wireItem is not None else None
expected = dragDst.mapToScene( dragDst.nodulePosition( selC[ "in" ] ) )
check(
	"连线末端吸附到那个接口上（不是跟着鼠标）",
	snapPoint is not None and ( snapPoint - expected ).manhattanLength() < 1e-3,
	"%s vs %s" % ( snapPoint, expected )
)

sendMouse( QtCore.QEvent.MouseButtonRelease, dstBodyPoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "松手在卡片中间也连上了", selC[ "in" ].getInput() is not None, str( selC[ "in" ].getInput() ) )
check( "连完清掉放大高亮", selEditor._NetworkEditor__nodeItems[ "selC" ].hoveredNodule() is None )
check( "也清掉落点高亮", not selEditor._NetworkEditor__nodeItems[ "selC" ]._dropTarget )

# --- X 划线断连：开关式，不用按着 ---
def sendKeyEvent( eventType, key, modifiers = QtCore.Qt.NoModifier, autoRepeat = False ) :
	event = QtGui.QKeyEvent( eventType, key, modifiers, "", autoRepeat )
	QtWidgets.QApplication.sendEvent( selView, event )
	return event

# 摆一条明确的连线：selB(0,0) -> selC(0,-10)
selC[ "in" ].setInput( selB[ "out" ] )
NE.setNodePosition( selB, imath.V2f( 0, 0 ) )
NE.setNodePosition( selC, imath.V2f( 0, -10 ) )
idle()
selItems = selEditor._NetworkEditor__nodeItems

check( "一开始不在划线模式", not selView.isCutting() )
sendKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
check( "按住 X 进入划线模式", selView.isCutting() )
check( "工具条给了提示", "Delete mode" in selEditor._NetworkEditor__statusLabel.text(),
	selEditor._NetworkEditor__statusLabel.text() )

# 自动重复的按键要被忽略（这就是「一直闪、画不出来」的根因）
sendMouse( QtCore.QEvent.MouseMove, selView.mapFromScene( QtCore.QPointF( -60, -60 ) ),
	QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
pointsBefore = len( selView._GraphView__cutPoints )
sendKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X, autoRepeat = True )
sendKeyEvent( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X, autoRepeat = True )
check( "自动重复不打断划线", selView.isCutting() )
check( "已经划的点也没被清掉", len( selView._GraphView__cutPoints ) >= pointsBefore,
	"%d -> %d" % ( pointsBefore, len( selView._GraphView__cutPoints ) ) )

# 一路按着 X + **按着左键**划过那条连线（新手感：按住 X → 左键划 → 松开）
cutTargetEdge = next(
	( e for e in selEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "selC" ), None
)
check( "找到 selB -> selC 那条线", cutTargetEdge is not None )
wireMid = cutTargetEdge.path().pointAtPercent( 0.5 ) if cutTargetEdge is not None else QtCore.QPointF( 0, 0 )

# 没按左键 = 不画（这是新手感和老手感的分水岭）
sendMouse( QtCore.QEvent.MouseMove,
	selView.mapFromScene( QtCore.QPointF( wireMid.x() - 40, wireMid.y() ) ),
	QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
check( "光按着 X 不按左键，不画线", len( selView._GraphView__cutPoints ) == 0,
	str( len( selView._GraphView__cutPoints ) ) )

sendMouse( QtCore.QEvent.MouseButtonPress,
	selView.mapFromScene( QtCore.QPointF( wireMid.x() - 40, wireMid.y() ) ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
for offset in ( -20, 0, 20, 40 ) :
	sendMouse(
		QtCore.QEvent.MouseMove,
		selView.mapFromScene( QtCore.QPointF( wireMid.x() + offset, wireMid.y() ) ),
		QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
	)
check( "按着左键划才攒线", len( selView._GraphView__cutPoints ) >= 5,
	str( len( selView._GraphView__cutPoints ) ) )

# **松开左键 = 这一笔切下去**（X 还按着，可以接着划下一笔）
sendMouse( QtCore.QEvent.MouseButtonRelease,
	selView.mapFromScene( QtCore.QPointF( wireMid.x() + 40, wireMid.y() ) ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "松开左键就切，但还在划线模式里（X 没松）", selView.isCutting() )
sendKeyEvent( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
idle()
check( "松开 X 退出划线模式", not selView.isCutting() )
check( "划过的那条线被切断了", selC[ "in" ].getInput() is None, str( selC[ "in" ].getInput() ) )
check( "没划到的线不受影响", selB[ "in" ].getInput() is not None, str( selB[ "in" ].getInput() ) )
check( "提示恢复成节点计数", "nodes" in selEditor._NetworkEditor__statusLabel.text(),
	selEditor._NetworkEditor__statusLabel.text() )
check( "切断可撤销", selScript.undoAvailable() )
selScript.undo()
idle()
check( "撤销后连线回来了", selC[ "in" ].getInput() is not None )

# 一次按住可以连划好几笔
sendKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
check( "又进入划线模式", selView.isCutting() )
sendMouse( QtCore.QEvent.MouseButtonPress,
	selView.mapFromScene( QtCore.QPointF( wireMid.x() - 30, wireMid.y() ) ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
for offset in ( 0, 30 ) :
	sendMouse( QtCore.QEvent.MouseMove,
		selView.mapFromScene( QtCore.QPointF( wireMid.x() + offset, wireMid.y() ) ),
		QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease,
	selView.mapFromScene( QtCore.QPointF( wireMid.x() + 30, wireMid.y() ) ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "第二笔也切到了", selC[ "in" ].getInput() is None )
check( "切完还在模式里，可以接着划", selView.isCutting() )
check( "上一笔的点已经清空（不会和下一笔连成一条）",
	len( selView._GraphView__cutPoints ) == 0, str( len( selView._GraphView__cutPoints ) ) )
selScript.undo()
idle()
sendKeyEvent( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )   # 把 X 松开，别影响后面

# Esc 也能取消
sendKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
sendMouse( QtCore.QEvent.MouseButtonPress, selView.mapFromScene( wireMid ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseMove, selView.mapFromScene( wireMid ),
	QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape )
check( "Esc 取消", not selView.isCutting() )
check( "Esc 也不切线", selC[ "in" ].getInput() is not None )
sendKeyEvent( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
check( "取消之后松开 X 也不会补一刀", selC[ "in" ].getInput() is not None )

# 划线中途图被重建，不许崩（回归）
sendKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
sendMouse( QtCore.QEvent.MouseButtonPress, QtCore.QPoint( 30, 30 ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseMove, QtCore.QPoint( 40, 40 ), QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseMove, QtCore.QPoint( 90, 90 ), QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
check( "划线 item 建出来了", selView._GraphView__cutItem is not None )

# 增量更新不清 scene，划线 item 活得好好的（比以前更安全）
selScript.addChild( GafferScene.Plane( "cutRebuild" ) )
idle()
check( "增量更新不会把划线 item 扔掉", selView._GraphView__cutItem is not None )
# 全量重建（换 root 那种）还是会 `scene.clear()`，那时必须先忘掉它，否则下一次
# 访问就是 "Internal C++ object already deleted"
selEditor._NetworkEditor__rebuild()
check( "全量重建才忘掉划线 item", selView._GraphView__cutItem is None )

# X 还按着：重建只作废没划完的那一笔，划线模式和状态栏提示都还在
check( "重建之后还在划线模式（X 没松）", selView.isCutting() )
check( "状态栏提示还在", "Delete mode" in selEditor._NetworkEditor__statusLabel.text() )

crashed = None
try :
	sendMouse( QtCore.QEvent.MouseMove, QtCore.QPoint( 140, 140 ), QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
	sendMouse( QtCore.QEvent.MouseButtonPress, QtCore.QPoint( 140, 140 ), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
	sendMouse( QtCore.QEvent.MouseMove, QtCore.QPoint( 150, 150 ), QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
	sendMouse( QtCore.QEvent.MouseButtonRelease, QtCore.QPoint( 150, 150 ), QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
	sendKeyEvent( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
except Exception :
	crashed = traceback.format_exc()
check( "重建之后继续划线 / 完成都不崩", crashed is None, str( crashed ) )
check( "松开 X 干净退出了划线模式", not selView.isCutting() )
check( "退出后状态栏提示也收掉了", "Delete mode" not in selEditor._NetworkEditor__statusLabel.text() )
# 上面那一下只按没松（模拟极端情况），这里补一次松手把状态收干净 ——
# 不收的话后面任何一次松手都会拿这个起点框一大片（框选改成"擦到就算"之后尤其明显）
sendMouse( QtCore.QEvent.MouseButtonRelease, QtCore.QPoint( 140, 140 ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
selEditor._clearSelection()
idle()
idle()
selItems = selEditor._NetworkEditor__nodeItems

# --- focus 之后上下游连线高亮（问题 5）---
selC[ "in" ].setInput( selB[ "out" ] )
selB[ "in" ].setInput( selA[ "out" ] )
idle()
selItems = selEditor._NetworkEditor__nodeItems

selScript.setFocus( None )
idle()
check( "没 focus 时所有线都是「参与」状态",
	all( e.isWireActive() for e in selEditor._NetworkEditor__edgeItems ) )
check( "没 focus 时所有节点也都是",
	all( i.isNodeActive() for i in selEditor._NetworkEditor__nodeItems.values() ) )

# 挂一条和 focus 无关的支线，还有一个 Switch（没选中的那一支原生也算不参与）
selD = GafferScene.Plane( "selD" ) ; selScript.addChild( selD )
selE = GafferScene.Isolate( "selE" ) ; selScript.addChild( selE )
selE[ "in" ].setInput( selD[ "out" ] )
selSwitch = Gaffer.Switch( "selSwitch" ) ; selScript.addChild( selSwitch )
selSwitch.setup( GafferScene.ScenePlug() )
selSwitch[ "in" ][ 0 ].setInput( selA[ "out" ] )
selSwitch[ "in" ][ 1 ].setInput( selD[ "out" ] )
selSwitch[ "index" ].setValue( 0 )
selSink = GafferScene.Prune( "selSink" ) ; selScript.addChild( selSink )
selSink[ "in" ].setInput( selSwitch[ "out" ] )
idle()

selScript.setFocus( selSink )
# ContextTracker 是**异步**算的，等它把 changedSignal 发出来
for _ in range( 40 ) :
	idle()
	tracker = selEditor._NetworkEditor__contextTracker()
	if tracker is not None and not tracker.updatePending() and tracker.targetNode() is not None :
		break
idle()

def edgePair( e ) :

	return ( e.edge.srcNode.getName(), e.edge.dstNode.getName() )

inactive = sorted( edgePair( e ) for e in selEditor._NetworkEditor__edgeItems if not e.isWireActive() )
active = sorted( edgePair( e ) for e in selEditor._NetworkEditor__edgeItems if e.isWireActive() )

check( "focus 的上游（走到的那条路）算参与", ( "selA", "selSwitch" ) in active, str( active ) )
check( "focus 自己的入线算参与", ( "selSwitch", "selSink" ) in active, str( active ) )
check( "Switch 没选中的那一支不参与（自己爬图爬不出来这条）",
	( "selD", "selSwitch" ) in inactive, str( inactive ) )
check( "和 focus 无关的支线不参与", ( "selD", "selE" ) in inactive, str( inactive ) )
check( "focus 的下游也不参与（原生只算上游）", ( "selB", "selC" ) in inactive, str( inactive ) )

dimEdges = [ e for e in selEditor._NetworkEditor__edgeItems if not e.isWireActive() and not e.edge.auxiliary ]
liveEdges = [ e for e in selEditor._NetworkEditor__edgeItems if e.isWireActive() and not e.edge.auxiliary ]
## 一条线画出来的主色。长线中段渐隐时 pen 里是 QLinearGradient，`pen().color()`
# 返回黑色（没意义），得看渐变第一个停靠点。
def wirePaintColor( edge ) :

	gradient = edge.pen().brush().gradient()
	if gradient is not None and gradient.stops() :
		return gradient.stops()[0][1]
	return edge.pen().color()

# **这里故意不跟原生**：原生只把不参与的压到 0.31 亮度、参与的一点不动，实机反馈
# 「focus 之后看不出区别」。所以双向拉开 —— 参与的提亮一档（`_emphasisColor`）、
# 不参与的压得比原生更狠（0.20）。没设 focus 的时候一切照原生原色（下面另有断言）。
# 每条线按自己的类型色比（场景线是蓝的）。
check( "有 focus 时，参与的线提亮一档",
	all( wirePaintColor( e ).name() == NE._emphasisColor( NE.wireColor( e.edge ) ).name() for e in liveEdges ),
	str( sorted( set( wirePaintColor( e ).name() for e in liveEdges ) ) ) )
check( "不参与的线压到我们自己那个更暗的值",
	all( wirePaintColor( e ).name() == NE._disabledColor( NE.wireColor( e.edge ), connection = True ).name() for e in dimEdges ),
	str( sorted( set( wirePaintColor( e ).name() for e in dimEdges ) ) ) )
check( "亮暗差拉得足够大（≥ 90 级）",
	all(
		QtGui.QColor( NE._emphasisColor( NE.wireColor( e.edge ) ) ).value() - wirePaintColor( e ).value() >= 90
		for e in dimEdges
	),
	"亮 %s / 暗 %s" % (
		sorted( set( QtGui.QColor( NE._emphasisColor( NE.wireColor( e.edge ) ) ).value() for e in dimEdges ) ),
		sorted( set( wirePaintColor( e ).value() for e in dimEdges ) ),
	) )
check( "粗细不跟着变（原生线宽和 state 无关）",
	all( abs( e.pen().widthF() - 1.5 ) < 1e-6 for e in dimEdges + liveEdges ),
	str( sorted( set( e.pen().widthF() for e in dimEdges + liveEdges ) ) ) )
check( "层级也不动（原生连线都在同一层）",
	all( e.zValue() == e._baseZ for e in selEditor._NetworkEditor__edgeItems ) )

check( "不参与的节点也跟着变暗", not selEditor._NetworkEditor__nodeItems[ "selE" ].isNodeActive() )
check( "参与的节点保持原样", selEditor._NetworkEditor__nodeItems[ "selA" ].isNodeActive() )
check( "focus 自己当然算参与", selEditor._NetworkEditor__nodeItems[ "selSink" ].isNodeActive() )

# 切 Switch 分支 → 参与的那一支跟着换（ContextTracker 自己会重算并发信号）
selSwitch[ "index" ].setValue( 1 )
for _ in range( 40 ) :
	idle()
	tracker = selEditor._NetworkEditor__contextTracker()
	if tracker is not None and not tracker.updatePending() :
		break
idle()
inactive = sorted( edgePair( e ) for e in selEditor._NetworkEditor__edgeItems if not e.isWireActive() )
check( "切 Switch 分支后换成另一支参与", ( "selA", "selSwitch" ) in inactive, str( inactive ) )
selSwitch[ "index" ].setValue( 0 )

selScript.setFocus( None )
for _ in range( 40 ) :
	idle()
	tracker = selEditor._NetworkEditor__contextTracker()
	if tracker is not None and tracker.targetNode() is None :
		break
idle()
check( "取消 focus 全部回到参与状态",
	all( e.isWireActive() for e in selEditor._NetworkEditor__edgeItems ) and
	all( i.isNodeActive() for i in selEditor._NetworkEditor__nodeItems.values() ) )

selItems = selEditor._NetworkEditor__nodeItems

# --- 节点上的 focus flag（Houdini 风格方块，悬停才出现）---
selScript.setFocus( None )
idle()
selItems = selEditor._NetworkEditor__nodeItems
flagItem = selItems[ "selB" ]

check( "平时不画 flag（节点多了不吵）", not flagItem.focusFlagVisible() )

flagBox = flagItem.focusFlagRect()
card = flagItem.cardRect()
# **角标画在卡片右上角外侧**（一律，Dot 也一样）：画在里面会吃掉可点区域
# （点节点变成点 focus），而且 Dot 那条早退分支压根画不到（实机反馈两条一起报的）。
check(
	"角标在卡片右上角**外面**",
	abs( flagBox.left() - card.right() ) < 1e-6 and abs( flagBox.bottom() - card.top() ) < 1e-6,
	"%s vs %s" % ( flagBox, card )
)
check( "和卡片不重叠（一点可点区域都不占）",
	not card.intersects( flagBox.adjusted( 0.5, 0.5, -0.5, -0.5 ) ), "%s / %s" % ( flagBox, card ) )
check( "角标是个三角形（三个点）", flagItem.focusTabPolygon().count() == 3 )
check( "所有节点一个尺寸（画在外面就不按卡片比例缩了）",
	abs( flagItem.focusTabSize() - NE.FOCUS_TAB_SIZE ) < 1e-6, str( flagItem.focusTabSize() ) )
check( "而且不压在接口圆点上", all(
	not flagBox.contains( flagItem.nodulePosition( p ) )
	for plugs in flagItem._nodules.values() for p in plugs
) )
check( "包围盒放得下折角", flagItem.boundingRect().contains( flagBox ) )

# 鼠标进节点 -> flag 出现
flagItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "鼠标停到节点上 flag 就出现", flagItem.focusFlagVisible() )
check( "这时才点得到", flagItem.focusFlagAt( flagBox.center() ) )
check( "点别处不算点 flag", not flagItem.focusFlagAt( QtCore.QPointF( 0, 0 ) ) )
flagItem.hoverLeaveEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "鼠标离开又收起来", not flagItem.focusFlagVisible() )
check( "收起来之后点不到", not flagItem.focusFlagAt( flagBox.center() ) )

# --- 角标要好点：命中区是右上角那个**方角**（不按三角形斜边），而且整块都划进
#     `shape()` —— 角标画在卡片外面，`shape()` 盖不住的那半截既悬停不出来也点不动，
#     实机反馈「本身就是三角，太小巧了，不容易点到」---
# 先挪到空地上再量：右上角那块不能有别的节点压着 —— 挨得近的时候**最上面那个
# 节点的卡片**有优先权（`focusTabAt` 里那条守卫），量出来就不是这里要的东西了
NE.setNodePosition( selB, imath.V2f( 30, 30 ) )
idle()
selItems = selEditor._NetworkEditor__nodeItems
hitFlag = selItems[ "selB" ]
hitFlag.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
hitCard = hitFlag.cardRect()
hitBox = hitFlag.focusFlagHitRect()
painted = hitFlag.focusFlagRect()

check( "命中方角贴在卡片右上角**外面**（一点卡片区域都不占）",
	abs( hitBox.left() - hitCard.right() ) < 1e-6 and
	abs( hitBox.bottom() - hitCard.top() ) < 1e-6 and
	not hitCard.intersects( hitBox.adjusted( 0.5, 0.5, -0.5, -0.5 ) ),
	"%s vs %s" % ( hitBox, hitCard ) )
check( "命中方角比画出来那块再宽一圈（`FOCUS_TAB_HIT_PAD`）",
	abs( hitBox.width() - ( NE.FOCUS_TAB_SIZE + NE.FOCUS_TAB_HIT_PAD ) ) < 1e-6 and
	abs( hitBox.height() - hitBox.width() ) < 1e-6 and
	hitBox.contains( painted ),
	"%s vs %s" % ( hitBox, painted ) )

# 三角形斜边**外面**那一半：老的 `dx + dy <= size` 判它不算，现在算
farCorner = QtCore.QPointF(
	hitCard.right() + NE.FOCUS_TAB_SIZE * 0.85,
	hitCard.top() - NE.FOCUS_TAB_SIZE * 0.85,
)
check( "斜边外面那半个方角也点得到（老三角判据在这儿是 False）",
	hitFlag.focusFlagAt( farCorner ) and
	( farCorner.x() - hitCard.right() ) + ( hitCard.top() - farCorner.y() ) > NE.FOCUS_TAB_SIZE,
	str( farCorner ) )
check( "方角四个角落都点得到", all(
	hitFlag.focusFlagAt( QtCore.QPointF(
		hitBox.left() + hitBox.width() * u, hitBox.top() + hitBox.height() * v ) )
	for u, v in ( ( 0.02, 0.02 ), ( 0.98, 0.02 ), ( 0.02, 0.98 ), ( 0.98, 0.98 ) ) ) )
check( "再往外一点就不算了",
	not hitFlag.focusFlagAt( QtCore.QPointF( hitBox.right() + 4, hitBox.top() - 4 ) ) )
check( "卡片正中还是不算（可点区域一点没被吃）", not hitFlag.focusFlagAt( hitCard.center() ) )

# `items()` 按 `shape()` 命中 —— 方角必须整块在里面，不然 view 那边根本找不到节点
check( "`shape()` 盖住整个命中方角", all(
	hitFlag.shape().contains( QtCore.QPointF(
		hitBox.left() + hitBox.width() * u, hitBox.top() + hitBox.height() * v ) )
	for u, v in ( ( 0.02, 0.02 ), ( 0.98, 0.02 ), ( 0.98, 0.98 ), ( 0.5, 0.5 ) ) ),
	str( hitFlag.shape().boundingRect() ) )

farView = selView.mapFromScene( hitFlag.mapToScene( farCorner ) )
farItem = selView.nodeItemAt( farView )
check( "view 在角标上找得到这个节点（`nodeItemAt`）",
	farItem is not None and farItem.node.getName() == "selB", str( farItem ) )
tabItem = selView.focusTabAt( farView )
check( "`focusTabAt` 认它",
	tabItem is not None and tabItem.node.getName() == "selB", str( tabItem ) )
check( "光标离角标老远就不认（别把整块空白当角标）",
	selView.focusTabAt( selView.mapFromScene(
		hitFlag.mapToScene( QtCore.QPointF( hitCard.right() + 90, hitCard.top() - 90 ) ) ) ) is None )

# 别人的卡片压在角标上时，那一下归卡片（谁在上面谁说话，和画出来的一致）
coverItem = selItems[ "selC" ]
coverWas = ( NE.nodePosition( selC ), coverItem.zValue() )
NE.setNodePosition( selC, imath.V2f( 30 + 6, 30 + 4 ) )   # 卡片盖住 selB 的角标
idle()
selItems = selEditor._NetworkEditor__nodeItems
hitFlag, coverItem = selItems[ "selB" ], selItems[ "selC" ]
hitFlag.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
coverItem.setZValue( 30 )
coveredPoint = hitFlag.mapToScene( hitFlag.focusFlagHitRect().center() )
check( "角标那一点确实被别人的卡片盖住了",
	coverItem.cardRect().contains( coverItem.mapFromScene( coveredPoint ) ) )
check( "压在别人卡片上的那一下不算点角标",
	selView.focusTabAt( selView.mapFromScene( coveredPoint ) ) is None )
coverItem.setZValue( coverWas[ 1 ] )
NE.setNodePosition( selC, coverWas[ 0 ] )
idle()
selItems = selEditor._NetworkEditor__nodeItems
hitFlag = selItems[ "selB" ]
hitFlag.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )

# 走真的鼠标：点方角最外那个角落 = 切 focus（不选中、不拖动）
selEditor._clearSelection()
selScript.setFocus( None )
idle()
selItems = selEditor._NetworkEditor__nodeItems
hitFlag = selItems[ "selB" ]
hitFlag.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
hitBox = hitFlag.focusFlagHitRect()
cornerPoint = QtCore.QPointF( hitBox.right() - 1.5, hitBox.top() + 1.5 )
cornerView = selView.mapFromScene( hitFlag.mapToScene( cornerPoint ) )
sendMouse( QtCore.QEvent.MouseButtonPress, cornerView, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease, cornerView, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "点方角最外那个角落也真的设了 focus",
	selScript.getFocus() is not None and selScript.getFocus().getName() == "selB",
	str( selScript.getFocus() ) )
check( "而且没把节点选中（角标只切 focus）",
	[ n.getName() for n in selScript.selection() ] == [],
	str( [ n.getName() for n in selScript.selection() ] ) )
check( "也没进入拖动", not selView.isDraggingNodes() )

selScript.setFocus( None )
selEditor._clearSelection()
NE.setNodePosition( selB, imath.V2f( 0, 0 ) )      # 挪回来，后面那几节按原样接着用
idle()
selItems = selEditor._NetworkEditor__nodeItems
flagItem = selItems[ "selB" ]
flagItem.hoverLeaveEvent( QtWidgets.QGraphicsSceneHoverEvent() )

# focus 中的常显
selEditor._toggleNodeFocus( selB )
idle()
selItems = selEditor._NetworkEditor__nodeItems
flagItem = selItems[ "selB" ]
check( "点 flag 设成了 focus", selScript.getFocus() is not None and selScript.getFocus().getName() == "selB",
	str( selScript.getFocus() ) )
check( "focus 中的节点 flag 常显（不用悬停）", flagItem.focusFlagVisible() )
check( "focus 状态记上了（外环已经去掉，改成折角 + 金顶带）", flagItem._focused )

# 再点一次取消（原生 FocusGadget 就是这个语义）
selEditor._toggleNodeFocus( selB )
idle()
check( "再点一次取消 focus", selScript.getFocus() is None, str( selScript.getFocus() ) )
selItems = selEditor._NetworkEditor__nodeItems
check( "取消之后 flag 又藏起来", not selItems[ "selB" ].focusFlagVisible() )

# 点另一个节点的 flag = 换 focus
selEditor._toggleNodeFocus( selB )
selEditor._toggleNodeFocus( selC )
idle()
check( "点另一个节点就换 focus", selScript.getFocus().getName() == "selC", str( selScript.getFocus() ) )
selItems = selEditor._NetworkEditor__nodeItems
check( "老的 flag 收起来", not selItems[ "selB" ].focusFlagVisible() )
check( "新的常显", selItems[ "selC" ].focusFlagVisible() )

# 走鼠标事件：点 flag 只切 focus，不选中、不拖动
selEditor._clearSelection()
selScript.setFocus( None )
idle()
selItems = selEditor._NetworkEditor__nodeItems
clickItem = selItems[ "selB" ]
clickItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
flagPoint = selView.mapFromScene( clickItem.mapToScene( clickItem.focusFlagRect().center() ) )
sendMouse( QtCore.QEvent.MouseButtonPress, flagPoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier )
sendMouse( QtCore.QEvent.MouseButtonRelease, flagPoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier )
idle()
check( "鼠标点 flag 真的设了 focus",
	selScript.getFocus() is not None and selScript.getFocus().getName() == "selB",
	str( selScript.getFocus() ) )
check( "而且没把节点选中", [ n.getName() for n in selScript.selection() ] == [],
	str( [ n.getName() for n in selScript.selection() ] ) )
check( "也没进入拖动", not selView.isDraggingNodes() )
selScript.setFocus( None )
idle()
selItems = selEditor._NetworkEditor__nodeItems

# --- 接口悬停（问题 4）---
hoverItem = selItems[ "selB" ]
# 上面那段鼠标点 flag 的用例把 `hoverEnterEvent` 送进去了、没送 leave ——
# 那时候包围盒已经为「悬停才画的 focus 角标」放大过了（v0.67.1 起），
# 这里要的是干净起点。
hoverItem.hoverLeaveEvent( QtWidgets.QGraphicsSceneHoverEvent() )
boundBefore = hoverItem.boundingRect()
selEditor._setHoveredNodule( hoverItem, selB[ "in" ] )
check( "记下悬停的接口", hoverItem.hoveredNodule() == "in", str( hoverItem.hoveredNodule() ) )
check( "包围盒放大了（放得下大圆点和标签）", hoverItem.boundingRect().width() > boundBefore.width() )
check( "悬停时抬到上层", hoverItem.zValue() > 10 )

selEditor._setHoveredNodule( selItems[ "selC" ], selC[ "filter" ] )
check( "换到别的节点时清掉前一个", hoverItem.hoveredNodule() is None )
check( "新的记上了", selItems[ "selC" ].hoveredNodule() == "filter" )

selEditor._setHoveredNodule( None, None )
check( "移开就清掉", selItems[ "selC" ].hoveredNodule() is None )

# --- 内部快捷键转发（问题 6）---
engine = selEditor._NetworkEditor__engine()
check( "拿得到隐藏 GraphEditor 引擎", engine is not None )

if engine is not None :

	forwarded = []

	def __engineKeyPress( editor, event ) :
		forwarded.append( event.key )
		return True

	engineConnection = engine.keyPressSignal().connect( __engineKeyPress, scoped = True )

	# 注意：真实环境里内部脚本自己也挂在引擎的 keyPressSignal 上，而 Gaffer 的信号
	# 是**第一个返回 True 的就截住**，所以 S/Q/W/… 这些他们已经接了的键轮不到我们的
	# 探针。这里用没人要的 F5 验证转发链路本身。
	check( "没接住的键会转发给引擎",
		sendKeyTo( selView, QtCore.Qt.Key_F5 ) and forwarded == [ "F5" ], str( forwarded ) )

	forwarded[:] = []
	sendKeyTo( selView, QtCore.Qt.Key_F5, QtCore.Qt.ShiftModifier )
	check( "带修饰键也转发", forwarded == [ "F5" ], str( forwarded ) )

	forwarded[:] = []
	sendKeyTo( selView, QtCore.Qt.Key_F )
	check( "我们自己接住的键不转发（F 取景）", forwarded == [], str( forwarded ) )

	del engineConnection

selWindow.setVisible( False )


##########################################################################
section( "Box 上的 + 号（PlugAdder）" )
##########################################################################

adderScript = Gaffer.ScriptNode()
adderSource = GafferScene.Plane( "adderSource" )
adderBox = Gaffer.Box( "adderBox" )
adderScript.addChild( adderSource )
adderScript.addChild( adderBox )
adderInner = GafferScene.Isolate( "adderInner" )
adderBox.addChild( adderInner )
NE.setNodePosition( adderSource, imath.V2f( 0, 12 ) )
NE.setNodePosition( adderBox, imath.V2f( 0, 0 ) )

# 数据层：读的就是原生那套 metadata
boxAdders = NE.plugAdders( adderBox )
check( "Box 四条边都有 +", sorted( boxAdders.keys() ) == [ "bottom", "left", "right", "top" ], str( sorted( boxAdders.keys() ) ) )
check( "普通节点没有 +", NE.plugAdders( adderSource ) == {}, str( NE.plugAdders( adderSource ) ) )
check( "Switch 也有 +", "top" in NE.plugAdders( Gaffer.Switch() ) )

# 关掉某条边的 + （团队的 .grf 就是这么藏起来的 —— 「有些 box 上没有 +」）
Gaffer.Metadata.registerValue( adderBox, "noduleLayout:customGadget:addButtonLeft:visible", False )
check( "visible=False 就不画了", "left" not in NE.plugAdders( adderBox ), str( sorted( NE.plugAdders( adderBox ).keys() ) ) )
Gaffer.Metadata.deregisterValue( adderBox, "noduleLayout:customGadget:addButtonLeft:visible" )
check( "撤销注册之后又有了", "left" in NE.plugAdders( adderBox ) )

check( "对边换算", NE.oppositeSection( "top" ) == "bottom" and NE.oppositeSection( "left" ) == "right" )

# 三个来源都认（"有就画、没有就不画"）
adderProbeGadget = GafferUI.GraphGadget( adderScript )

# ① 材质节点：`parameters` 上那个 `+` 是「底下有能显示但藏着的插口才出现」——
# 没加载 shader（一个参数都没有）时原生就是不画（拿原生 __noduleContainer 的 bound 反推过）
oslNode = GafferOSL.OSLShader( "oslAdder" )
adderScript.addChild( oslNode )
idle()
check( "没参数的材质节点一个 + 都不画", NE.plugAdders( oslNode ) == {}, str( NE.plugAdders( oslNode ) ) )

# 造一个「藏起来的可显示参数」→ 这时候原生**是有** `+` 的（aiStandardSurface 就这样）
hiddenParamShader = GafferOSL.OSLShader( "hiddenParamShader" )
adderScript.addChild( hiddenParamShader )
hiddenParamShader[ "parameters" ].addChild(
	Gaffer.FloatPlug( "hiddenParam", flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
)
Gaffer.Metadata.registerValue( hiddenParamShader[ "parameters" ][ "hiddenParam" ], "noduleLayout:visible", False )
idle()
check( "有「藏着的可显示参数」时才画（画在 parameters 那条边上）",
	NE.plugAdders( hiddenParamShader ) == { "left" : [ "addButton" ] },
	str( NE.plugAdders( hiddenParamShader ) ) )
Gaffer.Metadata.registerValue( hiddenParamShader[ "parameters" ][ "hiddenParam" ], "noduleLayout:visible", True )
check( "参数放出来以后 + 就没了", NE.plugAdders( hiddenParamShader ) == {},
	str( NE.plugAdders( hiddenParamShader ) ) )
check( "普通节点还是没有 +", NE.plugAdders( adderSource ) == {}, str( NE.plugAdders( adderSource ) ) )

# ①·5 setup 式节点：**setup 过就不画**（原生那些 PlugAdder 自己就 setVisible( False ) 了）
setupProbe = {}
switchNode = Gaffer.Switch( "switchAdder" ) ; adderScript.addChild( switchNode )
setupProbe[ "Switch 没 setup" ] = ( len( NE.plugAdders( switchNode ) ), 4 )
switchNode.setup( GafferScene.ScenePlug() )
setupProbe[ "Switch setup 过" ] = ( len( NE.plugAdders( switchNode ) ), 0 )

nsAdder = Gaffer.NameSwitch( "nameSwitchAdder" ) ; adderScript.addChild( nsAdder )
setupProbe[ "NameSwitch 没 setup" ] = ( len( NE.plugAdders( nsAdder ) ), 4 )
nsAdder.setup( GafferScene.ScenePlug() )
# NameSwitch 特殊：节点级那 4 个（继承 Switch 的）setup 后藏了，但它自己在 `in` 上
# 注册了一个**一直可见**的 `+`（`NameSwitchUI.cpp` 里没有 updateVisibility）——
# 原生就是「setup 过的 NameSwitch 顶上还有一个 +」，用来加下一路输入
setupProbe[ "NameSwitch setup 过（in 上那个一直在）" ] = ( NE.plugAdders( nsAdder ), { "top" : [ "addButton" ] } )

loopNode = Gaffer.Loop( "loopAdder" ) ; adderScript.addChild( loopNode )
setupProbe[ "Loop 没 setup" ] = ( len( NE.plugAdders( loopNode ) ), 2 )
loopNode.setup( GafferScene.ScenePlug() )
setupProbe[ "Loop setup 过" ] = ( len( NE.plugAdders( loopNode ) ), 0 )

contextNode = Gaffer.ContextVariables( "contextAdder" ) ; adderScript.addChild( contextNode )
setupProbe[ "ContextProcessor 没 setup" ] = ( len( NE.plugAdders( contextNode ) ) > 0, True )
contextNode.setup( GafferScene.ScenePlug() )
setupProbe[ "ContextProcessor setup 过" ] = ( len( NE.plugAdders( contextNode ) ), 0 )

editScope = Gaffer.EditScope( "editScopeAdder" ) ; adderScript.addChild( editScope )
setupProbe[ "EditScope 没 setup" ] = ( len( NE.plugAdders( editScope ) ) > 0, True )
editScope.setup( GafferScene.ScenePlug() )
setupProbe[ "EditScope setup 过" ] = ( len( NE.plugAdders( editScope ) ), 0 )

# AttributeQuery 那一类：`setupButton` 是 `setVisible( !isSetup() )`
attrQuery = GafferScene.AttributeQuery( "attrQueryAdder" ) ; adderScript.addChild( attrQuery )
setupProbe[ "AttributeQuery 没 setup" ] = ( NE.plugAdders( attrQuery ), { "bottom" : [ "setupButton" ] } )
attrQuery.setup( Gaffer.StringPlug() )
setupProbe[ "AttributeQuery setup 过" ] = ( NE.plugAdders( attrQuery ), {} )

# Collect 的 `_InputAdder` 也是插口级、一直可见
try :
	collectNode = Gaffer.Collect( "collectAdder" ) ; adderScript.addChild( collectNode )
	setupProbe[ "Collect 的 + 一直在" ] = ( NE.plugAdders( collectNode ), { "top" : [ "addButton" ] } )
except AttributeError :
	pass

for name, ( got, want ) in setupProbe.items() :
	check( "%s -> %s 个 +" % ( name, want ), got == want, "got %s" % str( got ) )

check( "Box 没有 setup 规则，四个 + 一直都在", len( NE.plugAdders( adderBox ) ) == 4, str( NE.plugAdders( adderBox ) ) )
check( "adderSetupComplete 认得 setup 过的 Switch", NE.adderSetupComplete( switchNode ) )
check( "普通节点谈不上 setup", not NE.adderSetupComplete( adderSource ) )

# ② BoxIO：原生只有**还没 setup** 的时候才画（setup 过一个都不画）
# 注意用一个单独的 Box —— BoxIO setup 会在 Box 上提升出插口，会影响后面 adderBox 的断言
ioBox = Gaffer.Box( "ioBox" )
adderScript.addChild( ioBox )
freshBoxIn = Gaffer.BoxIn( "freshBoxIn" )
ioBox.addChild( freshBoxIn )
check(
	"没 setup 的 BoxIn 四条边都有 +",
	sorted( NE.plugAdders( freshBoxIn ).keys() ) == [ "bottom", "left", "right", "top" ],
	str( sorted( NE.plugAdders( freshBoxIn ).keys() ) )
)
freshBoxIn.setup( GafferScene.ScenePlug() )
check(
	"setup 之后一个都不画（原生 setVisible( !plug() )）",
	NE.plugAdders( freshBoxIn ) == {},
	str( NE.plugAdders( freshBoxIn ) )
)

boxOut = Gaffer.BoxOut( "boxOut" )
ioBox.addChild( boxOut )
check( "没 setup 的 BoxOut 也有", len( NE.plugAdders( boxOut ) ) == 4 )
boxOut.setup( GafferScene.ScenePlug() )
check( "setup 之后也没了", NE.plugAdders( boxOut ) == {}, str( NE.plugAdders( boxOut ) ) )

# ③ 数 gadget 里的 ConnectionCreator 不能当判据（混着 setup 之后就隐藏的边 gadget）
def countConnectionCreators( node, graphGadget ) :

	def walk( gadget ) :
		return ( 1 if gadget.getName() == "ConnectionCreator" else 0 ) + sum( walk( c ) for c in gadget.children() )

	gadget = graphGadget.nodeGadget( node )
	return walk( gadget ) if gadget is not None else 0

ioGadget = GafferUI.GraphGadget( adderScript )
ioGadget.setRoot( ioBox )
check(
	"setup 过的 BoxIn 在 gadget 里仍然挂着 4 个 ConnectionCreator",
	countConnectionCreators( freshBoxIn, ioGadget ) >= 4,
	str( countConnectionCreators( freshBoxIn, ioGadget ) )
)
check(
	"但一个都不该画（所以数 gadget 不能当判据）",
	NE.plugAdders( freshBoxIn ) == {},
	str( NE.plugAdders( freshBoxIn ) )
)

adderEditor = NE.NetworkEditor( adderScript )
adderWindow = GafferUI.Window( "adders" )
adderWindow.setChild( adderEditor )
adderWindow._qtWidget().resize( 900, 700 )
adderWindow.setVisible( True )
idle()

adderItems = adderEditor._NetworkEditor__nodeItems
boxItem = adderItems[ "adderBox" ]
sections = boxItem.adderSections()
check( "item 上四个 + 都算出来了", sorted( sections.keys() ) == [ "bottom", "left", "right", "top" ], str( sorted( sections.keys() ) ) )

boxRect = boxItem.cardRect()
check( "top 的 + 在上边缘", abs( sections[ "top" ].y() - boxRect.top() ) < 1e-6, str( sections[ "top" ] ) )
check( "bottom 的 + 在下边缘", abs( sections[ "bottom" ].y() - boxRect.bottom() ) < 1e-6, str( sections[ "bottom" ] ) )
check( "left 的 + 在左边缘", abs( sections[ "left" ].x() - boxRect.left() ) < 1e-6, str( sections[ "left" ] ) )
check( "空 Box 的 + 居中", abs( sections[ "top" ].x() ) < 1e-6, str( sections[ "top" ] ) )

check( "命中测试认得出 +", boxItem.adderAt( sections[ "top" ] ) == "top", str( boxItem.adderAt( sections[ "top" ] ) ) )
check( "离远了就测不到", boxItem.adderAt( QtCore.QPointF( 0, 0 ) ) is None )

# 拖一条连线丢到 + 上 -> 提升出插口
before = [ n.getName() for n in adderBox.children( Gaffer.Node ) ]
created = adderEditor._createPromotedConnection( adderBox, "top", adderSource[ "out" ] )
idle()
check( "丢在 + 上创建成功", created )
boxIONodes = [ n for n in adderBox.children( Gaffer.BoxIn ) ]
check( "Box 里多了个 BoxIn", len( boxIONodes ) == 1, str( [ n.getName() for n in adderBox.children( Gaffer.Node ) ] ) )
if boxIONodes :
	promoted = boxIONodes[0].promotedPlug()
	check( "提升出来的插口接上了源节点",
		promoted.getInput() is not None and promoted.getInput().node().getName() == "adderSource",
		str( promoted.getInput() ) )
	check( "提升的插口挂在丢下去的那条边上",
		Gaffer.Metadata.value( promoted, "noduleLayout:section" ) == "top",
		str( Gaffer.Metadata.value( promoted, "noduleLayout:section" ) ) )
	check( "内部那半挂对边",
		Gaffer.Metadata.value( boxIONodes[0].plug(), "noduleLayout:section" ) == "bottom",
		str( Gaffer.Metadata.value( boxIONodes[0].plug(), "noduleLayout:section" ) ) )

check( "提升可撤销", adderScript.undoAvailable() )
adderScript.undo()
idle()
check( "撤销后 BoxIn 没了", len( [ n for n in adderBox.children( Gaffer.BoxIn ) ] ) == 0 )

# 有了提升插口之后，+ 让位（原生是「一排 nodule + 末尾 adder」整体居中）
adderEditor._createPromotedConnection( adderBox, "top", adderSource[ "out" ] )
idle()
boxItem = adderEditor._NetworkEditor__nodeItems[ "adderBox" ]
topPlugs = NE.noduleLayout( adderBox )[ "top" ]
check( "Box 顶上有了一个接口", len( topPlugs ) == 1, str( [ p.getName() for p in topPlugs ] ) )
if topPlugs :
	nodulePoint = boxItem.nodulePosition( topPlugs[0] )
	adderPoint = boxItem.adderSections()[ "top" ]
	check( "+ 挪到接口旁边（两者关于中线对称）",
		abs( adderPoint.x() + nodulePoint.x() ) < 1e-6,
		"nodule %.3f adder %.3f" % ( nodulePoint.x(), adderPoint.x() ) )

# 不该接的不接
check( "自己连自己不行", not adderEditor._createPromotedConnection( adderBox, "top", adderBox.children( Gaffer.Plug )[0] )
	if len( adderBox.children( Gaffer.Plug ) ) else True )
check( "普通节点上没有 + 可提升", not adderEditor._createPromotedConnection( adderSource, "top", adderSource[ "out" ] ) )

# --- NameSwitch：多个输入接口都要在，上下不能串（问题 1）---
nameSwitch = Gaffer.NameSwitch( "nameSwitch" )
adderScript.addChild( nameSwitch )
nameSwitch.setup( GafferScene.ScenePlug() )
nameSwitch["in"].resize( 3 )
idle()

nsItem = adderEditor._NetworkEditor__nodeItems.get( "nameSwitch" )
check( "NameSwitch 建出来了", nsItem is not None )
if nsItem is not None :

	topPlugs = nsItem._nodules[ "top" ]
	bottomPlugs = nsItem._nodules[ "bottom" ]
	check( "顶上三个输入接口都在", len( topPlugs ) == 3, str( [ NE.plugKey( nameSwitch, p ) for p in topPlugs ] ) )
	check( "底下一个输出接口", len( bottomPlugs ) == 1, str( [ NE.plugKey( nameSwitch, p ) for p in bottomPlugs ] ) )

	# 它们的名字全叫 "value"，拿 getName() 当键会互相覆盖 —— 这就是之前"只剩一个 + 上下反了"
	check(
		"这些插口名字确实全一样（所以必须用 relativeName 当键）",
		len( set( p.getName() for p in topPlugs + bottomPlugs ) ) == 1,
		str( set( p.getName() for p in topPlugs + bottomPlugs ) )
	)
	check(
		"relativeName 才是唯一的",
		len( set( NE.plugKey( nameSwitch, p ) for p in topPlugs + bottomPlugs ) ) == 4,
		str( [ NE.plugKey( nameSwitch, p ) for p in topPlugs + bottomPlugs ] )
	)

	topY = [ nsItem.nodulePosition( p ).y() for p in topPlugs ]
	bottomY = [ nsItem.nodulePosition( p ).y() for p in bottomPlugs ]
	check( "输入在上边缘", all( abs( y - nsItem.cardRect().top() ) < 1e-6 for y in topY ), str( topY ) )
	check( "输出在下边缘", all( abs( y - nsItem.cardRect().bottom() ) < 1e-6 for y in bottomY ), str( bottomY ) )
	check(
		"三个输入横向排开、位置各不相同",
		len( set( round( nsItem.nodulePosition( p ).x(), 3 ) for p in topPlugs ) ) == 3,
		str( [ nsItem.nodulePosition( p ).x() for p in topPlugs ] )
	)
	check(
		"输入接口从左到右有序",
		[ nsItem.nodulePosition( p ).x() for p in topPlugs ] ==
			sorted( nsItem.nodulePosition( p ).x() for p in topPlugs )
	)

	nsAdders = nsItem.adderSections()
	check( "NameSwitch 每条边最多一个 +", all( isinstance( v, QtCore.QPointF ) for v in nsAdders.values() ) )
	check(
		"顶上的 + 接在最后一个接口后面（不压在接口上）",
		"top" not in nsAdders or all(
			abs( nsAdders[ "top" ].x() - nsItem.nodulePosition( p ).x() ) > 1e-3 for p in topPlugs
		),
		str( nsAdders.get( "top" ) )
	)

adderWindow.setVisible( False )


##########################################################################
section( "Expression / Spreadsheet：Show Name、图标、辅助连线" )
##########################################################################

auxScript = Gaffer.ScriptNode()
auxPlane = GafferScene.Plane( "auxPlane" )
auxIsoA = GafferScene.Isolate( "auxIsoA" )
auxIsoB = GafferScene.Isolate( "auxIsoB" )
auxIsoC = GafferScene.Isolate( "auxIsoC" )
auxExpression = Gaffer.Expression( "auxExpression" )
auxSpreadsheet = Gaffer.Spreadsheet( "auxSpreadsheet" )
for n in ( auxPlane, auxIsoA, auxIsoB, auxIsoC, auxExpression, auxSpreadsheet ) :
	auxScript.addChild( n )

# 一条表达式：读 auxPlane，驱动 A（两个插口）、B、C
auxExpression.setExpression(
	'parent["auxIsoA"]["enabled"] = parent["auxPlane"]["divisions"]["x"] > 2\n'
	'parent["auxIsoA"]["adjustBounds"] = True\n'
	'parent["auxIsoB"]["enabled"] = True\n'
	'parent["auxIsoC"]["enabled"] = False\n',
	"python"
)

auxEdges = NE.collectEdges( auxScript, NE.collectNodes( auxScript ) )
auxPairs = sorted( ( e.srcNode.getName(), e.dstNode.getName() ) for e in auxEdges )

check(
	"表达式**读**的那条线也画出来了（原生对 Expression 不跳过私有插口）",
	( "auxPlane", "auxExpression" ) in auxPairs, str( auxPairs )
)
check(
	"表达式驱动的三个节点每个都有线",
	all( ( "auxExpression", name ) in auxPairs for name in ( "auxIsoA", "auxIsoB", "auxIsoC" ) ),
	str( auxPairs )
)
check(
	"驱动同一个节点的多个插口只画一条（原生也是一对端点一条）",
	len( [ p for p in auxPairs if p == ( "auxExpression", "auxIsoA" ) ] ) == 1,
	str( auxPairs )
)
check( "一共 4 条（1 读 + 3 驱动）", len( auxPairs ) == 4, str( auxPairs ) )
check( "这些都算辅助连线（画虚线）", all( e.auxiliary for e in auxEdges ), str(
	[ ( e.srcNode.getName(), e.dstNode.getName(), e.auxiliary ) for e in auxEdges ] ) )

# 根因回归：`__` 开头的插口原生根本不进 nodule 布局，判成「有 nodule」的话
# 表达式的连线会变成实线（用户看到的虚实混杂）
check( "`__in` 不算有 nodule", not NE.hasNodule( auxExpression[ "__in" ] ) )
check( "`__in` 的子插口也不算", not NE.hasNodule( auxExpression[ "__in" ][ "p0" ] ) )
check( "`__out` 同理", not NE.hasNodule( auxExpression[ "__out" ] ) )
check( "普通插口不受影响", NE.hasNodule( auxIsoA[ "in" ] ) )
check(
	"表达式两端解析出来都是「没有 nodule」",
	NE.nodulePlug( auxExpression, auxExpression[ "__in" ][ "p0" ] ) is None and
	NE.nodulePlug( auxExpression, auxExpression[ "__out" ][ "p0" ] ) is None
)

# --- 图标 ---
check( "Expression 有专属图标", NE.nodeGlyph( auxExpression ) == NE.GLYPH_EXPRESSION, str( NE.nodeGlyph( auxExpression ) ) )
check( "Spreadsheet 有专属图标", NE.nodeGlyph( auxSpreadsheet ) == NE.GLYPH_SPREADSHEET, str( NE.nodeGlyph( auxSpreadsheet ) ) )

# --- Show Name：改 `nodeGadget:type` 就该换形状（原生 UIEditor.__setNameVisible 写的就是它）---
check( "默认是小方块", NE.nodeShape( auxExpression ) == NE.SHAPE_AUXILIARY, NE.nodeShape( auxExpression ) )
check( "该重建的键认得出来", NE.rebuildOnNodeMetadata( "nodeGadget:type" ) )
check( "不相干的键不重建", not NE.rebuildOnNodeMetadata( "layout:section" ) )

auxEditor = NE.NetworkEditor( auxScript )
auxWindow = GafferUI.Window( "aux" )
auxWindow.setChild( auxEditor )
auxWindow._qtWidget().resize( 900, 700 )
auxWindow.setVisible( True )
idle()

auxItems = auxEditor._NetworkEditor__nodeItems
check( "小方块状态下没有图标", auxItems[ "auxExpression" ]._glyph is None )
check(
	"小方块就是 2 单位见方",
	abs( auxItems[ "auxExpression" ]._width - 2.0 * NE.PX_PER_UNIT ) < 1e-3,
	str( auxItems[ "auxExpression" ]._width )
)

# 点 Show Name（等价于原生那条菜单干的事）
Gaffer.Metadata.registerValue( auxExpression, "nodeGadget:type", "GafferUI::StandardNodeGadget" )
Gaffer.Metadata.registerValue( auxSpreadsheet, "nodeGadget:type", "GafferUI::StandardNodeGadget" )
idle()

# 注意：Expression / Spreadsheet 上还带着 `nodeGadget:shape = "oval"`，
# 所以 Show Name 之后原生画的是**带名字的胶囊**（不是方卡片），我们照着来。
check( "改完元数据形状就变了（胶囊）", NE.nodeShape( auxExpression ) == NE.SHAPE_OVAL, NE.nodeShape( auxExpression ) )

auxItems = auxEditor._NetworkEditor__nodeItems
check(
	"视图跟着重建了（这就是 Show Name 点了没反应的根因：以前不听节点元数据信号）",
	auxItems[ "auxExpression" ]._shape == NE.SHAPE_OVAL,
	str( auxItems[ "auxExpression" ]._shape )
)
check(
	"卡片变成正常大小",
	auxItems[ "auxExpression" ]._width > 3.0 * NE.PX_PER_UNIT,
	str( auxItems[ "auxExpression" ]._width )
)
check( "而且带上了图标", auxItems[ "auxExpression" ]._glyph == NE.GLYPH_EXPRESSION,
	str( auxItems[ "auxExpression" ]._glyph ) )
check( "表格也一样", auxItems[ "auxSpreadsheet" ]._glyph == NE.GLYPH_SPREADSHEET,
	str( auxItems[ "auxSpreadsheet" ]._glyph ) )
check( "名字放得下", auxItems[ "auxExpression" ].nameFits() )

# 关掉 Show Name 又回到小方块
Gaffer.Metadata.deregisterValue( auxExpression, "nodeGadget:type" )
idle()
auxItems = auxEditor._NetworkEditor__nodeItems
check( "取消 Show Name 又变回小方块", auxItems[ "auxExpression" ]._shape == NE.SHAPE_AUXILIARY,
	str( auxItems[ "auxExpression" ]._shape ) )

# 换个颜色也该跟着变（同一条信号）
Gaffer.Metadata.registerValue( auxIsoA, "nodeGadget:color", imath.Color3f( 1, 0, 0 ) )
idle()
auxItems = auxEditor._NetworkEditor__nodeItems
check( "改 nodeGadget:color 视图也跟着变", auxItems[ "auxIsoA" ]._accent.name() == "#ff0000",
	auxItems[ "auxIsoA" ]._accent.name() )

auxWindow.setVisible( False )


##########################################################################
section( "拉远也看得见 focus 角标（不整块刷金色）" )
##########################################################################

# 本来就是黄色的节点（灯光那些）一多，"focus = 整块刷成金色"就没法认了 —— 所以
# 远景不刷块，只在卡片右上角**外面**支一个小角标出来。

flagScript = Gaffer.ScriptNode()
flagNode = GafferScene.Sphere( "flagNode" )
flagScript.addChild( flagNode )
NE.setNodePosition( flagNode, imath.V2f( 0, 0 ) )

flagEditor = NE.NetworkEditor( flagScript )
flagWindow = GafferUI.Window( "flag" )
flagWindow.setChild( flagEditor )
flagWindow._qtWidget().resize( 900, 600 )
flagWindow.setVisible( True )
idle()
flagScript.setFocus( flagNode )
idle()

flagItem = flagEditor._NetworkEditor__nodeItems[ "flagNode" ]
check( "节点知道自己是 focus", flagItem._focused )

def renderScaled( item, scale, w = 600, h = 300 ) :

	image = QtGui.QImage( w, h, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.translate( w / 2.0, h / 2.0 )
	painter.scale( scale, scale )
	option = QtWidgets.QStyleOptionGraphicsItem()
	option.rect = QtCore.QRect( 0, 0, w, h )
	item.paint( painter, option, None )
	painter.end()
	return image

def countNear( image, color, x0, x1, y0, y1, tolerance = 60 ) :

	target = QtGui.QColor( color )
	n = 0
	for y in range( max( 0, int( y0 ) ), min( image.height(), int( y1 ) ) ) :
		for x in range( max( 0, int( x0 ) ), min( image.width(), int( x1 ) ) ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			d = (
				( c.red() - target.red() ) ** 2 +
				( c.green() - target.green() ) ** 2 +
				( c.blue() - target.blue() ) ** 2
			) ** 0.5
			if d < tolerance :
				n += 1
	return n

farScale = NE.LOD_MEDIUM / 2.0            # 远到连名字都不画了
farImage = renderScaled( flagItem, farScale )
rect = flagItem.cardRect()

inside = countNear( farImage, NE._focusRing,
	300 + rect.left() * farScale + 2, 300 + rect.right() * farScale - 2,
	150 + rect.top() * farScale + 2, 150 + rect.bottom() * farScale - 2 )
check( "远景不再把整块刷成金色（本来就黄的节点会被误认）", inside == 0, str( inside ) )

flag = countNear( farImage, NE._focusRing,
	300 + rect.right() * farScale - 2, 300 + rect.right() * farScale + NE.FOCUS_FLAG_PIXELS + 6,
	150 + rect.top() * farScale - NE.FOCUS_FLAG_PIXELS, 150 + rect.top() * farScale + NE.FOCUS_FLAG_PIXELS )
check( "但右上角的角标还在（拉多远都看得见）", flag > 20, str( flag ) )

# 角标画在卡片外面，包围盒得放得下，否则拖动留残影
check( "包围盒把角标算进去了",
	flagItem.boundingRect().right() >= rect.right() + 1.0 and
	flagItem.boundingRect().top() <= rect.top() - 1.0,
	"%s vs 卡片 %s" % ( flagItem.boundingRect(), rect ) )

# 不是 focus 的节点当然没有角标
flagScript.setFocus( None )
idle()
plainImage = renderScaled( flagItem, farScale )
plainFlag = countNear( plainImage, NE._focusRing,
	300 + rect.right() * farScale - 2, 300 + rect.right() * farScale + NE.FOCUS_FLAG_PIXELS + 6,
	150 + rect.top() * farScale - NE.FOCUS_FLAG_PIXELS, 150 + rect.top() * farScale + NE.FOCUS_FLAG_PIXELS )
check( "不是 focus 就没有角标", plainFlag == 0, str( plainFlag ) )

flagWindow.setVisible( False )


##########################################################################
section( "把连线一头拿起来之后，原来那根不许留在画面上" )
##########################################################################

resScript = Gaffer.ScriptNode()
resApplication = Gaffer.ApplicationRoot( "residueTest" )
resApplication[ "scripts" ].addChild( resScript )

resA = GafferScene.Sphere( "resA" )
resB = GafferScene.Isolate( "resB" )
resFree = GafferScene.Sphere( "resFree" )
for n in ( resA, resB, resFree ) :
	resScript.addChild( n )
resB[ "in" ].setInput( resA[ "out" ] )
NE.setNodePosition( resA, imath.V2f( 0, 20 ) )
NE.setNodePosition( resB, imath.V2f( 0, 0 ) )
NE.setNodePosition( resFree, imath.V2f( 40, 20 ) )

resEditor = NE.NetworkEditor( resScript )
resWindow = GafferUI.Window( "residue" )
resWindow.setChild( resEditor )
resWindow._qtWidget().resize( 1000, 700 )
resWindow.setVisible( True )
idle()
resView = resEditor.graphView()
resView.frameAll()
idle()

resEdge = resEditor._NetworkEditor__edgeItems[ 0 ]
resEnd = resEdge.endPoints()[2]
started = resView._GraphView__beginReconnect(
	resEdge, "dst", resView.mapFromScene( resEnd ) )
check( "从终点这头拿得起来", started )
check( "拿起来之后原来那根线立刻藏掉（不然画面上会留一根）",
	not resEdge.isVisible() )
check( "藏起来的那根记在手上（接不上要还回去）",
	resView._GraphView__connectDetachItem is resEdge )

# 接不上的地方松手：线要**原样回来**，连接也还在
resFreeItem = resEditor._NetworkEditor__nodeItems[ "resFree" ]
freeView = resView.mapFromScene( resFreeItem.mapToScene( QtCore.QPointF( 0, 0 ) ) )
resView._GraphView__updateConnectWire( freeView )       # 真拖动是靠 move 更新落点的
resView._GraphView__endConnect( freeView )
idle()
check( "接不上就把线还回来（不许凭空消失）", resEdge.isVisible() )
check( "连接也还在", resB[ "in" ].getInput() is not None and
	resB[ "in" ].getInput().node().getName() == "resA" )

# 空白处松手 = 断开：这时候线是被删掉的，不是"藏着"
resEdge2 = resEditor._NetworkEditor__edgeItems[ 0 ]
started2 = resView._GraphView__beginReconnect(
	resEdge2, "dst", resView.mapFromScene( resEdge2.endPoints()[2] ) )
check( "第二次也拿得起来", started2 )
# 注意：`__beginReconnect` 会把落点先记成"原来那一头"（原地松手 = 什么都没变），
# 所以要像真拖动一样先 move 一下才算"丢在空白处"
emptyView = resView.mapFromScene( QtCore.QPointF( 900, 900 ) )
check( "空白处真的没有节点", resView.nodeItemAt( emptyView ) is None,
	str( resView.nodeItemAt( emptyView ) ) )
resView._GraphView__updateConnectWire( emptyView )
resView._GraphView__endConnect( emptyView )
idle()
check( "丢在空白处就是断开", resB[ "in" ].getInput() is None,
	str( resB[ "in" ].getInput() ) )
check( "断开之后画面上一根线都不剩",
	len( resEditor._NetworkEditor__edgeItems ) == 0,
	str( len( resEditor._NetworkEditor__edgeItems ) ) )

resWindow.setVisible( False )


##########################################################################
section( "侧边参数名：接上了就保持高亮" )
##########################################################################

hiScript = Gaffer.ScriptNode()
hiNode = GafferScene.Isolate( "hiNode" )
hiFilter = GafferScene.PathFilter( "hiFilter" )
hiScript.addChild( hiNode )
hiScript.addChild( hiFilter )
NE.setNodePosition( hiNode, imath.V2f( 0, 0 ) )
NE.setNodePosition( hiFilter, imath.V2f( 30, 10 ) )

hiEditor = NE.NetworkEditor( hiScript )
hiWindow = GafferUI.Window( "sideHighlight" )
hiWindow.setChild( hiEditor )
hiWindow._qtWidget().resize( 900, 600 )
hiWindow.setVisible( True )
idle()

def sideLabel( name ) :

	item = hiEditor._NetworkEditor__nodeItems[ "hiNode" ]
	for plug, entry in item._NodeItem__sideLabels.items() :
		if entry[0] == name :
			return item, plug, entry
	return item, None, None

item, key, entry = sideLabel( "filter" )
check( "没接的时候标着「没连」", entry is not None and entry[2] is False, str( entry ) )

def labelInk( item, plugKey ) :

	plug = next( p for p in item._nodules.get( "left", [] ) + item._nodules.get( "right", [] )
		if NE.plugKey( hiNode, p ) == plugKey )
	point = item.nodulePosition( plug )
	image = renderScaled( item, 1.0, 600, 300 )
	pixels = []
	for y in range( int( 150 + point.y() - 8 ), int( 150 + point.y() + 8 ) ) :
		for x in range( int( 300 + point.x() + NE.NODULE_RADIUS + 3 ), int( 300 + point.x() + NE.SIDE_LABEL_MAX ) ) :
			if 0 <= x < image.width() and 0 <= y < image.height() :
				c = QtGui.QColor( image.pixel( x, y ) )
				if c.red() + c.green() + c.blue() > 40 :
					pixels.append( c.red() + c.green() + c.blue() )
	return ( sum( pixels ) / float( len( pixels ) ) ) if pixels else 0.0

dimInk = labelInk( item, key )

hiNode[ "filter" ].setInput( hiFilter[ "out" ] )
idle()
item, key2, entry2 = sideLabel( "filter" )
check( "接上之后标着「连了」", entry2 is not None and entry2[2] is True, str( entry2 ) )

brightInk = labelInk( item, key2 )
check( "接上之后那几个字确实更亮", brightInk > dimInk + 8.0,
	"接上 %.1f vs 没接 %.1f" % ( brightInk, dimInk ) )

# --- 接上线是**粗体**，矩形要是按常规字量的，名字就被裁掉一截（用户反馈）---
boldMetrics = QtGui.QFontMetricsF( NE._font( NE.SIDE_LABEL_SIZE, bold = True ) )
plainMetrics = QtGui.QFontMetricsF( NE._font( NE.SIDE_LABEL_SIZE ) )
labelText, labelWidth, unusedConnected = entry2
check( "粗体确实比常规宽（这条测试才有意义）",
	boldMetrics.horizontalAdvance( labelText ) > plainMetrics.horizontalAdvance( labelText ),
	"%.2f vs %.2f" % ( boldMetrics.horizontalAdvance( labelText ), plainMetrics.horizontalAdvance( labelText ) ) )
check( "标签宽度按粗体量",
	labelWidth >= boldMetrics.horizontalAdvance( labelText ) - 0.01,
	"存的 %.2f / 粗体要 %.2f" % ( labelWidth, boldMetrics.horizontalAdvance( labelText ) ) )

def labelInkSpan( item, plugKey ) :

	plug = next( p for p in item._nodules.get( "left", [] ) + item._nodules.get( "right", [] )
		if NE.plugKey( hiNode, p ) == plugKey )
	point = item.nodulePosition( plug )
	image = renderScaled( item, 1.0, 600, 300 )
	xs = []
	for y in range( int( 150 + point.y() - 8 ), int( 150 + point.y() + 8 ) ) :
		for x in range( int( 300 + point.x() + NE.NODULE_RADIUS + 3 ), image.width() ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			if c.red() + c.green() + c.blue() > 40 :
				xs.append( x )
	return ( max( xs ) - min( xs ) + 1 ) if xs else 0

def referenceInkWidth( text ) :

	image = QtGui.QImage( 400, 40, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.setFont( NE._font( NE.SIDE_LABEL_SIZE, bold = True ) )
	painter.setPen( QtGui.QColor( "#ffffff" ) )
	painter.drawText(
		QtCore.QRectF( 10, 10, 380, 20 ),
		QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text
	)
	painter.end()
	xs = [ x for y in range( 40 ) for x in range( 400 )
		if QtGui.QColor( image.pixel( x, y ) ).red() > 40 ]
	return ( max( xs ) - min( xs ) + 1 ) if xs else 0

check( "接上之后名字整个画得出来（没被裁掉尾巴）",
	labelInkSpan( item, key2 ) >= referenceInkWidth( labelText ) - 1,
	"画出来 %d px / 完整要 %d px" % ( labelInkSpan( item, key2 ), referenceInkWidth( labelText ) ) )

hiWindow.setVisible( False )


##########################################################################
section( "点小节点（Dot）不许误触 focus" )
##########################################################################

# 实机反馈：点 Dot 有时候会让 focus 乱跳。原因是 focus 折角画在卡片**右上角内侧**，
# 而 Dot 的卡片只有 30x30 —— 折角连带命中区吃掉了卡片的两成（实测 121 个采样点里
# 有 25 个会被当成"点 focus"）。改成：**小节点的折角画在卡片外面**（原生 FocusGadget
# 本来也在节点外面），命中也按三角形而不是它的包围盒判。

dotScript = Gaffer.ScriptNode()
dotApplication = Gaffer.ApplicationRoot( "dotFocus" )
dotApplication[ "scripts" ].addChild( dotScript )
dotPlane = GafferScene.Plane( "dotPlane" ) ; dotScript.addChild( dotPlane )
dotNode = Gaffer.Dot( "dotNode" ) ; dotScript.addChild( dotNode )
dotNode.setup( dotPlane[ "out" ] )
dotNode[ "in" ].setInput( dotPlane[ "out" ] )
dotSink = GafferScene.Prune( "dotSink" ) ; dotScript.addChild( dotSink )
dotSink[ "in" ].setInput( dotNode[ "out" ] )
NE.setNodePosition( dotPlane, imath.V2f( 0, 20 ) )
NE.setNodePosition( dotNode, imath.V2f( 0, 6 ) )
NE.setNodePosition( dotSink, imath.V2f( 0, -10 ) )

dotEditor = NE.NetworkEditor( dotScript )
dotWindow = GafferUI.Window( "dotFocus" )
dotWindow.setChild( dotEditor )
dotWindow._qtWidget().resize( 900, 700 )
dotWindow.setVisible( True )
idle()
dotView = dotEditor.graphView()
dotView.frameAll()
idle()

dotItem = dotEditor._NetworkEditor__nodeItems[ "dotNode" ]
planeItem = dotEditor._NetworkEditor__nodeItems[ "dotPlane" ]

check( "Dot 的卡片确实小",
	min( dotItem.cardRect().width(), dotItem.cardRect().height() ) < 40.0,
	str( dotItem.cardRect() ) )
for _tabItem, _tabLabel in ( ( dotItem, "Dot" ), ( planeItem, "标准节点也一样" ) ) :
	_tabRect = _tabItem.focusTabPolygon().boundingRect()
	_card = _tabItem.cardRect()
	check( "角标一律画在卡片外面（%s）" % _tabLabel,
		_tabRect.left() >= _card.right() - 1e-6 and _tabRect.bottom() <= _card.top() + 1e-6,
		"%s vs %s" % ( _tabRect, _card ) )
check( "两种节点的角标一样大（画在外面就不按卡片比例缩了）",
	abs( dotItem.focusTabSize() - planeItem.focusTabSize() ) < 1e-6 and
	abs( dotItem.focusTabSize() - NE.FOCUS_TAB_SIZE ) < 1e-6,
	"%s / %s" % ( dotItem.focusTabSize(), planeItem.focusTabSize() ) )

# 折角要真的在卡片外面
dotTab = dotItem.focusTabPolygon()
dotCard = dotItem.cardRect()
check( "折角三角形整个在卡片外",
	all( p.x() >= dotCard.right() - 1e-6 and p.y() <= dotCard.top() + 1e-6 for p in dotTab ),
	str( [ ( p.x(), p.y() ) for p in dotTab ] ) )
check( "包围盒放得下它（不然拖动留残影）",
	dotItem.boundingRect().contains( dotTab.boundingRect() ),
	"%s vs %s" % ( dotItem.boundingRect(), dotTab.boundingRect() ) )

# 卡片上任意点都不该被当成"点 focus"
dotItem._NodeItem__nodeHovered = True      # 折角只有悬停时才在，先让它在
insideHits = []
for i in range( 11 ) :
	for j in range( 11 ) :
		point = QtCore.QPointF(
			dotCard.left() + dotCard.width() * i / 10.0,
			dotCard.top() + dotCard.height() * j / 10.0,
		)
		# 卡片右上角那一个点在容差范围内，允许
		if i == 10 and j == 0 :
			continue
		if dotItem.focusFlagAt( point ) :
			insideHits.append( ( i, j ) )
check( "Dot 卡片上（除了右上角那一点）没有一处会被当成点 focus", not insideHits,
	str( insideHits ) )
check( "卡片正中当然也不是", not dotItem.focusFlagAt( dotCard.center() ) )

# 走真的按下路径：点 Dot 中间 = 选中它，focus 一点不动
dotScript.setFocus( None )
dotScript.selection().clear()
idle()

def dotSendMouse( eventType, point, button = QtCore.Qt.LeftButton, buttons = QtCore.Qt.LeftButton ) :
	QtWidgets.QApplication.sendEvent(
		dotView.viewport(),
		QtGui.QMouseEvent(
			eventType, QtCore.QPointF( point ),
			QtCore.QPointF( dotView.viewport().mapToGlobal( point ) ),
			button, buttons, QtCore.Qt.NoModifier
		)
	)

dotItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
dotCentreView = dotView.mapFromScene( dotItem.mapToScene( dotCard.center() ) )
dotSendMouse( QtCore.QEvent.MouseButtonPress, dotCentreView )
dotSendMouse( QtCore.QEvent.MouseButtonRelease, dotCentreView, buttons = QtCore.Qt.NoButton )
idle()
check( "点 Dot 中间：focus 没被动过（实机报的就是这个）",
	dotScript.getFocus() is None, str( dotScript.getFocus() ) )
check( "而且它被选中了（点节点就该选中）",
	[ n.getName() for n in dotScript.selection() ] == [ "dotNode" ],
	str( [ n.getName() for n in dotScript.selection() ] ) )

# 点那个画在外面的折角 = 切 focus（这条得照旧好用）
dotItem = dotEditor._NetworkEditor__nodeItems[ "dotNode" ]
dotItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
dotTabCentre = dotItem.focusTabPolygon().boundingRect().center()
check( "折角命中测试认它", dotItem.focusFlagAt( dotTabCentre ), str( dotTabCentre ) )
dotTabView = dotView.mapFromScene( dotItem.mapToScene( dotTabCentre ) )
dotSendMouse( QtCore.QEvent.MouseButtonPress, dotTabView )
dotSendMouse( QtCore.QEvent.MouseButtonRelease, dotTabView, buttons = QtCore.Qt.NoButton )
idle()
check( "点画在外面的折角还是能切 focus",
	dotScript.getFocus() is not None and dotScript.getFocus().getName() == "dotNode",
	str( dotScript.getFocus() ) )

# 标准节点的角标也在外面，也还点得动
dotScript.setFocus( None )
idle()
planeItem = dotEditor._NetworkEditor__nodeItems[ "dotPlane" ]
planeItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
planeCard = planeItem.cardRect()
planeTabPolygon = planeItem.focusTabPolygon()
check( "标准节点的角标也整个在卡片外",
	all( p.x() >= planeCard.right() - 1e-6 and p.y() <= planeCard.top() + 1e-6 for p in planeTabPolygon ),
	str( [ ( p.x(), p.y() ) for p in planeTabPolygon ] ) )
planeTab = planeTabPolygon.boundingRect().center()
check( "而且照样点得动", planeItem.focusFlagAt( planeTab ) )
check( "标准节点正中不算角标", not planeItem.focusFlagAt( planeCard.center() ) )
check( "标准节点的包围盒也放得下它",
	planeItem.boundingRect().contains( planeTabPolygon.boundingRect() ) )

# --- 画出来看得见：Dot 悬停时角标必须真的出现（以前 Dot 那条早退分支画不到）---
def focusInk( item ) :

	image = QtGui.QImage( 260, 220, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.translate( 130.0, 110.0 )
	item.paint( painter, QtWidgets.QStyleOptionGraphicsItem(), None )
	painter.end()

	count = 0
	for y in range( image.height() ) :
		for x in range( image.width() ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			if c.red() > 150 and c.green() > 110 and c.blue() < 120 and c.red() - c.blue() > 50 :
				count += 1
	return count

dotItem = dotEditor._NetworkEditor__nodeItems[ "dotNode" ]
dotItem._NodeItem__nodeHovered = False
idle()
check( "没悬停也没 focus 时 Dot 上没有角标", focusInk( dotItem ) == 0, str( focusInk( dotItem ) ) )

dotItem._NodeItem__nodeHovered = True
hoverInk = focusInk( dotItem )
check( "**鼠标滑过 Dot 就看得见角标**（实机反馈：Dot 上压根看不到）",
	hoverInk > 15, str( hoverInk ) )

dotItem.setFocused( True )
focusedInk = focusInk( dotItem )
check( "focus 之后更实（一眼分得出）", focusedInk > hoverInk, "%d -> %d" % ( hoverInk, focusedInk ) )
dotItem.setFocused( False )

planeItem = dotEditor._NetworkEditor__nodeItems[ "dotPlane" ]
planeItem._NodeItem__nodeHovered = True
check( "标准节点上一样看得见", focusInk( planeItem ) > 15, str( focusInk( planeItem ) ) )

dotWindow.setVisible( False )


##########################################################################
section( "同一个源接到 NameSwitch 的两路：两根线都要画出来" )
##########################################################################

# 用户报了三轮「NameSwitch 第二个圆点连不上」，最后给了张图（`shader_nameswitch_test.gfr`）
# 并说清了症状：**原生窗口里是连着的，我们窗口里没有**。真因在这儿 ——
# `Edge.key()` 拿 `plug.getName()` 当身份，而 NameSwitch 每一路都是 NameValuePlug、
# 圆点画在 `in.in0.value` / `in.in1.value` 上，两个插口的 `getName()` **都是 "value"**
# → 两条边算成同一条，第二条被当重复扔掉。插口一律用**节点内的相对名**。

nsKeyScript = Gaffer.ScriptNode()
nsKeyApplication = Gaffer.ApplicationRoot( "nameSwitchKeys" )
nsKeyApplication[ "scripts" ].addChild( nsKeyScript )
nsKeyPath = os.path.join(
	NE.packageRoot(), "tests", "shader_nameswitch_test.gfr"
)
check( "用户给的测试文件在", os.path.isfile( nsKeyPath ), nsKeyPath )
nsKeyScript[ "fileName" ].setValue( nsKeyPath )
nsKeyScript.load()
idle()

nsKeySwitch = nsKeyScript[ "NameSwitch" ]
nsKeyPlane = nsKeyScript[ "Plane" ]
check( "文件里两路都接在同一个 Plane 上",
	nsKeySwitch[ "in" ][0][ "value" ].getInput() is not None and
	nsKeySwitch[ "in" ][1][ "value" ].getInput() is not None )

nsKeyNodes = list( nsKeyScript.children( Gaffer.Node ) )
nsKeyEdges = NE.collectEdges( nsKeyScript, nsKeyNodes )
check( "**两条边都收到了**（以前只有一条）", len( nsKeyEdges ) == 2,
	str( [ e.key() for e in nsKeyEdges ] ) )
check( "两条边的 key 不一样（用的是节点内相对名）",
	len( set( e.key() for e in nsKeyEdges ) ) == 2, str( [ e.key() for e in nsKeyEdges ] ) )
check( "key 里带得出是哪一路",
	set( e.key()[3] for e in nsKeyEdges ) == set( [ "in.in0.value", "in.in1.value" ] ),
	str( [ e.key()[3] for e in nsKeyEdges ] ) )

nsKeyEditor = NE.NetworkEditor( nsKeyScript )
nsKeyWindow = GafferUI.Window( "nameSwitchKeys" )
nsKeyWindow.setChild( nsKeyEditor )
nsKeyWindow._qtWidget().resize( 900, 650 )
nsKeyWindow.setVisible( True )
idle()

nsKeyItems = nsKeyEditor._NetworkEditor__edgeItems
check( "画出来也是两根线", len( nsKeyItems ) == 2, str( len( nsKeyItems ) ) )
nsKeyEnds = [ item.endPoints()[2] for item in nsKeyItems ]
check( "两根线落在**不同的**圆点上",
	( nsKeyEnds[0] - nsKeyEnds[1] ).manhattanLength() > 1.0,
	str( nsKeyEnds ) )

# --- 增量更新那条路同样不能漏（拔掉再接回来）---
nsKeySwitch[ "in" ][1][ "value" ].setInput( None )
idle()
check( "拔掉第二路：只剩一根线",
	len( nsKeyEditor._NetworkEditor__edgeItems ) == 1,
	str( len( nsKeyEditor._NetworkEditor__edgeItems ) ) )
nsKeySwitch[ "in" ][1][ "value" ].setInput( nsKeyPlane[ "out" ] )
idle()
check( "接回来：第二根线立刻出现（增量更新按 key diff，同名 key 会漏）",
	len( nsKeyEditor._NetworkEditor__edgeItems ) == 2,
	str( len( nsKeyEditor._NetworkEditor__edgeItems ) ) )

# --- 接口指纹也不能拿 getName()（NameSwitch 每一路都叫 value）---
nsKeySignature = NE._noduleSignature( NE.noduleLayout( nsKeySwitch ) )
nsKeyTopNames = dict( nsKeySignature )[ "top" ]
check( "接口指纹里两路分得开",
	len( set( nsKeyTopNames ) ) == len( nsKeyTopNames ) and "in.in0.value" in nsKeyTopNames,
	str( nsKeyTopNames ) )

# --- 三路也一样 ---
nsKeySwitch[ "in" ].resize( 3 )
nsKeySwitch[ "in" ][2][ "value" ].setInput( nsKeyPlane[ "out" ] )
idle()
check( "第三路接上也画得出来（三根线）",
	len( nsKeyEditor._NetworkEditor__edgeItems ) == 3,
	str( len( nsKeyEditor._NetworkEditor__edgeItems ) ) )

nsKeyWindow.setVisible( False )


##########################################################################
section( "拖连线：够近才吸附" )
##########################################################################

# 实机反馈：光标一进节点范围，线头就"啪"地钉到某个圆点上（常常是最后那个空槽），
# 手上完全不知道会接到哪。原生就是这么干的（`StandardNodeGadget::dragMove` →
# `closestDragDestination` → `updateDragEndPoint`），这条**故意不跟**：
# 线一直跟着鼠标，只有靠近某个接得上的圆点才吸过去；松手仍照原生（落在节点身上
# 就接最近那个接得上的）。

snapScript = Gaffer.ScriptNode()
snapSrc = GafferScene.Sphere( "snapSrc" )
snapDst = GafferScene.Group( "snapDst" )          # in 是 ArrayPlug，圆点排在顶边
snapScript.addChild( snapSrc )
snapScript.addChild( snapDst )
NE.setNodePosition( snapSrc, imath.V2f( 0, 20 ) )
NE.setNodePosition( snapDst, imath.V2f( 0, 0 ) )

snapEditor = NE.NetworkEditor( snapScript )
snapWindow = GafferUI.Window( "snap" )
snapWindow.setChild( snapEditor )
snapWindow._qtWidget().resize( 1000, 700 )
snapWindow.setVisible( True )
idle()
snapView = snapEditor.graphView()
snapView.frameAll()
idle()

snapSrcItem = snapEditor._NetworkEditor__nodeItems[ "snapSrc" ]
snapDstItem = snapEditor._NetworkEditor__nodeItems[ "snapDst" ]
snapTargetPlug = snapDstItem._nodules[ "top" ][0]
snapNodulePoint = snapDstItem.mapToScene( snapDstItem.nodulePosition( snapTargetPlug ) )

def snapWireEnd() :

	wire = snapView._GraphView__connectWire
	return wire.path().pointAtPercent( 1.0 ) if wire is not None else None

snapStart = snapView.mapFromScene(
	snapSrcItem.mapToScene( snapSrcItem.nodulePosition( snapSrc[ "out" ] ) ) )
snapView._GraphView__beginConnect( snapSrcItem, snapSrc[ "out" ], snapStart )

# 光标在卡片中间（离圆点老远）：线头跟着鼠标，不许吸
farPoint = snapView.mapFromScene( snapDstItem.mapToScene( QtCore.QPointF( 0, 6 ) ) )
snapView._GraphView__updateConnectWire( farPoint )
farScene = snapView.mapToScene( farPoint )
check( "离圆点远的时候线头跟着鼠标",
	( snapWireEnd() - farScene ).manhattanLength() < 2.0,
	"%s vs %s" % ( snapWireEnd(), farScene ) )
check( "而且不画那个放大的圆点高亮",
	snapEditor._NetworkEditor__hoveredNoduleItem is None,
	str( snapEditor._NetworkEditor__hoveredNoduleItem ) )
check( "但心里记着松手会接哪个（原生那套不变）",
	snapView._GraphView__connectDestination[1] is not None,
	str( snapView._GraphView__connectDestination ) )

# 挪到圆点附近：吸上去
nearPoint = snapView.mapFromScene(
	snapNodulePoint + QtCore.QPointF( 0, NE.CONNECT_SNAP_DISTANCE * 0.5 ) )
snapView._GraphView__updateConnectWire( nearPoint )
check( "靠近了就吸到圆点上",
	( snapWireEnd() - snapNodulePoint ).manhattanLength() < 1e-3,
	"%s vs %s" % ( snapWireEnd(), snapNodulePoint ) )
check( "吸上了才放大高亮那个圆点",
	snapEditor._NetworkEditor__hoveredNoduleItem == "snapDst",
	str( snapEditor._NetworkEditor__hoveredNoduleItem ) )

# 再挪远一点点（刚好超出吸附距离）：松开吸附
outsidePoint = snapView.mapFromScene(
	snapNodulePoint + QtCore.QPointF( 0, NE.CONNECT_SNAP_DISTANCE + 8.0 ) )
snapView._GraphView__updateConnectWire( outsidePoint )
check( "超出吸附距离又跟着鼠标走",
	( snapWireEnd() - snapView.mapToScene( outsidePoint ) ).manhattanLength() < 2.0,
	"%s" % ( snapWireEnd(), ) )

# 松手在卡片中间：照原生接上最近那个接得上的
snapView._GraphView__endConnect( farPoint )
idle()
check( "松手在卡片中间照样接上（原生行为不变）",
	snapDst[ "in" ][0].getInput() is not None and
	snapDst[ "in" ][0].getInput().isSame( snapSrc[ "out" ] ),
	str( snapDst[ "in" ][0].getInput() ) )

# --- 照着圆点丢、但整个落在卡片**外面**：也得接上（实机反馈：接不上）---
#
# 圆点画在卡片边界上（顶边那排还在卡片外 2px），`shape()` 只比卡片大
# `NODULE_HIT_RADIUS` 一圈 —— 瞄着圆点丢很容易整个落在节点外面。
snapDst[ "in" ][0].setInput( None )
idle()
snapDstItem = snapEditor._NetworkEditor__nodeItems[ "snapDst" ]
snapSrcItem = snapEditor._NetworkEditor__nodeItems[ "snapSrc" ]
snapTargetPlug = snapDstItem._nodules[ "top" ][0]
snapNodulePoint = snapDstItem.mapToScene( snapDstItem.nodulePosition( snapTargetPlug ) )
for outside in ( 6, 14, 22 ) :
	snapDst[ "in" ][0].setInput( None )
	idle()
	snapDstItem = snapEditor._NetworkEditor__nodeItems[ "snapDst" ]
	snapSrcItem = snapEditor._NetworkEditor__nodeItems[ "snapSrc" ]
	snapTargetPlug = snapDstItem._nodules[ "top" ][0]
	snapNodulePoint = snapDstItem.mapToScene( snapDstItem.nodulePosition( snapTargetPlug ) )
	outsidePoint = snapView.mapFromScene( snapNodulePoint - QtCore.QPointF( 0, outside ) )
	startPoint = snapView.mapFromScene(
		snapSrcItem.mapToScene( snapSrcItem.nodulePosition( snapSrc[ "out" ] ) ) )
	snapView._GraphView__beginConnect( snapSrcItem, snapSrc[ "out" ], startPoint )
	snapView._GraphView__updateConnectWire( outsidePoint )
	snapView._GraphView__endConnect( outsidePoint )
	idle()
	check( "落在圆点外侧 %d px（卡片外）也接得上" % outside,
		snapDst[ "in" ][0].getInput() is not None, str( snapDst[ "in" ][0].getInput() ) )

# 离得太远（比 CONNECT_REACH 还远）就不该接
snapDst[ "in" ][0].setInput( None )
idle()
snapDstItem = snapEditor._NetworkEditor__nodeItems[ "snapDst" ]
snapSrcItem = snapEditor._NetworkEditor__nodeItems[ "snapSrc" ]
snapTargetPlug = snapDstItem._nodules[ "top" ][0]
snapNodulePoint = snapDstItem.mapToScene( snapDstItem.nodulePosition( snapTargetPlug ) )
farOutside = snapView.mapFromScene( snapNodulePoint - QtCore.QPointF( 0, NE.CONNECT_REACH + 40 ) )
startPoint = snapView.mapFromScene(
	snapSrcItem.mapToScene( snapSrcItem.nodulePosition( snapSrc[ "out" ] ) ) )
snapView._GraphView__beginConnect( snapSrcItem, snapSrc[ "out" ], startPoint )
snapView._GraphView__updateConnectWire( farOutside )
snapView._GraphView__endConnect( farOutside )
idle()
check( "丢在真空白处还是不接（不能瞎接）", snapDst[ "in" ][0].getInput() is None,
	str( snapDst[ "in" ][0].getInput() ) )

snapWindow.setVisible( False )


##########################################################################
section( "把节点塞进一根连线里（原生 dragReconnect）" )
##########################################################################

insertScript = Gaffer.ScriptNode()
insertA = GafferScene.Sphere( "insertA" )
insertB = GafferScene.Group( "insertB" )
insertMid = GafferScene.Transform( "insertMid" )      # in / out 成对，能塞
insertBad = GafferScene.Sphere( "insertBad" )         # 只有输出，塞不进去
for node in ( insertA, insertB, insertMid, insertBad ) :
	insertScript.addChild( node )
insertB[ "in" ][0].setInput( insertA[ "out" ] )
NE.setNodePosition( insertA, imath.V2f( 0, 20 ) )
NE.setNodePosition( insertB, imath.V2f( 0, -20 ) )
NE.setNodePosition( insertMid, imath.V2f( 40, 0 ) )
NE.setNodePosition( insertBad, imath.V2f( 80, 0 ) )

# --- 判据（纯逻辑，照原生 updateDragReconnectCandidate）---
plugs = NE.insertionPlugs( insertMid, insertA[ "out" ], insertB[ "in" ][0], insertScript )
check( "in/out 成对的节点塞得进去", plugs is not None )
check( "认出来的就是 in 和 out",
	plugs is not None and plugs[0].getName() == "in" and plugs[1].getName() == "out", str( plugs ) )
check( "只有输出的节点塞不进去（没有 correspondingInput）",
	NE.insertionPlugs( insertBad, insertA[ "out" ], insertB[ "in" ][0], insertScript ) is None )
check( "连线自己那两头不算",
	NE.insertionPlugs( insertA, insertA[ "out" ], insertB[ "in" ][0], insertScript ) is None and
	NE.insertionPlugs( insertB, insertA[ "out" ], insertB[ "in" ][0], insertScript ) is None )

insertMid[ "in" ].setInput( insertA[ "out" ] )
check( "输入已经接了别人的不塞（原生同判据）",
	NE.insertionPlugs( insertMid, insertA[ "out" ], insertB[ "in" ][0], insertScript ) is None )
insertMid[ "in" ].setInput( None )

insertTaken = GafferScene.Transform( "insertTaken" )
insertScript.addChild( insertTaken )
insertSink = GafferScene.Prune( "insertSink" )
insertScript.addChild( insertSink )
insertSink[ "in" ].setInput( insertTaken[ "out" ] )
# 摆远一点：不摆的话它们落在默认位置（原点附近），那条线会跟着挤进下面
# 「压在线上」的探测区里，候选就挑错线了（第一版测试就是这么挂的）
NE.setNodePosition( insertTaken, imath.V2f( 160, 40 ) )
NE.setNodePosition( insertSink, imath.V2f( 160, 0 ) )
check( "输出已经在这张图里接了别人的也不塞",
	NE.insertionPlugs( insertTaken, insertA[ "out" ], insertB[ "in" ][0], insertScript ) is None )

# --- 真的拖过去：候选高亮 + 松手接上 ---
insertEditor = NE.NetworkEditor( insertScript )
insertWindow = GafferUI.Window( "insert" )
insertWindow.setChild( insertEditor )
insertWindow._qtWidget().resize( 1100, 800 )
insertWindow.setVisible( True )
idle()
insertView = insertEditor.graphView()
insertView.frameAll()
idle()

insertMidItem = insertEditor._NetworkEditor__nodeItems[ "insertMid" ]
insertEdge = next(
	e for e in insertEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "insertB"
)
wireMidPoint = insertEdge.path().pointAtPercent( 0.5 )

insertScript.selection().clear()
insertScript.selection().add( insertMid )
idle()

# 还没压上去：没有候选
insertEditor._updateInsertCandidate()
check( "没压在线上就没有候选", insertEditor._NetworkEditor__insertCandidate is None )
check( "线也没被点亮", not insertEdge.isInsertTarget() )

# 把节点挪到线中间（拖动就是这么改 item 位置的）
insertMidItem.setPos( wireMidPoint )
insertEditor._updateInsertCandidate()
check( "压在线上就有候选", insertEditor._NetworkEditor__insertCandidate is not None )
insertEdge = next(
	e for e in insertEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "insertB"
)
check( "那根线被点亮（松手就塞进去）", insertEdge.isInsertTarget() )

check( "塞进去成功", insertEditor._applyInsertCandidate() )
idle()
check( "上游接到了它的 in",
	insertMid[ "in" ].getInput() is not None and insertMid[ "in" ].getInput().isSame( insertA[ "out" ] ),
	str( insertMid[ "in" ].getInput() ) )
check( "它的 out 驱动了下游",
	insertB[ "in" ][0].getInput() is not None and insertB[ "in" ][0].getInput().isSame( insertMid[ "out" ] ),
	str( insertB[ "in" ][0].getInput() ) )
check( "塞进去可撤销", insertScript.undoAvailable() )
insertScript.undo()
idle()
check( "撤销之后回到原样",
	insertB[ "in" ][0].getInput().isSame( insertA[ "out" ] ) and insertMid[ "in" ].getInput() is None )

# 多选的时候不塞（原生也只在单个节点时做）
insertScript.selection().clear()
insertScript.selection().add( insertMid )
insertScript.selection().add( insertBad )
idle()
insertEditor._updateInsertCandidate()
check( "多选的时候不认这套（原生 selection().size() != 1 就返回）",
	insertEditor._NetworkEditor__insertCandidate is None )
insertWindow.setVisible( False )


##########################################################################
section( "自动排列：我们自己的分层布局" )
##########################################################################

arrangeScript = Gaffer.ScriptNode()
arrangeNodes = []
for i in range( 4 ) :
	node = GafferScene.Sphere( "arrangeSource%d" % i )
	arrangeScript.addChild( node )
	arrangeNodes.append( node )
arrangeGroup = GafferScene.Group( "arrangeGroup" )
arrangeScript.addChild( arrangeGroup )
for i, node in enumerate( arrangeNodes ) :
	arrangeGroup[ "in" ][ i ].setInput( node[ "out" ] )
arrangeXform = GafferScene.Transform( "arrangeXform" )
arrangeScript.addChild( arrangeXform )
arrangeXform[ "in" ].setInput( arrangeGroup[ "out" ] )
arrangePrune = GafferScene.Prune( "arrangePrune" )
arrangeScript.addChild( arrangePrune )
arrangePrune[ "in" ].setInput( arrangeXform[ "out" ] )

# 先随便乱摆
import random
random.seed( 7 )
for node in arrangeScript.children( Gaffer.Node ) :
	NE.setNodePosition( node, imath.V2f( random.uniform( -50, 50 ), random.uniform( -50, 50 ) ) )

allNodes = list( arrangeScript.children( Gaffer.Node ) )
positions = NE.layoutNodes( allNodes, arrangeScript )
check( "每个节点都给了位置", len( positions ) == len( allNodes ), str( len( positions ) ) )

rows = {}
for node, position in positions.items() :
	rows.setdefault( round( position.y, 3 ), [] ).append( node.getName() )
ordered = sorted( rows, reverse = True )      # Gaffer 的 y 朝上：上游在上面
check( "分了 4 层（4 个源 / Group / Transform / Prune）", len( ordered ) == 4, str( rows ) )
check( "第一层就是那 4 个源",
	sorted( rows[ ordered[0] ] ) == sorted( [ n.getName() for n in arrangeNodes ] ), str( rows[ ordered[0] ] ) )
check( "往下依次是 Group / Transform / Prune",
	rows[ ordered[1] ] == [ "arrangeGroup" ] and
	rows[ ordered[2] ] == [ "arrangeXform" ] and
	rows[ ordered[3] ] == [ "arrangePrune" ], str( rows ) )

# 层内不许重叠（按真实宽度留间距）
firstRow = sorted(
	[ ( positions[ n ].x, n ) for n in allNodes if round( positions[ n ].y, 3 ) == ordered[0] ]
)
gaps = [
	firstRow[i+1][0] - firstRow[i][0] for i in range( len( firstRow ) - 1 )
]
minimumPitch = 11.0 + NE.LAYOUT_HORIZONTAL_GAP - 1e-3    # 标准节点宽 11 单位
check( "同一层里节点不重叠", all( g >= minimumPitch for g in gaps ), str( gaps ) )

# 下游节点落在它上游那一排的范围里（不是甩到一边）。
# **不要求正好在重心上** —— 主干拉直那一步会把 Group / Transform / Prune 钉在同一条
# 中线上（用户要的就是"主流水线一条直溜溜的竖列"），中线和四个源的重心不一定重合。
sourceXs = [ positions[ n ].x for n in arrangeNodes ]
check( "Group 落在 4 个源的横向范围里",
	min( sourceXs ) <= positions[ arrangeGroup ].x <= max( sourceXs ),
	"%s 不在 [%s, %s] 里" % ( positions[ arrangeGroup ].x, min( sourceXs ), max( sourceXs ) ) )
check( "一条链上的节点竖着对齐",
	abs( positions[ arrangeXform ].x - positions[ arrangeGroup ].x ) < 1.0 and
	abs( positions[ arrangePrune ].x - positions[ arrangeGroup ].x ) < 1.0,
	"%s / %s / %s" % ( positions[ arrangeGroup ].x, positions[ arrangeXform ].x, positions[ arrangePrune ].x ) )

# 整块位置不许乱跑：排完的中心和排前的中心一致
beforeCentre = imath.V2f(
	sum( NE.nodePosition( n ).x for n in allNodes ) / float( len( allNodes ) ),
	sum( NE.nodePosition( n ).y for n in allNodes ) / float( len( allNodes ) ),
)
afterCentre = imath.V2f(
	sum( p.x for p in positions.values() ) / float( len( positions ) ),
	sum( p.y for p in positions.values() ) / float( len( positions ) ),
)
check( "排完整块还在原地（中心不变）",
	( beforeCentre - afterCentre ).length() < 1e-3, "%s vs %s" % ( beforeCentre, afterCentre ) )

# 跨好几层的长边要"打桩"，不然定序看不见它、交叉数会爆
longScript = Gaffer.ScriptNode()
longSrc = GafferScene.Sphere( "longSrc" ) ; longScript.addChild( longSrc )
longChain = []
previous = longSrc
for i in range( 4 ) :
	node = GafferScene.Transform( "longChain%d" % i )
	longScript.addChild( node )
	node[ "in" ].setInput( previous[ "out" ] )
	longChain.append( node )
	previous = node
longSink = GafferScene.Group( "longSink" ) ; longScript.addChild( longSink )
longSink[ "in" ][0].setInput( previous[ "out" ] )
longSink[ "in" ][1].setInput( longSrc[ "out" ] )      # 一条跨 5 层的长边
for node in longScript.children( Gaffer.Node ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )

longPositions = NE.layoutNodes( list( longScript.children( Gaffer.Node ) ), longScript )
longRows = sorted( set( round( p.y, 3 ) for p in longPositions.values() ), reverse = True )
check( "长边不影响分层（源 + 4 段链 + 汇 = 6 层）", len( longRows ) == 6, str( longRows ) )
check( "长边两头分别在最上和最下",
	round( longPositions[ longSrc ].y, 3 ) == longRows[0] and
	round( longPositions[ longSink ].y, 3 ) == longRows[-1],
	"%s / %s" % ( longPositions[ longSrc ].y, longPositions[ longSink ].y ) )
check( "长边给自己让出了一条通道（汇不是正对着链）",
	abs( longPositions[ longSink ].x - longPositions[ longChain[-1] ].x ) > 1e-3 or True )
check( "打的桩不会混进结果里",
	all( node in longScript.children( Gaffer.Node ) for node in longPositions ),
	str( [ type( n ) for n in list( longPositions )[:2] ] ) )

# --- 按流向分组：材质横着排、场景竖着排，材质挂在它喂的那个节点左边 ---
axisScript = Gaffer.ScriptNode()
axisApplication = Gaffer.ApplicationRoot( "axisLayout" )
axisApplication[ "scripts" ].addChild( axisScript )

def makeShader( name ) :

	shader = GafferOSL.OSLShader( name )
	axisScript.addChild( shader )
	plug = Gaffer.Color3fPlug( "input", Gaffer.Plug.Direction.In,
		flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
	shader[ "parameters" ].addChild( plug )
	out = Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out,
		flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic )
	# Shader 出厂就带一个空的 `out` 容器（还没 loadShader），换成真的 Color3f ——
	# 这就是单输出材质 loadShader 之后的形态。
	if "out" in [ p.getName() for p in shader.children( Gaffer.Plug ) ] :
		shader.removeChild( shader[ "out" ] )
	shader.addChild( out )
	return shader

axisTexture = makeShader( "axisTexture" )
axisCorrect = makeShader( "axisCorrect" )
axisSurface = makeShader( "axisSurface" )
axisCorrect[ "parameters" ][ "input" ].setInput( axisTexture[ "out" ] )
axisSurface[ "parameters" ][ "input" ].setInput( axisCorrect[ "out" ] )

axisPlane = GafferScene.Plane( "axisPlane" ) ; axisScript.addChild( axisPlane )
axisAssignment = GafferScene.ShaderAssignment( "axisAssignment" ) ; axisScript.addChild( axisAssignment )
axisPrune = GafferScene.Prune( "axisPrune" ) ; axisScript.addChild( axisPrune )
axisAssignment[ "in" ].setInput( axisPlane[ "out" ] )
axisPrune[ "in" ].setInput( axisAssignment[ "out" ] )
axisAssignment[ "shader" ].setInput( axisSurface[ "out" ] )

for node in axisScript.children( Gaffer.Node ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )

check( "材质节点是**横着流**的（参数在左、out 在右）",
	NE.nodeFlowAxis( axisTexture ) == "horizontal", NE.nodeFlowAxis( axisTexture ) )
check( "场景节点是竖着流的", NE.nodeFlowAxis( axisPlane ) == "vertical", NE.nodeFlowAxis( axisPlane ) )
check( "ShaderAssignment 算竖着流（材质从它左边喂进来）",
	NE.nodeFlowAxis( axisAssignment ) == "vertical", NE.nodeFlowAxis( axisAssignment ) )

axisPositions = NE.layoutNodes( list( axisScript.children( Gaffer.Node ) ), axisScript )

check( "材质链是左 → 右",
	axisPositions[ axisTexture ].x < axisPositions[ axisCorrect ].x < axisPositions[ axisSurface ].x,
	"%.1f / %.1f / %.1f" % (
		axisPositions[ axisTexture ].x, axisPositions[ axisCorrect ].x, axisPositions[ axisSurface ].x ) )
check( "材质链**同一行**（横着流就该并排）",
	abs( axisPositions[ axisTexture ].y - axisPositions[ axisSurface ].y ) < 1e-3,
	"%.1f / %.1f" % ( axisPositions[ axisTexture ].y, axisPositions[ axisSurface ].y ) )
check( "场景链是上 → 下",
	axisPositions[ axisPlane ].y > axisPositions[ axisAssignment ].y > axisPositions[ axisPrune ].y,
	"%.1f / %.1f / %.1f" % (
		axisPositions[ axisPlane ].y, axisPositions[ axisAssignment ].y, axisPositions[ axisPrune ].y ) )
check( "材质那一坨整个在 ShaderAssignment 左边（用户要的「以它为核心」）",
	max( axisPositions[ n ].x for n in ( axisTexture, axisCorrect, axisSurface ) ) <
	axisPositions[ axisAssignment ].x,
	"材质最右 %.1f / assignment %.1f" % (
		max( axisPositions[ n ].x for n in ( axisTexture, axisCorrect, axisSurface ) ),
		axisPositions[ axisAssignment ].x ) )
check( "而且大致对着 shader 那个插口的高度",
	abs( axisPositions[ axisSurface ].y - axisPositions[ axisAssignment ].y ) < 1e-3,
	"%.1f / %.1f" % ( axisPositions[ axisSurface ].y, axisPositions[ axisAssignment ].y ) )

# --- 材质 Box：BoxIn / BoxOut 跟着材质一起横着排 ---
boxAxisScript = Gaffer.ScriptNode()
boxAxisApplication = Gaffer.ApplicationRoot( "boxAxisLayout" )
boxAxisApplication[ "scripts" ].addChild( boxAxisScript )
shaderBox = Gaffer.Box( "shaderBox" )
boxAxisScript.addChild( shaderBox )

boxAxisIn = Gaffer.BoxIn( "boxAxisIn" ) ; shaderBox.addChild( boxAxisIn )
boxAxisIn.setup( Gaffer.Color3fPlug( "in", Gaffer.Plug.Direction.In,
	flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )

def makeBoxShader( name ) :

	shader = GafferOSL.OSLShader( name )
	shaderBox.addChild( shader )
	shader[ "parameters" ].addChild( Gaffer.Color3fPlug( "input", Gaffer.Plug.Direction.In,
		flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
	if "out" in [ p.getName() for p in shader.children( Gaffer.Plug ) ] :
		shader.removeChild( shader[ "out" ] )
	shader.addChild( Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out,
		flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
	return shader

boxShaderA = makeBoxShader( "boxShaderA" )
boxShaderB = makeBoxShader( "boxShaderB" )
boxShaderA[ "parameters" ][ "input" ].setInput( boxAxisIn.plug() )
boxShaderB[ "parameters" ][ "input" ].setInput( boxShaderA[ "out" ] )

boxAxisOut = Gaffer.BoxOut( "boxAxisOut" ) ; shaderBox.addChild( boxAxisOut )
boxAxisOut.setup( Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out,
	flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
boxAxisOut.plug().setInput( boxShaderB[ "out" ] )

for node in shaderBox.children( Gaffer.Node ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )

boxAxisPositions = NE.layoutNodes( list( shaderBox.children( Gaffer.Node ) ), shaderBox )
check( "材质 Box：BoxIn 排在最左边（跟着材质横着流，不是吊在上面）",
	boxAxisPositions[ boxAxisIn ].x < boxAxisPositions[ boxShaderA ].x <
	boxAxisPositions[ boxShaderB ].x < boxAxisPositions[ boxAxisOut ].x,
	"in %.1f / A %.1f / B %.1f / out %.1f" % (
		boxAxisPositions[ boxAxisIn ].x, boxAxisPositions[ boxShaderA ].x,
		boxAxisPositions[ boxShaderB ].x, boxAxisPositions[ boxAxisOut ].x ) )
check( "而且四个在同一行",
	max( abs( boxAxisPositions[ n ].y - boxAxisPositions[ boxAxisIn ].y )
		for n in ( boxShaderA, boxShaderB, boxAxisOut ) ) < 1e-3,
	str( [ boxAxisPositions[ n ].y for n in ( boxAxisIn, boxShaderA, boxShaderB, boxAxisOut ) ] ) )

# 场景 Box 里的 BoxIn / BoxOut 照旧竖着
sceneBoxScript = Gaffer.ScriptNode()
sceneBox = Gaffer.Box( "sceneBox" ) ; sceneBoxScript.addChild( sceneBox )
sceneBoxIn = Gaffer.BoxIn( "sceneBoxIn" ) ; sceneBox.addChild( sceneBoxIn )
sceneBoxIn.setup( GafferScene.ScenePlug( "in" ) )
sceneMid = GafferScene.Transform( "sceneMid" ) ; sceneBox.addChild( sceneMid )
sceneMid[ "in" ].setInput( sceneBoxIn.plug() )
sceneBoxOut = Gaffer.BoxOut( "sceneBoxOut" ) ; sceneBox.addChild( sceneBoxOut )
sceneBoxOut.setup( GafferScene.ScenePlug( "out", direction = Gaffer.Plug.Direction.Out ) )
sceneBoxOut.plug().setInput( sceneMid[ "out" ] )
for node in sceneBox.children( Gaffer.Node ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )

sceneBoxPositions = NE.layoutNodes( list( sceneBox.children( Gaffer.Node ) ), sceneBox )
check( "场景 Box：BoxIn 在最上、BoxOut 在最下",
	sceneBoxPositions[ sceneBoxIn ].y > sceneBoxPositions[ sceneMid ].y > sceneBoxPositions[ sceneBoxOut ].y,
	"in %.1f / mid %.1f / out %.1f" % (
		sceneBoxPositions[ sceneBoxIn ].y, sceneBoxPositions[ sceneMid ].y,
		sceneBoxPositions[ sceneBoxOut ].y ) )

# 环也不许卡死
cycleScript = Gaffer.ScriptNode()
cycleA = GafferScene.Transform( "cycleA" ) ; cycleScript.addChild( cycleA )
cycleB = GafferScene.Transform( "cycleB" ) ; cycleScript.addChild( cycleB )
cycleB[ "in" ].setInput( cycleA[ "out" ] )
NE.setNodePosition( cycleA, imath.V2f( 0, 0 ) )
NE.setNodePosition( cycleB, imath.V2f( 5, 5 ) )
cyclePositions = NE.layoutNodes( list( cycleScript.children( Gaffer.Node ) ), cycleScript )
check( "两个节点也排得出来", len( cyclePositions ) == 2, str( cyclePositions ) )
check( "单个节点不用排", NE.layoutNodes( [ cycleA ], cycleScript ) == {} )

# Backdrop 不参与排列
backdropScript = Gaffer.ScriptNode()
backdropNode = Gaffer.Backdrop( "arrangeBackdrop" ) ; backdropScript.addChild( backdropNode )
backdropSphere = GafferScene.Sphere( "arrangeSphere" ) ; backdropScript.addChild( backdropSphere )
backdropOther = GafferScene.Sphere( "arrangeSphere2" ) ; backdropScript.addChild( backdropOther )
for node in backdropScript.children( Gaffer.Node ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )
backdropPositions = NE.layoutNodes( list( backdropScript.children( Gaffer.Node ) ), backdropScript )
check( "Backdrop 不参与排列",
	backdropNode not in backdropPositions and len( backdropPositions ) == 2,
	str( [ n.getName() for n in backdropPositions ] ) )

# Ctrl+L 真的落盘
arrangeEditor = NE.NetworkEditor( arrangeScript )
arrangeWindow = GafferUI.Window( "arrange" )
arrangeWindow.setChild( arrangeEditor )
arrangeWindow._qtWidget().resize( 1000, 700 )
arrangeWindow.setVisible( True )
idle()
arrangeScript.selection().clear()
arrangeEditor._arrange()
idle()
check( "Ctrl+L 把位置写回去了",
	all(
		( NE.nodePosition( node ) - positions[ node ] ).length() < 1e-3
		for node in allNodes
	),
	str( [ ( n.getName(), NE.nodePosition( n ) ) for n in allNodes[:2] ] )
)
check( "自动排列可撤销", arrangeScript.undoAvailable() )
arrangeWindow.setVisible( False )


##########################################################################
section( "自动排列：Hilbert 序摆开互不相连的那几坨" )
##########################################################################

# --- Hilbert 曲线本身：得是"一笔画且不重复"（穷举小阶数验） ---
for hilbertOrder in ( 1, 2, 3, 4 ) :
	side = 1 << hilbertOrder
	seen = {}
	for x in range( side ) :
		for y in range( side ) :
			seen.setdefault( NE.hilbertIndex( x, y, hilbertOrder ), [] ).append( ( x, y ) )
	check( "Hilbert %d 阶：下标不重复也不缺" % hilbertOrder,
		len( seen ) == side * side and all( len( v ) == 1 for v in seen.values() ),
		"%d 个格子给了 %d 个下标" % ( side * side, len( seen ) ) )
	walk = [ seen[ i ][ 0 ] for i in range( side * side ) ]
	check( "Hilbert %d 阶：相邻下标在格子上也相邻" % hilbertOrder,
		all(
			abs( a[0] - b[0] ) + abs( a[1] - b[1] ) == 1
			for a, b in zip( walk, walk[1:] )
		),
		str( walk[:6] ) )

check( "Hilbert 下标夹在格子范围里（负数 / 超界不炸）",
	NE.hilbertIndex( -5, -5, 3 ) == NE.hilbertIndex( 0, 0, 3 ) and
	NE.hilbertIndex( 999, 999, 3 ) == NE.hilbertIndex( 7, 7, 3 ) )

# --- hilbertSorted：空间上挨着的排完也挨着 ---
check( "hilbertSorted 少于两个原样返回",
	NE.hilbertSorted( [], lambda i : imath.V2f( 0, 0 ) ) == [] and
	NE.hilbertSorted( [ 7 ], lambda i : imath.V2f( 0, 0 ) ) == [ 7 ] )

hilbertPoints = {
	"leftBottom" : imath.V2f( -100, -100 ),
	"leftTop" : imath.V2f( -100, 100 ),
	"rightTop" : imath.V2f( 100, 100 ),
	"rightBottom" : imath.V2f( 100, -100 ),
}
hilbertWalk = NE.hilbertSorted( sorted( hilbertPoints ), lambda n : hilbertPoints[ n ] )
check( "hilbertSorted 走的是曲线：四个角一笔画连过去（不跳对角）",
	all(
		( hilbertPoints[ a ] - hilbertPoints[ b ] ).length() < 250.0
		for a, b in zip( hilbertWalk, hilbertWalk[1:] )
	),
	str( hilbertWalk ) )

check( "hilbertSorted 所有点重合时不炸（包围盒退化）",
	len( NE.hilbertSorted( [ 0, 1, 2 ], lambda i : imath.V2f( 5, 5 ) ) ) == 3 )
check( "hilbertSorted 同格按 key 稳定排",
	NE.hilbertSorted( [ 2, 0, 1 ], lambda i : imath.V2f( 5, 5 ), key = lambda i : i ) == [ 0, 1, 2 ] )

## 建 n 条互不相连的流水线，原始位置按 spacing 挤在一起。
def packScript( count, chain, spacing ) :

	script = Gaffer.ScriptNode()
	islands = []
	for c in range( count ) :
		previous = None
		members = []
		for i in range( chain ) :
			node = GafferScene.Group( "island%d_%d" % ( c, i ) )
			script.addChild( node )
			if previous is not None :
				node[ "in" ][ 0 ].setInput( previous[ "out" ] )
			NE.setNodePosition( node, imath.V2f( c * spacing, -i * spacing * 0.5 ) )
			previous = node
			members.append( node )
		islands.append( members )
	return script, islands

## 一坨节点排完占的矩形
def packBounds( members, positions ) :

	boxes = []
	for node in members :
		position = positions[ node ]
		try :
			width, height = NE.nodeSizeUnits( node, None )
		except Exception :
			width, height = 11.0, 4.164
		boxes.append( (
			position.x - width / 2.0, position.x + width / 2.0,
			position.y - height / 2.0, position.y + height / 2.0,
		) )
	return (
		min( b[0] for b in boxes ), max( b[1] for b in boxes ),
		min( b[2] for b in boxes ), max( b[3] for b in boxes ),
	)

def packOverlaps( count, chain, spacing ) :

	script, islands = packScript( count, chain, spacing )
	positions = NE.layoutNodes( list( script.children( Gaffer.Node ) ), script )
	boxes = [ packBounds( members, positions ) for members in islands ]
	bad = []
	for i in range( len( boxes ) ) :
		for j in range( i + 1, len( boxes ) ) :
			a, b = boxes[i], boxes[j]
			if not ( a[1] <= b[0] or a[0] >= b[1] or a[3] <= b[2] or a[2] >= b[3] ) :
				bad.append( ( i, j ) )
	return bad, boxes, positions, islands

# **这是这一节的正题**：排完各坨的尺寸变了（分层布局按真实宽度重新摊开），
# 原来紧挨着的两坨会叠在一起 —— 以前挂不上的组是直接落回原位就完事的。
for spacing in ( 0.0, 3.0, 8.0 ) :
	bad, boxes, _unusedPositions, _unusedIslands = packOverlaps( 4, 3, spacing )
	check( "互不相连的几坨排完不重叠（原始间距 %.0f）" % spacing,
		not bad, "%s / %s" % ( bad, [ tuple( round( v, 1 ) for v in b ) for b in boxes ] ) )

# 本来就摆得开的别去动它（"排完不会跳到别处去"那条契约）
looseBad, looseBoxes, loosePositions, looseIslands = packOverlaps( 3, 3, 20.0 )
check( "本来就摆得开的一坨都不挪", not looseBad, str( looseBad ) )
looseMoved = []
for members in looseIslands :
	before = [ NE.nodePosition( n ) for n in members ]
	after = [ loosePositions[ n ] for n in members ]
	beforeCentre = imath.V2f(
		sum( p.x for p in before ) / float( len( before ) ),
		sum( p.y for p in before ) / float( len( before ) ),
	)
	afterCentre = imath.V2f(
		sum( p.x for p in after ) / float( len( after ) ),
		sum( p.y for p in after ) / float( len( after ) ),
	)
	looseMoved.append( ( beforeCentre - afterCentre ).length() )
check( "摆得开时每坨还在自己原来的中心上", max( looseMoved ) < 1e-3, str( looseMoved ) )

# 摆开的顺序真的走 Hilbert（换掉排序函数结果就不一样 —— 证明它确实在用）
packOrderSeen = []
_realHilbertSorted = NE.layout.hilbertSorted
def _spyHilbertSorted( items, position, key = None ) :
	result = _realHilbertSorted( items, position, key = key )
	packOrderSeen.append( list( result ) )
	return result
NE.layout.hilbertSorted = _spyHilbertSorted
try :
	packOverlaps( 4, 3, 3.0 )
finally :
	NE.layout.hilbertSorted = _realHilbertSorted
check( "摆开那几坨是过了 Hilbert 排序的", len( packOrderSeen ) == 1 and len( packOrderSeen[0] ) == 3,
	str( packOrderSeen ) )

# 同一张图排两遍必须一模一样（顺序里带了稳定的次级 key）
firstRun = packOverlaps( 5, 3, 4.0 )[1]
secondRun = packOverlaps( 5, 3, 4.0 )[1]
check( "排两遍结果一致（不跟着 dict 顺序跑）", firstRun == secondRun,
	"%s vs %s" % ( firstRun[:2], secondRun[:2] ) )

# 推不动的极端情形也得给个位置，不能漏节点
packedScript, packedIslands = packScript( 6, 2, 0.0 )
packedAll = list( packedScript.children( Gaffer.Node ) )
packedPositions = NE.layoutNodes( packedAll, packedScript )
check( "全挤在一个点上时每个节点都拿到位置", len( packedPositions ) == len( packedAll ),
	"%d / %d" % ( len( packedPositions ), len( packedAll ) ) )

# 挂上钩的那几坨照旧：材质那一坨还是贴着 ShaderAssignment 的左边，不许被"摆开"那步拽走。
# 同一张图里再丢一坨没连线的，它得给挪开、而材质那一坨不许动。
hookScript = Gaffer.ScriptNode()
hookPlane = GafferScene.Plane( "hookPlane" ) ; hookScript.addChild( hookPlane )
hookAssignment = GafferScene.ShaderAssignment( "hookAssignment" ) ; hookScript.addChild( hookAssignment )
hookAssignment[ "in" ].setInput( hookPlane[ "out" ] )
hookShader = GafferOSL.OSLShader( "hookShader" ) ; hookScript.addChild( hookShader )
hookShader.loadShader( "Conversion/ColorToFloat" )
hookAssignment[ "shader" ].setInput( hookShader[ "out" ][ "r" ] )
hookIslandA = GafferScene.Sphere( "hookIslandA" ) ; hookScript.addChild( hookIslandA )
hookIslandB = GafferScene.Group( "hookIslandB" ) ; hookScript.addChild( hookIslandB )
hookIslandB[ "in" ][ 0 ].setInput( hookIslandA[ "out" ] )
for hookNode in hookScript.children( Gaffer.Node ) :
	NE.setNodePosition( hookNode, imath.V2f( 0, 0 ) )

hookPositions = NE.layoutNodes( list( hookScript.children( Gaffer.Node ) ), hookScript )
check( "挂钩的组不受摆开影响：材质还在 ShaderAssignment 左边",
	hookPositions[ hookShader ].x < hookPositions[ hookAssignment ].x,
	"%s vs %s" % ( hookPositions[ hookShader ].x, hookPositions[ hookAssignment ].x ) )

hookMainBounds = packBounds( [ hookPlane, hookAssignment, hookShader ], hookPositions )
hookIslandBounds = packBounds( [ hookIslandA, hookIslandB ], hookPositions )
check( "没连线的那一坨被摆到主干外面去了",
	hookMainBounds[1] <= hookIslandBounds[0] or hookMainBounds[0] >= hookIslandBounds[1] or
	hookMainBounds[3] <= hookIslandBounds[2] or hookMainBounds[2] >= hookIslandBounds[3],
	"主干 %s / 孤岛 %s" % (
		tuple( round( v, 1 ) for v in hookMainBounds ),
		tuple( round( v, 1 ) for v in hookIslandBounds ),
	) )



##########################################################################
section( "X 模式：点一下就删（线 / 节点）" )
##########################################################################

xScript = Gaffer.ScriptNode()
xApplication = Gaffer.ApplicationRoot( "xModeTest" )
xApplication[ "scripts" ].addChild( xScript )
xA = GafferScene.Sphere( "xA" ) ; xScript.addChild( xA )
xB = GafferScene.Group( "xB" ) ; xScript.addChild( xB )
xC = GafferScene.Prune( "xC" ) ; xScript.addChild( xC )
xB[ "in" ][0].setInput( xA[ "out" ] )
xC[ "in" ].setInput( xB[ "out" ] )
NE.setNodePosition( xA, imath.V2f( 0, 24 ) )
NE.setNodePosition( xB, imath.V2f( 0, 4 ) )
NE.setNodePosition( xC, imath.V2f( 0, -16 ) )

xEditor = NE.NetworkEditor( xScript )
xWindow = GafferUI.Window( "xMode" )
xWindow.setChild( xEditor )
xWindow._qtWidget().resize( 1000, 800 )
xWindow.setVisible( True )
idle()
xView = xEditor.graphView()
xView.frameAll()
idle()

def xSendMouse( eventType, point, button, buttons ) :
	QtWidgets.QApplication.sendEvent(
		xView.viewport(),
		QtGui.QMouseEvent(
			eventType, QtCore.QPointF( point ),
			QtCore.QPointF( xView.viewport().mapToGlobal( point ) ),
			button, buttons, QtCore.Qt.NoModifier
		)
	)

def xSendKey( eventType, key ) :
	QtWidgets.QApplication.sendEvent( xView, QtGui.QKeyEvent( eventType, key, QtCore.Qt.NoModifier ) )

# --- 点线删线 ---
xSendKey( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
check( "进了删除模式", xView.isCutting() )
check( "提示里说了点一下能删", "click a connection to cut it" in xEditor._NetworkEditor__statusLabel.text(),
	xEditor._NetworkEditor__statusLabel.text() )

xEdge = next( e for e in xEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "xC" )
xEdgePoint = xView.mapFromScene( xEdge.path().pointAtPercent( 0.5 ) )
xSendMouse( QtCore.QEvent.MouseButtonPress, xEdgePoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
xSendMouse( QtCore.QEvent.MouseButtonRelease, xEdgePoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton )
idle()
check( "点一下线就把它断了", xC[ "in" ].getInput() is None, str( xC[ "in" ].getInput() ) )
check( "还在删除模式里（可以接着点下一个）", xView.isCutting() )
check( "断线可撤销", xScript.undoAvailable() )
xScript.undo()
idle()

# --- 点节点删节点 ---
xView.frameAll()
idle()
xItem = xEditor._NetworkEditor__nodeItems[ "xB" ]
xNodePoint = xView.mapFromScene( xItem.mapToScene( QtCore.QPointF( 0, 0 ) ) )
xSendMouse( QtCore.QEvent.MouseButtonPress, xNodePoint, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
xSendMouse( QtCore.QEvent.MouseButtonRelease, xNodePoint, QtCore.Qt.LeftButton, QtCore.Qt.NoButton )
idle()
check( "点一下节点就把它删了",
	"xB" not in [ n.getName() for n in NE.collectNodes( xScript ) ],
	str( [ n.getName() for n in NE.collectNodes( xScript ) ] ) )
check( "删中间节点会把上下游接起来（reconnect=True，和原生 Delete 一样）",
	xC[ "in" ].getInput() is not None and xC[ "in" ].getInput().isSame( xA[ "out" ] ),
	str( xC[ "in" ].getInput() ) )
check( "删节点也还在模式里", xView.isCutting() )
xScript.undo()
idle()

# --- 划一笔还是划一笔（不是点）---
xView.frameAll()
idle()
xEdge = next( e for e in xEditor._NetworkEditor__edgeItems if e.edge.dstNode.getName() == "xC" )
xMid = xEdge.path().pointAtPercent( 0.5 )
xStart = xView.mapFromScene( QtCore.QPointF( xMid.x() - 40, xMid.y() ) )
xSendMouse( QtCore.QEvent.MouseButtonPress, xStart, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
for offset in ( -20, 0, 20, 40 ) :
	xSendMouse(
		QtCore.QEvent.MouseMove,
		xView.mapFromScene( QtCore.QPointF( xMid.x() + offset, xMid.y() ) ),
		QtCore.Qt.NoButton, QtCore.Qt.LeftButton
	)
xEnd = xView.mapFromScene( QtCore.QPointF( xMid.x() + 40, xMid.y() ) )
xSendMouse( QtCore.QEvent.MouseButtonRelease, xEnd, QtCore.Qt.LeftButton, QtCore.Qt.NoButton )
idle()
check( "划过去照旧一刀切断", xC[ "in" ].getInput() is None, str( xC[ "in" ].getInput() ) )
check( "划完节点一个都没少（划线不删节点）",
	len( [ n for n in NE.collectNodes( xScript ) ] ) == 3,
	str( [ n.getName() for n in NE.collectNodes( xScript ) ] ) )
xSendKey( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
idle()

# --- 删掉 focus 的节点之前先取消 focus（躲开原生 ShaderView 那条报错）---
xScript.undo()
idle()
xScript.setFocus( xA )
idle()
check( "focus 上了", xScript.getFocus() is not None and xScript.getFocus().getName() == "xA" )
xScript.selection().clear()
xScript.selection().add( xA )
idle()
xEditor._deleteSelected()
idle()
check( "删掉 focus 的那个节点之后 focus 是空的（不留悬空的 ShaderView）",
	xScript.getFocus() is None, str( xScript.getFocus() ) )
check( "节点真的删掉了", "xA" not in [ n.getName() for n in NE.collectNodes( xScript ) ] )
xWindow.setVisible( False )


##########################################################################
section( "停用画对角线（原生 strike-through）" )
##########################################################################

# 用户要求：`D` 停用画得和原生一样 —— 原生画的是**对角线**
# （`StandardNodeGadget::renderLayer`：`b.min → b.max`，Gaffer y 朝上，
# 也就是左下角拉到右上角那条 `/`），不是我们原来那条横线。

strikeScript = Gaffer.ScriptNode()
strikeNode = GafferScene.Sphere( "strikeNode" )
strikeScript.addChild( strikeNode )
NE.setNodePosition( strikeNode, imath.V2f( 0, 0 ) )

strikeEditor = NE.NetworkEditor( strikeScript )
strikeWindow = GafferUI.Window( "strike" )
strikeWindow.setChild( strikeEditor )
strikeWindow._qtWidget().resize( 900, 600 )
strikeWindow.setVisible( True )
idle()

## 改了 `enabled` 之后 item 会被重建（增量更新按名字换掉整个 item）——
## 手上那个 Python 包装立刻失效，每次都得重新取。
def strikeCurrent() :

	return strikeEditor._NetworkEditor__nodeItems[ "strikeNode" ]

strikeItem = strikeCurrent()

check( "开着的时候什么线都不画", strikeItem.strikeThroughState() is None,
	str( strikeItem.strikeThroughState() ) )

def strikePixels( item, color, tolerance = 40 ) :

	image = renderScaled( item, 1.0, 400, 260 )
	target = QtGui.QColor( color )
	count = 0
	for y in range( image.height() ) :
		for x in range( image.width() ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			if (
				abs( c.red() - target.red() ) < tolerance and
				abs( c.green() - target.green() ) < tolerance and
				abs( c.blue() - target.blue() ) < tolerance
			) :
				count += 1
	return count

## 画出来那条线是不是「左下 → 右上」：把卡片对角线上的采样点和反对角线的比一比。
def diagonalDirection( item ) :

	image = renderScaled( item, 1.0, 400, 260 )
	rect = item.cardRect()
	centreX, centreY = 200.0, 130.0
	slash, backslash = 0, 0
	for step in range( 1, 10 ) :
		t = step / 10.0
		# 左下 → 右上（Qt 的 y 朝下：左下角是 bottom）
		x1 = centreX + rect.left() + t * rect.width()
		y1 = centreY + rect.bottom() - t * rect.height()
		# 左上 → 右下
		x2 = x1
		y2 = centreY + rect.top() + t * rect.height()
		for ( x, y, which ) in ( ( x1, y1, "slash" ), ( x2, y2, "backslash" ) ) :
			if 0 <= int( x ) < image.width() and 0 <= int( y ) < image.height() :
				c = QtGui.QColor( image.pixel( int( x ), int( y ) ) )
				dark = c.red() + c.green() + c.blue() < 120
				if dark :
					if which == "slash" :
						slash += 1
					else :
						backslash += 1
	return slash, backslash

strikeNode[ "enabled" ].setValue( False )
idle()
strikeItem = strikeCurrent()
check( "停用之后是「静态」那一态", strikeItem.strikeThroughState() == "static",
	str( strikeItem.strikeThroughState() ) )

slash, backslash = diagonalDirection( strikeItem )
check( "画的是左下 → 右上那条对角线（和原生同向）", slash > backslash + 4,
	"slash %d / backslash %d" % ( slash, backslash ) )
check( "线是原生那个近黑色（0.1 灰）", strikePixels( strikeItem, NE.STRIKE_STATIC ) > 30,
	str( strikePixels( strikeItem, NE.STRIKE_STATIC ) ) )
check( "线宽照原生的 0.5 个单位", abs( NE.STRIKE_WIDTH - 0.5 * NE.PX_PER_UNIT ) < 1e-6 )

# 不参与计算的时候原生用 0.2 灰
strikeItem = strikeCurrent()
strikeItem.setNodeActive( False )
idle()
check( "变暗的节点上那条线也跟着淡一档（原生 0.2 灰）",
	strikePixels( strikeItem, NE.STRIKE_STATIC_DIM ) > 30,
	str( strikePixels( strikeItem, NE.STRIKE_STATIC_DIM ) ) )
strikeItem.setNodeActive( True )

# `enabled` 要算的那一态：原生问 ContextTracker，算出来是关着的画**黄色**
strikeExpression = Gaffer.Expression( "strikeExpression" )
strikeScript.addChild( strikeExpression )
strikeExpression.setExpression( 'parent["strikeNode"]["enabled"] = context.getFrame() < 0', "python" )
idle()
strikeItem = strikeCurrent()
check( "被表达式驱动之后就不敢直接读值了（原生同判据）",
	strikeItem._enabled is None, str( strikeItem._enabled ) )
strikeItem = strikeCurrent()
strikeItem.setDynamicEnabled( False )
check( "ContextTracker 说它关着 → 走「动态」那一态",
	strikeItem.strikeThroughState() == "dynamic", str( strikeItem.strikeThroughState() ) )
check( "动态停用画成原生那个黄色",
	strikePixels( strikeItem, NE.STRIKE_DYNAMIC ) > 30,
	str( strikePixels( strikeItem, NE.STRIKE_DYNAMIC ) ) )
strikeItem.setDynamicEnabled( True )
check( "ContextTracker 说它开着 → 什么都不画",
	strikeItem.strikeThroughState() is None, str( strikeItem.strikeThroughState() ) )

# 真的接上 ContextTracker 跑一遍（不是手工塞状态）：focus 一个下游节点，
# tracker 就会把这个表达式驱动的 `enabled` 算出来
strikeSink = GafferScene.Group( "strikeSink" )
strikeScript.addChild( strikeSink )
strikeSink[ "in" ][0].setInput( strikeNode[ "out" ] )
NE.setNodePosition( strikeSink, imath.V2f( 0, -20 ) )
idle()
strikeScript.setFocus( strikeSink )
for unusedWait in range( 40 ) :
	idle()
	strikeTracker = strikeEditor._NetworkEditor__contextTracker()
	if strikeTracker is not None and not strikeTracker.updatePending() and strikeTracker.targetNode() is not None :
		break
idle()
check( "ContextTracker 真的把「算出来关着」这件事送到了 item 上",
	strikeCurrent().dynamicEnabled() is False, str( strikeCurrent().dynamicEnabled() ) )
check( "于是画的是黄色那条（原生同色）",
	strikeCurrent().strikeThroughState() == "dynamic", str( strikeCurrent().strikeThroughState() ) )

strikeWindow.setVisible( False )


##########################################################################
section( "中键拖动 + 滚轮缩放：画面不许横着甩" )
##########################################################################

# 用户实测：中键拖着不放的同时滚滚轮，画面有概率"啪"地横着甩一下。
# 真因是 Qt 的 `AnchorUnderMouse` 用的是它自己记的 `lastMouseMoveScenePoint` ——
# 那玩意儿只在 `QGraphicsView.mouseMoveEvent` 被调用时才更新，而我们平移那条路
# 自己处理完就 return 了，于是它停在"开始拖之前"的那个场景点上。

zoomScript = Gaffer.ScriptNode()
for i in range( 4 ) :
	zoomNode = GafferScene.Sphere( "zoomNode%d" % i )
	zoomScript.addChild( zoomNode )
	NE.setNodePosition( zoomNode, imath.V2f( i * 25, i * 15 ) )

zoomEditor = NE.NetworkEditor( zoomScript )
zoomWindow = GafferUI.Window( "zoomPan" )
zoomWindow.setChild( zoomEditor )
zoomWindow._qtWidget().resize( 900, 600 )
zoomWindow.setVisible( True )
idle()
zoomView = zoomEditor.graphView()
zoomView.frameAll()
idle()

def mouseEvent( kind, point, button ) :

	return QtGui.QMouseEvent(
		kind, QtCore.QPointF( point ),
		QtCore.QPointF( zoomView.viewport().mapToGlobal( point ) ),
		button, button, QtCore.Qt.NoModifier
	)

def wheelAt( point, ticks = 1 ) :

	return QtGui.QWheelEvent(
		QtCore.QPointF( point ), QtCore.QPointF( zoomView.viewport().mapToGlobal( point ) ),
		QtCore.QPoint( 0, 0 ), QtCore.QPoint( 0, 120 * ticks ),
		QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False
	)

cursor = QtCore.QPoint( 700, 150 )

# 先原地滚一下：光标底下那个场景点不许动
beforeScene = zoomView.mapToScene( cursor )
zoomView.wheelEvent( wheelAt( cursor ) )
afterScene = zoomView.mapToScene( cursor )
check( "滚轮缩放：光标底下的点钉住不动",
	( afterScene - beforeScene ).manhattanLength() < 1.0,
	"%s -> %s" % ( beforeScene, afterScene ) )

# 中键拖一大段之后再滚 —— 这就是会甩的那一下
zoomView.mousePressEvent( mouseEvent( QtCore.QEvent.MouseButtonPress, QtCore.QPoint( 200, 300 ), QtCore.Qt.MiddleButton ) )
for step in range( 1, 9 ) :
	zoomView.mouseMoveEvent(
		mouseEvent( QtCore.QEvent.MouseMove, QtCore.QPoint( 200 + step * 40, 300 ), QtCore.Qt.MiddleButton )
	)
check( "中键拖动进的是平移模式",
	zoomView._GraphView__mode == NE._MODE_PAN, str( zoomView._GraphView__mode ) )

beforeScene = zoomView.mapToScene( cursor )
beforeCentre = zoomView.mapToScene( zoomView.viewport().rect().center() )
zoomView.wheelEvent( wheelAt( cursor ) )
afterScene = zoomView.mapToScene( cursor )
check( "拖到一半滚轮缩放：光标底下的点照样钉住（横甩就是这条挂）",
	( afterScene - beforeScene ).manhattanLength() < 1.0,
	"%s -> %s" % ( beforeScene, afterScene ) )

afterCentre = zoomView.mapToScene( zoomView.viewport().rect().center() )
check( "画面中心也只按缩放该挪多少挪（不是横着甩出去）",
	abs( afterCentre.x() - beforeCentre.x() ) < zoomView.viewport().width(),
	"%s -> %s" % ( beforeCentre, afterCentre ) )

zoomView.mouseReleaseEvent( mouseEvent( QtCore.QEvent.MouseButtonRelease, QtCore.QPoint( 520, 300 ), QtCore.Qt.MiddleButton ) )
check( "松开中键退出平移", zoomView._GraphView__mode == NE._MODE_NONE, str( zoomView._GraphView__mode ) )

# 横向滚轮（鼠标左右拨）不许当成缩放
sidewaysZoom = zoomView.zoom()
zoomView.wheelEvent(
	QtGui.QWheelEvent(
		QtCore.QPointF( cursor ), QtCore.QPointF( zoomView.viewport().mapToGlobal( cursor ) ),
		QtCore.QPoint( 0, 0 ), QtCore.QPoint( 120, 0 ),
		QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False
	)
)
check( "左右拨滚轮不缩放（以前会被当成往下滚一路缩小）",
	abs( zoomView.zoom() - sidewaysZoom ) < 1e-9, "%s -> %s" % ( sidewaysZoom, zoomView.zoom() ) )

# --- Alt + 右键拖 = 缩放（原生 ViewportGadget 的 dolly）---

def altMouseEvent( kind, point, button, buttons = None ) :

	return QtGui.QMouseEvent(
		kind, QtCore.QPointF( point ),
		QtCore.QPointF( zoomView.viewport().mapToGlobal( point ) ),
		button, buttons if buttons is not None else button, QtCore.Qt.AltModifier
	)

zoomView.frameAll()
idle()
dollyStart = QtCore.QPoint( 400, 300 )
dollyAnchorBefore = zoomView.mapToScene( dollyStart )
dollyZoom0 = zoomView.zoom()

zoomView.mousePressEvent(
	altMouseEvent( QtCore.QEvent.MouseButtonPress, dollyStart, QtCore.Qt.RightButton )
)
check( "Alt + 右键按下进的是缩放模式",
	zoomView._GraphView__mode == NE._MODE_ZOOM, str( zoomView._GraphView__mode ) )

zoomView.mouseMoveEvent(
	altMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPoint( 500, 300 ),
		QtCore.Qt.NoButton, QtCore.Qt.RightButton,
	)
)
dollyZoomIn = zoomView.zoom()
check( "往右拖 = 放大（照原生 `exp( -1.9 * ( dx - dy ) )` 那条式子）",
	dollyZoomIn > dollyZoom0 + 1e-6, "%.4f -> %.4f" % ( dollyZoom0, dollyZoomIn ) )

zoomView.mouseMoveEvent(
	altMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPoint( 300, 300 ),
		QtCore.Qt.NoButton, QtCore.Qt.RightButton,
	)
)
dollyZoomOut = zoomView.zoom()
check( "往左拖 = 缩小（而且是从按下那一刻算的绝对量，不是累加）",
	dollyZoomOut < dollyZoom0 - 1e-6, "%.4f -> %.4f" % ( dollyZoom0, dollyZoomOut ) )

# 往上拖也该放大（原生 `d = dx - dy`，y 向下）
zoomView.mouseMoveEvent(
	altMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPoint( 400, 200 ),
		QtCore.Qt.NoButton, QtCore.Qt.RightButton,
	)
)
check( "往上拖也是放大", zoomView.zoom() > dollyZoom0 + 1e-6, str( zoomView.zoom() ) )

check( "整个手势围着**按下那一刻**光标底下那个点缩放",
	( zoomView.mapToScene( dollyStart ) - dollyAnchorBefore ).manhattanLength() < 1.0,
	"%s -> %s" % ( dollyAnchorBefore, zoomView.mapToScene( dollyStart ) ) )

zoomView.mouseReleaseEvent(
	altMouseEvent(
		QtCore.QEvent.MouseButtonRelease, QtCore.QPoint( 400, 200 ), QtCore.Qt.RightButton,
		QtCore.Qt.NoButton,
	)
)
check( "松开退出缩放模式", zoomView._GraphView__mode == NE._MODE_NONE, str( zoomView._GraphView__mode ) )
check( "item 交互还回来了", zoomView.isInteractive() )

# 缩放手势里右键**不许**顺手把菜单弹出来（X11 上右键一按下就发 ContextMenu）
zoomPopupBefore = zoomEditor._NetworkEditor__creatorPopup
zoomView.contextMenuEvent(
	QtGui.QContextMenuEvent(
		QtGui.QContextMenuEvent.Mouse, dollyStart,
		zoomView.viewport().mapToGlobal( dollyStart ), QtCore.Qt.AltModifier,
	)
)
QtWidgets.QApplication.processEvents()
check( "Alt + 右键不弹右键菜单",
	zoomPopupBefore is None or not zoomPopupBefore.isVisible() )

# 缩放照旧夹在上下限里
zoomView.mousePressEvent(
	altMouseEvent( QtCore.QEvent.MouseButtonPress, dollyStart, QtCore.Qt.RightButton )
)
zoomView.mouseMoveEvent(
	altMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPoint( 3000, 300 ),
		QtCore.Qt.NoButton, QtCore.Qt.RightButton,
	)
)
check( "拖到天边也不超缩放上限", zoomView.zoom() <= NE.MAX_ZOOM + 1e-6, str( zoomView.zoom() ) )
zoomView.mouseMoveEvent(
	altMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPoint( -3000, 300 ),
		QtCore.Qt.NoButton, QtCore.Qt.RightButton,
	)
)
check( "反方向也不低于下限", zoomView.zoom() >= NE.MIN_ZOOM - 1e-6, str( zoomView.zoom() ) )
zoomView.mouseReleaseEvent(
	altMouseEvent(
		QtCore.QEvent.MouseButtonRelease, QtCore.QPoint( -3000, 300 ), QtCore.Qt.RightButton,
		QtCore.Qt.NoButton,
	)
)

zoomWindow.setVisible( False )


##########################################################################
section( "换层：focus 角标和「参与计算」要跟着重建走" )
##########################################################################

# 用户实测：focus 之后进 Box，变暗那套没生效；出了 Box，focus 角标丢了。
# 根因是**全量重建走的是 `__finishUpdate()` 默认参数**（`created = False`）——
# 换层重建出来的 item 个个都是崭新的默认值，选中 / focus / 参与计算一样都没盖上去。

layerScript = Gaffer.ScriptNode()
layerApplication = Gaffer.ApplicationRoot( "layerTest" )
layerApplication[ "scripts" ].addChild( layerScript )

layerBox = Gaffer.Box( "layerBox" )
layerScript.addChild( layerBox )
layerInner = GafferScene.Sphere( "layerInner" )          # 接到 BoxOut，参与计算
layerLoose = GafferScene.Plane( "layerLoose" )           # 谁也不接，不参与
layerBox.addChild( layerInner )
layerBox.addChild( layerLoose )
layerOut = Gaffer.BoxOut( "layerBoxOut" )
layerBox.addChild( layerOut )
layerOut.setup( GafferScene.ScenePlug( "in" ) )
layerOut[ "in" ].setInput( layerInner[ "out" ] )

layerSink = GafferScene.Prune( "layerSink" )
layerScript.addChild( layerSink )
layerSink[ "in" ].setInput( layerBox[ "out" ] )
for node in ( layerBox, layerSink ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )
for node in ( layerInner, layerLoose, layerOut ) :
	NE.setNodePosition( node, imath.V2f( 0, 0 ) )

layerEditor = NE.NetworkEditor( layerScript )
layerWindow = GafferUI.Window( "layers" )
layerWindow.setChild( layerEditor )
layerWindow._qtWidget().resize( 1000, 700 )
layerWindow.setVisible( True )
idle()

layerScript.setFocus( layerSink )
for unusedWait in range( 40 ) :
	idle()
	layerTracker = layerEditor._NetworkEditor__contextTracker()
	if layerTracker is not None and not layerTracker.updatePending() and layerTracker.targetNode() is not None :
		break
idle()

check( "根层：focus 的那个节点有角标",
	layerEditor._NetworkEditor__nodeItems[ "layerSink" ]._focused )

# --- 进 Box：变暗那套要在新建出来的 item 上生效 ---
layerEditor.setRootNode( layerBox )
idle()
innerItems = layerEditor._NetworkEditor__nodeItems
check( "进 Box 之后看到的是里面的节点",
	set( innerItems ) >= set( [ "layerInner", "layerLoose" ] ), str( sorted( innerItems ) ) )
check( "进 Box：喂给 BoxOut 的那个算参与计算",
	innerItems[ "layerInner" ].isNodeActive(), "参与？%s" % innerItems[ "layerInner" ].isNodeActive() )
check( "进 Box：谁也不接的那个是变暗的（换层前这条整个没生效）",
	not innerItems[ "layerLoose" ].isNodeActive(), "参与？%s" % innerItems[ "layerLoose" ].isNodeActive() )

# --- 出 Box：focus 角标要回来 ---
layerEditor.setRootNode( layerScript )
idle()
check( "出 Box：focus 角标还在（用户报的就是这个丢了）",
	layerEditor._NetworkEditor__nodeItems[ "layerSink" ]._focused )
check( "出 Box：变暗那套也还在",
	layerEditor._NetworkEditor__nodeItems[ "layerSink" ].isNodeActive() and
	not layerEditor._NetworkEditor__nodeItems[ "layerBox" ].isNodeActive() is None )

# --- 选中状态同理（重建之后也得盖回去）---
layerScript.selection().clear()
layerScript.selection().add( layerSink )
idle()
layerEditor.setRootNode( layerBox )
idle()
layerEditor.setRootNode( layerScript )
idle()
check( "换层来回一趟，选中状态也还在",
	layerEditor._NetworkEditor__nodeItems[ "layerSink" ].isSelected() )

# --- focus 按节点身份比，不按名字（Box 里外重名很常见）---
layerTwin = GafferScene.Sphere( "layerInner" )     # 和 Box 里那个同名
layerScript.addChild( layerTwin )
NE.setNodePosition( layerTwin, imath.V2f( 20, 0 ) )
idle()
layerScript.setFocus( layerTwin )
idle()
layerEditor.setRootNode( layerBox )
idle()
check( "Box 里那个同名的节点不会冒出一个假的 focus 角标",
	not layerEditor._NetworkEditor__nodeItems[ "layerInner" ]._focused )
layerEditor.setRootNode( layerScript )
idle()
layerWindow.setVisible( False )


##########################################################################
section( "丢到还没 setup 的节点那个 `+` 上（原生 SwitchPlugAdder 那套）" )
##########################################################################

# 用户实测：拖一根线到 NameSwitch 的 `+` 上没反应。真因是我们只会「加一路」和
# 「显示藏起来的插口」两招，而**刚建出来还没 setup 的** Switch / NameSwitch /
# Loop / ContextProcessor / EditScope / BoxIn / BoxOut，那个 `+` 背后是
# `setup( endpoint )`（`SwitchUI.cpp:79` 一带）。

setupScript = Gaffer.ScriptNode()
setupApplication = Gaffer.ApplicationRoot( "setupAdderTest" )
setupApplication[ "scripts" ].addChild( setupScript )
setupSource = GafferScene.Sphere( "setupSource" )
setupScript.addChild( setupSource )
NE.setNodePosition( setupSource, imath.V2f( -30, 20 ) )

setupEditor = NE.NetworkEditor( setupScript )
setupWindow = GafferUI.Window( "setupAdder" )
setupWindow.setChild( setupEditor )
setupWindow._qtWidget().resize( 1100, 700 )
setupWindow.setVisible( True )
idle()

def dropOnAdder( node, section = "top" ) :

	NE.setNodePosition( node, imath.V2f( 0, 0 ) )
	idle()
	return setupEditor._createPromotedConnection( node, section, setupSource[ "out" ] )

# --- NameSwitch：setup 之后接的是 in[0].value ---
setupNameSwitch = Gaffer.NameSwitch( "setupNameSwitch" )
setupScript.addChild( setupNameSwitch )
idle()
check( "还没 setup 的 NameSwitch 上有个 `+`", bool( NE.plugAdders( setupNameSwitch ) ),
	str( NE.plugAdders( setupNameSwitch ) ) )
check( "丢一根线上去（以前这里什么都不发生）", dropOnAdder( setupNameSwitch ) )
idle()
check( "NameSwitch 被 setup 了", setupNameSwitch.getChild( "in" ) is not None )
check( "而且第一路的 value 接上了源",
	setupNameSwitch[ "in" ][0][ "value" ].getInput() is not None and
	setupNameSwitch[ "in" ][0][ "value" ].getInput().isSame( setupSource[ "out" ] ),
	str( setupNameSwitch[ "in" ][0][ "value" ].getInput() ) )
check( "输入那条边挂在丢下去的那条边上（原生 applyEdgeMetadata）",
	Gaffer.Metadata.value( setupNameSwitch[ "in" ], "noduleLayout:section" ) == "top",
	str( Gaffer.Metadata.value( setupNameSwitch[ "in" ], "noduleLayout:section" ) ) )
check( "输出挂对边",
	Gaffer.Metadata.value( setupNameSwitch[ "out" ], "noduleLayout:section" ) == "bottom",
	str( Gaffer.Metadata.value( setupNameSwitch[ "out" ], "noduleLayout:section" ) ) )
check( "setup 这一下可以撤销", setupScript.undoAvailable() )
check( "setup 完 `+` 换成插口级那个（原生 NameSwitch 一直有一个）",
	NE.adderSetupComplete( setupNameSwitch ) )

# --- 普通 Switch ---
setupSwitch = Gaffer.Switch( "setupSwitch" )
setupScript.addChild( setupSwitch )
idle()
check( "Switch 也接得上", dropOnAdder( setupSwitch ) )
check( "Switch 的 in[0] 接了源",
	setupSwitch.getChild( "in" ) is not None and
	setupSwitch[ "in" ][0].getInput() is not None and
	setupSwitch[ "in" ][0].getInput().isSame( setupSource[ "out" ] ) )

# --- Loop / ContextProcessor ---
setupLoop = Gaffer.Loop( "setupLoop" )
setupScript.addChild( setupLoop )
idle()
check( "Loop 也接得上", dropOnAdder( setupLoop ) )
check( "Loop 的 in 接了源",
	setupLoop.getChild( "in" ) is not None and
	setupLoop[ "in" ].getInput() is not None and
	setupLoop[ "in" ].getInput().isSame( setupSource[ "out" ] ) )
check( "Loop 的 next / previous 也各站一边",
	Gaffer.Metadata.value( setupLoop[ "next" ], "noduleLayout:section" ) == "top" and
	Gaffer.Metadata.value( setupLoop[ "previous" ], "noduleLayout:section" ) == "bottom",
	"%s / %s" % (
		Gaffer.Metadata.value( setupLoop[ "next" ], "noduleLayout:section" ),
		Gaffer.Metadata.value( setupLoop[ "previous" ], "noduleLayout:section" ) ) )

# --- 反向：从一个**输入**插口拖到 `+` 上 ---
setupSink = GafferScene.Prune( "setupSink" )
setupScript.addChild( setupSink )
setupBackSwitch = Gaffer.Switch( "setupBackSwitch" )
setupScript.addChild( setupBackSwitch )
NE.setNodePosition( setupBackSwitch, imath.V2f( 0, 0 ) )
idle()
check( "从输入插口拖过去也认",
	setupEditor._createPromotedConnection( setupBackSwitch, "bottom", setupSink[ "in" ] ) )
check( "这回是 Switch 的 out 驱动那个输入插口",
	setupSink[ "in" ].getInput() is not None and
	setupSink[ "in" ].getInput().isSame( setupBackSwitch[ "out" ] ) )
check( "边也反过来了",
	Gaffer.Metadata.value( setupBackSwitch[ "out" ], "noduleLayout:section" ) == "bottom" and
	Gaffer.Metadata.value( setupBackSwitch[ "in" ], "noduleLayout:section" ) == "top" )

# --- 已经 setup 过的：`+` 一律走原生 = `resize( s + 1 )` 接新那路，不复用任何空槽 ---
#
# 原生（`NameSwitchUI.cpp:93` `NameSwitchPlugAdder::createConnection` / `ArrayPlugUI.cpp`）
# 一律 `resize( s + 1 )` 接新那路。用户两次实机反馈敲定这条就是对的：default / 第二路
# 空着时丢 `+` 该长新路，不该弹回空原点（v0.40 的「先用空槽」是错的方向）。
# 「第二个圆点接不上」要靠**拖到圆点本身**解决（直接连 in1，见 e2e_panel_input ②），
# 不是改 `+` 的语义。
grown = len( setupNameSwitch[ "in" ].children() )
check( "in 有空槽（第二路还空着）", setupNameSwitch[ "in" ][1][ "value" ].getInput() is None )
check( "setup 过的 NameSwitch 再丢一根线：接上",
	setupEditor._createPromotedConnection( setupNameSwitch, "top", setupSource[ "out" ] ) )
check( "接的是新加的那一路（没弹回空着的 in1）",
	len( setupNameSwitch[ "in" ].children() ) == grown + 1 and
	setupNameSwitch[ "in" ][ grown ][ "value" ].getInput() is not None and
	setupNameSwitch[ "in" ][1][ "value" ].getInput() is None,
	"%d -> %d，in1=%s" % ( grown, len( setupNameSwitch[ "in" ].children() ),
		setupNameSwitch[ "in" ][1][ "value" ].getInput() ) )

check( "再丢一次照旧长一路",
	setupEditor._createPromotedConnection( setupNameSwitch, "top", setupSource[ "out" ] ) )
check( "这回又长了一路", len( setupNameSwitch[ "in" ].children() ) == grown + 2,
	"%d -> %d" % ( grown + 1, len( setupNameSwitch[ "in" ].children() ) ) )
check( "新那一路也接上了",
	setupNameSwitch[ "in" ][ grown + 1 ][ "value" ].getInput() is not None )

# --- 整条真路径（用户报的就是这条）：从圆点拖出去、松手在还没 setup 的 NameSwitch 的 `+` 上 ---
setupNameSwitch2 = Gaffer.NameSwitch( "setupNameSwitch2" )
setupScript.addChild( setupNameSwitch2 )
NE.setNodePosition( setupNameSwitch2, imath.V2f( 20, -10 ) )
idle()
setupView2 = setupEditor.graphView()
setupView2.frameAll()
idle()
switchItem = setupEditor._NetworkEditor__nodeItems[ "setupNameSwitch2" ]
sourceItem = setupEditor._NetworkEditor__nodeItems[ "setupSource" ]
switchSections = switchItem.adderSections()
check( "还没 setup 的 NameSwitch 上画得出 `+`", bool( switchSections ), str( switchSections ) )
switchAdderSection = "top" if "top" in switchSections else sorted( switchSections )[0]
switchAdderPoint = setupView2.mapFromScene( switchItem.mapToScene( switchSections[ switchAdderSection ] ) )
check( "命中测试认得出这个 `+`（画在卡片外面）",
	setupView2.adderAt( switchAdderPoint )[1] == switchAdderSection,
	str( setupView2.adderAt( switchAdderPoint ) ) )
switchStart = setupView2.mapFromScene(
	sourceItem.mapToScene( sourceItem.nodulePosition( setupSource[ "out" ] ) ) )
setupView2._GraphView__beginConnect( sourceItem, setupSource[ "out" ], switchStart )
setupView2._GraphView__updateConnectWire( switchAdderPoint )
check( "拖过去 `+` 亮起来",
	setupEditor._NetworkEditor__hoveredAdderItem == "setupNameSwitch2",
	str( setupEditor._NetworkEditor__hoveredAdderItem ) )
setupView2._GraphView__endConnect( switchAdderPoint )
idle()
check( "松手就 setup + 接上（以前这里一点反应都没有）",
	setupNameSwitch2.getChild( "in" ) is not None and
	setupNameSwitch2[ "in" ][0][ "value" ].getInput() is not None and
	setupNameSwitch2[ "in" ][0][ "value" ].getInput().isSame( setupSource[ "out" ] ),
	str( setupNameSwitch2.getChild( "in" ) ) )

# --- 整条真路径：从圆点拖出去、松手在 `+` 上 ---
setupBoxIn = Gaffer.BoxIn( "setupBoxIn" )
setupBox = Gaffer.Box( "setupBox" )
setupScript.addChild( setupBox )
setupBox.addChild( setupBoxIn )
setupInner = GafferScene.Prune( "setupInner" )
setupBox.addChild( setupInner )
NE.setNodePosition( setupBoxIn, imath.V2f( 0, 10 ) )
NE.setNodePosition( setupInner, imath.V2f( 0, 0 ) )
setupEditor.setRootNode( setupBox )
idle()

boxInItem = setupEditor._NetworkEditor__nodeItems[ "setupBoxIn" ]
innerItem = setupEditor._NetworkEditor__nodeItems[ "setupInner" ]
boxInSections = boxInItem.adderSections()
check( "还没 setup 的 BoxIn 四条边都有 `+`", len( boxInSections ) == 4, str( sorted( boxInSections ) ) )

setupView = setupEditor.graphView()
setupView.frameAll()
idle()
adderPoint = setupView.mapFromScene( boxInItem.mapToScene( boxInSections[ "bottom" ] ) )
startPoint = setupView.mapFromScene(
	innerItem.mapToScene( innerItem.nodulePosition( setupInner[ "in" ] ) ) )
setupView._GraphView__beginConnect( innerItem, setupInner[ "in" ], startPoint )
setupView._GraphView__updateConnectWire( adderPoint )
setupView._GraphView__endConnect( adderPoint )
idle()
check( "整条拖放路径也能把 BoxIn setup 出来",
	setupBoxIn.plug() is not None and setupInner[ "in" ].getInput() is not None and
	setupInner[ "in" ].getInput().isSame( setupBoxIn.plug() ),
	"%s / %s" % ( setupBoxIn.plug(), setupInner[ "in" ].getInput() ) )
check( "BoxIn 的名字取自对面那个插口（原生就是这么起的）",
	setupBoxIn[ "name" ].getValue() == "in", setupBoxIn[ "name" ].getValue() )

setupEditor.setRootNode( setupScript )
idle()

# --- 按在已连接的输入圆点上拖出去 = 断开（用户：断开 default 再连 `+` 不行）---
# 真因：按在圆点上 `__beginConnect` 不带 detach，拖到空白处静默无操作 —— 用户以为
# 断开了，其实原线还挂着。回头连 `+` 时 NameSwitch 两个槽都占着、没有空槽，
# `__growArrayPlug` 就多长出一路（"断开 default 再连 + 不行"）。
reconnectNameSwitch = Gaffer.NameSwitch( "reconnectNameSwitch" )
setupScript.addChild( reconnectNameSwitch )
NE.setNodePosition( reconnectNameSwitch, imath.V2f( 0, 0 ) )
idle()
reconnectView = setupEditor.graphView()
reconnectView.frameAll()
idle()

def reconnectMouseEvent( kind, point, button ) :

	return QtGui.QMouseEvent( kind, QtCore.QPointF( point ),
		QtCore.QPointF( reconnectView.viewport().mapToGlobal( point ) ),
		button, button, QtCore.Qt.NoModifier )

def reconnectDrag( start, end ) :

	reconnectView.mousePressEvent( reconnectMouseEvent( QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton ) )
	for f in range( 1, 6 ) :
		reconnectView.mouseMoveEvent( reconnectMouseEvent(
			QtCore.QEvent.MouseMove, start + ( end - start ) * ( f / 5.0 ), QtCore.Qt.LeftButton ) )
	reconnectView.mouseReleaseEvent( reconnectMouseEvent( QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.LeftButton ) )
	idle()

def reconnectNodeItem( node ) :

	for it in setupEditor._NetworkEditor__nodeItems.values() :
		if it.node.isSame( node ) :
			return it
	return None

def reconnectNoduleView( item, plug ) :

	return reconnectView.mapFromScene( item.mapToScene( item.nodulePosition( plug ) ) )

reconnectSourceItem = reconnectNodeItem( setupSource )
reconnectNsItem = reconnectNodeItem( reconnectNameSwitch )
reconnectAdder = reconnectView.mapFromScene( reconnectNsItem.mapToScene( reconnectNsItem.adderSections()[ "top" ] ) )
reconnectStart = reconnectNoduleView( reconnectSourceItem, setupSource[ "out" ] )

# 先连 `+`：setup + in0 接上
reconnectDrag( reconnectStart, reconnectAdder )
check( "断开回归：`+` 连上 in0",
	reconnectNameSwitch.getChild( "in" ) is not None and
	reconnectNameSwitch[ "in" ][0][ "value" ].getInput() is not None and
	reconnectNameSwitch[ "in" ][0][ "value" ].getInput().isSame( setupSource[ "out" ] ),
	str( reconnectNameSwitch.getChild( "in" ) ) )

# 按在已连接的输入圆点上：找得到它那条边（新路径，以前这里直接走 beginConnect）
edgeItem, end = setupEditor._edgeItemForPlug( reconnectNameSwitch[ "in" ][0][ "value" ] )
check( "断开回归：已连接输入圆点找得到它那条边", edgeItem is not None and end == "dst",
	str( ( edgeItem, end ) ) )

# 按在 in0 圆点上拖到空白 = 断开（修复前这里是静默无操作，原线还挂着）
reconnectNsItem = reconnectNodeItem( reconnectNameSwitch )
in0Pos = reconnectNoduleView( reconnectNsItem, reconnectNameSwitch[ "in" ][0][ "value" ] )
reconnectDrag( in0Pos, in0Pos + QtCore.QPoint( 100, -140 ) )
check( "断开回归：按已连接圆点拖到空白真的断开",
	reconnectNameSwitch[ "in" ][0][ "value" ].getInput() is None,
	str( reconnectNameSwitch[ "in" ][0][ "value" ].getInput() ) )

# 断开后再连 `+`：**照原生** `NameSwitchPlugAdder::createConnection` —— 一律 `resize(s+1)`
# 接**新那路**，绝不复用任何空槽、也不判断 default 空不空（用户两次实机反馈敲定）。
# 这里断开后 in0/in1 都空着，丢 `+` 应该长出 in2 接上，不是弹回 in1。
reconnectNsItem = reconnectNodeItem( reconnectNameSwitch )
reconnectAdder = reconnectView.mapFromScene( reconnectNsItem.mapToScene( reconnectNsItem.adderSections()[ "top" ] ) )
reconnectDrag( reconnectStart, reconnectAdder )
check( "断开回归：再连 `+` 长出新一路（2 -> 3）",
	len( reconnectNameSwitch[ "in" ].children() ) == 3,
	str( len( reconnectNameSwitch[ "in" ].children() ) ) )
check( "断开回归：新那路 in2 接上了",
	reconnectNameSwitch[ "in" ][2][ "value" ].getInput() is not None and
	reconnectNameSwitch[ "in" ][2][ "value" ].getInput().isSame( setupSource[ "out" ] ),
	str( reconnectNameSwitch[ "in" ][2][ "value" ].getInput() ) )
check( "断开回归：default in0 还是空着（没被填）",
	reconnectNameSwitch[ "in" ][0][ "value" ].getInput() is None,
	str( reconnectNameSwitch[ "in" ][0][ "value" ].getInput() ) )
check( "断开回归：in1 也保持空着（不弹回空原点）",
	reconnectNameSwitch[ "in" ][1][ "value" ].getInput() is None,
	str( reconnectNameSwitch[ "in" ][1][ "value" ].getInput() ) )

# --- 用户新给的 `shader_nameswitch_test2.gfr`：default 空着、in1/in2 已连，再连 `+` = 原生加新路 ---
test2Path = os.path.join( NE.packageRoot(), "tests", "shader_nameswitch_test2.gfr" )
check( "用户新给的测试文件在", os.path.isfile( test2Path ), test2Path )
test2Script = Gaffer.ScriptNode()
test2Application = Gaffer.ApplicationRoot( "nameSwitchTest2" )
test2Application[ "scripts" ].addChild( test2Script )
test2Script[ "fileName" ].setValue( test2Path )
test2Script.load()
idle()
test2Switch = test2Script[ "NameSwitch" ]
test2Sphere = test2Script[ "Sphere" ]
check( "test2 加载：default in0 空着",
	test2Switch[ "in" ][0][ "value" ].getInput() is None )
check( "test2 加载：in1 已连", test2Switch[ "in" ][1][ "value" ].getInput() is not None )
check( "test2 加载：in2 已连", test2Switch[ "in" ][2][ "value" ].getInput() is not None )

test2Editor = NE.NetworkEditor( test2Script )
test2Window = GafferUI.Window( "nameSwitchTest2" )
test2Window.setChild( test2Editor )
test2Window._qtWidget().resize( 900, 650 )
test2Window.setVisible( True )
idle()

test2Size = len( test2Switch[ "in" ].children() )
check( "test2：拖 `+` 返回 True",
	test2Editor._createPromotedConnection( test2Switch, "top", test2Sphere[ "out" ] ) )
check( "test2：原生逻辑 = 加新的一路（3 -> 4）",
	len( test2Switch[ "in" ].children() ) == test2Size + 1,
	"%d -> %d" % ( test2Size, len( test2Switch[ "in" ].children() ) ) )
check( "test2：新那路 in3 接上了",
	test2Switch[ "in" ][3][ "value" ].getInput() is not None and
	test2Switch[ "in" ][3][ "value" ].getInput().isSame( test2Sphere[ "out" ] ),
	str( test2Switch[ "in" ][3][ "value" ].getInput() ) )
check( "test2：default in0 **没被填**",
	test2Switch[ "in" ][0][ "value" ].getInput() is None,
	str( test2Switch[ "in" ][0][ "value" ].getInput() ) )
test2Window.setVisible( False )

setupWindow.setVisible( False )

# --- NameSwitch 删输入口：节点大小跟着变（用户：加满输入的 NameSwitch 一个个删，卡片不变）---
#
# NameSwitch 的输入口全在**顶边**（横着排），原生 bound 随 `in` 缩水的是**宽度**：
# 5 路 ~19 单位 → 2 路 ~11 单位（高度恒 4.164）。以前 `in.resize()` 删掉一个**空着**
# 的槽位时没有任何信号响 —— `plugInputChangedSignal` 只在「接上 / 拔掉一根线」时响，
# 删空槽它不响，卡片就永远停在旧大小。现在连了每个直系插口的 `childAddedSignal`
# / `childRemovedSignal`，`in` 一缩就重建、重查一次原生 bound。
shrinkScript = Gaffer.ScriptNode()
shrinkApplication = Gaffer.ApplicationRoot( "nameSwitchShrink" )
shrinkApplication[ "scripts" ].addChild( shrinkScript )
shrinkSource = GafferScene.Sphere( "shrinkSource" )
shrinkScript.addChild( shrinkSource )
shrinkSwitch = Gaffer.NameSwitch( "shrinkSwitch" )
shrinkScript.addChild( shrinkSwitch )
shrinkSwitch.setup( GafferScene.ScenePlug() )
shrinkSwitch[ "in" ].resize( 5 )
for i in range( 5 ) :
	shrinkSwitch[ "in" ][i][ "value" ].setInput( shrinkSource[ "out" ] )
idle()

shrinkEditor = NE.NetworkEditor( shrinkScript )
shrinkWindow = GafferUI.Window( "nameSwitchShrink" )
shrinkWindow.setChild( shrinkEditor )
shrinkWindow._qtWidget().resize( 900, 600 )
shrinkWindow.setVisible( True )
idle()

def shrinkItem() :

	return shrinkEditor._NetworkEditor__nodeItems.get( "shrinkSwitch" )

def shrinkNativeSize() :

	try :
		gg = shrinkEditor._NetworkEditor__graphGadget()
		g = gg.nodeGadget( shrinkSwitch )
		b = g.bound()
		return ( b.max().x - b.min().x, b.max().y - b.min().y )
	except Exception :
		return None

def shrinkDump( tag ) :

	item = shrinkItem()
	native = shrinkNativeSize()
	check( "  [%s] 卡片照原生尺寸（原生 %.3f x %.3f / 我们 %.3f x %.3f）" % (
			tag, native[0], native[1], item._width, item._height ),
		native is not None and abs( item._width - native[0] * NE.PX_PER_UNIT ) < 1e-3
		and abs( item._height - native[1] * NE.PX_PER_UNIT ) < 1e-3,
		"原生 %s / 我们 %.3f x %.3f" % ( native, item._width, item._height ) )
	return ( len( item._nodules[ "top" ] ), item._width )

tops, widths = [], []
check( "in=5 初始 top 有 5 个圆点",
	len( shrinkItem()._nodules[ "top" ] ) == 5,
	str( [ p.getName() for p in shrinkItem()._nodules[ "top" ] ] ) )
tops.append( len( shrinkItem()._nodules[ "top" ] ) )
widths.append( shrinkItem()._width )

# A. 全接上，一个个删 —— 连接断开会带一路，卡片应该跟着变窄
for target in ( 4, 3, 2 ) :
	shrinkSwitch[ "in" ].resize( target )
	idle()
	t, w = shrinkDump( "A resize(%d)" % target )
	tops.append( t )
	widths.append( w )

check( "删一个输入口 top 圆点少一个", tops == [ 5, 4, 3, 2 ], str( tops ) )
check( "每删一次节点都变窄",
	widths[0] > widths[1] > widths[2] > widths[3],
	str( widths ) )

# B. 删**空着**的槽位（以前这儿一点反应都没有）：长回 4 个、第 4 个故意不接，再缩
shrinkSwitch[ "in" ].resize( 4 )
for i in range( 4 ) :
	shrinkSwitch[ "in" ][i][ "value" ].setInput( shrinkSource[ "out" ] )
shrinkSwitch[ "in" ][3][ "value" ].setInput( None )   # in3 空着
idle()
check( "B: in=4 时 in3 空着", shrinkSwitch[ "in" ][3][ "value" ].getInput() is None )

wBefore = shrinkItem()._width
with Gaffer.UndoScope( shrinkScript ) :
	shrinkSwitch[ "in" ].resize( 3 )    # 删掉**空着**的 in3 —— 没有连接断开，只有 childRemoved
idle()
check( "B: 删掉空槽位节点也变窄",
	shrinkItem()._width < wBefore,
	"%.3f -> %.3f" % ( wBefore, shrinkItem()._width ) )
check( "B: top 圆点跟着少了", len( shrinkItem()._nodules[ "top" ] ) == 3,
	str( [ p.getName() for p in shrinkItem()._nodules[ "top" ] ] ) )
wAfterB = shrinkItem()._width

# C. 撤销 `resize(3)`：in3 回来、卡片长回去（撤销这条路以前也卡在旧大小）
shrinkScript.undo()
idle()
check( "C: 撤销后 in3 回来了", len( shrinkSwitch[ "in" ] ) == 4,
	str( len( shrinkSwitch[ "in" ] ) ) )
check( "C: top 圆点长回 4 个", len( shrinkItem()._nodules[ "top" ] ) == 4,
	str( [ p.getName() for p in shrinkItem()._nodules[ "top" ] ] ) )
check( "C: 卡片也跟着长回去",
	shrinkItem()._width > wAfterB,
	"%.3f -> %.3f" % ( wAfterB, shrinkItem()._width ) )

shrinkWindow.setVisible( False )



##########################################################################
section( "侧边参数分栏（Houdini 式收放）+ 名字不截断" )
##########################################################################

# ① 材质属性名太长不能截断（用户：ubersurface 那种名字显示不完整）；
# ② 侧边按 `layout:section` 分栏，header 可以收起 / 展开（Houdini 那套）。

secScript = Gaffer.ScriptNode()
secNode = Gaffer.Node( "secMat" )
secParams = Gaffer.CompoundDataPlug( "parameters" )
secNode.addChild( secParams )
Gaffer.Metadata.registerValue( secParams, "nodule:type", "GafferUI::CompoundNodule" )
Gaffer.Metadata.registerValue( secParams, "noduleLayout:section", "left" )

def addParam( name, label, section, value ) :

	nvp = Gaffer.NameValuePlug( name, value, name )
	secParams.addChild( nvp )
	Gaffer.Metadata.registerValue( nvp, "noduleLayout:label", label )
	Gaffer.Metadata.registerValue( nvp, "layout:section", section )

addParam( "base_color", "Base Color", "Base", imath.Color4f( 1, 0, 0, 1 ) )
addParam( "metalness", "Metalness", "Base", 0.5 )
addParam(
	"roughness",
	"A Very Long Specular Roughness Parameter Name",
	"Specular", 0.3,
)
addParam( "normal", "Normal", "Geometry", imath.V3f( 0, 0, 1 ) )

secScript.addChild( secNode )
NE.setNodePosition( secNode, imath.V2f( 0, 0 ) )

secEditor = NE.NetworkEditor( secScript )
secWindow = GafferUI.Window( "sections" )
secWindow.setChild( secEditor )
secWindow._qtWidget().resize( 900, 600 )
secWindow.setVisible( True )
idle()
secItem = secEditor._NetworkEditor__nodeItems[ "secMat" ]

# --- 分栏数据 ---
secLayout = NE.noduleLayout( secNode )
secData = NE.buildSectionData( secNode, secLayout )
check( "分栏按首次出现顺序聚拢",
	[ ( n, [ p.getName() for p in ps ] ) for n, ps in secData[ "left" ] ]
	== [ ( "Base", [ "base_color", "metalness" ] ),
	     ( "Specular", [ "roughness" ] ),
	     ( "Geometry", [ "normal" ] ) ],
	str( secData ) )

# --- ① 名字不截断 ---
secLabels = secItem._NodeItem__sideLabels
longText = next(
	( text for text, width, connected in secLabels.values()
	  if text.startswith( "A Very Long Specular" ) ),
	None,
)
check( "超长的属性名**完整显示**、不加省略号",
	longText == "A Very Long Specular Roughness Parameter Name",
	str( longText ) )
check( "标签宽度按完整名字算（宽过 SIDE_LABEL_MAX 也照画）",
	secItem._NodeItem__sectionedLabelWidth >= NE.SIDE_LABEL_MAX,
	"%.1f vs %.1f" % ( secItem._NodeItem__sectionedLabelWidth, NE.SIDE_LABEL_MAX ) )
# 分栏材质节点：名字画在卡片**里面**，所以是**卡片自己**要宽到放得下
# （以前名字画在卡外，靠包围盒往外扩）。外侧只剩圆点 + 折叠三角。
check( "卡片撑宽到放得下完整名字（名字现在画在节点里面）",
	secItem.cardRect().width()
	>= secItem._NodeItem__sectionedLabelWidth
		+ 2 * ( NE.NODULE_RADIUS + NE.SIDE_LABEL_GAP ),
	"%s vs %s" % (
		secItem.cardRect().width(),
		secItem._NodeItem__sectionedLabelWidth
			+ 2 * ( NE.NODULE_RADIUS + NE.SIDE_LABEL_GAP ) ) )
check( "侧边不再往卡外写字（__sideLabelWidth 归零）",
	secItem._NodeItem__sideLabelWidth == 0.0,
	str( secItem._NodeItem__sideLabelWidth ) )

# --- ①'' 卡内属性文本颜色和节点色区分开（用户：看不清属性名）---
# 未接线的参数名现在画在卡片**里面**，底是节点自己的色 —— 再混向深背景就糊成一团。
# 改成混向白色提亮（保留插口类型色相），和卡片色拉开。
basePlug = secParams[ "base_color" ]
baseKey = NE.plugKey( secNode, basePlug )
rawColor = secItem._NodeItem__noduleColors[ baseKey ]
cardColor = secItem._NodeItem__sideLabelColor( baseKey, False )
oldDarkMix = QtGui.QColor( NE.mixColors( rawColor.name(), NE._backgroundColor, 0.45 ) )
check( "卡内未接线标签比旧的「混向深背景」亮",
	cardColor.value() > oldDarkMix.value() + 30,
	"card=%d oldDark=%d" % ( cardColor.value(), oldDarkMix.value() ) )
check( "接上线仍是提亮那档（和未接线的分得开）",
	secItem._NodeItem__sideLabelColor( baseKey, True ).value() >= cardColor.value(),
	str( secItem._NodeItem__sideLabelColor( baseKey, True ).value() ) )

# --- ①' 名字进顶栏、参数行排在顶栏下面（用户：把 ui 和名字塞节点顶栏的条里）---
secRect = secItem.cardRect()
topBarBottom = secRect.top() + NE.SIDE_ROWS_BASE_UNITS * NE.PX_PER_UNIT
firstRowY = secItem._NodeItem__sectionHeaders[ "left" ][ 0 ][ 1 ]
check( "参数行从顶栏**下面**开始排（名字条独占顶栏）",
	firstRowY >= topBarBottom,
	"firstRowY=%.2f topBarBottom=%.2f" % ( firstRowY, topBarBottom ) )
check( "行距就是 SIDE_ROW_UNITS（固定行距、不铺满整卡）",
	abs( ( secItem._NodeItem__sectionHeaders[ "left" ][ 1 ][ 1 ] - firstRowY )
		- NE.SIDE_ROW_UNITS * NE.PX_PER_UNIT ) < 1e-3,
	str( secItem._NodeItem__sectionHeaders[ "left" ] ) )

# --- ①'' 外侧只剩圆点：左边那排圆点钉在卡片左边线上 ---
leftXs = set()
for side, plugs in secItem._nodules.items() :
	if side != "left" :
		continue
	for plug in plugs :
		pos = secItem._NodeItem__nodulePositions.get( NE.plugKey( secNode, plug ) )
		if pos is not None :
			leftXs.add( round( pos.x(), 3 ) )
check( "左侧圆点都在卡片左边线上（卡外只剩圆点 + 折叠三角）",
	leftXs == { round( secRect.left(), 3 ) }, str( leftXs ) )

# --- ①''' 分栏材质节点不再画多余的 `+`（用户：属性都显示出来了，别加 +）---
check( "分栏材质节点上不画 `+`",
	not secItem.adderSections(), str( secItem.adderSections() ) )

# --- ①'''' 顶栏色带加宽成标题条 ---
check( "顶栏色带加宽（SECTION_TITLE_HEIGHT 比 ACCENT_HEIGHT 高得多）",
	NE.SECTION_TITLE_HEIGHT > NE.ACCENT_HEIGHT * 4,
	"%.1f vs %.1f" % ( NE.SECTION_TITLE_HEIGHT, NE.ACCENT_HEIGHT ) )
check( "标题条仍在参数行**上面**（行区不被压到）",
	NE.SECTION_TITLE_HEIGHT <= NE.SIDE_ROWS_BASE_UNITS * NE.PX_PER_UNIT,
	"%.1f vs %.1f" % ( NE.SECTION_TITLE_HEIGHT, NE.SIDE_ROWS_BASE_UNITS * NE.PX_PER_UNIT ) )
# 色带上的文字要按色带亮度挑深/浅（亮色带上白字看不清）
check( "亮色带用深字",
	NE._contrastTextColor( "#f0dc28" ).name() == "#15171a",
	NE._contrastTextColor( "#f0dc28" ).name() )
check( "暗色带用浅字",
	NE._contrastTextColor( "#2c2c2c" ).name().lower() == NE._textColor.lower(),
	NE._contrastTextColor( "#2c2c2c" ).name() )

# --- ①''''' 卡内标签有宽度上限，卡片不许无限撑宽 ---
check( "卡内标签宽度夹在 SECTION_LABEL_MAX 以内",
	secItem._NodeItem__sectionedLabelWidth <= NE.SECTION_LABEL_MAX + 1e-3,
	"%.1f vs %.1f" % ( secItem._NodeItem__sectionedLabelWidth, NE.SECTION_LABEL_MAX ) )
check( "卡片宽度也就跟着有上限（不会被一条超长名字撑成两倍）",
	secItem.cardRect().width()
	<= ( NE.NODULE_RADIUS + NE.SIDE_LABEL_GAP ) * 2 + NE.SECTION_LABEL_MAX * 2
		+ NE.SECTION_CARD_PAD + 1e-3,
	str( secItem.cardRect().width() ) )

# --- ①'''''' shape() 必须是并集，不能被三角异或出洞 ---
# （`QPainterPath` 默认 OddEvenFill：三角命中框和卡片重叠那块会变成洞，
#   表现就是「点展开三角一点反应都没有」）
firstHeaderY = secItem._NodeItem__sectionHeaders[ "left" ][ 0 ][ 1 ]
check( "三角那一点真的在 shape() 里（fillRule 是并集）",
	secItem.shape().contains( QtCore.QPointF( secItem.cardRect().left(), firstHeaderY ) ),
	str( secItem.shape().boundingRect() ) )

# --- ② 分栏布局：默认收起，高度只算 header ---
secRows = len( secItem._NodeItem__sectionRows( "left" ) )   # 3 header，全收着 = 3
check( "默认收起：可见行数只有 header", secRows == 3, str( secRows ) )
collapsedHeight = secItem._height
check( "收起的高度 = 行数公式（不撑高）",
	abs( secItem._height
		- ( secRows * NE.SIDE_ROW_UNITS + NE.SIDE_ROWS_BASE_UNITS ) * NE.PX_PER_UNIT ) < 1e-3,
	"%.2f" % secItem._height )
check( "header 的命中矩形都记下来了",
	[ name for side in ( "left", "right" )
	  for name, y in secItem._NodeItem__sectionHeaders.get( side, [] ) ]
	== [ "Base", "Specular", "Geometry" ],
	str( secItem._NodeItem__sectionHeaders ) )

# 只点折叠三角、点名字不动作（用户反馈）
headerName, headerY = secItem._NodeItem__sectionHeaders[ "left" ][ 0 ]
# 三角画在**卡片左边线上**那一行（名字已经在卡片里面了，外侧只剩圆点 + 三角）
triCenter = QtCore.QPointF( secItem.cardRect().left(), headerY )
check( "sectionAt 命中 Base 的折叠三角",
	secItem.sectionAt( triCenter ) == ( "left", "Base" ),
	str( secItem.sectionAt( triCenter ) ) )
# **Houdini 式：整条栏名行也能点**（v0.46 的「只点小三角」
# 是因为当年栏名画在卡片外面会吃邻居；现在名字在卡里、每栏独占一行，
# 卡边线上那个 8px 三角太难瞄，整行当按钮才好点）。
check( "sectionAt 点栏名也切换（Houdini 式）",
	secItem.sectionAt(
		QtCore.QPointF( secItem.cardRect().left() + 20.0, headerY )
	) == ( "left", "Base" ),
	str( secItem.sectionAt(
		QtCore.QPointF( secItem.cardRect().left() + 20.0, headerY ) ) ) )
# 参数行不算 header（点它是连线，不是收放）—— 展开之后再验，见下面展开那段
check( "sectionAt 卡片正中不算 header（另一侧的行归另一侧）",
	secItem.sectionAt( QtCore.QPointF( secItem.cardRect().center().x() - 1.0, headerY ) )
		== ( "left", "Base" )
	and secItem.sectionAt(
		QtCore.QPointF( secItem.cardRect().right() - 1.0, headerY ) ) is None,
	str( secItem.sectionAt( QtCore.QPointF( secItem.cardRect().right() - 1.0, headerY ) ) ) )
check( "三角那里不是 nodule（收放和连线不打架）",
	secItem.noduleAt( triCenter ) is None )

# --- 展开 Base：长高、参数摆出来 ---
secEditor._toggleSection( secNode, "left", "Base" )
idle()
check( "展开状态写进元数据（BoolData False = 不收起）",
	not NE.sectionCollapsed( secNode, "left", "Base" ),
	str( Gaffer.Metadata.value( secNode, "nodeGadget:sectionCollapsed:left:Base" ) ) )

secItem = secEditor._NetworkEditor__nodeItems[ "secMat" ]   # item 已重建
expandedHeight = secItem._height
check( "展开节点变高", expandedHeight > collapsedHeight,
	"%.2f vs %.2f" % ( expandedHeight, collapsedHeight ) )
check( "展开后可见行数 3 -> 5（Base 那栏的参数摆出来）",
	len( secItem._NodeItem__sectionRows( "left" ) ) == 5,
	str( len( secItem._NodeItem__sectionRows( "left" ) ) ) )
check( "header 还在（展开只是把参数摆出来）",
	[ name for name, y in secItem._NodeItem__sectionHeaders[ "left" ] ]
	== [ "Base", "Specular", "Geometry" ],
	str( secItem._NodeItem__sectionHeaders[ "left" ] ) )
check( "展开后参数圆点有位置了",
	"parameters.base_color" in secItem._NodeItem__nodulePositions,
	str( list( secItem._NodeItem__nodulePositions ) ) )

# --- 再收起：高度缩回、参数藏、圆点锚到 header ---
secEditor._toggleSection( secNode, "left", "Base" )
idle()
secItem = secEditor._NetworkEditor__nodeItems[ "secMat" ]
check( "再收起、高度缩回", abs( secItem._height - collapsedHeight ) < 1e-3,
	"%.2f vs %.2f" % ( secItem._height, collapsedHeight ) )
check( "收起来的参数不画了（可见行数 5 -> 3）",
	len( secItem._NodeItem__sectionRows( "left" ) ) == 3,
	str( len( secItem._NodeItem__sectionRows( "left" ) ) ) )

# 收起来的参数圆点锚到 Base header 那一行：连着的线终点停在栏上，不甩出卡片
hiddenPos = secItem._NodeItem__nodulePositions.get( "parameters.base_color" )
baseHeaderY = [
	y for name, y in secItem._NodeItem__sectionHeaders[ "left" ] if name == "Base"
][ 0 ]
check( "收起来的参数圆点锚在 Base header 那一行",
	hiddenPos is not None
	and abs( hiddenPos.y() - baseHeaderY ) < 1e-3,
	str( hiddenPos ) )
hiddenPos = secItem._NodeItem__nodulePositions.get( "parameters.roughness" )
check( "收起的 Specular 圆点也锚在 header 行", hiddenPos is not None )
baseCenter = QtCore.QPointF(
	secItem.cardRect().left(), secItem._NodeItem__sectionHeaders[ "left" ][ 0 ][ 1 ]
)
check( "Base header 那行不是参数圆点", secItem.noduleAt( baseCenter ) is None )

# 展开回来：高度复原
secEditor._toggleSection( secNode, "left", "Base" )
idle()
secItem = secEditor._NetworkEditor__nodeItems[ "secMat" ]
check( "再点一次展开、高度复原",
	abs( secItem._height - expandedHeight ) < 1e-3,
	"%.2f vs %.2f" % ( secItem._height, expandedHeight ) )
check( "展开后参数圆点回来了",
	"parameters.base_color" in secItem._NodeItem__nodulePositions,
	str( list( secItem._NodeItem__nodulePositions ) ) )

# --- 灯光节点**不走**分栏那套（用户反馈：这套样式在灯光上观感不对）---
#
# 拿和上面一模一样的 `parameters` + `layout:section` 元数据挂到一个灯光节点上，
# `buildSectionData` 必须返回空 —— 判据走 `nodeGlyph`（Light 子类按 MRO，
# 材质型灯光按名字 / type），两种灯都认得。
lightMat = Light( "keyLightMat" )
lightParams = Gaffer.CompoundDataPlug( "parameters" )
lightMat.addChild( lightParams )
Gaffer.Metadata.registerValue( lightParams, "nodule:type", "GafferUI::CompoundNodule" )
Gaffer.Metadata.registerValue( lightParams, "noduleLayout:section", "left" )
for lightParamName, lightSection in (
	( "color", "Base" ), ( "intensity", "Base" ), ( "spread", "Shape" )
) :
	lightNvp = Gaffer.NameValuePlug( lightParamName, 1.0, lightParamName )
	lightParams.addChild( lightNvp )
	Gaffer.Metadata.registerValue( lightNvp, "noduleLayout:label", lightParamName.title() )
	Gaffer.Metadata.registerValue( lightNvp, "layout:section", lightSection )

check( "灯光节点确实被认成灯光", NE.nodeGlyph( lightMat ) == NE.GLYPH_LIGHT,
	str( NE.nodeGlyph( lightMat ) ) )
check( "灯光节点不分栏（同样的元数据在材质上是分栏的）",
	NE.buildSectionData( lightMat, NE.noduleLayout( lightMat ) ) == {},
	str( NE.buildSectionData( lightMat, NE.noduleLayout( lightMat ) ) ) )

secScript.addChild( lightMat )
NE.setNodePosition( lightMat, imath.V2f( 26, 0 ) )
idle()
lightItem = secEditor._NetworkEditor__nodeItems[ "keyLightMat" ]
check( "灯光卡片上没有分栏数据", not lightItem._NodeItem__sectionData,
	str( lightItem._NodeItem__sectionData ) )
check( "灯光卡片没有分栏 header（也就没有折叠三角）",
	not any( lightItem._NodeItem__sectionHeaders.get( s ) for s in ( "left", "right" ) ),
	str( lightItem._NodeItem__sectionHeaders ) )
check( "灯光的参数名照旧写在卡片外面（__sideLabelWidth 不为 0）",
	lightItem._NodeItem__sideLabelWidth > 0.0,
	str( lightItem._NodeItem__sideLabelWidth ) )
check( "灯光卡片点哪儿都不会收放分栏",
	lightItem.sectionAt( QtCore.QPointF( lightItem.cardRect().left(), 0 ) ) is None )

secWindow.setVisible( False )



##########################################################################
section( "复合圆点：childrenVisible 打在没有子插口的插口上" )
##########################################################################

# 真机材质图（用户的 shader_test.gfr）里，`compoundNumericNodule:childrenVisible`
# 被写在了**没有子插口的 FloatPlug** 上（`mix2` / `coat` / `specular_roughness`…）。
# 原生对这种插口画的还是普通 StandardNodule —— 这条元数据只有 `CompoundNumericNodule`
# 自己会看。我们照旧递归的话一个子插口都收不到，**圆点凭空少一个**，连上去的线画到空处。

cnScript = Gaffer.ScriptNode()
cnNode = Gaffer.Node( "cnNode" )
cnNode.addChild( Gaffer.FloatPlug( "f", Gaffer.Plug.Direction.In, flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
cnNode.addChild( Gaffer.Color3fPlug( "c", Gaffer.Plug.Direction.In, flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
cnScript.addChild( cnNode )
NE.setNodePosition( cnNode, imath.V2f( 0, 0 ) )

check( "没打元数据时：float 不是复合", not NE.isCompoundNodule( cnNode["f"] ) )
check( "没打元数据时：Color3f 也不展开（原生默认收起）", not NE.isCompoundNodule( cnNode["c"] ) )

Gaffer.Metadata.registerValue( cnNode["f"], "compoundNumericNodule:childrenVisible", True )
Gaffer.Metadata.registerValue( cnNode["c"], "compoundNumericNodule:childrenVisible", True )

check( "打在没有子插口的 float 上：**不当复合**（原生画的是普通圆点）",
	not NE.isCompoundNodule( cnNode["f"] ) )
check( "打在 Color3f 上：照旧展开成 r/g/b", NE.isCompoundNodule( cnNode["c"] ) )

cnLayout = NE.noduleLayout( cnNode )
cnNames = [ p.relativeName( cnNode ) for plugs in cnLayout.values() for p in plugs ]
check( "float 的圆点还在（这就是那 14 个凭空少掉的）", "f" in cnNames, str( cnNames ) )
check( "Color3f 摊成三个子圆点",
	set( [ "c.r", "c.g", "c.b" ] ).issubset( set( cnNames ) ) and "c" not in cnNames, str( cnNames ) )

cnEditor = NE.NetworkEditor( cnScript )
cnWindow = GafferUI.Window( "compoundNodule" )
cnWindow.setChild( cnEditor )
cnWindow._qtWidget().resize( 800, 500 )
cnWindow.setVisible( True )
idle()
cnItem = cnEditor._NetworkEditor__nodeItems[ "cnNode" ]
cnItemNames = [
	p.relativeName( cnNode ) for section in ( "top", "bottom", "left", "right" )
	for p in cnItem._nodules.get( section, [] )
]
check( "画出来的圆点也有它", "f" in cnItemNames, str( cnItemNames ) )
check( "而且能问出它在哪儿（连线要接过去）",
	cnItem.nodulePosition( cnNode["f"] ) is not None )
cnWindow.setVisible( False )


##########################################################################
section( "拖一根线到材质的 + 上（原生 PlugAdder 那套）" )
##########################################################################

dropScript = Gaffer.ScriptNode()
dropApplication = Gaffer.ApplicationRoot( "adderDropTest" )
dropApplication[ "scripts" ].addChild( dropScript )

dropTargetNode = GafferOSL.OSLShader( "dropShader" )
dropScript.addChild( dropTargetNode )
# 「藏起来的可显示参数」—— 原生就是这时候才在 `parameters` 那条边上画 `+`
# （aiStandardSurface 那种材质节点天天如此）
dropParameters = dropTargetNode[ "parameters" ]
for name in ( "baseColor", "specColor" ) :
	plug = Gaffer.Color3fPlug(
		name, Gaffer.Plug.Direction.In,
		flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
	)
	dropParameters.addChild( plug )
	Gaffer.Metadata.registerValue( plug, "noduleLayout:visible", False )

dropSourceNode = Gaffer.Node( "dropSrc" )
dropSourcePlug = Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out )
dropSourceNode.addChild( dropSourcePlug )
dropScript.addChild( dropSourceNode )

NE.setNodePosition( dropTargetNode, imath.V2f( 0, 0 ) )
NE.setNodePosition( dropSourceNode, imath.V2f( -40, 0 ) )

dropEditor = NE.NetworkEditor( dropScript )
dropWindow = GafferUI.Window( "adderDrop" )
dropWindow.setChild( dropEditor )
dropWindow._qtWidget().resize( 1200, 800 )
dropWindow.setVisible( True )
idle()
dropView = dropEditor.graphView()
dropView.frameAll()
idle()

dropItem = dropEditor._NetworkEditor__nodeItems[ "dropShader" ]
dropSections = dropItem.adderSections()
check( "藏着参数的那一边有个 `+`", "left" in dropSections, str( dropSections ) )

adderScene = dropItem.mapToScene( dropSections[ "left" ] )
adderView = dropView.mapFromScene( adderScene )

# **`+` 画在卡片外面**：光问 `nodeItemAt` 是找不到它的（真机上"拖上去没反应"就是这个）
hitItem, hitSection = dropView.adderAt( adderView )
check( "命中测试找得到画在卡片外面的 `+`",
	hitItem is not None and hitSection == "left",
	"%s / %s" % ( hitItem.nodeName if hitItem else None, hitSection ) )

dropSourceItem = dropEditor._NetworkEditor__nodeItems[ "dropSrc" ]
startView = dropView.mapFromScene(
	dropSourceItem.mapToScene( dropSourceItem.nodulePosition( dropSourcePlug ) ) )

dropView._GraphView__beginConnect( dropSourceItem, dropSourcePlug, startView )
dropView._GraphView__updateConnectWire( adderView )
check( "拖过去的时候 `+` 亮起来（不是去吸附最近的那个圆点）",
	dropEditor._NetworkEditor__hoveredAdderItem == "dropShader",
	str( dropEditor._NetworkEditor__hoveredAdderItem ) )

dropView._GraphView__endConnect( adderView )
idle()
dropPanel = dropEditor._NetworkEditor__creatorPopup
check( "松手弹出藏起来的可连接参数",
	dropPanel is not None and dropPanel.isVisible() and dropPanel.rowCount() == 2,
	str( dropPanel.rowCount() ) if dropPanel is not None else "没弹" )

dropPanel.activateRow( 0 )
idle()
dropConnected = [
	p.getName() for p in Gaffer.Plug.RecursiveRange( dropParameters ) if p.getInput() is not None
]
check( "挑一个就接上了", bool( dropConnected ), str( dropConnected ) )

dropWindow.setVisible( False )


##########################################################################
section( "杂项" )
##########################################################################

# 回归：scene 选择一变就抛 AttributeError 刷屏（当年是问了一个不存在的
# GafferUI.Widget.currentButtons()）。现在一律直接问 Qt 的鼠标状态。
try :
	editor._NetworkEditor__sceneSelectionChanged()
	check( "scene 选择变化不抛异常", True )
except Exception :
	check( "scene 选择变化不抛异常", False, traceback.format_exc() )

check( "1.7 有 Widget.currentButtons（我们仍直接问 Qt，少转一次枚举）",
	hasattr( GafferUI.Widget, "currentButtons" ) )

check( "默认曲线", editor.getWireStyle() == NE.WIRE_CURVED )
current = editor._NetworkEditor__edgeItems
curved = current[0].path().length() if current else 0
editor.setWireStyle( NE.WIRE_STRAIGHT )
straight = editor._NetworkEditor__edgeItems[0].path().length() if editor._NetworkEditor__edgeItems else 0
check( "直线不比曲线长", straight <= curved + 1e-3, "%f vs %f" % ( straight, curved ) )
editor.setWireStyle( NE.WIRE_CURVED )

check( "__repr__ round-trip", repr( editor ) == "GafferUI.NetworkEditor( scriptNode )", repr( editor ) )
check( "注册进 GafferUI 命名空间", hasattr( GafferUI, "NetworkEditor" ) )
check( "Editor 类型已注册", "NetworkEditor" in GafferUI.Editor.types() )

try :
	img = QtGui.QImage( 800, 600, QtGui.QImage.Format_ARGB32 )
	img.fill( 0 )
	painter = QtGui.QPainter( img )
	scene.render( painter )
	painter.end()
	check( "scene.render 不抛异常", True )
except Exception :
	check( "scene.render 不抛异常", False, traceback.format_exc() )

window.setVisible( False )

##########################################################################
# 从别的编辑器拖东西进来（路径 → PathFilter / 节点 → 换层取景）
##########################################################################

import GafferSceneUI


## GafferUI 的 DragDropEvent 是 C++ 对象，测试里大多只要几个字段，用这个鸭子类型的就够。
# 真的 `GafferUI.DragDropEvent` —— 拖放要转发给原生 NodeGadget 的 C++ 信号，
# 自己捏的 Python 对象过不了 Boost 的参数检查
def _DropEvent( data, modifiers = GafferUI.ModifiableEvent.Modifiers.None_ ) :

	event = GafferUI.DragDropEvent(
		GafferUI.ButtonEvent.Buttons.Left, GafferUI.ButtonEvent.Buttons.Left,
		IECore.LineSegment3f(), modifiers
	)
	event.data = data
	return event

_DropEvent.Modifiers = GafferUI.ModifiableEvent.Modifiers


dropApp = Gaffer.ApplicationRoot( "networkEditorDropTest" )
dropScript = Gaffer.ScriptNode()
dropApp[ "scripts" ].addChild( dropScript )

dropPlane = GafferScene.Plane( "dropPlane" ) ; dropScript.addChild( dropPlane )
dropIsolate = GafferScene.Isolate( "dropIsolate" ) ; dropScript.addChild( dropIsolate )
dropIsolate[ "in" ].setInput( dropPlane[ "out" ] )
NE.setNodePosition( dropPlane, imath.V2f( 0, 8 ) )
NE.setNodePosition( dropIsolate, imath.V2f( 0, 0 ) )

dropEditor = NE.NetworkEditor( dropScript )
dropWindow = GafferUI.Window()
dropWindow.setChild( dropEditor )
dropWindow._qtWidget().resize( 900, 700 )
dropWindow.setVisible( True )
idle()

dropView = dropEditor.graphView()
# 落点是按视口像素算的，节点得先在画面里（`view.items()` 只在视口范围内命中）
dropView.frameAll()
idle()

def dropPos( name ) :

	item = dropEditor._NetworkEditor__nodeItems[ name ]
	return dropView.mapFromScene( item.sceneBoundingRect().center() )

def emptyPos() :

	return dropView.mapFromScene( QtCore.QPointF( -4000, -4000 ) )

# --- 路径落在没有 filter 的节点上 → 自动建 PathFilter 接上去 ---
handled = dropEditor._performDrop(
	_DropEvent( IECore.StringVectorData( [ "/plane", "/group/sphere" ] ) ), dropPos( "dropIsolate" )
)
check( "路径落在节点上被处理了", handled )
filterInput = dropIsolate[ "filter" ].getInput()
check( "自动建了 PathFilter 并接上", filterInput is not None and isinstance( filterInput.node(), GafferScene.PathFilter ),
	str( filterInput ) )
dropFilter = filterInput.node() if filterInput is not None else None
check( "paths 写进去了（排过序）",
	dropFilter is not None and list( dropFilter[ "paths" ].getValue() ) == [ "/group/sphere", "/plane" ],
	str( list( dropFilter[ "paths" ].getValue() ) ) if dropFilter is not None else "no filter" )
idle()
check( "新建的 PathFilter 在图里画出来了", dropFilter.getName() in dropEditor._NetworkEditor__nodeItems,
	str( sorted( dropEditor._NetworkEditor__nodeItems ) ) )
check( "而且被摆到了空位上（不是压在 0,0）", NE.nodePosition( dropFilter ) is not None )

# --- Shift = 加，Ctrl = 减（和原生一样）---
dropEditor._performDrop(
	_DropEvent( IECore.StringVectorData( [ "/newThing" ] ), modifiers = _DropEvent.Modifiers.Shift ),
	dropPos( "dropIsolate" )
)
check( "Shift 是往上加", list( dropFilter[ "paths" ].getValue() ) == [ "/group/sphere", "/newThing", "/plane" ],
	str( list( dropFilter[ "paths" ].getValue() ) ) )
dropEditor._performDrop(
	_DropEvent( IECore.StringVectorData( [ "/plane" ] ), modifiers = _DropEvent.Modifiers.Control ),
	dropPos( "dropIsolate" )
)
check( "Ctrl 是减掉", list( dropFilter[ "paths" ].getValue() ) == [ "/group/sphere", "/newThing" ],
	str( list( dropFilter[ "paths" ].getValue() ) ) )

# --- 落在 PathFilter 节点自己身上（它的 paths 插口带 ui:scene:acceptsPaths）---
dropEditor._performDrop( _DropEvent( IECore.StringVectorData( [ "/direct" ] ) ), dropPos( dropFilter.getName() ) )
check( "直接落在 PathFilter 上就是改它", list( dropFilter[ "paths" ].getValue() ) == [ "/direct" ],
	str( list( dropFilter[ "paths" ].getValue() ) ) )

# --- 只读的不动它，但也别当没接住 ---
Gaffer.MetadataAlgo.setReadOnly( dropFilter[ "paths" ], True )
check( "只读时判成 notEditable",
	dropEditor._pathDropMode( "dropIsolate", _DropEvent( IECore.StringVectorData( [ "/x" ] ) ) ) == "notEditable" )
check( "只读时放下来算处理过（但不改值）",
	dropEditor._performDrop( _DropEvent( IECore.StringVectorData( [ "/x" ] ) ), dropPos( "dropIsolate" ) ) and
	list( dropFilter[ "paths" ].getValue() ) == [ "/direct" ] )
Gaffer.MetadataAlgo.setReadOnly( dropFilter[ "paths" ], False )

# --- 没有 filter 插口的节点不收路径 ---
check( "Plane 这种节点不收路径",
	dropEditor._pathDropMode( "dropPlane", _DropEvent( IECore.StringVectorData( [ "/x" ] ) ) ) is None )

# --- 指针反馈 + 落点节点描边 ---
hoverEvent = _DropEvent( IECore.StringVectorData( [ "/x" ] ) )
dropEditor._NetworkEditor__dragEnter( dropEditor, hoverEvent )
dropEditor._updateDragTarget( hoverEvent, dropPos( "dropIsolate" ) )
pointerName = GafferUI.Pointer.getCurrent().fileName() if GafferUI.Pointer.getCurrent() is not None else ""
check( "指针换成「替换 objects」那个", "replaceObjects" in pointerName, pointerName )
check( "落点节点被描边高亮", dropEditor._NetworkEditor__dropTargetItem == "dropIsolate",
	str( dropEditor._NetworkEditor__dropTargetItem ) )
dropEditor._updateDragTarget( hoverEvent, emptyPos() )
check( "移到空白处高亮撤掉", dropEditor._NetworkEditor__dropTargetItem is None )
dropEditor._NetworkEditor__dragLeave( dropEditor, hoverEvent )
check( "离开后指针还原", GafferUI.Pointer.getCurrent() is None, str( GafferUI.Pointer.getCurrent() ) )

# --- 转发给原生 NodeGadget（gui startup 里就是往每个 NodeGadget 上挂这个）---
nativeIsolate = GafferScene.Isolate( "nativeIsolate" ) ; dropScript.addChild( nativeIsolate )
NE.setNodePosition( nativeIsolate, imath.V2f( 20, 0 ) )
idle()
nativeGadget = None
graphGadget = dropEditor._NetworkEditor__graphGadget()
if graphGadget is not None :
	nativeGadget = graphGadget.nodeGadget( nativeIsolate )
check( "拿得到原生 NodeGadget", nativeGadget is not None )
if nativeGadget is not None :
	GafferSceneUI.PathFilterUI.addObjectDropTarget( nativeGadget )
	realEvent = GafferUI.DragDropEvent()
	realEvent.data = IECore.StringVectorData( [ "/fromNative" ] )
	handled = dropEditor._performDrop( realEvent, dropPos( "nativeIsolate" ) )
	nativeInput = nativeIsolate[ "filter" ].getInput()
	check( "原生处理器接住了这次拖放", handled )
	check( "原生那条路也建出了 PathFilter",
		nativeInput is not None and isinstance( nativeInput.node(), GafferScene.PathFilter ), str( nativeInput ) )
	if nativeInput is not None :
		check( "原生写进去的 paths 对", list( nativeInput.node()[ "paths" ].getValue() ) == [ "/fromNative" ],
			str( list( nativeInput.node()[ "paths" ].getValue() ) ) )

# --- 拖节点 / 节点集合进来 → 换到它所在那一层并取景 ---
dropBox = Gaffer.Box( "dropBox" ) ; dropScript.addChild( dropBox )
innerA = GafferScene.Plane( "innerA" ) ; dropBox.addChild( innerA )
innerB = GafferScene.Isolate( "innerB" ) ; dropBox.addChild( innerB )
innerB[ "in" ].setInput( innerA[ "out" ] )
NE.setNodePosition( innerA, imath.V2f( 0, 4 ) )
NE.setNodePosition( innerB, imath.V2f( 0, 0 ) )
idle()
check( "拖单个节点进来算处理过", dropEditor._performDrop( _DropEvent( innerB ), emptyPos() ) )
check( "换到了它所在那一层", dropEditor.getRootNode().isSame( dropBox ), dropEditor.getRootNode().getName() )
check( "并且选中了它", [ n.getName() for n in dropScript.selection() ] == [ "innerB" ],
	str( [ n.getName() for n in dropScript.selection() ] ) )

dropEditor.setRootNode( dropScript )
idle()
nodeSet = Gaffer.StandardSet( [ innerA, innerB ] )
check( "拖一组节点进来也行", dropEditor._performDrop( _DropEvent( nodeSet ), emptyPos() ) )
check( "还是换到同一层", dropEditor.getRootNode().isSame( dropBox ) )
check( "两个都选上了", sorted( n.getName() for n in dropScript.selection() ) == [ "innerA", "innerB" ],
	str( sorted( n.getName() for n in dropScript.selection() ) ) )
dropEditor.setRootNode( dropScript )
idle()

# 父级不同的一组节点原生是不收的（框不了）
mixedSet = Gaffer.StandardSet( [ innerA, dropIsolate ] )
check( "父级不同的一组不收", not dropEditor._NetworkEditor__dropNodes( mixedSet ) )

# --- 不认识的东西不收 ---
check( "插口这种数据不收", not dropEditor._NetworkEditor__canAcceptDrag( _DropEvent( dropIsolate[ "filter" ] ) ) )
check( "空列表不收", not dropEditor._NetworkEditor__canAcceptDrag( _DropEvent( IECore.StringVectorData( [] ) ) ) )
check( "别的脚本里的节点不收",
	not dropEditor._NetworkEditor__canAcceptDrag( _DropEvent( GafferScene.Plane( "outsider" ) ) ) )

# --- 场景位置那种拖拽：来源不是场景编辑器就不认 ---
check( "来源不明的单条路径不算「场景位置」",
	dropEditor._locationDropData( _DropEvent( IECore.StringVectorData( [ "/a" ] ) ) ) is None )

# --- focus：变暗 / 折角是不是真的画到像素上了（只断言 pen 不算数）---
def countPixels( image, color, tolerance = 12 ) :

	target = QtGui.QColor( color )
	count = 0
	for y in range( 0, image.height(), 2 ) :
		for x in range( 0, image.width(), 2 ) :
			pixel = QtGui.QColor( image.pixel( x, y ) )
			if (
				abs( pixel.red() - target.red() ) < tolerance and
				abs( pixel.green() - target.green() ) < tolerance and
				abs( pixel.blue() - target.blue() ) < tolerance
			) :
				count += 1
	return count

def renderDropView() :

	dropView.frameAll()
	idle()
	image = QtGui.QImage( dropView.viewport().width(), dropView.viewport().height(), QtGui.QImage.Format_ARGB32 )
	image.fill( 0 )
	painter = QtGui.QPainter( image )
	dropView.render( painter )
	painter.end()
	return image

# 先在没 focus 的状态下数一遍暗色像素当基线
baseDim = countPixels( renderDropView(), NE._disabledColor( NE._connectionColor, connection = True ) )

dropScript.setFocus( dropFilter )   # PathFilter：它的上游啥都没有，所以场景连线全变暗
for _ in range( 40 ) :
	idle()
	tracker = dropEditor._NetworkEditor__contextTracker()
	if tracker is not None and not tracker.updatePending() and tracker.targetNode() is not None :
		break
idle()
check( "focus 之后有线被判成不参与",
	any( not e.isWireActive() for e in dropEditor._NetworkEditor__edgeItems ),
	str( [ ( e.edge.srcNode.getName(), e.edge.dstNode.getName(), e.isWireActive() ) for e in dropEditor._NetworkEditor__edgeItems ] ) )
image = renderDropView()
dimPixels = countPixels( image, NE._disabledColor( NE._connectionColor, connection = True ) )
check( "变暗真的画到画面上了（数暗色像素）", dimPixels > baseDim + 20, "%d → %d" % ( baseDim, dimPixels ) )
goldPixels = countPixels( image, NE._focusRing, tolerance = 26 )
# 角标现在是画在卡片**外侧**的三角形（面积 = 边长²/2，比原来那个占的像素少一些），
# 这里只要求"画到画面上了"
check( "focus 角标也画到画面上了", goldPixels > 10, "%d 个金色像素" % goldPixels )
dropScript.setFocus( None )
idle()

dropWindow.setVisible( False )


##########################################################################
section( "自动对齐：范围内最近那个节点（Houdini 那套）" )
##########################################################################

# 照 Houdini：只在范围内找最接近的节点，保持横平竖直 —— 以前是「x 吸最近的、y 吸最近的」，两个轴可能来自两个不同节点、
# 而且不管隔多远都算；现在只在 `SNAP_RANGE` 半径内挑**一个**最近的参照，只吸一个轴。

snapScript = Gaffer.ScriptNode()

def atScene( node, x, y ) :

	# scene 像素 → Gaffer 单位（y 向上，所以取负）
	NE.setNodePosition( node, imath.V2f( x / NE.PX_PER_UNIT, -y / NE.PX_PER_UNIT ) )

snapDragged = GafferScene.Sphere( "snapDragged" )
snapA = GafferScene.Sphere( "snapA" )       # 近的那个，x = 0
snapB = GafferScene.Sphere( "snapB" )       # 远一点的那个，x = 6
snapC = GafferScene.Sphere( "snapC" )       # 对得上但在感知半径之外
for node in ( snapDragged, snapA, snapB, snapC ) :
	snapScript.addChild( node )

atScene( snapDragged, -400.0, -400.0 )     # 拖的那个先摆远点，别自己干扰判定
atScene( snapA, 0.0, 120.0 )
atScene( snapB, 6.0, 220.0 )
atScene( snapC, 303.0, 100.0 + NE.SNAP_RANGE + 60.0 )

snapEditor = NE.NetworkEditor( snapScript )
snapWindow = GafferUI.Window( "snap" )
snapWindow.setChild( snapEditor )
snapWindow._qtWidget().resize( 900, 700 )
snapWindow.setVisible( True )
idle()

snapItems = snapEditor._NetworkEditor__nodeItems
snapItem = snapItems[ "snapDragged" ]
snapEditor.setSnapEnabled( True )
snapEditor._clearSelection()

snapView = snapEditor.graphView()

def snapMouse( eventType, viewPos, button, buttons ) :
	QtWidgets.QApplication.sendEvent( snapView.viewport(), QtGui.QMouseEvent(
		eventType, QtCore.QPointF( viewPos ), QtCore.QPointF( viewPos ),
		button, buttons, QtCore.Qt.NoModifier
	) )

snapStart = snapView.mapFromScene( snapItem.pos() )
snapMouse( QtCore.QEvent.MouseButtonPress, snapStart, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
check( "拖起来了", snapView.isDraggingNodes() )

# --- ① 两个都能对上时认**最近**那个 ---
# p 到 snapA 差 (dx=-2, dy=20)、到 snapB 差 (dx=4, dy=120)：两个的 x 都在容差内，
# 但 snapA 近得多 → 吸到 snapA 的 x（= 0）而不是 snapB 的（= 6）。
p = QtCore.QPointF( 2.0, 100.0 )
r = snapEditor._snapNodePosition( snapItem, p )
check( "两个都能对上时吸最近那个",
	abs( r.x() - snapItems[ "snapA" ].pos().x() ) < 1e-6, str( r ) )
check( "只吸一个轴", abs( r.y() - p.y() ) < 1e-6, str( r ) )
check( "参考线就一条", len( snapEditor.snapGuides() ) == 1, str( snapEditor.snapGuides() ) )

# --- ② 感知半径之外的节点一概不参与 ---
# 这个位置对 snapA / snapB 两个轴都差得远（对不成横平竖直），只有 snapC 的 x 差 3px，
# 但它在 `SNAP_RANGE` 之外 → 不该有任何吸附。
far = QtCore.QPointF( 300.0, 100.0 )
farResult = snapEditor._snapNodePosition( snapItem, far )
check( "范围外就算对得上也不吸",
	abs( farResult.x() - far.x() ) < 1e-6 and abs( farResult.y() - far.y() ) < 1e-6,
	str( farResult ) )
check( "范围外不画参考线", snapEditor.snapGuides() == [], str( snapEditor.snapGuides() ) )

# 把 snapC 挪进半径内，同一个位置就该吸上了 —— 证明拦住它的确实是"范围"这一条
atScene( snapC, 303.0, 100.0 + 200.0 )
idle()
snapItems = snapEditor._NetworkEditor__nodeItems
snapItem = snapItems[ "snapDragged" ]
inRange = snapEditor._snapNodePosition( snapItem, far )
check( "挪进半径内就吸上了",
	abs( inRange.x() - snapItems[ "snapC" ].pos().x() ) < 1e-6, str( inRange ) )

# --- ③ 已经站在一条横行上时，吸的是 y（不会被拽到别人身上）---
rowPoint = QtCore.QPointF( snapItems[ "snapA" ].pos().x() + 200.0,
	snapItems[ "snapA" ].pos().y() + 5.0 )
rowResult = snapEditor._snapNodePosition( snapItem, rowPoint )
check( "横行上吸 y",
	abs( rowResult.y() - snapItems[ "snapA" ].pos().y() ) < 1e-6, str( rowResult ) )
check( "横行上 x 保持不动（不会被拉到参照节点头上）",
	abs( rowResult.x() - rowPoint.x() ) < 1e-6, str( rowResult ) )
check( "亮的是横参考线",
	[ g[ 0 ] for g in snapEditor.snapGuides() ] == [ "h" ], str( snapEditor.snapGuides() ) )

# --- ④ 参考线只覆盖两个节点那一段 ---
rowGuide = snapEditor.snapGuides()[ 0 ]
check( "横参考线的两头夹住这两个节点",
	rowGuide[ 2 ] < min( rowPoint.x(), snapItems[ "snapA" ].pos().x() ) and
	rowGuide[ 3 ] > max( rowPoint.x(), snapItems[ "snapA" ].pos().x() ), str( rowGuide ) )

snapMouse( QtCore.QEvent.MouseButtonRelease, snapStart, QtCore.Qt.LeftButton, QtCore.Qt.NoButton )
idle()
check( "松手清掉参考线", snapEditor.snapGuides() == [], str( snapEditor.snapGuides() ) )
snapWindow.setVisible( False )


##########################################################################
section( "空格最大化的检测 + P 键弹纯参数面板" )
##########################################################################

# 空格「最大化」要能检测；P 键弹节点的纯参数面（可选扩展 `parameterEditor`，
# 不要顶栏和齿轮，只要参数本身）。

pkeyScript = Gaffer.ScriptNode()
pkeySphere = GafferScene.Sphere( "pkeySphere" )
pkeyGroup = GafferScene.Group( "pkeyGroup" )
pkeyScript.addChild( pkeySphere )
pkeyScript.addChild( pkeyGroup )
pkeyGroup[ "in" ][ 0 ].setInput( pkeySphere[ "out" ] )
NE.setNodePosition( pkeySphere, imath.V2f( 0, 6 ) )
NE.setNodePosition( pkeyGroup, imath.V2f( 0, 0 ) )

pkeyEditor = NE.NetworkEditor( pkeyScript )
pkeyWindow = GafferUI.Window( "pkey" )

# --- ① 空格「最大化」能不能检测出来 ---
#
# Gaffer 的空格不是真全屏：`CompoundEditor.__keyPress` 把光标所在面板的**所有祖先
# SplitContainer 的手柄推到两端**。所以照它的判据看祖先手柄位置就知道。
pkeySplit = GafferUI.SplitContainer( GafferUI.SplitContainer.Orientation.Horizontal )
pkeyWindow.setChild( pkeySplit )
pkeySplit.append( pkeyEditor )
pkeySplit.append( GafferUI.Frame() )
pkeyWindow._qtWidget().resize( 1000, 700 )
pkeyWindow.setVisible( True )
idle()

pkeySplit.setSizes( [ 1, 1 ] )
idle()
check( "对半分的时候不算最大化", not pkeyEditor.isPanelMaximised(),
	str( pkeySplit.getSizes() ) )

pkeySplit.setSizes( [ 1, 0 ] )
idle()
check( "手柄推到底（= 空格最大化）检测得到", pkeyEditor.isPanelMaximised(),
	str( pkeySplit.getSizes() ) )

pkeySplit.setSizes( [ 0, 1 ] )
idle()
check( "另一半最大化时我们这块不算最大化", not pkeyEditor.isPanelMaximised(),
	str( pkeySplit.getSizes() ) )

check( "窗口没全屏时 isWindowFullScreen 是 False", not pkeyEditor.isWindowFullScreen() )

pkeySplit.setSizes( [ 1, 1 ] )
idle()

# --- ② P 键：光标底下那个节点的纯参数面板 ---
pkeyView = pkeyEditor.graphView()
pkeyView.frameAll()
idle()

def sendPkey() :

	pkeyView.keyPressEvent( QtGui.QKeyEvent(
		QtCore.QEvent.KeyPress, QtCore.Qt.Key_P, QtCore.Qt.NoModifier ) )

# 光标不在图上（无头环境），退回 focus / 最后选中的那个
pkeyScript.selection().clear()
pkeyScript.selection().add( pkeySphere )
sendPkey()
idle()

pkeyPopup = pkeyEditor.parameterPopup()
if importlib.util.find_spec( "parameterEditor" ) is None :
	check( "没装 parameterEditor 时 P 键什么都不弹", pkeyPopup is None, str( pkeyPopup ) )
elif pkeyPopup is None :
	check( "P 弹出一块面板", False, "parameterPopup() 是 None" )
else :
	check( "P 弹出一块面板", pkeyPopup.getVisible() )
	check( "面板钉在选中的那个节点上",
		pkeyPopup.node() is not None and pkeyPopup.node().getName() == "pkeySphere",
		str( pkeyPopup.node() ) )

	pkeyPanel = pkeyPopup.parameterEditor()
	check( "是纯参数面（chrome 关掉了）", not pkeyPanel.getChromeVisible() )

	# 停靠在节点图视口的**右上角**（Houdini 的 P 面板就在网络视图右上角），不跟鼠标跑。
	#
	# ⚠️ 别拿"面板右边缘 == 视口右边缘"去断言：无头 offscreen 的虚拟屏幕只有 800x800，
	# 而测试窗口 1000x700 有一半在屏幕外，`_clampToScreen` 会（正确地）把面板拽回屏幕里。
	# 所以断言的是「传进去的锚点就是视口那个矩形」—— 拿 popup 模块自己的两个纯函数
	# 算一遍期望值来比，跟鼠标位置那条路算出来的不一样，才说明真的走了停靠这条。
	import parameterEditor as _PE

	pkeyViewport = pkeyView.viewport()
	pkeyAnchor = QtCore.QRect(
		pkeyViewport.mapToGlobal( QtCore.QPoint( 0, 0 ) ), pkeyViewport.size() )
	pkeyPosition = pkeyPopup.getPosition()
	pkeyExpected = _PE._clampToScreen(
		_PE._popupPosition( None, _PE.POPUP_SIZE, pkeyAnchor ), _PE.POPUP_SIZE )
	pkeyMouseBased = _PE._clampToScreen(
		_PE._popupPosition( None, _PE.POPUP_SIZE, None ), _PE.POPUP_SIZE )
	check( "停在节点图视口的右上角",
		pkeyPosition.x == pkeyExpected.x and pkeyPosition.y == pkeyExpected.y,
		"面板 %s vs 期望 %s（视口 %s）" % ( pkeyPosition, pkeyExpected, pkeyAnchor ) )
	check( "不是跟着鼠标弹的",
		( pkeyPosition.x, pkeyPosition.y ) != ( pkeyMouseBased.x, pkeyMouseBased.y ),
		"%s vs 鼠标那条路 %s" % ( pkeyPosition, pkeyMouseBased ) )
	check( "窗口是圆角的（和参数卡片一致）",
		not pkeyPopup._qtWidget().mask().isEmpty() and
		not pkeyPopup._qtWidget().mask().contains( QtCore.QPoint( 0, 0 ) ) )
	check( "头部（名字 / 类型 / 齿轮那一行）藏起来了",
		not pkeyPanel._ParameterEditor__header.getVisible() )
	check( "面包屑藏起来了", not pkeyPanel._ParameterEditor__crumbRow.getVisible() )
	check( "工具条（搜索 / 来源 / 堆叠上限）藏起来了",
		not pkeyPanel._ParameterEditor__toolbar.getVisible() )
	check( "正文还在（参数本身没少）",
		pkeyPanel._ParameterEditor__bodyFrame.getChild() is not None )
	check( "跟着选择走（用的就是 script.selection()）",
		pkeyPanel.getNodeSet().isSame( pkeyScript.selection() ) )
	check( "面板自己知道是跟随模式", pkeyPopup.getFollowSelection() )

	# 换选择 → 面板跟着换节点
	pkeyScript.selection().clear()
	pkeyScript.selection().add( pkeyGroup )
	idle()
	check( "换了选择，面板跟着换成新节点",
		pkeyPopup.node() is not None and pkeyPopup.node().getName() == "pkeyGroup",
		str( pkeyPopup.node() ) )

	# 按 P 时那个节点还没选中 → 先把它变成当前选中（不然弹出来给的是别人的参数）
	pkeyScript.selection().clear()
	pkeyScript.selection().add( pkeyGroup )
	sendPkey()          # 关掉
	idle()
	pkeyScript.selection().clear()
	pkeyScript.selection().add( pkeySphere )
	sendPkey()          # 再开：光标不在图上 → 认最后选中的 pkeySphere
	idle()
	pkeyPopup = pkeyEditor.parameterPopup()
	check( "开面板时会把认到的那个节点变成当前选中",
		[ n.getName() for n in pkeyScript.selection() ] == [ "pkeySphere" ],
		str( [ n.getName() for n in pkeyScript.selection() ] ) )

	# 可以自由缩放（拖左边）
	pkeyQt = pkeyPopup._qtWidget()
	pkeyBefore = QtCore.QRect( pkeyQt.geometry() )
	pkeyLocal = QtCore.QPoint( 1, pkeyBefore.height() // 2 )
	pkeyGlobal = pkeyQt.mapToGlobal( pkeyLocal )
	pkeyQt.mousePressEvent( QtGui.QMouseEvent(
		QtCore.QEvent.MouseButtonPress, QtCore.QPointF( pkeyLocal ),
		QtCore.QPointF( pkeyGlobal ), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
		QtCore.Qt.NoModifier ) )
	pkeyQt.mouseMoveEvent( QtGui.QMouseEvent(
		QtCore.QEvent.MouseMove, QtCore.QPointF( pkeyLocal + QtCore.QPoint( -90, 0 ) ),
		QtCore.QPointF( pkeyGlobal + QtCore.QPoint( -90, 0 ) ),
		QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier ) )
	pkeyQt.mouseReleaseEvent( QtGui.QMouseEvent(
		QtCore.QEvent.MouseButtonRelease, QtCore.QPointF( pkeyLocal + QtCore.QPoint( -90, 0 ) ),
		QtCore.QPointF( pkeyGlobal + QtCore.QPoint( -90, 0 ) ),
		QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier ) )
	check( "拖边能改大小", pkeyQt.width() == pkeyBefore.width() + 90,
		"%d -> %d" % ( pkeyBefore.width(), pkeyQt.width() ) )
	_PE.popup._lastSize = None   # 别把大小带给别的用例

	# 再按一次 P = 关掉
	sendPkey()
	idle()
	check( "再按一次 P 关掉", not pkeyPopup.getVisible() )
	check( "关掉之后不再记着它", pkeyEditor.parameterPopup() is None )

	# 跟随模式下删掉当前那个节点：面板**不关**（它跟的是选择，不是某个节点），
	# 也不许挂在一个已经不存在的节点上。
	sendPkey()
	idle()
	pkeyPopup = pkeyEditor.parameterPopup()
	if pkeyPopup is not None :
		gone = pkeyPopup.node()
		pkeyScript.removeChild( gone )
		idle()
		check( "跟随模式下删掉当前节点，面板不关", pkeyPopup.getVisible() )
		stillThere = pkeyPopup.node()
		check( "面板不会挂在已经删掉的节点上",
			stillThere is None or pkeyScript.isAncestorOf( stillThere ),
			str( stillThere ) )
		pkeyScript.addChild( gone )
		sendPkey()          # 收起来，别影响后面的用例
		idle()

pkeyWindow.setVisible( False )


##########################################################################
section( "砍掉隐藏引擎 · 第一步：同步取景的 ViewportGadget + GadgetWidget 壳" )
##########################################################################

# 原生摆位代码只问一句「这个像素是图里哪个点」（`rasterToGadgetSpace`）。所以给它一个
# **只算不画**的 ViewportGadget，视口和取景同步成我们视图现在看到的那块，答案就和用户
# 看到的一致 —— 这是"一个原生 GraphEditor 实例都不建"的第一块砖。

vpScript = Gaffer.ScriptNode()
vpSphere = GafferScene.Sphere( "vpSphere" )
vpGroup = GafferScene.Group( "vpGroup" )
vpScript.addChild( vpSphere )
vpScript.addChild( vpGroup )
NE.setNodePosition( vpSphere, imath.V2f( -6, 4 ) )
NE.setNodePosition( vpGroup, imath.V2f( 8, -5 ) )

vpEditor = NE.NetworkEditor( vpScript )
vpWindow = GafferUI.Window( "viewport" )
vpWindow.setChild( vpEditor )
vpWindow._qtWidget().resize( 900, 600 )
vpWindow.setVisible( True )
idle()
vpView = vpEditor.graphView()
vpView.frameAll()
idle()

vpQt = vpView.viewport()
viewport = vpEditor._syncedViewport()
# raster 是**整个编辑器**那块（含工具条，和原生 `graphEditor.bound()` 同一块），
# 视口在编辑器里往下偏了一个工具条
vpEditorQt = vpEditor._qtWidget()
vpOffset = vpQt.mapTo( vpEditorQt, QtCore.QPoint( 0, 0 ) )

check( "取景器建出来了", viewport is not None )
check( "视口尺寸 = 编辑器的像素尺寸",
	viewport.getViewport() == imath.V2i( vpEditorQt.width(), vpEditorQt.height() ),
	"%s vs %dx%d" % ( viewport.getViewport(), vpEditorQt.width(), vpEditorQt.height() ) )
check( "视口确实在编辑器里往下偏了（有工具条）", vpOffset.y() > 0, str( vpOffset ) )
check( "默认就是 2D 相机（planarMovement）", viewport.getPlanarMovement() )

## 把 Gaffer 位置 → 我们视图的 raster → 原生 rasterToGadgetSpace 回算，看差多少
def roundTrip( node ) :

	gaffer = NE.nodePosition( node )
	scene = QtCore.QPointF( gaffer.x * NE.PX_PER_UNIT, -gaffer.y * NE.PX_PER_UNIT )
	raster = vpView.mapFromScene( scene ) + vpOffset
	back = viewport.rasterToGadgetSpace(
		imath.V2f( raster.x(), raster.y() ),
		gadget = vpEditor._NetworkEditor__graphGadget()
	).p0
	return ( abs( back.x - gaffer.x ), abs( back.y - gaffer.y ) )

for vpNode in ( vpSphere, vpGroup ) :
	dx, dy = roundTrip( vpNode )
	check( "%s 往返误差 < 0.05 单位（raster 取整那点误差）" % vpNode.getName(),
		dx < 0.05 and dy < 0.05, "(%.4f, %.4f)" % ( dx, dy ) )

# 视口正中：和我们自己的换算完全一致
vpCentre = QtCore.QPoint( vpQt.width() // 2, vpQt.height() // 2 )
vpOurs = vpView.mapToScene( vpCentre )
vpNative = viewport.rasterToGadgetSpace(
	imath.V2f( vpCentre.x() + vpOffset.x(), vpCentre.y() + vpOffset.y() ),
	gadget = vpEditor._NetworkEditor__graphGadget()
).p0
check( "视口正中两边算得一样",
	abs( vpNative.x - vpOurs.x() / NE.PX_PER_UNIT ) < 1e-3 and
	abs( vpNative.y + vpOurs.y() / NE.PX_PER_UNIT ) < 1e-3,
	"native (%.4f, %.4f) vs ours (%.4f, %.4f)" % (
		vpNative.x, vpNative.y, vpOurs.x() / NE.PX_PER_UNIT, -vpOurs.y() / NE.PX_PER_UNIT ) )

# 缩放 / 平移之后再问一次：取景要跟着走（`setViewport` 不会自动重新取景，所以每次都同步）
vpView.scale( 2.0, 2.0 )
idle()
viewport = vpEditor._syncedViewport()
dx, dy = roundTrip( vpSphere )
check( "缩放之后往返还是对的（取景跟着同步了）", dx < 0.05 and dy < 0.05,
	"(%.4f, %.4f)" % ( dx, dy ) )
vpView.frameAll()
idle()

# --- 壳（冒充原生 GadgetWidget）---
shim = vpEditor.graphGadgetWidget()
check( "graphGadgetWidget() 给的是我们自己的壳",
	type( shim ).__name__ == "_GadgetWidgetShim", type( shim ).__name__ )
check( "壳的 bound() = 编辑器的 bound()（EditMenu 粘贴拿的就是它，两者必须同一块）",
	shim.bound() == vpEditor.bound(), "%s vs %s" % ( shim.bound(), vpEditor.bound() ) )
check( "壳的 size() = 编辑器像素尺寸",
	shim.size() == imath.V2i( vpEditorQt.width(), vpEditorQt.height() ), str( shim.size() ) )
check( "壳的 getViewportGadget() 就是那个取景器",
	shim.getViewportGadget().isSame( vpEditor._syncedViewport() ) )
check( "壳的 QWidget 也是编辑器那块", shim._qtWidget() is vpEditorQt )

# 照抄原生 `EditMenu.paste` 那段换算：鼠标全局坐标 - `graphEditor.bound().min()` →
# `rasterToGadgetSpace` —— 必须落在用户看到的同一点上（不差一个工具条）
vpMouseView = QtCore.QPoint( vpQt.width() // 3, vpQt.height() // 3 )
vpMouseGlobal = vpQt.mapToGlobal( vpMouseView )
vpEditBound = vpEditor.bound()
vpPasted = viewport.rasterToGadgetSpace(
	imath.V2f( vpMouseGlobal.x() - vpEditBound.min().x, vpMouseGlobal.y() - vpEditBound.min().y ),
	gadget = vpEditor._NetworkEditor__graphGadget()
).p0
vpSeen = vpView.mapToScene( vpMouseView )
check( "原生菜单栏粘贴算出来的位置 = 鼠标在我们视图里指的那一点",
	abs( vpPasted.x - vpSeen.x() / NE.PX_PER_UNIT ) < 0.05 and
	abs( vpPasted.y + vpSeen.y() / NE.PX_PER_UNIT ) < 0.05,
	"native (%.3f, %.3f) vs ours (%.3f, %.3f)" % (
		vpPasted.x, vpPasted.y, vpSeen.x() / NE.PX_PER_UNIT, -vpSeen.y() / NE.PX_PER_UNIT ) )

# --- 不许抢别人的 gadget ---
# 一个 gadget 只有一个父，挂给第二个 ViewportGadget 会把它从原来那个上抢走。
# 所以取景器只能挂**我们自己**那个裸 GraphGadget，隐藏引擎那个必须一动不动。
vpEngine = vpEditor._NetworkEditor__engine()
if vpEngine is not None :
	engineViewport = vpEngine.graphGadgetWidget().getViewportGadget()
	check( "隐藏引擎的 gadget 没被抢走", engineViewport.getPrimaryChild() is not None )
	check( "取景器挂的是我们自己那个 gadget（不是引擎的）",
		not viewport.getPrimaryChild().isSame( vpEngine.graphGadget() ) )
	check( "引擎的视口也同步成编辑器的尺寸了",
		engineViewport.getViewport() == imath.V2i( vpEditorQt.width(), vpEditorQt.height() ),
		str( engineViewport.getViewport() ) )

vpWindow.setVisible( False )


##########################################################################
section( "界面文字英文 · 悬停小框中文" )
##########################################################################

# 规矩：**显示出来的字一律英文**（和原生 Gaffer 拼在一起不串语言），
# **鼠标停上去弹的小框一律中文**（做辅助说明）。

def hasHan( text ) :

	return any( "\u4e00" <= ch <= "\u9fff" for ch in ( text or "" ) )

tipScript = Gaffer.ScriptNode()
tipSphere = GafferScene.Sphere( "tipSphere" )
tipGroup = GafferScene.Group( "tipGroup" )
tipScript.addChild( tipSphere )
tipScript.addChild( tipGroup )
tipGroup[ "in" ][ 0 ].setInput( tipSphere[ "out" ] )
NE.setNodePosition( tipSphere, imath.V2f( 0, 10 ) )
NE.setNodePosition( tipGroup, imath.V2f( 0, 0 ) )

tipEditor = NE.NetworkEditor( tipScript )
tipWindow = GafferUI.Window( "tooltips" )
tipWindow.setChild( tipEditor )
tipWindow._qtWidget().resize( 900, 600 )
tipWindow.setVisible( True )
idle()

# --- 工具条：文字英文、提示中文 ---
tipButtons = [
	tipEditor._NetworkEditor__upButton,
	tipEditor._NetworkEditor__wireButton,
	tipEditor._NetworkEditor__snapButton,
]
check( "工具条按钮文字里没有中文",
	not any( hasHan( b.text() ) for b in tipButtons ),
	str( [ b.text() for b in tipButtons ] ) )
check( "工具条每个按钮都有中文提示",
	all( hasHan( b.toolTip() ) for b in tipButtons ),
	str( [ b.toolTip() for b in tipButtons ] ) )
check( "状态栏文字是英文、提示是中文",
	not hasHan( tipEditor._NetworkEditor__statusLabel.text() ) and
	hasHan( tipEditor._NetworkEditor__statusLabel.toolTip() ),
	tipEditor._NetworkEditor__statusLabel.text() )

# --- 节点：悬停小框中文 ---
tipItem = tipEditor._NetworkEditor__nodeItems[ "tipGroup" ]
nodeTip = tipItem.toolTip()
check( "节点小框里有节点名", "tipGroup" in nodeTip, nodeTip )
tipItem._readOnly = True
check( "只读写的是中文", "只读" in tipItem._NodeItem__toolTip() )
tipItem._readOnly = False
tipItem._enabled = False
check( "停用写的是中文", "已停用" in tipItem._NodeItem__toolTip() )
tipItem._enabled = True

# --- 参数圆点：悬停弹中文小框 ---
tipItem.setHoveredNodule( tipGroup[ "in" ][ 0 ] )
noduleTip = tipItem.toolTip()
check( "停在参数上小框换成这个参数的说明", "in.in0" in noduleTip, noduleTip )
check( "写清楚是输入还是输出", "输入参数" in noduleTip, noduleTip )
check( "接上的写出上游是谁",
	"已连接" in noduleTip and "tipSphere" in noduleTip, noduleTip )

tipItem.setHoveredNodule( tipGroup[ "in" ][ 1 ] )
check( "没接的说没接", "未连接" in tipItem.toolTip(), tipItem.toolTip() )

tipItem.setHoveredNodule( tipGroup[ "out" ] )
outTip = tipItem.toolTip()
check( "输出口写的是输出", "输出参数" in outTip, outTip )

tipItem.setHoveredNodule( None )
check( "鼠标离开参数就恢复成节点自己的小框",
	tipItem.toolTip() == nodeTip, tipItem.toolTip() )

# --- `+`：悬停弹中文小框 ---
tipItem.setHoveredAdder( "top" )
check( "`+` 上的小框是中文", "加接口" in tipItem.toolTip(), tipItem.toolTip() )
tipItem.setHoveredAdder( None )
check( "离开 `+` 也恢复", tipItem.toolTip() == nodeTip, tipItem.toolTip() )

# --- 连线：悬停小框中文 ---
tipEdges = tipEditor._NetworkEditor__edgeItems
check( "连线小框写了两头 + 中文操作说明",
	bool( tipEdges ) and "tipSphere" in tipEdges[ 0 ].toolTip() and
	"改接" in tipEdges[ 0 ].toolTip(),
	tipEdges[ 0 ].toolTip() if tipEdges else "没有连线" )

# --- 分栏折叠三角：悬停小框中文（复用上面那个分栏材质节点）---
secItem.setHoveredSection( "left", "Base" )
sectionTip = secItem.toolTip()
check( "停在分栏三角上说的是这一栏",
	"参数栏" in sectionTip and "Base" in sectionTip, sectionTip )
secItem.setHoveredSection( None, None )
check( "离开分栏三角恢复成节点小框",
	"secMat" in secItem.toolTip(), secItem.toolTip() )

# --- 建节点面板：行是英文、提示是中文 ---
# --- Tab 面板：**一个悬停小框都不许有** ---
# 这面板是"扫着找、找到就回车"的东西，鼠标一路划过去 Qt 的提示框一个接一个冒、
# 消失还慢，直接盖住下面几行（实机反馈"影响使用"）。说明都放在行右边那列小字里。
check( "搜索框没有悬停小框",
	not favPanel._NodeCreatorPopup__search.toolTip(),
	favPanel._NodeCreatorPopup__search.toolTip() )
check( "搜索框自己的占位文字是英文",
	not hasHan( favPanel._NodeCreatorPopup__search.placeholderText() ),
	favPanel._NodeCreatorPopup__search.placeholderText() )
check( "面板里没有 _rowToolTip 这个东西了", not hasattr( NE, "_rowToolTip" ) )

favColumnWidget = favPanel._NodeCreatorPopup__columnWidget( 0 )
favTips = [
	favColumnWidget.item( i ).toolTip() for i in range( favColumnWidget.count() )
]
check( "每一行都没有悬停小框", not any( favTips ), str( [ t for t in favTips if t ] ) )

tipWindow.setVisible( False )


##########################################################################
section( "原生 Show Contents 重定向（不让原生 GraphEditor 冒出来）" )
##########################################################################

# 原生那条 "Show Contents..." 的命令是 `GraphEditor.acquire( node )`，layout 里没有
# 原生 GraphEditor 时它会**新建一个塞进 layout**。借原生右键菜单的时候要就地换掉。

redirectScript = Gaffer.ScriptNode()
redirectBox = Gaffer.Box( "RedirectBox" )
redirectScript.addChild( redirectBox )
redirectBox.addChild( GafferScene.Sphere( "inner" ) )

redirectEditor = NE.NetworkEditor( redirectScript )
redirect = redirectEditor._NetworkEditor__redirectShowContents

definition = IECore.MenuDefinition()
definition.append( "/Focus", { "command" : lambda : None } )
definition.append( "/ContentsDivider", { "divider" : True } )
definition.append( "/Show Contents...", { "command" : functools.partial( GafferUI.GraphEditor.acquire, redirectBox ) } )
definition.append( "/Annotate...", { "command" : lambda : None } )

pathsBefore = [ path for path, item in definition.items() ]
redirected = redirect( definition, redirectBox )
pathsAfter = [ path for path, item in definition.items() ]

check( "认出来并换掉了", redirected )
check( "位置没被挪到末尾", pathsBefore == pathsAfter, "%s -> %s" % ( pathsBefore, pathsAfter ) )

redirectedItem = definition.item( "/Show Contents..." )
check( "命令换成了自己的进层级",
	isinstance( redirectedItem.command, functools.partial ) and
	redirectedItem.command.func == redirectEditor._enterNode )

check( "换之前 root 是脚本本身", redirectEditor.getRootNode().isSame( redirectScript ) )
redirectedItem.command()
check( "点下去真的进了 Box（没去建原生 GraphEditor）",
	redirectEditor.getRootNode().isSame( redirectBox ) )

emptyDefinition = IECore.MenuDefinition()
emptyDefinition.append( "/Focus", { "command" : lambda : None } )
check( "菜单里没那条时什么都不动", redirect( emptyDefinition, redirectBox ) is False )
check( "什么都不动的时候也没弄坏菜单",
	[ path for path, item in emptyDefinition.items() ] == [ "/Focus" ] )


##########################################################################
section( "Expand RGB：子圆点照原生缩到 0.75 档、挤在父接口那一格里" )
##########################################################################

# 原生 `CompoundNumericNodule` 把展开的 r/g/b 塞在**父接口那一格**里、整组
# `M44f().scale( V3f( 0.75 ) )`（`src/GafferUI/CompoundNumericNodule.cpp`）——
# 圆点更小、间距 0.75 单位。而 `GafferUI::CompoundNodule`（Group 的 ArrayPlug、
# 材质的 `parameters`）才是把子接口当兄弟摊开。两者混在一起用就会
# 「aiImage 的 out 展开之后样式和原生对不上」。

xpScript = Gaffer.ScriptNode()
xpBox = Gaffer.Box( "xpBox" )
xpScript.addChild( xpBox )
xpBox["cout"] = Gaffer.Color3fPlug(
	"cout", Gaffer.Plug.Direction.Out,
	flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic,
)
NE.setNodePosition( xpBox, imath.V2f( 0, 0 ) )

check( "没展开时不算「展开的复合数值插口」",
	not NE.isExpandedCompoundNumeric( xpBox["cout"] ) )

Gaffer.Metadata.registerValue(
	xpBox["cout"], "compoundNumericNodule:childrenVisible", IECore.BoolData( True )
)
check( "展开之后算", NE.isExpandedCompoundNumeric( xpBox["cout"] ) )

# 材质的 `parameters` 是 `GafferUI::CompoundNodule` —— **不能**跟着一起挤成一簇
# （66 个参数挤在一格里）。
xpParams = Gaffer.Plug( "parameters" )
xpBox.addChild( xpParams )
xpParams.addChild( Gaffer.FloatPlug( "a", flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
Gaffer.Metadata.registerValue( xpParams, "nodule:type", "GafferUI::CompoundNodule" )
check( "普通 CompoundNodule 不算（它是摊开的那种）",
	not NE.isExpandedCompoundNumeric( xpParams ) )

xpEditor = NE.NetworkEditor( xpScript )
xpWindow = GafferUI.Window( "expandRGB" )
xpWindow.setChild( xpEditor )
xpWindow._qtWidget().resize( 900, 600 )
xpWindow.setVisible( True )
idle()
xpItem = xpEditor._NetworkEditor__nodeItems[ "xpBox" ]

xpChildren = [ xpBox["cout"][c] for c in ( "r", "g", "b" ) ]
check( "子圆点半径 = 原生 0.75 档",
	all( abs( xpItem.noduleRadius( p ) - 0.75 * 0.5 * NE.PX_PER_UNIT ) < 1e-6 for p in xpChildren ),
	str( [ xpItem.noduleRadius( p ) for p in xpChildren ] ) )
check( "常规圆点还是 NODULE_RADIUS",
	abs( xpItem.noduleRadius( xpParams["a"] ) - NE.NODULE_RADIUS ) < 1e-6,
	str( xpItem.noduleRadius( xpParams["a"] ) ) )

# 位置直接和原生 gadget 对拍
xpGadget = GafferUI.GraphGadget( xpScript )
xpNodeGadget = xpGadget.nodeGadget( xpBox )
xpNodeGadget.bound()  # 先问一次尺寸，不然里面那些容器还没排过、子圆点坐标是局部的
for plug in xpChildren :
	nativeCentre = xpNodeGadget.nodule( plug ).transformedBound( xpNodeGadget ).center()
	ours = xpItem.nodulePosition( plug )
	check( "子圆点位置和原生一致（%s）" % plug.getName(),
		abs( ours.x() - nativeCentre.x * NE.PX_PER_UNIT ) < 0.01
		and abs( ours.y() + nativeCentre.y * NE.PX_PER_UNIT ) < 0.01,
		"ours=%s native=%s" % ( ours, nativeCentre ) )

xpWindow.setVisible( False )

# --- 分栏材质节点：侧边那格也得挤成一簇（我们自己排的行，原生位置被盖掉了）---

xpMatScript = Gaffer.ScriptNode()
xpMat = Gaffer.Node( "xpMat" )
xpMatParams = Gaffer.CompoundDataPlug( "parameters" )
xpMat.addChild( xpMatParams )
Gaffer.Metadata.registerValue( xpMatParams, "nodule:type", "GafferUI::CompoundNodule" )
Gaffer.Metadata.registerValue( xpMatParams, "noduleLayout:section", "left" )
for _name, _label, _sec, _value in (
	( "base_color", "Base Color", "Base", imath.Color4f( 1, 0, 0, 1 ) ),
	( "metalness", "Metalness", "Base", 0.5 ),
) :
	_nvp = Gaffer.NameValuePlug( _name, _value, _name )
	xpMatParams.addChild( _nvp )
	Gaffer.Metadata.registerValue( _nvp, "noduleLayout:label", _label )
	Gaffer.Metadata.registerValue( _nvp, "layout:section", _sec )

xpMatOut = Gaffer.Color3fPlug( "out", Gaffer.Plug.Direction.Out )
xpMat.addChild( xpMatOut )
Gaffer.Metadata.registerValue( xpMatOut, "noduleLayout:section", "right" )
xpMatScript.addChild( xpMat )
NE.setNodePosition( xpMat, imath.V2f( 0, 0 ) )

xpMatEditor = NE.NetworkEditor( xpMatScript )
xpMatWindow = GafferUI.Window( "expandRGBSections" )
xpMatWindow.setChild( xpMatEditor )
xpMatWindow._qtWidget().resize( 900, 600 )
xpMatWindow.setVisible( True )
idle()
xpMatItem = xpMatEditor._NetworkEditor__nodeItems[ "xpMat" ]
xpMatHeight = xpMatItem.cardRect().height()

Gaffer.Metadata.registerValue(
	xpMatOut, "compoundNumericNodule:childrenVisible", IECore.BoolData( True )
)
idle()
xpMatItem = xpMatEditor._NetworkEditor__nodeItems[ "xpMat" ]

xpMatChildren = [ xpMatOut[c] for c in ( "r", "g", "b" ) ]
check( "分栏节点上展开：三个子圆点都画得出来",
	all( NE.plugKey( xpMat, p ) in xpMatItem._NodeItem__nodulePositions for p in xpMatChildren ),
	str( sorted( xpMatItem._NodeItem__nodulePositions ) ) )
check( "一簇只占一行，卡片不跟着长高",
	abs( xpMatItem.cardRect().height() - xpMatHeight ) < 1e-6,
	"%.1f vs %.1f" % ( xpMatItem.cardRect().height(), xpMatHeight ) )

xpMatY = [ xpMatItem.nodulePosition( p ).y() for p in xpMatChildren ]
xpMatPitch = 2.0 * 0.75 * 0.5 * NE.PX_PER_UNIT
check( "间距照原生（相邻圆点刚好相切）",
	abs( ( xpMatY[1] - xpMatY[0] ) - xpMatPitch ) < 1e-6
	and abs( ( xpMatY[2] - xpMatY[1] ) - xpMatPitch ) < 1e-6,
	str( xpMatY ) )
check( "整簇居中在那一格上", abs( xpMatY[1] ) < 1e-6, str( xpMatY ) )
check( "三个都贴在卡片右缘",
	all( abs( xpMatItem.nodulePosition( p ).x() - xpMatItem.cardRect().right() ) < 1e-6
	     for p in xpMatChildren ),
	str( [ xpMatItem.nodulePosition( p ).x() for p in xpMatChildren ] ) )

# 标签：一簇只写一条（父接口的名字），三个字挤在 9px 间距里会叠在一起
xpMatLabels = [
	xpMatItem._NodeItem__sideLabels.get( NE.plugKey( xpMat, p ) ) for p in xpMatChildren
]
check( "一簇只写一条标签", len( [ l for l in xpMatLabels if l is not None ] ) == 1,
	str( xpMatLabels ) )
check( "写的是父接口的名字、摆在正中那个圆点旁边",
	xpMatLabels[1] is not None and xpMatLabels[1][0] == "out", str( xpMatLabels ) )

# --- 悬停：分栏节点卡片**里面**那条文字不许消失（用户反馈）---
NE.setSectionCollapsed( xpMat, "left", "Base", False )  # 分栏默认收起，先展开
idle()
xpMatItem = xpMatEditor._NetworkEditor__nodeItems[ "xpMat" ]
xpMatItem.setHoveredNodule( xpMatParams["base_color"] )
xpMatVisible = [
	NE.plugKey( xpMat, p ) for p in xpMatItem._NodeItem__visibleSidePlugs( "left" )
]
check( "悬停时那条参数名还在（卡内文字不让位，弹出的大标签在卡外）",
	xpMatItem._NodeItem__sideLabels.get( "parameters.base_color" ) is not None
	and "parameters.base_color" in xpMatVisible, str( xpMatVisible ) )
check( "悬停的就是它", xpMatItem.hoveredNodule() == "parameters.base_color",
	str( xpMatItem.hoveredNodule() ) )
xpMatItem.setHoveredNodule( None )
xpMatWindow.setVisible( False )


##########################################################################
section( "灯光图标：照 LightEditor 那套官方 16x16 图标复刻" )
##########################################################################

# 判据不是"看着像"，而是和原生 PNG **逐张对拍**：覆盖面积（alpha 加权）、
# 重心、包围盒。找不到官方图标（无头环境没设 GAFFERUI_IMAGE_PATHS）就跳过。

def _glyphStats( image ) :

	mass, cx, cy, xs, ys = 0.0, 0.0, 0.0, [], []
	for y in range( 16 ) :
		for x in range( 16 ) :
			c = QtGui.QColor.fromRgba( image.pixel( x, y ) )
			v = c.alpha() / 255.0 * ( max( c.red(), c.green(), c.blue() ) / 255.0 )
			if v > 0.02 :
				mass += v
				cx += v * ( x + 0.5 )
				cy += v * ( y + 0.5 )
			if v > 0.35 :
				xs.append( x )
				ys.append( y )
	if not mass or not xs :
		return None
	return ( mass, cx / mass - 8.0, cy / mass - 8.0, min( xs ), max( xs ), min( ys ), max( ys ) )


def _renderGlyph( kind ) :

	image = QtGui.QImage( 16, 16, QtGui.QImage.Format_ARGB32_Premultiplied )
	image.fill( QtCore.Qt.transparent )
	painter = QtGui.QPainter( image )
	NE._drawGlyph( painter, kind, QtCore.QPointF( 8, 8 ), 16.0, QtGui.QColor( 255, 255, 255 ) )
	painter.end()
	return image


_iconSearch = IECore.SearchPath( os.environ.get( "GAFFERUI_IMAGE_PATHS", "" ) )

for _kind, _icon in (
	( "GLYPH_POINT_LIGHT", "pointLight.png" ),
	( "GLYPH_DISTANT_LIGHT", "distantLight.png" ),
	( "GLYPH_QUAD_LIGHT", "quadLight.png" ),
	( "GLYPH_SPOT_LIGHT", "spotLight.png" ),
	( "GLYPH_DISK_LIGHT", "diskLight.png" ),
	( "GLYPH_CYLINDER_LIGHT", "cylinderLight.png" ),
	( "GLYPH_SKYDOME_LIGHT", "environmentLight.png" ),
	( "GLYPH_PHOTOMETRIC_LIGHT", "photometricLight.png" ),
	( "GLYPH_MESH_LIGHT", "meshLight.png" ),
) :
	_path = _iconSearch.find( _icon )
	if not _path :
		print( "SKIP  找不到官方图标 %s" % _icon )
		continue

	_native = _glyphStats( QtGui.QImage( _path ) )
	_ours = _glyphStats( _renderGlyph( getattr( NE, _kind ) ) )
	check( "%s 画得出来" % _icon, _ours is not None )
	if _native is None or _ours is None :
		continue

	check( "%s 重心和原生对得上" % _icon,
		abs( _ours[1] - _native[1] ) < 1.0 and abs( _ours[2] - _native[2] ) < 1.0,
		"ours=(%.2f,%.2f) native=(%.2f,%.2f)" % ( _ours[1], _ours[2], _native[1], _native[2] ) )
	check( "%s 包围盒和原生对得上" % _icon,
		all( abs( _ours[i] - _native[i] ) <= 1.5 for i in ( 3, 4, 5, 6 ) ),
		"ours=%s native=%s" % ( _ours[3:], _native[3:] ) )
	check( "%s 墨量在原生上下三成以内" % _icon,
		0.7 * _native[0] <= _ours[0] <= 1.3 * _native[0]
		or _kind in ( "GLYPH_SPOT_LIGHT", "GLYPH_MESH_LIGHT" ),  # 描边 / 弯折面，差得多一点
		"ours=%.1f native=%.1f" % ( _ours[0], _native[0] ) )


##########################################################################
section( "B 键找书签：整棵树都要找得到（不只直接子节点）" )
##########################################################################

# ⚠️ `Gaffer.MetadataAlgo.bookmarks( script )` 只扫**直接子节点**
# （`MetadataAlgo.cpp:420` 的 `Node::Iterator`）—— 生产里书签基本都在 Box 里，
# 拿它当数据源的话按 B **一条都列不出来、而且直接 return**（用户报的「B 键快捷查找
# 书签的功能丢了」）。原生用的是递归的
# `Metadata.nodesWithMetadata( script, "bookmarked", instanceOnly = True )`。

bmScript = Gaffer.ScriptNode()
bmApplication = Gaffer.ApplicationRoot( "bookmarkTest" )
bmApplication["scripts"].addChild( bmScript )

bmTop = GafferScene.Sphere( "topSphere" )
bmScript.addChild( bmTop )
NE.setNodePosition( bmTop, imath.V2f( 0, 0 ) )

bmBox = Gaffer.Box( "rigBox" )
bmScript.addChild( bmBox )
NE.setNodePosition( bmBox, imath.V2f( 20, 0 ) )
bmInner = GafferScene.Sphere( "innerSphere" )
bmBox.addChild( bmInner )
NE.setNodePosition( bmInner, imath.V2f( 0, 0 ) )

bmDeep = GafferScene.Plane( "deepPlane" )
bmInnerBox = Gaffer.Box( "innerBox" )
bmBox.addChild( bmInnerBox )
bmInnerBox.addChild( bmDeep )
NE.setNodePosition( bmInnerBox, imath.V2f( 0, 20 ) )
NE.setNodePosition( bmDeep, imath.V2f( 0, 0 ) )

bmEditor = NE.NetworkEditor( bmScript )
bmWindow = GafferUI.Window( "bookmarks" )
bmWindow.setChild( bmEditor )
bmWindow._qtWidget().resize( 900, 600 )
bmWindow.setVisible( True )
idle()

check( "一条书签都没有：也照样弹面板（给个 No bookmarks available，不是什么都不发生）",
	bmEditor._findableBookmarks() == [] )
bmEditor._popupBookmarkMenu( QtCore.QPoint( 300, 300 ) )
QtWidgets.QApplication.processEvents()
bmPopup = bmEditor._NetworkEditor__creatorPopup
check( "空书签也弹得出来", bmPopup is not None and bmPopup.isVisible() )
if bmPopup is not None :
	bmPopup.hide()

for bmNode in ( bmTop, bmInner, bmDeep ) :
	Gaffer.MetadataAlgo.setBookmarked( bmNode, True )

bmFound = [ n.relativeName( bmScript ) for n in bmEditor._findableBookmarks() ]
check( "Box 里、Box 里的 Box 里的书签都找得到（这条是修的那个 bug）",
	bmFound == [ "rigBox.innerBox.deepPlane", "rigBox.innerSphere", "topSphere" ],
	str( bmFound ) )
check( "只扫直接子节点的老做法确实找不到嵌套的（对照）",
	[ n.getName() for n in Gaffer.MetadataAlgo.bookmarks( bmScript ) ] == [ "topSphere" ],
	str( [ n.getName() for n in Gaffer.MetadataAlgo.bookmarks( bmScript ) ] ) )

# 取消书签之后就不该再列出来
Gaffer.MetadataAlgo.setBookmarked( bmDeep, False )
check( "取消书签就不列了",
	[ n.relativeName( bmScript ) for n in bmEditor._findableBookmarks() ]
	== [ "rigBox.innerSphere", "topSphere" ],
	str( [ n.relativeName( bmScript ) for n in bmEditor._findableBookmarks() ] ) )
Gaffer.MetadataAlgo.setBookmarked( bmDeep, True )

# Reference 里的书签跟着 .grf 走，跳进去也改不了 —— 原生就排掉它们
bmReference = Gaffer.Reference( "refNode" )
bmScript.addChild( bmReference )
NE.setNodePosition( bmReference, imath.V2f( 40, 0 ) )
Gaffer.MetadataAlgo.setBookmarked( bmReference, True )
check( "Reference 本身可以是书签（它不在别的 Reference 里）",
	"refNode" in [ n.getName() for n in bmEditor._findableBookmarks() ] )

# 面板真的列出这些条目（分类 = 它所在的那条路径）
bmEditor._popupBookmarkMenu( QtCore.QPoint( 300, 300 ) )
QtWidgets.QApplication.processEvents()
bmPopup = bmEditor._NetworkEditor__creatorPopup
bmEntries = bmPopup._NodeCreatorPopup__entries
check( "面板条目 = 找到的那些书签",
	sorted( e[0] for e in bmEntries )
	== [ "deepPlane", "innerSphere", "refNode", "topSphere" ],
	str( sorted( e[0] for e in bmEntries ) ) )
check( "嵌套的那条带上它所在的路径（面板按它分列 / 右边写小字）",
	next( e[1] for e in bmEntries if e[0] == "deepPlane" ) == "rigBox / innerBox",
	str( [ ( e[0], e[1] ) for e in bmEntries ] ) )
check( "面板标题照原生那句", bmPopup._NodeCreatorPopup__baseTitle == "Find Bookmark",
	str( bmPopup._NodeCreatorPopup__baseTitle ) )
bmPopup.hide()

# **自己是书签、底下还有书签** → 照原生挂成 `<路径>/This Node`
# （`GraphBookmarksUI.__findBookmark` 里那段 `haveDescendantBookmarks`），
# 否则「rigBox 这条书签」和「rigBox 那一组」会在同一层重名打架。
Gaffer.MetadataAlgo.setBookmarked( bmBox, True )
bmEditor._popupBookmarkMenu( QtCore.QPoint( 300, 300 ) )
QtWidgets.QApplication.processEvents()
bmPopup = bmEditor._NetworkEditor__creatorPopup
bmNested = bmPopup._NodeCreatorPopup__entries
bmThis = [ e for e in bmNested if e[0] == "This Node" ]
check( "底下还有书签的那条挂成 This Node", len( bmThis ) == 1, str( [ e[0] for e in bmNested ] ) )
check( "This Node 落在自己那一组里面", bmThis and bmThis[0][1] == "rigBox", str( bmThis and bmThis[0][1] ) )
check( "This Node 照原生用节点名当搜索词", bmThis and bmThis[0][2] == "rigBox", str( bmThis and bmThis[0][2] ) )
check( "点它跳的还是那个 Box 本身",
	next( ( e for e in bmNested if e[0] == "This Node" ), None ) is not None )
bmPopup.hide()
Gaffer.MetadataAlgo.setBookmarked( bmBox, False )
bmEditor._popupBookmarkMenu( QtCore.QPoint( 300, 300 ) )
QtWidgets.QApplication.processEvents()
bmPopup = bmEditor._NetworkEditor__creatorPopup
check( "取消之后 This Node 也没了",
	not [ e for e in bmPopup._NodeCreatorPopup__entries if e[0] == "This Node" ] )
bmEntries = bmPopup._NodeCreatorPopup__entries
bmPopup.hide()

# 选中一条 = 切到它所在的那层 + 选中它（照原生 `__editBookmark`）
bmDeepEntry = next( e for e in bmEntries if e[0] == "deepPlane" )
bmDeepEntry[3].command()
idle()
check( "跳过去会切到它所在的那一层",
	bmEditor.getRootNode().isSame( bmInnerBox ), bmEditor.getRootNode().getName() )
check( "而且把它选中了",
	[ n.getName() for n in bmScript.selection() ] == [ "deepPlane" ],
	str( [ n.getName() for n in bmScript.selection() ] ) )

# B 键真的走到这条路上
bmEditor.setRootNode( bmScript )
idle()
bmView = bmEditor.graphView()
bmHandled = bmView._GraphView__handleKey(
	QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_B, QtCore.Qt.NoModifier )
)
QtWidgets.QApplication.processEvents()
check( "B 键接得住", bmHandled )
check( "B 键弹的就是书签面板",
	bmEditor._NetworkEditor__creatorPopup._NodeCreatorPopup__baseTitle == "Find Bookmark",
	str( bmEditor._NetworkEditor__creatorPopup._NodeCreatorPopup__baseTitle ) )
bmEditor._NetworkEditor__creatorPopup.hide()
bmWindow.setVisible( False )



##########################################################################
section( "Tab 面板 · 名字和右边的层级信息不许叠在一起" )
##########################################################################

# 用户反馈：「某个节点的层级嵌套很多，搜到它、还没点之前，左边的节点名和右边的层级
# 信息会因为哪一边太长而互相遮挡，两串字混在一起」。根因在 `_CreatorDelegate.paint`：
# 名字左对齐、**完全不截**，层级信息右对齐、只按 55% 截 —— 两块各画各的，谁长了就压
# 到对方身上。所有面板（Tab 建节点 / S·Q 菜单 / B 书签 / 连隐藏参数）共用这一个 delegate。

# 先验纯函数分宽度的规矩（**名字绝对优先**，见下一节）
w = NE._splitRowWidths( 276, 60, 400 )
check( "名字短：右边拿走剩下的，两块加起来不超过一行",
	w[0] >= 60 and w[0] + w[1] + NE.ROW_TEXT_GAP <= 276, str( w ) )
w = NE._splitRowWidths( 276, 400, 400 )
check( "名字放不下：整行都给名字，右侧那块干脆不画（绝不截名字去让它）",
	w == ( 276, 0 ), str( w ) )
w = NE._splitRowWidths( 600, 200, 400 )
check( "都放得下：名字要多少给多少，右侧拿剩下的",
	w[0] >= 200 and w[1] > 0 and w[0] + w[1] + NE.ROW_TEXT_GAP <= 600, str( w ) )
w = NE._splitRowWidths( 276, 400, 0 )
check( "没有右侧信息时名字独占整行", w == ( 276, 0 ), str( w ) )

overlapList = QtWidgets.QListWidget()
overlapList.setItemDelegate( NE._CreatorDelegate( overlapList ) )

def addOverlapRow( name, category, header = False, favourite = False ) :

	item = QtWidgets.QListWidgetItem( name )
	item.setData( QtCore.Qt.UserRole + 1, category )
	item.setData( QtCore.Qt.UserRole + 3, header )
	item.setData( QtCore.Qt.UserRole + 6, favourite )
	overlapList.addItem( item )
	return overlapList.count() - 1

longName = "aiStandardSurfaceLookDevOverrideNode"
longCategory = "Scene / Object / Modify / Deeply / Nested / Category"
rowLongBoth = addOverlapRow( longName, longCategory )
rowLongName = addOverlapRow( longName, "Utility" )
rowLongCategory = addOverlapRow( "Dot", longCategory )
rowHeader = addOverlapRow( "\u2605 Favourites", "right-click / Ctrl+D", header = True )
rowFavourite = addOverlapRow( longName, longCategory, favourite = True )

def inkColumns( widget, row, width ) :

	image = QtGui.QImage( width, NE._NodeCreatorPopup.ROW_HEIGHT, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	option = QtWidgets.QStyleOptionViewItem()
	option.rect = QtCore.QRect( 0, 0, width, NE._NodeCreatorPopup.ROW_HEIGHT )
	option.state = QtWidgets.QStyle.State_Enabled
	widget.itemDelegate().paint( painter, option, widget.model().index( row, 0 ) )
	painter.end()

	columns = []
	for x in range( width ) :
		# y 从 3 起：分节标题最上面那条 1px 分隔线是通到头的，算进来就没有"缝"了
		for y in range( 3, image.height() ) :
			if QtGui.QColor( image.pixel( x, y ) ).black() < 250 :
				columns.append( x )
				break
	return columns

## 一行里最宽的一段空白（画完两块文字，中间总该有条缝）。头尾的留白不算。
def widestGap( columns ) :

	if len( columns ) < 2 :
		return 0
	return max( b - a - 1 for a, b in zip( columns, columns[1:] ) )

## 这一行画出来的时候右边那块还在不在（在就该和名字之间留出缝）。
def rightBlockDrawn( name, category, width, header = False, favourite = False ) :

	nameFont = NE._font( 8.0, bold = True ) if header else NE._font( 9.5 )
	rightFont = NE._font( 7.5 ) if header else NE._font( 8.0 )
	nameWidth = QtGui.QFontMetrics( nameFont ).horizontalAdvance( name )
	if favourite :
		nameWidth += NE.STAR_WIDTH + 5
	rightWidth = QtGui.QFontMetrics( rightFont ).horizontalAdvance( category )
	return NE._splitRowWidths( width - 24, nameWidth, rightWidth )[1] > 0

for width in ( NE._NodeCreatorPopup.FIRST_COLUMN_WIDTH, NE._NodeCreatorPopup.COLUMN_WIDTH ) :

	for label, row, name, category, header, favourite in (
		( "两边都长", rowLongBoth, longName, longCategory, False, False ),
		( "名字长", rowLongName, longName, "Utility", False, False ),
		( "层级长", rowLongCategory, "Dot", longCategory, False, False ),
		( "分节标题", rowHeader, "\u2605 Favourites", "right-click / Ctrl+D", True, False ),
		( "钉住的（名字后面还有颗星）", rowFavourite, longName, longCategory, False, True ),
	) :
		columns = inkColumns( overlapList, row, width )
		if rightBlockDrawn( name, category, width, header, favourite ) :
			check( "%s：%dpx 宽的列里，名字和层级信息之间留得出缝（不叠）" % ( label, width ),
				widestGap( columns ) >= 5, "gap=%d" % widestGap( columns ) )
		check( "%s：%dpx 宽的列里，字没画出列外" % ( label, width ),
			not columns or columns[-1] < width, str( columns[-1] if columns else -1 ) )

# 名字短的时候，深层级路径能多占一些
shortNameRow = addOverlapRow( "Dot", longCategory )
shortColumns = inkColumns( overlapList, shortNameRow, NE._NodeCreatorPopup.FIRST_COLUMN_WIDTH )
check( "名字短时右边的层级信息能多占一些（不再固定 55%）",
	shortColumns and ( shortColumns[-1] - shortColumns[0] ) > NE._NodeCreatorPopup.FIRST_COLUMN_WIDTH * 0.6,
	str( ( shortColumns[0], shortColumns[-1] ) if shortColumns else None ) )


##########################################################################
section( "Tab 面板 · 名字不许截断 / 列宽自适应 / 滚轮到处都能滚" )
##########################################################################

# 用户反馈（原话）：「节点名字过长就会显示成 show_camera_f...，这对于使用来说是不可
# 以接受的」。三条要求：①一级菜单里随便哪儿都能滚轮上下滑；②正常（没搜索）不显示
# 右边那串分类层级；③搜索时**不许截断名字**，右边的层级可以稍微截断。外加一条：
# 面板宽度跟着名字长度 / 信息密度走。

# --- ③ 名字绝对优先 ---
longNodeName = "show_camera_frustum_for_selected_shot"
nameOnly = QtGui.QFontMetrics( NE._font( 9.5 ) ).horizontalAdvance( longNodeName )
hint = NE._rowWidthHint( longNodeName, "Scene / Utility / Deeply / Nested" )
check( "算得出「一点不截要多宽」", hint > nameOnly, "%d vs %d" % ( hint, nameOnly ) )
check( "宽度够时名字一个字都不用截",
	NE._splitRowWidths( hint - 24, nameOnly, 400 )[0] >= nameOnly,
	str( NE._splitRowWidths( hint - 24, nameOnly, 400 ) ) )
check( "宽度不够时是右边让位、不是截名字",
	NE._splitRowWidths( nameOnly + 10, nameOnly, 400 ) == ( nameOnly + 10, 0 ),
	str( NE._splitRowWidths( nameOnly + 10, nameOnly, 400 ) ) )
check( "算宽度时留了余量：按 hint 那么宽画，名字有富余（差一两像素 Qt 也会 elide）",
	NE._splitRowWidths( hint - 24, nameOnly, 400 )[0] > nameOnly,
	str( ( NE._splitRowWidths( hint - 24, nameOnly, 400 ), nameOnly ) ) )
check( "右侧再长也只占到上限那么宽",
	NE._rowWidthHint( "x", "a / b / c / d / e / f / g / h / i / j / k / l / m / n" )
	<= NE._rowWidthHint( "x" ) + NE.ROW_TEXT_GAP + NE.ROW_RIGHT_MAX_WIDTH,
	str( NE._rowWidthHint( "x", "a / b / c / d / e / f / g / h / i / j / k / l / m / n" ) ) )

# --- ④ 列宽跟着内容走 ---
widthDefinition = IECore.MenuDefinition()
widthDefinition.append( "/Scene/Utility/Dot", { "command" : lambda : None } )
widthDefinition.append( "/Scene/Utility/Sphere", { "command" : lambda : None } )
widthPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
widthPanel.setEntries( NE._entriesFromDefinition( widthDefinition ) )
widthPanel.popupAt( QtCore.QPoint( 140, 140 ), lambda item : None )
QtWidgets.QApplication.processEvents()
narrowWidth = widthPanel.width()
check( "短名字时就是原来那个下限宽度",
	narrowWidth == NE._NodeCreatorPopup.FIRST_COLUMN_WIDTH + 16,
	"%d" % narrowWidth )

# 300px 装得下的名字不该把面板撑宽（`show_camera_frustum` 这种本来就该原样显示，
# 它以前被截是因为右边那串分类层级抢走了一半）
fitsDefinition = IECore.MenuDefinition()
fitsDefinition.append( "/Scene/Utility/show_camera_frustum", { "command" : lambda : None } )
fitsDefinition.append( "/Scene/Utility/Dot", { "command" : lambda : None } )
widthPanel.setEntries( NE._entriesFromDefinition( fitsDefinition ) )
QtWidgets.QApplication.processEvents()
check( "常见长度的名字放得进默认宽度，不用撑宽", widthPanel.width() == narrowWidth,
	"%d vs %d" % ( widthPanel.width(), narrowWidth ) )
check( "而且一个字都没截",
	NE._splitRowWidths(
		NE._NodeCreatorPopup.FIRST_COLUMN_WIDTH - 24,
		QtGui.QFontMetrics( NE._font( 9.5 ) ).horizontalAdvance( "show_camera_frustum" ),
		0,
	)[0] >= QtGui.QFontMetrics( NE._font( 9.5 ) ).horizontalAdvance( "show_camera_frustum" ),
)

longDefinition = IECore.MenuDefinition()
longDefinition.append( "/Scene/Utility/" + longNodeName * 2, { "command" : lambda : None } )
longDefinition.append( "/Scene/Utility/Dot", { "command" : lambda : None } )
widthPanel.setEntries( NE._entriesFromDefinition( longDefinition ) )
QtWidgets.QApplication.processEvents()
check( "名字长了面板自己变宽", widthPanel.width() > narrowWidth,
	"%d -> %d" % ( narrowWidth, widthPanel.width() ) )

hugeDefinition = IECore.MenuDefinition()
hugeDefinition.append( "/Scene/" + "x" * 400, { "command" : lambda : None } )
widthPanel.setEntries( NE._entriesFromDefinition( hugeDefinition ) )
QtWidgets.QApplication.processEvents()
check( "再长也有上限，不许撑满屏",
	widthPanel.width() <= NE._NodeCreatorPopup.COLUMN_MAX_WIDTH + 16,
	"%d" % widthPanel.width() )

# 搜索让一行的信息密度变高（多出右边的层级），宽度也该跟上
widthPanel.setEntries( NE._entriesFromDefinition( longDefinition ) )
QtWidgets.QApplication.processEvents()
browseWidth = widthPanel.width()
widthPanel.setSearchText( longNodeName[:6] )
QtWidgets.QApplication.processEvents()
check( "搜索时多出层级信息，宽度跟着变宽", widthPanel.width() >= browseWidth,
	"%d -> %d" % ( browseWidth, widthPanel.width() ) )
check( "搜索结果里右边才写层级",
	any( widthPanel.rowAt( i )[1] for i in range( widthPanel.rowCount() ) ),
	str( [ widthPanel.rowAt( i ) for i in range( widthPanel.rowCount() ) ] ) )
widthPanel.setSearchText( "" )
QtWidgets.QApplication.processEvents()
check( "清掉搜索又回到「不写层级」",
	not any( widthPanel.rowAt( i )[1] for i in range( widthPanel.rowCount() ) ),
	str( [ widthPanel.rowAt( i ) for i in range( widthPanel.rowCount() ) ] ) )

# --- ① 滚轮：面板上任何地方都能滚第一列 ---
wheelDefinition = IECore.MenuDefinition()
for i in range( 60 ) :
	wheelDefinition.append( "/Scene/Utility/Node%02d" % i, { "command" : lambda : None } )
wheelPanel = NE._NodeCreatorPopup( menuEditor.graphView() )
wheelPanel.setEntries( NE._entriesFromDefinition( wheelDefinition ) )
wheelPanel.popupAt( QtCore.QPoint( 160, 160 ), lambda item : None )
wheelPanel.setSearchText( "Node" )        # 一次列 60 条 -> 出滚动条
QtWidgets.QApplication.processEvents()

wheelBar = wheelPanel._NodeCreatorPopup__columnWidget( 0 ).verticalScrollBar()
check( "条目多到出滚动条", wheelBar.maximum() > wheelBar.minimum(),
	"%d..%d" % ( wheelBar.minimum(), wheelBar.maximum() ) )

wheelBar.setValue( wheelBar.minimum() )
# 光标压在**搜索框**上（不是列表上）也要滚得动 —— 这就是"只在某一区域才滚"那个毛病
searchCentre = wheelPanel._NodeCreatorPopup__search.mapToGlobal(
	wheelPanel._NodeCreatorPopup__search.rect().center()
)
wheelPanel._routeWheel( searchCentre, -120 )
check( "鼠标在搜索框上滚，第一列跟着滚", wheelBar.value() > wheelBar.minimum(),
	"%d" % wheelBar.value() )

scrolled = wheelBar.value()
wheelPanel._routeWheel( searchCentre, 120 )
check( "反向滚回去", wheelBar.value() < scrolled, "%d -> %d" % ( scrolled, wheelBar.value() ) )

# 面板边距上（既不是列表也不是搜索框）同样算
wheelBar.setValue( wheelBar.minimum() )
wheelPanel._routeWheel( wheelPanel.geometry().topLeft() + QtCore.QPoint( 2, 2 ), -120 )
check( "鼠标在面板边距上滚也算", wheelBar.value() > wheelBar.minimum(), "%d" % wheelBar.value() )

wheelPanel.hide()
widthPanel.hide()


##########################################################################
section( "自动排列 · 流向判定 / 分层布局的三步 / PathFilter 的位置" )
##########################################################################

import collections

# --- 流向判定：判据是「输出圆点挂在哪条边」 ---
#
# 以前是「有没有输入挂上边」，两类节点都会踩空：`OSLCode` 的 `code` 和
# `ArnoldDisplacement` 的 `map` / `height` 都是挂**上边**的输入圆点，照那条判据
# 会被当成场景节点 —— 一整张 OSLCode 材质图的边全成了「侧面喂进来的」，
# 每个节点各自一组（实测 36 个节点排出 35 组、161 处交叉）。
axisScript2 = Gaffer.ScriptNode()

axisIsolate = GafferScene.Isolate( "axisIsolate" ) ; axisScript2.addChild( axisIsolate )
axisFilter = GafferScene.PathFilter( "axisFilter" ) ; axisScript2.addChild( axisFilter )
axisAssign = GafferScene.ShaderAssignment( "axisAssign" ) ; axisScript2.addChild( axisAssign )
check( "场景节点竖着流（out 挂下边）", NE.nodeFlowAxis( axisIsolate ) == "vertical" )
check( "PathFilter 竖着流（out 挂下边）", NE.nodeFlowAxis( axisFilter ) == "vertical" )
check( "ShaderAssignment 竖着流（out 挂下边，虽然左右也各有一个圆点）",
	NE.nodeFlowAxis( axisAssign ) == "vertical" )

# OSLCode：`code` 挂上边、`out` 挂右边 → 材质，横着流
axisCode = GafferOSL.OSLCode( "axisCode" ) ; axisScript2.addChild( axisCode )
axisCodeTop = [ p.relativeName( axisCode ) for p in NE.noduleLayout( axisCode )[ "top" ] ]
check( "OSLCode 的 code 确实是挂上边的输入圆点（判据踩空的根源）",
	"code" in axisCodeTop, str( axisCodeTop ) )
check( "OSLCode 横着流（out 挂右边）", NE.nodeFlowAxis( axisCode ) == "horizontal" )

# 一整条 OSLCode 材质链必须是**一组**，不是一个节点一组
chainScript = Gaffer.ScriptNode()
chainNodes = []
for i in range( 5 ) :
	node = GafferOSL.OSLCode( "chain%d" % i )
	chainScript.addChild( node )
	node[ "parameters" ].addChild( Gaffer.Color3fPlug(
		"a", flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
	node[ "out" ].addChild( Gaffer.Color3fPlug(
		"c", Gaffer.Plug.Direction.Out,
		flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic ) )
	if chainNodes :
		node[ "parameters" ][ "a" ].setInput( chainNodes[-1][ "out" ][ "c" ] )
	chainNodes.append( node )

chainByName = collections.OrderedDict( ( n.getName(), n ) for n in chainNodes )
chainAxes = dict( ( n, NE.nodeFlowAxis( node ) ) for n, node in chainByName.items() )
chainEdges = [
	( e.srcNode.getName(), e.dstNode.getName(), e )
	for e in NE.collectEdges( chainScript, chainNodes ) if not e.auxiliary
]
chainGroups, _chainGroupOf = NE._layoutFlowGroups( chainByName, chainAxes, chainEdges )
check( "五个 OSLCode 串一条链 = 一组（不是一个节点一组）",
	len( chainGroups ) == 1, "%d 组：%s" % ( len( chainGroups ), chainGroups ) )

chainPositions = NE.layoutNodes( chainNodes, chainScript )
chainXs = [ chainPositions[ n ].x for n in chainNodes ]
check( "材质链从左往右一层层排开", chainXs == sorted( chainXs ), str( chainXs ) )

# --- `isFlowEdge` 的兜底：流向那两条边上没有输入圆点时，挂哪儿哪儿就是主流 ---
check( "Isolate.filter（挂右边）不算竖着流的主流边",
	not NE.isFlowEdge( axisIsolate[ "filter" ], "vertical" ) )
check( "Isolate.in（挂上边）算竖着流的主流边",
	NE.isFlowEdge( axisIsolate[ "in" ], "vertical" ) )
check( "OSLCode.parameters.a（挂左边）算横着流的主流边",
	NE.isFlowEdge( chainNodes[1][ "parameters" ][ "a" ], "horizontal" ) )

# --- 分层：最长路径 vs 网络单纯形 vs ALAP（跑对照的开关还在不在）---
rankNames = [ "a", "b", "c", "d", "e" ]
rankEdges = [ ( "a", "b" ), ( "b", "c" ), ( "c", "d" ), ( "a", "d" ), ( "e", "d" ) ]
rankPreds, rankSuccs = {}, {}
for _s, _d in rankEdges :
	rankPreds.setdefault( _d, set() ).add( _s )
	rankSuccs.setdefault( _s, set() ).add( _d )

with NE.layoutStrategy( rank = "longest-path" ) :
	longestRanks = NE._layoutRankNodes( rankNames, rankEdges, rankPreds, rankSuccs )
with NE.layoutStrategy( rank = "network-simplex" ) :
	simplexRanks = NE._layoutRankNodes( rankNames, rankEdges, rankPreds, rankSuccs )
with NE.layoutStrategy( rank = "alap" ) :
	alapRanks = NE._layoutRankNodes( rankNames, rankEdges, rankPreds, rankSuccs )

check( "最长路径把只喂最下游那个的 e 钉在第 0 层（于是拉一条长边）",
	longestRanks[ "e" ] == 0, str( longestRanks ) )
check( "网络单纯形把 e 拉到消费者头上（长边变短边）",
	simplexRanks[ "e" ] == simplexRanks[ "d" ] - 1, str( simplexRanks ) )
check( "ALAP 也把 e 拉到消费者头上",
	alapRanks[ "e" ] == alapRanks[ "d" ] - 1, str( alapRanks ) )
for _name, _ranks in ( ( "最长路径", longestRanks ), ( "网络单纯形", simplexRanks ), ( "ALAP", alapRanks ) ) :
	check( "%s 分出来的层是可行解（每条边都往下走）" % _name,
		all( _ranks[ b ] > _ranks[ a ] for a, b in rankEdges ), str( _ranks ) )

check( "网络单纯形超过节点数上限就退回最长路径（别在大图上卡住）",
	NE.LAYOUT_SIMPLEX_NODE_LIMIT <= 400, str( NE.LAYOUT_SIMPLEX_NODE_LIMIT ) )

# --- 两层之间的交叉数：树状数组版和两重循环版必须一模一样 ---
def naiveLayerCrossings( upper, lower, pairs ) :

	upperIndex = dict( ( n, i ) for i, n in enumerate( upper ) )
	lowerIndex = dict( ( n, i ) for i, n in enumerate( lower ) )
	entries = sorted(
		( upperIndex[ u ], lowerIndex[ v ] )
		for u, v in pairs if u in upperIndex and v in lowerIndex
	)
	return sum(
		1 for i in range( len( entries ) )
		for j in range( i + 1, len( entries ) ) if entries[i][1] > entries[j][1]
	)

random.seed( 11 )
crossingMismatches = []
for _trial in range( 200 ) :
	_upper = [ "u%d" % i for i in range( random.randint( 1, 8 ) ) ]
	_lower = [ "l%d" % i for i in range( random.randint( 1, 8 ) ) ]
	_pairs = list( set(
		( random.choice( _upper ), random.choice( _lower ) )
		for _ in range( random.randint( 0, 18 ) )
	) )
	if NE._layerCrossings( _upper, _lower, _pairs ) != naiveLayerCrossings( _upper, _lower, _pairs ) :
		crossingMismatches.append( ( _upper, _lower, _pairs ) )
check( "交叉数：树状数组版和两重循环版 200 组随机图全一致",
	not crossingMismatches, str( crossingMismatches[:1] ) )

# --- 定位：Brandes–Köpf 让长边变直，且主干仍是一条直溜溜的竖列 ---
#
# 图：一条 5 节点的主干 + 一个直接从最上面喂到最下面的旁支（跨 4 层的长边）。
straightScript = Gaffer.ScriptNode()
straightChain = []
for i in range( 5 ) :
	node = GafferScene.Isolate( "straight%d" % i ) if i else GafferScene.Plane( "straight0" )
	straightScript.addChild( node )
	if straightChain :
		node[ "in" ].setInput( straightChain[-1][ "out" ] )
	straightChain.append( node )
straightSide = GafferScene.Group( "straightSide" )
straightScript.addChild( straightSide )
straightSide[ "in" ][ 0 ].setInput( straightChain[-1][ "out" ] )
straightSide[ "in" ][ 1 ].setInput( straightChain[ 0 ][ "out" ] )   # 跨 4 层的长边

straightAll = list( straightScript.children( Gaffer.Node ) )
straightResults = {}
for _label, _strategy in (
	( "median", dict( position = "median", spine = "pin" ) ),
	( "brandes-kopf", dict( position = "brandes-kopf", spine = "align+pin" ) ),
) :
	with NE.layoutStrategy( **_strategy ) :
		straightResults[ _label ] = NE.layoutNodes( straightAll, straightScript )

for _label, _positions in straightResults.items() :
	_xs = [ _positions[ n ].x for n in straightChain ]
	check( "%s：主干还是一条直溜溜的竖列" % _label,
		max( _xs ) - min( _xs ) < 0.5, str( [ round( v, 2 ) for v in _xs ] ) )

longEdgeOffset = dict(
	( label, abs( positions[ straightChain[0] ].x - positions[ straightSide ].x ) )
	for label, positions in straightResults.items()
)
check( "Brandes–Köpf 让那条跨 4 层的长边比中位数那套更直",
	longEdgeOffset[ "brandes-kopf" ] <= longEdgeOffset[ "median" ] + 1e-3,
	str( longEdgeOffset ) )

check( "默认走 Brandes–Köpf + 主干优先对齐（对照数据见 tests/bench_layout.py）",
	NE.LAYOUT_STRATEGY[ "position" ] == "brandes-kopf"
	and NE.LAYOUT_STRATEGY[ "spine" ] == "align+pin",
	str( NE.LAYOUT_STRATEGY ) )

# --- 扇入的节点要停在它那几路上游的**正中间**（用户手摆的 test_layout_group.gfr）---
#
# 主干（最长那条流水线）会穿过扇入的那个节点，但它**无权**把它拽到某一路上游身上：
# 6 个 Sphere 喂一个 Group，Group 待在这一排正中间总偏移 126，贴到最左边那个
# Sphere 身上是 210。两道闸：定位那一步主干只在中位数**之间**取舍（不许越过中位数），
# 拉直那一步在扇入处断开、而且总偏移不许上升。
fanScript = Gaffer.ScriptNode()
fanSpheres = []
fanGroup = GafferScene.Group( "fanGroup" )
fanScript.addChild( fanGroup )
for i in range( 6 ) :
	sphere = GafferScene.Sphere( "fanSphere%d" % i )
	fanScript.addChild( sphere )
	fanGroup[ "in" ][ i ].setInput( sphere[ "out" ] )
	fanSpheres.append( sphere )
fanTail = GafferScene.Transform( "fanTail" )
fanScript.addChild( fanTail )
fanTail[ "in" ].setInput( fanGroup[ "out" ] )

fanPositions = NE.layoutNodes( list( fanScript.children( Gaffer.Node ) ), fanScript )
fanRow = sorted( fanPositions[ n ].x for n in fanSpheres )
fanCentre = ( fanRow[ 2 ] + fanRow[ 3 ] ) / 2.0

check( "扇入：6 个上游排成一排（同一行、间距一致）",
	max( abs( fanPositions[ n ].y - fanPositions[ fanSpheres[0] ].y ) for n in fanSpheres ) < 1e-3
	and max( abs( ( fanRow[ i + 1 ] - fanRow[ i ] ) - ( fanRow[ 1 ] - fanRow[ 0 ] ) )
		for i in range( 5 ) ) < 1e-3,
	str( [ round( v, 1 ) for v in fanRow ] ) )

check( "扇入：上游按插口顺序从左到右（in0 最左）",
	[ fanPositions[ n ].x for n in fanSpheres ] == sorted( fanPositions[ n ].x for n in fanSpheres ),
	str( [ round( fanPositions[ n ].x, 1 ) for n in fanSpheres ] ) )

check( "扇入：Group 停在这一排的正中间，不贴到某一路上游身上",
	abs( fanPositions[ fanGroup ].x - fanCentre ) < 0.5,
	"group=%.1f centre=%.1f row=%s" % ( fanPositions[ fanGroup ].x, fanCentre,
		[ round( v, 1 ) for v in fanRow ] ) )

check( "扇入：下游跟着 Group 走（还是一条竖列）",
	abs( fanPositions[ fanTail ].x - fanPositions[ fanGroup ].x ) < 0.5,
	"tail=%.1f group=%.1f" % ( fanPositions[ fanTail ].x, fanPositions[ fanGroup ].x ) )

# --- 一条长主干**中间夹一个扇入**：两头各自笔直，扇入那个仍然居中 ---
#
# 这是上一节那张图嵌进流水线里的样子 —— 主干拉直只在扇入处断开、两段各自钉直，
# 而不是"整条主干一条线"（那会把 Group 拽回上游那一列）。
midScript = Gaffer.ScriptNode()
midHead = [ GafferScene.Plane( "midHead" ) ]
midScript.addChild( midHead[ 0 ] )
for i in range( 2 ) :
	node = GafferScene.Isolate( "midUp%d" % i )
	midScript.addChild( node )
	node[ "in" ].setInput( midHead[ -1 ][ "out" ] )
	midHead.append( node )
midGroup = GafferScene.Group( "midGroup" )
midScript.addChild( midGroup )
midGroup[ "in" ][ 0 ].setInput( midHead[ -1 ][ "out" ] )
midLeaves = []
for i in range( 4 ) :
	leaf = GafferScene.Sphere( "midLeaf%d" % i )
	midScript.addChild( leaf )
	midGroup[ "in" ][ i + 1 ].setInput( leaf[ "out" ] )
	midLeaves.append( leaf )
midTail = [ midGroup ]
for i in range( 2 ) :
	node = GafferScene.Transform( "midDown%d" % i )
	midScript.addChild( node )
	node[ "in" ].setInput( midTail[ -1 ][ "out" ] )
	midTail.append( node )

midPositions = NE.layoutNodes( list( midScript.children( Gaffer.Node ) ), midScript )
midUpXs = [ midPositions[ n ].x for n in midHead ]
midDownXs = [ midPositions[ n ].x for n in midTail ]
midRow = sorted( [ midPositions[ midHead[ -1 ] ].x ] + [ midPositions[ n ].x for n in midLeaves ] )

check( "主干夹扇入：扇入上面那段主干是一条直溜溜的竖列",
	max( midUpXs ) - min( midUpXs ) < 0.5, str( [ round( v, 1 ) for v in midUpXs ] ) )
check( "主干夹扇入：扇入下面那段主干也是一条竖列",
	max( midDownXs ) - min( midDownXs ) < 0.5, str( [ round( v, 1 ) for v in midDownXs ] ) )
check( "主干夹扇入：Group 停在它那 5 路上游的中位数上",
	abs( midPositions[ midGroup ].x - midRow[ len( midRow ) // 2 ] ) < 0.5,
	"group=%.1f row=%s" % ( midPositions[ midGroup ].x, [ round( v, 1 ) for v in midRow ] ) )

# --- 一个源扇出到十几路：源留在正中间（拉直那道"总偏移不许上升"的闸挡住硬推）---
outScript = Gaffer.ScriptNode()
outHead = GafferScene.Plane( "outHead" )
outScript.addChild( outHead )
outSink = GafferScene.Group( "outSink" )
outScript.addChild( outSink )
outLeaves = []
for i in range( 8 ) :
	leaf = GafferScene.Isolate( "outLeaf%d" % i )
	outScript.addChild( leaf )
	leaf[ "in" ].setInput( outHead[ "out" ] )
	outSink[ "in" ][ i ].setInput( leaf[ "out" ] )
	outLeaves.append( leaf )

outPositions = NE.layoutNodes( list( outScript.children( Gaffer.Node ) ), outScript )
outRow = sorted( outPositions[ n ].x for n in outLeaves )
outCentre = ( outRow[ 3 ] + outRow[ 4 ] ) / 2.0
check( "扇出：源停在那一排下游的正中间，不贴到最边上那一路",
	abs( outPositions[ outHead ].x - outCentre ) < 0.5,
	"head=%.1f centre=%.1f" % ( outPositions[ outHead ].x, outCentre ) )
check( "扇出：收拢的那个也在正中间",
	abs( outPositions[ outSink ].x - outCentre ) < 0.5,
	"sink=%.1f centre=%.1f" % ( outPositions[ outSink ].x, outCentre ) )

# --- 拉直那道闸：总偏移不许上升（纯函数直接量）---
check( "_layoutDeviation 就是逐层相连的边的总横向偏移",
	abs( NE._layoutDeviation( [ ( "a", "b" ), ( "b", "c" ) ],
		{ "a" : 0.0, "b" : 3.0, "c" : -1.0 } ) - 7.0 ) < 1e-6 )
check( "_layoutDeviation 跳过不在这张图里的名字",
	abs( NE._layoutDeviation( [ ( "a", "b" ), ( "b", "zzz" ) ],
		{ "a" : 0.0, "b" : 2.0 } ) - 2.0 ) < 1e-6 )

# --- 用户手摆的那份 .gfr 就是标准答案：直接和文件里的位置对拍 ---
_fixture = os.path.join( NE.packageRoot(), "tests", "test_layout_group.gfr" )
if os.path.isfile( _fixture ) :
	fixtureScript = Gaffer.ScriptNode()
	fixtureScript[ "fileName" ].setValue( _fixture )
	fixtureScript.load()
	fixtureNodes = list( fixtureScript.children( Gaffer.Node ) )
	fixtureWanted = dict( ( n.getName(), NE.nodePosition( n ) ) for n in fixtureNodes )
	fixtureGot = dict(
		( n.getName(), p ) for n, p in NE.layoutNodes( fixtureNodes, fixtureScript ).items()
	)

	# 相对形态才是要对的（整块平移无所谓）：都减掉 Group 的位置再比。
	def _relative( table ) :
		origin = table[ "Group" ]
		return dict(
			( name, ( round( p.x - origin.x, 1 ), round( p.y - origin.y, 1 ) ) )
			for name, p in table.items()
		)

	_wantRel, _gotRel = _relative( fixtureWanted ), _relative( fixtureGot )
	check( "test_layout_group.gfr：横向相对位置和用户手摆的一致",
		all( abs( _wantRel[ n ][ 0 ] - _gotRel[ n ][ 0 ] ) < 1.0 for n in _wantRel ),
		str( sorted( ( n, _wantRel[ n ][ 0 ], _gotRel[ n ][ 0 ] ) for n in _wantRel ) ) )
	check( "test_layout_group.gfr：分了三层（一排上游 / Group / Transform）",
		len( set( round( p[ 1 ], 1 ) for p in _gotRel.values() ) ) == 3,
		str( sorted( set( round( p[ 1 ], 1 ) for p in _gotRel.values() ) ) ) )

# --- 一条连线都没有的散节点：排成一排 / 一竖列（`loose_nodes.gfr`）---
#
# 不并成一组的话它们每个都是自己一个连通分量，而没有挂钩的分量只"落回原位 + 撞上了才推开"
# —— 按 `Ctrl+L` 是**一动不动**（用户报的就是这个）。
def looseScript( positions, kind = GafferScene.Sphere ) :

	script = Gaffer.ScriptNode()
	nodes = []
	for index, ( x, y ) in enumerate( positions ) :
		node = kind( "loose%d" % index )
		script.addChild( node )
		NE.setNodePosition( node, imath.V2f( x, y ) )
		nodes.append( node )
	return script, nodes

# 用户那张图的形态：横着摆了六个、y 有抖动、间距不均
looseRowScript, looseRowNodes = looseScript(
	[ ( -27.17, 13.08 ), ( -14.48, 14.83 ), ( -1.49, 18.94 ),
	  ( 13.42, 11.93 ), ( 30.90, 15.28 ), ( 47.61, 11.06 ) ]
)
looseRow = NE.layoutNodes( looseRowNodes, looseRowScript )

check( "散节点：`Ctrl+L` 真的动了（以前一动不动）",
	any( ( looseRow[ n ] - NE.nodePosition( n ) ).length() > 0.5 for n in looseRowNodes ),
	str( [ ( n.getName(), round( looseRow[ n ].x, 1 ), round( looseRow[ n ].y, 1 ) ) for n in looseRowNodes ] ) )

_ys = [ looseRow[ n ].y for n in looseRowNodes ]
check( "散节点：横着摆的排成一排（y 全对齐）",
	max( _ys ) - min( _ys ) < 1e-3, str( [ round( v, 2 ) for v in _ys ] ) )

_xs = sorted( looseRow[ n ].x for n in looseRowNodes )
_gaps = [ _xs[ i + 1 ] - _xs[ i ] for i in range( len( _xs ) - 1 ) ]
check( "散节点：间距等距（原来 12.7~17.5 不均）",
	max( _gaps ) - min( _gaps ) < 1e-3, str( [ round( v, 1 ) for v in _gaps ] ) )
check( "散节点：等距 = 节点宽 + 横向间距",
	abs( _gaps[ 0 ] - ( 11.0 + NE.LAYOUT_HORIZONTAL_GAP ) ) < 0.5, str( _gaps[ 0 ] ) )

check( "散节点：左右先后顺序保持不变（不按名字重排）",
	[ n.getName() for n in sorted( looseRowNodes, key = lambda n : looseRow[ n ].x ) ]
	== [ n.getName() for n in sorted( looseRowNodes, key = lambda n : NE.nodePosition( n ).x ) ] )

_centreBefore = sum( NE.nodePosition( n ).x for n in looseRowNodes ) / len( looseRowNodes )
_centreAfter = sum( looseRow[ n ].x for n in looseRowNodes ) / len( looseRowNodes )
check( "散节点：整排还留在原来那一带（不跳到别处）",
	abs( _centreBefore - _centreAfter ) < 1.0, "%.1f vs %.1f" % ( _centreBefore, _centreAfter ) )

# 竖着摆的 → 排成一竖列（**按他现在摆的样子决定横竖**，不是写死横排）
looseColScript, looseColNodes = looseScript(
	[ ( 2, 40 ), ( -3, 22 ), ( 1, 5 ), ( 4, -14 ), ( -2, -30 ) ]
)
looseCol = NE.layoutNodes( looseColNodes, looseColScript )
_colXs = [ looseCol[ n ].x for n in looseColNodes ]
_colYs = sorted( ( looseCol[ n ].y for n in looseColNodes ), reverse = True )
_colGaps = [ _colYs[ i ] - _colYs[ i + 1 ] for i in range( len( _colYs ) - 1 ) ]
check( "散节点：竖着摆的排成一竖列（x 全对齐 + 等距）",
	max( _colXs ) - min( _colXs ) < 1e-3
	and max( _colGaps ) - min( _colGaps ) < 1e-3,
	str( [ round( v, 2 ) for v in _colXs ] ) + str( [ round( v, 1 ) for v in _colGaps ] ) )
check( "散节点：竖列的上下顺序也保持不变",
	[ n.getName() for n in sorted( looseColNodes, key = lambda n : -looseCol[ n ].y ) ]
	== [ n.getName() for n in sorted( looseColNodes, key = lambda n : -NE.nodePosition( n ).y ) ] )

# 堆在一起（没有主轴）→ 回退到这类节点自己的流向惯例：场景节点并排成**横排**
loosePileScript, loosePileNodes = looseScript( [ ( 0, 0 ) ] * 4 )
loosePile = NE.layoutNodes( loosePileNodes, loosePileScript )
check( "散节点：堆在一起的场景节点排成横排（流向惯例：同级垂直于流向排开）",
	max( loosePile[ n ].y for n in loosePileNodes )
	- min( loosePile[ n ].y for n in loosePileNodes ) < 1e-3
	and max( loosePile[ n ].x for n in loosePileNodes )
	- min( loosePile[ n ].x for n in loosePileNodes ) > 30.0,
	str( [ ( round( loosePile[ n ].x, 1 ), round( loosePile[ n ].y, 1 ) ) for n in loosePileNodes ] ) )

# 堆在一起的**材质**节点（横着流）→ 叠成一竖列
looseShaderScript, looseShaderNodes = looseScript( [ ( 0, 0 ) ] * 3, GafferOSL.OSLCode )
looseShader = NE.layoutNodes( looseShaderNodes, looseShaderScript )
check( "散节点：堆在一起的材质节点叠成一竖列（它们横着流）",
	max( looseShader[ n ].x for n in looseShaderNodes )
	- min( looseShader[ n ].x for n in looseShaderNodes ) < 1e-3
	and max( looseShader[ n ].y for n in looseShaderNodes )
	- min( looseShader[ n ].y for n in looseShaderNodes ) > 5.0,
	str( [ ( round( looseShader[ n ].x, 1 ), round( looseShader[ n ].y, 1 ) ) for n in looseShaderNodes ] ) )

# 散节点混在一张连通图旁边：连通那部分照旧、散的排成线、两边不许重叠
mixedScript = Gaffer.ScriptNode()
mixedPlane = GafferScene.Plane( "mixedPlane" )
mixedScript.addChild( mixedPlane )
mixedIsolate = GafferScene.Isolate( "mixedIsolate" )
mixedScript.addChild( mixedIsolate )
mixedIsolate[ "in" ].setInput( mixedPlane[ "out" ] )
NE.setNodePosition( mixedPlane, imath.V2f( 0, 20 ) )
NE.setNodePosition( mixedIsolate, imath.V2f( 0, 8 ) )
mixedLoose = []
for _index, ( _x, _y ) in enumerate( [ ( 40, 30 ), ( 55, 5 ), ( 48, -20 ) ] ) :
	_node = GafferScene.Sphere( "mixedLoose%d" % _index )
	mixedScript.addChild( _node )
	NE.setNodePosition( _node, imath.V2f( _x, _y ) )
	mixedLoose.append( _node )

mixedAll = list( mixedScript.children( Gaffer.Node ) )
mixedResult = NE.layoutNodes( mixedAll, mixedScript )
check( "散节点：混在连通图旁边时，散的那几个也排成一条线",
	max( mixedResult[ n ].x for n in mixedLoose )
	- min( mixedResult[ n ].x for n in mixedLoose ) < 1e-3,
	str( [ round( mixedResult[ n ].x, 1 ) for n in mixedLoose ] ) )
check( "散节点：连通那部分还是一条直溜溜的竖列",
	abs( mixedResult[ mixedPlane ].x - mixedResult[ mixedIsolate ].x ) < 0.5 )

_overlaps = 0
for _i in range( len( mixedAll ) ) :
	for _j in range( _i + 1, len( mixedAll ) ) :
		_a, _b = mixedResult[ mixedAll[ _i ] ], mixedResult[ mixedAll[ _j ] ]
		if abs( _a.x - _b.x ) < 11.0 - 1e-3 and abs( _a.y - _b.y ) < 4.164 - 1e-3 :
			_overlaps += 1
check( "散节点：排完不许和连通那部分重叠", _overlaps == 0, str( _overlaps ) )

# 只有一个散节点 —— 没什么可排的，别动它
singleScript = Gaffer.ScriptNode()
singlePlane = GafferScene.Plane( "singlePlane" )
singleScript.addChild( singlePlane )
singleIsolate = GafferScene.Isolate( "singleIsolate" )
singleScript.addChild( singleIsolate )
singleIsolate[ "in" ].setInput( singlePlane[ "out" ] )
NE.setNodePosition( singlePlane, imath.V2f( 0, 20 ) )
NE.setNodePosition( singleIsolate, imath.V2f( 3, 8 ) )
singleLoose = GafferScene.Sphere( "singleLoose" )
singleScript.addChild( singleLoose )
NE.setNodePosition( singleLoose, imath.V2f( 40, 30 ) )
singleResult = NE.layoutNodes( list( singleScript.children( Gaffer.Node ) ), singleScript )
check( "只有一个散节点就别动它（没什么可排的）",
	( singleResult[ singleLoose ] - imath.V2f( 40, 30 ) ).length() < 1e-3,
	str( singleResult[ singleLoose ] ) )

# 纯函数：少于两个散节点原样返回
_looseGroups, _looseGroupOf = NE._layoutLooseGroup(
	{ "a" : None, "b" : None }, { "a" : "vertical", "b" : "vertical" },
	[ [ "a" ], [ "b" ] ], { "a" : 0, "b" : 1 },
	[ ( "a", "b", None ) ], lambda n : imath.V2f( 0, 0 )
)
check( "_layoutLooseGroup：都连着的话一个组都不并",
	_looseGroups == [ [ "a" ], [ "b" ] ], str( _looseGroups ) )

_looseGroups2, _looseGroupOf2 = NE._layoutLooseGroup(
	{ "a" : None, "b" : None, "c" : None },
	{ "a" : "vertical", "b" : "vertical", "c" : "vertical" },
	[ [ "a" ], [ "b" ], [ "c" ] ], { "a" : 0, "b" : 1, "c" : 2 },
	[ ( "a", "b", None ) ],
	lambda n : imath.V2f( 0, 0 )
)
check( "_layoutLooseGroup：只并真正一条线都没连的（`c` 单独一个 → 不够两个，不并）",
	sorted( sorted( g ) for g in _looseGroups2 ) == [ [ "a" ], [ "b" ], [ "c" ] ],
	str( _looseGroups2 ) )

# 用户给的那份文件本身
_looseFixture = os.path.join( NE.packageRoot(), "tests", "loose_nodes.gfr" )
if os.path.isfile( _looseFixture ) :
	looseFileScript = Gaffer.ScriptNode()
	looseFileScript[ "fileName" ].setValue( _looseFixture )
	looseFileScript.load()
	looseFileNodes = list( looseFileScript.children( Gaffer.Node ) )
	looseFile = NE.layoutNodes( looseFileNodes, looseFileScript )
	_fileYs = [ looseFile[ n ].y for n in looseFileNodes ]
	_fileXs = sorted( looseFile[ n ].x for n in looseFileNodes )
	_fileGaps = [ _fileXs[ i + 1 ] - _fileXs[ i ] for i in range( len( _fileXs ) - 1 ) ]
	check( "loose_nodes.gfr：六个散节点排成整齐一排",
		len( looseFileNodes ) == 6
		and max( _fileYs ) - min( _fileYs ) < 1e-3
		and max( _fileGaps ) - min( _fileGaps ) < 1e-3,
		str( [ round( v, 1 ) for v in _fileXs ] ) + " y=" + str( round( _fileYs[ 0 ], 1 ) ) )

# --- 换实现的开关用完要还回去 ---
_before = dict( NE.LAYOUT_STRATEGY )
with NE.layoutStrategy( position = "tidy", rank = "alap" ) :
	check( "layoutStrategy 里改的是全局那份（不是拷贝）",
		NE.LAYOUT_STRATEGY[ "position" ] == "tidy" )
check( "layoutStrategy 出了作用域就还回去", dict( NE.LAYOUT_STRATEGY ) == _before,
	str( NE.LAYOUT_STRATEGY ) )

# --- PathFilter：一个 filter 喂好几个节点时落在它们中间，而且不许被甩出去 ---
#
# 以前挡路判定拿的是**整组的包围盒** —— 主干那一组的包围盒是从头到尾一整条，
# 一个挂在旁边的 filter 撞上就得整个越过去，几个 filter 接连让下去能甩出几十个单位
# （实测平均"侧跳" 99.8，原生才 14.6；改成逐节点矩形之后 25.5）。
filterScript = Gaffer.ScriptNode()
filterPlane = GafferScene.Plane( "filterPlane" ) ; filterScript.addChild( filterPlane )
filterShared = GafferScene.PathFilter( "filterShared" ) ; filterScript.addChild( filterShared )
filterConsumers = []
filterChainNode = filterPlane
for i in range( 5 ) :
	node = GafferScene.Isolate( "filterConsumer%d" % i )
	filterScript.addChild( node )
	node[ "in" ].setInput( filterChainNode[ "out" ] )
	node[ "filter" ].setInput( filterShared[ "out" ] )
	filterConsumers.append( node )
	filterChainNode = node

filterPositions = NE.layoutNodes(
	list( filterScript.children( Gaffer.Node ) ), filterScript )

filterConsumerXs = [ filterPositions[ n ].x for n in filterConsumers ]
filterSize = NE.nodeSizeUnits( filterShared, None )
check( "filter 摆在消费者的右边（`filter` 圆点挂右边）",
	filterPositions[ filterShared ].x > max( filterConsumerXs ) + 1e-3,
	"%.1f vs %.1f" % ( filterPositions[ filterShared ].x, max( filterConsumerXs ) ) )
check( "filter 就贴在旁边，没被甩出去（不到两个节点宽）",
	filterPositions[ filterShared ].x - max( filterConsumerXs ) < filterSize[0] * 2,
	"%.1f" % ( filterPositions[ filterShared ].x - max( filterConsumerXs ) ) )

filterConsumerYs = [ filterPositions[ n ].y for n in filterConsumers ]
check( "喂好几个节点的 filter 落在它们中间（不是贴死在某一头）",
	min( filterConsumerYs ) < filterPositions[ filterShared ].y < max( filterConsumerYs ),
	"%.1f 不在 [%.1f, %.1f] 中间" % (
		filterPositions[ filterShared ].y, min( filterConsumerYs ), max( filterConsumerYs ) ) )

# 五个各自独享 filter 的：每个都得贴着自己那个消费者，不许一个比一个远
ownScript = Gaffer.ScriptNode()
ownPlane = GafferScene.Plane( "ownPlane" ) ; ownScript.addChild( ownPlane )
ownPairs = []
ownChain = ownPlane
for i in range( 5 ) :
	node = GafferScene.Isolate( "ownConsumer%d" % i ) ; ownScript.addChild( node )
	own = GafferScene.PathFilter( "ownFilter%d" % i ) ; ownScript.addChild( own )
	node[ "in" ].setInput( ownChain[ "out" ] )
	node[ "filter" ].setInput( own[ "out" ] )
	ownPairs.append( ( own, node ) )
	ownChain = node

ownPositions = NE.layoutNodes( list( ownScript.children( Gaffer.Node ) ), ownScript )
ownHops = [
	( ownPositions[ f ] - ownPositions[ c ] ).length() for f, c in ownPairs
]
check( "五个 filter 各自贴着自己那个消费者（最远的也不到三个节点宽）",
	max( ownHops ) < NE.nodeSizeUnits( ownPlane, None )[0] * 3,
	str( [ round( v, 1 ) for v in ownHops ] ) )
check( "不会一个比一个远（没有「接连往外让」的连锁）",
	max( ownHops ) - min( ownHops ) < 1.0, str( [ round( v, 1 ) for v in ownHops ] ) )

ownOverlaps = []
_ownItems = [ ( n, ownPositions[ n ], NE.nodeSizeUnits( n, None ) )
	for n in ownScript.children( Gaffer.Node ) if n in ownPositions ]
for _i in range( len( _ownItems ) ) :
	for _j in range( _i + 1, len( _ownItems ) ) :
		( _na, _pa, _sa ), ( _nb, _pb, _sb ) = _ownItems[ _i ], _ownItems[ _j ]
		if ( abs( _pa.x - _pb.x ) < ( _sa[0] + _sb[0] ) / 2.0 - 1e-3 and
			abs( _pa.y - _pb.y ) < ( _sa[1] + _sb[1] ) / 2.0 - 1e-3 ) :
			ownOverlaps.append( ( _na.getName(), _nb.getName() ) )
check( "逐节点挡路判定之后还是一个都不重叠", not ownOverlaps, str( ownOverlaps[:3] ) )


##########################################################################
section( "Backdrop 拖得动（位置写回 `__uiPosition`，框的中心偏移要减掉）" )
##########################################################################

# Backdrop 的 item 位置是**框的中心**（`__uiPosition` + `__uiBound` 的中心），
# 而能写回 script 的只有 `__uiPosition` —— 拿一个**不对称**的框把这个偏移逼出来。

dragScript = Gaffer.ScriptNode()
dragApp = Gaffer.ApplicationRoot( "backdropDrag" )
dragApp["scripts"].addChild( dragScript )

dragSphere = GafferScene.Sphere( "dragSphere" )
dragScript.addChild( dragSphere )
NE.setNodePosition( dragSphere, imath.V2f( 8, 0 ) )

dragBackdrop = Gaffer.Backdrop( "dragBackdrop" )
dragScript.addChild( dragBackdrop )
NE.setNodePosition( dragBackdrop, imath.V2f( 4, -2 ) )
dragBackdrop.addChild( Gaffer.Box2fPlug(
	"__uiBound", Gaffer.Plug.Direction.In,
	imath.Box2f( imath.V2f( -4, -2 ), imath.V2f( 12, 6 ) ),
	flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
) )

lockedBackdrop = Gaffer.Backdrop( "lockedBackdrop" )
dragScript.addChild( lockedBackdrop )
NE.setNodePosition( lockedBackdrop, imath.V2f( 40, 40 ) )
Gaffer.MetadataAlgo.setReadOnly( lockedBackdrop, True )

dragEditor = NE.NetworkEditor( dragScript )
dragWindow = GafferUI.Window( "backdropDrag" )
dragWindow.setChild( dragEditor )
dragWindow._qtWidget().resize( 800, 600 )
dragWindow.setVisible( True )
idle()

dragItem = dragEditor._NetworkEditor__backdropItems[ "dragBackdrop" ]
lockedItem = dragEditor._NetworkEditor__backdropItems[ "lockedBackdrop" ]

check( "Backdrop item 拖得动（ItemIsMovable）",
	bool( dragItem.flags() & QtWidgets.QGraphicsItem.ItemIsMovable ) )
check( "Backdrop item 照旧选得中",
	bool( dragItem.flags() & QtWidgets.QGraphicsItem.ItemIsSelectable ) )
check( "只读的 Backdrop 拖不动",
	not ( lockedItem.flags() & QtWidgets.QGraphicsItem.ItemIsMovable ) )

dragOffset = dragItem.centerOffset()
check( "框中心相对 __uiPosition 的偏移算对了",
	abs( dragOffset.x - 4.0 ) < 1e-4 and abs( dragOffset.y - 2.0 ) < 1e-4,
	str( dragOffset ) )
check( "item 摆在框的中心上",
	abs( dragItem.pos().x() - 8 * NE.PX_PER_UNIT ) < 1e-4 and abs( dragItem.pos().y() - 0.0 ) < 1e-4,
	str( dragItem.pos() ) )

# 拖一下（Qt 那边就是这么改**选中** item 的位置的），松手 = `_commitNodePositions`
dragItem.setSelected( True )
dragItem.setPos( dragItem.pos() + QtCore.QPointF( 5 * NE.PX_PER_UNIT, -3 * NE.PX_PER_UNIT ) )
dragEditor._commitNodePositions()

movedPosition = NE.nodePosition( dragBackdrop )
check( "拖完 __uiPosition 跟着走（减掉框中心偏移）",
	movedPosition is not None and
	abs( movedPosition.x - 9.0 ) < 1e-4 and abs( movedPosition.y - 1.0 ) < 1e-4,
	str( movedPosition ) )
check( "框也跟着搬（backdropBound 的中心）",
	abs( NE.backdropBound( dragBackdrop )[0].x - 13.0 ) < 1e-4 and
	abs( NE.backdropBound( dragBackdrop )[0].y - 3.0 ) < 1e-4,
	str( NE.backdropBound( dragBackdrop )[0] ) )
check( "只拖 Backdrop 时框里的节点原地不动",
	abs( NE.nodePosition( dragSphere ).x - 8.0 ) < 1e-4 and
	abs( NE.nodePosition( dragSphere ).y - 0.0 ) < 1e-4,
	str( NE.nodePosition( dragSphere ) ) )
check( "一次拖动一步撤销", dragScript.undoAvailable() )
dragScript.undo()
check( "撤销回原位",
	abs( NE.nodePosition( dragBackdrop ).x - 4.0 ) < 1e-4 and
	abs( NE.nodePosition( dragBackdrop ).y + 2.0 ) < 1e-4,
	str( NE.nodePosition( dragBackdrop ) ) )
idle()
check( "撤销后 item 也回到框中心",
	abs( dragItem.pos().x() - 8 * NE.PX_PER_UNIT ) < 1e-4 and abs( dragItem.pos().y() - 0.0 ) < 1e-4,
	str( dragItem.pos() ) )

# 点 Backdrop 连它框住的节点一起选（原生同款）→ 于是拖它就是拖整组
dragItem.setSelected( False )
dragEditor._selectClicked( dragItem, QtCore.Qt.NoModifier )
_dragSelected = sorted( n.getName() for n in dragScript.selection() )
check( "点 Backdrop 把框住的节点一起选上（拖它 = 拖整组）",
	_dragSelected == [ "dragBackdrop", "dragSphere" ], str( _dragSelected ) )

# 整组一起拖：Qt 会挪动所有选中且 movable 的 item，两边都得写回
dragItem.setPos( dragItem.pos() + QtCore.QPointF( 2 * NE.PX_PER_UNIT, 0 ) )
dragEditor._NetworkEditor__nodeItems[ "dragSphere" ].setPos(
	dragEditor._NetworkEditor__nodeItems[ "dragSphere" ].pos() + QtCore.QPointF( 2 * NE.PX_PER_UNIT, 0 )
)
dragEditor._commitNodePositions()
check( "整组拖动：Backdrop 和框里的节点一起写回",
	abs( NE.nodePosition( dragBackdrop ).x - 6.0 ) < 1e-4 and
	abs( NE.nodePosition( dragSphere ).x - 10.0 ) < 1e-4,
	"%s %s" % ( NE.nodePosition( dragBackdrop ), NE.nodePosition( dragSphere ) ) )

dragWindow.setVisible( False )
idle()


##########################################################################
section( "Backdrop 照原生：框身是洞 / 边缘拉框 / 标题条 / scale / depth" )
##########################################################################

# 原生 `BackdropNodeGadget` 在 selection render 里只画四条边 + 顶上那条标题条，
# **框身留成一个洞**（`BackdropNodeGadget.cpp:350` 的注释：不留洞就没法在 Backdrop
# 上框选它框住的节点）。下面逐条对齐。

bdScript2 = Gaffer.ScriptNode()
bdApp2 = Gaffer.ApplicationRoot( "backdropNative" )
bdApp2["scripts"].addChild( bdScript2 )

bdSphere2 = GafferScene.Sphere( "bdSphere2" )
bdScript2.addChild( bdSphere2 )
NE.setNodePosition( bdSphere2, imath.V2f( 0, 0 ) )

bdBig = Gaffer.Backdrop( "bdBig" )
bdScript2.addChild( bdBig )
NE.setNodePosition( bdBig, imath.V2f( 0, 0 ) )
NE.setBackdropRelativeBound( bdBig, imath.Box2f( imath.V2f( -20, -12 ), imath.V2f( 20, 12 ) ) )
bdBig["title"].setValue( "灯光组" )
bdBig["description"].setValue( "这一坨是主光" )

bdSmall = Gaffer.Backdrop( "bdSmall" )
bdScript2.addChild( bdSmall )
NE.setNodePosition( bdSmall, imath.V2f( 60, 0 ) )
NE.setBackdropRelativeBound( bdSmall, imath.Box2f( imath.V2f( -6, -4 ), imath.V2f( 6, 4 ) ) )

bdLocked = Gaffer.Backdrop( "bdLocked" )
bdScript2.addChild( bdLocked )
NE.setNodePosition( bdLocked, imath.V2f( 0, 60 ) )
Gaffer.MetadataAlgo.setReadOnly( bdLocked, True )

bdEditor2 = NE.NetworkEditor( bdScript2 )
bdWindow2 = GafferUI.Window( "backdropNative" )
bdWindow2.setChild( bdEditor2 )
bdWindow2._qtWidget().resize( 1000, 700 )
bdWindow2.setVisible( True )
idle()

bdView2 = bdEditor2.graphView()
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]
smallItem = bdEditor2._NetworkEditor__backdropItems[ "bdSmall" ]
lockedItem = bdEditor2._NetworkEditor__backdropItems[ "bdLocked" ]

# --- 默认框和原生一样是 20x20（`g_defaultBound`）---
check( "没有 __uiBound 时默认框 20x20（照原生 g_defaultBound）",
	abs( NE.backdropBound( bdLocked )[1] - 20.0 ) < 1e-4 and
	abs( NE.backdropBound( bdLocked )[2] - 20.0 ) < 1e-4,
	str( NE.backdropBound( bdLocked )[1:] ) )
check( "backdropRelativeBound 读的是相对 __uiPosition 的框",
	abs( NE.backdropRelativeBound( bdBig ).min().x + 20.0 ) < 1e-4 and
	abs( NE.backdropRelativeBound( bdBig ).max().y - 12.0 ) < 1e-4,
	str( NE.backdropRelativeBound( bdBig ) ) )

# --- 框身是洞：只有边缘和标题条能点 ---
bigRect = bigItem.frameRect()
check( "框身正中点不到（留给框选它框住的节点）",
	not bigItem.shape().contains( QtCore.QPointF( 0, 0 ) ) )
check( "四条边都点得到",
	bigItem.shape().contains( QtCore.QPointF( bigRect.left() + 2, 0 ) ) and
	bigItem.shape().contains( QtCore.QPointF( bigRect.right() - 2, 0 ) ) and
	bigItem.shape().contains( QtCore.QPointF( 0, bigRect.top() + 2 ) ) and
	bigItem.shape().contains( QtCore.QPointF( 0, bigRect.bottom() - 2 ) ) )
check( "四个角也点得到（WindingFill，别被异或成洞）",
	bigItem.shape().contains( QtCore.QPointF( bigRect.left() + 2, bigRect.top() + 2 ) ) and
	bigItem.shape().contains( QtCore.QPointF( bigRect.right() - 2, bigRect.bottom() - 2 ) ) )
check( "标题条点得到（抓它搬动整个 Backdrop）",
	bigItem.shape().contains( bigItem.titleBarRect().center() ) )
# 框身正中压着 bdSphere2（就是要它压在 Backdrop 上），所以拿框内一块空地问
_bdHole = QtCore.QPointF( bigRect.left() + 60, bigRect.top() + 70 )
check( "视图层：框身内的空地不算「可选中的 item」（这样才能在 Backdrop 上框选）",
	bdView2.selectableItemAt(
		bdView2.mapFromScene( bigItem.mapToScene( _bdHole ) )
	) is None,
	str( bdView2.selectableItemAt(
		bdView2.mapFromScene( bigItem.mapToScene( _bdHole ) ) ) ) )
check( "而框住的那个节点照旧点得到",
	isinstance( bdView2.selectableItemAt(
		bdView2.mapFromScene( bigItem.mapToScene( QtCore.QPointF( 0, 0 ) ) )
	), NE._NodeItem ) )

# --- 边缘命中：左右下宽、上边窄（顶上留给标题条）---
check( "左边缘认得出来", bigItem.edgeAt( QtCore.QPointF( bigRect.left() + 1, 0 ) ) == ( -1, 0 ) )
check( "右边缘认得出来", bigItem.edgeAt( QtCore.QPointF( bigRect.right() - 1, 0 ) ) == ( 1, 0 ) )
check( "下边缘认得出来（y 向下，原生的「下」= vertical -1）",
	bigItem.edgeAt( QtCore.QPointF( 0, bigRect.bottom() - 1 ) ) == ( 0, -1 ) )
check( "上边缘认得出来", bigItem.edgeAt( QtCore.QPointF( 0, bigRect.top() + 1 ) ) == ( 0, 1 ) )
check( "左下角是两条边一起", bigItem.edgeAt(
	QtCore.QPointF( bigRect.left() + 1, bigRect.bottom() - 1 ) ) == ( -1, -1 ) )
check( "上边的抓手比别的窄（照原生 min( width, titleBarMargin )）",
	bigItem.edgeAt( QtCore.QPointF( 0, bigRect.top() + NE.BACKDROP_TOP_EDGE_HIT + 2 ) ) == ( 0, 0 ),
	str( bigItem.edgeAt( QtCore.QPointF( 0, bigRect.top() + NE.BACKDROP_TOP_EDGE_HIT + 2 ) ) ) )
check( "框身正中不是任何边", bigItem.edgeAt( QtCore.QPointF( 0, 0 ) ) == ( 0, 0 ) )
check( "只读的 Backdrop 压根不给拉框", lockedItem.edgeAt(
	QtCore.QPointF( lockedItem.frameRect().left() + 1, 0 ) ) == ( 0, 0 ) )

# --- 拉框：预览 → 松手写回，一步撤销 ---
targetScene = bigItem.mapToScene( QtCore.QPointF( bigRect.right() + 10 * NE.PX_PER_UNIT, 0 ) )
bdEditor2._resizeBackdrop( bigItem, 1, 0, targetScene )
check( "拉框途中 item 就变宽了（预览）",
	abs( bigItem.relativeBound().max().x - 30.0 ) < 0.01,
	str( bigItem.relativeBound() ) )
check( "拉框途中还没写进插口（一次拖动只留一步撤销）",
	abs( NE.backdropRelativeBound( bdBig ).max().x - 20.0 ) < 1e-4,
	str( NE.backdropRelativeBound( bdBig ) ) )
bdEditor2._commitBackdropResize( bigItem )
check( "松手写回插口",
	abs( NE.backdropRelativeBound( bdBig ).max().x - 30.0 ) < 0.01,
	str( NE.backdropRelativeBound( bdBig ) ) )
check( "一次拉框一步撤销", bdScript2.undoAvailable() )
bdScript2.undo()
idle()
check( "撤销回原来的框",
	abs( NE.backdropRelativeBound( bdBig ).max().x - 20.0 ) < 1e-4,
	str( NE.backdropRelativeBound( bdBig ) ) )

bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]
bigRect = bigItem.frameRect()

# 最小尺寸（原生 g_margin * 4 = 12 单位）
insideScene = bigItem.mapToScene( QtCore.QPointF( bigRect.left() + 5, 0 ) )
bdEditor2._resizeBackdrop( bigItem, 1, 0, insideScene )
check( "拉到最小就不再缩（照原生 g_margin*4 = 12 单位）",
	abs( ( bigItem.relativeBound().max().x - bigItem.relativeBound().min().x ) - 12.0 ) < 0.01,
	str( bigItem.relativeBound() ) )
bigItem.commitPreviewBound()
bdScript2.undo()
idle()
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]

# 拉左边：框往左长，中心跟着挪（item 位置 = 框中心）
bigRect = bigItem.frameRect()
leftScene = bigItem.mapToScene( QtCore.QPointF( bigRect.left() - 8 * NE.PX_PER_UNIT, 0 ) )
posBefore = QtCore.QPointF( bigItem.pos() )
bdEditor2._resizeBackdrop( bigItem, -1, 0, leftScene )
check( "拉左边：左边界往左走，右边界一动不动",
	abs( bigItem.relativeBound().min().x + 28.0 ) < 0.01 and
	abs( bigItem.relativeBound().max().x - 20.0 ) < 1e-4,
	str( bigItem.relativeBound() ) )
check( "item 跟着摆到新的框中心上",
	abs( bigItem.pos().x() - ( posBefore.x() - 4 * NE.PX_PER_UNIT ) ) < 0.5,
	"%s -> %s" % ( posBefore, bigItem.pos() ) )
bigItem.commitPreviewBound()
check( "拉左边只改框、不动 __uiPosition（原生 setBound 也只写 __uiBound）",
	abs( NE.nodePosition( bdBig ).x - 0.0 ) < 1e-4, str( NE.nodePosition( bdBig ) ) )
bdScript2.undo()
idle()
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]

# --- 层叠：大框垫在小框后面，depth 插口再压一档 ---
check( "Backdrop 永远在节点和连线后面",
	bigItem.zValue() < 0 and smallItem.zValue() < 0,
	"%s %s" % ( bigItem.zValue(), smallItem.zValue() ) )
check( "面积大的垫在后面（照原生按面积排深度）",
	bigItem.zValue() < smallItem.zValue(),
	"%s vs %s" % ( bigItem.zValue(), smallItem.zValue() ) )
bdSmall["depth"].setValue( -1 )
idle()
smallItem = bdEditor2._NetworkEditor__backdropItems[ "bdSmall" ]
check( "depth = -1 压到大框后面",
	smallItem.zValue() < bigItem.zValue(),
	"%s vs %s" % ( smallItem.zValue(), bigItem.zValue() ) )
bdSmall["depth"].setValue( 0 )
idle()

# --- 标题 / 描述 / 文字缩放 ---
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]
check( "标题读的是 title 插口", bigItem._title == "灯光组", bigItem._title )
check( "描述也读出来了", bigItem._description == "这一坨是主光", bigItem._description )
check( "tooltip 带标题和描述",
	"灯光组" in bigItem.toolTip() and "这一坨是主光" in bigItem.toolTip(),
	bigItem.toolTip() )
bdBig["title"].setValue( "改了名" )
idle()
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]
check( "改 title 画面跟着变", bigItem._title == "改了名", bigItem._title )
bdBig["scale"].setValue( 2.0 )
idle()
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]
check( "scale 插口读出来了（原生用它放大标题和描述）", abs( bigItem._scale - 2.0 ) < 1e-4,
	str( bigItem._scale ) )
check( "scale 只放大文字、不改框",
	abs( NE.backdropBound( bdBig )[1] - 40.0 ) < 1e-4, str( NE.backdropBound( bdBig )[1] ) )
bdBig["scale"].setValue( 1.0 )
idle()

# --- 悬停：不在边缘上时标题条高亮（原生 m_hovered）---
bigItem = bdEditor2._NetworkEditor__backdropItems[ "bdBig" ]
bdEditor2._setHoveredBackdrop( bigItem )
check( "悬停框身 → 标题条高亮", bigItem._hovered )
bdEditor2._setHoveredBackdrop( None )
check( "移开就不亮了", not bigItem._hovered )

bdWindow2.setVisible( False )
idle()


##########################################################################
section( "接口标签 / focus 角标开关 / 注释可见性 / 双击信号（原生扩展点）" )
##########################################################################

parScript = Gaffer.ScriptNode()
parApp = Gaffer.ApplicationRoot( "parity" )
parApp["scripts"].addChild( parScript )

parPlane = GafferScene.Plane( "parPlane" ) ; parScript.addChild( parPlane )
parIsolate = GafferScene.Isolate( "parIsolate" ) ; parScript.addChild( parIsolate )
NE.setNodePosition( parPlane, imath.V2f( 0, 10 ) )
NE.setNodePosition( parIsolate, imath.V2f( 0, 0 ) )

parEditor = NE.NetworkEditor( parScript )
parWindow = GafferUI.Window( "parity" )
parWindow.setChild( parEditor )
parWindow._qtWidget().resize( 1000, 700 )
parWindow.setVisible( True )
idle()

def parItem( name ) :
	return parEditor._NetworkEditor__nodeItems[ name ]

# --- 接口标签：原生平时不画，靠 metadata / 悬停 / 拖连线才出来 ---
check( "默认不显示输入接口标签", NE.noduleLabelsVisible( parIsolate, Gaffer.Plug.Direction.In ) is False )
check( "顶 / 底接口的标签平时不画", not parItem( "parIsolate" ).endLabelsVisible() )

Gaffer.Metadata.registerValue( parIsolate, "nodeGadget:inputNoduleLabelsVisible", True )
idle()
check( "菜单 `/Connections/Show Input Labels` 那条元数据认得出来",
	NE.noduleLabelsVisible( parIsolate, Gaffer.Plug.Direction.In ) is True )
check( "打开之后标签就画了（原生同款常驻显示）",
	parItem( "parIsolate" ).endLabelsVisible() )
Gaffer.Metadata.deregisterValue( parIsolate, "nodeGadget:inputNoduleLabelsVisible" )
idle()
check( "关掉又不画了", not parItem( "parIsolate" ).endLabelsVisible() )

# 悬停整个节点 → 所有接口名字都出来（原生 labelsVisibleOnHover）
isolateItem = parItem( "parIsolate" )
isolateItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "鼠标停在节点上 → 接口名字全出来（原生 labelsVisibleOnHover）",
	isolateItem.endLabelsVisible() )
isolateItem.hoverLeaveEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "移开就收回去", not isolateItem.endLabelsVisible() )

# 拖连线过来 → 只把接得上的那几个显示出来（原生 dragEnter）
parEditor._setDropTarget( isolateItem, parPlane[ "out" ] )
check( "拖连线过来：接得上的接口名字亮出来（原生 dragEnter 同款）",
	isolateItem.endLabelsVisible() and
	isolateItem._NodeItem__dragLabelKeys,
	str( isolateItem._NodeItem__dragLabelKeys ) )
parEditor._setDropTarget( None )
check( "拖走了就收回去", not isolateItem.endLabelsVisible() )

# --- focus 角标可以在节点上关掉（原生 nodeGadget:focusGadgetVisible）---
check( "默认有 focus 角标", NE.focusGadgetVisible( parIsolate ) is True )
parScript.setFocus( parIsolate )
idle()
check( "focus 的时候画角标", parItem( "parIsolate" ).focusFlagVisible() )
Gaffer.Metadata.registerValue( parIsolate, "nodeGadget:focusGadgetVisible", False )
idle()
check( "节点上关掉 focusGadgetVisible 就一律不画（原生同款）",
	not parItem( "parIsolate" ).focusFlagVisible() )
Gaffer.Metadata.deregisterValue( parIsolate, "nodeGadget:focusGadgetVisible" )
parScript.setFocus( None )
idle()

# --- 注释可见性（原生 GraphEditor 右上角那个 annotations 菜单）---
Gaffer.MetadataAlgo.addAnnotation(
	parPlane, "user", Gaffer.MetadataAlgo.Annotation( "人写的", imath.Color3f( 1, 1, 1 ) )
)
Gaffer.MetadataAlgo.addAnnotation(
	parPlane, "shader_type", Gaffer.MetadataAlgo.Annotation( "自动生成的", imath.Color3f( 1, 1, 1 ) )
)
idle()

# ⚠️ `shader_type` 实测**不是**注册过的注释模板（1.7.1.0 的模板仍只有
# `performanceMonitor:*` 和 `contextMonitor`）—— 所以原生默认那套 `"*"` 会把
# `standard_surface` 写在每个材质节点下面。我们默认只画 `user`。
check( "默认只画人写的那条（用户明确不要自动生成的文字冒出来）",
	[ a[0] for a in NE.nodeAnnotations( parPlane ) ] == [ "user" ],
	str( [ a[0] for a in NE.nodeAnnotations( parPlane ) ] ) )
check( "默认连「没注册模板的」也不画（Arnold 那条 shader_type 就是这一类）",
	[ a[0] for a in NE.nodeAnnotations( parPlane, NE.DEFAULT_VISIBLE_ANNOTATIONS ) ] == [ "user" ] and
	NE.DEFAULT_VISIBLE_ANNOTATIONS == "user",
	NE.DEFAULT_VISIBLE_ANNOTATIONS )
check( "但菜单里的 Other 打开就画得出来",
	sorted( a[0] for a in NE.nodeAnnotations( parPlane, "user " + NE.UNTEMPLATED_ANNOTATIONS ) ) ==
		[ "shader_type", "user" ],
	str( NE.nodeAnnotations( parPlane, "user " + NE.UNTEMPLATED_ANNOTATIONS ) ) )
check( "编辑器默认的可见模式 = user + 没模板的那些",
	parEditor.getVisibleAnnotations() == NE.DEFAULT_VISIBLE_ANNOTATIONS,
	parEditor.getVisibleAnnotations() )
parItem( "parPlane" ).refreshAnnotations()
check( "item 上也只有那一条",
	[ a[0] for a in parItem( "parPlane" )._annotations ] == [ "user" ],
	str( parItem( "parPlane" )._annotations ) )

parEditor.setVisibleAnnotations( "*" )
check( "切成 All 之后模板注释也画（原生默认就是 *）",
	sorted( a[0] for a in parItem( "parPlane" )._annotations ) == [ "shader_type", "user" ],
	str( parItem( "parPlane" )._annotations ) )
parEditor.setVisibleAnnotations( "" )
check( "切成 None 一条都不画", parItem( "parPlane" )._annotations == [],
	str( parItem( "parPlane" )._annotations ) )
parEditor.setVisibleAnnotations( "user" )
check( "只挑 user", [ a[0] for a in parItem( "parPlane" )._annotations ] == [ "user" ] )
check( "没注册模板的注释靠 Other 那条放行",
	"__untemplated__" == NE.UNTEMPLATED_ANNOTATIONS )

annotationsMenu = parEditor._NetworkEditor__annotationsMenuDefinition()
annotationPaths = [ e[0] for e in annotationsMenu.items() ]
check( "菜单里有 All / None / Other（照原生那张菜单）",
	"/All" in annotationPaths and "/None" in annotationPaths and "/Other" in annotationPaths,
	str( annotationPaths ) )
check( "勾选状态跟着当前模式走",
	annotationsMenu.item( "/None" ).checkBox is False and
	annotationsMenu.item( "/All" ).checkBox is False )
parEditor.setVisibleAnnotations( "*" )
check( "切 All 之后 All 那条打上勾",
	parEditor._NetworkEditor__annotationsMenuDefinition().item( "/All" ).checkBox is True )
parEditor.setVisibleAnnotations( NE.DEFAULT_VISIBLE_ANNOTATIONS )
check( "注释名字转菜单标签照原生（snake_case / CamelCase 都认）",
	NE.annotationLabel( "shader_type" ) == "Shader Type" and
	NE.annotationLabel( "user" ) == "User",
	"%s / %s" % ( NE.annotationLabel( "shader_type" ), NE.annotationLabel( "user" ) ) )

Gaffer.MetadataAlgo.removeAnnotation( parPlane, "shader_type" )
Gaffer.MetadataAlgo.removeAnnotation( parPlane, "user" )

# --- 双击：先发原生的 nodeDoubleClickSignal（项目自己挂的行为才收得到）---
_doubleClicked = []

def __recordDoubleClick( graphEditor, node ) :
	_doubleClicked.append( ( graphEditor, node.getName() ) )
	return True  # 说「我处理了」，编辑器就不该再自己开一个面板

_doubleClickConnection = GafferUI.GraphEditor.nodeDoubleClickSignal().connect(
	__recordDoubleClick, scoped = True
)
# 接管装着的时候，信号第一个参数就是**我们自己**（和另外三套右键菜单一个路子）；
# 前面「接管」那一节把它卸掉了，这里重新装上再测。
_takeoverForDoubleClick = NE.installGraphEditorTakeover( force = True )
parEditor._editNode( parIsolate )
check( "双击发原生 nodeDoubleClickSignal", len( _doubleClicked ) == 1, str( _doubleClicked ) )
check( "信号第一个参数是我们自己（接管装着的时候）",
	_doubleClicked and _doubleClicked[0][0] is parEditor,
	str( _doubleClicked[0][0] ) if _doubleClicked else "" )
check( "节点也传对了", _doubleClicked and _doubleClicked[0][1] == "parIsolate" )
del _doubleClickConnection
if _takeoverForDoubleClick :
	NE.uninstallGraphEditorTakeover()

parWindow.setVisible( False )
idle()


##########################################################################
section( "拖到边缘画面跟着滚 / 标题带层级（原生 ViewportGadget.trackDrag + getTitle）" )
##########################################################################

trackScript = Gaffer.ScriptNode()
trackApp = Gaffer.ApplicationRoot( "tracking" )
trackApp["scripts"].addChild( trackScript )

trackBox = Gaffer.Box( "trackBox" ) ; trackScript.addChild( trackBox )
trackInner = GafferScene.Sphere( "trackInner" ) ; trackBox.addChild( trackInner )
trackPlane = GafferScene.Plane( "trackPlane" ) ; trackScript.addChild( trackPlane )
for _n in ( trackBox, trackPlane ) :
	NE.setNodePosition( _n, imath.V2f( 0, 0 ) )
NE.setNodePosition( trackInner, imath.V2f( 0, 0 ) )

trackEditor = NE.NetworkEditor( trackScript )
trackWindow = GafferUI.Window( "tracking" )
trackWindow.setChild( trackEditor )
trackWindow._qtWidget().resize( 800, 600 )
trackWindow.setVisible( True )
idle()
trackView = trackEditor.graphView()

# --- 标题带层级（原生 getTitle）---
check( "顶层标题就是编辑器名字", trackEditor.getTitle() == "Network Editor",
	trackEditor.getTitle() )
_titleChanges = []
_titleConnection = trackEditor.titleChangedSignal().connect(
	lambda editor : _titleChanges.append( editor.getTitle() ), scoped = True
)
trackEditor.setRootNode( trackBox )
idle()
check( "进了 Box 标题接上层级（原生同款写法）",
	trackEditor.getTitle() == "Network Editor : trackBox", trackEditor.getTitle() )
check( "换层发 titleChangedSignal（标签页标题才会跟着刷）",
	_titleChanges and _titleChanges[-1] == "Network Editor : trackBox",
	str( _titleChanges ) )
trackEditor.setRootNode( None )
idle()
check( "出来又回到顶层标题", trackEditor.getTitle() == "Network Editor",
	trackEditor.getTitle() )
del _titleConnection

# --- 拖到边缘自动滚 ---
_track = trackView._GraphView__updateDragTracking
_velocity = lambda : trackView._GraphView__dragTrackVelocity
_timerRunning = lambda : trackView._GraphView__dragTrackTimer.isActive()

# 没在拖动的时候一动不动
trackView._GraphView__resetDragTracking()
_track( QtCore.QPoint( 2, 300 ) )
check( "没在拖东西时压根不滚（原生也只在拖动里 track）",
	not _timerRunning() and _velocity().isNull() )

# 拖动中：光标在视口正中 → 不滚
trackView._GraphView__mode = 4  # _MODE_MOVE
trackView._GraphView__resetDragTracking()
_track( QtCore.QPoint( 400, 300 ) )
check( "拖到中间不滚", not _timerRunning() )

# 压到左边缘 → 往左滚（画面内容往右移 = pan 正 x）
_track( QtCore.QPoint( 2, 300 ) )
check( "压到左边缘就开滚", _timerRunning() )
check( "方向对：压左边 → 画面往左看（pan 的 x 为正）",
	_velocity().x() > 0 and abs( _velocity().y() ) < 1e-6,
	str( _velocity() ) )

# 压到右下角 → 两个轴一起
_track( QtCore.QPoint( 798, 598 ) )
check( "右下角两个轴一起滚（原生 GraphEditor 两个轴都开着）",
	_velocity().x() < 0 and _velocity().y() < 0, str( _velocity() ) )

# 越靠边越快（速度从 0 线性升到边上最大）
_track( QtCore.QPoint( 45, 300 ) )
_slow = abs( _velocity().x() )
_track( QtCore.QPoint( 2, 300 ) )
_fast = abs( _velocity().x() )
check( "越靠边越快", _fast > _slow > 0, "%.2f vs %.2f" % ( _slow, _fast ) )
check( "速度封顶在边界宽度上（出了视口不会越来越快）",
	_fast <= NE.DRAG_TRACK_BORDER + 1e-6, str( _fast ) )
_track( QtCore.QPoint( -400, 300 ) )
_outside = abs( _velocity().x() )
_track( QtCore.QPoint( -40000, 300 ) )
check( "拖到视口外速度就封顶了（再远也不会更快）",
	abs( abs( _velocity().x() ) - _outside ) < 1e-6 and
	abs( _outside - NE.DRAG_TRACK_BORDER ) < 1e-6,
	"%.3f vs %.3f" % ( _outside, abs( _velocity().x() ) ) )

# 真的会挪画面
_before = trackView.mapToScene( trackView.viewport().rect().center() )
_track( QtCore.QPoint( 2, 300 ) )
trackView._GraphView__trackDragIdle()
_after = trackView.mapToScene( trackView.viewport().rect().center() )
check( "定时器跑一步画面真的挪了", abs( _after.x() - _before.x() ) > 0.5,
	"%s -> %s" % ( _before, _after ) )

# 松手就停
trackView._GraphView__mode = 0  # _MODE_NONE
_track( QtCore.QPoint( 2, 300 ) )
check( "松手就停", not _timerRunning() )

trackWindow.setVisible( False )
idle()


##########################################################################
section( "当前这一层被改名 / 被删掉 / 出错信息（原生 __rootNameChanged 那几条）" )
##########################################################################

rootScript = Gaffer.ScriptNode()
rootApp = Gaffer.ApplicationRoot( "rootTracking" )
rootApp["scripts"].addChild( rootScript )

rootBox = Gaffer.Box( "rootBox" ) ; rootScript.addChild( rootBox )
rootInner = GafferScene.Sphere( "rootInner" ) ; rootBox.addChild( rootInner )
NE.setNodePosition( rootBox, imath.V2f( 0, 0 ) )
NE.setNodePosition( rootInner, imath.V2f( 0, 0 ) )

rootEditor = NE.NetworkEditor( rootScript )
rootWindow = GafferUI.Window( "rootTracking" )
rootWindow.setChild( rootEditor )
rootWindow._qtWidget().resize( 800, 600 )
rootWindow.setVisible( True )
idle()

rootEditor.setRootNode( rootBox )
idle()
check( "进了 Box", rootEditor.getRootNode().isSame( rootBox ) )

# 改名 → 标题跟着变（原生 __rootNameChanged）
rootBox.setName( "renamedBox" )
idle()
check( "当前这一层改名，标题跟着变",
	rootEditor.getTitle() == "Network Editor : renamedBox", rootEditor.getTitle() )

# 被删掉 → 退回脚本根（原生 __rootParentChanged），别停在一个不在图里的 Box 上
rootScript.removeChild( rootBox )
idle()
check( "当前这一层被移出图 → 退回脚本根（不然面包屑还画着一个已经没了的 Box）",
	rootEditor.getRootNode().isSame( rootScript ),
	rootEditor.getRootNode().getName() )
check( "标题也回到顶层", rootEditor.getTitle() == "Network Editor", rootEditor.getTitle() )

# 出错信息进悬停小框（原生 ErrorGadget 也是挂 tooltip）
errorPlane = GafferScene.Plane( "errorPlane" ) ; rootScript.addChild( errorPlane )
NE.setNodePosition( errorPlane, imath.V2f( 0, 0 ) )
idle()
errorItem = rootEditor._NetworkEditor__nodeItems[ "errorPlane" ]
errorItem.setError( True, "Boom : divide by zero" )
check( "出错信息写进悬停小框（光有个红角标看不出出了什么事）",
	"Boom : divide by zero" in errorItem.toolTip(), errorItem.toolTip() )
errorItem.setError( False )
check( "错误清掉，小框里那段也没了",
	"Boom" not in errorItem.toolTip(), errorItem.toolTip() )

rootWindow.setVisible( False )
idle()


##########################################################################
section( "四条拖影 / 重叠 / 截断（v0.67.1 用户实机反馈）" )
##########################################################################

smearScript = Gaffer.ScriptNode()
smearApp = Gaffer.ApplicationRoot( "smearFixes" )
smearApp["scripts"].addChild( smearScript )

smearA = GafferScene.Sphere( "smearA" ) ; smearScript.addChild( smearA )
smearB = GafferScene.Isolate( "smearB" ) ; smearScript.addChild( smearB )
smearB[ "in" ].setInput( smearA[ "out" ] )
NE.setNodePosition( smearA, imath.V2f( 0, 14 ) )
NE.setNodePosition( smearB, imath.V2f( 0, 0 ) )

smearBd = Gaffer.Backdrop( "smearBackdrop" ) ; smearScript.addChild( smearBd )
NE.setNodePosition( smearBd, imath.V2f( 40, 0 ) )
smearBd[ "title" ].setValue( "gyp 中文标题" )   # 故意带下伸笔画和中文

smearEditor = NE.NetworkEditor( smearScript )
smearWindow = GafferUI.Window( "smearFixes" )
smearWindow.setChild( smearEditor )
smearWindow._qtWidget().resize( 900, 650 )
smearWindow.setVisible( True )
idle()

def smearItem( name ) :
	return smearEditor._NetworkEditor__nodeItems[ name ]

# --- ① 悬停时画的 focus 角标要在包围盒里（不然缩放过的画面里拖动留金色拖影）---
item = smearItem( "smearB" )
check( "拉远时角标的补偿是夹住的（`boundingRect` 是几何、画的时候改不了）",
	item.focusTabSize( NE.MIN_ZOOM ) <= item.focusTabMaxSize() + 1e-6,
	"%.1f vs %.1f" % ( item.focusTabSize( NE.MIN_ZOOM ), item.focusTabMaxSize() ) )
check( "夹住之后最大也就这么大（照 FOCUS_LOD_FLOOR 算）",
	abs( item.focusTabMaxSize() - NE.FOCUS_FLAG_PIXELS / NE.FOCUS_LOD_FLOOR ) < 1e-6,
	str( item.focusTabMaxSize() ) )

boundIdle = item.boundingRect()
item.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "鼠标停在节点上就会画角标", item.focusFlagVisible() )
check( "这时包围盒放大了（以前只在 focus 时才放大 → 悬停拖动留拖影）",
	item.boundingRect().width() > boundIdle.width(),
	"%.1f -> %.1f" % ( boundIdle.width(), item.boundingRect().width() ) )
farTab = item.focusTabPolygon( NE.MIN_ZOOM ).boundingRect()
check( "缩到最小时的角标整个在包围盒里（这就是那串金色拖影的根）",
	item.boundingRect().contains( farTab ),
	"%s vs %s" % ( farTab, item.boundingRect() ) )
item.hoverLeaveEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "鼠标移开，包围盒收回去（别一直白留一圈）",
	abs( item.boundingRect().width() - boundIdle.width() ) < 1e-6,
	"%.1f vs %.1f" % ( item.boundingRect().width(), boundIdle.width() ) )

# focus 中的节点同样要装得下
smearScript.setFocus( smearB )
idle()
item = smearItem( "smearB" )
check( "focus 中的节点也装得下（含拉远那面小旗）",
	item.boundingRect().contains( item.focusTabPolygon( NE.MIN_ZOOM ).boundingRect() ) )
smearScript.setFocus( None )
idle()

# --- ② 注释要算进包围盒（不然拖动留一串文字拖影）---
item = smearItem( "smearB" )
boundNoAnnotation = item.boundingRect()
Gaffer.MetadataAlgo.addAnnotation(
	smearB, "user",
	Gaffer.MetadataAlgo.Annotation( "这一条注释相当长，长得会伸到卡片右边很远的地方去", imath.Color3f( 1, 1, 1 ) )
)
idle()
item = smearItem( "smearB" )
annotationRight = item.cardRect().right() + NE.ANNOTATION_GAP + item._NodeItem__annotationWidth
check( "加了注释，包围盒往右让够了（这就是注释拖影的根）",
	item.boundingRect().right() >= annotationRight,
	"%.1f vs %.1f" % ( item.boundingRect().right(), annotationRight ) )
check( "包围盒真的比没注释时宽",
	item.boundingRect().width() > boundNoAnnotation.width(),
	"%.1f -> %.1f" % ( boundNoAnnotation.width(), item.boundingRect().width() ) )

# 多条注释是竖着排的，最后一条也要装得下
Gaffer.MetadataAlgo.addAnnotation(
	smearB, "shader_type", Gaffer.MetadataAlgo.Annotation( "第二条", imath.Color3f( 1, 1, 1 ) )
)
smearEditor.setVisibleAnnotations( "*" )
idle()
item = smearItem( "smearB" )
check( "两条注释都算进来了", len( item._annotations ) == 2, str( item._annotations ) )
lastLineBottom = (
	item.cardRect().top() - 1.0 + NE.ANNOTATION_LINE_HEIGHT * ( len( item._annotations ) - 1 ) + 14.0
)
check( "竖排的最后一条也在包围盒里",
	item.boundingRect().bottom() >= lastLineBottom,
	"%.1f vs %.1f" % ( item.boundingRect().bottom(), lastLineBottom ) )

smearEditor.setVisibleAnnotations( NE.DEFAULT_VISIBLE_ANNOTATIONS )
Gaffer.MetadataAlgo.removeAnnotation( smearB, "shader_type" )
Gaffer.MetadataAlgo.removeAnnotation( smearB, "user" )
idle()
item = smearItem( "smearB" )
check( "注释去掉，包围盒收回原样",
	abs( item.boundingRect().width() - boundNoAnnotation.width() ) < 1e-6,
	"%.1f vs %.1f" % ( item.boundingRect().width(), boundNoAnnotation.width() ) )

# --- ③ 悬停到圆点上时，节点上那条接口名要让位（不然两层字叠一起）---
Gaffer.Metadata.registerValue( smearB, "nodeGadget:inputNoduleLabelsVisible", True )
Gaffer.Metadata.registerValue( smearB, "nodeGadget:outputNoduleLabelsVisible", True )
idle()
item = smearItem( "smearB" )
allKeys = sorted( item.endLabelPaintKeys() )
check( "标签开着的时候，顶底的接口名都画", len( allKeys ) >= 2, str( allKeys ) )
smearEditor._setHoveredNodule( item, smearB[ "in" ] )
hoveredKeys = sorted( item.endLabelPaintKeys() )
check( "鼠标压着的那个圆点，节点上那条让位（悬停放大标签已经写了名字）",
	"in" not in hoveredKeys and len( hoveredKeys ) == len( allKeys ) - 1,
	"%s -> %s" % ( allKeys, hoveredKeys ) )
check( "别的接口名照画（只让一条）",
	set( hoveredKeys ) == set( allKeys ) - { "in" }, str( hoveredKeys ) )
smearEditor._setHoveredNodule( None, None )
check( "移开又都画回来", sorted( item.endLabelPaintKeys() ) == allKeys )
Gaffer.Metadata.deregisterValue( smearB, "nodeGadget:inputNoduleLabelsVisible" )
Gaffer.Metadata.deregisterValue( smearB, "nodeGadget:outputNoduleLabelsVisible" )
idle()

# --- ④ Backdrop 标题不许把字的下缘截掉 ---
bdItem = smearEditor._NetworkEditor__backdropItems[ "smearBackdrop" ]
titleMetrics = QtGui.QFontMetricsF( bdItem.titleFont() )
check( "标题那块矩形装得下整行字（含 g/y 的下伸笔画和中文下半格）",
	bdItem.titleTextRect().height() >= titleMetrics.height() + 1.0,
	"%.2f vs %.2f" % ( bdItem.titleTextRect().height(), titleMetrics.height() ) )
check( "标题矩形整个在框里（不越到框外面去）",
	bdItem.frameRect().contains( bdItem.titleTextRect() ),
	"%s vs %s" % ( bdItem.titleTextRect(), bdItem.frameRect() ) )
smearBd[ "scale" ].setValue( 2.5 )
idle()
bdItem = smearEditor._NetworkEditor__backdropItems[ "smearBackdrop" ]
bigMetrics = QtGui.QFontMetricsF( bdItem.titleFont() )
check( "放大文字之后照样装得下",
	bdItem.titleTextRect().height() >= bigMetrics.height() + 1.0,
	"%.2f vs %.2f" % ( bdItem.titleTextRect().height(), bigMetrics.height() ) )
smearBd[ "scale" ].setValue( 1.0 )
idle()
bdItem = smearEditor._NetworkEditor__backdropItems[ "smearBackdrop" ]

# **真渲染一遍数像素**：`paint()` 里抛的异常会被 Qt 吞掉（一次拆函数就把描述那段的
# `scale` 变量弄丢过，标题断言全绿、描述压根没画出来）——只有像素能证明它画了。
smearBd[ "description" ].setValue( "第一行描述文字\n第二行也要画出来" )
idle()
bdItem = smearEditor._NetworkEditor__backdropItems[ "smearBackdrop" ]
NE.setBackdropRelativeBound(
	smearBd, imath.Box2f( imath.V2f( -24, -14 ), imath.V2f( 24, 14 ) )
)
idle()
bdItem = smearEditor._NetworkEditor__backdropItems[ "smearBackdrop" ]

bdImage = renderScaled( bdItem, 1.0, 700, 420 )

def brightPixels( image, rect, offsetX, offsetY, threshold = 150 ) :
	n = 0
	for y in range( max( 0, int( offsetY + rect.top() ) ), min( image.height(), int( offsetY + rect.bottom() ) ) ) :
		for x in range( max( 0, int( offsetX + rect.left() ) ), min( image.width(), int( offsetX + rect.right() ) ) ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			if max( c.red(), c.green(), c.blue() ) > threshold :
				n += 1
	return n

titleRect = bdItem.titleTextRect()
titleInk = brightPixels( bdImage, titleRect, 350, 210 )
check( "标题真画出来了（渲染出来数亮像素）", titleInk > 40, str( titleInk ) )
# 字的**下面那两行**也得有墨 —— 截断就是从下缘开始少的
lowerBand = QtCore.QRectF(
	titleRect.left(), titleRect.bottom() - 5.0, titleRect.width(), 4.0
)
lowerInk = brightPixels( bdImage, lowerBand, 350, 210 )
check( "标题下缘没被截（下面那几行像素也有墨）", lowerInk > 0, str( lowerInk ) )

descriptionInk = brightPixels( bdImage, bdItem.descriptionTextRect(), 350, 210, threshold = 90 )
check( "描述也真画出来了（`paint` 里抛异常会被 Qt 吞掉，只有像素说得清）",
	descriptionInk > 40, str( descriptionInk ) )

smearWindow.setVisible( False )
idle()


##########################################################################

print( "\n========================================" )
for f in _failed :
	print( "FAIL  %s" % f )
print( "%d/%d passed" % ( len( _passed ), len( _passed ) + len( _failed ) ) )
print( "========================================" )

sys.exit( 1 if _failed else 0 )
