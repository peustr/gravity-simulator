"""Cross-platform development commands; no third-party tooling dependencies."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / "physics_server" / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SCENARIOS = ("solar", "binary", "black_hole", "smash", "formation", "galaxies", "empty")


def run(args: list[str], timeout: int = 120) -> str:
    result = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace",
                            timeout=timeout)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    return result.stdout


def selftest() -> None:
    output = run([str(PYTHON), "physics_server/server.py", "--selftest"], timeout=300)
    if "Self-test PASSED" not in output or "[FAIL]" in output or "[ok]" not in output:
        raise RuntimeError("Physics runner did not report completed, passing checks.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "setup-dev", "selftest", "test", "lint", "docs", "docs-check", "check", "godot-test", "godot-check", "visual-check"))
    parser.add_argument("scenario", nargs="?", choices=SCENARIOS, default="solar")
    args, extra = parser.parse_known_args()
    if extra and args.command != "visual-check":
        parser.error("Extra automation flags are only supported for visual-check.")
    if args.command in ("setup", "setup-dev"):
        if not (3, 10) <= sys.version_info[:2] < (3, 15):
            raise RuntimeError("Use Python 3.10–3.14; prefer 3.13 on Windows or 3.12 in cloud.")
        run([sys.executable, "-m", "venv", str(VENV)])
        run([str(PYTHON), "-m", "pip", "install", "-r", "requirements-dev.txt" if args.command == "setup-dev" else "physics_server/requirements.txt"], 300)
        run([str(PYTHON), "-m", "pip", "check"])
    if not PYTHON.is_file():
        raise RuntimeError("Missing physics venv. Run this helper's setup command first.")
    if args.command in ("setup", "setup-dev", "selftest"):
        selftest()
        return

    checks = {
        "lint": [str(PYTHON), "-m", "ruff", "check", "."],
        "test": [str(PYTHON), "-m", "pytest", "--cov=physics_server", "--cov-report=term-missing", "--cov-report=xml"],
        "docs": [str(PYTHON), "tools/docs.py"],
        "docs-check": [str(PYTHON), "tools/docs.py", "--check"],
    }
    if args.command in checks:
        run(checks[args.command], timeout=300)
        return
    if args.command == "check":
        for name in ("lint", "test", "docs-check", "godot-check"):
            run([sys.executable, str(Path(__file__).resolve()), name], timeout=300)
        return

    godot = os.environ.get("GODOT") or shutil.which("godot") or shutil.which("godot4")
    if not godot:
        raise RuntimeError("Godot 4.7.2 not found. Set GODOT to its executable or add it to PATH.")
    if sys.platform.startswith("linux"):
        for key, suffix in (("XDG_CACHE_HOME", ".cache"), ("XDG_DATA_HOME", ".local/share")):
            os.environ.setdefault(key, str(VENV / suffix))
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
    command = [godot, "--path", str(ROOT / "godot")]
    screenshot = None
    if args.command in ("godot-test", "godot-check"):
        contract_output = run(command + ["--headless", "--script", "res://tests/contracts.gd"])
        if re.search(r"SCRIPT ERROR|Parse Error|(?:^|\n)\s*ERROR:", contract_output):
            raise RuntimeError("Godot contract tests reported errors.")
        contract = next((line.removeprefix("CONTRACT_JSON:") for line in contract_output.splitlines()
                         if line.startswith("CONTRACT_JSON:")), None)
        if contract is None:
            raise RuntimeError("Godot contract tests did not complete.")
        # Run the comparison using the venv, which owns NumPy and REBOUND.
        run([str(PYTHON), "-c",
             "import sys; sys.path[:0] = ['physics_server', 'tools']; "
             "import json, contracts; contracts.check(json.loads(sys.argv[1]))", json.dumps(json.loads(contract))])
        if args.command == "godot-test":
            return
        command += ["--headless", "--", "--preset=solar", "--smoke"]
    else:
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise RuntimeError("Visual checks require a working display and renderer. Use godot-check for headless validation.")
        # Keep the output fresh and prevent extra flags from overriding evidence paths.
        reserved = {"--screenshot", "--preset", "--quit", "--offline_ok"}
        if any(flag.split("=", 1)[0] in reserved for flag in extra):
            parser.error("Screenshot, preset and quit are managed by the helper; offline checks require a direct Godot invocation.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        screenshot = ROOT / "shots" / f"{args.scenario}-{stamp}.png"
        command += ["--resolution", "1280x720", "--", f"--preset={args.scenario}",
                    "--wait=6", f"--screenshot={screenshot.as_posix()}", "--quit", *extra]
    output = run(command)
    if re.search(r"SCRIPT ERROR|Parse Error|(?:^|\n)\s*ERROR:", output):
        raise RuntimeError("Godot reported an error despite a zero process exit code.")
    if screenshot:
        if not screenshot.is_file() or screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Godot did not produce a new PNG screenshot.")
        print(f"Inspect screenshot: {screenshot}")
    else:
        if "Godot live state check PASSED" not in output:
            raise RuntimeError("Godot did not confirm live physics state.")
        scene_output = run([godot, "--path", str(ROOT / "godot"), "--headless",
                            "--script", "res://tests/experiments.gd"])
        if re.search(r"SCRIPT ERROR|Parse Error|(?:^|\n)\s*ERROR:", scene_output) or "Godot experiment save/load/restart check PASSED" not in scene_output:
            raise RuntimeError("Godot experiment checks did not pass.")
        print("Godot headless check PASSED (rendered appearance not checked).")


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        if exc.output:
            print(exc.output.decode(errors="replace") if isinstance(exc.output, bytes) else exc.output)
        print("Check timed out; inspect any child physics server before restarting.", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
