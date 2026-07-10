from pydantic import BaseModel

from app.domain.queue import QueueStatus


class QueueResponse(BaseModel):
    job_id: int
    status: QueueStatus
