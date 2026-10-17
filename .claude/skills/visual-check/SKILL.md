---
name: visual-check
description: Render Gravity Simulator to a PNG and inspect it. Use after changing shaders, visuals, effects, UI or anything else in godot/, or when the user asks how something looks.
argument-hint: "[scenario] [extra flags]"
---

Take a screenshot of the game and review it. Arguments: $ARGUMENTS. The first argument is the scenario; the default is `solar`. Anything after it is extra automation flags.

Scenarios: `solar`, `binary`, `black_hole`, `smash`, `formation`, `galaxies`, `empty`.

## Steps

1. Read `GODOT` from `CLAUDE.local.md`. It should be the `..._console.exe` build. If it isn't there, ask the user for the full path to `Godot_v4.x-stable_win64_console.exe` and save it to `CLAUDE.local.md` as `GODOT="C:/path/to/Godot_v4.x-stable_win64_console.exe"`.
2. Run from the repository root. Godot starts the physics server from `physics_server/.venv` by itself and stops it on exit:

   ```
   "$GODOT" --path godot --resolution 1280x720 -- --preset=SCENARIO --wait=6 --screenshot=shots/SCENARIO.png --quit EXTRA_FLAGS
   ```

   A relative `--screenshot` path is resolved from the repository root. The `shots/` folder is git-ignored.
3. Scan the console output for `SCRIPT ERROR`, `Parse Error` and `ERROR:`. Ignore audio-driver warnings.
4. Open the PNG with the Read tool. Describe what you see, compare it with the intent of the change, and point out anything that looks wrong: blown-out glow, missing bodies, UI overlaps.
5. If the scene changes quickly (explosions, tidal disruption), use `--pause_at` to freeze it at a chosen moment, then take the screenshot a little later.

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
