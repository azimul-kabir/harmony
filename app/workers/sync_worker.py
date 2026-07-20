import time
import threading
from app.core.logging import logger
from app.database.session import SessionLocal
from app.services.sync_checker import check_sync_status
from app.services.scan_manager import scan_manager

def background_sync_loop():
    logger.info("Background Navidrome sync worker started.")
    while True:
        db = SessionLocal()
        try:
            status = check_sync_status(db)
            if status.get("connected") and status.get("online"):
                delta = status.get("delta", 0)
                if delta > 0:
                    logger.info(f"Sync mismatch detected: Harmony has {delta} more tracks than Navidrome. Triggering scan...")
                    scan_manager.mark_pending()
        except Exception as e:
            logger.error(f"Error in background sync worker: {e}")
        finally:
            db.close()

        # Sleep for an hour
        time.sleep(3600)

def start_sync_worker():
    thread = threading.Thread(
        target=background_sync_loop,
        daemon=True,
        name="navidrome-sync-worker"
    )
    thread.start()
