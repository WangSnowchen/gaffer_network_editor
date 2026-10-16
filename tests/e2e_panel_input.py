# -*- coding: utf-8 -*-
##########################################################################
# 真机真输入：两件只有真屏幕 + 真鼠标测得出来的事
#   1. 建节点面板改成「一列一个窗口」（嵌套 popup）之后，事件派发还准不准；
#   2. 视口更新模式从 `FullViewportUpdate` 换成 `SmartViewportUpdate` 之后，
#      平移 / 缩放 / 橡皮筋会不会留残迹（离屏抓图**测不出来**：`grab()` 永远是
#      重新渲染一遍，看不到屏幕上真正显示的内容）；
#   3. 按住 X 划线断连 —— X11 按住约 0.5 秒后会开始发 press/release 对，
#      合成事件里没有自动重复，**只有真键盘长按测得出来**。
#
# 无头测试只能直接调 `_routeMouse`；这里用 xdotool 真的挪鼠标 / 真的点，走完整条
# 「事件只发给最上面那个 popup → 面板按全局坐标自己派发」的路。
#
#   DISPLAY=:0 gaffer env python tests/e2e_panel_input.py
#
# 报告写 /tmp/panel_input_report.txt
##########################################################################

import os, sys, time, subprocess

sys.path.insert( 0, os.path.join( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ), "python" ) )

import IECore
from Qt import QtCore, QtGui, QtWidgets

import networkEditor as NE

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication( [] )

_passed = []
_failed = []

def check( name, condition, detail = "" ) :

	( _passed if condition else _failed ).append( "%s  %s" % ( name, detail ) )
	print( "%s  %s  %s" % ( "PASS" if condition else "FAIL", name, detail ) )

def pump( seconds = 0.35 ) :

	end = time.time() + seconds
	while time.time() < end :
		app.processEvents()
		time.sleep( 0.01 )

def mouseTo( point ) :

	# **先挪到旁边再挪过去**：光标要是已经在目标点上，X 根本不会发 motion 事件，
	# `itemEntered` 就不来（真机上偶发"第二列没开出来"就是这么来的）。
	subprocess.call( [ "xdotool", "mousemove", str( point.x() + 6 ), str( point.y() + 6 ) ] )
	pump( 0.15 )
	subprocess.call( [ "xdotool", "mousemove", str( point.x() ), str( point.y() ) ] )
	pump()

def clickHere() :

	subprocess.call( [ "xdotool", "click", "1" ] )
	pump( 0.5 )

##########################################################################

definition = IECore.MenuDefinition()
for group in ( "Alpha", "Beta", "Gamma" ) :
	for sub in ( "One", "Two" ) :
		for i in range( 9 ) :
			definition.append(
				"/%s/%s/Node%02d" % ( group, sub, i ),
				{ "command" : lambda : None, "searchText" : "%s%s%d" % ( group, sub, i ) }
			)
entries = NE._entriesFromDefinition( definition )

host = QtWidgets.QWidget()
host.resize( 500, 400 )
host.move( 200, 200 )
host.show()
pump()

accepted = []
panel = NE._NodeCreatorPopup( host )
panel.setEntries( entries )
# 先把鼠标挪开，不然上一次跑完留在原地的光标正好压在面板上，"刚弹出来什么都不亮"那条会假红
subprocess.call( [ "xdotool", "mousemove", "1500", "900" ] )
panel.popupAt( QtCore.QPoint( 300, 300 ), lambda item : accepted.append( item ) )
pump( 0.5 )

column = lambda i : panel._NodeCreatorPopup__columnWidget( i )

def rowPoint( index, row ) :

	viewport = column( index ).viewport()
	return viewport.mapToGlobal(
		QtCore.QPoint( 40, row * NE._NodeCreatorPopup.ROW_HEIGHT + NE._NodeCreatorPopup.ROW_HEIGHT // 2 )
	)

## 每一列上"亮着"的行有哪些（直接数像素）—— 底色是灰的（r=g=b），高亮偏蓝。
def highlightedRows( index ) :

	widget = column( index )
	image = widget.grab().toImage()
	rows = []
	for row in range( widget.count() ) :
		y = row * NE._NodeCreatorPopup.ROW_HEIGHT + NE._NodeCreatorPopup.ROW_HEIGHT // 2
		if y >= image.height() :
			break
		colour = QtGui.QColor( image.pixel( 8, y ) )
		if colour.blue() > colour.red() + 8 :
			rows.append( row )
	return rows

## 每一列都只能有一行亮着，而且必须就是当前行 —— 多出来的就是"残留"。
def checkNoResidue( tag ) :

	for index in range( panel.columnCount() ) :
		widget = column( index )
		expected = [ widget.currentRow() ] if widget.currentRow() >= 0 else []
		check( "%s：第 %d 列没有残留" % ( tag, index ),
			highlightedRows( index ) == expected,
			"亮着的行 %s，当前行 %d" % ( highlightedRows( index ), widget.currentRow() ) )

check( "面板弹出来了", panel.isVisible() )
check( "根层三个大类", panel.rowCount() == 3, str( panel.rowCount() ) )

rootWindowGeometry = QtCore.QRect( panel.geometry() )

check( "刚弹出来什么都不亮（鼠标还没进来）", highlightedRows( 0 ) == [],
	"亮着的行 %s，当前行 %d" % ( highlightedRows( 0 ), column( 0 ).currentRow() ) )

# --- 真鼠标：停在第一列第二行 ---
mouseTo( rowPoint( 0, 1 ) )
check( "真鼠标划过第一列，高亮跟着走", column( 0 ).currentRow() == 1, str( column( 0 ).currentRow() ) )
checkNoResidue( "停在第一列第 1 行" )
check( "而且开出了第二列", panel.columnCount() == 2, str( panel.columnCount() ) )
check( "第二列是 Beta", panel.columnPath( 1 ) == [ "Beta" ], str( panel.columnPath( 1 ) ) )
check( "根窗口没被带着动", panel.geometry() == rootWindowGeometry,
	"%s -> %s" % ( rootWindowGeometry, panel.geometry() ) )

# 划到别的行：刚才那行不许留下印子（老毛病：Qt 的 hover 状态在非最上层的列上清不掉）
mouseTo( rowPoint( 0, 2 ) )
check( "划到第 2 行", column( 0 ).currentRow() == 2, str( column( 0 ).currentRow() ) )
checkNoResidue( "划到第一列第 2 行" )
mouseTo( rowPoint( 0, 1 ) )

# --- 真鼠标：挪到第二列（这时候最上面那个 popup 是第二列窗口）---
secondWindowGeometry = QtCore.QRect( panel.columnWindow( 1 ).geometry() )
mouseTo( rowPoint( 1, 1 ) )
check( "真鼠标划过第二列，那一列的高亮跟着走", column( 1 ).currentRow() == 1, str( column( 1 ).currentRow() ) )
check( "并开出第三列", panel.columnCount() == 3, str( panel.columnCount() ) )
check( "第三列是 Beta / Two", panel.columnPath( 2 ) == [ "Beta", "Two" ], str( panel.columnPath( 2 ) ) )
check( "第二列窗口没被第三列带着动", panel.columnWindow( 1 ).geometry() == secondWindowGeometry,
	"%s -> %s" % ( secondWindowGeometry, panel.columnWindow( 1 ).geometry() ) )
checkNoResidue( "进到第二列" )
check( "每列高度按自己的条目数（3 行 vs 9 行）",
	panel.columnWindow( 2 ).height() - panel.columnWindow( 1 ).height()
		== 7 * NE._NodeCreatorPopup.ROW_HEIGHT,
	"%d vs %d" % ( panel.columnWindow( 1 ).height(), panel.columnWindow( 2 ).height() ) )

# --- 真鼠标：退回第一列（事件只发给最上面那个 popup，全靠面板自己派发）---
mouseTo( rowPoint( 0, 2 ) )
check( "真鼠标退回第一列，高亮跟过去了", column( 0 ).currentRow() == 2, str( column( 0 ).currentRow() ) )
check( "右边跟着换成新大类", panel.columnPath( 1 ) == [ "Gamma" ], str( panel.columnPath( 1 ) ) )
check( "退回来之后只剩两列", panel.columnCount() == 2, str( panel.columnCount() ) )

# --- 真鼠标：进第二列、再进第三列，点一个叶子 ---
mouseTo( rowPoint( 1, 0 ) )
mouseTo( rowPoint( 2, 4 ) )
check( "第三列高亮在第 5 行", column( 2 ).currentRow() == 4, str( column( 2 ).currentRow() ) )
checkNoResidue( "进到第三列" )
mouseTo( rowPoint( 2, 7 ) )
checkNoResidue( "在第三列里再划一行" )
mouseTo( rowPoint( 2, 4 ) )
clickHere()
check( "真点击子列的条目 = 选中它", len( accepted ) == 1, str( len( accepted ) ) )
check( "点完面板关掉了", not panel.isVisible() )
check( "子列窗口也一起收了", panel.columnCount() == 1, str( panel.columnCount() ) )

# --- 真鼠标：点在所有列外面 = 关掉 ---
del accepted[:]
panel.popupAt( QtCore.QPoint( 300, 300 ), lambda item : accepted.append( item ) )
pump( 0.5 )
mouseTo( rowPoint( 0, 1 ) )
check( "又开出了第二列", panel.columnCount() == 2, str( panel.columnCount() ) )
mouseTo( QtCore.QPoint( 1500, 900 ) )
clickHere()
check( "点在外面就关掉", not panel.isVisible() )
check( "什么都没选中", not accepted, str( accepted ) )

##########################################################################

panel.hide()
host.hide()
pump( 0.2 )

##########################################################################
# 第二部分：视口重绘不留残迹
#
# 判据 = **屏幕上真实显示的内容** vs 强制整块重绘之后的内容，逐像素比。
##########################################################################

import Gaffer, GafferUI, GafferScene, imath

smearScript = Gaffer.ScriptNode()
smearPrevious = None
for i in range( 120 ) :
	n = GafferScene.Isolate( "n%03d" % i )
	smearScript.addChild( n )
	if smearPrevious is not None and i % 10 :
		n[ "in" ].setInput( smearPrevious[ "out" ] )
	NE.setNodePosition( n, imath.V2f( ( i % 10 ) * 14.0, -( i // 10 ) * 8.0 ) )
	smearPrevious = n

smearEditor = NE.NetworkEditor( smearScript )
smearWindow = GafferUI.Window( "smear" )
smearWindow.setChild( smearEditor )
smearWindow._qtWidget().resize( 1000, 700 )
smearWindow._qtWidget().move( 2100, 200 )
smearWindow.setVisible( True )
pump( 0.8 )
smearView = smearEditor.graphView()
smearView.frameAll()
pump( 0.4 )

def screenGrab() :

	# 抓**屏幕上真实显示的**那块（不是重新渲染一遍）
	return QtWidgets.QApplication.primaryScreen().grabWindow(
		smearView.viewport().winId()
	).toImage().convertToFormat( QtGui.QImage.Format_RGB32 )

def sampleDiff( a, b ) :

	if a.size() != b.size() :
		return -1
	count = 0
	for y in range( 0, a.height(), 3 ) :
		for x in range( 0, a.width(), 3 ) :
			if a.pixel( x, y ) != b.pixel( x, y ) :
				count += 1
	return count

def checkNoSmear( tag ) :

	pump( 0.3 )
	shown = screenGrab()
	smearView.viewport().repaint()          # 强制整块重画
	pump( 0.3 )
	clean = screenGrab()
	difference = sampleDiff( shown, clean )
	check( "%s：屏幕内容和强制重绘一致（没留残迹）" % tag, 0 <= difference <= 30, "差 %d 个采样点" % difference )

checkNoSmear( "刚取景" )

for i in range( 8 ) :
	smearView.translate( 23, 11 )
	pump( 0.06 )
checkNoSmear( "连续平移 8 步" )

for i in range( 6 ) :
	smearView.scale( 1.1, 1.1 )
	pump( 0.06 )
checkNoSmear( "连续放大 6 步" )

smearCentre = smearView.viewport().rect().center()
smearGlobal = smearView.viewport().mapToGlobal( smearCentre )
subprocess.call( [ "xdotool", "mousemove", str( smearGlobal.x() - 200 ), str( smearGlobal.y() - 150 ) ] )
pump( 0.2 )
subprocess.call( [ "xdotool", "mousedown", "1" ] )
pump( 0.2 )
for step in range( 6 ) :
	subprocess.call( [ "xdotool", "mousemove_relative", "60", "40" ] )
	pump( 0.08 )
subprocess.call( [ "xdotool", "mouseup", "1" ] )
pump( 0.3 )
checkNoSmear( "拖完橡皮筋" )

smearWindow.setVisible( False )
pump( 0.2 )

##########################################################################
# 第三部分：按住 X 划线断连（真键盘，长按到自动重复也不能断）
#
# X11 按住一个键约 0.5 秒后会开始发 press/release 对。以前就是被这个坑到，
# 才把 X 改成开关式；现在改回「按住划、松手切」，靠的是两边都忽略 `isAutoRepeat()`。
# **只有真键盘长按测得出来**：合成事件里没有自动重复。
##########################################################################

cutScript = Gaffer.ScriptNode()
cutA = GafferScene.Sphere( "cutA" )
cutB = GafferScene.Isolate( "cutB" )
cutScript.addChild( cutA ) ; cutScript.addChild( cutB )
cutB[ "in" ].setInput( cutA[ "out" ] )
NE.setNodePosition( cutA, imath.V2f( 0, 0 ) )
NE.setNodePosition( cutB, imath.V2f( 0, -14 ) )

cutEditor = NE.NetworkEditor( cutScript )
cutWindow = GafferUI.Window( "cut" )
cutWindow.setChild( cutEditor )
cutWindow._qtWidget().resize( 900, 650 )
cutWindow._qtWidget().move( 2200, 260 )
cutWindow.setVisible( True )
pump( 0.6 )
cutView = cutEditor.graphView()
cutView.frameAll()
pump( 0.4 )
cutWindow._qtWidget().activateWindow()
cutWindow._qtWidget().raise_()
cutView.setFocus()
pump( 0.5 )

cutEdge = cutEditor._NetworkEditor__edgeItems[ 0 ]
p0, unusedT0, p1, unusedT1 = cutEdge.endPoints()
wireMid = QtCore.QPointF( ( p0.x() + p1.x() ) / 2.0, ( p0.y() + p1.y() ) / 2.0 )
midGlobal = cutView.viewport().mapToGlobal( cutView.mapFromScene( wireMid ) )

subprocess.call( [ "xdotool", "mousemove", str( midGlobal.x() - 120 ), str( midGlobal.y() ) ] )
pump( 0.3 )
subprocess.call( [ "xdotool", "keydown", "x" ] )
pump( 0.3 )
check( "按下 X 进入划线模式", cutView.isCutting() )

# **按住左键**慢慢划过去，总共 1.5 秒以上 —— 保证 X11 的键盘自动重复真的发生
# （手感是「按住 X → 按住左键划 → 松手就切」，所以这里必须真的按下左键；
# 少了这一下 `__cutPoints` 一个都不会攒）
subprocess.call( [ "xdotool", "mousedown", "1" ] )
pump( 0.25 )
for step in range( 10 ) :
	subprocess.call( [ "xdotool", "mousemove_relative", "24", "0" ] )
	pump( 0.16 )
check( "长按到自动重复也没断（线还在划）", cutView.isCutting() )
check( "而且点在攒", len( cutView._GraphView__cutPoints ) >= 5,
	str( len( cutView._GraphView__cutPoints ) ) )

subprocess.call( [ "xdotool", "mouseup", "1" ] )
pump( 0.5 )
check( "松开左键这一刀就切下去了，模式还在（X 没松）", cutView.isCutting() )

subprocess.call( [ "xdotool", "keyup", "x" ] )
pump( 0.5 )
check( "松开 X 退出划线模式", not cutView.isCutting() )
check( "划过的那条线真的断了", cutB[ "in" ].getInput() is None, str( cutB[ "in" ].getInput() ) )
check( "可以撤销", cutScript.undoAvailable() )
if cutScript.undoAvailable() :
	cutScript.undo()
	pump( 0.3 )
	check( "撤销之后线回来了", cutB[ "in" ].getInput() is not None )

cutWindow.setVisible( False )
pump( 0.2 )

##########################################################################
# 真鼠标：NameSwitch 的 `+` 和第二个圆点（用户报了两轮"接不上"）
#
# 前面几轮全是**合成事件**测的，都通；用户实机还是接不上 —— 所以这条必须用
# xdotool 真的按住拖过去。
##########################################################################

import Gaffer, GafferScene, GafferUI

nsScript = Gaffer.ScriptNode()
nsRoot = Gaffer.ApplicationRoot( "nameSwitchInput" )
nsRoot[ "scripts" ].addChild( nsScript )
nsSphere = GafferScene.Sphere( "nsSphere" ) ; nsScript.addChild( nsSphere )
nsSwitch = Gaffer.NameSwitch( "nsSwitch" ) ; nsScript.addChild( nsSwitch )
import imath
NE.setNodePosition( nsSphere, imath.V2f( -24, 26 ) )
NE.setNodePosition( nsSwitch, imath.V2f( 0, 0 ) )

nsEditor = NE.NetworkEditor( nsScript )
nsWindow = GafferUI.Window( "nameSwitchInput" )
nsWindow.setChild( nsEditor )
nsWindow._qtWidget().resize( 1100, 750 )
nsWindow._qtWidget().move( 140, 140 )
nsWindow.setVisible( True )
pump( 1.0 )
nsView = nsEditor.graphView()
nsView.frameAll()
pump( 0.5 )

def nsItem( name ) :

	return nsEditor._NetworkEditor__nodeItems[ name ]

def nsGlobal( item, localPoint ) :

	return nsView.viewport().mapToGlobal(
		nsView.mapFromScene( item.mapToScene( localPoint ) )
	)

def dragBetween( fromPoint, toPoint ) :

	subprocess.call( [ "xdotool", "mousemove", str( fromPoint.x() ), str( fromPoint.y() ) ] )
	pump( 0.25 )
	subprocess.call( [ "xdotool", "mousedown", "1" ] )
	pump( 0.25 )
	for t in ( 0.35, 0.7, 1.0 ) :
		subprocess.call( [ "xdotool", "mousemove",
			str( int( fromPoint.x() + ( toPoint.x() - fromPoint.x() ) * t ) ),
			str( int( fromPoint.y() + ( toPoint.y() - fromPoint.y() ) * t ) ) ] )
		pump( 0.2 )
	subprocess.call( [ "xdotool", "mouseup", "1" ] )
	pump( 0.6 )

# --- ① 真鼠标把线拖到还没 setup 的 NameSwitch 的 `+` 上 ---
switchItem = nsItem( "nsSwitch" )
sphereItem = nsItem( "nsSphere" )
check( "还没 setup 的 NameSwitch 有 `+`", bool( switchItem.adderSections() ),
	str( switchItem.adderSections() ) )
outPoint = nsGlobal( sphereItem, sphereItem.nodulePosition( nsSphere[ "out" ] ) )
adderPoint = nsGlobal( switchItem, switchItem.adderSections()[ "top" ] )
dragBetween( outPoint, adderPoint )
check( "真鼠标拖到 `+`：setup 出来了", nsSwitch.getChild( "in" ) is not None )
check( "而且第一路接上了",
	nsSwitch.getChild( "in" ) is not None and
	nsSwitch[ "in" ][0][ "value" ].getInput() is not None,
	str( nsSwitch[ "in" ][0][ "value" ].getInput() if nsSwitch.getChild( "in" ) else None ) )

# --- ② 真鼠标把**同一个节点**再拖到第二个圆点上（用户说这一步接不上）---
if nsSwitch.getChild( "in" ) is not None :

	pump( 0.4 )
	switchItem = nsItem( "nsSwitch" )
	sphereItem = nsItem( "nsSphere" )
	topNodules = switchItem._nodules.get( "top", [] )
	check( "顶边有两个圆点（in0 / in1）", len( topNodules ) >= 2,
		str( [ p.relativeName( nsSwitch ) for p in topNodules ] ) )

	if len( topNodules ) >= 2 :
		secondPlug = topNodules[1]
		secondPoint = nsGlobal( switchItem, switchItem.nodulePosition( secondPlug ) )
		outPoint = nsGlobal( sphereItem, sphereItem.nodulePosition( nsSphere[ "out" ] ) )
		dragBetween( outPoint, secondPoint )
		connected = nsSwitch[ "in" ][1][ "value" ].getInput()
		check( "真鼠标拖到**第二个圆点**：接上了（用户报的就是这一步）",
			connected is not None and connected.node().isSame( nsSphere ),
			"in1 = %s，in 共 %d 路" % ( connected, len( nsSwitch[ "in" ].children() ) ) )

		# ③ 再往 `+` 上拖一次：全满了就该多一路
		full = len( nsSwitch[ "in" ].children() )
		switchItem = nsItem( "nsSwitch" )
		sphereItem = nsItem( "nsSphere" )
		if switchItem.adderSections() :
			adderPoint = nsGlobal( switchItem, list( switchItem.adderSections().values() )[0] )
			outPoint = nsGlobal( sphereItem, sphereItem.nodulePosition( nsSphere[ "out" ] ) )
			dragBetween( outPoint, adderPoint )
			check( "两路都满了之后再丢 `+`：多出一路并接上",
				len( nsSwitch[ "in" ].children() ) == full + 1 and
				nsSwitch[ "in" ][ full ][ "value" ].getInput() is not None,
				"%d -> %d" % ( full, len( nsSwitch[ "in" ].children() ) ) )

##########################################################################
# Alt + 右键拖 = 缩放，以及 B 键找书签（都得在**真键盘 / 真鼠标**下验）
#
# ① Alt + 右键：窗口管理器常把 Alt + 右键抢去做「改窗口大小」，合成事件测不出来
#    有没有被抢；而且 X11 上右键一按下 Qt 就发 ContextMenuEvent —— 挡不住的话
#    手势会变成「点一下弹菜单」。
# ② B 键：书签数据源以前用 `MetadataAlgo.bookmarks( script )`，只扫直接子节点，
#    装在 Box 里的书签一条都列不出来（而且直接 return，按 B 什么都不发生）。
##########################################################################

nsView.frameAll()
pump( 0.4 )

nsViewport = nsView.viewport()
nsCentre = nsViewport.mapToGlobal(
	QtCore.QPoint( nsViewport.width() // 2, nsViewport.height() // 2 )
)

def altDrag( fromPoint, dx, dy ) :

	subprocess.call( [ "xdotool", "mousemove", str( fromPoint.x() ), str( fromPoint.y() ) ] )
	pump( 0.25 )
	subprocess.call( [ "xdotool", "keydown", "alt" ] )
	pump( 0.15 )
	subprocess.call( [ "xdotool", "mousedown", "3" ] )
	pump( 0.25 )
	mode = nsView._GraphView__mode
	for step in range( 1, 6 ) :
		subprocess.call( [ "xdotool", "mousemove",
			str( int( fromPoint.x() + dx * step / 5.0 ) ),
			str( int( fromPoint.y() + dy * step / 5.0 ) ) ] )
		pump( 0.12 )
	zoom = nsView.zoom()
	subprocess.call( [ "xdotool", "mouseup", "3" ] )
	pump( 0.2 )
	subprocess.call( [ "xdotool", "keyup", "alt" ] )
	pump( 0.3 )
	return mode, zoom

altZoom0 = nsView.zoom()
altMode, altZoomIn = altDrag( nsCentre, 150, 0 )
check( "Alt + 右键按下真的进了缩放模式（没被窗口管理器抢走）",
	altMode == NE._MODE_ZOOM, str( altMode ) )
check( "Alt + 右键往右拖 = 放大", altZoomIn > altZoom0 + 1e-4,
	"%.4f -> %.4f" % ( altZoom0, altZoomIn ) )
check( "松手退出缩放模式", nsView._GraphView__mode == NE._MODE_NONE, str( nsView._GraphView__mode ) )
altPopup = nsEditor._NetworkEditor__creatorPopup
check( "Alt + 右键不会顺手把右键菜单弹出来",
	altPopup is None or not altPopup.isVisible() )

altZoom1 = nsView.zoom()
unusedMode, altZoomOut = altDrag( nsCentre, -150, 0 )
check( "Alt + 右键往左拖 = 缩小", altZoomOut < altZoom1 - 1e-4,
	"%.4f -> %.4f" % ( altZoom1, altZoomOut ) )

# --- B 键找书签 ---

nsBox = Gaffer.Box( "nsRigBox" )
nsScript.addChild( nsBox )
NE.setNodePosition( nsBox, imath.V2f( 30, 0 ) )
nsInner = GafferScene.Sphere( "nsInnerSphere" )
nsBox.addChild( nsInner )
NE.setNodePosition( nsInner, imath.V2f( 0, 0 ) )
Gaffer.MetadataAlgo.setBookmarked( nsInner, True )
Gaffer.MetadataAlgo.setBookmarked( nsSphere, True )
pump( 0.4 )

subprocess.call( [ "xdotool", "mousemove", str( nsCentre.x() ), str( nsCentre.y() ) ] )
pump( 0.2 )
nsView.setFocus( QtCore.Qt.OtherFocusReason )
pump( 0.2 )
subprocess.call( [ "xdotool", "key", "b" ] )
pump( 0.8 )

bookmarkPopup = nsEditor._NetworkEditor__creatorPopup
bookmarkTitle = bookmarkPopup and bookmarkPopup._NodeCreatorPopup__baseTitle
bookmarkNames = sorted(
	e[0] for e in ( bookmarkPopup._NodeCreatorPopup__entries if bookmarkPopup else [] )
)
check( "真键盘 B 弹出书签面板",
	bool( bookmarkPopup and bookmarkPopup.isVisible() ) and bookmarkTitle == "Find Bookmark",
	"%s / %s" % ( bookmarkTitle, bookmarkNames ) )
check( "**Box 里的书签也列出来了**（这就是「功能丢了」那个 bug）",
	bookmarkNames == [ "nsInnerSphere", "nsSphere" ], str( bookmarkNames ) )
if bookmarkPopup is not None :
	bookmarkPopup.hide()
	pump( 0.2 )

nsWindow.setVisible( False )
pump( 0.2 )

##########################################################################
# 真滚轮：面板上任何地方都能滚第一列（用户反馈「只在某一区域才滚得动」）
##########################################################################
#
# 这条**只有真滚轮测得出来**：无头直接调 `_routeWheel` 一定是绿的，而真机上滚轮是
# 发给光标底下那个控件的 —— 压在搜索框 / 边距上时，事件根本到不了列表。

wheelDefinition = IECore.MenuDefinition()
# 40 条（<= PANEL_FLAT_LIMIT）且只有一个顶层分类 -> 根层直接平铺，一列 40 行出滚动条
for i in range( 40 ) :
	wheelDefinition.append(
		"/Flat/Node%02d" % i, { "command" : lambda : None, "searchText" : "Node%02d" % i }
	)

wheelPanel = NE._NodeCreatorPopup( host )
wheelPanel.setEntries( NE._entriesFromDefinition( wheelDefinition ) )
subprocess.call( [ "xdotool", "mousemove", "1500", "900" ] )
wheelPanel.popupAt( QtCore.QPoint( 300, 300 ), lambda item : None )
pump( 0.5 )

wheelColumn = wheelPanel._NodeCreatorPopup__columnWidget( 0 )
wheelBar = wheelColumn.verticalScrollBar()
check( "滚轮用例：条目多到出滚动条", wheelBar.maximum() > wheelBar.minimum(),
	"%d..%d" % ( wheelBar.minimum(), wheelBar.maximum() ) )

def wheelHere( button ) :

	subprocess.call( [ "xdotool", "click", str( button ) ] )
	pump( 0.3 )

searchWidget = wheelPanel._NodeCreatorPopup__search
searchCentre = searchWidget.mapToGlobal( searchWidget.rect().center() )

wheelBar.setValue( wheelBar.minimum() )
pump( 0.2 )
subprocess.call( [ "xdotool", "mousemove", str( searchCentre.x() ), str( searchCentre.y() ) ] )
pump( 0.2 )
wheelHere( 5 )      # 5 = 向下滚
check( "**真滚轮压在搜索框上，第一列照样滚**", wheelBar.value() > wheelBar.minimum(),
	"%d" % wheelBar.value() )

downTo = wheelBar.value()
wheelHere( 4 )      # 4 = 向上滚
check( "真滚轮反向滚回去", wheelBar.value() < downTo, "%d -> %d" % ( downTo, wheelBar.value() ) )

# 面板最上面那点边距（既不是列表也不是搜索框）
marginPoint = wheelPanel.geometry().topLeft() + QtCore.QPoint( 3, 3 )
wheelBar.setValue( wheelBar.minimum() )
pump( 0.2 )
subprocess.call( [ "xdotool", "mousemove", str( marginPoint.x() ), str( marginPoint.y() ) ] )
pump( 0.2 )
wheelHere( 5 )
check( "真滚轮压在面板边距上也滚得动", wheelBar.value() > wheelBar.minimum(), "%d" % wheelBar.value() )

# 列表自己身上照旧能滚（别为了兜底把原来那条路弄坏了）
listPoint = wheelColumn.viewport().mapToGlobal( QtCore.QPoint( 40, 40 ) )
wheelBar.setValue( wheelBar.minimum() )
pump( 0.2 )
subprocess.call( [ "xdotool", "mousemove", str( listPoint.x() ), str( listPoint.y() ) ] )
pump( 0.2 )
wheelHere( 5 )
check( "压在列表上当然也能滚", wheelBar.value() > wheelBar.minimum(), "%d" % wheelBar.value() )

wheelPanel.hide()
pump( 0.2 )
subprocess.call( [ "xdotool", "mousemove", "1500", "900" ] )
pump( 0.2 )

##########################################################################
# 真鼠标：Backdrop 拖得动（用户实机报「可以创建但没法移动」）
#
# 合成事件测不出这条 —— item 少个 `ItemIsMovable` 的时候，Qt 一样会 accept 按下、
# 一样进 `_MODE_MOVE`，只是**不挪 item**。所以这里 xdotool 真的按住拖。
##########################################################################

bdScript = Gaffer.ScriptNode()
bdRoot = Gaffer.ApplicationRoot( "backdropInput" )
bdRoot[ "scripts" ].addChild( bdScript )

bdSphere = GafferScene.Sphere( "bdSphere" ) ; bdScript.addChild( bdSphere )
NE.setNodePosition( bdSphere, imath.V2f( 0, 0 ) )

bdNode = Gaffer.Backdrop( "bdBackdrop" ) ; bdScript.addChild( bdNode )
NE.setNodePosition( bdNode, imath.V2f( 0, 0 ) )
bdNode.addChild( Gaffer.Box2fPlug(
	"__uiBound", Gaffer.Plug.Direction.In,
	imath.Box2f( imath.V2f( -16, -10 ), imath.V2f( 16, 10 ) ),
	flags = Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
) )

bdEditor = NE.NetworkEditor( bdScript )
bdWindow = GafferUI.Window( "backdropInput" )
bdWindow.setChild( bdEditor )
bdWindow._qtWidget().resize( 1000, 700 )
bdWindow._qtWidget().move( 160, 160 )
bdWindow.setVisible( True )
pump( 0.6 )
bdView = bdEditor.graphView()
bdView.frameAll()
pump( 0.4 )
bdWindow._qtWidget().activateWindow()
bdWindow._qtWidget().raise_()
bdView.setFocus()
pump( 0.5 )

bdItem = bdEditor._NetworkEditor__backdropItems[ "bdBackdrop" ]

def bdGlobal( localPoint ) :

	return bdView.viewport().mapToGlobal(
		bdView.mapFromScene( bdItem.mapToScene( localPoint ) )
	)

# **抓标题条**搬动整个 Backdrop（框身是洞，照原生 —— 那是留给「在 Backdrop 上
# 框选它框住的节点」的）
bdStart = bdGlobal( bdItem.titleBarRect().center() )
bdTarget = QtCore.QPoint( bdStart.x() + 90, bdStart.y() - 60 )

_bd0 = NE.nodePosition( bdNode ) ; _sp0 = NE.nodePosition( bdSphere )
bdBefore = imath.V2f( _bd0.x, _bd0.y )
sphereBefore = imath.V2f( _sp0.x, _sp0.y )

dragBetween( bdStart, bdTarget )

bdAfter = NE.nodePosition( bdNode )
sphereAfter = NE.nodePosition( bdSphere )
check( "真鼠标能把 Backdrop 拖走",
	( bdAfter - bdBefore ).length() > 1.0, "%s -> %s" % ( bdBefore, bdAfter ) )
check( "拖的方向对（往右上）",
	bdAfter.x > bdBefore.x + 0.5 and bdAfter.y > bdBefore.y + 0.5,
	"%s -> %s" % ( bdBefore, bdAfter ) )
check( "框住的节点跟着一起走（原生：点 Backdrop 连框内节点一起选）",
	abs( ( sphereAfter.x - sphereBefore.x ) - ( bdAfter.x - bdBefore.x ) ) < 0.05 and
	abs( ( sphereAfter.y - sphereBefore.y ) - ( bdAfter.y - bdBefore.y ) ) < 0.05,
	"%s -> %s" % ( sphereBefore, sphereAfter ) )
check( "item 停在框中心上（没和写回的位置错开）",
	abs( bdItem.pos().x() - NE.backdropBound( bdNode )[0].x * NE.PX_PER_UNIT ) < 0.5 and
	abs( bdItem.pos().y() + NE.backdropBound( bdNode )[0].y * NE.PX_PER_UNIT ) < 0.5,
	"%s vs %s" % ( bdItem.pos(), NE.backdropBound( bdNode )[0] ) )
check( "一次拖动一步撤销", bdScript.undoAvailable() )
if bdScript.undoAvailable() :
	bdScript.undo()
	pump( 0.3 )
	check( "撤销回原位",
		( NE.nodePosition( bdNode ) - bdBefore ).length() < 1e-3 and
		( NE.nodePosition( bdSphere ) - sphereBefore ).length() < 1e-3,
		"%s %s" % ( NE.nodePosition( bdNode ), NE.nodePosition( bdSphere ) ) )

# --- 真鼠标拉右边缘改大小 ---
bdBoundBefore = NE.backdropRelativeBound( bdNode )
bdRect = bdItem.boundingRect()
edgeStart = bdGlobal( QtCore.QPointF( bdRect.right() - 2, 0 ) )
dragBetween( edgeStart, QtCore.QPoint( edgeStart.x() + 120, edgeStart.y() ) )
bdBoundAfter = NE.backdropRelativeBound( bdNode )
check( "真鼠标拉右边缘：框变宽了",
	bdBoundAfter.max().x - bdBoundBefore.max().x > 1.0,
	"%s -> %s" % ( bdBoundBefore, bdBoundAfter ) )
check( "左边界一动不动（只拉了右边）",
	abs( bdBoundAfter.min().x - bdBoundBefore.min().x ) < 1e-3,
	"%s -> %s" % ( bdBoundBefore, bdBoundAfter ) )
check( "上下也没动",
	abs( bdBoundAfter.min().y - bdBoundBefore.min().y ) < 1e-3 and
	abs( bdBoundAfter.max().y - bdBoundBefore.max().y ) < 1e-3,
	"%s -> %s" % ( bdBoundBefore, bdBoundAfter ) )
check( "一次拉框一步撤销", bdScript.undoAvailable() )
if bdScript.undoAvailable() :
	bdScript.undo()
	pump( 0.3 )
	check( "撤销回原来的框",
		abs( NE.backdropRelativeBound( bdNode ).max().x - bdBoundBefore.max().x ) < 1e-3,
		str( NE.backdropRelativeBound( bdNode ) ) )

# --- 框身是洞：在 Backdrop 上照样能框选它框住的节点（原生留这个洞就是为了这个）---
bdScript.selection().clear()
pump( 0.2 )
bdItem = bdEditor._NetworkEditor__backdropItems[ "bdBackdrop" ]
sphereItem = bdEditor._NetworkEditor__nodeItems[ "bdSphere" ]
sphereRect = sphereItem.mapToScene( sphereItem.cardRect() ).boundingRect()
bandFrom = bdView.viewport().mapToGlobal(
	bdView.mapFromScene( QtCore.QPointF( sphereRect.left() - 18, sphereRect.top() - 18 ) )
)
bandTo = bdView.viewport().mapToGlobal(
	bdView.mapFromScene( QtCore.QPointF( sphereRect.right() + 18, sphereRect.bottom() + 18 ) )
)
dragBetween( bandFrom, bandTo )
_banded = sorted( n.getName() for n in bdScript.selection() )
check( "在 Backdrop 身上框选：选到里面的节点（不是把 Backdrop 拖走）",
	_banded == [ "bdSphere" ], str( _banded ) )
check( "Backdrop 自己没被拖走",
	abs( NE.nodePosition( bdNode ).x - bdBefore.x ) < 1e-3 and
	abs( NE.nodePosition( bdNode ).y - bdBefore.y ) < 1e-3,
	str( NE.nodePosition( bdNode ) ) )

# --- 拉框不许留残迹（用户实机截图：缓慢缩短时留下一排竖线）---
#
# 手法照用户描述：**快速拉到接近窗口边缘**（不无限拉、不进自动滚动带），
# 然后**缓慢缩短**，每一步都比「屏幕上真实显示的内容」和「强制重绘一遍」。
bdScript.selection().clear()
pump( 0.2 )
bdItem = bdEditor._NetworkEditor__backdropItems[ "bdBackdrop" ]

def bdScreenGrab() :

	return QtWidgets.QApplication.primaryScreen().grabWindow(
		bdView.viewport().winId()
	).toImage().convertToFormat( QtGui.QImage.Format_RGB32 )

def bdSmear() :

	pump( 0.25 )
	shown = bdScreenGrab()
	bdView.viewport().repaint()
	pump( 0.25 )
	clean = bdScreenGrab()
	if shown.size() != clean.size() :
		return -1
	n = 0
	for y in range( 0, shown.height(), 3 ) :
		for x in range( 0, shown.width(), 3 ) :
			if shown.pixel( x, y ) != clean.pixel( x, y ) :
				n += 1
	return n

_bdRect = bdItem.boundingRect()
_edgeLocal = bdView.mapFromScene( bdItem.mapToScene( QtCore.QPointF( _bdRect.right() - 2, 0 ) ) )
_edge = bdView.viewport().mapToGlobal( _edgeLocal )
_targetX = bdView.viewport().mapToGlobal(
	QtCore.QPoint( bdView.viewport().width() - 140, _edgeLocal.y() )
).x()

# 前面几条用例刚在这个窗口上真拖过（橡皮筋 / 移动），先泵一会儿让它安顿下来
pump( 0.8 )
_idleSmear = bdSmear()
check( "拉框之前屏幕是干净的", 0 <= _idleSmear <= 60, "差 %d 个采样点" % _idleSmear )

subprocess.call( [ "xdotool", "mousemove", str( _edge.x() ), str( _edge.y() ) ] )
pump( 0.3 )
subprocess.call( [ "xdotool", "mousedown", "1" ] )
pump( 0.2 )

# ① 快速拉长
for _i in range( 1, 7 ) :
	_x = int( _edge.x() + ( _targetX - _edge.x() ) * _i / 6.0 )
	subprocess.call( [ "xdotool", "mousemove", str( _x ), str( _edge.y() ) ] )
	pump( 0.03 )
pump( 0.3 )
_grownWidth = bdItem.relativeBound().max().x - bdItem.relativeBound().min().x
check( "快速拉长：真的变宽了", _grownWidth > 24.0, "%.1f" % _grownWidth )
_growSmear = bdSmear()
check( "快速拉长之后屏幕没留残迹", 0 <= _growSmear <= 60, "差 %d 个采样点" % _growSmear )

# ② 缓慢缩短：每步都得更窄、每步都不许留残迹
_worst = 0
_widths = [ _grownWidth ]
_x = _targetX
for _step in range( 8 ) :
	_x -= 14
	subprocess.call( [ "xdotool", "mousemove", str( _x ), str( _edge.y() ) ] )
	pump( 0.12 )
	_widths.append( bdItem.relativeBound().max().x - bdItem.relativeBound().min().x )
	_worst = max( _worst, bdSmear() )

check( "缓慢缩短：每一步都真的更窄（以前会越拖越长）",
	all( _widths[ i + 1 ] < _widths[ i ] + 1e-6 for i in range( len( _widths ) - 1 ) ),
	str( [ round( w, 1 ) for w in _widths ] ) )
check( "缓慢缩短：一步都没留残迹（用户截图里那排竖线）",
	0 <= _worst <= 60, "最差差 %d 个采样点" % _worst )

subprocess.call( [ "xdotool", "mouseup", "1" ] )
pump( 0.4 )
_releaseSmear = bdSmear()
check( "松手之后也干净", 0 <= _releaseSmear <= 60, "差 %d 个采样点" % _releaseSmear )
check( "松手写回的框 = 屏幕上那个",
	abs( NE.backdropRelativeBound( bdNode ).max().x - bdItem.relativeBound().max().x ) < 1e-4,
	"%s vs %s" % ( NE.backdropRelativeBound( bdNode ), bdItem.relativeBound() ) )

bdWindow.setVisible( False )
pump( 0.2 )
subprocess.call( [ "xdotool", "mousemove", "1500", "900" ] )
pump( 0.2 )

report = "\n".join( [ "PASS  " + p for p in _passed ] + [ "FAIL  " + f for f in _failed ] )
report += "\n\n==== panel input + repaint + hold-X e2e: %d/%d passed ====\n" % ( len( _passed ), len( _passed ) + len( _failed ) )
open( "/tmp/panel_input_report.txt", "w" ).write( report )
print( report.splitlines()[-2] )

sys.exit( 0 )
