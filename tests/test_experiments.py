import copy
import json
import time

import numpy as np
import pytest

import experiments as E
import server as S
import world as W


def scene():
    w = W.World(seed=41)
    w.load_preset('solar')
    w.advance(.01, time.perf_counter() + 1)
    w.paused = True
    w.speed = 25
    w.meta['1']['heat'] = .7
    return w, E.capture(w, dict(focus=[1, 2, 3], distance=240, pitch=.8, yaw=-1.2))


def test_disk_round_trip_restores_physics_and_random_state(tmp_path):
    original, data = scene()
    path = tmp_path / 'scene.gravity.json'
    E.save(path, data)
    saved, restored, camera = E.load(path)
    for key in ('m', 'r', 'xyz', 'v'):
        # Repartition can change array order, so compare bodies by persistent ID.
        left, right = original.snapshot(), restored.snapshot()
        a = np.argsort([int(n) for n in left['names']])
        b = np.argsort([int(n) for n in right['names']])
        np.testing.assert_array_equal(left[key][a], right[key][b])
    assert restored.meta == original.meta
    assert restored.sim.t == original.sim.t
    assert restored.speed == 25 and restored.paused
    assert restored._next_id == original._next_id
    assert restored.rng.getstate() == original.rng.getstate()
    assert camera == data['camera']
    assert saved['version'] == 1
    restored.paused = False
    restored.advance(.01, time.perf_counter() + 1)
    assert restored.sim.t > original.sim.t
    assert np.isfinite(restored.snapshot()['xyz']).all()


@pytest.mark.parametrize('change', [
    lambda d: d.update(version=2),
    lambda d: d.update(time=float('nan')),
    lambda d: d.update(paused='yes'),
    lambda d: d.update(next_id=1),
    lambda d: d.update(rng=[3, [], None]),
    lambda d: d.update(rng=[3, d['rng'][1], float('nan')]),
    lambda d: d['camera'].update(distance=-1),
    lambda d: d['bodies'][0].update(mass=-1),
    lambda d: d['bodies'][0].update(pos=[0, 1]),
    lambda d: d['bodies'][0].update(vel=[float('inf'), 0, 0]),
    lambda d: d['bodies'][1].update(id=d['bodies'][0]['id']),
    lambda d: d.update(max_bodies=1),
    lambda d: d.update(supernova_queue=[9999]),
])
def test_invalid_file_does_not_replace_live_world(tmp_path, change):
    w, data = scene()
    before = E.capture(w, E.DEFAULT_CAMERA)
    service = S.Server('127.0.0.1', 0, w)
    replies = []
    service.send_json = lambda reply, addr=None: replies.append(reply)
    try:
        change(data)
        path = tmp_path / 'bad.gravity.json'
        path.write_text(json.dumps(data))
        service.handle(dict(cmd='load_scene', path=str(path), request='bad'), ('127.0.0.1', 1234))
        assert not replies[-1]['ok']
        assert service.world is w
        assert E.capture(w, E.DEFAULT_CAMERA) == before
    finally:
        service.sock.close()


def test_atomic_save_preserves_existing_file_on_replace_failure(tmp_path, monkeypatch):
    _, data = scene()
    path = tmp_path / 'scene.gravity.json'
    path.write_text('existing save')
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr(E.os, 'replace', fail)
    with pytest.raises(OSError):
        E.save(path, data)
    assert path.read_text() == 'existing save'
    assert list(tmp_path.iterdir()) == [path]


def test_restart_and_retry_are_idempotent(tmp_path):
    w, data = scene()
    service = S.Server('127.0.0.1', 0, w)
    replies = []
    service.send_json = lambda reply, addr=None: replies.append(copy.deepcopy(reply))
    addr = ('127.0.0.1', 1234)
    try:
        path = tmp_path / 'scene.gravity.json'
        command = dict(cmd='save_scene', path=str(path), camera=data['camera'], request='save')
        service.handle(command, addr)
        checkpoint = copy.deepcopy(service.checkpoint)
        w.remove_body(1)
        service.handle(command, addr)  # retry must not overwrite the saved baseline
        assert service.checkpoint == checkpoint
        assert replies[-1]['ok']
        restart = dict(cmd='restart', request='restart')
        service.handle(restart, addr)
        assert service.world.sim.N == len(data['bodies'])
        assert service.world.meta == data_to_meta(data)
        restored = service.world
        restored.remove_body(1)
        service.handle(restart, addr)
        assert service.world is restored and restored.particle('1') is None
        service.handle(dict(cmd='restart', request='restart-again'), addr)
        assert service.world.particle('1') is not None
        assert replies[-1]['camera'] == data['camera']
    finally:
        service.sock.close()


def data_to_meta(data):
    return {str(b['id']): dict(type=b['type'], heat=b['heat'], born=b['born']) for b in data['bodies']}


def test_checkpoint_empty_and_preset_restart():
    service = S.Server('127.0.0.1', 0, W.World(seed=1))
    service.send_json = lambda *args: None
    addr = ('127.0.0.1', 1234)
    try:
        service.handle(dict(cmd='restart', request='empty'), addr)
        assert service.world.sim.N == 0
        service.handle(dict(cmd='preset', name='binary'), addr)
        baseline = E.capture(service.world, service.checkpoint['camera'])
        service.world.advance(.1, time.perf_counter() + 1)
        service.handle(dict(cmd='restart', request='preset'), addr)
        assert E.capture(service.world, service.checkpoint['camera']) == baseline
        service.handle(dict(cmd='checkpoint', camera=E.DEFAULT_CAMERA, request='checkpoint'), addr)
        assert service.checkpoint['camera'] == E.DEFAULT_CAMERA
    finally:
        service.sock.close()


def test_oversized_and_truncated_files(tmp_path):
    path = tmp_path / 'bad.gravity.json'
    path.write_bytes(b' ' * (E.MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match='too large'):
        E.load(path)
    path.write_text('{')
    with pytest.raises(ValueError):
        E.load(path)


@pytest.mark.parametrize('msg', [
    dict(cmd='restart', request=''),
    dict(cmd='checkpoint', request=1),
    dict(cmd='save_scene', request='save', path='bad\0path'),
    dict(cmd='load_scene', request='load', path=[]),
])
def test_reject_invalid_scene_commands(msg):
    from commands import validate
    with pytest.raises(ValueError):
        validate(msg)


@pytest.mark.parametrize('change', [
    lambda d: d.update(camera=None),
    lambda d: d['bodies'].__setitem__(0, None),
    lambda d: d.update(rng=[]),
    lambda d: d.update(supernova_queue='bad'),
])
def test_reject_invalid_scene_structure(change):
    _, data = scene()
    change(data)
    with pytest.raises(ValueError):
        E.restore(data)


def test_restore_pending_supernova_and_cached_gaussian():
    w = W.World(seed=7)
    bid = w.add_body(W.STAR, W.STAR_COLLAPSE, (0, 0, 0), (0, 0, 0))
    w._supernova_queue.append(bid)
    w.rng.gauss(0, 1)  # fills the Gaussian cache in Random's state
    data = E.capture(w, E.DEFAULT_CAMERA)
    restored, _ = E.restore(data)
    assert restored.rng.gauss(0, 1) == w.rng.gauss(0, 1)
    restored._post_tick(.01)
    assert restored.meta[str(bid)]['type'] == W.BLACK_HOLE
    assert not restored._supernova_queue


def test_save_rejects_oversized_payload_before_touching_file(tmp_path, monkeypatch):
    _, data = scene()
    monkeypatch.setattr(E, 'MAX_FILE_BYTES', 1)
    path = tmp_path / 'scene.gravity.json'
    path.write_text('old')
    with pytest.raises(ValueError, match='too large'):
        E.save(path, data)
    assert path.read_text() == 'old'


def test_save_cannot_create_temporary_file(tmp_path, monkeypatch):
    _, data = scene()
    def denied(**kwargs):
        raise PermissionError('read-only directory')
    monkeypatch.setattr(E.tempfile, 'NamedTemporaryFile', denied)
    with pytest.raises(PermissionError):
        E.save(tmp_path / 'scene.gravity.json', data)
    assert not list(tmp_path.iterdir())
