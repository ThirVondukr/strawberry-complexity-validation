import pytest
from strawberry import Schema
from strawberry_query_complexity import QueryComplexityExtension

from tests.test_complexity import (
    BOOKS_ASSUMED_SIZE,
    MAX_COMPLEXITY,
    Magazine,
    Query,
)

_BOOKS_WITH_AUTHORS = """query {
  books {
    __typename
    id
    authors {
      __typename
      id
    }
  }
}"""

_BOOKS_WITH_AUTHORS_AND_ADDITIONAL_FIELDS = """query {
  books {
    __typename
    id
    title
    authors {
      __typename
      id
      name
    }
  }
}"""

_ADDITIONAL_FIELDS_USING_FRAGMENTS = """query  {
  books {
    ...BookF
  }
}

fragment BookF on Book {
  __typename
  id
  title
  authors {
    ...AuthorF
  }
}

fragment AuthorF on Author {
  __typename
  id
  name
}"""

_UNION = """query  {
  press {
    title
  }
}
"""
_UNION_SPREAD_BOOK = """query  {
  press {
    ... on Book {
      title
    }
  }
}
"""

_UNION_SPREAD_MAGAZINE = """query  {
  press {
    ... on Magazine {
      title
    }
  }
}
"""


@pytest.mark.parametrize(
    ("query", "cost"),
    [
        (_BOOKS_WITH_AUTHORS, 30),
        (
            _BOOKS_WITH_AUTHORS_AND_ADDITIONAL_FIELDS,
            60,
        ),
        (
            _ADDITIONAL_FIELDS_USING_FRAGMENTS,
            60,
        ),
        (
            _UNION,
            BOOKS_ASSUMED_SIZE * 3,
        ),
        (
            _UNION_SPREAD_BOOK,
            BOOKS_ASSUMED_SIZE * 2,
        ),
        (
            _UNION_SPREAD_MAGAZINE,
            BOOKS_ASSUMED_SIZE * 3,
        ),
    ],
)
def test_list_cost(query: str, cost: int) -> None:
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
    result = schema.execute_sync(query)
    assert result.extensions
    assert result.extensions["complexity"] == {
        "max": MAX_COMPLEXITY,
        "current": cost,
    }
