from pathlib import Path


def test_library_watcher_source_compiles_without_importing_optional_dependency():
    """Catch syntax regressions even when Watchdog is unavailable in CI."""
    source = Path("app/services/library_watcher.py").read_text(encoding="utf-8")
    compile(source, "app/services/library_watcher.py", "exec")
