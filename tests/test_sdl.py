import strawberry
from strawberry import Schema
from strawberry_query_complexity import Cost, QueryComplexityExtension

# Introspection query sent by graphiql
QUERY = """query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      ...FullType
    }
    directives {
      name
      description

      locations
      args(includeDeprecated: true) {
        ...InputValue
      }
    }
  }
}

fragment FullType on __Type {
  kind
  name
  description

  fields(includeDeprecated: true) {
    name
    description
    args(includeDeprecated: true) {
      ...InputValue
    }
    type {
      ...TypeRef
    }
    isDeprecated
    deprecationReason
  }
  inputFields(includeDeprecated: true) {
    ...InputValue
  }
  interfaces {
    ...TypeRef
  }
  enumValues(includeDeprecated: true) {
    name
    description
    isDeprecated
    deprecationReason
  }
  possibleTypes {
    ...TypeRef
  }
}

fragment InputValue on __InputValue {
  name
  description
  type { ...TypeRef }
  defaultValue
  isDeprecated
  deprecationReason
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
      }
    }
  }
}
"""


def test_sdl_query() -> None:
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

    result = schema.execute_sync(QUERY)
    assert not result.errors
    assert not result.extensions
