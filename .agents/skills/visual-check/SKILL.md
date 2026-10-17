---
name: visual-check
description: Render a Gravity Simulator scenario and inspect the PNG. Use after changes to shaders, visuals, effects, UI or Godot scene code, or when asked to assess appearance.
---

# Visual check

1. Read `AGENTS.md`. Use the requested scenario, or `solar` by default. Scenarios: `solar`, `binary`, `black_hole`, `smash`, `formation`, `galaxies`, `empty`.
2. Resolve Godot from `GODOT` or PATH. On Windows use the console executable. If missing, inspect available installations before requesting a path. Do not save machine paths in tracked files.
3. Run `python3 tools/dev.py visual-check SCENARIO` from the repository root (`py -3.13` on Windows). Optional automation flags follow the scenario, for example `--pause_at=2 --grid`. The helper chooses a unique PNG in ignored `shots/`, enforces a timeout, and rejects engine errors and missing images.
4. Open the resulting image with the available image-viewing tool. Check body placement, glow, lensing, trails, HUD overlaps and the physics connection indicator. Compare with the requested change. A PNG existing is not enough: actually inspect it.
5. If rendering is unavailable, run `godot-check`, report the limitation, and do not claim visual validation. Do not use headless rendering or `--offline_ok` as evidence of a functioning rendered simulation. Use offline mode only when explicitly checking the offline screen.
6. Diagnose failures and fix issues within the authorized task. Report the scenario, image path, observed result, and any remaining limitation. Never disable assertions or hide engine errors.

The game starts and stops its own backend. Do not launch the interactive editor. If a timeout interrupts the client, inspect and clean up only its own child server; never kill unrelated processes.

## Automation flags

These go after the `--` and are implemented in `godot/scripts/main.gd` → `_run_auto()`.

| Flag | Meaning |
|---|---|
| `--preset=NAME` | Load a scenario once the physics server is connected |
| `--wait=S` | Seconds before the screenshot (default 3) |
| `--screenshot=PATH` | Save a PNG (creates folders as needed) |
| `--quit` | Exit after the screenshot |
| `--cam=DIST,PITCH,YAW` | Camera distance, elevation (radians) and heading |
| `--follow_type=N` | Follow the first body of type N (0 rocky, 1 gas giant, 2 star, 3 neutron star, 4 black hole, 5 asteroid, 6 gas cloud) |
| `--select_type=N` | Select (inspect) the first body of type N |
| `--tool=N` | Pick body tool N and hover at 62% / 50% of the screen (shows the ghost and forecast) |
| `--click` | Click once at the hover point, which places a body |
| `--keys=T,G,H` | Press these keys once |
| `--grid` | Turn the gravity grid on |
| `--pause_at=S` | Pause the physics after S seconds |
| `--nova_at=S` | Make the heaviest star go supernova after S seconds |
| `--debug` | Print the 6 heaviest bodies and the camera position |
| `--welcome` | Allow the welcome card in screenshot mode |
| `--offline_ok` | Screenshot even without the physics server (tests the offline screen) |
