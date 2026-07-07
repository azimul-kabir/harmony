from enum import Enum


class TrackStatus(str, Enum):
    OWNED = "owned"
    MISSING = "missing"