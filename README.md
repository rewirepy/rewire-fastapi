
# rewire\_fastapi

A FastAPI integration for rewire.

## Installation

To get started, install `rewire_fastapi` using pip:

```bash
pip install rewire_fastapi
```

## Supported Servers

This package supports running with both Uvicorn and Hypercorn servers (`rewire_fastapi.server`).

## Usage

First, import add `rewire_fastapi` to your rewire application:

```python
# ...
import rewire_fastapi

async def main():
    async with Space().init().use():
        DependenciesModule.get().add(rewire_fastapi.plugin)  # add this
        # ...

```

Then have injected fastapi in your files:

```python
from fastapi import APIRouter, FastAPI
from rewire.plugins import simple_plugin

plugin = simple_plugin()
router = APIRouter()


@router.get("/hello")
def hello_world():
    return "world"


@plugin.setup()
async def include_router(app: FastAPI):
    app.include_router(router)
```

## Configuration

Configure the package in `config.yaml` file:

```yaml
rewire_fastapi:
  server: "hypercorn"
  app: # will be passed to FastAPI instance
    title: "My App"
  uvicorn: # (optional)
    port: 1234
  hypercorn: # (optional)
    bind: "0.0.0.0:1234"
  routes:  # (optional)
    tag_prefix: "myapp:"
  patch: # (optional)
    swagger_hierarchical_tags: true
    tag_prefixes: true
  middleware:
    cors: # enable cors middleware (optional)
      allow_origins: ["*"]
      allow_methods: ["*"]
      allow_headers: ["*"]

```
