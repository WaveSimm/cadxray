# cadxray

<!-- mcp-name: io.github.WaveSimm/cadxray -->

**Your AI actually looks inside FreeCAD.** Hand it a drawing, a vendor STEP, an STL — or a sketch that just turned red.

![cadxray demo](https://github.com/WaveSimm/cadxray/releases/download/media-v1/cadxray-demo.gif)

An MCP server that lets any MCP client (Claude Code, Cursor, VS Code Copilot, Codex, Gemini CLI …) **diagnose and edit** a live FreeCAD document. It does not guess — it reads the sketch solver, measures faces, and verifies its own work with numbers.

## Install — two commands

```bash
uvx cadxray install     # copy the bundled addon into FreeCAD's Mod folder
```

Then register the bridge with your AI tool. For Claude Code:

```bash
claude mcp add --scope user cadxray -- uvx cadxray
```

Restart FreeCAD — the server starts automatically on `127.0.0.1:9877`. Other clients (Cursor, Codex, Gemini CLI, Claude Desktop …) use the same launch command `uvx cadxray`; only the registration differs. See the [README](https://github.com/WaveSimm/cadxray#readme) for each one.

Stuck? `uvx cadxray doctor` checks the addon install, the FreeCAD connection and version mismatches.

## What it does

- **Diagnose** — why a sketch is red, named by the same constraint numbers the GUI panel shows. Fix candidates come back as a numbered list with a confidence level; nothing is applied until you pick one, and it rolls back if the state gets worse.
- **Reverse-engineer with proof** — a vendor STEP or an STL becomes a parametric Body, verified numerically: 0.0004 % volume difference on a 44-face clamp jaw, all 1,432 mesh vertices within 0.03 mm on a threaded STL.
- **Build from 2D** — vector PDF drawings, DXF, drawing sheets and photos into parametric models.
- **Inspect** — hole diameters and pitch, interference across 80 parts in 6.5 s, mass, centre of gravity, tipping angle.
- **Draw, print, analyse** — TechDraw pages with dimensions measured off the model, printability checks with automatic fixes, CalculiX FEM with safety factors and colour maps.

36 tools in total. Everything stays on `127.0.0.1` — your model files never leave the machine.

## Commands

```bash
cadxray                 # run the MCP server (your AI tool launches this)
cadxray install         # copy the bundled addon into FreeCAD's Mod folder
cadxray install --dev   # symlink a repository checkout instead (for development)
cadxray doctor          # diagnose the install and the connection
```

## Requirements

FreeCAD **1.0.x / 1.1.x** (verified on 1.1.3) on Windows, macOS or Linux. Python ≥ 3.10. The only dependency is `mcp`; the FreeCAD-side addon uses stdlib + PySide only and is bundled in this package.

## Learn it

A guide with ten hands-on exercises — from drilling four holes in a plate to rebuilding a vendor STEP — with the actual input files and the exact prompts:

**<https://wavesimm.github.io/cadxray/en/>**

Repository and full documentation: <https://github.com/WaveSimm/cadxray>

MIT licensed.
