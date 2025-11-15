from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional
import time
import json


class MessageStatus(Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED_MAX_RETRIES = "FAILED_MAX_RETRIES"


@dataclass
class Message:
    """Message to be sent via SMS"""
    message_id: str
    content: str
    metadata: Optional[dict] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass
class MessageState:
    """State tracking for message retry logic"""
    message_id: str
    message: Message
    attempt_count: int  # 0-6
    next_retry_at: float  # epoch timestamp
    status: MessageStatus
    created_at: float
    updated_at: float

    # Retry schedule in seconds from arrival
    RETRY_SCHEDULE = [0, 0.5, 2, 4, 8, 16]
    MAX_ATTEMPTS = 6

    def to_dict(self):
        return {
            'message_id': self.message_id,
            'message': self.message.to_dict(),
            'attempt_count': self.attempt_count,
            'next_retry_at': self.next_retry_at,
            'status': self.status.value,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            message_id=data['message_id'],
            message=Message.from_dict(data['message']),
            attempt_count=data['attempt_count'],
            next_retry_at=data['next_retry_at'],
            status=MessageStatus(data['status']),
            created_at=data['created_at'],
            updated_at=data['updated_at']
        )

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str):
        return cls.from_dict(json.loads(json_str))

    def calculate_next_retry_time(self):
        """Calculate next retry time based on attempt count"""
        if self.attempt_count >= self.MAX_ATTEMPTS:
            return None

        delay = self.RETRY_SCHEDULE[self.attempt_count]
        return self.created_at + delay

    def is_due(self, current_time: float) -> bool:
        """Check if message is due for retry"""
        return self.next_retry_at <= current_time and self.status == MessageStatus.PENDING