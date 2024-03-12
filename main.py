import uvicorn
from strawberry.asgi import GraphQL

from tests.test_complexity import schema

app = GraphQL(schema=schema)

if __name__ == "__main__":
    uvicorn.run("main:app")
