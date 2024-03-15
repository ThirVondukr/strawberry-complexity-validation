from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, TypeVar

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
    IntValueNode,
    OperationDefinitionNode,
    ValidationContext,
    ValidationRule,
    VariableNode,
    VisitorAction,
)
from strawberry.schema.schema_converter import GraphQLCoreConverter
from strawberry.types import ExecutionContext

from ._context import (
    ComplexityResult,
    _complexity_var,
)
from ._directives import AnyCostDirective, Cost, ListCost

if TYPE_CHECKING:
    from ._extension import QueryComplexityExtension

T = TypeVar("T")

_STRAWBERRY_KEY = GraphQLCoreConverter.DEFINITION_BACKREF


def _find_extension(schema: GraphQLSchema) -> QueryComplexityExtension | None:
    from ._extension import QueryComplexityExtension

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
    multipliers: list[int] = dataclasses.field(default_factory=list)
    children: list[State | FragmentLateEval] = dataclasses.field(
        default_factory=list,
    )


GT = TypeVar("GT", bound=GraphQLType)


def _unwrap_graphql_node(
    node: GT | GraphQLWrappingType[GT],
) -> GT:
    while isinstance(node, GraphQLWrappingType):
        node = node.of_type
    return node


def default_cost_compare_key(directive: AnyCostDirective | None) -> int:
    if directive is None:
        return -1

    if isinstance(directive, ListCost):
        return _get_unset_value(directive.assumed_size, 0)

    return _get_unset_value(directive.complexity, 0)


def _get_cost_directive(
    schema: GraphQLSchema,
    node: GraphQLWrappingType[GraphQLNamedType] | GraphQLNamedType | None,
) -> AnyCostDirective | None:
    if not node:
        return None

    node = _unwrap_graphql_node(node)
    if isinstance(node, GraphQLInterfaceType):
        return max(
            (
                _get_cost_directive(schema, obj)
                for obj in schema.get_implementations(
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


def get_field_arguments(  # noqa: C901
    operation: OperationDefinitionNode | None,
    execution_context: ExecutionContext,
    node: FieldNode,
) -> Mapping[str, object]:
    result = {}
    for argument_node in node.arguments:
        argument_name = argument_node.name.value
        if isinstance(argument_node.value, IntValueNode):
            result[argument_name] = argument_node.value.value
            continue

        if not isinstance(argument_node.value, VariableNode):
            continue

        variable_name = argument_node.value.name.value
        if (
            execution_context.variables
            and variable_name in execution_context.variables
        ):
            result[argument_name] = execution_context.variables[variable_name]
            continue

        if operation:
            variable_definition = next(
                (
                    var
                    for var in operation.variable_definitions
                    if var.variable.name.value == variable_name
                ),
                None,
            )
            if not variable_definition or not isinstance(
                variable_definition.default_value,
                IntValueNode,
            ):
                continue
            result[argument_name] = variable_definition.default_value.value
            continue
    return result


def _add_field_variables_to_state(
    operation: OperationDefinitionNode | None,
    execution_context: ExecutionContext,
    node: FieldNode,
    state: State,
    cost: AnyCostDirective | None,
) -> None:
    if not isinstance(cost, ListCost) or not cost.arguments:
        return

    field_arguments = get_field_arguments(
        node=node,
        operation=operation,
        execution_context=execution_context,
    )
    for k, v in field_arguments.items():
        if k not in cost.arguments:
            continue
        if isinstance(v, str) and v.isnumeric():
            state.multipliers.append(int(v))
        if isinstance(v, int):
            state.multipliers.append(v)


class QueryComplexityValidationRule(ValidationRule):
    def __init__(self, context: ValidationContext) -> None:
        super().__init__(context)
        self.extension: QueryComplexityExtension = _find_extension(
            # type: ignore[assignment]
            context.schema,
        )
        self._state: list[State] = []
        self._fragments: MutableMapping[str, State] = {}

        self._operation_definitions: list[OperationDefinitionNode] = []

    @property
    def execution_context(self) -> ExecutionContext:
        return self.extension.execution_context

    @property
    def operation_definition(self) -> OperationDefinitionNode | None:
        if not self._operation_definitions:
            return None
        return self._operation_definitions[-1]

    def _enter(self, state: State, *, contributes_to_cost: bool = True) -> None:
        if contributes_to_cost:
            self._state[-1].children.append(state)
        self._state.append(state)

    def _leave(self) -> State:
        return self._state.pop()

    def enter_operation_definition(
        self,
        node: OperationDefinitionNode,
        *args: object,
    ) -> None:
        self._operation_definitions.append(node)

    def leave_operation_definition(self, *args: object) -> None:
        self._operation_definitions.pop()

    def _calculate_complexity(
        self,
        state: State,
        children_complexity: int,
    ) -> int:
        if isinstance(state.directive, ListCost):
            complexity = state.added_complexity + children_complexity
            return sum(
                complexity * mult
                for mult in state.multipliers
                or [_get_unset_value(state.directive.assumed_size, 0)]
            )

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

        directives = [
            _get_cost_directive(self.context.schema, def_)
            for def_ in definitions
        ]
        resolves_to_type_cost = _get_cost_directive(
            self.context.schema,
            self.context.get_type(),
        )

        cost = max(directives, key=default_cost_compare_key)

        state = State(directive=cost)

        _add_field_variables_to_state(
            self.operation_definition,
            execution_context=self.execution_context,
            node=node,
            state=state,
            cost=cost,
        )

        if resolves_to_type_cost and not isinstance(
            resolves_to_type_cost,
            ListCost,
        ):
            state.added_complexity += _get_unset_value(
                resolves_to_type_cost.complexity,
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
