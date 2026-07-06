from pathlib import Path

from loguru import logger

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger.add(
    LOG_DIR / "harmony.log",
    rotation="10 MB",
    retention=10,
    enqueue=True,
)

__all__ = ["logger"]