"""Cross-platform development commands; no third-party tooling dependencies."""
from __future__ import annotations

import argparse
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
    parser.add_argument("command", choices=("setup", "selftest", "godot-check", "visual-check"))
    parser.add_argument("scenario", nargs="?", choices=SCENARIOS, default="solar")
    args, extra = parser.parse_known_args()
    if extra and args.command != "visual-check":
        parser.error("Extra automation flags are only supported for visual-check.")
    if args.command == "setup":
        if not (3, 10) <= sys.version_info[:2] < (3, 15):
            raise RuntimeError("Use Python 3.10–3.14; prefer 3.13 on Windows or 3.12 in cloud.")
        run([sys.executable, "-m", "venv", str(VENV)])
        run([str(PYTHON), "-m", "pip", "install", "-r", "physics_server/requirements.txt"], 300)
        run([str(PYTHON), "-m", "pip", "check"])
    if not PYTHON.is_file():
        raise RuntimeError("Missing physics venv. Run this helper's setup command first.")
    if args.command in ("setup", "selftest"):
        selftest()
        return

    godot = os.environ.get("GODOT") or shutil.which("godot") or shutil.which("godot4")
    if not godot:
        raise RuntimeError("Godot 4.6+ not found. Set GODOT to its executable or add it to PATH.")
    if sys.platform.startswith("linux"):
        for key, suffix in (("XDG_CACHE_HOME", ".cache"), ("XDG_DATA_HOME", ".local/share")):
            os.environ.setdefault(key, str(VENV / suffix))
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
    command = [godot, "--path", str(ROOT / "godot")]
    screenshot = None
    if args.command == "godot-check":
        command += ["--headless", "--quit-after", "300", "--", "--preset=solar"]
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
