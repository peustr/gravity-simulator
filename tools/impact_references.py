"""Export runnable, validated impact experiments for the existing collision engine."""

from __future__ import annotations

import argparse
from pathlib import Path
import math
import sys
import time

import numpy as np
import rebound

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "physics_server"))
from body_state import BodyInventory
from diagnostics import conservation_report
from disruption import estimate_head_on_disruption
import experiments as E
import units as U
import world as W
from collision_models import surface_contact, _impact
from disruption import classify_contact


PLANET_CASES = (
    ("merging", 0, 0.5, "escape"),
    ("graze_and_merge", 0.6, 1.0, "escape"),
    ("hit_and_run", 0.9, 1.5, "escape"),
    ("hit_and_run_stripping", 0.7, 3.0, "escape"),
    ("partial_accretion", 0, 0.4, "disruption"),
    ("erosion", 0, 0.95, "disruption"),
    ("disruption", 0, 1.3, "disruption"),
    ("supercatastrophic_disruption", 0, 2.2, "disruption"),
)
SMALL_CASES = (
    ("merging", 0, 0.5, "escape"),
    ("partial_accretion", 0, 0.3, "disruption"),
    ("erosion", 0, 0.7, "disruption"),
    ("disruption", 0, 1.3, "disruption"),
    ("supercatastrophic_disruption", 0, 2.2, "disruption"),
)


def reference_world(case, material="fluid_planets", *, capacity=600, unsupported_spin=False):
    """Use Planet smash's masses, or a 20 km small-body target, at a set contact."""
    name, angle, ratio, scale = case
    w = W.World(max_bodies=capacity, seed=42)
    camera = w.load_preset("smash")["camera"]
    if material == "planetesimals":
        w.clear()
        w.configure(dict(impact_material=material))
        mass = (20_000 / U.LENGTH_M / w.radius_for(W.ASTEROID, 1)) ** 3
        w.add_body(W.ASTEROID, mass, (0, 0, 0), (0, 0, 0))
        w.add_body(W.ASTEROID, mass * 0.25, (1, 0, 0), (0, 0, 0))
    a, b = w.sim.particles
    total, radius = a.m + b.m, a.r + b.r
    fraction = b.m / total
    if scale == "escape":
        speed = ratio * math.sqrt(2 * w.sim.G * total / radius)
    else:
        q = estimate_head_on_disruption(a.m * U.MASS_KG, b.m * U.MASS_KG, 0, material=material).disruption_energy_j_kg
        speed = math.sqrt(2 * ratio * q / (fraction * (1 - fraction))) / U.VELOCITY_M_S
    velocity = speed * np.array([-math.sqrt(1 - angle * angle), 0, angle])
    back = rebound.Simulation()
    back.integrator = "ias15"
    back.integrator.epsilon = 1e-12
    for p, weight in ((a, -fraction), (b, 1 - fraction)):
        position = weight * radius * np.array([1, 0, 0])
        v = weight * velocity
        back.add(m=p.m, x=position[0], y=position[1], z=position[2], vx=-v[0], vy=-v[1], vz=-v[2])
    lead = min(0.03, 0.1 * radius / speed) if scale == "escape" and ratio < 1 else 0.03
    back.integrate(lead)
    for p, q in zip(w.sim.particles, back.particles, strict=True):
        p.xyz = q.xyz
        p.vxyz = [-v for v in q.vxyz]
    if unsupported_spin:
        w.meta["1"]["inventory"] = BodyInventory((0, 0, 1e30), 0)
    w.paused = True
    w.speed = 0.05
    camera.update(distance=1.5, display_scale=0.5)
    return w, camera, lead


def export_references(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for material, cases, prefix in (
        ("fluid_planets", PLANET_CASES, "planet"),
        ("planetesimals", SMALL_CASES, "small-body"),
    ):
        for case in cases:
            for compact in (False, True) if case[0] == "supercatastrophic_disruption" else (False,):
                w, camera, lead = reference_world(case, material, capacity=2 if compact else 600)
                name = f"{prefix}-{case[0]}" + ("-compact" if compact else "")
                path = directory / (name + ".gravity.json")
                E.save(path, E.capture(w, camera))
                executed = []
                apply = w._apply_isolated_collision

                def record(rec, apply=apply, executed=executed):
                    apply(rec)
                    executed.append(rec)

                w._apply_isolated_collision = record
                conservation_report(w)
                w.paused = False
                w.speed = 1
                target = lead + 0.002
                deadline = time.perf_counter() + 3
                while w.sim.t < target - 1e-12 and not w.paused and time.perf_counter() < deadline:
                    w.advance(min(0.001, target - w.sim.t), time.perf_counter() + 0.1)
                report = conservation_report(w)
                if w.paused or w.sim.t < target - 1e-12 or abs(report["relative_energy_change"]) > 1e-8:
                    raise RuntimeError(f"Impact reference failed: {name}: {w.notices}")
                if not w.events:
                    raise RuntimeError(f"Impact reference has no live collision: {name}")
                classification = classify_contact(
                    _impact(*surface_contact(*executed[0]["spheres"])),
                    unit_system="si",
                    material=material,
                    body_types=(executed[0]["ts"], executed[0]["tr"]),
                )
                expected = "hit_and_run" if case[0] == "hit_and_run_stripping" else case[0]
                largest = w.particle(executed[0]["s"]).m * U.MASS_KG
                if classification.regime != expected or not math.isclose(
                    largest, classification.largest_remnant_mass_kg, rel_tol=1e-10
                ):
                    raise RuntimeError(f"Live mass outcome disagrees with classification: {name}")
                records.append(
                    dict(
                        name=name,
                        path=str(path),
                        regime=classification.regime,
                        bodies=w.sim.N,
                        unresolved_fragments=report["current"]["unresolved_fragments"],
                        relative_energy_change=report["relative_energy_change"],
                    )
                )
    w, camera, _ = reference_world(PLANET_CASES[0], unsupported_spin=True)
    E.save(directory / "planet-unsupported-spin.gravity.json", E.capture(w, camera))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    records = export_references(args.output)
    for record in records:
        print(
            f"[ok] {record['name']}: {record['bodies']} bodies, {record['unresolved_fragments']} unresolved fragments"
        )
    print(f"Exported {len(records) + 1} experiments. Load a .gravity.json file through Experiment, then press Play.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
