import subprocess
import sys

import pytest

from tools import dev, docs


def test_runner_propagates_failure():
    with pytest.raises(SystemExit) as result:
        dev.run([sys.executable, '-c', 'raise SystemExit(7)'])
    assert result.value.code == 7


def test_runner_times_out():
    with pytest.raises(subprocess.TimeoutExpired):
        dev.run([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=.05)


def test_docs_check_rejects_stale_output(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, 'ROOT', tmp_path)
    (tmp_path / 'docs').mkdir()
    monkeypatch.setattr(sys, 'argv', ['docs.py'])
    docs.main()
    monkeypatch.setattr(sys, 'argv', ['docs.py', '--check'])
    docs.main()
    (tmp_path / 'docs/runtime-reference.md').write_text('outdated', encoding='utf-8')
    with pytest.raises(SystemExit, match='stale'):
        docs.main()
