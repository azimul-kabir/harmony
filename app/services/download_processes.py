"""Thread-safe lifecycle management for provider-owned download processes."""
import os
import signal
import subprocess
import threading


class DownloadProcessManager:
    def __init__(self, grace_seconds: float = 3.0) -> None:
        self._grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[str]] = {}
        self._shutting_down = False

    def register(self, job_id: int, process: subprocess.Popen[str]) -> bool:
        with self._lock:
            if self._shutting_down or job_id in self._processes:
                return False
            self._processes[job_id] = process
            return True

    def unregister(self, job_id: int, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._processes.get(job_id) is process:
                self._processes.pop(job_id, None)

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            process = self._processes.get(job_id)
        if process is None or process.poll() is not None:
            return False
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=self._grace_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=self._grace_seconds)
        except OSError:
            pass
        finally:
            self.unregister(job_id, process)
        return True

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._processes)
        for job_id in jobs:
            try:
                self.cancel(job_id)
            except OSError:
                continue

    def begin_shutdown(self) -> None:
        """Reject new registrations before taking the cancellation snapshot."""
        with self._lock:
            self._shutting_down = True
        self.cancel_all()


download_processes = DownloadProcessManager()
