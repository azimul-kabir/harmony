import threading
import time

import pytest
from sqlalchemy.exc import OperationalError

from app.database.crud_downloads import claim_next_job


class _EmptyQueueSession:
    def __init__(self, state=None):
        self.rolled_back = False
        self.state = state

    def execute(self, _statement):
        if self.state is None:
            raise OperationalError("BEGIN IMMEDIATE", (), Exception("database is locked"))
        with self.state["guard"]:
            self.state["active"] += 1
            self.state["maximum"] = max(self.state["maximum"], self.state["active"])
        time.sleep(0.02)
        with self.state["guard"]:
            self.state["active"] -= 1

    def scalar(self, _statement):
        return None

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back = True


def test_claim_rolls_back_when_begin_immediate_is_locked():
    db = _EmptyQueueSession()

    with pytest.raises(OperationalError, match="database is locked"):
        claim_next_job(db)

    assert db.rolled_back is True


def test_claim_transactions_are_serialized_between_download_workers():
    state = {
        "active": 0,
        "maximum": 0,
        "guard": threading.Lock(),
    }
    sessions = [_EmptyQueueSession(state), _EmptyQueueSession(state)]
    threads = [threading.Thread(target=claim_next_job, args=(session,)) for session in sessions]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state["maximum"] == 1

