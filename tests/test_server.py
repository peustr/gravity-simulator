import json
import socket
import struct
import time

import numpy as np
import pytest

import server as S
import world as W


@pytest.fixture
def server():
    instance = S.Server('127.0.0.1', 0, W.World(seed=1))
    yield instance
    instance.sock.close()


@pytest.mark.parametrize('msg', [
    {'cmd': 'add', 'type': 'star', 'pos': [float('nan'), 0, 0]},
    {'cmd': 'add', 'type': 'star', 'pos': [0, 0]},
    {'cmd': 'add', 'type': 'star', 'pos': [0, 0, 0], 'mass_mult': -1},
    {'cmd': 'add', 'type': 'star', 'pos': [0, 0, 0], 'drag': [0, float('inf'), 0]},
    {'cmd': 'add', 'type': [], 'pos': [0, 0, 0]},
    {'cmd': 'predict', 'type': 'star', 'pos': [0, 0, 0], 'req': 2**24 + 1},
    {'cmd': 'belt', 'pos': [0, 0, 0], 'count': 2.5},
    {'cmd': 'remove', 'id': True}, {'cmd': 'pause', 'value': 'false'},
    {'cmd': 'speed', 'value': float('inf')}, {'cmd': 'preset', 'name': 'typo'},
    {'cmd': []},
])
def test_rejects_invalid_commands_atomically(server, msg):
    server.world.load_preset('binary')
    before = S.pack_state(server.world)
    with pytest.raises((ValueError, TypeError, OverflowError)):
        server.handle(msg, ('127.0.0.1', 12345))
    assert S.pack_state(server.world) == before


def test_udp_recovers_after_malformed_packets(server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(('127.0.0.1', 0))
        client.settimeout(2)
        for data in [b'\xff', b'{', b'[]', b'{"protocol":2,"cmd":"add","pos":[NaN,0,0]}',
                     b'[' * 1100, json.dumps({'cmd': 'hello', 'protocol': 2}).encode()]:
            client.sendto(data, server.sock.getsockname())
        deadline = time.monotonic() + 2
        while server.client is None and time.monotonic() < deadline:
            server.poll()
        assert json.loads(client.recv(4096))['protocol'] == S.PROTOCOL_VERSION
        server.send(S.pack_state(server.world))
        assert struct.unpack('<11f', client.recv(65535))[0] == 3
        server.handle({'cmd': 'bye'}, client.getsockname())
        assert server.client is None


def test_maximum_packet_and_event_backlog():
    w = W.World(max_bodies=W.MAX_BODIES)
    for i in range(w.max_bodies):
        w.add_body(W.ASTEROID, .00002, (i, 0, 0), (0, 0, 0))
    for _ in range(70):
        w._event(W.EV_MERGE, (1, 2, 3), 1, 2)
    data = S.pack_state(w)
    assert len(data) <= 65507
    values = np.frombuffer(data, dtype='<f4')
    assert values[4:6].tolist() == [W.MAX_BODIES, 64]
    assert len(w.events) == 6
    assert len(data) == 4 * (11 + 12 * W.MAX_BODIES + 8 * 64)


def test_prediction_wire_layout():
    data = S.pack_prediction(123, dict(points=[(1, 2, 3)], hit=True, attractor=42, vel=(4, 5, 6), radius=0.5))
    assert struct.unpack('<12f', data) == (4, 123, 1, 1, 42, 4, 5, 6, 0.5, 1, 2, 3)


def test_valid_command_sequence(server):
    addr = ('127.0.0.1', 12345)
    server.handle({'cmd': 'preset', 'name': 'empty'}, addr)
    server.handle({'cmd': 'add', 'type': 'star', 'pos': [0, 0, 0]}, addr)
    assert server.world.sim.N == 1
    server.handle({'cmd': 'add', 'type': 'rocky', 'pos': [100, 0, 0]}, addr)
    server.handle({'cmd': 'predict', 'type': 'rocky', 'pos': [200, 0, 0], 'req': 3}, addr)
    server.handle({'cmd': 'belt', 'pos': [150, 0, 0], 'count': 3}, addr)
    assert server.world.sim.N == 5
    server.handle({'cmd': 'pause', 'value': True}, addr)
    assert server.world.paused
    server.handle({'cmd': 'pause'}, addr)
    assert not server.world.paused
    server.handle({'cmd': 'speed', 'value': 3000}, addr)
    assert server.world.speed == 2000
    server.handle({'cmd': 'speed', 'value': -2}, addr)
    assert server.world.speed == .05
    server.handle({'cmd': 'remove', 'id': 2}, addr)
    assert server.world.sim.N == 4
    server.handle({'cmd': 'supernova', 'id': 1}, addr)
    assert W.EV_SUPERNOVA in [event[0] for event in server.world.events]
    server.handle({'cmd': 'clear'}, addr)
    assert server.world.sim.N == 0


def test_run_sends_state_and_exits_when_idle(server):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(('127.0.0.1', 0))
        client.settimeout(2)
        client.sendto(b'{"protocol":2,"cmd":"hello"}', server.sock.getsockname())
        server.world.notice('queued')
        server.exit_when_idle = .04
        server.run()
        assert json.loads(client.recv(4096))['type'] == 'info'
        assert struct.unpack('<11f', client.recv(65535))[0] == 3
        assert json.loads(client.recv(4096))['text'] == 'queued'
        assert server.sock.fileno() == -1


@pytest.mark.parametrize('args', [
    ['--max-bodies', '1322'], ['--port', '-1'], ['--exit-when-idle', 'nan'],
])
def test_cli_rejects_invalid_limits(monkeypatch, args):
    monkeypatch.setattr('sys.argv', ['server.py', *args])
    with pytest.raises(SystemExit) as result:
        S.main()
    assert result.value.code == 2
