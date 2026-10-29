"""Benchmark output stays interpretable and failed accuracy gates fail the CLI."""
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tools import benchmark, dev


def test_summary_retains_latency_outliers_and_empty_samples():
    assert benchmark.summary([]) == dict(count=0, p50_ms=None, p95_ms=None, max_ms=None)
    result = benchmark.summary([.001] * 99 + [.1])
    assert result['p50_ms'] == 1 and result['max_ms'] == 100


def test_seeded_workload_and_separate_accounting():
    first = benchmark.workload('solar', 2, 7)
    second = benchmark.workload('solar', 2, 7, audit=True)
    assert first['initial_bodies'] == second['initial_bodies'] == 73
    assert first['advance']['count'] == 2 and first['forecast']['count'] == 1
    assert first['initial_tracers'] == 0
    assert 'accounting' not in first and 'accounting' in second
    assert second['accounting']['initial']['tracers'] == 0
    assert first['requested_simulated_time'] == pytest.approx(1 / 30)


def test_profile_reports_native_integration_and_forecast():
    report = benchmark.profile_workload('binary', 2, 42)
    phases = {item['phase'] for item in report['phases']}
    assert {'integration_including_collision_callbacks', 'tides', 'forecast', 'packing'} <= phases


def test_physical_inventory_reports_unknown_energy_and_supported_smash():
    import world as W
    w=W.World(seed=42)
    w.load_preset('smash')
    assert benchmark.physical_inventory(w)['available']
    w.meta['1']['inventory']=None
    assert not benchmark.physical_inventory(w)['available']
    w.load_preset('smash')
    w.sim.particles[1].x=w.sim.particles[0].x
    assert not benchmark.physical_inventory(w)['available']


@pytest.mark.parametrize('passed, expected', [(True, 0), (False, 1)])
def test_cli_writes_accuracy_failures_and_returns_status(tmp_path, monkeypatch, passed, expected):
    monkeypatch.setattr(benchmark, 'run_accuracy', lambda: [dict(name='reference', passed=passed, errors={'position': 1})])
    monkeypatch.setattr(benchmark, 'metadata', lambda: {})
    path = tmp_path / 'report.json'
    assert benchmark.main(['--accuracy-only', '--output', str(path)]) == expected
    assert json.loads(path.read_text())['accuracy'][0]['passed'] is passed
    assert json.loads(path.read_text())['runs'] == []


def test_cli_runs_selected_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, 'run_accuracy', lambda: [])
    monkeypatch.setattr(benchmark, 'metadata', lambda: {})
    path = tmp_path / 'report.json'
    assert benchmark.main(['--scenario', 'smash', '--ticks', '1', '--repeats', '1', '--profile', '--output', str(path)]) == 0
    report = json.loads(path.read_text())
    assert len(report['runs']) == len(report['accounting_runs']) == len(report['profiles']) == 1
    assert report['runs'][0]['scenario'] == 'smash'


@pytest.mark.parametrize('flag,value', [('--ticks', '0'), ('--ticks', '3601'), ('--repeats', '0'), ('--repeats', '11')])
def test_cli_rejects_invalid_workload(flag, value):
    with pytest.raises(SystemExit):
        benchmark.main([flag, value])


def test_dev_forwards_benchmark_paths_without_shell_interpretation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(dev, 'PYTHON', tmp_path / 'python')
    dev.PYTHON.touch()
    monkeypatch.setattr(dev, 'run', lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(sys, 'argv', ['dev.py', 'benchmark', '--output', 'path with spaces.json'])
    dev.main()
    assert calls[0][-2:] == ['--output', 'path with spaces.json']
    monkeypatch.setattr(sys, 'argv', ['dev.py', 'accuracy'])
    dev.main()
    assert calls[1][-1] == '--accuracy-only'


def test_hardware_probe_failure_is_explicit(monkeypatch):
    monkeypatch.setattr(benchmark.sys, 'platform', 'win32')
    def fail(*args, **kwargs):
        raise OSError('probe unavailable')
    monkeypatch.setattr(benchmark.subprocess, 'check_output', fail)
    assert benchmark.hardware()['ram_bytes'] is None


def test_rendered_benchmark_rejects_missing_display(monkeypatch):
    monkeypatch.setattr(dev.sys, 'platform', 'linux')
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    with pytest.raises(RuntimeError, match='headless timings are invalid'):
        dev.visual_benchmark([])


@pytest.fixture
def render_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(dev.sys, 'platform', 'win32')
    monkeypatch.setenv('GODOT', 'godot')
    monkeypatch.setattr(dev, 'PYTHON', tmp_path / 'python')
    dev.PYTHON.touch()
    process = Mock(pid=1234)
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(dev.subprocess, 'Popen', launch)
    sockets = []
    def socket(*args):
        instance = Mock()
        instance.recvfrom.return_value = (b'{"pid":1234}', ('127.0.0.1', 47810))
        instance.__enter__ = Mock(return_value=instance)
        instance.__exit__ = Mock(return_value=False)
        sockets.append(instance)
        return instance
    monkeypatch.setattr(dev.socket, 'socket', socket)
    return process, launch, sockets


def test_rendered_benchmark_owns_seeded_server_and_cleans_up(tmp_path, monkeypatch, render_environment):
    process, launch, sockets = render_environment
    path = tmp_path / 'render.json'
    def render(command, timeout):
        assert timeout == 152
        destination = next(arg.split('=', 1)[1] for arg in command if arg.startswith('--benchmark='))
        assert Path(destination) == path
        path.write_text(json.dumps(dict(format='gravity-render-baseline', display='windows',
                                       frame_intervals_ms={'p95': 20}, average_fps=55)))
        return 'Rendered benchmark complete: test'
    monkeypatch.setattr(dev, 'run', render)
    dev.visual_benchmark(['solar', '--seconds', '2', '--seed', '91', '--output', str(path)])
    assert launch.call_args.args[0][-2:] == ['--seed', '91']
    assert len(sockets) == 2
    process.terminate.assert_called_once()
    process.wait.assert_called_once()


def test_render_failure_and_timeout_still_clean_up(tmp_path, monkeypatch, render_environment):
    process, _launch, _sockets = render_environment
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired('godot', 45)
    monkeypatch.setattr(dev, 'run', fail)
    process.wait.side_effect = [subprocess.TimeoutExpired('server', 5), 0]
    with pytest.raises(subprocess.TimeoutExpired):
        dev.visual_benchmark(['--output', str(tmp_path / 'failed.json')])
    process.terminate.assert_called_once()
    process.kill.assert_called_once()


def test_existing_render_report_is_not_reused(tmp_path, render_environment):
    _process, launch, _sockets = render_environment
    path = tmp_path / 'old.json'
    path.write_text('old evidence')
    with pytest.raises(RuntimeError, match='existing file'):
        dev.visual_benchmark(['--output', str(path)])
    launch.assert_not_called()
    assert path.read_text() == 'old evidence'


def test_busy_port_does_not_launch_or_stop_existing_server(tmp_path, monkeypatch, render_environment):
    _process, launch, _sockets = render_environment
    def occupied(*args, **kwargs):
        raise OSError('port already bound')
    original = dev.socket.socket
    def socket(*args):
        sock = original(*args)
        sock.bind.side_effect = occupied
        return sock
    monkeypatch.setattr(dev.socket, 'socket', socket)
    with pytest.raises(RuntimeError, match='Close the running simulator'):
        dev.visual_benchmark(['--output', str(tmp_path / 'unused.json')])
    launch.assert_not_called()


def test_server_identity_must_match_child(tmp_path, monkeypatch, render_environment):
    process, _launch, _sockets = render_environment
    original = dev.socket.socket
    def socket(*args):
        sock = original(*args)
        sock.recvfrom.return_value = (b'{"pid":9999}', ('127.0.0.1', 47810))
        return sock
    monkeypatch.setattr(dev.socket, 'socket', socket)
    clock = iter([0, 6])
    monkeypatch.setattr(dev.time, 'monotonic', lambda: next(clock))
    run = Mock()
    monkeypatch.setattr(dev, 'run', run)
    with pytest.raises(RuntimeError, match='verify'):
        dev.visual_benchmark(['--output', str(tmp_path / 'unused.json')])
    run.assert_not_called()
    process.terminate.assert_called_once()
