import asyncio
import time
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.core.logging import logger
from app.services.settings_service import get_settings_by_category
from app.services import subsonic
from app.database.models import ScanHistory

class ScanManager:
    def __init__(self):
        import threading
        self.last_activity_time = 0
        self.scan_pending = False
        self.debounce_seconds = 15
        self.task_running = False
        self._lock = threading.Lock()

    def mark_pending(self):
        """Called whenever a download worker finishes importing a track."""
        with self._lock:
            self.last_activity_time = time.time()
            self.scan_pending = True

            if not self.task_running:
                self.task_running = True
                import threading
                threading.Thread(target=self._debounce_loop, daemon=True).start()

    def _debounce_loop(self):
        logger.info("Scan debounce loop started.")
        while self.scan_pending:
            time_since_last_activity = time.time() - self.last_activity_time
            if time_since_last_activity >= self.debounce_seconds:
                # Time's up, trigger the scan
                logger.info(f"No activity for {self.debounce_seconds}s. Triggering Navidrome scan...")
                self.scan_pending = False
                self._trigger_scan_sync()
                break
            else:
                # Sleep a bit and check again
                time.sleep(1)
        self.task_running = False
        logger.info("Scan debounce loop finished.")

    def _trigger_scan_sync(self):
        # We run this in a background task, so we need our own DB session
        db = SessionLocal()
        try:
            settings = get_settings_by_category(db, "navidrome")

            if not settings.get("navidrome_connected"):
                logger.info("Navidrome not connected, skipping scan.")
                return

            url = settings.get("navidrome_url")
            username = settings.get("navidrome_username")
            token = settings.get("navidrome_token")
            salt = settings.get("navidrome_salt")

            success = subsonic.trigger_scan(url, username, token=token, salt=salt)

            if success:
                history = ScanHistory(
                    trigger_type="automatic",
                    status="success",
                    details="Automatic scan triggered successfully after download batch."
                )
            else:
                history = ScanHistory(
                    trigger_type="automatic",
                    status="failed",
                    error_message="Failed to trigger scan"
                )

            db.add(history)
            db.commit()
        except Exception as e:
            logger.error(f"Error triggering Navidrome scan: {e}")
            history = ScanHistory(
                trigger_type="automatic",
                status="failed",
                error_message=str(e)
            )
            db.add(history)
            db.commit()
        finally:
            db.close()

# Global singleton
scan_manager = ScanManager()
