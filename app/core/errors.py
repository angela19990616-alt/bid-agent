from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
