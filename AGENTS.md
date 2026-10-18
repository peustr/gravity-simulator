# Gravity Simulator

Interactive N-body space sandbox for Windows. Two programs talk over UDP on `127.0.0.1:47810`:

- `physics_server/` — Python 3.10–3.14 + REBOUND 5 (IAS15 integrator) + NumPy. **All physics lives here.**
- `godot/` — Godot 4.7.2 project (GDScript, Forward+ renderer). Rendering, input and UI only. Never put physics in GDScript.

Codex is the primary developer and maintainer. The user plays and develops on Windows 11; cloud development runs on Linux. The physics venv is `physics_server/.venv` (Python 3.13 on Windows; Python 3.12 for cloud development). The user is learning: explain changes in plain language, and keep physics claims honest (see README "What is *not* simulated").

## Working practices

- Read the relevant code and check `git status` before editing. Preserve user changes and keep patches focused on the requested outcome.
- Use the existing checkout. Cloud tasks are already isolated; create a Git worktree only when explicitly requested.
- Complete authorized setup, fixes and validation without asking again for routine implementation choices. Ask when missing information or credentials actually block progress.
- Keep local paths and credentials out of tracked files. Use the `GODOT` environment variable for a custom engine path; otherwise discover `godot` or `godot4` on PATH.
- Keep simulation claims honest: REBOUND supplies gravity; stellar evolution, collisions and visuals include approximations documented in README.
- Report what changed, what was tested, and any remaining limitation. A headless run does not validate rendered appearance.

## Documentation

- Document only the current repository: setup, commands, architecture, behavior, contracts and relevant limitations.
- Keep documentation concise, factual and useful to a human reader. Avoid narrative prose, change summaries, dated review reports, session notes and historical test results.
- Update or remove outdated information in place. Use Git history and PR descriptions for change history; do not keep changelogs or completed-work reports in repository documentation.
- Keep generated references synchronized with their source. Report validation results in the chat or PR, not in permanent documentation.

## Commands (run from the repo root)

Use `python3` on Linux/macOS or `py -3.13` on Windows to run `tools/dev.py`. The helper finds the repository and its venv independently of the current directory.

| Task | Command (Linux/macOS) |
|---|---|
| Create/refresh the venv and validate physics | `python3 tools/dev.py setup` |
| Install developer tools | `python3 tools/dev.py setup-dev` |
| All quality checks | `python3 tools/dev.py check` |
| Refresh generated runtime reference | `python3 tools/dev.py docs` |
| Physics self-test | `python3 tools/dev.py selftest` |
| Godot protocol contract tests | `python3 tools/dev.py godot-test` |
| Godot headless script/startup check | `python3 tools/dev.py godot-check` |
| Render and inspect a scenario | `python3 tools/dev.py visual-check black_hole` |
| Server with a live log | `physics_server/.venv/bin/python physics_server/server.py --verbose` |

On Windows the standalone server interpreter is `physics_server/.venv/Scripts/python.exe`. Use the standard Godot 4.7.2 build; choose its console executable on Windows. Godot starts the venv server automatically and stops its child on exit. Do not start a duplicate server on UDP port 47810.

Codex skills: `$selftest` in `.agents/skills/selftest/` and `$visual-check` in `.agents/skills/visual-check/`. These contain diagnosis and validation guidance. Do not launch the editor or play interactively unless requested.

Cloud headless checks use writable XDG cache/data directories when needed. Visual checks require a working display and graphics renderer; report unavailable rendering separately from successful physics or script checks. Never treat a stale screenshot as evidence for the current run.

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

## REBOUND 5 invariants

- Never pass `name=` to `sim.add()`: the C side keeps a pointer to a temporary Python buffer. Add first, then `sim.particles[sim.N-1].name = name`. Always go through `World.add_body` / `remove_body`.
- Reacquire particle references by ID after adding particles: array growth can invalidate references to C storage.
- Never add particles inside the collision callback. `_resolve_collision` merges and records; `_handle_collision` runs after `sim.steps(1)` and may shatter.
- Collision callback return: 1 removes p1, 2 removes p2. REBOUND reports only *approaching* overlaps, so fragments may start overlapping the remnant.
- Light debris (asteroids, small gas clouds) are **test particles**: massive bodies must come first in the particle array, and `sim.N_active` = their count. Anything that adds or promotes a body sets `_partition_dirty`; `_repartition()` swaps particle structs with `ctypes.memmove`. Preserve this invariant.
- IAS15 has one global timestep, so a single close encounter slows everything. `min_dt` is 1e-4. Keep debris counts in check (`SHATTER_MIN_MASS`, fragment caps).
- Prefer Python 3.13 on Windows (3.12 for cloud development). Check wheel availability before moving to a newer Python; do not silently introduce a compiler requirement.

## Godot conventions

- Only use APIs available in Godot 4.7.2. GDScript with tabs, typed where practical.
- Scripts are referenced with `preload` constants, not `class_name`. `main.tscn` is only a root node; everything else is created in `main.gd`.
- HDR colour values above 1 drive the bloom. Billboards use `billboard_modelview()` from `noise.gdshaderinc`.
- The black-hole look depends on the accretion disk being **opaque** (alpha scissor), so the lens shader (`hint_screen_texture`) can bend it.
- UI buttons use `focus_mode = FOCUS_NONE`, so Space and other keys reach `_unhandled_input`.

## Before saying a change is done

1. The self-test passes (for physics changes).
2. The headless Godot run prints no `SCRIPT ERROR` or `Parse Error` (for Godot changes).
3. For visual changes, run `$visual-check` and actually look at the PNG.
4. The README is updated if anything user-visible changed.

5. For tooling or instruction changes, exercise the affected commands and check links/paths. Do not add tests that merely restate documentation.
6. Fix failures caused by the change; distinguish existing application defects from environment limitations. Do not weaken checks to make them pass.
