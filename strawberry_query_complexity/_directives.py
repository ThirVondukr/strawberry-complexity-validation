import strawberry
from strawberry.schema_directive import Location


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
