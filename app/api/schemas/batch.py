from pydantic import BaseModel


class BatchQueueResponse(BaseModel):
    queued: int
    skipped: int