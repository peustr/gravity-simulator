#!/usr/bin/env python3
"""
Gravity Simulator - physics server.

Runs the REBOUND simulation (see world.py) and talks to the Godot front end
over UDP on your own machine (127.0.0.1 only - nothing leaves your computer).

    Godot  --JSON commands-->  this server (port 47810)
    Godot  <--binary state---  this server (~60 times per second)

Usage:
    python server.py                 # start the server and wait for Godot
    python server.py --selftest      # check the installation and exit
    python server.py --help          # all options
"""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import sys
import time
import traceback

try:
    import numpy as np
    import rebound
except ImportError as exc:  # friendly message instead of a stack trace
    print("\n[physics server] A required package is missing:", exc)
    print("Run the setup again (setup_physics_server.bat on Windows), or:")
    print("    python -m pip install -r requirements.txt\n")
    sys.exit(1)

import world as W
import experiments
import units
from commands import validate

PROTOCOL_VERSION = 2
STATE_KIND = 3
PREDICTION_KIND = 4
DEFAULT_PORT = 47810
TICK_HZ = 60
PHYSICS_BUDGET = 0.011       # seconds of physics per tick (keeps the server responsive)
MAX_EVENTS_PER_PACKET = 64
HEADER_FLOATS = 11
BODY_FLOATS = 12
EVENT_FLOATS = 8


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pack_state(world: W.World) -> bytes:
    """Binary state packet (little-endian float32), see README 'Protocol'."""
    snap = world.snapshot()
    n = snap["n"]
    events = world.events[:MAX_EVENTS_PER_PACKET]
    del world.events[:MAX_EVENTS_PER_PACKET]
    t = world.sim.t
    t_hi = float(int(t // 1000.0) * 1000.0)
    header = np.array([
        STATE_KIND, float(world.version % 16_000_000), t_hi, t - t_hi, n, len(events),
        1.0 if world.paused else 0.0, world.speed, world.perf, world.max_bodies,
        0.0 if world.units == units.LEGACY else 1.0,
    ], dtype="<f4")
    bodies = np.zeros((n, BODY_FLOATS), dtype="<f4")
    if n:
        names = snap["names"]
        meta = world.meta
        now = world.sim.t
        ids = np.fromiter((int(nm) for nm in names), dtype=np.float64, count=n)
        types = np.empty(n)
        heat = np.empty(n)
        age = np.empty(n)
        for i, nm in enumerate(names):
            md = meta.get(nm)
            if md is None:
                types[i], heat[i], age[i] = W.ASTEROID, 0.0, 0.0
            else:
                types[i], heat[i], age[i] = md["type"], md["heat"], now - md["born"]
        bodies[:, 0] = ids
        bodies[:, 1] = types
        bodies[:, 2:5] = snap["xyz"]
        bodies[:, 5:8] = snap["v"]
        bodies[:, 8] = snap["m"]
        bodies[:, 9] = snap["r"]
        bodies[:, 10] = heat
        bodies[:, 11] = age
    ev = np.array(events, dtype="<f4").reshape(len(events), EVENT_FLOATS)
    return header.tobytes() + bodies.tobytes() + ev.tobytes()


def pack_prediction(req_id: int, result: dict) -> bytes:
    pts = result["points"]
    vel = result["vel"]
    head = np.array([PREDICTION_KIND, req_id, len(pts), 1.0 if result["hit"] else 0.0,
                     result["attractor"], vel[0], vel[1], vel[2], result["radius"]], dtype="<f4")
    body = np.array(pts, dtype="<f4").reshape(len(pts), 3)
    return head.tobytes() + body.tobytes()


class Server:
    def __init__(self, host: str, port: int, world: W.World, verbose=False, exit_when_idle=0.0):
        self.world = world
        self.verbose = verbose
        self.exit_when_idle = exit_when_idle
        self.client = None
        self.checkpoint = experiments.capture(world, experiments.DEFAULT_CAMERA)
        self.scene_replies = {}
        self.last_heard = time.monotonic()
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 21)
        except OSError:
            pass
        # Windows quirk: without this, an ICMP "port unreachable" (Godot not
        # running yet) makes the next recvfrom() raise ConnectionResetError.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except (OSError, ValueError):
                pass
        try:
            self.sock.bind(self.addr)
        except OSError as exc:
            self.sock.close()
            print(f"\n[physics server] Could not listen on {host}:{port}: {exc}")
            print("Is another copy of the physics server already running?")
            print("Close it (or use --port to pick another port) and try again.\n")
            sys.exit(2)
        self.sock.setblocking(False)

    # ----------------------------------------------------------- networking
    def send(self, data: bytes, addr=None):
        addr = addr or self.client
        if addr is None:
            return
        try:
            self.sock.sendto(data, addr)
        except OSError:
            pass

    def send_json(self, obj: dict, addr=None):
        self.send(json.dumps(obj).encode("utf-8"), addr)

    def poll(self):
        for _ in range(500):
            try:
                data, addr = self.sock.recvfrom(65535)
            except (BlockingIOError, InterruptedError):
                return
            except ConnectionResetError:
                continue
            except OSError:
                return
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                continue
            if isinstance(msg, dict):
                try:
                    if msg.get("protocol") != PROTOCOL_VERSION:
                        self.send_json({"type": "protocol_error", "protocol": PROTOCOL_VERSION,
                                        "text": "Update both the physics server and Godot client (protocol 2)."}, addr)
                        continue
                    self.handle(msg, addr)
                    if addr == self.client:
                        self.last_heard = time.monotonic()
                except (ValueError, TypeError, OverflowError):
                    if self.verbose:
                        log("Rejected invalid command")
                except Exception:
                    traceback.print_exc()

    # -------------------------------------------------------------- commands
    def handle(self, msg: dict, addr):
        validate(msg)
        cmd = msg.get("cmd")
        w = self.world
        if self.verbose and cmd not in ("hello", "predict"):
            log(f"command: {msg}")
        if cmd in ("save_scene", "load_scene", "checkpoint", "restart"):
            self.handle_scene(msg, addr)
        elif cmd == "hello":
            if self.client != addr:
                log(f"Godot connected from {addr[0]}:{addr[1]}")
            self.client = addr
            self.send_json({
                "type": "info", "protocol": PROTOCOL_VERSION, "rebound": rebound.__version__,
                "integrator": "IAS15", "max_bodies": w.max_bodies, "pid": os.getpid(),
                "physical_units": units.metadata(),
                "physics": w.gravity_summary(),
            }, addr)
        elif cmd == "bye":
            if self.client == addr:
                log("Godot disconnected")
                self.client = None
        elif cmd == "add":
            btype = W.TYPE_KEYS.get(msg.get("type"), W.ROCKY)
            w.spawn(btype, msg["pos"], msg.get("mode", "orbit"), msg.get("drag", (0, 0, 0)),
                    float(msg.get("mass_mult", 1.0)))
        elif cmd == "predict":
            btype = W.TYPE_KEYS.get(msg.get("type"), W.ROCKY)
            result = w.predict(btype, msg["pos"], msg.get("mode", "orbit"), msg.get("drag", (0, 0, 0)),
                               float(msg.get("mass_mult", 1.0)))
            self.send(pack_prediction(int(msg.get("req", 0)), result), addr)
        elif cmd == "belt":
            w.belt(msg["pos"], int(msg.get("count", 60)), float(msg.get("mass_mult", 1.0)))
        elif cmd == "remove":
            w.remove_body(int(msg["id"]))
        elif cmd == "supernova":
            w.supernova(int(msg["id"]))
        elif cmd == "pause":
            w.paused = bool(msg.get("value", not w.paused))
            w.version += 1
        elif cmd == "speed":
            w.speed = min(2000.0, max(0.05, float(msg.get("value", 10.0))))
        elif cmd == "physics":
            w.configure(msg['settings'])
            self.send_json(dict(type='physics', **w.gravity_summary()), addr)
        elif cmd == "clear":
            w.clear()
            self.checkpoint = experiments.capture(w, experiments.DEFAULT_CAMERA)
        else:  # validate() guarantees the remaining command is preset.
            hint = w.load_preset(str(msg.get("name", "empty")))
            self.checkpoint = experiments.capture(w, hint["camera"])
            self.send_json(hint, addr)

    def handle_scene(self, msg, addr):
        # Retries repeat the acknowledgement, never the mutation or disk write.
        key = (addr, msg["request"])
        if key in self.scene_replies:
            self.send_json(self.scene_replies[key], addr)
            return
        cmd = msg["cmd"]
        reply = dict(type="scene_result", request=msg["request"], action=cmd, ok=False)
        try:
            if cmd in ("save_scene", "checkpoint"):
                data = experiments.capture(self.world, msg.get("camera"))
                if cmd == "save_scene":
                    experiments.save(msg["path"], data)
                self.checkpoint = data
            else:
                if cmd == "load_scene":
                    data, candidate, camera = experiments.load(msg["path"])
                else:
                    data = self.checkpoint
                    candidate, camera = experiments.restore(data)
                candidate.version = self.world.version + 1
                self.world = candidate
                self.checkpoint = data
                reply["camera"] = camera
            reply["ok"] = True
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            reply["error"] = f"Could not {cmd.replace('_', ' ')}: {str(exc)[:200]}"
        self.scene_replies[key] = reply
        if len(self.scene_replies) > 64:
            del self.scene_replies[next(iter(self.scene_replies))]
        self.send_json(reply, addr)

    # ------------------------------------------------------------- main loop
    def run(self):
        log(f"Physics server listening on {self.addr[0]}:{self.addr[1]}  "
            f"(REBOUND {rebound.__version__}, IAS15, max {self.world.max_bodies} bodies)")
        log("Now press Play in Godot (or run the exported game). Ctrl+C stops the server.")
        tick = 1.0 / TICK_HZ
        last = time.perf_counter()
        next_tick = last
        try:
            while True:
                self.poll()
                now = time.perf_counter()
                real_dt = min(now - last, 0.1)
                last = now
                self.world.advance(real_dt, now + PHYSICS_BUDGET)
                if self.client is not None:
                    self.send(pack_state(self.world))
                    while self.world.notices:
                        self.send_json(self.world.notices.pop(0))
                else:
                    self.world.events.clear()
                    self.world.notices.clear()
                if self.client is not None and time.monotonic() - self.last_heard > 3.0:
                    log("Lost contact with Godot (no messages for 3 s) - waiting for it to come back")
                    self.client = None
                if self.exit_when_idle and time.monotonic() - self.last_heard > self.exit_when_idle:
                    log(f"No contact for {self.exit_when_idle:.0f} s - exiting.")
                    return
                next_tick += tick
                wait = next_tick - time.perf_counter()
                if wait < -tick:
                    next_tick = time.perf_counter()
                    wait = 0
                if wait > 0:
                    select.select([self.sock], [], [], wait)
        except KeyboardInterrupt:
            log("Stopped.")
        finally:
            self.sock.close()


# ------------------------------------------------------------------ self test
def selftest() -> int:
    """Exercise every physics feature quickly. Returns a process exit code."""
    print(f"Python {sys.version.split()[0]}, REBOUND {rebound.__version__}, NumPy {np.__version__}")
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        print(f"  [{'ok' if cond else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
        ok = ok and bool(cond)

    def run(world, sim_time, max_wall=20.0):
        t_end = world.sim.t + sim_time
        wall0 = time.perf_counter()
        while world.sim.t < t_end and time.perf_counter() - wall0 < max_wall:
            world.paused = False
            world.speed = 1e9
            world._target_t = t_end
            world.advance(0.0, time.perf_counter() + 0.05)
        check("integration reaches requested time", world.sim.t >= t_end,
              f"{world.sim.t:.3f} / {t_end:.3f}")
        snap = world.snapshot()
        check("simulation remains finite", all(np.isfinite(snap[key]).all()
              for key in ("m", "r", "xyz", "v")))
        return world

    w = W.World(seed=1)
    for name in W.SCENARIOS:
        t0 = time.perf_counter()
        w.load_preset(name)
        n0 = w.sim.N
        run(w, 5.0)
        dt = (time.perf_counter() - t0) * 1000
        check(f"scenario '{name}' loads and runs", w.sim.N <= w.max_bodies and len(w.meta) == w.sim.N, f"{n0} bodies, {dt:.0f} ms")
        pack = pack_state(w)
        check(f"scenario '{name}' state packet fits in one UDP datagram", len(pack) < 65000, f"{len(pack)} bytes")

    # Gentle merger
    w = W.World(seed=2)
    w.add_body(W.ROCKY, 0.003, (0, 0, 0), (0, 0, 0))
    contact = W.radius_for(W.ROCKY, .003) + W.radius_for(W.ROCKY, .001)
    w.add_body(W.ROCKY, 0.001, (3 * contact, 0, 0), (-0.05, 0, 0))
    run(w, .1)
    kinds = [e[0] for e in w.events]
    check("slow impact merges two planets", w.sim.N == 1 and W.EV_MERGE in kinds,
          f"{w.sim.N} body left, mass {w.sim.particles[0].m:.4f}")

    # Catastrophic impact
    w = W.World(seed=3)
    w.load_preset("smash")
    run(w, 80)
    kinds = [e[0] for e in w.events]
    check("fast impact shatters planets into fragments", W.EV_SHATTER in kinds and w.sim.N > 4,
          f"{w.sim.N} bodies after the impact")
    w.events.clear()

    # Black hole swallow
    w = W.World(seed=4)
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ASTEROID, 2e-5, (20, 0, 0), (-20, 0, 0))
    run(w, 2)
    check("black hole captures a small body at physical contact", w.sim.N == 1 and W.EV_SWALLOW in [e[0] for e in w.events])

    # Tidal disruption
    w = W.World(seed=5)
    w.load_preset("black_hole")
    run(w, 60)
    check("star is torn apart by tides near the black hole", W.EV_TIDAL in [e[0] for e in w.events],
          f"{w.sim.N} bodies")

    # Supernova
    w = W.World(seed=6)
    sid = w.add_body(W.STAR, 10000, (0, 0, 0), (0, 0, 0))
    w.supernova(sid)
    check("supernova leaves a remnant and ejecta", W.EV_SUPERNOVA in [e[0] for e in w.events] and w.sim.N > 20,
          f"{w.sim.N} bodies")

    # Ignition
    w = W.World(seed=7)
    w.add_body(W.GAS_GIANT, 50, (0, 0, 0), (0, 0, 0))
    w.add_body(W.GAS_GIANT, 40, (8, 0, 0), (0, 0, 0))
    run(w, 30)
    types = [w.meta[n]["type"] for n in w.meta]
    check("merging gas giants ignite into a star", W.STAR in types)

    # Neutron star merger
    w = W.World(seed=8)
    w.add_body(W.NEUTRON_STAR, 1400, (-5, 0, 0), (0, 0, 0))
    w.add_body(W.NEUTRON_STAR, 1300, (5, 0, 0), (0, 0, 0))
    run(w, 10)
    kinds = [e[0] for e in w.events]
    check("neutron stars collide: kilonova + black hole", W.EV_KILONOVA in kinds and W.EV_COLLAPSE in kinds)

    # Prediction and belts
    w = W.World(seed=9)
    w.load_preset("solar")
    # Check orbit correctness without the interactive preview's 25 ms deadline:
    # coverage instrumentation and shared CI runners can exceed that budget.
    res = w.predict(W.ROCKY, (100.0, 0.0, 0.0), "orbit", (0, 0, 0), 1.0, wall_budget=1.0)
    pts = np.array(res["points"])
    radii = np.linalg.norm(pts, axis=1)
    check("orbit preview is a closed circle", len(pts) > 50 and radii.std() < 3.0,
          f"{len(pts)} points, radius {radii.mean():.1f} +/- {radii.std():.2f}")
    n0 = w.sim.N
    w.belt((60.0, 0.0, 0.0), 30)
    check("asteroid belt tool adds bodies", w.sim.N == n0 + 30)

    # Speed
    w = W.World(seed=10)
    w.load_preset("solar")
    t0 = time.perf_counter()
    run(w, 100)
    el = time.perf_counter() - t0
    check("solar system advances 100 time units within 10 seconds", el < 10.0,
          f"100 time units in {el:.2f} s (needs < 10 s)")

    print("\nSelf-test", "PASSED - you're ready to go!" if ok else "FAILED - see the lines marked FAIL above.")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Gravity Simulator physics server (REBOUND).")
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"UDP port (default {DEFAULT_PORT})")
    ap.add_argument("--max-bodies", type=int, default=600, help="cap on simultaneous bodies (default 600)")
    ap.add_argument("--seed", type=int, default=None, help="seed initial conditions and stochastic outcomes")
    ap.add_argument("--exit-when-idle", type=float, default=0.0,
                    help="exit after this many seconds without hearing from Godot (0 = never)")
    ap.add_argument("--selftest", action="store_true", help="run the built-in checks and exit")
    ap.add_argument("--verbose", action="store_true", help="log every command")
    ap.add_argument("--log", metavar="FILE", help="also write all messages to this file")
    args = ap.parse_args()
    if args.log:
        # When Godot starts the server there is no console window, so keep a
        # log file around for troubleshooting.
        logf = open(args.log, "w", buffering=1, encoding="utf-8")
        sys.stdout = logf
        sys.stderr = logf
    if args.selftest:
        sys.exit(selftest())
    if not 1 <= args.max_bodies <= W.MAX_BODIES:
        ap.error(f"--max-bodies must be between 1 and {W.MAX_BODIES}")
    if not 0 <= args.port <= 65535:
        ap.error("--port must be between 0 and 65535")
    if not np.isfinite(args.exit_when_idle) or args.exit_when_idle < 0:
        ap.error("--exit-when-idle must be finite and nonnegative")
    Server(args.host, args.port, W.World(max_bodies=args.max_bodies, seed=args.seed), args.verbose, args.exit_when_idle).run()


if __name__ == "__main__":
    main()
