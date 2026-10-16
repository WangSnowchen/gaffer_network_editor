# -*- coding: utf-8 -*-
#
# Optional rez package definition. Gaffer itself does not need it: pointing
# GAFFER_EXTENSION_PATHS at this directory is enough (see README).

name = "gaffer_network_editor"

version = "0.1.0"

description = (
    "A Qt (QGraphicsView) node graph editor for Gaffer that looks modern "
    "and behaves like the native GraphEditor."
)

authors = ["WangSnowchen"]

requires = [
    "gaffer-1.7+",
]


def commands():
    env.GAFFER_EXTENSION_PATHS.append("{root}")
