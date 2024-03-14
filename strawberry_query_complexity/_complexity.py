import contextvars
import dataclasses
import typing
from collections.abc import Callable, Iterator, MutableMapping
from contextvars import ContextVar
from typing import Any, TypeVar

import strawberry
from graphql import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLError,
    GraphQLInterfaceType,
    GraphQLNamedType,
    GraphQLSchema,
    GraphQLType,
    GraphQLUnionType,
    GraphQLWrappingType,
    ValidationContext,
    ValidationRule,
    VisitorAction,
)
from strawberry.extensions import SchemaExtension
from strawberry.schema.schema_converter import GraphQLCoreConverter
from strawberry.schema_directive import Location

T = TypeVar("T")


@strawberry.schema_directive(
    name="cost",
    locations=[Location.FIELD_DEFINITION, Location.OBJECT],
)
class Cost:
    complexity: int | None = strawberry.UNSET


@strawberry.schema_directive(
    name="listCost",
    locations=[Location.FIELD_DEFINITION],
)
class ListCost:
    assumed_size: int | None = strawberry.UNSET
    arguments: list[str] | None = strawberry.UNSET
    sized_fields: list[str] | None = strawberry.UNSET


AnyCostDirective = Cost | ListCost

_STRAWBERRY_KEY = GraphQLCoreConverter.DEFINITION_BACKREF


def _find_extension(schema: GraphQLSchema) -> "QueryComplexityExtension | None":
    strawberry_schema: strawberry.Schema = schema.extensions[_STRAWBERRY_KEY]
    for extension in strawberry_schema.extensions:
        if isinstance(extension, QueryComplexityExtension):
            return extension
    return None


def _get_unset_value(value: T | None, default: T) -> T:
    if value is None or value is strawberry.UNSET:
        return default
    return value


@dataclasses.dataclass(kw_only=True, slots=True)
class FragmentLateEval:
    name: str


@dataclasses.dataclass(kw_only=True, slots=True)
class State:
    directive: AnyCostDirective | None = None
    added_complexity: int = 0
    children: list["State | FragmentLateEval"] = dataclasses.field(
        default_factory=list,
    )


GT = TypeVar("GT", bound=GraphQLType)


def _unwrap_graphql_node(
    node: GT | GraphQLWrappingType[GT] | None,
) -> GT | None:
    while isinstance(node, GraphQLWrappingType):
        node = node.of_type
    return node


def default_cost_compare_key(directive: AnyCostDirective | None) -> int:
    if directive is None:
        return -1

    if isinstance(directive, ListCost):
        return _get_unset_value(directive.assumed_size, 0)

    return _get_unset_value(directive.complexity, 0)


@dataclasses.dataclass(slots=True, kw_only=True)
class ComplexityResult:
    current: int
    max: int


class QueryComplexityValidationRule(ValidationRule):
    def __init__(self, context: ValidationContext) -> None:
        super().__init__(context)
        self.extension: QueryComplexityExtension = _find_extension(
            # type: ignore[assignment]
            context.schema,
        )
        self._state: list[State] = []
        self._fragments: MutableMapping[str, State] = {}

    def _enter(self, state: State, *, contributes_to_cost: bool = True) -> None:
        if contributes_to_cost:
            self._state[-1].children.append(state)
        self._state.append(state)

    def _leave(self) -> State:
        return self._state.pop()

    def _calculate_complexity(
        self,
        state: State,
        children_complexity: int,
    ) -> int:
        if isinstance(state.directive, ListCost):
            return (
                state.added_complexity + children_complexity
            ) * _get_unset_value(state.directive.assumed_size, 0)

        if isinstance(state.directive, Cost):
            return (
                _get_unset_value(
                    state.directive.complexity,
                    default=self.extension.default_complexity,
                )
                + children_complexity
            )

        return self.extension.default_complexity + children_complexity

    def _resolve_complexity(self, state: State | FragmentLateEval) -> int:
        if isinstance(state, FragmentLateEval):
            state = self._fragments[state.name]

        children_complexity = sum(
            self._resolve_complexity(c) for c in state.children
        )

        return self._calculate_complexity(
            state=state,
            children_complexity=children_complexity,
        )

    def _find_cost_directive(
        self,
        node: GraphQLWrappingType[GraphQLNamedType] | GraphQLNamedType | None,
    ) -> AnyCostDirective | None:
        node = _unwrap_graphql_node(node)
        if not node:
            return None

        if isinstance(node, GraphQLInterfaceType):
            return max(
                (
                    self._find_cost_directive(obj)
                    for obj in self.context.schema.get_implementations(
                        node,
                    ).objects
                ),
                key=default_cost_compare_key,
            )

        for extension in node.extensions.values():
            for directive in extension.directives:
                if isinstance(directive, typing.get_args(AnyCostDirective)):
                    return directive  # type: ignore[no-any-return]
        return None

    def enter_document(self, node: DocumentNode, *args: object) -> None:
        if self.extension is None:
            # Issue a warning?
            return self.BREAK  # type: ignore[unreachable]
        self._enter(State(), contributes_to_cost=False)
        return None

    def leave_document(self, node: DocumentNode, *args: object) -> None:
        state = self._leave()
        assert not self._state  # noqa: S101
        complexity = self._resolve_complexity(state)
        _complexity_var.set(
            ComplexityResult(
                current=complexity,
                max=self.extension.max_complexity,
            ),
        )

        if complexity > self.extension.max_complexity:
            self.report_error(
                GraphQLError(
                    f"Complexity of {complexity} is greater than max complexity of {self.extension.max_complexity}",
                    extensions={
                        "complexity": {
                            "current": complexity,
                            "max": self.extension.max_complexity,
                        },
                    },
                ),
            )

    def enter_field(  # noqa: C901
        self,
        node: FieldNode,
        *args: object,
    ) -> VisitorAction:
        field_name = node.name.value
        if field_name.startswith("__"):
            return self.SKIP

        # Probably an invalid query
        if (parent_type := self.context.get_parent_type()) is None:
            return self.SKIP

        if isinstance(parent_type, GraphQLUnionType):
            return None

        if field_name not in parent_type.fields:
            return None

        if isinstance(parent_type, GraphQLInterfaceType):
            definitions = [
                obj.fields[field_name]
                for obj in self.context.schema.get_implementations(
                    parent_type,
                ).objects
            ]
        else:
            definitions = [parent_type.fields[field_name]]

        directives = [self._find_cost_directive(def_) for def_ in definitions]
        resolves_to_cost = self._find_cost_directive(self.context.get_type())
        cost = max(directives, key=default_cost_compare_key)

        state = State(directive=cost)
        if resolves_to_cost and not isinstance(resolves_to_cost, ListCost):
            state.added_complexity += _get_unset_value(
                resolves_to_cost.complexity,
                0,
            )
        self._enter(state)
        return None

    def leave_field(self, node: FieldNode, *args: object) -> None:
        self._leave()

    def enter_fragment_definition(
        self,
        node: FragmentDefinitionNode,
        *_args: object,
    ) -> None:
        state = State()
        self._fragments[node.name.value] = state
        self._enter(state, contributes_to_cost=False)

    def leave_fragment_definition(
        self,
        node: FragmentDefinitionNode,
        *_args: object,
    ) -> None:
        self._leave()

    def enter_fragment_spread(
        self,
        node: FragmentSpreadNode,
        *_args: object,
    ) -> None:
        fragment = self.context.get_fragment(node.name.value)
        if not fragment:
            return

        self._state[-1].children.append(
            FragmentLateEval(name=fragment.name.value),
        )


_complexity_var: ContextVar[ComplexityResult] = contextvars.ContextVar(
    "__strawberry__complexity",
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
        except LookupError:
            return {}

        return {
            "complexity": {
                "current": result.current,
                "max": result.max,
            },
        }
