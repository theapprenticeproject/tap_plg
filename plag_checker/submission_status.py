from enum import IntEnum

class SubmissionStatus(IntEnum):
    ERROR = 5
    SUBMITTED = 1
    EVALUATED = 2
    NOTIFIED = 3
    FAILED = 4