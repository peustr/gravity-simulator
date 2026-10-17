---
name: selftest
description: Run and diagnose the Gravity Simulator REBOUND physics self-test. Use after physics changes or when asked whether simulation behavior still works.
---

# Physics self-test

1. Read `AGENTS.md` and run `python3 tools/dev.py selftest` from the repository root (`py -3.13 tools/dev.py selftest` on Windows).
2. If the venv is missing and setup is within the task, run `python3 tools/dev.py setup` with a supported Python. Reuse the project's venv and requirements; do not modify dependency declarations merely to make setup pass.
3. Preserve the command's exit status and confirm the output ends with `Self-test PASSED`. Report the actual number of `[ok]` and `[FAIL]` checks, failure details, and unusual timings. A zero-check run is not a pass.
4. Investigate failures in `physics_server/server.py` and `world.py`. Distinguish environment problems from simulation defects. Fix issues within the authorized scope and rerun affected checks; do not suppress assertions or weaken tolerances to obtain a pass.
5. Summarize PASSED, FAILED or BLOCKED with concrete evidence. The suite exercises physics and packet serialization; it does not establish UDP connectivity or rendered appearance.
