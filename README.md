# gaffer_network_editor

A node graph editor for [Gaffer](https://github.com/GafferHQ/gaffer), drawn with
Qt (`QGraphicsView`) instead of Gaffer's OpenGL `GraphEditor`.

**Goal: look modern, behave exactly like the native editor.**

[中文说明](README.zh-CN.md)

- Flat cards with node-type icons, plug dots coloured by plug type, curved
  ("rounded", Houdini-style) or straight wires, zoom level-of-detail, Backdrops.
- Node sizes, plug positions and colours are all **queried from Gaffer**
  (`NodeGadget.bound()`, nodule transforms, `nodeGadget:color`, `nodule:color`,
  StandardStyle defaults), so a node is the same size and colour in both editors.
- Editing and shortcuts follow the native `GraphEditor`, `EditMenu` and
  `GraphBookmarksUI` one by one. Native context menus (node / plug / connection)
  are borrowed as-is, including entries added by other extensions.
- Shortcuts that pipeline startup scripts register through
  `GraphEditor.instanceCreatedSignal` keep working, and the menus they pop up
  are drawn by this editor's own panel.
- Takes over `GafferUI.GraphEditor` (copy/paste from the menu bar, bookmarks,
  `Ctrl+F`, *Show Contents...*), while the native editor keeps working.
- Extras: cascading node-creation panel with acronym search
  (`ass` → aiStandardSurface) and favourites / frequently used, snap-to-align
  while dragging, connection snapping, focus highlighting via
  `ContextTracker`, a layered auto-layout (`Ctrl+L`) with fewer crossings than
  the native one, "cut wires" mode (`X`), sectioned material nodes.
- Incremental updates: changing one connection costs ~5 ms regardless of graph
  size (200 / 800 / 2000 nodes).

The UI text is English; tooltips are Chinese.

## Requirements

- Gaffer **1.7** (tested with 1.7.1.0). Gaffer 1.6 is not supported.
- Optional: a separate extension providing a Python module `parameterEditor`
  with `popupParameters( node, anchor = QRect )` enables the `P` key (a
  docked parameter panel). Without it, `P` does nothing.

## Install

The repository is a Gaffer extension: `python/` goes on `PYTHONPATH`,
`startup/gui/` registers the editor.

```bash
export GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:/path/to/gaffer_network_editor"
gaffer
```

Or without the extension mechanism:

```bash
export PYTHONPATH="/path/to/gaffer_network_editor/python:$PYTHONPATH"
export GAFFER_STARTUP_PATHS="/path/to/gaffer_network_editor/startup:$GAFFER_STARTUP_PATHS"
```

A rez `package.py` is included as well.

Then pick **NetworkEditor** from any panel's editor menu.

### Environment variables

| Variable | Effect |
| --- | --- |
| `GAFFER_NETWORK_EDITOR_TAKEOVER=native` | Do not take over `GafferUI.GraphEditor` |
| `GAFFER_NETWORK_EDITOR_ENGINE=0/1` | Force the hidden native GraphEditor off / on (default: only when the takeover is off) |
| `GAFFER_NETWORK_EDITOR_GADGET=0` | Do not use a bare `GraphGadget` for native sizes and placement (diagnostics) |
| `GAFFER_NETWORK_EDITOR_STATE_DIR` | Where favourites / usage counts are stored (default `~/.gaffer_network_editor`) |

## Shortcuts (same as native unless noted)

| Key | Action |
| --- | --- |
| Click / Shift / Ctrl | Select / add / remove |
| Alt+Shift / Alt+Ctrl click | Select with upstream / downstream |
| Drag on empty space | Box select (nodes touched by the box are selected) |
| Drag a node onto a wire | Insert it into the connection |
| Middle drag / Alt+left drag | Pan |
| Wheel / Alt+right drag | Zoom |
| `F` | Frame selection / all |
| `` ` `` / `Ctrl+` `` ` `` | Frame focus / set focus |
| `↓` / `↑` / `[` `]` | Enter node / go up / navigate history |
| `Tab`, right-click empty space | Node creation panel |
| `X` | Cut mode: click a wire or node to delete it, drag to cut several wires |
| `D` | Toggle enabled |
| `P` | Parameter panel (optional, see Requirements) |
| `B` | Find bookmark |
| `1`–`9`, `Ctrl+1`–`9` | Jump to / set numeric bookmark |
| `Delete`, `Ctrl+C/X/V`, `Ctrl+D` | Delete, copy/cut/paste, duplicate with inputs |
| `Ctrl+L` | Auto layout (own layered algorithm) |
| `F2` / `Ctrl+F` | Rename / find node |

## Documentation (Chinese)

| File | Content |
| --- | --- |
| [docs/design-and-comparison.md](docs/design-and-comparison.md) | Design principles, what is borrowed from native Gaffer, comparison with the native GraphEditor, known differences, risks |
| [docs/architecture.md](docs/architecture.md) | Code tour: module layering, every file and its key classes |
| [docs/pitfalls.md](docs/pitfalls.md) | Every problem met during development, with root cause and fix |
| [docs/gaffer-knowledge.md](docs/gaffer-knowledge.md) | Gaffer internals learned along the way: GraphEditor, metadata, ContextTracker, NodeMenu, ViewportGadget, drag & drop, version differences, testing techniques |
| [docs/testing.md](docs/testing.md) | How to run the test suites |
| [skills/](skills/README.md) | Claude Code skills for Gaffer UI work (this editor, parameter panels, HierarchyView columns, colour chooser, node menus, node docs, probing, headless delivery) |

## Tests

```bash
# headless (data layer + UI + editing)
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_network_editor.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_optimizations.py
QT_QPA_PLATFORM=offscreen gaffer env python tests/test_review_v070.py

# real GUI (needs a display and Arnold)
GAFFER_EXTENSION_PATHS="$GAFFER_EXTENSION_PATHS:$PWD" \
    gaffer screengrab -commandFile tests/e2e_network_editor.py -image /tmp/editor.png
```

See [docs/testing.md](docs/testing.md) for the rest.

## License

BSD 3-Clause, see [LICENSE](LICENSE).
