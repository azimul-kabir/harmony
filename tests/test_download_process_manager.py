import subprocess

from app.services.download_processes import DownloadProcessManager
from app.services import download_processes


class FakeProcess:
    def __init__(self, running=True, timeout=False):
        self.pid = 999999
        self.running = running
        self.timeout = timeout
        self.wait_calls = 0
    def poll(self): return None if self.running else 0
    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.timeout and self.wait_calls == 1:
            raise subprocess.TimeoutExpired("fake", timeout)
        self.running = False
        return 0


def test_register_unregister_and_unknown_cancel_are_safe():
    manager = DownloadProcessManager(0.01)
    first, second = FakeProcess(), FakeProcess()
    assert manager.register(1, first)
    assert not manager.register(1, second)
    manager.unregister(1, second)
    assert manager.cancel(1) is True
    assert manager.cancel(1) is False
    assert manager.cancel(404) is False


def test_graceful_and_forced_group_termination(monkeypatch):
    signals = []
    class Process:
        pid = 42
        def __init__(self, force=False): self.force, self.calls, self.running = force, 0, True
        def poll(self): return None if self.running else 0
        def wait(self, timeout=None):
            self.calls += 1
            if self.force and self.calls == 1: raise subprocess.TimeoutExpired("x", timeout)
            self.running = False
    monkeypatch.setattr(download_processes.os, "killpg", lambda pid, sig: signals.append(sig))
    manager = DownloadProcessManager(0.01)
    graceful = Process(); assert manager.register(1, graceful); assert manager.cancel(1)
    assert signals == [download_processes.signal.SIGTERM]
    forced = Process(force=True); assert manager.register(2, forced); assert manager.cancel(2)
    assert signals[-2:] == [download_processes.signal.SIGTERM, download_processes.signal.SIGKILL]


def test_process_lookup_race_is_cleaned_up(monkeypatch):
    class Process:
        pid = 4
        def poll(self): return None
    monkeypatch.setattr(download_processes.os, "killpg", lambda *_: (_ for _ in ()).throw(ProcessLookupError()))
    manager = DownloadProcessManager(); process = Process()
    assert manager.register(4, process)
    assert manager.cancel(4)
    assert not manager._processes


def test_shutdown_rejects_new_registration(monkeypatch):
    manager = DownloadProcessManager()
    monkeypatch.setattr(manager, "cancel_all", lambda: None)
    manager.begin_shutdown()
    assert not manager.register(9, FakeProcess())
