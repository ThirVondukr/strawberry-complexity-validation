import strawberry
from graphql.utilities import get_introspection_query
from strawberry import Schema
from strawberry_query_complexity import Cost, QueryComplexityExtension


def test_sdl_query() -> None:
    query = get_introspection_query()

    @strawberry.type
    class Query:
        @strawberry.field(directives=[Cost(complexity=1)])  # type: ignore[misc]
        def exceeds_max_complexity(self) -> None:
            return None

    schema = Schema(
        query=Query,
        extensions=[
            QueryComplexityExtension(max_complexity=1, default_cost=1),
        ],
    )

    result = schema.execute_sync(query)
    assert not result.errors
    assert not result.extensions
