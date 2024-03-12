import pytest
import strawberry
from strawberry import Schema
from strawberry_query_complexity import Cost, QueryComplexityExtension

MAX_COMPLEXITY = 100


@strawberry.type
class Multiplied:
    a: None = None
    b: None = None
    c: None = None


@strawberry.type
class Query:
    @strawberry.field(extensions=[Cost(complexity=MAX_COMPLEXITY + 1)])  # type: ignore[misc]
    def very_complex(self) -> None:
        return None

    @strawberry.field(extensions=[Cost(multiplier=34, complexity=0)])  # type: ignore[misc]
    def multiplier_err(self) -> Multiplied:
        return Multiplied()

    @strawberry.field(extensions=[Cost(multiplier=33, complexity=0)])  # type: ignore[misc]
    def multiplier_ok(self) -> Multiplied:
        return Multiplied()


schema = Schema(
    query=Query,
    extensions=[
        QueryComplexityExtension(max_complexity=MAX_COMPLEXITY, default_cost=1),
    ],
)


def test_field_too_complex() -> None:
    query = """
    query {
        veryComplex
    }
    """
    result = schema.execute_sync(query=query)
    assert result.errors
    assert result.errors[0].extensions == {
        "QUERY_COMPLEXITY": {
            "MAX": MAX_COMPLEXITY,
            "CURRENT": MAX_COMPLEXITY + 1,
        },
    }


@pytest.mark.parametrize(
    "query",
    [
        """
        fragment F on Multiplied {
            a
            b
            c
        }
        query {
            multiplierErr {
                ... F
            }
        }
        """,
        """
       query {
           multiplierErr {
               a
               b
               c
           }
       }
       """,
    ],
)
def test_multiplier(query: str) -> None:

    result = schema.execute_sync(query=query)
    assert result.errors
    assert result.errors[0].extensions == {
        "QUERY_COMPLEXITY": {
            "MAX": MAX_COMPLEXITY,
            "CURRENT": 34 * 3,
        },
    }


def test_multiplier_ok() -> None:
    query = """
    query {
        multiplierOk {
            a
            b
            c
        }
    }
    """
    result = schema.execute_sync(query=query)
    assert not result.errors
