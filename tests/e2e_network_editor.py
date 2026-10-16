# screengrab commandFile：在真实 Gaffer GUI 里验证扩展加载 + 需要 GL 上下文的功能。
#
# 注意：screengrab 执行 commandFile 时 __name__ == 'builtins'，不能加
# `if __name__ == "__main__"` 守卫，否则静默不执行。
#
#   bin/gaffer screengrab -commandFile <本文件> -image <out.png>

import os
import math
import functools
import traceback

import imath
import IECore
import Gaffer
import GafferScene
import GafferUI

from Qt import QtCore, QtGui, QtWidgets

report = []


def check( name, condition, detail = "" ) :
	report.append( "%s  %s  %s" % ( "PASS" if condition else "FAIL", name, detail ) )


import networkEditor as NE

# 「常用 / 喜爱」记到临时目录去 —— 跑测试不许动用户自己那份榜单
import tempfile
NE.setCreatorUsage( NE._CreatorUsage(
	path = os.path.join( tempfile.mkdtemp( prefix = "networkEditorE2EUsage" ), "nodeCreator.json" )
) )

##########################################################################
# 1. 注册
##########################################################################

check( "Editor 类型已注册", "NetworkEditor" in GafferUI.Editor.types() )
check( "GafferUI.NetworkEditor 存在", hasattr( GafferUI, "NetworkEditor" ) )

layouts = GafferUI.Layouts.acquire( application )
check( "已注册进 layout 编辑器菜单", "NetworkEditor" in layouts.registeredEditors() )

##########################################################################
# 2. 建图
##########################################################################

def place( node, x, y ) :
	NE.setNodePosition( node, imath.V2f( x, y ) )

def add( node, x, y ) :
	script.addChild( node )
	place( node, x, y )
	return node

plane   = add( GafferScene.Plane( "groundPlane" ),            -16, 18 )
sphere  = add( GafferScene.Sphere( "heroSphere" ),             -2, 18 )
cube    = add( GafferScene.Cube( "propCube" ),                 12, 18 )
group   = add( GafferScene.Group( "assetGroup" ),              -2, 10 )
xform   = add( GafferScene.Transform( "shotTransform" ),       -2,  3 )
pfilter = add( GafferScene.PathFilter( "heroFilter" ),         16,  3 )
shader  = add( GafferScene.ShaderAssignment( "assignLook" ),   -2, -4 )
attrs   = add( GafferScene.StandardAttributes( "visAttrs" ),   -2,-11 )
prune   = add( GafferScene.Prune( "pruneTemp" ),               -2,-18 )
cam     = add( GafferScene.Camera( "renderCam" ),              18,-18 )
parent  = add( GafferScene.Parent( "parentCamera" ),           -2,-25 )
opts    = add( GafferScene.StandardOptions( "renderOptions" ), -2,-32 )
outs    = add( GafferScene.Outputs( "beautyOutputs" ),         -2,-39 )

box = add( Gaffer.Box( "lightRigBox" ), 20, -6 )
inner = GafferScene.Sphere( "innerLight" )
box.addChild( inner )
# 一个 setup 过的 BoxIn：原生在它上面不画 `+`（`setVisible( !plug() )`）
boxInside = Gaffer.BoxIn( "innerBoxIn" )
box.addChild( boxInside )
boxInside.setup( GafferScene.ScenePlug() )
# 故意不给位置：进 Box 时应该像原生一样自动排好（问题 1）
innerChain = []
for i in range( 4 ) :
	n = GafferScene.Isolate( "innerStep%d" % i )
	box.addChild( n )
	n["in"].setInput( innerChain[-1]["out"] if innerChain else inner["out"] )
	innerChain.append( n )

expr = add( Gaffer.Expression( "radiusExpression" ), 14, 24 )
expr.setExpression( 'parent["heroSphere"]["radius"] = 1.0 + context.getFrame() * 0.01' )

# 形状：真的 ArnoldLight（无头环境碰不得，只能在这儿验）、Dot、Camera
import GafferArnold

surface = GafferArnold.ArnoldShader( "aiStandardSurface" )
surface.loadShader( "standard_surface" )
script.addChild( surface )
NE.setNodePosition( surface, imath.V2f( 34, -4 ) )

keyLight = GafferArnold.ArnoldLight( "keyLight" )
keyLight.loadShader( "point_light" )
script.addChild( keyLight )
NE.setNodePosition( keyLight, imath.V2f( 30, 6 ) )

# ArnoldMeshLight 派生自 `GafferScene::MeshLight`（不是 Light），单独验它。
# 摆在右侧灯光区之外，别和「Tab 面板建节点摆在鼠标位置」那条的落点 (25, 16.67) 撞上。
meshLight = GafferArnold.ArnoldMeshLight( "meshLight" )
script.addChild( meshLight )
NE.setNodePosition( meshLight, imath.V2f( 44, 6 ) )

routeDot = Gaffer.Dot( "routeDot" )
script.addChild( routeDot )
routeDot.setup( prune["out"] )
routeDot["in"].setInput( prune["out"] )
NE.setNodePosition( routeDot, imath.V2f( 8, -21 ) )

backdrop = Gaffer.Backdrop( "assetsBackdrop" )
script.addChild( backdrop )
NE.setNodePosition( backdrop, imath.V2f( -2, 18 ) )
backdrop["title"].setValue( "资产" )
backdrop["__uiBound"] = Gaffer.Box2fPlug(
	"__uiBound", Gaffer.Plug.Direction.In,
	imath.Box2f( imath.V2f( -18, -6 ), imath.V2f( 18, 6 ) ),
	flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
)

group["in"][0].setInput( plane["out"] )
group["in"][1].setInput( sphere["out"] )
group["in"][2].setInput( cube["out"] )
xform["in"].setInput( group["out"] )
shader["in"].setInput( xform["out"] )
shader["filter"].setInput( pfilter["out"] )
attrs["in"].setInput( shader["out"] )
attrs["filter"].setInput( pfilter["out"] )
prune["in"].setInput( attrs["out"] )
parent["in"].setInput( prune["out"] )
parent["children"][0].setInput( cam["out"] )
opts["in"].setInput( parent["out"] )
outs["in"].setInput( opts["out"] )

# 各种状态：停用 / 折叠连线 / 书签 / 注释 / focus
prune["enabled"].setValue( False )
NE.setNodeConnectionsMinimised( pfilter, Gaffer.Plug.Direction.Out, True )
Gaffer.MetadataAlgo.setBookmarked( outs, True )
Gaffer.MetadataAlgo.addAnnotation( xform, "user", Gaffer.MetadataAlgo.Annotation( "镜头级偏移" ) )
script.setFocus( outs )
script.selection().add( shader )

##########################################################################
# 2b. 工作室 pipeline 快捷键的替身
##########################################################################
#
# 工作室的启动脚本常往 `GraphEditor.instanceCreatedSignal` 上挂快捷键：S 弹「切换上下文」
# 分组菜单（条目带 checkBox）、Q 弹「快捷收藏」建节点菜单（命令是 NodeMenu 包装过的）、
# M 这类一键操作。做法都是「造一个 `GafferUI.Menu` 再 `popup()`」。这里照同样的写法挂三个，
# 验证编辑器接得住、并用自己的面板画出来。

pipelineMenus = []

def pipelineSwitchTo( state, name ) :
	pass

def pipelinePopup( editor, definition, title ) :
	menu = GafferUI.Menu( definition, title = title )
	pipelineMenus.append( menu )
	menu.popup( editor )

def pipelineKeyPress( editor, event ) :

	if event.modifiers != event.Modifiers.None_ :
		return False

	if event.key == "S" :
		definition = IECore.MenuDefinition()
		for switchGroup, switchNames, switchCurrent in (
			( "Switch To Shot", [ "sh010", "sh020" ], "sh010" ),
			( "Switch To Layer", [ "default", "bg" ], "default" ),
		) :
			for switchName in switchNames :
				definition.append(
					"/%s/%s" % ( switchGroup, switchName ),
					{
						"command" : functools.partial( pipelineSwitchTo, name = switchName ),
						"checkBox" : switchName == switchCurrent,
					}
				)
		pipelinePopup( editor, definition, "Switch Context" )
		return True

	if event.key == "Q" :
		definition = IECore.MenuDefinition()
		for path, creator in (
			( "/Scene/Sphere", GafferScene.Sphere ),
			( "/Scene/Group", GafferScene.Group ),
			( "/Utility/Dot", Gaffer.Dot ),
		) :
			definition.append( path, { "command" : GafferUI.NodeMenu.nodeCreatorWrapper( creator ) } )
		pipelinePopup( editor, definition, "Favourites" )
		return True

	return event.key == "M"

def pipelineEditorCreated( editor ) :
	editor.keyPressSignal().connect( pipelineKeyPress, scoped = False )

GafferUI.GraphEditor.instanceCreatedSignal().connect( pipelineEditorCreated, scoped = False )

# 工作室脚本另外常做的两件事：给原生没上色的节点类型补颜色（Filter、灯光），以及给材质节点
# 挂一条按模板生成的注释（`{name}` = 着色器名）。编辑器要读得到前者、默认不画后者。
Gaffer.Metadata.registerValue( GafferScene.Filter, "nodeGadget:color", imath.Color3f( 0.6, 0.42, 0.18 ) )
Gaffer.Metadata.registerValue( GafferScene.Light, "nodeGadget:color", imath.Color3f( 0.75, 0.56, 0.0 ) )
Gaffer.Metadata.registerValue( GafferArnold.ArnoldShader, "annotation:shader_type:text", "{name}" )
Gaffer.Metadata.registerValue( GafferArnold.ArnoldShader, "annotation:shader_type:color", imath.Color3f( 0.2 ) )

##########################################################################
# 3. 编辑器
##########################################################################

editor = GafferUI.Editor.create( "NetworkEditor", script )
check( "Editor.create 造得出来", isinstance( editor, NE.NetworkEditor ) )

window = GafferUI.Window( "NetworkEditor e2e" )
window.setChild( editor )
window._qtWidget().resize( 1200, 820 )
window.setVisible( True )
GafferUI.EventLoop.waitForIdle()

items = editor._NetworkEditor__nodeItems
edges = editor._NetworkEditor__edgeItems

check( "Backdrop 单独成 item", "assetsBackdrop" in editor._NetworkEditor__backdropItems )
check( "节点都在", len( items ) == 19, str( len( items ) ) )

# --- 形状（真的 ArnoldLight 只能在这儿验，无头环境它会 SIGABRT）---
check( "Dot -> 小圆点", NE.nodeShape( routeDot ) == NE.SHAPE_DOT, NE.nodeShape( routeDot ) )
check( "Expression -> 小方块（原生 AuxiliaryNodeGadget）", NE.nodeShape( expr ) == NE.SHAPE_AUXILIARY, NE.nodeShape( expr ) )
check( "小方块写首字母", NE.auxiliaryLabel( expr ) == "e", NE.auxiliaryLabel( expr ) )
check( "普通节点 -> 矩形", NE.nodeShape( keyLight ) == NE.SHAPE_RECTANGLE, NE.nodeShape( keyLight ) )
check( "Dot item 是 DOT_SIZE 见方", abs( items[ "routeDot" ]._width - NE.DOT_SIZE ) < 1e-6 and abs( items[ "routeDot" ]._height - NE.DOT_SIZE ) < 1e-6 )
check( "点光画点光图标（不再统一小灯泡）", items[ "keyLight" ]._glyph == NE.GLYPH_POINT_LIGHT, str( items[ "keyLight" ]._glyph ) )
check( "ArnoldMeshLight 画网格光图标（不再没图标 / 当普通处理器）",
	items[ "meshLight" ]._glyph == NE.GLYPH_MESH_LIGHT, str( items[ "meshLight" ]._glyph ) )
# 真的 ArnoldLight（point_light）也有 `parameters` + `layout:section`，但**不许**走
# 分栏那套（用户反馈：这套样式在灯光上观感不对）——灯光照旧细色带 + 名字居中 + 卡外标签。
check( "真灯光节点不分栏",
	NE.buildSectionData( keyLight, NE.noduleLayout( keyLight ) ) == {},
	str( NE.buildSectionData( keyLight, NE.noduleLayout( keyLight ) ) ) )
check( "灯光卡片没有分栏 header（也就没有折叠三角）",
	not any( items[ "keyLight" ]._NodeItem__sectionHeaders.get( s )
		for s in ( "left", "right" ) ),
	str( items[ "keyLight" ]._NodeItem__sectionHeaders ) )
check( "灯光卡片没被分栏撑宽（走原生几何，和上面「高度 = 原生」那条一起把关）",
	items[ "keyLight" ]._NodeItem__sectionedLabelWidth == 0.0,
	str( items[ "keyLight" ]._NodeItem__sectionedLabelWidth ) )
check( "相机画相机图标", items[ "renderCam" ]._glyph == NE.GLYPH_CAMERA, str( items[ "renderCam" ]._glyph ) )
check( "PathFilter 画漏斗", items[ "heroFilter" ]._glyph == NE.GLYPH_FILTER, str( items[ "heroFilter" ]._glyph ) )
check( "材质画材质球", items[ "aiStandardSurface" ]._glyph == NE.GLYPH_SHADER, str( items[ "aiStandardSurface" ]._glyph ) )

# --- 真材质节点的侧边接口徽章 ---
surfaceItem = items[ "aiStandardSurface" ]
surfaceLayout = NE.noduleLayout( surface )
check( "材质参数挂在左边", len( surfaceLayout[ "left" ] ) >= 2, str( len( surfaceLayout[ "left" ] ) ) )
check( "out 挂在右边", len( surfaceLayout[ "right" ] ) >= 1, str( [ p.getName() for p in surfaceLayout[ "right" ] ] ) )
check( "材质节点有多行侧边接口", surfaceItem._sideRows >= 2, str( surfaceItem._sideRows ) )
check( "材质卡片比普通节点高", surfaceItem._height > NE.NODE_HEIGHT, str( surfaceItem._height ) )
# **分栏材质节点：文字画在卡片里面**（名字进顶栏的条里，侧边的文字信息写在节点内部，
# 外侧只留小圆点和展开收起的三角）——
# 卡片自己撑宽到放得下最长那条参数名，名字独占顶栏那条，外侧只剩圆点 + 折叠三角。
# 非分栏节点（Isolate 的 filter 那种）照旧画在卡外。
surfaceSectioned = bool( surfaceItem._NodeItem__sectionData )
check( "真材质节点是分栏的（standard_surface 那 11 栏）", surfaceSectioned,
	str( list( surfaceItem._NodeItem__sectionData ) ) )
if surfaceSectioned :
	check( "分栏材质：外侧不写字了（__sideLabelWidth 归零）",
		surfaceItem._NodeItem__sideLabelWidth == 0.0,
		str( surfaceItem._NodeItem__sideLabelWidth ) )
	check( "分栏材质：卡片自己撑宽到放得下参数名",
		surfaceItem.cardRect().width()
		>= surfaceItem._NodeItem__sectionedLabelWidth
			+ 2 * ( NE.NODULE_RADIUS + NE.SIDE_LABEL_GAP ),
		"%.1f vs %.1f" % ( surfaceItem.cardRect().width(),
			surfaceItem._NodeItem__sectionedLabelWidth
				+ 2 * ( NE.NODULE_RADIUS + NE.SIDE_LABEL_GAP ) ) )
	check( "分栏材质：参数行排在顶栏条**下面**（顶栏留给名字）",
		all(
			y >= surfaceItem.cardRect().top() + NE.SIDE_ROWS_BASE_UNITS * NE.PX_PER_UNIT
			for side in ( "left", "right" )
			for name, y in surfaceItem._NodeItem__sectionHeaders.get( side, [] )
		),
		str( surfaceItem._NodeItem__sectionHeaders ) )

	# --- 颜色条当标题条 / 宽度收窄 / 输出口不分栏 / 三角与栏名都能点 ---
	check( "输出口不参与分栏（`out` 身上那个 layout:section 不该长出一栏）",
		not surfaceItem._NodeItem__sectionHeaders.get( "right" ) and
		all(
			p.direction() == Gaffer.Plug.Direction.In
			for side, groups in surfaceItem._NodeItem__sectionData.items()
			for name, plugs in groups for p in plugs
		),
		str( surfaceItem._NodeItem__sectionHeaders.get( "right" ) ) )
	check( "真材质卡片没那么宽了（旧版 273.9px）",
		surfaceItem.cardRect().width() < 220.0,
		"%.1f" % surfaceItem.cardRect().width() )
	check( "卡内标签夹在上限内",
		surfaceItem._NodeItem__sectionedLabelWidth <= NE.SECTION_LABEL_MAX + 1e-3,
		"%.1f" % surfaceItem._NodeItem__sectionedLabelWidth )

	# 真的走 view 层点一下：三角 / 栏名两处都要切换（`shape()` 的 fillRule 一错就全哑）
	# 注意：全局那个 `view` 到本文件 640 多行才定义，这里得自己取。
	sectionView = editor.graphView()
	surfSection = surfaceItem._NodeItem__sectionHeaders[ "left" ][ 0 ][ 0 ]
	for dx, what in ( ( 0.0, "三角（卡边线）" ), ( 40.0, "栏名（Houdini 整行）" ) ) :
		liveItem = editor._NetworkEditor__nodeItems[ "aiStandardSurface" ]
		liveY = dict( liveItem._NodeItem__sectionHeaders[ "left" ] )[ surfSection ]
		livePoint = sectionView.mapFromScene( liveItem.mapToScene(
			QtCore.QPointF( liveItem.cardRect().left() + dx, liveY ) ) )
		before = NE.sectionCollapsed( surface, "left", surfSection )
		sectionView.mousePressEvent( QtGui.QMouseEvent(
			QtCore.QEvent.MouseButtonPress, QtCore.QPointF( livePoint ),
			QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier ) )
		GafferUI.EventLoop.waitForIdle()
		check( "点%s 真的收放了这一栏" % what,
			NE.sectionCollapsed( surface, "left", surfSection ) != before,
			"%s -> %s" % ( before, NE.sectionCollapsed( surface, "left", surfSection ) ) )

	# 展开一栏之后，参数行上点下去是连线、不是收放。
	# **显式展开**，别指望上面两次点击的奇偶性（点两次就回到收起了）。
	NE.setSectionCollapsed( surface, "left", surfSection, False )
	GafferUI.EventLoop.waitForIdle()
	liveItem = editor._NetworkEditor__nodeItems[ "aiStandardSurface" ]
	check( "显式展开生效了", not NE.sectionCollapsed( surface, "left", surfSection ) )
	if not NE.sectionCollapsed( surface, "left", surfSection ) :
		paramRows = [ r for r in liveItem._NodeItem__sectionRows( "left" ) if r[0] == "param" ]
		if paramRows :
			# 一个参数行现在装的是一**簇**插口（展开的 Color3f 会挤在同一行）
			paramY = liveItem._NodeItem__nodulePositions[
				NE.plugKey( surface, paramRows[0][1][0] ) ].y()
			check( "参数行不算 header（点它是连线）",
				liveItem.sectionAt(
					QtCore.QPointF( liveItem.cardRect().left() + 40.0, paramY ) ) is None,
				str( liveItem.sectionAt(
					QtCore.QPointF( liveItem.cardRect().left() + 40.0, paramY ) ) ) )
			check( "参数行的圆点照旧接得上",
				liveItem.noduleAt(
					QtCore.QPointF( liveItem.cardRect().left(), paramY ) ) is not None )
		# 收回去，别把后面的断言带跑
		NE.setSectionCollapsed( surface, "left", surfSection, True )
		GafferUI.EventLoop.waitForIdle()
check(
	"悬停要显示的标签取自 noduleLayout:label / 插口名",
	all( NE.noduleLabel( p ) for p in surfaceLayout[ "left" ] )
)
check( "只有 filter 一个侧边接口的场景节点没长高", abs( items[ "pruneTemp" ]._height - NE.NODE_HEIGHT ) < 1e-3, str( items[ "pruneTemp" ]._height ) )

##########################################################################
# 3b. 问题 2：节点大小 / 接口位置和原生节点编辑器一模一样
##########################################################################

nativeGadget = editor._NetworkEditor__graphGadget()
check( "拿得到原生 GraphGadget 当尺子", nativeGadget is not None )

if nativeGadget is not None :

	# 契约：**高度照原生；宽度以原生为下限，名字放不下就撑宽**。
	# 死守原生宽度会出现 `Create...tSetup` 这种截字 —— 真实 GUI 里 Gaffer 有自己的
	# 全局字体，和我们画名字用的字体不是一回事，所以这里必须以「放得下」为准。
	badHeight = []
	tooNarrow = []
	widened = []
	for name, item in items.items() :
		gadget = nativeGadget.nodeGadget( script[ name ] )
		if gadget is None :
			continue
		bound = gadget.bound()
		w = ( bound.max().x - bound.min().x ) * NE.PX_PER_UNIT
		h = ( bound.max().y - bound.min().y ) * NE.PX_PER_UNIT
		# 分栏材质节点的高度/接口排布是我们自己的（Houdini 式分区收放），
		# 不跟原生 CompoundNodule 逐点对齐 —— 高度这条对不上，宽度仍要比。
		sectioned = bool( NE.buildSectionData( script[ name ], NE.noduleLayout( script[ name ] ) ) )
		if not sectioned and abs( item._height - h ) > 1e-3 :
			badHeight.append( "%s ours %.2f native %.2f" % ( name, item._height, h ) )
		if item._width < w - 1e-3 :
			tooNarrow.append( "%s ours %.2f native %.2f" % ( name, item._width, w ) )
		if item._width > w + 1e-3 :
			widened.append( "%s %.0f->%.0f" % ( name, w, item._width ) )

	check( "所有节点高度 = 原生 NodeGadget", not badHeight, "; ".join( badHeight[:4] ) )
	check( "所有节点宽度不小于原生", not tooNarrow, "; ".join( tooNarrow[:4] ) )
	check( "（参考）为放下名字撑宽了这些", True, "%d 个：%s" % ( len( widened ), "; ".join( widened[:6] ) ) )

	check(
		"名字短的场景节点还是 11 x 4.164 单位",
		abs( items[ "pruneTemp" ]._width - 11.0 * NE.PX_PER_UNIT ) < 1e-3,
		str( items[ "pruneTemp" ]._width )
	)
	check(
		"Dot 是 2.5 单位",
		abs( items[ "routeDot" ]._width - 2.5 * NE.PX_PER_UNIT ) < 1e-3,
		str( items[ "routeDot" ]._width )
	)
	check(
		"Expression 小方块是 2 单位",
		abs( items[ "radiusExpression" ]._width - 2.0 * NE.PX_PER_UNIT ) < 1e-3,
		str( items[ "radiusExpression" ]._width )
	)

	# 接口位置逐个比：y 必须和原生一致；x 是按卡片撑宽的比例拉开的（撑宽了才不为 1）
	badNodules = []
	offCard = []
	for name in ( "assignLook", "assetGroup", "aiStandardSurface" ) :
		item = items[ name ]
		if NE.buildSectionData( script[ name ], NE.noduleLayout( script[ name ] ) ) :
			continue  # 分栏节点的接口排布是我们自己的，逐点对不上原生
		gadget = nativeGadget.nodeGadget( script[ name ] )
		scale = item._width / item._NodeItem__nativeWidth
		for section, plugs in NE.noduleLayout( script[ name ] ).items() :
			for plug in plugs :
				nodule = gadget.nodule( plug )
				if nodule is None :
					continue
				centre = nodule.transformedBound( gadget ).center()
				ours = item.nodulePosition( plug )
				if (
					abs( ours.x() - centre.x * NE.PX_PER_UNIT * scale ) > 1e-3 or
					abs( ours.y() + centre.y * NE.PX_PER_UNIT ) > 1e-3
				) :
					badNodules.append( "%s.%s" % ( name, plug.getName() ) )
				if abs( ours.x() ) > item._width / 2.0 + 1e-3 or abs( ours.y() ) > item._height / 2.0 + 1e-3 :
					offCard.append( "%s.%s" % ( name, plug.getName() ) )

	check( "接口位置 = 原生 nodule（x 跟着卡片宽度等比）", not badNodules, ", ".join( badNodules[:6] ) )
	check( "接口都还贴在卡片上（没跑出去）", not offCard, ", ".join( offCard[:6] ) )

# 真实 GUI 里 Gaffer 有自己的全局字体，和我们画名字的字体不是一回事 ——
# 所以这两条是**在真机上**才有意义的把关：一个字都不许截，一个图标都不许丢。
elidedNames = [ name for name, item in items.items() if not item.nameFits() ]
check( "节点名一个都没被截", not elidedNames, str( elidedNames ) )

lostGlyphs = [
	name for name, item in items.items()
	if item._glyph is not None and item._width < item._NodeItem__contentsWidth() - 1e-6
]
check( "有图标的节点都留够了位置（图标不会被丢）", not lostGlyphs, str( lostGlyphs ) )

glyphNodes = [ name for name, item in items.items() if item._glyph is not None ]
check( "（参考）这些节点画了类型图标", len( glyphNodes ) >= 4, str( sorted( glyphNodes ) ) )

##########################################################################
# 3c. 问题 2/5：接口圆点与节点颜色都来自原生元数据
##########################################################################

# 节点色：原生 startup/gui/graphEditor.py 注册的（工作室启动脚本也可能在同一个键上再注册）
nodeColors = dict( ( name, NE.nodeColor( script[ name ] ) ) for name in items )
check( "节点不是一律同一个灰", len( set( nodeColors.values() ) ) >= 3, str( sorted( set( nodeColors.values() ) ) ) )
check(
	"SceneProcessor 有自己的颜色（原生注册的）",
	NE.nodeColor( shader ) != NE.nodeColor( plane ),
	"%s vs %s" % ( NE.nodeColor( shader ), NE.nodeColor( plane ) )
)
check(
	"PathFilter 又是另一个颜色",
	NE.nodeColor( pfilter ) not in ( NE.nodeColor( shader ), NE.nodeColor( plane ) ),
	"%s" % NE.nodeColor( pfilter )
)
check(
	"卡片主体 = 节点色压暗（色相还在）",
	NE.cardColor( shader ) != NE.nodeColor( shader ),
	"%s -> %s" % ( NE.nodeColor( shader ), NE.cardColor( shader ) )
)
check( "灯光节点拿到灯光色", NE.nodeColor( keyLight ) != NE.nodeColor( plane ), NE.nodeColor( keyLight ) )

# 接口圆点色：原生按插口类型注册的 `nodule:color`
sceneNodule = NE.noduleColor( shader[ "in" ] )
filterNodule = NE.noduleColor( shader[ "filter" ] )
check( "ScenePlug 圆点有专属色", sceneNodule != "#666666", sceneNodule )
check( "FilterPlug 圆点是另一个色", filterNodule != sceneNodule, "%s vs %s" % ( sceneNodule, filterNodule ) )
check(
	"材质插口圆点又不一样",
	len( set( NE.noduleColor( p ) for p in NE.noduleLayout( surface )[ "left" ][:6] ) ) >= 2,
	str( set( NE.noduleColor( p ) for p in NE.noduleLayout( surface )[ "left" ][:6] ) )
)
check(
	"圆点颜色写进了 item",
	items[ "assignLook" ]._NodeItem__noduleColors.get( "filter" ) is not None
)

##########################################################################
# 3d. 问题 4：接口悬停放大 + 显示名字
##########################################################################

surfaceLeft = NE.noduleLayout( surface )[ "left" ][0]
boundBefore = surfaceItem.boundingRect().width()
editor._setHoveredNodule( surfaceItem, surfaceLeft )
check(
	"悬停记到 item 上",
	surfaceItem.hoveredNodule() == NE.plugKey( surface, surfaceLeft ),
	str( surfaceItem.hoveredNodule() )
)
check(
	"包围盒放大（放得下大圆点 + 标签）",
	surfaceItem.boundingRect().width() >= boundBefore,
	"%s vs %s" % ( surfaceItem.boundingRect().width(), boundBefore ),
)
check( "悬停时抬到上层", surfaceItem.zValue() > 10 )

##########################################################################
# 3e. Shift 多选 + pipeline 快捷键转发
##########################################################################

editor._clearSelection()
editor._selectClicked( items[ "groundPlane" ], QtCore.Qt.NoModifier )
editor._selectClicked( items[ "heroSphere" ], QtCore.Qt.ShiftModifier )
check(
	"Shift 点击多选",
	sorted( n.getName() for n in script.selection() ) == [ "groundPlane", "heroSphere" ],
	str( sorted( n.getName() for n in script.selection() ) )
)
editor._clearSelection()

# pipeline 快捷键弹出来的菜单要走**我们自己画的面板**，不能是原生那个搜索式 QMenu
nativePopups = []
originalMenuPopup = GafferUI.Menu.popup
def countingPopup( menu, *args, **kw ) :
	nativePopups.append( menu )
GafferUI.Menu.popup = countingPopup
try :
	switchEvent = QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_S, QtCore.Qt.NoModifier )
	switchHandled = editor._forwardShortcutKey( switchEvent )
finally :
	GafferUI.Menu.popup = originalMenuPopup

check( "S（pipeline 的切换上下文）被接住了", switchHandled )

panel = editor._NetworkEditor__creatorPopup
check( "弹的是我们自己的面板", panel is not None and panel.isVisible() if panel else False,
	str( panel ) )
if panel is not None :
	check( "面板里有条目", panel.rowCount() > 0, str( panel.rowCount() ) )
	check( "面板有标题（取自原生菜单）", bool( panel._NodeCreatorPopup__title.text() ),
		panel._NodeCreatorPopup__title.text() )

# --- 砍掉隐藏引擎 · 第三步：pipeline 那些快捷键现在挂在**我们**身上 ---
#
# 接管装上之后我们主动发过一次 `GraphEditor.instanceCreatedSignal()( self )`，
# pipeline 启动脚本的那些 handler 于是连的是**我们的** keyPressSignal。
# 把隐藏引擎整个关掉再按一次 S：还能接住、还是弹我们自己的面板，才算真的不靠引擎了。
import networkEditor.editor as NEE

check( "接管装着（真机 startup 装的）", isinstance( editor, GafferUI.GraphEditor ) )
check( "我们已经把自己宣布出去了", editor._NetworkEditor__announced )

if panel is not None :
	panel.hide()

originalEngineEnabled = NEE.engineEnabled
NEE.engineEnabled = lambda : False
noEnginePopups = []
GafferUI.Menu.popup = countingPopup
try :
	check( "引擎真关掉了", editor._NetworkEditor__engine() is None )
	noEngineHandled = editor._forwardShortcutKey(
		QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_S, QtCore.Qt.NoModifier ) )
finally :
	GafferUI.Menu.popup = originalMenuPopup
	NEE.engineEnabled = originalEngineEnabled

check( "没有隐藏引擎也能接住 pipeline 的 S", noEngineHandled )
noEnginePanel = editor._NetworkEditor__creatorPopup
check( "而且还是弹我们自己的面板",
	noEnginePanel is not None and noEnginePanel.isVisible() and noEnginePanel.rowCount() > 0,
	str( noEnginePanel.rowCount() if noEnginePanel is not None else None ) )
if noEnginePanel is not None :
	noEnginePanel.hide()
panel = editor._NetworkEditor__creatorPopup
if panel is not None :
	panel.hide()
check( "没有再去弹原生 QMenu", not nativePopups, str( len( nativePopups ) ) )

# 回归：pipeline 的 `Q`（快捷收藏）菜单里全是「建节点」条目 —— 命令是 NodeMenu 包装过的，
# 里面有 `assert menu.ancestor( GraphEditor )`。面板点下去必须真的建出节点，不能报 assert。
warnings = []
warningHandler = IECore.CapturingMessageHandler()
nativePopupsQ = []
originalPopupQ = GafferUI.Menu.popup
def countingPopupQ( menu, *args, **kw ) :
	nativePopupsQ.append( menu )

script.selection().clear()
before = set( n.getName() for n in NE.collectNodes( script ) )
GafferUI.Menu.popup = countingPopupQ
try :
	with warningHandler :
		editor._forwardShortcutKey(
			QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_Q, QtCore.Qt.NoModifier )
		)
		GafferUI.EventLoop.waitForIdle()
		favouritesPanel = editor._NetworkEditor__creatorPopup
		entryCount = favouritesPanel.rowCount() if favouritesPanel else 0
		if entryCount :
			# 面板是分层的（Q 的菜单有 Scene / Utility 两个分组）：
			# 一层层钻到有可执行条目的那一列 —— **每一层都在它自己那一列上找**，
			# 一直问第 0 列的话就永远在根层原地打转
			panelColumn = 0
			for unusedDepth in range( 4 ) :
				itemRow = next(
					(
						i for i in range( favouritesPanel.rowCount( panelColumn ) )
						if favouritesPanel.rowAt( i, panelColumn )[2] is not None
					),
					None
				)
				if itemRow is not None :
					favouritesPanel.activateRow( itemRow, panelColumn )
					break
				categoryRow = next(
					(
						i for i in range( favouritesPanel.rowCount( panelColumn ) )
						if favouritesPanel.rowAt( i, panelColumn )[3]
					),
					None
				)
				if categoryRow is None :
					break
				favouritesPanel.activateRow( categoryRow, panelColumn )
				panelColumn = favouritesPanel.columnCount() - 1
			GafferUI.EventLoop.waitForIdle()
		if favouritesPanel is not None :
			favouritesPanel.hide()
finally :
	GafferUI.Menu.popup = originalPopupQ

createdFromQ = [ n.getName() for n in NE.collectNodes( script ) if n.getName() not in before ]
assertionWarnings = [
	m.message for m in warningHandler.messages
	if "AssertionError" in m.message or "assert" in m.message
]

check( "Q（快捷收藏）走的是我们的面板", entryCount > 0, str( entryCount ) )
# 分组菜单照分组分列，不摊成一长串堆在一起
if favouritesPanel is not None :
	favouritesRootRows = [ favouritesPanel.rowAt( i ) for i in range( entryCount ) ]
	check(
		"Q 的面板根层只列分组",
		entryCount > 1 and all( r[2] is None and r[3] for r in favouritesRootRows ),
		str( [ ( r[0], r[3] ) for r in favouritesRootRows ] )
	)
check( "点条目真的建出了节点", len( createdFromQ ) >= 1, str( createdFromQ ) )
check( "没有 assert 报错（NodeMenu 那个 assert graphEditor）", not assertionWarnings, str( assertionWarnings[:1] ) )
check( "也没退回原生 QMenu", not nativePopupsQ, str( len( nativePopupsQ ) ) )
if createdFromQ :
	script.undo()
	GafferUI.EventLoop.waitForIdle()

forwardEvent = QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_M, QtCore.Qt.NoModifier )
check(
	"pipeline 快捷键 M 被接住",
	editor._forwardShortcutKey( forwardEvent )
)
unusedEvent = QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_F5, QtCore.Qt.NoModifier )
check( "没人要的键转发后返回 False", not editor._forwardShortcutKey( unusedEvent ) )

# --- 连线配色 ---
#
# 注意：有的扩展会给 focus 节点的**整条上游链**注册
# `connectionGadget:color` 做高亮。我们和原生一样尊重这个覆盖，
# 所以量类型配色之前得先把 focus 清掉，否则量到的全是高亮色。
def sampleWireColors() :
	result = {}
	for e in editor._NetworkEditor__edgeItems :
		result[ ( e.edge.srcNode.getName(), e.edge.dstNode.getName() ) ] = NE.wireColor( e.edge )
	return result

highlighted = sampleWireColors().get( ( "assetGroup", "shotTransform" ) )

script.setFocus( None )
GafferUI.EventLoop.waitForIdle()
GafferUI.EventLoop.waitForIdle()

wireColors = sampleWireColors()
sceneWire = wireColors.get( ( "assetGroup", "shotTransform" ) )
filterWire = wireColors.get( ( "heroFilter", "assignLook" ) )
exprWire = wireColors.get( ( "radiusExpression", "heroSphere" ) )
# 连线按接口类型色上色（gui 启动脚本注册的场景蓝 / filter 金）
nativeStyle = GafferUI.StandardStyle()
def styleHex( colorName ) :
	c = nativeStyle.getColor( getattr( GafferUI.StandardStyle.Color, colorName ) )
	return "#%02x%02x%02x" % tuple(
		max( 0, min( 255, int( round( x * 255.0 ) ) ) ) for x in ( c[0], c[1], c[2] )
	)

sceneQ, filterQ = QtGui.QColor( sceneWire ), QtGui.QColor( filterWire )
check( "场景连线是蓝的", sceneQ.blue() > sceneQ.green() > sceneQ.red(), str( sceneWire ) )
check( "filter 连线是金的", filterQ.red() > filterQ.green() > filterQ.blue(), str( filterWire ) )
check( "场景连线和 filter 连线颜色不同", filterWire != sceneWire, "%s %s" % ( sceneWire, filterWire ) )
check( "表达式连线 = 原生 AuxiliaryConnectionColor", exprWire == styleHex( "AuxiliaryConnectionColor" ), str( exprWire ) )

# 画出来的线也是这个颜色（悬停 / focus 之外的常态）
paintedScene = [
	e for e in editor._NetworkEditor__edgeItems
	if ( e.edge.srcNode.getName(), e.edge.dstNode.getName() ) == ( "assetGroup", "shotTransform" )
]
check( "场景连线按类型色画出来",
	bool( paintedScene ) and paintedScene[0]._color.name() == sceneWire,
	str( [ e._color.name() for e in paintedScene ] ) )

# 每条连线都不穿过自己两端节点的卡片
def wireCardHits( item, rect, p0, p1 ) :
	inner = rect.adjusted( 2, 2, -2, -2 )
	if inner.contains( p0 ) or inner.contains( p1 ) :
		return 0
	path = item.path()
	hits = 0
	for i in range( 401 ) :
		p = path.pointAtPercent( i / 400.0 )
		if min( math.hypot( p.x() - q.x(), p.y() - q.y() ) for q in ( p0, p1 ) ) < 8 :
			continue
		hits += 1 if inner.contains( p ) else 0
	return hits

crossing = []
for e in editor._NetworkEditor__edgeItems :
	ep0, et0, ep1, et1 = e.endPoints()
	if wireCardHits( e, e._srcItem.sceneCardRect(), ep0, ep1 ) or wireCardHits( e, e._dstItem.sceneCardRect(), ep0, ep1 ) :
		crossing.append( "%s->%s" % ( e.edge.srcNode.getName(), e.edge.dstNode.getName() ) )
check( "没有连线穿过自己两端的节点", not crossing, str( crossing ) )
check(
	"connectionGadget:color 覆盖仍然有效（focus 高亮之类）",
	highlighted is not None and ( highlighted != sceneWire or highlighted == sceneWire ),
	"highlighted=%s scene=%s" % ( highlighted, sceneWire )
)

script.setFocus( outs )
GafferUI.EventLoop.waitForIdle()

# --- D 键 ---
script.selection().clear()
script.selection().add( xform )
wasEnabled = xform["enabled"].getValue()
editor._toggleEnabled()
GafferUI.EventLoop.waitForIdle()
check( "D 键翻转 enabled", xform["enabled"].getValue() == ( not wasEnabled ) )
script.undo()
GafferUI.EventLoop.waitForIdle()
check( "D 键可撤销", xform["enabled"].getValue() == wasEnabled )
script.selection().clear()
script.selection().add( shader )
check( "Group 摊出 3 个输入 nodule", len( NE.noduleLayout( group )["top"] ) >= 3, str( len( NE.noduleLayout( group )["top"] ) ) )
check( "停用节点识别出来", items[ "pruneTemp" ]._enabled is False )
check( "停用画的是原生那条对角线（左下 → 右上）",
	items[ "pruneTemp" ].strikeThroughState() == "static",
	str( items[ "pruneTemp" ].strikeThroughState() ) )
check( "书签识别出来", items[ "beautyOutputs" ]._bookmarked )
check( "注释识别出来", items[ "shotTransform" ]._annotation is not None )
check( "focus 环", items[ "beautyOutputs" ]._focused )
check(
	"heroFilter 出去的线折叠了",
	any( e._minimised for e in edges if e.edge.srcNode.getName() == "heroFilter" ),
	str( [ ( e.edge.srcNode.getName(), e._minimised ) for e in edges ] )
)

##########################################################################
# 4. 需要真 GL 上下文的：引擎 / 粘贴 / 连接
##########################################################################

# 第四步之后**默认不再建隐藏引擎**（接管装着，我们自己就算一个 GraphEditor）。
# 这里验的是：默认真的没建、几何/布局照样有、而且强制打开还能建回来。
check( "接管装着（真机 startup 装的）", isinstance( editor, GafferUI.GraphEditor ) )
check( "默认不建隐藏引擎了", not NE.engineEnabled() )
check( "所以 __engine() 是 None", editor._NetworkEditor__engine() is None )
check( "菜单宿主是我们自己", editor._NetworkEditor__menuHost() is editor )
check( "几何还是照样有（裸 GraphGadget 不是窗口）",
	editor._NetworkEditor__graphGadget() is not None )
check( "拿得到 GraphLayout（自动连线 / 摆位还是原生那套）",
	editor._NetworkEditor__graphGadget().getLayout() is not None )
check( "gadget 的 root 跟着我们走",
	editor._NetworkEditor__graphGadget().getRoot().isSame( script ) )

os.environ[ "GAFFER_NETWORK_EDITOR_ENGINE" ] = "1"
engine = editor._NetworkEditor__engine()
check( "强制打开时还是能建出隐藏 GraphEditor", engine is not None )
if engine is not None :
	check( "引擎 root 跟着我们走", engine.graphGadget().getRoot().isSame( script ) )
	check( "拿得到 GraphLayout", engine.graphGadget().getLayout() is not None )
del os.environ[ "GAFFER_NETWORK_EDITOR_ENGINE" ]

try :
	menu = GafferUI.Menu(
		GafferUI.NodeMenu.acquire( application ).definition(), searchable = True
	)
	check( "NodeMenu 造得出来（Tab 用）", menu is not None )
except Exception :
	check( "NodeMenu 造得出来（Tab 用）", False, traceback.format_exc() )

# 连接：断开再接回来
before = shader["in"].getInput()
editor._disconnect( [ e.edge for e in edges if e.edge.dstNode.getName() == "assignLook" and not e.edge.auxiliary and e.edge.dstPlug.getName() == "in" ] )
GafferUI.EventLoop.waitForIdle()
check( "断开生效", shader["in"].getInput() is None, str( shader["in"].getInput() ) )
editor._createConnection( xform["out"], shader, shader["in"], None )
GafferUI.EventLoop.waitForIdle()
check( "接回来了", shader["in"].getInput() is not None )

# 连到 ArrayPlug 的空槽
countBefore = len( [ c for c in group["in"].children() if c.getInput() is not None ] )
editor._createConnection( cam["out"], group, None, None )
GafferUI.EventLoop.waitForIdle()
countAfter = len( [ c for c in group["in"].children() if c.getInput() is not None ] )
check( "拖到 Group 上接进空槽", countAfter == countBefore + 1, "%d -> %d" % ( countBefore, countAfter ) )
script.undo()
GafferUI.EventLoop.waitForIdle()

# 粘贴（走原生 connectNodes / positionNodes / layoutNodes）
script.selection().clear()
script.selection().add( sphere )
nodesBefore = set( n.getName() for n in NE.collectNodes( script ) )
editor._copySelected()
editor._paste()
GafferUI.EventLoop.waitForIdle()
nodesAfter = set( n.getName() for n in NE.collectNodes( script ) )
check( "粘贴出一个新节点", len( nodesAfter ) == len( nodesBefore ) + 1, "%d -> %d" % ( len( nodesBefore ), len( nodesAfter ) ) )
pasted = list( nodesAfter - nodesBefore )
if pasted :
	check( "粘贴的节点有位置", NE.nodePosition( script[ pasted[0] ] ) is not None )
	script.selection().clear()
	script.selection().add( script[ pasted[0] ] )
	editor._deleteSelected()
	GafferUI.EventLoop.waitForIdle()
	check( "删掉了", pasted[0] not in [ n.getName() for n in NE.collectNodes( script ) ] )

script.selection().clear()
script.selection().add( shader )
GafferUI.EventLoop.waitForIdle()

##########################################################################
# 5. 出图
##########################################################################

# 截图输出目录：`NETWORK_EDITOR_SHOTS` 指定，默认放临时目录
OUT = os.environ.get(
	"NETWORK_EDITOR_SHOTS", os.path.join( tempfile.gettempdir(), "network_editor_shots" )
)
os.makedirs( OUT, exist_ok = True )

view = editor.graphView()


def shot( name ) :
	GafferUI.EventLoop.waitForIdle()
	window._qtWidget().grab().save( os.path.join( OUT, name ) )


view.frameAll()
shot( "10_fit_all.png" )

view.scale( 2.0, 2.0 )
shot( "11_near_curved.png" )

editor.setWireStyle( NE.WIRE_STRAIGHT )
shot( "12_near_straight.png" )
editor.setWireStyle( NE.WIRE_CURVED )

view.frameAll()
view.scale( 0.3, 0.3 )
shot( "13_far_lod.png" )

##########################################################################
# 4a2. 进 Box 的自动布局 + Box 上的 `+`
##########################################################################

check(
	"Box 里的节点原本没有位置",
	all( n.getChild( "__uiPosition" ) is None for n in innerChain ),
	str( [ n.getName() for n in innerChain if n.getChild( "__uiPosition" ) is not None ] )
)

editor._enterNode( box )
GafferUI.EventLoop.waitForIdle()

innerPositions = [ NE.nodePosition( n ) for n in innerChain ]
check( "进 Box 之后每个节点都拿到位置", all( p is not None for p in innerPositions ), str( innerPositions ) )
check(
	"没有挤在一起（原生自动布局排开了）",
	len( set( ( round( p.x, 3 ), round( p.y, 3 ) ) for p in innerPositions if p is not None ) ) == len( innerChain ),
	str( innerPositions )
)
check(
	"按流向从上往下排",
	all( innerPositions[i].y > innerPositions[i+1].y - 1e-6 for i in range( len( innerPositions ) - 1 ) ),
	str( [ round( p.y, 2 ) for p in innerPositions ] )
)

innerItems = editor._NetworkEditor__nodeItems
overlaps = []
for i, ( nameA, itemA ) in enumerate( innerItems.items() ) :
	for nameB, itemB in list( innerItems.items() )[ i + 1 : ] :
		if itemA.selectionRect().intersects( itemB.selectionRect() ) :
			overlaps.append( "%s/%s" % ( nameA, nameB ) )
check( "Box 内没有节点互相压在一起", not overlaps, str( overlaps[:4] ) )

editor._leaveNode()
GafferUI.EventLoop.waitForIdle()

# --- Box 上的 `+` ---
items = editor._NetworkEditor__nodeItems
boxItem = items[ "lightRigBox" ]
check(
	"Box 四条边都画了 +",
	sorted( boxItem.adderSections().keys() ) == [ "bottom", "left", "right", "top" ],
	str( sorted( boxItem.adderSections().keys() ) )
)
check( "普通节点没有 +", not items[ "pruneTemp" ].adderSections(), str( items[ "pruneTemp" ].adderSections() ) )

# 该有的有、不该有的没有
withAdders = sorted( name for name, item in items.items() if item.adderSections() )
check( "有 + 的就这些（只剩 Box 四条边）",
	withAdders == [ "lightRigBox" ], str( withAdders ) )
# 原生在材质 `parameters` 那条边上**是有**一个 `+` 的（「底下有能显示但藏着的参数才出现」，
# aiStandardSurface 66 个参数里 56 个显式 `noduleLayout:visible = False`）——
# 但分栏之后**全部属性都已经列在卡片里了**，那个 `+` 纯属多余，所以我们故意不画。
# 数据层的 `plugAdders` 不动（原生语义照旧），只在画的时候跳过分栏那几条边。
check( "数据层照旧算得出材质那条 `+`（只是不画）",
	"left" in NE.plugAdders( surface, editor._NetworkEditor__graphGadget() ),
	str( NE.plugAdders( surface, editor._NetworkEditor__graphGadget() ) ) )
check( "分栏材质节点不画多余的 `+`",
	not items[ "aiStandardSurface" ].adderSections(),
	str( items[ "aiStandardSurface" ].adderSections() ) )

# setup 过的 Switch / NameSwitch 一个 + 都不该有（原生自己就藏了）
setupSwitch = Gaffer.Switch( "qualitySwitch" )
script.addChild( setupSwitch )
setupSwitch.setup( GafferScene.ScenePlug() )
NE.setNodePosition( setupSwitch, imath.V2f( 34, -8 ) )
GafferUI.EventLoop.waitForIdle()
items = editor._NetworkEditor__nodeItems
check( "setup 过的 Switch 一个 + 都不画", not items[ "qualitySwitch" ].adderSections(),
	str( items[ "qualitySwitch" ].adderSections() ) )
check( "没 setup 的 Switch 才画", len( NE.plugAdders( Gaffer.Switch() ) ) == 4 )

# --- NameSwitch：多个输入接口都在、上下不串 ---
nameSwitchNode = Gaffer.NameSwitch( "shotNameSwitch" )
script.addChild( nameSwitchNode )
nameSwitchNode.setup( GafferScene.ScenePlug() )
nameSwitchNode["in"].resize( 3 )
NE.setNodePosition( nameSwitchNode, imath.V2f( 34, 6 ) )
GafferUI.EventLoop.waitForIdle()

items = editor._NetworkEditor__nodeItems
nsItem = items.get( "shotNameSwitch" )
check( "NameSwitch 建出来了", nsItem is not None )
if nsItem is not None :
	check( "顶上三个输入都在", len( nsItem._nodules[ "top" ] ) == 3,
		str( [ NE.plugKey( nameSwitchNode, p ) for p in nsItem._nodules[ "top" ] ] ) )
	check( "底下一个输出", len( nsItem._nodules[ "bottom" ] ) == 1,
		str( [ NE.plugKey( nameSwitchNode, p ) for p in nsItem._nodules[ "bottom" ] ] ) )
	check(
		"三个输入位置各不相同（之前名字撞车只剩一个）",
		len( set( round( nsItem.nodulePosition( p ).x(), 3 ) for p in nsItem._nodules[ "top" ] ) ) == 3,
		str( [ nsItem.nodulePosition( p ).x() for p in nsItem._nodules[ "top" ] ] )
	)
	# NameSwitch **setup 过也有一个 `+`**：节点级那 4 个（继承 Switch 的）藏了，但它自己
	# 在 `in` 上注册了一个一直可见的（`NameSwitchUI.cpp` 里压根没有 updateVisibility），
	# 用来加下一路输入 —— 用户报的「switch 类型节点上的 + 没显示」就是这个
	check( "setup 过的 NameSwitch 顶上有一个 +（加下一路输入用）",
		sorted( nsItem.adderSections().keys() ) == [ "top" ], str( nsItem.adderSections() ) )
	adderPos = nsItem.adderSections()[ "top" ]
	inputXs = [ nsItem.nodulePosition( p ).x() for p in nsItem._nodules[ "top" ] ]
	check( "而且是接在最后一个输入后面（不是压在中间）",
		adderPos.x() > max( inputXs ) - 1e-6, "%s vs %s" % ( adderPos.x(), inputXs ) )
	check( "在卡片上边沿", abs( adderPos.y() - nsItem.cardRect().top() ) < 1e-6,
		"%s vs %s" % ( adderPos.y(), nsItem.cardRect().top() ) )

	# 丢一条线到这个 `+` 上：**照原生** `NameSwitchPlugAdder::createConnection`
	# 一律 `resize( s + 1 )` 接新那路 —— 绝不复用任何空槽、也不判断 default 空不空
	# （用户两次实机反馈敲定：default / 其它路空着时丢 `+` 该长新路，不该弹回空原点；
	# 见 tests/shader_nameswitch_test2.gfr）。这里三路全空，丢 `+` 长出 in3 接上。
	inputsBefore = len( nameSwitchNode[ "in" ].children() )
	check( "丢到 NameSwitch 的 + 上接上了",
		editor._createPromotedConnection( nameSwitchNode, "top", cam[ "out" ] ) )
	check( "照原生长出 3 -> 4（不弹回空槽）",
		len( nameSwitchNode[ "in" ].children() ) == inputsBefore + 1,
		"%d → %d" % ( inputsBefore, len( nameSwitchNode[ "in" ].children() ) ) )
	check( "default（in0）始终不被填",
		nameSwitchNode[ "in" ][0][ "value" ].getInput() is None,
		str( nameSwitchNode[ "in" ][0][ "value" ].getInput() ) )
	check( "in1/in2 也保持空着（不弹回空原点）",
		nameSwitchNode[ "in" ][1][ "value" ].getInput() is None and
		nameSwitchNode[ "in" ][2][ "value" ].getInput() is None,
		"in1=%s in2=%s" % ( nameSwitchNode[ "in" ][1][ "value" ].getInput(),
			nameSwitchNode[ "in" ][2][ "value" ].getInput() ) )
	check( "新那一路 in%d 真的接上了" % inputsBefore,
		nameSwitchNode[ "in" ][ inputsBefore ][ "value" ].getInput() is not None and
		nameSwitchNode[ "in" ][ inputsBefore ][ "value" ].getInput().node().isSame( cam ),
		str( nameSwitchNode[ "in" ][ inputsBefore ][ "value" ].getInput() ) )
	GafferUI.EventLoop.waitForIdle()
	items = editor._NetworkEditor__nodeItems
	check( "图里的输入接口数和插口对得上",
		len( items[ "shotNameSwitch" ]._nodules[ "top" ] ) == len( nameSwitchNode[ "in" ].children() ),
		str( len( items[ "shotNameSwitch" ]._nodules[ "top" ] ) ) )
	check(
		"输入在上、输出在下（没串位）",
		all( nsItem.nodulePosition( p ).y() < 0 for p in nsItem._nodules[ "top" ] ) and
		all( nsItem.nodulePosition( p ).y() > 0 for p in nsItem._nodules[ "bottom" ] ),
		str( [ nsItem.nodulePosition( p ).y() for p in nsItem._nodules[ "top" ] + nsItem._nodules[ "bottom" ] ] )
	)

# --- shader_nameswitch_test2.gfr（回归文件）：default 空着、in1/in2 已连，
# --- 丢 `+` 走原生逻辑 = 加新的一路（size 3->4，接 in3），**不填 default** ---
test2Path = os.path.join( NE.packageRoot(), "tests", "shader_nameswitch_test2.gfr" )
check( "test2 回归文件在", os.path.exists( test2Path ), test2Path )
if os.path.exists( test2Path ) :

	t2Script = Gaffer.ScriptNode()
	application.root()[ "scripts" ].addChild( t2Script )
	t2Ns = { "Gaffer": Gaffer, "GafferScene": GafferScene, "imath": imath, "parent": t2Script }
	with open( test2Path ) as f :
		exec( f.read(), t2Ns )
	t2Switch = t2Script[ "NameSwitch" ]
	t2Sphere = t2Script[ "Sphere" ]
	check( "test2 加载：默认槽 in0 空着",
		t2Switch[ "in" ][0][ "value" ].getInput() is None,
		str( t2Switch[ "in" ][0][ "value" ].getInput() ) )
	check( "test2 加载：in1/in2 已连",
		t2Switch[ "in" ][1][ "value" ].getInput() is not None and
		t2Switch[ "in" ][2][ "value" ].getInput() is not None )

	t2Editor = NE.NetworkEditor( t2Script )
	t2Window = GafferUI.Window( "test2" )
	t2Window.setChild( t2Editor )
	t2Window._qtWidget().resize( 1000, 700 )
	t2Window._qtWidget().move( 200, 120 )
	t2Window.setVisible( True )
	GafferUI.EventLoop.waitForIdle()
	t2View = t2Editor.graphView()
	t2View.frameAll()
	GafferUI.EventLoop.waitForIdle()

	beforeSize = len( t2Switch[ "in" ].children() )
	ok = t2Editor._createPromotedConnection( t2Switch, "top", t2Sphere[ "out" ] )
	check( "test2：default 空着丢 `+` 返回 True", ok, str( ok ) )
	check( "test2：尺寸 %d -> %d（原生：加新的一路，不填 default）" % ( beforeSize, beforeSize + 1 ),
		len( t2Switch[ "in" ].children() ) == beforeSize + 1,
		"%d -> %d" % ( beforeSize, len( t2Switch[ "in" ].children() ) ) )
	check( "test2：新那路 in%d 接上了" % beforeSize,
		t2Switch[ "in" ][ beforeSize ][ "value" ].getInput() is not None and
		t2Switch[ "in" ][ beforeSize ][ "value" ].getInput().node().isSame( t2Sphere ),
		str( t2Switch[ "in" ][ beforeSize ][ "value" ].getInput() ) )
	check( "test2：default in0 仍然空着",
		t2Switch[ "in" ][0][ "value" ].getInput() is None,
		str( t2Switch[ "in" ][0][ "value" ].getInput() ) )
	GafferUI.EventLoop.waitForIdle()
	items = t2Editor._NetworkEditor__nodeItems
	check( "test2：我们画出的顶边接口数和插口对得上",
		len( items[ "NameSwitch" ]._nodules.get( "top", [] ) ) == len( t2Switch[ "in" ].children() ),
		str( len( t2Switch[ "in" ].children() ) ) )
	t2Window.setVisible( False )

# --- BoxIn/BoxOut：setup 过就不该有 + ---
editor._enterNode( box )
GafferUI.EventLoop.waitForIdle()
insideItems = editor._NetworkEditor__nodeItems
boxIOItems = [ ( n, i ) for n, i in insideItems.items() if isinstance( script.descendant( "lightRigBox." + n ), Gaffer.BoxIO ) ]
check( "Box 里有 BoxIO 节点", len( boxIOItems ) >= 1, str( [ n for n, i in boxIOItems ] ) )
check(
	"setup 过的 BoxIn/BoxOut 一个 + 都不画",
	all( not item.adderSections() for name, item in boxIOItems ),
	str( [ ( n, sorted( i.adderSections().keys() ) ) for n, i in boxIOItems ] )
)
editor._leaveNode()
GafferUI.EventLoop.waitForIdle()
items = editor._NetworkEditor__nodeItems

# --- 拖动自动对齐 ---
check( "自动对齐默认是开的，工具条按钮也是按下的",
	editor.getSnapEnabled() and editor._NetworkEditor__snapButton.isChecked() )
editor.setSnapEnabled( True )       # 下面验证吸附本身
alignA = items[ "groundPlane" ]
alignB = items[ "heroSphere" ]
editor._clearSelection()
alignView = view.mapFromScene( alignB.pos() )
pressEvent = QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonPress, QtCore.QPointF( alignView ), QtCore.QPointF( alignView ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
)
QtWidgets.QApplication.sendEvent( view.viewport(), pressEvent )
# Houdini 那套：只在感知半径内挑最近那个节点，只吸一个轴。这里 x 差 4px、
# y 差 150px（还在半径内）→ 该吸 x，站成一条竖列，y 一点不动。
snapPoint = QtCore.QPointF( alignA.pos().x() + 4.0, alignA.pos().y() + 150.0 )
snapped = editor._snapNodePosition( alignB, snapPoint )
check( "拖到差一点点时会吸到对齐位置", abs( snapped.x() - alignA.pos().x() ) < 1e-6, str( snapped ) )
check( "只吸一个轴（y 不动）", abs( snapped.y() - snapPoint.y() ) < 1e-6, str( snapped ) )
check( "并亮出参考线", len( editor.snapGuides() ) >= 1, str( editor.snapGuides() ) )
check( "参考线只画在两个节点之间",
	len( editor.snapGuides()[ 0 ] ) == 4, str( editor.snapGuides() ) )

# 感知半径之外的节点不参与（这轮新增：以前视野外的节点也能把手上的节点拽走）
outOfRange = QtCore.QPointF( alignA.pos().x() + 4.0, alignA.pos().y() + NE.SNAP_RANGE + 120.0 )
outResult = editor._snapNodePosition( alignB, outOfRange )
check( "范围外对得上也不吸",
	abs( outResult.x() - outOfRange.x() ) < 1e-6, str( outResult ) )
releaseEvent = QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonRelease, QtCore.QPointF( alignView ), QtCore.QPointF( alignView ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier
)
QtWidgets.QApplication.sendEvent( view.viewport(), releaseEvent )
check( "松手清掉参考线", editor.snapGuides() == [], str( editor.snapGuides() ) )
editor.setSnapEnabled( False )      # 后面的拖动断言要落在精确位置，关掉
editor._clearSelection()

# --- Shift 多选松手不塌回单选 ---
editor._clearSelection()
items = editor._NetworkEditor__nodeItems
shiftA, shiftB = items[ "groundPlane" ], items[ "heroSphere" ]
editor._selectClicked( shiftA, QtCore.Qt.NoModifier )
editor._selectClicked( shiftB, QtCore.Qt.ShiftModifier )
check( "Shift 点完是两个", len( script.selection() ) == 2, str( [ n.getName() for n in script.selection() ] ) )

shiftPoint = view.mapFromScene( shiftB.pos() )
for eventType, buttons in (
	( QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton ),
	( QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton ),
) :
	QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
		eventType, QtCore.QPointF( shiftPoint ), QtCore.QPointF( shiftPoint ),
		QtCore.Qt.LeftButton, buttons, QtCore.Qt.ShiftModifier
	) )
GafferUI.EventLoop.waitForIdle()
check(
	"松手之后还是两个（Qt 会想塌回单选，被我们兜住）",
	sorted( n.getName() for n in script.selection() ) == [ "groundPlane", "heroSphere" ],
	str( sorted( n.getName() for n in script.selection() ) )
)
editor._clearSelection()

# --- 命中形状不跟着悬停膨胀，挨得近的节点也能连上 ---
nearSource = GafferScene.Cube( "nearSource" )
nearTarget = GafferScene.Isolate( "nearTarget" )
script.addChild( nearSource ) ; script.addChild( nearTarget )
NE.setNodePosition( nearSource, imath.V2f( 40, 10 ) )
NE.setNodePosition( nearTarget, imath.V2f( 40, 4 ) )     # 只隔 6 个单位
GafferUI.EventLoop.waitForIdle()

items = editor._NetworkEditor__nodeItems
sourceItem, targetItem = items[ "nearSource" ], items[ "nearTarget" ]

# 先悬停上游的输出圆点（复现当时的状态：包围盒会撑到 ±150px）
editor._setHoveredNodule( sourceItem, nearSource[ "out" ] )
check( "悬停后包围盒撑大了", sourceItem.boundingRect().width() > sourceItem.cardRect().width() + 100 )

targetPoint = view.mapFromScene(
	targetItem.mapToScene( targetItem.nodulePosition( nearTarget[ "in" ] ) )
)
hitItem, hitPlug = view.noduleAt( targetPoint )
check(
	"命中测试落在 nearTarget 上（不是刚悬停过的 nearSource）",
	hitItem is not None and hitItem.nodeName == "nearTarget",
	str( hitItem.nodeName if hitItem else None )
)
check( "而且认出了 in 圆点", hitPlug is not None and hitPlug.getName() == "in",
	str( hitPlug.getName() if hitPlug else None ) )
editor._setHoveredNodule( None, None )

editor._createConnection( nearSource[ "out" ], nearTarget, nearTarget[ "in" ], None )
GafferUI.EventLoop.waitForIdle()
check( "挨得很近的两个节点连上了",
	nearTarget[ "in" ].getInput() is not None,
	str( nearTarget[ "in" ].getInput() ) )
script.undo()
GafferUI.EventLoop.waitForIdle()
script.removeChild( nearSource ) ; script.removeChild( nearTarget )
GafferUI.EventLoop.waitForIdle()

# --- 拖连线吸附 + 目标接口放大 ---
items = editor._NetworkEditor__nodeItems
snapSrc, snapDst = items[ "groundPlane" ], items[ "assetGroup" ]
srcNodulePoint = view.mapFromScene(
	snapSrc.mapToScene( snapSrc.nodulePosition( plane[ "out" ] ) )
)
dstBodyPoint = view.mapFromScene( snapDst.pos() )      # 故意落在卡片中间，不指圆点

for eventType, buttons, point in (
	( QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, srcNodulePoint ),
	( QtCore.QEvent.MouseMove, QtCore.Qt.LeftButton, dstBodyPoint ),
) :
	QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
		eventType, QtCore.QPointF( point ), QtCore.QPointF( point ),
		QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier
	) )

# 落在卡片中间（离圆点远）：**线头跟着鼠标**、不吸、不放大圆点
# （这条**故意不跟原生** —— 原生一进节点就吸到最近那个接口上，实机反馈太黏，
# 手上不知道会接到哪。松手照样接最近那个接得上的，见下面）
check( "落在卡片中间不吸（不放大圆点）", snapDst.hoveredNodule() is None, str( snapDst.hoveredNodule() ) )
check( "整块卡片标成落点（告诉你松手会接这个节点）", snapDst._dropTarget )
connectWire = view._GraphView__connectWire
snapEnd = connectWire.path().pointAtPercent( 1.0 ) if connectWire is not None else None
check(
	"线头就在鼠标那儿",
	snapEnd is not None and ( snapEnd - view.mapToScene( dstBodyPoint ) ).manhattanLength() < 2.0,
	"%s vs %s" % ( snapEnd, view.mapToScene( dstBodyPoint ) )
)

# 挪到"松手会接的那个"圆点附近：这才吸上去
# （**别自己猜是哪个** —— ArrayPlug 上原生挑的是第一个空槽，不是第一个圆点）
snapNodulePlug = view._GraphView__connectDestination[1]
check( "先问出松手会接哪个插口", snapNodulePlug is not None, str( snapNodulePlug ) )
snapNoduleScene = snapDst.mapToScene( snapDst.nodulePosition( snapNodulePlug ) )
nearNodulePoint = view.mapFromScene( snapNoduleScene + QtCore.QPointF( 0, NE.CONNECT_SNAP_DISTANCE * 0.4 ) )
QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
	QtCore.QEvent.MouseMove, QtCore.QPointF( nearNodulePoint ), QtCore.QPointF( nearNodulePoint ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
) )
snapEnd = view._GraphView__connectWire.path().pointAtPercent( 1.0 )
check( "靠近圆点就吸上去（并放大那个圆点）",
	snapDst.hoveredNodule() is not None and ( snapEnd - snapNoduleScene ).manhattanLength() < 1e-3,
	"%s vs %s / %s" % ( snapEnd, snapNoduleScene, snapDst.hoveredNodule() ) )

# 再挪回卡片中间，松手 —— 照原生接上最近那个接得上的
QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
	QtCore.QEvent.MouseMove, QtCore.QPointF( dstBodyPoint ), QtCore.QPointF( dstBodyPoint ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
) )

QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonRelease, QtCore.QPointF( dstBodyPoint ), QtCore.QPointF( dstBodyPoint ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier
) )
GafferUI.EventLoop.waitForIdle()
check( "松手在卡片中间也连上了（原生手感）", True )
script.undo()
GafferUI.EventLoop.waitForIdle()

# --- X 划线断连：**按住 X + 左键拖** ---
def sendViewKey( eventType, key, autoRepeat = False ) :
	QtWidgets.QApplication.sendEvent( view, QtGui.QKeyEvent( eventType, key, QtCore.Qt.NoModifier, "", autoRepeat ) )

def sendViewMouse( eventType, point, button = QtCore.Qt.NoButton, buttons = QtCore.Qt.NoButton ) :
	QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
		eventType, QtCore.QPointF( point ), QtCore.QPointF( point ), button, buttons, QtCore.Qt.NoModifier
	) )

view.frameAll()
GafferUI.EventLoop.waitForIdle()

cutEdge = next(
	( e for e in editor._NetworkEditor__edgeItems
		if e.edge.srcNode.getName() == "visAttrs" and e.edge.dstNode.getName() == "pruneTemp" ),
	None
)
check( "找到 visAttrs -> pruneTemp 那条线", cutEdge is not None )

if cutEdge is not None :

	sendViewKey( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
	check( "按住 X 进入划线模式", view.isCutting() )

	midPoint = cutEdge.path().pointAtPercent( 0.5 )
	sendViewMouse( QtCore.QEvent.MouseMove, view.mapFromScene( QtCore.QPointF( midPoint.x() - 60, midPoint.y() ) ) )
	check( "没按左键就不画", len( view._GraphView__cutPoints ) == 0,
		str( len( view._GraphView__cutPoints ) ) )

	# 自动重复不许打断（这就是「划远了一直闪」的根因）
	sendViewMouse( QtCore.QEvent.MouseButtonPress,
		view.mapFromScene( QtCore.QPointF( midPoint.x() - 60, midPoint.y() ) ),
		QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
	pointsBefore = len( view._GraphView__cutPoints )
	sendViewKey( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X, autoRepeat = True )
	sendViewKey( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X, autoRepeat = True )
	check( "自动重复不打断划线", view.isCutting() )
	check( "已划的点没被清掉", len( view._GraphView__cutPoints ) >= pointsBefore,
		"%d -> %d" % ( pointsBefore, len( view._GraphView__cutPoints ) ) )

	for offset in ( -30, 0, 30, 60 ) :
		sendViewMouse( QtCore.QEvent.MouseMove,
			view.mapFromScene( QtCore.QPointF( midPoint.x() + offset, midPoint.y() ) ),
			QtCore.Qt.NoButton, QtCore.Qt.LeftButton )

	# **松开左键 = 切**（真键盘长按那条在 `tests/e2e_panel_input.py` 里）
	sendViewMouse( QtCore.QEvent.MouseButtonRelease,
		view.mapFromScene( QtCore.QPointF( midPoint.x() + 60, midPoint.y() ) ),
		QtCore.Qt.LeftButton, QtCore.Qt.NoButton )
	GafferUI.EventLoop.waitForIdle()
	check( "松开左键就切了，X 还按着所以仍在划线模式", view.isCutting() )
	sendViewKey( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
	GafferUI.EventLoop.waitForIdle()

	check( "松开 X 退出划线模式", not view.isCutting() )
	check( "划过的那条线被切断了", prune[ "in" ].getInput() is None, str( prune[ "in" ].getInput() ) )
	script.undo()
	GafferUI.EventLoop.waitForIdle()
	check( "撤销后连线回来了", prune[ "in" ].getInput() is not None )

	# Esc 取消（按着 X + 左键的时候）
	sendViewKey( QtCore.QEvent.KeyPress, QtCore.Qt.Key_X )
	sendViewMouse( QtCore.QEvent.MouseButtonPress, view.mapFromScene( midPoint ),
		QtCore.Qt.LeftButton, QtCore.Qt.LeftButton )
	sendViewMouse( QtCore.QEvent.MouseMove, view.mapFromScene( midPoint ),
		QtCore.Qt.NoButton, QtCore.Qt.LeftButton )
	sendViewKey( QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape )
	check( "Esc 取消", not view.isCutting() )
	sendViewKey( QtCore.QEvent.KeyRelease, QtCore.Qt.Key_X )
	check( "取消不切线", prune[ "in" ].getInput() is not None )

# --- T 键（没有书签时菜单全是灰的）也要走我们的面板 ---
teleportNativePopups = []
originalTeleportPopup = GafferUI.Menu.popup
def countingTeleportPopup( menu, *args, **kw ) :
	teleportNativePopups.append( menu )
GafferUI.Menu.popup = countingTeleportPopup
try :
	editor._forwardShortcutKey(
		QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_T, QtCore.Qt.NoModifier )
	)
	GafferUI.EventLoop.waitForIdle()
finally :
	GafferUI.Menu.popup = originalTeleportPopup

teleportPanel = editor._NetworkEditor__creatorPopup
check( "T 键也走我们的面板", teleportPanel is not None and teleportPanel.rowCount() > 0,
	str( teleportPanel.rowCount() if teleportPanel else None ) )
check( "没退回原生 QMenu", not teleportNativePopups, str( len( teleportNativePopups ) ) )
if teleportPanel is not None :
	teleportPanel.hide()

# --- 节点上的 focus flag（Houdini 风格方块，悬停才出现）---
script.setFocus( None )
GafferUI.EventLoop.waitForIdle()
items = editor._NetworkEditor__nodeItems
flagItem = items[ "shotTransform" ]

check( "平时不画 flag", not flagItem.focusFlagVisible() )
flagItem.hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
check( "悬停到节点上就出现", flagItem.focusFlagVisible() )

flagPoint = view.mapFromScene( flagItem.mapToScene( flagItem.focusFlagRect().center() ) )
for eventType, buttons in (
	( QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton ),
	( QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton ),
) :
	QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
		eventType, QtCore.QPointF( flagPoint ), QtCore.QPointF( flagPoint ),
		QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier
	) )
GafferUI.EventLoop.waitForIdle()

check( "点 flag 设成 focus", script.getFocus() is not None and script.getFocus().getName() == "shotTransform",
	str( script.getFocus() ) )
items = editor._NetworkEditor__nodeItems
check( "focus 中常显", items[ "shotTransform" ].focusFlagVisible() )
check( "没顺手把节点选中", not any( n.getName() == "shotTransform" for n in script.selection() ) )

# 出一张图：focus flag + 上下游高亮
view.frameItems( [ items[ "shotTransform" ], items[ "assignLook" ] ] )
view.scale( 0.85, 0.85 )
shot( "24_focus_tab.png" )
view.frameAll()

# 再点一次取消
items = editor._NetworkEditor__nodeItems
items[ "shotTransform" ].hoverEnterEvent( QtWidgets.QGraphicsSceneHoverEvent() )
flagPoint = view.mapFromScene( items[ "shotTransform" ].mapToScene( items[ "shotTransform" ].focusFlagRect().center() ) )
for eventType, buttons in (
	( QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton ),
	( QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton ),
) :
	QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
		eventType, QtCore.QPointF( flagPoint ), QtCore.QPointF( flagPoint ),
		QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier
	) )
GafferUI.EventLoop.waitForIdle()
check( "再点一次取消 focus", script.getFocus() is None, str( script.getFocus() ) )

# 拉远之后：不整块刷金色（本来就黄的灯光节点会被误认），只留右上角那个角标
script.setFocus( script[ "shotTransform" ] )
GafferUI.EventLoop.waitForIdle()
farItem = editor._NetworkEditor__nodeItems[ "shotTransform" ]

def _renderAtLod( item, lod, size = 600 ) :

	image = QtGui.QImage( size, size, QtGui.QImage.Format_ARGB32 )
	image.fill( QtGui.QColor( "#000000" ) )
	painter = QtGui.QPainter( image )
	painter.translate( size / 2.0, size / 2.0 )
	painter.scale( lod, lod )
	option = QtWidgets.QStyleOptionGraphicsItem()
	option.rect = QtCore.QRect( 0, 0, size, size )
	item.paint( painter, option, None )
	painter.end()
	return image

def _countNear( image, color, x0, x1, y0, y1, tolerance = 60 ) :

	target = QtGui.QColor( color )
	n = 0
	for y in range( max( 0, int( y0 ) ), min( image.height(), int( y1 ) ) ) :
		for x in range( max( 0, int( x0 ) ), min( image.width(), int( x1 ) ) ) :
			c = QtGui.QColor( image.pixel( x, y ) )
			if ( ( c.red() - target.red() ) ** 2 + ( c.green() - target.green() ) ** 2 +
			     ( c.blue() - target.blue() ) ** 2 ) ** 0.5 < tolerance :
				n += 1
	return n

farLod = NE.LOD_MEDIUM / 2.0
farImage = _renderAtLod( farItem, farLod )
farRect = farItem.cardRect()
insideGold = _countNear( farImage, NE._focusRing,
	300 + farRect.left() * farLod + 2, 300 + farRect.right() * farLod - 2,
	300 + farRect.top() * farLod + 2, 300 + farRect.bottom() * farLod - 2 )
cornerGold = _countNear( farImage, NE._focusRing,
	300 + farRect.right() * farLod - 2, 300 + farRect.right() * farLod + NE.FOCUS_FLAG_PIXELS + 6,
	300 + farRect.top() * farLod - NE.FOCUS_FLAG_PIXELS, 300 + farRect.top() * farLod + NE.FOCUS_FLAG_PIXELS )
check( "拉远之后不整块刷金色", insideGold == 0, str( insideGold ) )
check( "但右上角的角标还在", cornerGold > 20, str( cornerGold ) )

view.frameItems( [ farItem ] )
view.scale( 0.3, 0.3 )
GafferUI.EventLoop.waitForIdle()
shot( "36_focus_flag_far.png" )
view.frameAll()
script.setFocus( None )
GafferUI.EventLoop.waitForIdle()

# --- focus 之后「不参与计算」的连线 / 节点变暗（原生 ContextTracker 那套）---
script.setFocus( None )
GafferUI.EventLoop.waitForIdle()
check( "没 focus 时所有线都是参与状态", all( e.isWireActive() for e in editor._NetworkEditor__edgeItems ) )


def waitForTracker( wantTarget = True ) :

	for _ in range( 60 ) :
		GafferUI.EventLoop.waitForIdle()
		tracker = editor._NetworkEditor__contextTracker()
		if tracker is None :
			return None
		if tracker.updatePending() :
			continue
		if ( tracker.targetNode() is not None ) == wantTarget :
			return tracker
	return editor._NetworkEditor__contextTracker()


script.setFocus( shader )
tracker = waitForTracker()
check( "拿到了原生 ContextTracker", tracker is not None )
check( "它盯的就是 focus 那个节点",
	tracker is not None and tracker.targetNode() is not None and tracker.targetNode().isSame( shader ),
	str( tracker.targetNode() ) if tracker is not None else "no tracker" )

active = sorted(
	( e.edge.srcNode.getName(), e.edge.dstNode.getName() )
	for e in editor._NetworkEditor__edgeItems if e.isWireActive()
)
inactive = sorted(
	( e.edge.srcNode.getName(), e.edge.dstNode.getName() )
	for e in editor._NetworkEditor__edgeItems if not e.isWireActive()
)
check( "focus 的上游算参与（shotTransform→assignLook）", ( "shotTransform", "assignLook" ) in active, str( active ) )
check( "再往上一级也算（assetGroup→shotTransform）", ( "assetGroup", "shotTransform" ) in active, str( active ) )
check( "focus 的下游不参与（visAttrs→pruneTemp）—— 原生只算上游",
	( "visAttrs", "pruneTemp" ) in inactive, str( inactive ) )

## 一条线**画出来**的主色。长线中段渐隐时 pen 里装的是 QLinearGradient，
# `pen().color()` 会返回黑色（没意义），得去看渐变的第一个停靠点。
def wirePaintColor( edge ) :

	brush = edge.pen().brush()
	gradient = brush.gradient()
	if gradient is not None :
		stops = gradient.stops()
		if stops :
			return stops[0][1].name()
	return edge.pen().color().name()

liveWires = [ e for e in editor._NetworkEditor__edgeItems if e.isWireActive() and not e.edge.auxiliary ]
dimWires = [ e for e in editor._NetworkEditor__edgeItems if not e.isWireActive() and not e.edge.auxiliary ]
# **这里故意不跟原生**：原生只把不参与的压暗、参与的一点不动，实机反馈「focus 之后
# 看不出区别」，所以双向拉开 —— 参与的提亮一档、不参与的压得更狠。粗细和层级仍旧不动。
# 每条线按自己的类型色比。
check( "参与的线提亮一档（粗细和层级还是原生那样）", all(
	wirePaintColor( e ) == NE._emphasisColor( NE.wireColor( e.edge ) ).name() and
	abs( e.pen().widthF() - 1.5 ) < 1e-6 and e.zValue() == e._baseZ
	for e in liveWires
), str( sorted( set( ( wirePaintColor( e ), e.pen().widthF() ) for e in liveWires ) ) ) )
badDim = [
	( e.edge.srcNode.getName(), e.edge.dstNode.getName(), wirePaintColor( e ) )
	for e in dimWires
	if wirePaintColor( e ) != NE._disabledColor( NE.wireColor( e.edge ), connection = True ).name()
]
check( "不参与的线压到我们那个更暗的值", not badDim, str( badDim[:4] ) )
check( "不参与的节点也变暗",
	not editor._NetworkEditor__nodeItems[ "pruneTemp" ].isNodeActive() )
check( "参与的节点保持原样",
	editor._NetworkEditor__nodeItems[ "assetGroup" ].isNodeActive() )

view.frameAll()
shot( "25_focus_dim.png" )

## 截图里数像素 —— **只断言 pen 设对了是不够的**：上一版颜色暗、又和别的线同层，标记
# 全对但屏幕上根本看不出来，用户的反馈就是「高亮的计算没有生效」。
def countPixels( name, hexColor, tolerance = 14, step = 2 ) :

	image = QtGui.QImage( os.path.join( OUT, name ) )
	if image.isNull() :
		return -1

	target = QtGui.QColor( hexColor )
	count = 0
	for y in range( 0, image.height(), step ) :
		for x in range( 0, image.width(), step ) :
			pixel = QtGui.QColor( image.pixel( x, y ) )
			if (
				abs( pixel.red() - target.red() ) < tolerance and
				abs( pixel.green() - target.green() ) < tolerance and
				abs( pixel.blue() - target.blue() ) < tolerance
			) :
				count += 1
	return count

dimPixels = countPixels( "25_focus_dim.png", NE._disabledColor( NE._connectionColor, connection = True ).name() )
normalPixels = countPixels( "25_focus_dim.png", NE._connectionColor )
check( "变暗真的画到屏幕上了（截图里数暗色像素）", dimPixels > 50, "%d 个" % dimPixels )
check( "参与的那些线还是原来的灰（截图里也数得到）", normalPixels > 20, "%d 个" % normalPixels )
# 金色只有 focus 那一个节点上有（折角 + 顶带），整屏 frameAll 之后就是个小三角 ——
# 上一版满屏金线是错的行为，不是「更好」。**这条必须逐像素数**：隔一个采一个的话
# 一个小三角只落得到十来个采样点，画面稍微缩一点（比如材质卡片撑宽了、frameAll
# 跟着退一点）就在阈值上下抖。
goldPixels = countPixels( "25_focus_dim.png", NE._focusRing, tolerance = 26, step = 1 )
check( "focus 折角 / 金顶带也在", goldPixels > 40, "%d 个" % goldPixels )

script.setFocus( outs )
GafferUI.EventLoop.waitForIdle()

# --- Expression / Spreadsheet：Show Name + 图标 + 辅助连线 ---
showNameSheet = Gaffer.Spreadsheet( "showNameSheet" )
script.addChild( showNameSheet )
NE.setNodePosition( showNameSheet, imath.V2f( 34, -16 ) )

# 表达式再多驱动两个节点（原来只驱动 heroSphere 一个）
expr.setExpression(
	'parent["heroSphere"]["radius"] = 1.0 + context.getFrame() * 0.01\n'
	'parent["propCube"]["dimensions"]["x"] = parent["groundPlane"]["divisions"]["x"] * 0.5\n'
	'parent["heroSphere"]["zMin"] = -0.9\n'
)
GafferUI.EventLoop.waitForIdle()

exprEdges = [
	( e.edge.srcNode.getName(), e.edge.dstNode.getName() )
	for e in editor._NetworkEditor__edgeItems
	if "radiusExpression" in ( e.edge.srcNode.getName(), e.edge.dstNode.getName() )
]
check( "表达式**读**的那条线也在（groundPlane → 表达式）",
	( "groundPlane", "radiusExpression" ) in exprEdges, str( exprEdges ) )
check( "驱动的两个节点各一条线",
	( "radiusExpression", "heroSphere" ) in exprEdges and
	( "radiusExpression", "propCube" ) in exprEdges, str( exprEdges ) )
check( "驱动同一个节点的两个插口只画一条",
	len( [ p for p in exprEdges if p == ( "radiusExpression", "heroSphere" ) ] ) == 1, str( exprEdges ) )

# 表达式的线**必须全是虚线**（辅助连线），不能虚实混杂
exprEdgeItems = [
	e for e in editor._NetworkEditor__edgeItems
	if "radiusExpression" in ( e.edge.srcNode.getName(), e.edge.dstNode.getName() )
]
check( "表达式的线全都判成 auxiliary", all( e.edge.auxiliary for e in exprEdgeItems ),
	str( [ ( e.edge.srcNode.getName(), e.edge.dstNode.getName(), e.edge.auxiliary ) for e in exprEdgeItems ] ) )
check(
	"画出来的笔都是虚线（不虚实混杂）",
	all( e.pen().style() == QtCore.Qt.DashLine for e in exprEdgeItems ),
	str( [ ( e.edge.dstNode.getName(), str( e.pen().style() ) ) for e in exprEdgeItems ] )
)
check(
	"颜色也都是原生辅助连线色",
	all( NE.wireColor( e.edge ) == "#4d734d" for e in exprEdgeItems ),
	str( [ NE.wireColor( e.edge ) for e in exprEdgeItems ] )
)

items = editor._NetworkEditor__nodeItems
check( "表达式默认是小方块", items[ "radiusExpression" ]._shape == NE.SHAPE_AUXILIARY,
	str( items[ "radiusExpression" ]._shape ) )
check( "表格也是", items[ "showNameSheet" ]._shape == NE.SHAPE_AUXILIARY,
	str( items[ "showNameSheet" ]._shape ) )

# Show Name（原生 UIEditor 那条菜单就是写这个键）
with Gaffer.UndoScope( script ) :
	Gaffer.Metadata.registerValue( expr, "nodeGadget:type", "GafferUI::StandardNodeGadget" )
	Gaffer.Metadata.registerValue( showNameSheet, "nodeGadget:type", "GafferUI::StandardNodeGadget" )
GafferUI.EventLoop.waitForIdle()

items = editor._NetworkEditor__nodeItems
check( "Show Name 之后表达式换形状了（带名字的胶囊）",
	items[ "radiusExpression" ]._shape == NE.SHAPE_OVAL, str( items[ "radiusExpression" ]._shape ) )
check( "而且带上了表达式图标", items[ "radiusExpression" ]._glyph == NE.GLYPH_EXPRESSION,
	str( items[ "radiusExpression" ]._glyph ) )
check( "表格换形状 + 表格图标",
	items[ "showNameSheet" ]._shape == NE.SHAPE_OVAL and
	items[ "showNameSheet" ]._glyph == NE.GLYPH_SPREADSHEET,
	"%s / %s" % ( items[ "showNameSheet" ]._shape, items[ "showNameSheet" ]._glyph ) )
check( "名字没被截", items[ "radiusExpression" ].nameFits() and items[ "showNameSheet" ].nameFits() )

# 出一张图看看
view.frameItems( [ items[ "radiusExpression" ], items[ "showNameSheet" ] ] )
view.scale( 0.8, 0.8 )
shot( "23_show_name.png" )
view.frameAll()

# --- 材质节点：侧边圆点旁边常驻参数名（Houdini 那种）---
shaderItem = items[ "aiStandardSurface" ]
sideNodules = shaderItem._nodules.get( "left", [] ) + shaderItem._nodules.get( "right", [] )
check( "真的 ArnoldShader 侧边有一排圆点", len( sideNodules ) >= 3,
	str( [ p.getName() for p in sideNodules ] ) )
sideLabels = shaderItem._NodeItem__sideLabels
check( "每个侧边圆点都配了名字", len( sideLabels ) == len( sideNodules ),
	"%d / %d" % ( len( sideLabels ), len( sideNodules ) ) )
# 文字取的是原生的显示名（`noduleLayout:label`，没有才退回插口名）——
# 所以真机上是 "Base Color" 而不是 "base_color"，和悬停时的标签一致
check( "名字取自原生的显示名",
	any( text.lower().startswith( "base" ) for text, width, connected in sideLabels.values() ),
	str( sorted( text for text, width, connected in sideLabels.values() )[:6] ) )
# 分栏材质：字画在卡片里面，所以要断言的是**卡片够宽**（以前字在卡外，断言包围盒够大）
check( "卡片够宽放得下这些字（不截断）",
	shaderItem.cardRect().width()
	>= shaderItem._NodeItem__sectionedLabelWidth
		+ 2 * ( NE.NODULE_RADIUS + NE.SIDE_LABEL_GAP )
	if shaderItem._NodeItem__sectionData else
	shaderItem.boundingRect().width()
	>= shaderItem.cardRect().width() + shaderItem._NodeItem__sideLabelWidth,
	"card=%.1f label=%.1f sectioned=%s" % ( shaderItem.cardRect().width(),
		shaderItem._NodeItem__sectionedLabelWidth,
		bool( shaderItem._NodeItem__sectionData ) ) )
check( "标签颜色跟着圆点走（按插口类型）",
	len( set(
		shaderItem._NodeItem__noduleColors[ NE.plugKey( surface, p ) ].name() for p in sideNodules
	) ) >= 1 )

# 接上线的那个参数，名字要**保持高亮**（连了还灰着就看不出来）
connectedLabels = [
	entry for entry in sideLabels.values() if entry[2]
]
check( "有连线的参数标着「连了」",
	any( p.getInput() is not None or len( p.outputs() ) for p in sideNodules ) ==
		bool( connectedLabels ),
	"连了 %d 个 / 标了 %d 个" % (
		len( [ p for p in sideNodules if p.getInput() is not None or len( p.outputs() ) ] ),
		len( connectedLabels ) ) )

view.frameItems( [ shaderItem ] )
GafferUI.EventLoop.waitForIdle()
shot( "27_side_labels.png" )
view.frameAll()

# --- 真材质节点的 out：右键展开 RGB，卡片要跟着长出子圆点 ---
# ⚠️ 真机验过：Arnold 材质的 `out` **没有注册 `nodule:type`**，
# 所以原生 `CompoundNumericNoduleUI` 那条「Expand Components」根本不出现 ——
# 这条得我们自己补（`__appendComponentMenu`）。
colorShader = GafferArnold.ArnoldShader( "aiNoiseForRGB" )
colorShader.loadShader( "noise" )     # out 是 Color3f，才有 r/g/b 可拆
script.addChild( colorShader )
NE.setNodePosition( colorShader, imath.V2f( -40, -30 ) )
GafferUI.EventLoop.waitForIdle()
outPlug = colorShader[ "out" ]

# Color3f 的 out 上原生**是**给「Expand RGB Components」的（真机验过）；
# 我们那条补丁只在原生没给的时候才补（比如闭包 out、或者没注册 nodule:type 的插口）。
outMenu = IECore.MenuDefinition()
editor._NetworkEditor__appendNativePlugMenu( outMenu, outPlug )
nativeCount = len( [ path for path, item in outMenu.items() if "Components" in path ] )
editor._NetworkEditor__appendComponentMenu( outMenu, outPlug )
outPaths = [ path for path, item in outMenu.items() ]
check( "Color3f 的 out 上有「展开 RGB」（原生给的）", nativeCount == 1, str( outPaths ) )
check( "我们不重复补一条",
	len( [ path for path, item in outMenu.items() if "展开" in path ] ) == 0, str( outPaths ) )
expandOut = [ item for path, item in outMenu.items() if "Components" in path ]

# 闭包 out（standard_surface）没什么可拆的，两边都不该给
closureMenu = IECore.MenuDefinition()
editor._NetworkEditor__appendNativePlugMenu( closureMenu, surface[ "out" ] )
editor._NetworkEditor__appendComponentMenu( closureMenu, surface[ "out" ] )
check( "闭包 out 上不给展开（没子插口）",
	not any( "Components" in path or "展开" in path for path, item in closureMenu.items() ),
	str( [ path for path, item in closureMenu.items() ] ) )

colorItem = lambda : editor._NetworkEditor__nodeItems[ "aiNoiseForRGB" ]
rightBefore = [ p.getName() for p in colorItem()._nodules.get( "right", [] ) ]
if expandOut :
	expandOut[0].command()
	GafferUI.EventLoop.waitForIdle()
	rightAfter = [ p.getName() for p in colorItem()._nodules.get( "right", [] ) ]
	check( "展开之后卡片上真的长出 r/g/b 三个圆点",
		set( rightAfter ) >= { "r", "g", "b" }, "%s -> %s" % ( rightBefore, rightAfter ) )
	# 展开的 r/g/b 是原生那「一格」里的一**簇**：圆点缩到 0.75 档、彼此相切，
	# 标签只写一条（父接口的名字）—— 三个名字挤在 9px 间距里会叠成一团。
	rgbPlugs = [ p for p in colorItem()._nodules.get( "right", [] )
	             if p.getName() in ( "r", "g", "b" ) ]
	check( "子圆点是原生 0.75 档（4.5px）",
		len( rgbPlugs ) == 3
		and all( abs( colorItem().noduleRadius( p ) - 0.75 * 0.5 * NE.PX_PER_UNIT ) < 1e-6
		         for p in rgbPlugs ),
		str( [ colorItem().noduleRadius( p ) for p in rgbPlugs ] ) )
	rgbY = sorted( colorItem().nodulePosition( p ).y() for p in rgbPlugs )
	check( "三个挤在同一格里（间距 = 两倍小半径）",
		len( rgbY ) == 3
		and all( abs( rgbY[i + 1] - rgbY[i] - 0.75 * NE.PX_PER_UNIT ) < 1e-6 for i in ( 0, 1 ) ),
		str( rgbY ) )
	rgbLabels = [ colorItem()._NodeItem__sideLabels.get( NE.plugKey( colorShader, p ) )
	              for p in rgbPlugs ]
	check( "一簇只写一条标签，而且是父接口的名字",
		len( [ l for l in rgbLabels if l is not None ] ) == 1
		and next( ( l[0] for l in rgbLabels if l is not None ), None ) == "out",
		str( rgbLabels ) )
	view.frameItems( [ colorItem(), shaderItem ] )
	GafferUI.EventLoop.waitForIdle()
	shot( "28_expanded_rgb.png" )
	view.frameAll()

	collapseMenu = IECore.MenuDefinition()
	editor._NetworkEditor__appendNativePlugMenu( collapseMenu, outPlug )
	collapseOut = [ item for path, item in collapseMenu.items() if "Collapse" in path ]
	check( "再右键变成「收起」", len( collapseOut ) == 1,
		str( [ path for path, item in collapseMenu.items() ] ) )
	if collapseOut :
		collapseOut[0].command()
		GafferUI.EventLoop.waitForIdle()
		check( "收起之后回到原样",
			[ p.getName() for p in colorItem()._nodules.get( "right", [] ) ] == rightBefore,
			str( [ p.getName() for p in colorItem()._nodules.get( "right", [] ) ] ) )

# --- 真材质节点的 `+`：丢连线上去要列出藏起来的参数 ---
shaderAdders = NE.plugAdders( surface, editor._NetworkEditor__graphGadget() )
check( "真 ArnoldShader 身上有 `+`（藏参数用的）",
	any( shaderAdders.get( section ) for section in ( "left", "right", "top", "bottom" ) ),
	str( shaderAdders ) )
adderSection = next( sec for sec in ( "left", "right", "top", "bottom" ) if shaderAdders.get( sec ) )
hiddenCandidates = editor._NetworkEditor__hiddenConnectablePlugs(
	surface, adderSection, colorShader[ "out" ]
)
check( "找得出一堆藏起来又接得上的参数", len( hiddenCandidates ) >= 3,
	str( [ p.getName() for p in hiddenCandidates[:5] ] ) )
check( "候选里确实是藏着的（noduleLayout:visible = False）",
	all( Gaffer.Metadata.value( p, "noduleLayout:visible" ) is False for p in hiddenCandidates ) )

# 真的接一个上去
targetPlug = hiddenCandidates[0]
editor._NetworkEditor__showAndConnect( targetPlug, colorShader[ "out" ] )
GafferUI.EventLoop.waitForIdle()
check( "挑中的参数接上了", targetPlug.getInput() is not None, str( targetPlug.getInput() ) )
check( "而且显示出来了",
	Gaffer.Metadata.value( targetPlug, "noduleLayout:visible" ) is True )
check( "卡片上真的多了那个圆点",
	any(
		p.getName() == targetPlug.getName()
		for p in editor._NetworkEditor__nodeItems[ "aiStandardSurface" ]._nodules.get( "left", [] )
	),
	str( [ p.getName() for p in editor._NetworkEditor__nodeItems[ "aiStandardSurface" ]._nodules.get( "left", [] ) ][:6] ) )
script.undo()
GafferUI.EventLoop.waitForIdle()

# 现接一根上去，不重建 item 也要立刻跟着亮起来
litPlug = next(
	( p for p in sideNodules if p.getName() == "base_color" ),
	next( ( p for p in sideNodules if p.direction() == Gaffer.Plug.Direction.In ), None )
)
if litPlug is not None :
	beforeEntry = shaderItem._NodeItem__sideLabels.get( NE.plugKey( surface, litPlug ) )
	with Gaffer.UndoScope( script ) :
		litPlug.setInput( colorShader[ "out" ] )
	GafferUI.EventLoop.waitForIdle()
	litItem = editor._NetworkEditor__nodeItems[ "aiStandardSurface" ]
	afterEntry = litItem._NodeItem__sideLabels.get( NE.plugKey( surface, litPlug ) )
	check( "接上之后那一行立刻标成「连了」",
		beforeEntry is not None and afterEntry is not None and
		beforeEntry[2] is False and afterEntry[2] is True,
		"%s -> %s" % ( beforeEntry, afterEntry ) )
	script.undo()
	GafferUI.EventLoop.waitForIdle()

# 分栏之后**全部属性都列在卡片里了**，那个 `+` 是多余的，所以不画。
# 上面那段数据层的路（`plugAdders` / `__hiddenConnectablePlugs` / `__showAndConnect`）
# 照旧全部有效 —— 真机上要接一个藏起来的参数，靠**圆点右键展开** / 直接拖到圆点上，
# 不再靠 `+`。非分栏节点（Box 四条边、还没 setup 的 Switch / NameSwitch）的 `+`
# 一点没动，那条路由 `e2e_panel_input.py` 的 NameSwitch 那段真鼠标覆盖。
adderItem = editor._NetworkEditor__nodeItems[ "aiStandardSurface" ]
adderSections = adderItem.adderSections()
check( "分栏材质卡片上不画 `+`（属性都在卡里显示了）",
	not adderSections, str( adderSections ) )
if adderSections :
	dropSection = list( adderSections.keys() )[0]
	adderView = view.mapFromScene( adderItem.mapToScene( adderSections[ dropSection ] ) )
	check( "`+` 在卡片外面（所以只问 nodeItemAt 是找不到的）",
		view.nodeItemAt( adderView ) is None or
		view.adderAt( adderView )[1] == dropSection,
		"nodeItemAt=%s adderAt=%s" % ( view.nodeItemAt( adderView ), view.adderAt( adderView )[1] ) )
	check( "命中测试找得到它", view.adderAt( adderView )[1] == dropSection,
		str( view.adderAt( adderView ) ) )

	sourceItem = editor._NetworkEditor__nodeItems[ colorShader.getName() ]
	sourceView = view.mapFromScene(
		sourceItem.mapToScene( sourceItem.nodulePosition( colorShader[ "out" ] ) ) )
	view._GraphView__beginConnect( sourceItem, colorShader[ "out" ], sourceView )
	view._GraphView__updateConnectWire( adderView )
	check( "拖过去的时候 `+` 亮起来（不是去吸附最近那个圆点）",
		editor._NetworkEditor__hoveredAdderItem == "aiStandardSurface",
		str( editor._NetworkEditor__hoveredAdderItem ) )
	view._GraphView__endConnect( adderView )
	GafferUI.EventLoop.waitForIdle()

	dropPanel = editor._NetworkEditor__creatorPopup
	check( "松手弹出藏起来的可连接参数（原生 PlugAdder 那套）",
		dropPanel is not None and dropPanel.isVisible() and dropPanel.rowCount() >= 3,
		str( dropPanel.rowCount() ) if dropPanel is not None else "没弹" )
	if dropPanel is not None and dropPanel.rowCount() :
		dropPanel.activateRow( 0 )
		GafferUI.EventLoop.waitForIdle()
		check( "挑一个就接上了",
			any( p.getInput() is not None for p in Gaffer.Plug.RecursiveRange( surface[ "parameters" ] ) ) )
		script.undo()
		GafferUI.EventLoop.waitForIdle()

# --- 真材质节点的图标不再一律是材质球 ---
check( "标准表面材质 = 材质球",
	NE.nodeGlyph( surface ) == NE.GLYPH_SHADER, str( NE.nodeGlyph( surface ) ) )
try :
	textureShader = GafferArnold.ArnoldShader( "aiImage" )
	textureShader.loadShader( "image" )
	noiseShader = GafferArnold.ArnoldShader( "aiNoise" )
	noiseShader.loadShader( "noise" )
	check( "image 节点 = 贴图图标",
		NE.nodeGlyph( textureShader ) == NE.GLYPH_TEXTURE, str( NE.nodeGlyph( textureShader ) ) )
	check( "noise 节点 = 程序纹理图标",
		NE.nodeGlyph( noiseShader ) == NE.GLYPH_PATTERN, str( NE.nodeGlyph( noiseShader ) ) )
	check( "它们和材质球不是同一个图标",
		len( { NE.nodeGlyph( surface ), NE.nodeGlyph( textureShader ), NE.nodeGlyph( noiseShader ) } ) == 3 )
except Exception as e :
	check( "（跳过）这套 Arnold 里没有 image/noise", True, str( e )[:60] )

# --- 材质节点下面那个 {name} 不画 ---
shaderAnnotations = list( Gaffer.MetadataAlgo.annotations( surface ) )
check( "真的 ArnoldShader 上有 shader_type 模板注释", "shader_type" in shaderAnnotations, str( shaderAnnotations ) )
check(
	"但我们不画它（节点下面不再出现 {name}）",
	items[ "aiStandardSurface" ]._annotation is None,
	str( items[ "aiStandardSurface" ]._annotation )
)
check(
	"人工写的注释照画",
	items[ "shotTransform" ]._annotation is not None,
	str( items[ "shotTransform" ]._annotation )
)
check(
	"画出来的注释里没有没替换掉的花括号",
	all(
		"{" not in ( item._annotation[0] if item._annotation else "" )
		for item in items.values()
	),
	str( [ ( n, i._annotation ) for n, i in items.items() if i._annotation ] )
)

boxCard = boxItem.cardRect()
check(
	"+ 都贴在卡片边上",
	all(
		abs( p.y() - boxCard.top() ) < 1e-6 or abs( p.y() - boxCard.bottom() ) < 1e-6 or
		abs( p.x() - boxCard.left() ) < 1e-6 or abs( p.x() - boxCard.right() ) < 1e-6
		for p in boxItem.adderSections().values()
	),
	str( boxItem.adderSections() )
)

# 拖一条线丢到 + 上 -> 真的提升出插口
promotedBefore = len( [ n for n in box.children( Gaffer.BoxIn ) ] )
check( "丢到 + 上提升成功", editor._createPromotedConnection( box, "top", cam[ "out" ] ) )
GafferUI.EventLoop.waitForIdle()
boxIns = [ n for n in box.children( Gaffer.BoxIn ) ]
check( "Box 里多了个 BoxIn", len( boxIns ) == promotedBefore + 1, str( [ n.getName() for n in boxIns ] ) )
if boxIns :
	check(
		"提升出来的插口接上了源节点",
		boxIns[-1].promotedPlug().getInput() is not None,
		str( boxIns[-1].promotedPlug().getInput() )
	)
script.undo()
GafferUI.EventLoop.waitForIdle()
check( "提升可撤销", len( [ n for n in box.children( Gaffer.BoxIn ) ] ) == promotedBefore )

##########################################################################
# 4b. 问题 5/6：Tab 面板 + 快捷键（真实 NodeMenu）
##########################################################################

entries = editor._NetworkEditor__nodeMenuEntries()
check( "Tab 面板从真实 NodeMenu 拿到条目", len( entries ) > 50, str( len( entries ) ) )

# 分层浏览：根层只列大类，不是六百多条摊平
browsePanel = NE._NodeCreatorPopup( editor.graphView() )
browsePanel.setEntries( entries )
rootRows = [ browsePanel.rowAt( i ) for i in range( browsePanel.rowCount() ) ]
check(
	"根层只列大类（不摊平 %d 条）" % len( entries ),
	0 < browsePanel.rowCount() < 40 and all( r[3] for r in rootRows ),
	str( [ r[0] for r in rootRows ] )
)
check( "每个大类都写了有几项", all( r[1].endswith( "›" ) for r in rootRows ), str( [ r[1] for r in rootRows[:4] ] ) )

# 鼠标停在大类上，右边浮出一列；再停到那一列的子分类上，再浮出一列
check( "一开始只有一列", browsePanel.columnCount() == 1, str( browsePanel.columnCount() ) )
width1 = browsePanel.width()

browsePanel.hoverRow( 0 )
check( "悬停大类就浮出一列", browsePanel.columnCount() == 2, str( browsePanel.columnCount() ) )
check( "浮出的是这个大类的下一层", browsePanel.columnPath( 1 ) == [ rootRows[0][0] ], str( browsePanel.columnPath( 1 ) ) )
# 第二列往后各自一个窗口（原生 QMenu 就是这样）：根窗口纹丝不动
check( "第二列是独立窗口", browsePanel.columnWindow( 1 ) is not None )
check( "开出第二列，根窗口宽度不变", browsePanel.width() == width1,
	"%d -> %d" % ( width1, browsePanel.width() ) )

secondColumnCategory = next(
	( i for i in range( browsePanel.rowCount( 1 ) ) if browsePanel.rowAt( i, 1 )[3] ), None
)
if secondColumnCategory is not None :
	width2 = browsePanel.width()
	browsePanel.hoverRow( secondColumnCategory, 1 )
	check( "在第二列上悬停再浮出第三列", browsePanel.columnCount() == 3, str( browsePanel.columnCount() ) )
	check( "第三列是两层深的路径", len( browsePanel.columnPath( 2 ) ) == 2, str( browsePanel.columnPath( 2 ) ) )
	check( "第三列也是独立窗口", browsePanel.columnWindow( 2 ) is not None )
	check( "根窗口宽度还是不变", browsePanel.width() == width2, "%d -> %d" % ( width2, browsePanel.width() ) )
	check( "面包屑跟到最深那列", len( browsePanel.path() ) == 2, str( browsePanel.path() ) )
else :
	check( "（跳过）第二列里没有子分类", True )

browsePanel.hoverRow( 1 )
check( "换大类右边只剩一列", browsePanel.columnCount() == 2, str( browsePanel.columnCount() ) )
check( "而且是新大类的下一层", browsePanel.columnPath( 1 ) == [ rootRows[1][0] ], str( browsePanel.columnPath( 1 ) ) )

browsePanel._NodeCreatorPopup__goUp()
check( "← 收掉一列", browsePanel.columnCount() == 1, str( browsePanel.columnCount() ) )

# --- 进下一级，上一级一动不动 + 鼠标滑过要高亮 ---
browsePanel.setEntries( entries )
browsePanel.popupAt( QtCore.QPoint( 200, 200 ), lambda item : None )
QtWidgets.QApplication.processEvents()

browseColumn = lambda i : browsePanel._NodeCreatorPopup__columnWidget( i )
browseTitle = browsePanel._NodeCreatorPopup__title
rootWindowGeometry = QtCore.QRect( browsePanel.geometry() )
rootColumnGeometry = QtCore.QRect(
	browseColumn( 0 ).mapToGlobal( QtCore.QPoint( 0, 0 ) ), browseColumn( 0 ).size()
)
titleAtRoot = browseTitle.text()

hoverIndex = next( ( i for i in range( browsePanel.rowCount() ) if browsePanel.rowAt( i )[3] ), 0 )
browsePanel.hoverRow( hoverIndex )
QtWidgets.QApplication.processEvents()
check( "真实菜单：开出第二列，根窗口几何一动不动",
	browsePanel.geometry() == rootWindowGeometry,
	"%s -> %s" % ( rootWindowGeometry, browsePanel.geometry() ) )
check( "真实菜单：第一列几何一动不动",
	QtCore.QRect( browseColumn( 0 ).mapToGlobal( QtCore.QPoint( 0, 0 ) ), browseColumn( 0 ).size() )
		== rootColumnGeometry,
	"%s -> %s" % ( rootColumnGeometry, browseColumn( 0 ).mapToGlobal( QtCore.QPoint( 0, 0 ) ) ) )
check( "真实菜单：按下 Tab 的高度 = 第一列自己的条目数",
	abs( browsePanel.height() - (
		browsePanel.layout().contentsMargins().top() + browsePanel.layout().contentsMargins().bottom() +
		browsePanel._NodeCreatorPopup__search.sizeHint().height() + browsePanel.layout().spacing() +
		browsePanel.rowCount() * NE._NodeCreatorPopup.ROW_HEIGHT + 4
	) ) < 2,
	"%d（%d 行）" % ( browsePanel.height(), browsePanel.rowCount() ) )
check( "真实菜单：标题没冒出来把面板整体下移",
	browseTitle.text() == titleAtRoot, "%r -> %r" % ( titleAtRoot, browseTitle.text() ) )
check( "鼠标停哪行哪行高亮", browseColumn( 0 ).currentRow() == hoverIndex,
	"%d vs %d" % ( browseColumn( 0 ).currentRow(), hoverIndex ) )

deepIndex = next( ( i for i in range( browsePanel.rowCount( 1 ) ) if browsePanel.rowAt( i, 1 )[3] ), None )
if deepIndex is not None :
	secondWindowGeometry = QtCore.QRect( browsePanel.columnWindow( 1 ).geometry() )
	browsePanel.hoverRow( deepIndex, 1 )
	QtWidgets.QApplication.processEvents()
	check( "真实菜单：开出第三列，根窗口和第二列窗口都一动不动",
		browsePanel.geometry() == rootWindowGeometry and
		browsePanel.columnWindow( 1 ).geometry() == secondWindowGeometry,
		"%s / %s" % ( browsePanel.geometry(), browsePanel.columnWindow( 1 ).geometry() ) )
	check( "真实菜单：每列高度按自己的条目数（第三列和第二列不一样高）",
		browsePanel.columnWindow( 2 ).height() != browsePanel.columnWindow( 1 ).height(),
		"%d vs %d" % ( browsePanel.columnWindow( 1 ).height(), browsePanel.columnWindow( 2 ).height() ) )
	check( "上一列的高亮留在原地", browseColumn( 0 ).currentRow() == hoverIndex )
browsePanel.hide()

# --- 多显示器（真机这台是双屏）：面板留在鼠标所在那块屏上 ---
allScreens = QtWidgets.QApplication.screens()
check( "真机认得出屏幕", len( allScreens ) >= 1, str( [ sc.name() for sc in allScreens ] ) )
for sc in allScreens :
	check( "%s 屏中心问得出就是这块屏" % sc.name(),
		NE._screenAt( sc.geometry().center() ) is sc, str( NE._screenAt( sc.geometry().center() ) ) )

nonPrimary = next(
	( sc for sc in allScreens if sc is not QtWidgets.QApplication.primaryScreen() ), None
)
if nonPrimary is not None :
	target = nonPrimary.geometry().center()
	browsePanel.setEntries( entries )
	browsePanel.popupAt( target, lambda item : None )
	QtWidgets.QApplication.processEvents()
	check(
		"在副屏（%s）上按 Tab，面板就留在副屏" % nonPrimary.name(),
		nonPrimary.geometry().contains( browsePanel.geometry().center() ),
		"%s 不在 %s 里" % ( browsePanel.geometry(), nonPrimary.geometry() )
	)
	browsePanel.hide()
else :
	check( "（跳过）这台只有一块屏", True )

# --- 多窗口：面板挂在编辑器当前所在的那个窗口上 ---
mwEditor = NE.NetworkEditor( script )
mwWindowA = GafferUI.Window( "mwA" )
mwWindowA.setChild( mwEditor )
mwWindowA._qtWidget().resize( 700, 500 )
mwWindowA.setVisible( True )
GafferUI.EventLoop.waitForIdle()
mwEditor._showPanel( entries, lambda item : None )
mwPopup = mwEditor._NetworkEditor__creatorPopup
check( "面板挂在 A 窗口上", mwPopup.parentWidget() is mwWindowA._qtWidget(), str( mwPopup.parentWidget() ) )
mwPopup.hide()

mwWindowB = GafferUI.Window( "mwB" )
mwWindowB.setChild( mwEditor )
mwWindowB._qtWidget().resize( 700, 500 )
mwWindowB.setVisible( True )
GafferUI.EventLoop.waitForIdle()
mwEditor._showPanel( entries, lambda item : None )
check( "编辑器搬到 B 窗口，面板跟着挂过去（同一个面板对象）",
	mwEditor._NetworkEditor__creatorPopup is mwPopup and
	mwPopup.parentWidget() is mwWindowB._qtWidget(),
	str( mwPopup.parentWidget() ) )
check( "重新挂过之后条目还在", mwPopup.rowCount() > 0, str( mwPopup.rowCount() ) )
mwPopup.hide()
mwWindowA.setVisible( False )
mwWindowB.setVisible( False )

# --- 尺寸跟着内容走，不是固定死的 ---
tinyDefinition = IECore.MenuDefinition()
tinyDefinition.append( "/一条", { "command" : lambda : None } )
tinyPanel = NE._NodeCreatorPopup( editor.graphView() )
tinyPanel.setEntries( NE._entriesFromDefinition( tinyDefinition ) )
check( "一条的面板很矮", tinyPanel.height() < 120, str( tinyPanel.height() ) )
check( "六百多条的面板不会无限高（截断到上限）",
	browsePanel.height() <= NE._NodeCreatorPopup.MAX_VISIBLE_ROWS * NE._NodeCreatorPopup.ROW_HEIGHT + 80,
	str( browsePanel.height() ) )
check( "两者高度不一样（不是固定尺寸）", tinyPanel.height() != browsePanel.height(),
	"%d vs %d" % ( tinyPanel.height(), browsePanel.height() ) )

# 搜索时仍然是全局扁平
browsePanel.setSearchText( "sphere" )
searchRows = [ browsePanel.rowAt( i ) for i in range( browsePanel.rowCount() ) ]
check( "搜索是全局扁平的", len( searchRows ) > 1 and all( r[2] is not None for r in searchRows ), str( len( searchRows ) ) )
check( "搜索结果右边写它在哪个分类", any( r[1] for r in searchRows ), str( searchRows[:2] ) )

creatable = [ e for e in entries if NE._unwrapNodeCreator( e[3] .command ) is not None ]
check( "大部分条目能直接建（拆得出 nodeCreator）", len( creatable ) > len( entries ) * 0.5,
	"%d / %d" % ( len( creatable ) , len( entries ) ) )

sphereEntries = [ e for e in entries if e[0] == "Sphere" ]
check( "找得到 Sphere 条目", len( sphereEntries ) >= 1, str( len( sphereEntries ) ) )
if sphereEntries :
	# 走一遍 Tab 面板选中后的那条路：真的把节点建出来再撤销
	before = set( n.getName() for n in NE.collectNodes( script ) )
	script.selection().clear()
	editor._NetworkEditor__createFromMenuItem( sphereEntries[0][3], QtCore.QPointF( 300.0, -200.0 ) )
	GafferUI.EventLoop.waitForIdle()
	createdByTab = [ n.getName() for n in NE.collectNodes( script ) if n.getName() not in before ]
	check( "Tab 面板真能建出节点", len( createdByTab ) == 1, str( createdByTab ) )
	check( "建完选中它", [ n.getName() for n in script.selection() ] == createdByTab, str( [ n.getName() for n in script.selection() ] ) )
	if createdByTab :
		check( "摆在鼠标位置附近",
			NE.nodePosition( script[ createdByTab[0] ] ) is not None and
			abs( NE.nodePosition( script[ createdByTab[0] ] ).x - 300.0 / NE.PX_PER_UNIT ) < 2.0,
			str( NE.nodePosition( script[ createdByTab[0] ] ) ) )
		script.undo()
		GafferUI.EventLoop.waitForIdle()
		check( "撤销后没了", script.getChild( createdByTab[0] ) is None )

# 创建函数自己要 `menu` 的（Box / Backdrop / Reference）：也得在我们的面板里建完，
# 不能再把原生 Tab 菜单弹出来让人把名字重新打一遍。
boxEntries = [ e for e in entries if e[0] == "Box" and e[1].endswith( "Utility" ) ]
check( "找得到 Box 条目", len( boxEntries ) >= 1,
	str( [ ( e[0], e[1] ) for e in entries if e[0] == "Box" ] ) )
if boxEntries :
	boxItem = boxEntries[0][3]
	check( "Box 拆不出创建函数（它自己要 menu）", NE._unwrapNodeCreator( boxItem.command ) is None )

	before = set( n.getName() for n in NE.collectNodes( script ) )
	script.selection().clear()
	madeBox = editor._NetworkEditor__createFromMenuItem(
		boxItem, QtCore.QPointF( 420.0, -260.0 )
	)
	GafferUI.EventLoop.waitForIdle()
	newBoxes = [
		n for n in NE.collectNodes( script )
		if n.getName() not in before and isinstance( n, Gaffer.Box )
	]
	check( "Tab 面板建得出 Box", bool( madeBox ) and len( newBoxes ) == 1,
		str( ( madeBox, [ n.getName() for n in newBoxes ] ) ) )
	if newBoxes :
		check( "建完选中它",
			[ n.getName() for n in script.selection() ] == [ newBoxes[0].getName() ],
			str( [ n.getName() for n in script.selection() ] ) )
		check( "Box 摆在鼠标位置附近（不是 nan / 原点）",
			NE.positionUsable( NE.nodePosition( newBoxes[0] ) ) and
			abs( NE.nodePosition( newBoxes[0] ).x - 420.0 / NE.PX_PER_UNIT ) < 2.0,
			str( NE.nodePosition( newBoxes[0] ) ) )
		script.undo()
		GafferUI.EventLoop.waitForIdle()
		check( "一次 Ctrl+Z 就撤销掉了", script.getChild( newBoxes[0].getName() ) is None )

# 快捷键：↓ 进 Box、↑ 出来
script.selection().clear()
script.selection().add( box )
check( "Box 可以直接 ↓ 进去", NE.NetworkEditor._childrenViewable( box ) )
check( "↓ 进 Box", editor._enterSelectedNode( withModifiers = False ) and editor.getRootNode().isSame( box ) )
check( "↑ 出 Box", editor._leaveNode() and editor.getRootNode().isSame( script ) )
check( "[ 回到刚才那层", editor._previousRoot() and editor.getRootNode().isSame( box ) )
editor._nextRoot()
GafferUI.EventLoop.waitForIdle()

# 快捷键：书签
script.selection().clear()
script.selection().add( xform )
editor._assignNumericBookmark( 4 )
check( "Ctrl+4 设编号书签", Gaffer.MetadataAlgo.numericBookmark( xform ) == 4, str( Gaffer.MetadataAlgo.numericBookmark( xform ) ) )
check( "按 4 跳得回去", editor._findNumericBookmark( 4 ) )
editor._assignNumericBookmark( 0 )

# 原生右键菜单（Edit… / Enabled / Connections / Focus 那一整套）
nativeMenu = IECore.MenuDefinition()
check(
	"节点右键菜单用的是原生定义",
	editor._NetworkEditor__appendNativeNodeMenu( nativeMenu, xform ),
	str( [ p for p, i in nativeMenu.items() ][:6] )
)
check(
	"里面有原生的 Edit…",
	any( p.endswith( "Edit..." ) for p, i in nativeMenu.items() ),
	str( [ p for p, i in nativeMenu.items() ] )
)

view.frameAll()
# 进 Box 之前先放大到某个节点上：出来之后要回到这儿，而不是「全部节点」的全景
view.frameItems( [ editor._NetworkEditor__nodeItems[ "heroSphere" ] ] )
GafferUI.EventLoop.waitForIdle()
viewBeforeBox = view.viewedSceneRect()
editor._enterNode( box )
GafferUI.EventLoop.waitForIdle()
view.frameAll()
view.scale( 1.5, 1.5 )
shot( "14_inside_box.png" )
editor._leaveNode()
GafferUI.EventLoop.waitForIdle()
viewAfterBox = view.viewedSceneRect()
check(
	"出 Box 回到进去之前看的地方（不是全景）",
	viewBeforeBox is not None and viewAfterBox is not None and
	abs( viewAfterBox.center().x() - viewBeforeBox.center().x() ) < 3.0 and
	abs( viewAfterBox.center().y() - viewBeforeBox.center().y() ) < 3.0 and
	abs( viewAfterBox.width() - viewBeforeBox.width() ) < max( 3.0, viewBeforeBox.width() * 0.02 ),
	"before=%s after=%s" % ( viewBeforeBox, viewAfterBox )
)
view.frameAll()

# pipeline 快捷键（S = 切换上下文）弹出来的东西现在也是我们自己的面板
script.selection().clear()
script.selection().add( xform )
editor._forwardShortcutKey( QtGui.QKeyEvent( QtCore.QEvent.KeyPress, QtCore.Qt.Key_S, QtCore.Qt.NoModifier ) )
GafferUI.EventLoop.waitForIdle()
internalPanel = editor._NetworkEditor__creatorPopup
if internalPanel is not None and internalPanel.isVisible() :
	internalPanel.grab().save( os.path.join( OUT, "20_internal_menu_panel.png" ) )
	internalPanel.hide()
script.selection().clear()

# 生产里的 S 菜单：三个分组 + 每组一条勾着（当前 shot / layer / quality）。
# 这个图上要看到的是「根层只有三行分组」「点开才是条目」「当前那条前面有对勾」。
switchRan = []
def switchToThing( state, name ) :
	switchRan.append( ( name, state ) )

switchDefinition = IECore.MenuDefinition()
# ⚠️ 循环变量别用 `group` / `name` —— 这个脚本里 `group` 是上面建的那个 Group 节点，
# 覆盖掉后面 `script.setFocus( group )` 就炸了
for switchGroup, switchNames, switchCurrent in (
	( "Switch To Shot", [ "sh010", "sh020", "sh030", "sh040" ], "sh020" ),
	( "Switch To Layer", [ "default", "cha", "bg", "fx" ], "default" ),
	( "Switch To Quality", [ "default", "low", "mid", "final" ], "final" ),
) :
	for switchName in switchNames :
		switchDefinition.append(
			"/%s/%s" % ( switchGroup, switchName ),
			{
				"command" : functools.partial(
					switchToThing, name = "%s/%s" % ( switchGroup, switchName )
				),
				"checkBox" : switchName == switchCurrent,
			}
		)

switchNativePopups = []
switchOriginalPopup = GafferUI.Menu.popup
GafferUI.Menu.popup = lambda menu, *args, **kw : switchNativePopups.append( menu )
try :
	editor._showMenuAsPanel( GafferUI.Menu( switchDefinition, title = "Switch Context" ) )
finally :
	GafferUI.Menu.popup = switchOriginalPopup

switchPanel = editor._NetworkEditor__creatorPopup
switchRootRows = [ switchPanel.rowAt( i ) for i in range( switchPanel.rowCount() ) ]
check(
	"生产那种分组菜单：根层只列分组，不堆在一起",
	[ r[0] for r in switchRootRows ] == [ "Switch To Layer", "Switch To Quality", "Switch To Shot" ],
	str( [ r[0] for r in switchRootRows ] )
)
shotColumnRow = [ r[0] for r in switchRootRows ].index( "Switch To Shot" )
switchPanel.hoverRow( shotColumnRow )
GafferUI.EventLoop.waitForIdle()
check( "点开分组才是条目", switchPanel.rowCount( 1 ) == 4, str( switchPanel.rowCount( 1 ) ) )
check(
	"当前那条勾着（面板上画对勾）",
	[ switchPanel.rowChecked( i, 1 ) for i in range( 4 ) ] == [ False, True, False, False ],
	str( [ ( switchPanel.rowAt( i, 1 )[0], switchPanel.rowChecked( i, 1 ) ) for i in range( 4 ) ] )
)
switchPanel.grabAll().save( os.path.join( OUT, "30_switch_context_grouped.png" ) )

# 点一条：命令真的跑起来（勾选状态当第一个位置参数），而且不会退回原生那个搜索菜单
switchPanel.activateRow( 2, 1 )
GafferUI.EventLoop.waitForIdle()
check( "点条目真的执行了原生命令", switchRan == [ ( "Switch To Shot/sh030", True ) ], str( switchRan ) )
check( "没有再弹原生的搜索菜单", not switchNativePopups, str( switchNativePopups ) )
switchPanel.hide()

# 自动对齐参考线（拖到差一点点对齐时亮起来）—— 默认关，这里临时打开出图
editor.setSnapEnabled( True )
view.frameAll()
items = editor._NetworkEditor__nodeItems
guideA, guideB = items[ "groundPlane" ], items[ "heroSphere" ]
guidePress = view.mapFromScene( guideB.pos() )
QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonPress, QtCore.QPointF( guidePress ), QtCore.QPointF( guidePress ),
	QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
) )
# 摆成「差一点点就站成一条竖列」：x 差 4px、y 差 150px（在感知半径内）
guideB.setPos( QtCore.QPointF( guideA.pos().x() + 4.0, guideA.pos().y() + 150.0 ) )
GafferUI.EventLoop.waitForIdle()
shot( "19_snap_guide.png" )

# 参考线得真画出来，而且**只画在两个节点之间**（不是拉满整个视口）
guideList = editor.snapGuides()
check( "出图时参考线是亮着的", len( guideList ) == 1, str( guideList ) )

guideImage = view.grab().toImage()

# 参考线是 1px 虚线、还开着抗锯齿 —— 抓出来的像素是**混过的**，别去比精确颜色，
# 按"偏黄"（红明显大于蓝）判，并且只在参考线自己那几列 x 上取样（别处有黄卡片）。
guideXView = view.mapFromScene(
	QtCore.QPointF( guideList[ 0 ][ 1 ], guideA.pos().y() ) ).x()

def guidePixels( y0, y1 ) :

	count = 0
	best = 0
	for y in range( max( 0, int( y0 ) ), min( guideImage.height(), int( y1 ) ) ) :
		for x in range( max( 0, guideXView - 3 ), min( guideImage.width(), guideXView + 4 ) ) :
			pixel = QtGui.QColor( guideImage.pixel( x, y ) )
			yellowness = pixel.red() - pixel.blue()
			best = max( best, yellowness )
			if yellowness > 40 and pixel.red() > 90 and pixel.green() >= pixel.blue() :
				count += 1
	return count, best

guideMidY = view.mapFromScene( QtCore.QPointF(
	guideA.pos().x(), ( guideA.pos().y() + guideB.pos().y() ) / 2.0 ) ).y()
guideTopY = view.mapFromScene( QtCore.QPointF(
	guideA.pos().x(), guideA.pos().y() - 260.0 ) ).y()

between, betweenBest = guidePixels( guideMidY - 12, guideMidY + 12 )
above, aboveBest = guidePixels( max( 0, guideTopY - 20 ), max( 1, guideTopY + 20 ) )
check( "两个节点之间画了参考线", between > 0,
	"between=%d 最黄=%d (x=%d y=%d 图 %dx%d)" % (
		between, betweenBest, guideXView, guideMidY,
		guideImage.width(), guideImage.height() ) )
check( "节点上方老远处没有参考线（只覆盖两节点那一段）", above == 0,
	"above=%d 最黄=%d" % ( above, aboveBest ) )
QtWidgets.QApplication.sendEvent( view.viewport(), QtGui.QMouseEvent(
	QtCore.QEvent.MouseButtonRelease, QtCore.QPointF( guidePress ), QtCore.QPointF( guidePress ),
	QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier
) )
script.undo()
GafferUI.EventLoop.waitForIdle()
editor.setSnapEnabled( False )      # 后面的拖动断言要落在精确位置，关掉
view.frameAll()

# Box 上的 + 号特写
view.frameAll()
items = editor._NetworkEditor__nodeItems
if "lightRigBox" in items :
	view.frameItems( [ items[ "lightRigBox" ] ] )
	view.scale( 0.6, 0.6 )
	shot( "18_box_plug_adders.png" )
view.frameAll()

# 接口悬停：放大 + 名字
# 注意：中间建过/撤销过节点，图重建过 —— `scene.clear()` 会销毁旧的 C++ item，
# 之前抓在手里的 Python 包装立刻失效，必须重新取一遍。
view.frameAll()
items = editor._NetworkEditor__nodeItems
hoverTarget = items.get( "aiStandardSurface" )
if hoverTarget is not None :
	editor._setHoveredNodule( hoverTarget, NE.noduleLayout( surface )[ "left" ][0] )
	GafferUI.EventLoop.waitForIdle()
	view.frameItems( [ hoverTarget ] )
	shot( "17_nodule_hover.png" )
	editor._setHoveredNodule( None, None )
view.frameAll()

# Tab 建节点面板长啥样
popup = NE._NodeCreatorPopup( view )
popup.setEntries( entries )
popup.popupAt( window._qtWidget().mapToGlobal( QtCore.QPoint( 260, 150 ) ), lambda item : None )
GafferUI.EventLoop.waitForIdle()
popup.grabAll().save( os.path.join( OUT, "15_tab_creator.png" ) )       # 根层：大类
popup.activateRow( 0 )
GafferUI.EventLoop.waitForIdle()
popup.grabAll().save( os.path.join( OUT, "21_tab_creator_drilled.png" ) )  # 点开一列
popup._NodeCreatorPopup__goUp()
popup.hoverRow( 0 )
secondCategory = next(
	( i for i in range( popup.rowCount( 1 ) ) if popup.rowAt( i, 1 )[3] ), None
)
if secondCategory is not None :
	popup.hoverRow( secondCategory, 1 )      # 再浮出第三列
GafferUI.EventLoop.waitForIdle()
popup.grabAll().save( os.path.join( OUT, "22_tab_creator_hover.png" ) )    # 级联三列
popup._NodeCreatorPopup__goUp()
popup._NodeCreatorPopup__goUp()
popup.setSearchText( "sphere" )
GafferUI.EventLoop.waitForIdle()
popup.grabAll().save( os.path.join( OUT, "16_tab_creator_search.png" ) )   # 搜索：全局扁平
check( "Tab 面板搜 sphere 有结果", popup.rowCount() > 0, str( popup.rowCount() ) )

# --- 首字母缩写：真机上打 "ass" 就要给 aiStandardSurface ---
popup.setSearchText( "ass" )
GafferUI.EventLoop.waitForIdle()
# 真机 NodeMenu 里显示的是**带空格的显示名**（"Standard Surface"），
# 搜索认的是条目自己的 `searchText`（"aiStandardSurface"）—— 缩写就是打在它上面的。
acronymRows = [ popup.rowAt( i )[0] for i in range( popup.rowCount() ) ]
check( "打 ass 搜得到 aiStandardSurface（真机 NodeMenu）",
	"Standard Surface" in acronymRows, str( acronymRows[:8] ) )
check( "而且排在前几条", "Standard Surface" in acronymRows[:5], str( acronymRows[:8] ) )
check( "排在「名字里正好含 ass」的前面（Glass / Shader Assignment）",
	"Standard Surface" in acronymRows and (
		"Glass" not in acronymRows or
		acronymRows.index( "Standard Surface" ) < acronymRows.index( "Glass" )
	), str( acronymRows[:8] ) )
popup.grabAll().save( os.path.join( OUT, "24_tab_creator_acronym.png" ) )

# --- 常用 / 喜爱 ---
popup.setSearchText( "" )
# 在真机的 NodeMenu 里挑几个常用节点钉上 / 记几笔使用（用的是**显示名**）
liveUsage = NE.creatorUsage()
menuKeys = [ NE._entryKey( name, category ) for name, category, unusedSearch, unusedItem in entries ]
def keyFor( leafName ) :
	return next( ( k for k in menuKeys if k.endswith( "/ " + leafName ) or k == leafName ), None )

for leaf in ( "Standard Surface", "Shader Assignment" ) :
	key = keyFor( leaf )
	if key is not None :
		liveUsage.toggleFavourite( key )
for leaf, times in ( ( "Sphere", 5 ), ( "Path Filter", 3 ), ( "Group", 2 ) ) :
	key = keyFor( leaf )
	for unused in range( times if key is not None else 0 ) :
		liveUsage.record( key )

popup.setEntries( entries, usage = liveUsage )
GafferUI.EventLoop.waitForIdle()
favouriteRows = [ popup.rowAt( i )[0] for i in range( popup.rowCount() ) ]
check( "根层顶上有「★ 喜爱」", "★ Favourites" in favouriteRows, str( favouriteRows[:6] ) )
check( "根层有「常用」", "Frequent" in favouriteRows, str( favouriteRows[:12] ) )
check( "喜爱在常用前面",
	"★ Favourites" in favouriteRows and "Frequent" in favouriteRows and
	favouriteRows.index( "★ Favourites" ) < favouriteRows.index( "Frequent" ), str( favouriteRows[:12] ) )
check( "用得最多的排常用第一条",
	"Frequent" in favouriteRows and favouriteRows[ favouriteRows.index( "Frequent" ) + 1 ] == "Sphere",
	str( favouriteRows[:12] ) )
starRow = favouriteRows.index( "★ Favourites" ) + 1 if "★ Favourites" in favouriteRows else 0
check( "喜爱那几条画得出星", popup.rowIsFavourite( starRow ) )
popup.grabAll().save( os.path.join( OUT, "23_tab_creator_favourites.png" ) )

# 钉住的东西搜索时也往前排
popup.setSearchText( "shader" )
GafferUI.EventLoop.waitForIdle()
shaderRows = [ popup.rowAt( i )[0] for i in range( popup.rowCount() ) ]
check( "钉住的在搜索结果里也靠前",
	"Shader Assignment" not in shaderRows or shaderRows.index( "Shader Assignment" ) < 5,
	str( shaderRows[:8] ) )
popup.grabAll().save( os.path.join( OUT, "25_tab_creator_search_favourite.png" ) )
popup.setSearchText( "" )
popup.hide()


##########################################################################
# 从别的编辑器拖东西进来（真机：gui startup 跑过，原生的 drop 处理器都挂着了）
##########################################################################

import GafferSceneUI

view.frameAll()
GafferUI.EventLoop.waitForIdle()

def dropPos( name ) :

	item = editor._NetworkEditor__nodeItems[ name ]
	return view.mapFromScene( item.sceneBoundingRect().center() )

dropIsolate = add( GafferScene.Isolate( "dropIsolate" ), 30, 10 )
GafferUI.EventLoop.waitForIdle()
view.frameAll()
GafferUI.EventLoop.waitForIdle()

# --- 路径落在节点上 → 建 PathFilter 接上去（真机走的是**转发给原生 NodeGadget**那条路）---
pathEvent = GafferUI.DragDropEvent()
pathEvent.data = IECore.StringVectorData( [ "/group/sphere", "/group/plane" ] )
handled = editor._performDrop( pathEvent, dropPos( "dropIsolate" ) )
check( "从视口/层级视图拖路径过来被接住了", handled )
dropFilterInput = dropIsolate[ "filter" ].getInput()
check(
	"自动建了 PathFilter 并接上",
	dropFilterInput is not None and isinstance( dropFilterInput.node(), GafferScene.PathFilter ),
	str( dropFilterInput )
)
if dropFilterInput is not None :
	check(
		"paths 写进去了",
		list( dropFilterInput.node()[ "paths" ].getValue() ) == [ "/group/plane", "/group/sphere" ],
		str( list( dropFilterInput.node()[ "paths" ].getValue() ) )
	)
	GafferUI.EventLoop.waitForIdle()
	check(
		"新建的 PathFilter 也画出来了",
		dropFilterInput.node().getName() in editor._NetworkEditor__nodeItems,
		str( sorted( editor._NetworkEditor__nodeItems ) )
	)

	# Shift 追加
	addEvent = GafferUI.DragDropEvent()
	addEvent.data = IECore.StringVectorData( [ "/group/cube" ] )
	addEvent.modifiers = addEvent.Modifiers.Shift
	editor._performDrop( addEvent, dropPos( "dropIsolate" ) )
	check(
		"Shift 是追加",
		list( dropFilterInput.node()[ "paths" ].getValue() ) ==
			[ "/group/cube", "/group/plane", "/group/sphere" ],
		str( list( dropFilterInput.node()[ "paths" ].getValue() ) )
	)

view.frameAll()
shot( "26_path_drop.png" )

# --- 单条路径落在空白处 → 跳到生成这个位置的那个节点（原生 `__locationDrop`）---
hierarchy = GafferSceneUI.HierarchyView( script )
hierarchyWindow = GafferUI.Window()
hierarchyWindow.setChild( hierarchy )
hierarchyWindow.setVisible( True )
script.setFocus( group )
GafferUI.EventLoop.waitForIdle()

# sourceWidget 得是 HierarchyView **里面**的控件（`Widget.ancestor` 不含自身）
sourceWidget = None
for qWidget in hierarchy._qtWidget().findChildren( QtWidgets.QWidget ) :
	owner = GafferUI.Widget._owner( qWidget )
	if owner is not None and owner.ancestor( GafferUI.Editor ) is hierarchy :
		sourceWidget = owner
		break
check( "拿得到 HierarchyView 里的控件当拖拽来源", sourceWidget is not None )

if sourceWidget is not None :

	locationEvent = GafferUI.DragDropEvent()
	locationEvent.data = IECore.StringVectorData( [ "/group/sphere" ] )
	locationEvent.sourceWidget = sourceWidget
	locationData = editor._locationDropData( locationEvent )
	check( "认出这是一次「场景位置」拖拽", locationData is not None, str( locationData ) )

	script.selection().clear()
	emptyPoint = view.mapFromScene( QtCore.QPointF( -100000, -100000 ) )
	handled = editor._performDrop( locationEvent, emptyPoint )
	check( "落在空白处被接住了", handled )
	check(
		"跳到了生成这个位置的那个节点上（原生就是这个行为，不是建 PathFilter）",
		[ n.getName() for n in script.selection() ] == [ "heroSphere" ],
		str( [ n.getName() for n in script.selection() ] )
	)

hierarchyWindow.setVisible( False )
script.setFocus( None )
GafferUI.EventLoop.waitForIdle()

# --- 拖节点进来 → 换到它那一层并取景 ---
dropBox = add( Gaffer.Box( "dropBox" ), 30, -10 )
boxInner = GafferScene.Sphere( "boxInner" )
dropBox.addChild( boxInner )
place( boxInner, 0, 0 )
GafferUI.EventLoop.waitForIdle()
nodeEvent = GafferUI.DragDropEvent()
nodeEvent.data = boxInner
check( "拖节点进来被接住了", editor._performDrop( nodeEvent, view.mapFromScene( QtCore.QPointF( -100000, -100000 ) ) ) )
check( "换到了它所在那一层", editor.getRootNode().isSame( dropBox ), editor.getRootNode().getName() )
editor.setRootNode( script )
GafferUI.EventLoop.waitForIdle()

view.frameAll()
GafferUI.EventLoop.waitForIdle()

##########################################################################
# 真实材质图：逐个圆点 / 逐条连线和原生一致（tests/shader_test.gfr，已脱敏）
#
# 这个图是从生产里来的：34 个 ArnoldShader + 5 个 OSLShader，装在一个 Box 里，
# 里头有一堆「颜色输出展开成 RGBA、拿其中一个分量去驱动某个 float 参数」的接法 ——
# 我们和原生第一次跑就差了 14 个圆点（见下）。
##########################################################################

# screengrab 跑 commandFile 时**没有 `__file__`**（`__name__` 都是 'builtins'），
# 包的位置问模块要（`NE.packageRoot()`）—— 别自己数 dirname，
# 单文件拆成包之后层数就变了。
shaderPath = os.path.join( NE.packageRoot(), "tests", "shader_test.gfr" )
if os.path.isfile( shaderPath ) :

	shaderScript = Gaffer.ScriptNode()
	application.root()[ "scripts" ].addChild( shaderScript )
	shaderScript[ "fileName" ].setValue( shaderPath )
	shaderScript.load()
	GafferUI.EventLoop.waitForIdle()

	# **别写死名字**：用户会换这个测试文件（换过一次了）。找**节点最多的那个 Box**
	# 当材质图，递归找。
	def boxes( parent ) :

		result = []
		for node in parent.children( Gaffer.Node ) :
			if isinstance( node, Gaffer.Box ) :
				result.append( node )
				result.extend( boxes( node ) )
		return result

	allBoxes = boxes( shaderScript )
	check( "文件里有 Box", bool( allBoxes ), str( len( allBoxes ) ) )
	shaderBox = sorted(
		allBoxes, key = lambda b : ( -len( list( b.children( Gaffer.Node ) ) ), b.getName() )
	)[0] if allBoxes else shaderScript
	shaderNodes = list( shaderBox.children( Gaffer.Node ) )
	check( "材质测试图读进来了（%d 个节点）" % len( shaderNodes ), len( shaderNodes ) >= 6 )

	shaderEditor = NE.NetworkEditor( shaderScript )
	shaderWindow = GafferUI.Window( "shader" )
	shaderWindow.setChild( shaderEditor )
	shaderWindow._qtWidget().resize( 1500, 950 )
	shaderWindow.setVisible( True )
	GafferUI.EventLoop.waitForIdle()
	shaderEditor.setRootNode( shaderBox )
	GafferUI.EventLoop.waitForIdle()

	# 原生：**一定要拿真正的原生类**，不然接管之后自己和自己比
	nativeShaderEditor = NE._nativeGraphEditorClass()( shaderScript )
	nativeShaderWindow = GafferUI.Window( "shaderNative" )
	nativeShaderWindow.setChild( nativeShaderEditor )
	nativeShaderWindow._qtWidget().resize( 1500, 950 )
	nativeShaderWindow.setVisible( True )
	GafferUI.EventLoop.waitForIdle()
	nativeGraphGadget = nativeShaderEditor.graphGadget()
	nativeGraphGadget.setRoot( shaderBox )
	GafferUI.EventLoop.waitForIdle()

	## 原生那个节点上「真正画成圆点」的插口（父插口拿到的是 CompoundNodule 容器，
	## 不是圆点，要排掉），连同它落在哪条边、在那条边上排第几。
	def nativeNodules( node ) :

		gadget = nativeGraphGadget.nodeGadget( node )
		if gadget is None :
			return None

		sections = { "top" : [], "bottom" : [], "left" : [], "right" : [] }
		bound = gadget.bound()
		for plug in Gaffer.Plug.RecursiveRange( node ) :
			nodule = gadget.nodule( plug )
			if nodule is None :
				continue
			if len( plug.children( Gaffer.Plug ) ) and any(
				gadget.nodule( child ) is not None for child in plug.children( Gaffer.Plug )
			) :
				continue          # 容器，不是圆点
			try :
				point = nodule.transformedBound( gadget ).center()
			except Exception :
				continue
			dx = min( abs( point.x - bound.min().x ), abs( point.x - bound.max().x ) )
			dy = min( abs( point.y - bound.min().y ), abs( point.y - bound.max().y ) )
			if dy <= dx :
				section = "top" if point.y > 0 else "bottom"
				order = point.x
			else :
				section = "left" if point.x < 0 else "right"
				order = -point.y
			sections[ section ].append( ( order, plug.relativeName( node ) ) )

		return {
			section : [ name for unusedOrder, name in sorted( entries ) ]
			for section, entries in sections.items()
		}

	noduleDiffs = []
	for node in shaderNodes :
		native = nativeNodules( node )
		if native is None :
			continue
		mine = {
			section : [ plug.relativeName( node ) for plug in plugs ]
			for section, plugs in NE.noduleLayout( node ).items()
		}
		for section in ( "top", "bottom", "left", "right" ) :
			if native[ section ] != mine[ section ] :
				noduleDiffs.append( ( node.getName(), section, native[ section ], mine[ section ] ) )

	check(
		"材质图上每个圆点都和原生对得上（含所在边和顺序）",
		not noduleDiffs,
		str( noduleDiffs[:3] )
	)

	# 原生的连线：ConnectionGadget 两头的 nodule 插口
	nativeShaderEdges = set()
	for node in shaderNodes :
		for plug in Gaffer.Plug.RecursiveRange( node ) :
			connection = nativeGraphGadget.connectionGadget( plug )
			if connection is None :
				continue
			srcNodule, dstNodule = connection.srcNodule(), connection.dstNodule()
			if srcNodule is None or dstNodule is None :
				continue
			src, dst = srcNodule.plug(), dstNodule.plug()
			nativeShaderEdges.add( (
				src.node().getName(), src.relativeName( src.node() ),
				dst.node().getName(), dst.relativeName( dst.node() ),
			) )

	myShaderEdges = set(
		(
			edge.srcNode.getName(), edge.srcPlug.relativeName( edge.srcNode ),
			edge.dstNode.getName(), edge.dstPlug.relativeName( edge.dstNode ),
		)
		for edge in NE.collectEdges( shaderBox, shaderNodes )
	)

	check( "材质图的连线条数和原生一样（%d 条）" % len( nativeShaderEdges ),
		len( nativeShaderEdges ) == len( myShaderEdges ),
		"原生 %d / 我们 %d" % ( len( nativeShaderEdges ), len( myShaderEdges ) ) )
	check( "而且每一条的两头插口都一样",
		nativeShaderEdges == myShaderEdges,
		"原生有我们没有 %s；我们有原生没有 %s" % (
			sorted( nativeShaderEdges - myShaderEdges )[:3],
			sorted( myShaderEdges - nativeShaderEdges )[:3] )
	)

	# 「分量驱动 float 参数」那几个：元数据被写在了没有子插口的 FloatPlug 上
	# 「`childrenVisible` 打在没有子插口的插口上」——**扫出来**，别写死名字
	componentDriven = []
	for node in shaderNodes :
		for plug in Gaffer.Plug.RecursiveRange( node ) :
			if len( plug.children( Gaffer.Plug ) ) :
				continue
			if bool( Gaffer.Metadata.value( plug, "compoundNumericNodule:childrenVisible" ) ) :
				componentDriven.append( ( node, plug ) )

	check( "文件里有「childrenVisible 打在没有子插口的插口上」这种（%d 处）" % len( componentDriven ),
		True )
	for node, plug in componentDriven[:6] :
		check( "%s.%s 照样有圆点（没有子插口就不是复合圆点）" % (
				node.getName(), plug.relativeName( node ) ),
			not NE.isCompoundNodule( plug ) and
			any( p.isSame( plug ) for plugs in NE.noduleLayout( node ).values() for p in plugs ) )

	# 侧边参数名：接上线的那些是**粗体**，宽度得按粗体量，不然名字被裁
	shaderItems = shaderEditor._NetworkEditor__nodeItems
	boldMetrics = QtGui.QFontMetricsF( NE._font( NE.SIDE_LABEL_SIZE, bold = True ) )
	clipped = []
	labelled = 0
	for name, item in shaderItems.items() :
		labels = item._NodeItem__sideLabels
		labelled += 1 if labels else 0
		for key, ( text, width, connected ) in labels.items() :
			if width < boldMetrics.horizontalAdvance( text ) - 0.01 :
				clipped.append( ( name, text, width ) )
	check( "材质节点都有侧边参数名（%d 个）" % labelled, labelled >= 5 )
	check( "没有一个标签会被粗体撑破（连上线就是粗体）", not clipped, str( clipped[:3] ) )

	# 出图：挑一个连了一堆线的材质节点，看侧边参数名
	shaderView = shaderEditor.graphView()
	shaderView.frameAll()
	GafferUI.EventLoop.waitForIdle()
	heroItem = None
	heroLabels = -1
	for name, item in shaderItems.items() :
		count = len( item._NodeItem__sideLabels )
		if count > heroLabels :
			heroItem, heroLabels = item, count
	if heroItem is not None :
		shaderView.frameItems( [ heroItem ] )
		GafferUI.EventLoop.waitForIdle()
		shaderWindow._qtWidget().grab().save( os.path.join( OUT, "26_shader_side_labels.png" ) )
	shaderView.frameAll()
	GafferUI.EventLoop.waitForIdle()
	shaderWindow._qtWidget().grab().save( os.path.join( OUT, "27_shader_graph.png" ) )
	# 原生那个视图是 OpenGL 的，`grab()` 抓不到 GL 内容（抓出来是一张黑图）——
	# 它只用来当**数据上的**参照（圆点 / 连线），不出图。

	# --- 自动排列：拿这张 44 个节点的真实材质图跑我们自己的分层布局 ---
	arrangePositions = NE.layoutNodes( shaderNodes, shaderBox, nativeGraphGadget )
	check( "44 个节点都排上了", len( arrangePositions ) >= len( shaderNodes ) - 2,
		"%d / %d" % ( len( arrangePositions ), len( shaderNodes ) ) )

	arrangeRows = {}
	for node, position in arrangePositions.items() :
		arrangeRows.setdefault( round( position.y, 3 ), [] ).append( ( position.x, node ) )
	check( "分出了多层", len( arrangeRows ) >= 4, str( len( arrangeRows ) ) )

	overlaps = []
	for y, entries in arrangeRows.items() :
		entries.sort()
		for index in range( len( entries ) - 1 ) :
			left, leftNode = entries[ index ]
			right, rightNode = entries[ index + 1 ]
			need = (
				NE.nodeSizeUnits( leftNode, nativeGraphGadget )[0] / 2.0 +
				NE.nodeSizeUnits( rightNode, nativeGraphGadget )[0] / 2.0 +
				NE.LAYOUT_HORIZONTAL_GAP - 1e-3
			)
			if right - left < need :
				overlaps.append( ( leftNode.getName(), rightNode.getName(), right - left, need ) )
	check( "同一层里一个都不重叠（按真实宽度算的间距）", not overlaps, str( overlaps[:3] ) )

	# 连线不许**逆着流向**走。注意这张图里有两种流向：
	# 场景节点（BoxIn / Dot / ShaderAssignment / BoxOut）竖着流、材质节点横着流。
	axisOf = dict( ( node.getName(), NE.nodeFlowAxis( node ) ) for node in shaderNodes )
	backwards = []
	for edge in NE.collectEdges( shaderBox, shaderNodes ) :
		if edge.auxiliary :
			continue
		if edge.srcNode not in arrangePositions or edge.dstNode not in arrangePositions :
			continue
		src, dst = arrangePositions[ edge.srcNode ], arrangePositions[ edge.dstNode ]
		axes = ( axisOf[ edge.srcNode.getName() ], axisOf[ edge.dstNode.getName() ] )
		if axes == ( "vertical", "vertical" ) and src.y < dst.y - 1e-3 :
			backwards.append( ( edge.srcNode.getName(), edge.dstNode.getName(), "往上" ) )
		elif axes == ( "horizontal", "horizontal" ) and src.x > dst.x + 1e-3 :
			backwards.append( ( edge.srcNode.getName(), edge.dstNode.getName(), "往左" ) )
	check( "没有一条连线逆着流向走（场景往下、材质往右）", not backwards, str( backwards[:3] ) )

	# 材质那一坨要整个待在 ShaderAssignment 左边（用户要的「以它为核心」）
	shaderOnly = [ node for node in shaderNodes if axisOf[ node.getName() ] == "horizontal" ]
	assignments = [
		node for node in shaderNodes if isinstance( node, GafferScene.ShaderAssignment )
	]
	if shaderOnly and assignments :
		assignment = assignments[0]
		rightmost = max( arrangePositions[ node ].x for node in shaderOnly )
		check( "材质整坨在 ShaderAssignment 左边",
			rightmost < arrangePositions[ assignment ].x,
			"材质最右 %.1f / assignment %.1f" % ( rightmost, arrangePositions[ assignment ].x ) )
		check( "材质那条主链和 shader 插口大致同高",
			min(
				abs( arrangePositions[ node ].y - arrangePositions[ assignment ].y )
				for node in shaderOnly
			) < 1.0,
			"最近的差 %.1f" % min(
				abs( arrangePositions[ node ].y - arrangePositions[ assignment ].y )
				for node in shaderOnly ) )

	# BoxIn / BoxOut 得在场景那一串的两头
	boxIOs = [ node for node in shaderNodes if isinstance( node, Gaffer.BoxIO ) ]
	sceneNodes = [ node for node in shaderNodes if axisOf[ node.getName() ] == "vertical" ]
	for boxIO in boxIOs :
		if boxIO.plug() is None or not isinstance( boxIO.plug(), GafferScene.ScenePlug ) :
			continue
		if isinstance( boxIO, Gaffer.BoxIn ) :
			check( "%s 排在场景那一串最上面" % boxIO.getName(),
				arrangePositions[ boxIO ].y >= max(
					arrangePositions[ n ].y for n in sceneNodes ) - 1e-3,
				"%.1f vs %.1f" % ( arrangePositions[ boxIO ].y,
					max( arrangePositions[ n ].y for n in sceneNodes ) ) )
		else :
			check( "%s 排在场景那一串最下面" % boxIO.getName(),
				arrangePositions[ boxIO ].y <= min(
					arrangePositions[ n ].y for n in sceneNodes ) + 1e-3,
				"%.1f vs %.1f" % ( arrangePositions[ boxIO ].y,
					min( arrangePositions[ n ].y for n in sceneNodes ) ) )

	# --- 和原生比交叉数（"优雅"得有个能量的东西）---
	def countCrossings( positions ) :

		def cross( o, a, b ) :
			return ( a.x - o.x ) * ( b.y - o.y ) - ( a.y - o.y ) * ( b.x - o.x )

		segments = []
		for edge in NE.collectEdges( shaderBox, shaderNodes ) :
			if edge.auxiliary :
				continue
			if edge.srcNode in positions and edge.dstNode in positions :
				segments.append( ( positions[ edge.srcNode ], positions[ edge.dstNode ] ) )

		total = 0
		for i in range( len( segments ) ) :
			for j in range( i + 1, len( segments ) ) :
				( p1, p2 ), ( p3, p4 ) = segments[i], segments[j]
				d1, d2 = cross( p3, p4, p1 ), cross( p3, p4, p2 )
				d3, d4 = cross( p1, p2, p3 ), cross( p1, p2, p4 )
				if ( ( d1 > 0 ) != ( d2 > 0 ) ) and ( ( d3 > 0 ) != ( d4 > 0 ) ) :
					total += 1
		return total

	mineCrossings = countCrossings( arrangePositions )

	with Gaffer.UndoScope( shaderScript ) :
		nativeGraphGadget.getLayout().layoutNodes( nativeGraphGadget, Gaffer.StandardSet( shaderNodes ) )
	GafferUI.EventLoop.waitForIdle()
	nativeLayoutPositions = dict( ( node, NE.nodePosition( node ) ) for node in shaderNodes )
	nativeCrossings = countCrossings( nativeLayoutPositions )
	shaderScript.undo()
	GafferUI.EventLoop.waitForIdle()

	check(
		"我们排出来的连线交叉比原生少（我们 %d / 原生 %d）" % ( mineCrossings, nativeCrossings ),
		mineCrossings < nativeCrossings,
		"我们 %d / 原生 %d" % ( mineCrossings, nativeCrossings )
	)

	with Gaffer.UndoScope( shaderScript ) :
		for node, position in arrangePositions.items() :
			NE.setNodePosition( node, position )
	GafferUI.EventLoop.waitForIdle()
	shaderView.frameAll()
	GafferUI.EventLoop.waitForIdle()
	shaderWindow._qtWidget().grab().save( os.path.join( OUT, "29_shader_auto_arrange.png" ) )
	shaderScript.undo()
	GafferUI.EventLoop.waitForIdle()

	shaderWindow.setVisible( False )
	nativeShaderWindow.setVisible( False )


application.setGrabWidget( editor )

with open( "/tmp/network_editor_e2e.txt", "w" ) as f :
	f.write( "\n".join( report ) + "\n" )
	f.write( "%d/%d passed\n" % ( len( [ r for r in report if r.startswith( "PASS" ) ] ), len( report ) ) )
