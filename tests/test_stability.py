"""Regression tests for simulation integrity and the command/wire boundaries."""
import json
import socket
import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'physics_server'))
import server
import world as W


class WorldTests(unittest.TestCase):
    def test_rejected_placement_does_not_kick_attractor(self):
        w = W.World(max_bodies=1)
        w.add_body(W.ROCKY, 0.003, (0, 0, 0), (0, 0, 0))
        before = w.snapshot()['v'].copy()
        self.assertIsNone(w.spawn(W.STAR, (100, 0, 0)))
        np.testing.assert_array_equal(before, w.snapshot()['v'])

    def test_removal_repartitions(self):
        w = W.World()
        heavy = w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
        w.add_body(W.ASTEROID, 1e-5, (100, 0, 0), (0, 0, 0))
        w._repartition()
        w.remove_body(heavy)
        w._repartition()
        self.assertEqual(w.sim.N_active, 0)

    def test_partition_preserves_identity_and_state(self):
        w = W.World()
        ids = [w.add_body(t, m, (i * 100, 0, 0), (0, i, 0))
               for i, (t, m) in enumerate([(W.ASTEROID, 1e-5), (W.STAR, 1000),
                                           (W.PLASMA, 0.1), (W.ROCKY, 0.003)])]
        w._repartition()
        self.assertEqual(w.sim.N_active, 2)
        for i, bid in enumerate(ids):
            p = w.particle(str(bid))
            self.assertEqual((p.x, p.vy), (i * 100, i))
        self.assertEqual(set(w.snapshot()['names']), set(w.meta))

    def test_clear_drops_old_events_and_notices(self):
        w = W.World()
        w._event(W.EV_MERGE, (0, 0, 0), 1, 1)
        w.notice('old scene')
        w.clear()
        self.assertEqual((w.events, w.notices, w.sim.N), ([], [], 0))

    def test_unknown_preset_is_not_destructive(self):
        w = W.World()
        w.load_preset('solar')
        n = w.sim.N
        with self.assertRaises(ValueError):
            w.load_preset('typo')
        self.assertEqual(w.sim.N, n)

    def test_prediction_does_not_mutate_world(self):
        w = W.World(seed=1)
        w.load_preset('solar')
        before = w.snapshot()
        version = w.version
        w.predict(W.STAR, (100, 0, 0), 'orbit', (0, 0, 0), 10)
        for key in ('xyz', 'v', 'm', 'r'):
            np.testing.assert_array_equal(before[key], w.snapshot()[key])
        self.assertEqual(w.version, version)

    def test_packet_limit_and_event_batching(self):
        w = W.World(max_bodies=W.MAX_BODIES)
        for i in range(w.max_bodies):
            w.add_body(W.ASTEROID, 1e-5, (i, 0, 0), (0, 0, 0))
        for _ in range(65):
            w._event(W.EV_MERGE, (1, 2, 3), 4, 5)
        packet = server.pack_state(w)
        self.assertLessEqual(len(packet), 65507)
        header = np.frombuffer(packet, dtype='<f4')[:10]
        self.assertEqual(tuple(header[[0, 4, 5]]), (1, W.MAX_BODIES, 64))
        self.assertEqual(len(w.events), 1)
        self.assertEqual(len(server.pack_state(w)), 40 + W.MAX_BODIES * 48 + 32)

    def test_simultaneous_contact_cannot_discard_later_mass(self):
        w = W.World()
        bid = w.add_body(W.ROCKY, 0.009, (0, 0, 0), (0, 0, 0))
        rec = dict(s=str(bid), r='999', ts=W.ROCKY, tr=W.ROCKY, ms=.003, mr=.003,
                   rs=1, rr=1, vrel=(10, 0, 0), normal=(1, 0, 0), heat_r=0)
        w._handle_collision(rec)
        self.assertAlmostEqual(w.snapshot()['m'].sum(), 0.009)

    def test_kilonova_survivor_after_particle_array_growth(self):
        w = W.World(seed=8)
        bid = w.add_body(W.NEUTRON_STAR, 2700, (0, 0, 0), (0, 0, 0))
        allocated = w.sim.N_allocated
        while w.sim.N < allocated:
            w.add_body(W.ASTEROID, 1e-5, (1000 + w.sim.N, 0, 0), (0, 0, 0))
        w._kilonova(w.particle(str(bid)), {'s': str(bid), 'r': '9999', 'rs': 0.6, 'rr': 0.6})
        self.assertGreater(w.sim.N_allocated, allocated)
        self.assertEqual(w.meta[str(bid)]['type'], W.BLACK_HOLE)
        survivor = w.particle(str(bid))
        self.assertAlmostEqual(survivor.m, 2700 * 0.97)
        self.assertAlmostEqual(survivor.r, W.radius_for(W.BLACK_HOLE, survivor.m))

    def test_supernova_conserves_mass_and_momentum(self):
        w = W.World(seed=7)
        bid = w.add_body(W.STAR, 1000, (0, 0, 0), (1, 2, 3))
        self.assertTrue(w.supernova(bid))
        snap = w.snapshot()
        self.assertAlmostEqual(snap['m'].sum(), 1000)
        np.testing.assert_allclose((snap['m'][:, None] * snap['v']).sum(axis=0),
                                   [1000, 2000, 3000], rtol=1e-12)

    def test_repeated_scenarios_keep_finite_and_consistent_state(self):
        w = W.World(seed=42)
        for preset in W.SCENARIOS:
            with self.subTest(preset=preset):
                w.load_preset(preset)
                for _ in range(20):
                    w.advance(1 / 60, time.perf_counter() + 0.05)
                snap = w.snapshot()
                self.assertEqual(set(snap['names']), set(w.meta))
                self.assertLessEqual(snap['n'], w.max_bodies)
                for key in ('xyz', 'v', 'm', 'r'):
                    self.assertTrue(np.isfinite(snap[key]).all(), key)
                w._repartition()
                for i, name in enumerate(w.snapshot()['names']):
                    p = w.particle(name)
                    self.assertEqual(i < w.sim.N_active,
                                     not w.is_light(w.meta[name]['type'], p.m))

    def test_body_limit_validation(self):
        for value in (0, -1, W.MAX_BODIES + 1, True, 2.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                W.World(max_bodies=value)


class CommandTests(unittest.TestCase):
    def test_invalid_commands_do_not_mutate_world(self):
        w = W.World()
        w.load_preset('solar')
        service = server.Server.__new__(server.Server)
        service.world, service.verbose = w, False
        cases = [dict(cmd='add', type='star', pos=p) for p in
                 ([float('nan'), 0, 0], [float('inf'), 0, 0], [0, 0], 'xyz', [True, 0, 0])]
        cases += [dict(cmd='add', type='star', pos=[100, 0, 0], mass_mult=m)
                  for m in (-1, 0, float('nan'), float('inf'), '1', True)]
        cases += [dict(cmd='preset', name='typo'), dict(cmd='pause', value='false'),
                  dict(cmd='speed', value=float('nan')), dict(cmd='remove', id=1.5)]
        before = w.snapshot()
        for msg in cases:
            with self.subTest(msg=msg), self.assertRaises(ValueError):
                service.handle(msg, ('127.0.0.1', 1))
            np.testing.assert_array_equal(before['v'], w.snapshot()['v'])
            self.assertEqual(w.sim.N, before['n'])

    def test_udp_survives_bad_datagrams_and_accepts_next_command(self):
        w = W.World()
        service = server.Server('127.0.0.1', 0, w)
        self.addCleanup(service.sock.close)
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(client.close)
        client.bind(('127.0.0.1', 0))
        client.settimeout(2)
        address = service.sock.getsockname()
        for data in (b'\xff', b'{', b'[]', b'[' * 2000,
                     b'{"cmd":"add","type":"star","pos":[NaN,0,0]}',
                     json.dumps({'cmd': 'hello'}).encode()):
            client.sendto(data, address)
        deadline = time.monotonic() + 2
        while service.client is None and time.monotonic() < deadline:
            service.poll()
        self.assertEqual(json.loads(client.recv(4096))['protocol'], 1)
        self.assertEqual(w.sim.N, 0)
        client.sendto(b'{"cmd":"add","type":"rocky","pos":[0,0,0]}', address)
        while w.sim.N == 0 and time.monotonic() < deadline:
            service.poll()
        self.assertEqual(w.sim.N, 1)


if __name__ == '__main__':
    unittest.main()
