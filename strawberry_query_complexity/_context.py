import contextvars
import dataclasses
from contextvars import ContextVar


@dataclasses.dataclass(slots=True, kw_only=True)
class ComplexityResult:
    current: int
    max: int


_complexity_var: ContextVar[ComplexityResult] = contextvars.ContextVar(
    "__strawberry__complexity",
)
