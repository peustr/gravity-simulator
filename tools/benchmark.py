"""Repeatable physics accuracy and performance measurements; no display required."""
from __future__ import annotations

import argparse
from collections import Counter
import cProfile
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import pstats
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'physics_server'))

import numpy as np
import rebound

from diagnostics import Ledger, totals
from server import MAX_EVENTS_PER_PACKET, PHYSICS_BUDGET, TICK_HZ, pack_state
from validation import run_accuracy
import world as W

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('solar', 'binary', 'black_hole', 'smash', 'formation', 'galaxies')


def summary(values):
    return dict(count=len(values), p50_ms=float(np.percentile(values, 50)) * 1000 if values else None,
                p95_ms=float(np.percentile(values, 95)) * 1000 if values else None,
                max_ms=max(values) * 1000 if values else None)


def hardware():
    data = dict(cpu=platform.processor() or None, logical_cpus=os.cpu_count(), ram_bytes=None, gpu=None, model=None)
    try:
        if sys.platform == 'win32':
            script = "[pscustomobject]@{cpu=(Get-CimInstance Win32_Processor).Name; ram_bytes=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory; gpu=(Get-CimInstance Win32_VideoController).Name; model=(Get-CimInstance Win32_ComputerSystem).Model} | ConvertTo-Json -Compress"
            value = subprocess.check_output(['powershell', '-NoProfile', '-Command', script], timeout=15, text=True)
            data.update(json.loads(value))
        elif sys.platform.startswith('linux'):
            data['ram_bytes'] = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
            for line in Path('/proc/cpuinfo').read_text().splitlines():
                if line.startswith('model name'):
                    data['cpu'] = line.split(':', 1)[1].strip()
                    break
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # Unavailable hardware fields remain null; never invent a machine.
    return data


def metadata():
    data = dict(python=platform.python_version(), rebound=rebound.__version__, numpy=np.__version__,
                os=platform.system(), os_release=platform.release(), architecture=platform.machine(),
                hardware=hardware(), revision=None, working_tree_dirty=None)
    try:
        data['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        data['working_tree_dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True))
    except (OSError, subprocess.SubprocessError):
        pass
    return data


def workload(name, ticks, seed, audit=False):
    world = W.World(seed=seed)
    world.load_preset(name)
    initial = totals(world)
    solver = dict(integrator=str(world.sim.integrator), epsilon=world.sim.integrator.epsilon,
                  minimum_timestep=world.sim.integrator.min_dt, collision=world.sim.collision,
                  gravity_constant=world.sim.G, max_bodies=world.max_bodies)
    if audit:
        world.ledger = Ledger()
    advance, packing, forecast, tick_times, point_counts = [], [], [], [], []
    events = Counter()
    for tick in range(ticks):
        start = time.perf_counter()
        world.advance(1 / TICK_HZ, start + PHYSICS_BUDGET)
        after_advance = time.perf_counter()
        # Only count events consumed by this packet; backlogged events follow.
        events.update(int(event[0]) for event in world.events[:MAX_EVENTS_PER_PACKET])
        pack_state(world)
        after_pack = time.perf_counter()
        advance.append(after_advance - start)
        packing.append(after_pack - after_advance)
        if tick % 30 == 0:
            forecast_start = time.perf_counter()
            prediction = world.predict(W.ROCKY, (400, 50, 0), 'orbit', (0, 0, 0), 1.0)
            forecast.append(time.perf_counter() - forecast_start)
            point_counts.append(len(prediction['points']))
        tick_times.append(time.perf_counter() - start)
        world.notices.clear()
    final = totals(world)
    measured_seconds = sum(tick_times)
    report = dict(scenario=name, seed=seed, ticks=ticks, solver=solver,
                  initial_bodies=initial['bodies'], final_bodies=world.sim.N,
                  simulated_time=world.sim.t, requested_simulated_time=ticks / TICK_HZ * world.speed,
                  workload_wall_seconds=measured_seconds,
                  simulated_units_per_wall_second=world.sim.t / measured_seconds,
                  advance=summary(advance), packing=summary(packing), forecast=summary(forecast), tick=summary(tick_times),
                  ticks_over_60hz_budget=sum(value > 1 / TICK_HZ for value in tick_times),
                  forecast_point_counts=point_counts, events=dict(events),
                  initial_tracers=initial['tracers'], final_tracers=final['tracers'])
    if audit:
        report['accounting'] = world.ledger.report(initial, final)
    return report


def profile_workload(name, ticks, seed):
    profiler = cProfile.Profile()
    profiler.runcall(workload, name, ticks, seed)
    phases = {'steps': 'integration_including_collision_callbacks',
              '_resolve_collision': 'collision_callbacks', '_process_collisions': 'collision_outcomes',
              '_tidal_check': 'tides', 'predict': 'forecast', 'pack_state': 'packing'}
    entries = []
    for (_file, _line, function), (_primitive, calls, own, cumulative, _callers) in pstats.Stats(profiler).stats.items():
        if function in phases:
            entries.append(dict(phase=phases[function], calls=calls, own_ms=own * 1000,
                                inclusive_ms=cumulative * 1000))
    return dict(scenario=name, phases=entries,
                interpretation='Separate profiled run. Inclusive times overlap; do not sum them. REBOUND gravity and collision detection share the native integration call.')


def bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}–{high}')
        return number
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticks', type=bounded_int(1, 3600), default=600)
    parser.add_argument('--repeats', type=bounded_int(1, 10), default=3)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--scenario', choices=SCENARIOS, action='append')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--accuracy-only', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = args.output or ROOT / 'benchmarks' / f'physics-{stamp}.json'
    report = dict(format='gravity-baseline', version=1, created_at_utc=stamp, machine=metadata(),
                  settings=dict(ticks=args.ticks, repeats=args.repeats, seed=args.seed,
                                tick_hz=TICK_HZ, physics_budget_seconds=PHYSICS_BUDGET,
                                forecast_every_ticks=30, forecast_position=[400, 50, 0]),
                  accuracy=run_accuracy(), runs=[], accounting_runs=[], profiles=[],
                  rendering='Not measured by this command; use benchmark-visual with a working display.',
                  performance_targets=dict(advance_p95_ms=11.0, forecast_p95_ms=33.0,
                                           frame_p95_ms=33.3, preferred_frame_p95_ms=16.7),
                  notes=['Timings exclude startup, accuracy tests and inventory calculation.',
                         'Workloads feed 1/60 s ticks without sleeping; they are not live end-to-end latency measurements.',
                         'Seeds reproduce initial conditions; wall budgets can change subsequent trajectories.',
                         'Accounting runs enable expensive inventory sampling and are excluded from timing comparisons.',
                         'Energy is Newtonian mechanical energy; spin, heat and rest-mass energy are absent.',
                         'Tracer-containing systems and collision/explosion scenarios are not closed conservative systems.'])
    for case in report['accuracy']:
        print(f"{'PASS' if case['passed'] else 'FAIL'} {case['name']}: {case['errors']}", flush=True)
    if not args.accuracy_only:
        for name in args.scenario or SCENARIOS:
            # One warmup on a disposable world; measured repeats start afresh.
            workload(name, min(60, args.ticks), args.seed)
            for repeat in range(args.repeats):
                run = workload(name, args.ticks, args.seed)
                run['repeat'] = repeat + 1
                report['runs'].append(run)
                print(f"{name} #{repeat + 1}: tick p95 {run['tick']['p95_ms']:.2f} ms, "
                      f"{run['simulated_time']:.2f}/{run['requested_simulated_time']:.2f} simulated units", flush=True)
            report['accounting_runs'].append(workload(name, args.ticks, args.seed, audit=True))
            if args.profile:
                report['profiles'].append(profile_workload(name, args.ticks, args.seed))
    report['accuracy_passed'] = all(case['passed'] for case in report['accuracy'])
    report['accounting_complete'] = all(not run['accounting']['errors'] for run in report['accounting_runs'])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Report: {path.resolve()}', flush=True)
    return 0 if report['accuracy_passed'] and report['accounting_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
