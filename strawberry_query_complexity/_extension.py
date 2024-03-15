import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

from strawberry.extensions import SchemaExtension

from ._context import _complexity_var
from ._directives import AnyCostDirective
from ._validation import (
    QueryComplexityValidationRule,
    default_cost_compare_key,
)


@dataclasses.dataclass(kw_only=True)
class QueryComplexityConfig:
    cost_compare_key: Callable[[AnyCostDirective | None], int] = (
        default_cost_compare_key
    )


class QueryComplexityExtension(SchemaExtension):
    def __init__(
        self,
        *,
        max_complexity: int,
        default_cost: int = 0,
        report_complexity: bool = False,
    ) -> None:
        self.max_complexity = max_complexity
        self.default_complexity = default_cost
        self.report_complexity = report_complexity

    def on_operation(self) -> Iterator[None]:
        self.execution_context.validation_rules = (
            *self.execution_context.validation_rules,
            QueryComplexityValidationRule,
        )
        yield

    def get_results(self) -> dict[str, Any]:
        if not self.report_complexity:
            return {}

        try:
            result = _complexity_var.get()
        except LookupError:  # pragma: no cover
            return {}

        return {
            "complexity": {
                "current": result.current,
                "max": result.max,
            },
        }
