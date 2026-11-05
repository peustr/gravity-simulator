"""Scene contracts and transition audit. Reports failure and missing evidence explicitly."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import shutil

import numpy as np

PROMISES = {
    "solar": "Eight bound planetary primaries at Solar System orbital scales",
    "binary": "A bound stellar binary over multiple orbits",
    "black_hole": "Local tidal disruption and physically accounted capture",
    "smash": "Observable calibrated contact and persistent disruption remnants",
    "formation": "A disk with multigeneration growth from at least three embryos",
    "galaxies": "Continuous gravitational interaction of two particle disks",
    "empty": "An empty, advancing sandbox with no inherited objects",
}


def issue(code, message, *, status="FAIL", **evidence):
    return dict(code=code, status=status, message=message, evidence=evidence)


def status(issues):
    if any(i["status"] == "FAIL" for i in issues):
        return "FAIL"
    return "BLOCKED" if issues else "PASS"


def snapshot(world):
    return {
        p.name: dict(
            mass=p.m, radius=p.r, position=tuple(p.xyz), velocity=tuple(p.vxyz), type=world.meta[p.name]["type"]
        )
        for p in world.sim.particles
    }


def valid_sample(data):
    return (
        all(np.isfinite(data[key]).all() for key in ("m", "r", "xyz", "v"))
        and np.all(data["m"] > 0)
        and np.all(data["r"] > 0)
    )


def birth_geometry(parent, children):
    """An instantaneous breakup starts within its source, not an extended stream."""
    if not children:
        return []
    radius = parent["radius"]
    for body in (parent, *children):
        values = [body["mass"], body["radius"], *body["position"], *body["velocity"]]
        if not all(math.isfinite(v) for v in values) or min(values[:2]) <= 0:
            return [issue("invalid_birth", "Nonfinite or nonpositive material appeared during breakup")]
    offsets = [math.dist(c["position"], parent["position"]) / radius for c in children]
    radii = [c["radius"] / radius for c in children]
    issues = []
    # Five percent accommodates a coarse boundary representation, not expansion.
    if max(offsets) > 1.05:
        issues.append(
            issue(
                "nonlocal_birth",
                "Debris is created outside the source volume",
                maximum_source_radii=max(offsets),
                limit=1.05,
            )
        )
    if max(radii) > 1.05:
        issues.append(
            issue(
                "instant_volume_expansion",
                "A debris parcel is larger than its source",
                maximum_radius_ratio=max(radii),
                limit=1.05,
            )
        )
    masses = [c["mass"] for c in children]
    centre = np.average([c["position"] for c in children], axis=0, weights=masses)
    centre_error = math.dist(centre, parent["position"]) / radius
    velocity = np.average([c["velocity"] for c in children], axis=0, weights=masses)
    velocity_error = math.dist(velocity, parent["velocity"]) / max(math.hypot(*parent["velocity"]), 1e-30)
    if centre_error > 1e-8:
        issues.append(
            issue(
                "source_com_jump",
                "Breakup displaces the material centre of mass",
                source_radii=centre_error,
                limit=1e-8,
            )
        )
    if velocity_error > 1e-10:
        issues.append(
            issue(
                "source_momentum_change",
                "Breakup changes bulk momentum without a physical source",
                relative_change=velocity_error,
                limit=1e-10,
            )
        )
    return issues


def assembly_check(lineages):
    largest = max(map(len, lineages.values()), default=0)
    return (
        []
        if largest >= 3
        else [
            issue(
                "no_multigeneration_growth",
                "No surviving body assembles material from three initial embryos",
                maximum_initial_contributors=largest,
                required=3,
            )
        ]
    )


def audit_scene(name, *, seed=42, seconds=12, wall_limit=30):
    import world as W
    from diagnostics import conservation_report

    world = W.World(seed=seed)
    if name == "smash":
        world.load_collision_demo("disruption")  # The application's default menu path.
    else:
        world.load_preset(name)
    initial = snapshot(world)
    initial_mass = math.fsum(b["mass"] for b in initial.values())

    def momentum(states):
        return np.sum([np.array(b["velocity"]) * b["mass"] for b in states.values()], axis=0) if states else np.zeros(3)

    momentum_scale = math.fsum(b["mass"] * math.hypot(*b["velocity"]) for b in initial.values())
    initial_momentum = momentum(initial)
    issues, transitions = [], []
    lineages = {n: {n} for n, b in initial.items() if b["type"] == W.ROCKY}
    stars = [n for n, b in initial.items() if b["type"] == W.STAR]
    holes = [n for n, b in initial.items() if b["type"] == W.BLACK_HOLE]
    original = world._disrupt

    def observe(victim, heavy):
        before = snapshot(world)
        original(victim, heavy)
        after = snapshot(world)
        if victim in before and victim not in after:
            children = [b for n, b in after.items() if n not in before]
            found = birth_geometry(before[victim], children)
            transitions.append(
                dict(kind="tidal_disruption", time=world.sim.t, source=victim, children=len(children), issues=found)
            )
            issues.extend(found)

    world._disrupt = observe
    conservation_report(world, reset=True)
    world.paused = False
    deadline = time.perf_counter() + wall_limit
    target = seconds * world.speed
    steps = 0
    events = Counter()
    for _ in range(round(seconds * 60)):
        world.advance(1 / 60, min(deadline, time.perf_counter() + 0.05))
        steps += 1
        if not valid_sample(world.snapshot()):
            issues.append(issue("invalid_sample", "Nonfinite or nonpositive state during the scene", tick=steps))
            break
        for event in world.events:
            events[int(event[0])] += 1
            if event[0] == W.EV_MERGE:
                survivor, removed = str(int(event[6])), str(int(event[7]))
                if survivor in lineages and removed in lineages:
                    lineages[survivor] |= lineages.pop(removed)
        world.events.clear()
        if world.paused or world.notices or time.perf_counter() >= deadline:
            break
    final = snapshot(world)
    if world.paused or world.notices:
        issues.append(
            issue("interrupted_scene", "The default scene paused or emitted a refusal", notices=world.notices)
        )
    if world.sim.t < target * (1 - 1e-8):
        issues.append(
            issue(
                "incomplete_interval",
                "The full reference interval was not observed",
                status="BLOCKED",
                observed=world.sim.t,
                required=target,
            )
        )
    for n, body in final.items():
        values = [body["mass"], body["radius"], *body["position"], *body["velocity"]]
        if not all(math.isfinite(v) for v in values) or min(values[:2]) <= 0:
            issues.append(issue("invalid_body", "Body state is nonfinite or nonpositive", body=n))
    mass_error = abs(math.fsum(b["mass"] for b in final.values()) - initial_mass) / max(initial_mass, 1e-30)
    if mass_error > 1e-12:
        issues.append(issue("mass_change", "Default interval has unexplained mass change", relative_error=mass_error))
    momentum_error = float(np.linalg.norm(momentum(final) - initial_momentum)) / max(momentum_scale, 1e-30)
    if momentum_error > 1e-9:
        issues.append(
            issue("momentum_change", "Default interval has unexplained momentum change", relative_error=momentum_error)
        )
    budget = conservation_report(world)
    if budget["current"]["energy_j"] is None:
        issues.append(issue("unknown_energy_budget", "Physical energy accounting became unavailable", status="BLOCKED"))
    elif budget["relative_conservation_residual"] is not None and abs(budget["relative_conservation_residual"]) > 1e-8:
        issues.append(
            issue(
                "energy_residual",
                "Accounted energy exceeds the numerical reference bound",
                relative_error=budget["relative_conservation_residual"],
            )
        )
    if events[W.EV_IGNITION] or sum(b["type"] == W.STAR for b in final.values()) > len(stars):
        issues.append(issue("unexplained_stellar_birth", "New stars appeared during the default interval"))
    if name in ("solar", "binary"):
        if len(stars) != (1 if name == "solar" else 2):
            issues.append(issue("stellar_primary_count", "Scene has the wrong number of stellar primaries"))
        if any(n not in final for n in stars):
            issues.append(issue("missing_primary", "A stellar primary disappeared"))
        if name == "solar" and stars:
            primary = stars[0]
            planets = sorted(
                (n for n, b in initial.items() if b["type"] in (W.ROCKY, W.GAS_GIANT)),
                key=lambda n: initial[n]["mass"],
                reverse=True,
            )[:8]
            pairs = [(primary, n) for n in planets]
            if len(planets) != 8:
                issues.append(issue("planet_count", "Solar system requires eight planetary primaries"))
            import units

            distances = sorted(
                math.dist(initial[primary]["position"], initial[n]["position"]) * units.LENGTH_M / units.AU_M
                for n in planets
            )
            nominal = (0.3871, 0.7233, 1.0, 1.5237, 5.2044, 9.5826, 19.2184, 30.11)
            if len(distances) == 8 and any(abs(a / b - 1) > 0.01 for a, b in zip(distances, nominal, strict=True)):
                issues.append(
                    issue("orbital_scale", "Initial planetary distances depart from nominal AU scales by over 1%")
                )
        else:
            pairs = [tuple(stars)] if len(stars) == 2 else []
        for a, b in pairs:
            if a not in final or b not in final:
                issues.append(issue("missing_orbiter", "A promised orbital primary disappeared"))
                continue
            r = math.dist(final[a]["position"], final[b]["position"])
            v = math.dist(final[a]["velocity"], final[b]["velocity"])
            if 0.5 * v * v - W.G * (final[a]["mass"] + final[b]["mass"]) / r >= 0:
                issues.append(issue("unbound_primary", "A promised bound primary escaped", body=b))
    if name == "formation":
        issues.extend(assembly_check({n: s for n, s in lineages.items() if n in final}))
    if name == "black_hole" and not any(final[n]["mass"] > initial[n]["mass"] for n in holes if n in final):
        issues.append(issue("no_capture", "No material was captured during the feeding reference interval"))
    if name == "smash" and (world.last_impact is None or world.last_impact["regime"] != "supercatastrophic_disruption"):
        issues.append(issue("missing_contact_outcome", "The selected disruption encounter did not occur"))
    if name == "empty" and final:
        issues.append(issue("nonempty_sandbox", "Empty space inherited bodies"))
    return dict(
        scene=name,
        promise=PROMISES[name],
        status=status(issues),
        issues=issues,
        transitions=transitions,
        initial_bodies=len(initial),
        final_bodies=len(final),
        requested_time=target,
        observed_time=world.sim.t,
        ticks=steps,
        seed=seed,
        mass_error=mass_error,
        momentum_error=momentum_error,
        final_types=dict(Counter(b["type"] for b in final.values())),
    )


def capture_rendered(project, folder, godot, renderer, seed=42):
    """Collect all scenes even if backend contracts already failed."""
    folder.mkdir(parents=True)
    if not godot or (sys.platform.startswith("linux") and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))):
        return dict(status="BLOCKED", reason="A Godot executable and real display are required")
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.bind(("127.0.0.1", 47810))
        except OSError:
            return dict(status="BLOCKED", reason="Physics port occupied; close the existing session before QA")
    env = os.environ.copy()
    if sys.platform.startswith("linux"):
        for key, subdir in (("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
            env.setdefault(key, str(folder / subdir))
            Path(env[key]).mkdir(parents=True, exist_ok=True)
    command = [
        godot,
        "--path",
        str(project / "godot"),
        "--resolution",
        "1280x720",
        "--rendering-method",
        renderer,
        "--audio-driver",
        "Dummy",
        "--script",
        "res://tests/scene_quality.gd",
        "--",
        "--qa-output=" + str(folder),
        "--qa-seed=" + str(seed),
    ]
    # Own a seeded server and verify its PID before allowing the GUI to mutate it.
    with (folder / "physics.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(project / "physics_server/server.py"), "--seed", str(seed)],
            cwd=project,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.1)
                deadline = time.monotonic() + 5
                verified = False
                while process.poll() is None and time.monotonic() < deadline:
                    client.sendto(b'{"cmd":"hello","protocol":2}', ("127.0.0.1", 47810))
                    try:
                        packet, _ = client.recvfrom(65535)
                        if json.loads(packet).get("pid") == process.pid:
                            verified = True
                            break
                    except (OSError, ValueError):
                        pass
                if not verified:
                    return dict(status="BLOCKED", reason="Could not verify ownership of the seeded physics server")
            try:
                completed = subprocess.run(
                    command, cwd=project, env=env, capture_output=True, text=True, errors="replace", timeout=360
                )
            except subprocess.TimeoutExpired as exc:
                (folder / "engine.log").write_text(str(exc))
                return dict(status="BLOCKED", reason="Recording timed out")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    (folder / "engine.log").write_text(completed.stdout + completed.stderr)
    file = folder / "render.json"
    if not file.exists():
        return dict(status="BLOCKED", reason="No completed rendered report; inspect engine.log")
    data = json.loads(file.read_text())
    engine_error = completed.returncode != 0 or any(
        line.lstrip().startswith(("ERROR:", "SCRIPT ERROR:"))
        for line in (completed.stdout + completed.stderr).splitlines()
    )
    return assess_rendered(data, engine_error=engine_error, evidence_root=folder)


def assess_rendered(data, *, engine_error=False, evidence_root=None):
    problems = []
    if engine_error:
        problems.append(issue("engine_error", "Renderer or interaction suite reported errors"))
    if {s["scene"] for s in data["scenes"]} != set(PROMISES):
        problems.append(issue("missing_scenes", "Rendered report did not include all presets", status="BLOCKED"))
    if (
        data.get("display") == "headless"
        or data.get("renderer") != "forward_plus"
        or data.get("engine_version") != dict(major=4, minor=7, patch=2)
    ):
        problems.append(
            issue(
                "different_rendering_path", "Diagnostic rendering does not match Godot 4.7.2 Forward+", status="BLOCKED"
            )
        )
    if not data.get("controls_passed"):
        problems.append(issue("interaction_failure", "The all-preset controls suite failed"))
    for scene in data["scenes"]:
        for problem in scene["issues"]:
            problems.append(issue(problem, "Rendered scene failed acceptance", scene=scene["scene"]))
        frames = scene.get("frames", [])
        complete = bool(frames) and all(
            isinstance(f.get("path"), str) and isinstance(f.get("time_s"), (float, int)) for f in frames
        )
        if complete:
            times = [f["time_s"] for f in frames]
            stages = {f.get("stage") for f in frames}
            watch = [f["time_s"] for f in frames if f.get("stage") == "watch"]
            complete = (
                all(b > a for a, b in zip(times[:-1], times[1:], strict=True))
                and {"initial", "watch", "aftermath", "save_edit_restart_load"} <= stages
                and len(watch) >= 2
                and max(watch) - min(watch) >= 10
            )
        if evidence_root is not None and complete:
            complete = all((evidence_root / f["path"]).is_file() for f in frames)
        if not complete:
            problems.append(
                issue(
                    "missing_sequence",
                    "Complete timed evidence through startup, event, aftermath and controls is missing",
                    status="BLOCKED",
                    scene=scene["scene"],
                )
            )
    data.update(status=status(problems), issues=problems)
    return data


def write_viewer(path, rendered):
    scenes = rendered.get("scenes", [])
    if not scenes:
        return
    # Relative image paths work when an artifact ZIP is extracted and opened locally.
    body = r"""<!doctype html><meta charset="utf-8"><title>Scene quality recordings</title>
<style>body{background:#111;color:#ddd;font:16px system-ui;margin:20px}img{width:min(100%,1280px)}button,select{font:inherit;margin:8px}pre{white-space:pre-wrap}</style>
<h1>Scene quality recordings</h1><p>Recorded wall-clock timing. Inspect startup, peak events and aftermath. Recording affects frame time.</p>
<select id="scene"></select><button id="play">Play/pause</button><button id="peak">Peak brightness</button>
<input id="seek" type="range" min="0" value="0" step="0.01"><pre id="info"></pre><img id="frame">
<script>const scenes=SCENE_DATA;let selected=0,playing=false,offset=0,clock=0;
const menu=document.getElementById('scene'),image=document.getElementById('frame'),seek=document.getElementById('seek');
for(const s of scenes){const o=document.createElement('option');o.textContent=s.scene;menu.append(o)}
function show(t){const s=scenes[selected];const f=s.frames.filter(f=>f.time_s<=t).at(-1)||s.frames[0];if(!f)return;image.src='render/'+f.path;seek.value=t;document.getElementById('info').textContent=s.scene+' · '+f.stage+' · '+t.toFixed(2)+' s · simulated '+f.sim_time+' · white '+f.white_fraction.toFixed(3)+'\n'+JSON.stringify(s.issues)}
function reset(){playing=false;offset=0;seek.max=scenes[selected].frames.at(-1)?.time_s||0;show(0)}
menu.onchange=()=>{selected=menu.selectedIndex;reset()};seek.oninput=()=>{playing=false;offset=+seek.value;show(offset)};
document.getElementById('play').onclick=()=>{playing=!playing;clock=performance.now()};
document.getElementById('peak').onclick=()=>{playing=false;image.src='render/'+scenes[selected].peak_frame};
function tick(){const n=performance.now();if(playing){offset+=(n-clock)/1000;if(offset>+seek.max){offset=+seek.max;playing=false}show(offset)}clock=n;requestAnimationFrame(tick)}reset();tick();</script>"""
    path.write_text(body.replace("SCENE_DATA", json.dumps(scenes).replace("</", "<\\/")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend-only", action="store_true", help="Diagnostic subset; cannot approve appearance")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--renderer", default="forward_plus", choices=("forward_plus", "gl_compatibility"))
    args = parser.parse_args()
    project = args.project.resolve()
    args.output = (
        args.output
        or project / "benchmarks" / datetime.now(timezone.utc).strftime("scene-quality-%Y%m%dT%H%M%S%f") / "report.json"
    ).resolve()
    if args.output.exists() or (args.output.parent / "render").exists():
        raise SystemExit("Use a fresh output path; stale recordings cannot be evidence")
    sys.path.insert(0, str(project / "physics_server"))
    import world as W

    if set(W.SCENARIOS) != set(PROMISES):
        raise SystemExit("Every preset requires a scene contract; registry mismatch")
    results = []
    for name in W.SCENARIOS:
        try:
            results.append(audit_scene(name, seed=args.seed))
        except Exception as exc:
            results.append(
                dict(scene=name, promise=PROMISES[name], status="FAIL", issues=[issue("audit_exception", str(exc))])
            )
    from validation import run_accuracy

    references = run_accuracy()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
    report = dict(
        format="scene-quality-audit",
        version=1,
        revision=revision,
        working_tree_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=project)),
        audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scenes=results,
        automated_backend_status=status([i for r in results for i in r["issues"]]),
        references=references,
        references_passed=all(r["passed"] for r in references),
        rendered_status="BLOCKED",
        interaction_status="BLOCKED",
        release_status="NOT_APPROVED",
        missing_evidence=[
            "Target-renderer continuous recordings",
            "Interactive controls",
            "Consumer-hardware performance",
            "Complete-sequence human review",
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.backend_only:
        rendered = capture_rendered(
            project,
            args.output.parent / "render",
            os.getenv("GODOT") or shutil.which("godot") or shutil.which("godot4"),
            args.renderer,
            args.seed,
        )
        report.update(
            rendered=rendered,
            rendered_status=rendered["status"],
            interaction_status="PASS" if rendered.get("controls_passed") else "BLOCKED",
        )
        write_viewer(args.output.parent / "index.html", rendered)
        if report["rendered_status"] == "PASS":
            report["missing_evidence"].remove("Target-renderer continuous recordings")
        if report["interaction_status"] == "PASS":
            report["missing_evidence"].remove("Interactive controls")
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for result in results:
        print(
            result["scene"], result["status"], ", ".join(i["code"] for i in result["issues"]) or "backend checks passed"
        )
    print("Release NOT APPROVED; rendered/interaction/performance review required")
    failed = (
        report["automated_backend_status"] == "FAIL"
        or report["rendered_status"] == "FAIL"
        or not report["references_passed"]
    )
    blocked = report["automated_backend_status"] == "BLOCKED" or (
        not args.backend_only and report["rendered_status"] == "BLOCKED"
    )
    raise SystemExit(1 if failed else 2 if blocked else 0)


if __name__ == "__main__":
    main()
