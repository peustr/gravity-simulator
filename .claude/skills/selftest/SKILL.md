---
name: selftest
description: Run the physics server self-test (REBOUND) and summarise the results. Use after any change in physics_server/, or when the user asks whether the physics still works.
allowed-tools: Bash(physics_server/.venv/Scripts/python.exe physics_server/server.py --selftest) Bash(physics_server/.venv/bin/python physics_server/server.py --selftest) Read
---

Run the self-test from the repository root:

```
physics_server/.venv/Scripts/python.exe physics_server/server.py --selftest
```

On macOS or Linux, use `physics_server/.venv/bin/python` instead. If the `.venv` folder doesn't exist, tell the user to run the setup in README section 3.3 first. Don't create it yourself.

Then report:

- **PASSED or FAILED** on the first line.
- Any `[FAIL]` lines, with the detail text.
- Anything unusual in the timings, for example a scenario that suddenly takes much longer than the others.

If something failed, read the relevant code in `physics_server/world.py`, explain the cause in plain language, and propose a fix. Ask before editing.
