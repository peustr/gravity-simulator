"""Deterministic fault injection at OS boundaries, with real command handling."""
import builtins
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock

import numpy as np
import pytest

import server as S
import world as W

ADDRESS = ('127.0.0.1', 12345)


@pytest.fixture
def service(monkeypatch):
    sock = Mock()
    monkeypatch.setattr(S.socket, 'socket', Mock(return_value=sock))
    return S.Server('127.0.0.1', 0, W.World(seed=1))


@pytest.mark.parametrize('ioctl_error', [None, OSError('unsupported'), ValueError('unsupported')])
def test_optional_socket_tuning_failure_still_binds(monkeypatch, ioctl_error):
    sock = Mock()
    sock.setsockopt.side_effect = OSError('buffer denied')
    sock.ioctl.side_effect = ioctl_error
    monkeypatch.setattr(S.socket, 'socket', Mock(return_value=sock))
    monkeypatch.setattr(S.socket, 'SIO_UDP_CONNRESET', 123, raising=False)
    instance = S.Server('127.0.0.1', 0, W.World())
    assert instance.sock is sock
    sock.ioctl.assert_called_once_with(123, False)
    sock.bind.assert_called_once_with(('127.0.0.1', 0))
    sock.setblocking.assert_called_once_with(False)


def test_bind_failure_closes_socket_and_explains_recovery(monkeypatch, capsys):
    sock = Mock()
    sock.bind.side_effect = OSError('address in use')
    monkeypatch.setattr(S.socket, 'socket', Mock(return_value=sock))
    with pytest.raises(SystemExit) as exc:
        S.Server('127.0.0.1', 0, W.World())
    assert exc.value.code == 2
    sock.close.assert_called_once()
    assert 'another copy' in capsys.readouterr().out


def test_send_without_client_and_failed_send_are_harmless(service):
    service.send(b'ignored')
    service.sock.sendto.assert_not_called()
    service.sock.sendto.side_effect = OSError('peer gone')
    service.send(b'state', ADDRESS)
    service.sock.sendto.assert_called_once_with(b'state', ADDRESS)


@pytest.mark.parametrize('ending', [OSError('closed'), InterruptedError()])
def test_receive_reset_continues_until_socket_unavailable(service, ending):
    service.sock.recvfrom.side_effect = [ConnectionResetError(), (b'{"cmd":"hello"}', ADDRESS), ending]
    service.poll()
    assert service.client == ADDRESS
    assert service.sock.recvfrom.call_count == 3
    assert json.loads(service.sock.sendto.call_args.args[0])['type'] == 'info'


def test_poll_is_bounded_and_other_client_cannot_disconnect(service):
    service.client = ADDRESS
    before = service.last_heard
    service.sock.recvfrom.return_value = (b'{"cmd":"bye"}', ('127.0.0.1', 9999))
    service.poll()
    assert service.sock.recvfrom.call_count == 500
    assert service.client == ADDRESS and service.last_heard == before


def test_poll_reports_bad_commands_and_recovers_from_handler_failure(service, monkeypatch, capsys):
    service.verbose = True
    service.sock.recvfrom.side_effect = [
        (b'{"cmd":"speed","value":"bad"}', ADDRESS),
        (b'{"cmd":"clear"}', ADDRESS),
        (b'{"cmd":"hello"}', ADDRESS),
        (b'{"cmd":"hello"}', ADDRESS), BlockingIOError()]
    monkeypatch.setattr(service.world, 'clear', Mock(side_effect=RuntimeError('injected failure')))
    service.poll()
    output = capsys.readouterr()
    assert 'Rejected invalid command' in output.out
    assert 'command:' in output.out
    assert 'injected failure' in output.err
    assert output.out.count('Godot connected') == 1
    assert service.client == ADDRESS


def test_loop_disconnects_stale_client_drops_old_events_and_stops(service, monkeypatch, capsys):
    service.client = ADDRESS
    service.last_heard = 0
    polls = 0
    def poll():
        nonlocal polls
        polls += 1
        if polls == 3:
            raise KeyboardInterrupt
        service.world.notice('queued')
        service.world._event(W.EV_MERGE, (0, 0, 0), 1, 1)
    service.poll = poll
    monkeypatch.setattr(service.world, 'advance', Mock())
    clock = iter([0, .1, .2, .3, .4, .5, .6])
    monkeypatch.setattr(S.time, 'perf_counter', lambda: next(clock))
    monkeypatch.setattr(S.time, 'monotonic', lambda: 4)
    select = Mock()
    monkeypatch.setattr(S.select, 'select', select)
    service.run()
    assert service.client is None
    assert not service.world.events and not service.world.notices
    select.assert_not_called()  # overdue ticks must not sleep
    service.sock.close.assert_called_once()
    output = capsys.readouterr().out
    assert 'Lost contact' in output and 'Stopped.' in output


def test_packet_fallback_for_missing_metadata():
    w = W.World()
    bid = w.add_body(W.ROCKY, .003, (0, 0, 0), (0, 0, 0))
    w.meta.pop(str(bid))
    body = np.frombuffer(S.pack_state(w), dtype='<f4')[10:]
    assert body[1] == W.ASTEROID
    assert body[10:].tolist() == [0, 0]


def test_scene_reply_cache_is_bounded(service):
    for request in range(65):
        service.handle(dict(cmd='restart', request=str(request)), ADDRESS)
    assert len(service.scene_replies) == 64
    assert (ADDRESS, '0') not in service.scene_replies
    assert service.scene_replies[(ADDRESS, '64')]['ok']


def test_cli_selftest_propagates_status(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['server.py', '--selftest'])
    monkeypatch.setattr(S, 'selftest', lambda: 7)
    with pytest.raises(SystemExit) as exc:
        S.main()
    assert exc.value.code == 7


def test_cli_entrypoint_runs_and_writes_log(tmp_path, monkeypatch):
    path = tmp_path / 'server.log'
    monkeypatch.setattr(sys, 'argv', ['server.py', '--port', '0', '--exit-when-idle', '.001', '--log', str(path)])
    stdout, stderr = sys.stdout, sys.stderr
    try:
        runpy.run_path(str(Path(S.__file__)), run_name='__main__')
    finally:
        log = sys.stdout
        sys.stdout, sys.stderr = stdout, stderr
        if log is not stdout:
            log.close()
    assert 'Physics server listening' in path.read_text()
    assert 'exiting' in path.read_text()


def test_missing_dependency_reports_setup_instructions(monkeypatch, capsys):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'numpy':
            raise ImportError('numpy unavailable')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(S.__file__)), run_name='__main__')
    assert exc.value.code == 1
    assert 'pip install -r requirements.txt' in capsys.readouterr().out
