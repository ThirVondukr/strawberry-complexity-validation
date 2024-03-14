from collections.abc import Sequence

import strawberry
from strawberry import Schema
from strawberry_query_complexity import Cost, ListCost, QueryComplexityExtension

MAX_COMPLEXITY = 200
BOOKS_ASSUMED_SIZE = 10


@strawberry.type(directives=[Cost(complexity=1)])
class Author:
    id: strawberry.ID
    name: str = strawberry.field(directives=[Cost(complexity=1)])


@strawberry.interface
class Press:
    title: str


@strawberry.type(directives=[Cost(complexity=1)])
class Book(Press):
    id: strawberry.ID
    title: str = strawberry.field(directives=[Cost(complexity=1)])
    authors: Sequence[Author] = strawberry.field(
        directives=[ListCost(assumed_size=2)],
    )


@strawberry.type(directives=[Cost(complexity=1)])
class Magazine(Press):
    id: strawberry.ID
    title: str = strawberry.field(directives=[Cost(complexity=2)])


@strawberry.type
class Query:
    @strawberry.field(
        directives=[Cost(complexity=MAX_COMPLEXITY + 1)],
    )  # type: ignore[misc]
    def exceeds_max_complexity(self) -> None:
        return None

    @strawberry.field(directives=[Cost(complexity=MAX_COMPLEXITY)])  # type: ignore[misc]
    def ok(self) -> None:
        return None

    @strawberry.field(directives=[ListCost(assumed_size=BOOKS_ASSUMED_SIZE, arguments=["limit"])])  # type: ignore[misc]
    def books(
        self,
        limit: int | None = None,  # noqa: ARG002
    ) -> Sequence[Book]:
        return []

    @strawberry.field(directives=[ListCost(assumed_size=BOOKS_ASSUMED_SIZE, arguments=["limit"])])  # type: ignore[misc]
    def press(
        self,
        limit: int | None = None,  # noqa: ARG002
    ) -> Sequence[Press]:
        return []


schema = Schema(
    query=Query,
    extensions=[
        QueryComplexityExtension(
            max_complexity=MAX_COMPLEXITY,
            report_complexity=True,
        ),
    ],
    types=[Magazine],
)


def test_field_exceeds_max_complexity() -> None:
    query = """
    query {
        exceedsMaxComplexity
    }
    """
    result = schema.execute_sync(query=query)
    assert result.errors
    assert result.errors[0].extensions == {
        "complexity": {
            "max": MAX_COMPLEXITY,
            "current": MAX_COMPLEXITY + 1,
        },
    }
