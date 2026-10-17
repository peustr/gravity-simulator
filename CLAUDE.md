# Gravity Simulator

Interactive N-body space sandbox for Windows. Two programs talk over UDP on `127.0.0.1:47810`:

- `physics_server/` — Python 3.10–3.14 + REBOUND 5 (IAS15 integrator) + NumPy. **All physics lives here.**
- `godot/` — Godot 4.6+ project (GDScript, Forward+ renderer). Rendering, input and UI only. Never put physics in GDScript.

The user develops on Windows 11. The physics venv is `physics_server/.venv` (Python 3.13). The user is learning: explain changes in plain language, and keep physics claims honest (see README "What is *not* simulated").

## Commands (run from the repo root)

- Physics self-test — run after **any** change in `physics_server/`:
  `physics_server/.venv/Scripts/python.exe physics_server/server.py --selftest`
  (on macOS/Linux the interpreter is `physics_server/.venv/bin/python`)
- Server with a live log: `physics_server/.venv/Scripts/python.exe physics_server/server.py --verbose`
- Godot executable: `GODOT` in `CLAUDE.local.md` (the `_console.exe` build, so errors reach the terminal). If it's missing, ask the user for the path and save it there.
- Script/parse check without a window: `"$GODOT" --headless --path godot --quit-after 300`
- Visual check (renders a PNG you can look at): use the `/visual-check` skill.
- Don't launch the Godot editor or play the game interactively; the user does that.

## Layout

| Path | What |
|---|---|
| `physics_server/world.py` | `World`: REBOUND sim, body types, collisions, fragmentation, tides, supernovae, scenarios (`load_preset`), orbit forecast (`predict`) |
| `physics_server/server.py` | UDP loop (60 Hz), JSON commands, binary packing, `--selftest` |
| `godot/scripts/main.gd` | Builds the scene in code, parses state packets, smooth motion, input, automation flags (`_run_auto`) |
| `godot/scripts/net_client.gd` | UDP client; auto-starts the server from `.venv` or `server.exe` |
| `godot/scripts/body_view.gd` | Visuals for one body (per type) |
| `godot/scripts/hud.gd` | All UI, built in code with a code-made Theme |
| `godot/scripts/palette.gd` | Shared constants: type ids, colours, names, radius formula |
| `godot/shaders/` | Stars, planets, black-hole lens, accretion disk, starfield, grid; helpers in `noise.gdshaderinc` |
| `README.md` | User-facing install guide, controls, physics notes, protocol |

## Things that must stay in sync

| What | Where |
|---|---|
| Body type ids (ROCKY=0 … PLASMA=6), event codes (EV_MERGE=1 … EV_KILONOVA=9), `DEFAULT_MASS`, `radius_for()` | `world.py` ↔ `godot/scripts/palette.gd` |
| Packet layout: header 10 floats, body 12, event 8; forecast reply header 8 | `server.py` `pack_state`/`pack_prediction` ↔ `main.gd` `_on_state`/`_on_prediction` |
| UDP port 47810 | `server.py` `DEFAULT_PORT` ↔ `net_client.gd` `SERVER_PORT` |
| Scenario names | `world.load_preset()` ↔ `hud.gd` `PRESETS` |
| New body type | also `TYPE_LABELS`, `TYPE_COLORS`, `TOOL_TYPES`, a builder in `body_view.gd`, an icon in `hud.gd`, trail strength in `trails.gd` |
| User-visible change | README: controls table, scenarios, physics notes |

## REBOUND 5 gotchas (learned the hard way)

- Never pass `name=` to `sim.add()`: the C side keeps a pointer to a temporary Python buffer. Add first, then `sim.particles[sim.N-1].name = name`. Always go through `World.add_body` / `remove_body`.
- Never add particles inside the collision callback. `_resolve_collision` merges and records; `_handle_collision` runs after `sim.steps(1)` and may shatter.
- Collision callback return: 1 removes p1, 2 removes p2. REBOUND reports only *approaching* overlaps, so fragments may start overlapping the remnant.
- Light debris (asteroids, small gas clouds) are **test particles**: massive bodies must come first in the particle array, and `sim.N_active` = their count. Anything that adds or promotes a body sets `_partition_dirty`; `_repartition()` swaps particle structs with `ctypes.memmove`. Preserve this invariant.
- IAS15 has one global timestep, so a single close encounter slows everything. `min_dt` is 1e-4. Keep debris counts in check (`SHATTER_MIN_MASS`, fragment caps).
- Python 3.15 has no REBOUND wheels yet; keep the venv on 3.13.

## Godot conventions

- Only use APIs available in Godot 4.6 (tested on 4.6.3 and 4.7.2). GDScript with tabs, typed where practical.
- Scripts are referenced with `preload` constants, not `class_name`. `main.tscn` is only a root node; everything else is created in `main.gd`.
- HDR colour values above 1 drive the bloom. Billboards use `billboard_modelview()` from `noise.gdshaderinc`.
- The black-hole look depends on the accretion disk being **opaque** (alpha scissor), so the lens shader (`hint_screen_texture`) can bend it.
- UI buttons use `focus_mode = FOCUS_NONE`, so Space and other keys reach `_unhandled_input`.

## Before saying a change is done

1. The self-test passes (for physics changes).
2. The headless Godot run prints no `SCRIPT ERROR` or `Parse Error` (for Godot changes).
3. For visual changes, run `/visual-check` and actually look at the PNG.
4. The README is updated if anything user-visible changed.
