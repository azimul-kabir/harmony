"""Backward-compatible entry point for the canonical Library indexer."""

from pathlib import Path

from sqlalchemy.orm import Session

from app.services.library_scanner import ScanResult, scan_library as _scan_library


def scan_library(db: Session, library: Path) -> ScanResult:
    return _scan_library(db, root=library)
