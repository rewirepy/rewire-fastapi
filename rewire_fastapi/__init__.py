from contextlib import suppress
from copy import copy
from enum import Enum
from functools import wraps
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Union,
    cast,
)
from typing_extensions import Annotated
from venv import logger

from fastapi.dependencies.models import Dependant
from rewire import ConfigDependency, LifecycleModule, simple_plugin
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
import fastapi.openapi.docs
import fastapi.applications
from fastapi.middleware.cors import CORSMiddleware
from rewire_fastapi.dependable import Dependable
from fastapi.dependencies.utils import get_dependant

plugin = simple_plugin()


class AppConfig(BaseModel, extra="allow"):
    debug: bool = False
    title: str = "FastAPI"
    description: str = ""
    version: str = "0.1.0"
    openapi_url: Optional[str] = "/openapi.json"
    openapi_tags: Optional[List[Dict[str, Any]]] = None
    servers: Optional[List[Dict[str, Union[str, Any]]]] = None
    docs_url: Optional[str] = "/docs"
    redoc_url: Optional[str] = "/redoc"


class UvicornConfig(BaseModel, extra="allow"):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8000


class HypercornConfig(BaseModel, extra="allow"):
    enabled: bool = False

    bind: str = "0.0.0.0:8000"


class RouteConfig(BaseModel):
    tag_prefix: str = ""


class PatchConfig(BaseModel):
    swagger_hierarchical_tags: bool = False
    tag_prefixes: bool = True
    dependency_overrides: dict[Callable, Callable] = {}
    """Will be reflected in swagger"""


class CORSConfig(BaseModel):
    allow_origins: Sequence[str] = []
    allow_methods: Sequence[str] = ["*"]
    allow_headers: Sequence[str] = ["*"]
    allow_credentials: bool = True
    allow_origin_regex: Optional[str] = None
    expose_headers: Sequence[str] = []
    max_age: int = 600


class MiddlewareConfig(BaseModel):
    cors: CORSConfig | None = None


@plugin.bind
class Config(ConfigDependency):
    server: Literal["uvicorn", "hypercorn", None] = "hypercorn"
    app: AppConfig = AppConfig()
    routes: RouteConfig = RouteConfig()
    uvicorn: UvicornConfig = UvicornConfig()
    hypercorn: HypercornConfig = HypercornConfig()
    patch: PatchConfig = PatchConfig()
    middleware: MiddlewareConfig = MiddlewareConfig()
    endpoint_: Annotated[Optional[str], Field(alias="endpoint")] = None

    @property
    def endpoint(self):
        if self.endpoint_ is not None:
            return self.endpoint_
        host = self.uvicorn.host
        if host == "0.0.0.0":
            host = "localhost"

        return f"http://{host}:{self.uvicorn.port}"


async def run_uvicorn(app: FastAPI, cfg: Config.Value):
    import uvicorn.config

    if not cfg.uvicorn.enabled:
        return

    logger.info(f"Starting fastapi with uvicorn at {cfg.endpoint}")
    config = uvicorn.config.Config(
        app,
        **cfg.uvicorn.model_dump(exclude={"enabled"}),
    )
    server = uvicorn.Server(config=config)

    if config.reload:
        raise NotImplementedError("reloads are not supported")
    if config.uds:
        raise NotImplementedError("uds is not implemented")
    if config.workers > 1:
        raise NotImplementedError("Multiprocess is not implemented")

    config.setup_event_loop()
    with suppress(LookupError):
        lm = LifecycleModule.get()

        @lm.on_stop
        async def stop():
            server.should_exit = True

    return await server.serve()


async def run_hypercorn(app: FastAPI, cfg: Config.Value):
    import sniffio
    from hypercorn.config import Config

    lib = sniffio.current_async_library()
    config = Config().from_mapping(cfg.hypercorn.model_dump())

    if lib == "asyncio":
        from hypercorn.asyncio import serve

        return await serve(app, config)  # type: ignore
    if lib == "trio":
        from hypercorn.trio import serve

        return await serve(app, config)  # type: ignore
    raise NotImplementedError(f"Unable to start hypercorn with {lib}")


@plugin.setup()
def create_fastapi(config: Config.Value) -> FastAPI:
    return FastAPI(**config.app.model_dump())


@plugin.run()
async def run_fastapi_app(app: FastAPI, cfg: Config.Value):
    if cfg.server == "uvicorn":
        await run_uvicorn(app, cfg)
    elif cfg.server == "hypercorn":
        await run_hypercorn(app, cfg)


@plugin.setup()
def add_middleware(app: FastAPI, config: Config.Value):
    if config.middleware.cors is not None:
        app.add_middleware(CORSMiddleware, **config.middleware.cors.model_dump())


@plugin.setup()
def stop_on_app_stop(app: FastAPI):
    with suppress(LookupError):
        lm = LifecycleModule.get()

        @app.on_event("shutdown")
        async def shutdown():
            await lm.stop()


@plugin.setup()
def add_hierarchial_tags(config: Config.Value):
    if not config.patch.swagger_hierarchical_tags:
        return

    get_swagger_ui_html = fastapi.openapi.docs.get_swagger_ui_html

    @wraps(get_swagger_ui_html)
    def get_swagger_ui_html_patched(*a, **kw):
        value = get_swagger_ui_html(*a, **kw)
        body = value.body.replace(
            b"<!-- `SwaggerUIBundle` is now available on the page -->",
            b"<!-- `SwaggerUIBundle` is now available on the page -->\n"
            b'<script src="https://unpkg.com/swagger-ui-plugin-hierarchical-tags"></script>',
        ).replace(
            b"SwaggerUIBundle({",
            b"SwaggerUIBundle({\nplugins: [HierarchicalTagsPlugin],\n",
        )
        return type(value)(body)

    fastapi.openapi.docs.get_swagger_ui_html = get_swagger_ui_html_patched
    fastapi.applications.get_swagger_ui_html = get_swagger_ui_html_patched  # type: ignore


@plugin.setup(stage=100)
def patch_router_tags(app: FastAPI, config: Config.Value):
    if not config.patch.tag_prefixes:
        return

    for route in app.router.routes:
        if not isinstance(route, APIRoute):
            continue

        if config.routes.tag_prefix:
            route.tags = [
                cast(str | Enum, f"{config.routes.tag_prefix}{x}".removesuffix(":"))
                for x in route.tags
            ]

    if app.openapi_tags and config.routes.tag_prefix:
        for tag in app.openapi_tags:
            tag["name"] = f"{config.routes.tag_prefix}{tag['name']}".removesuffix(":")


def patch_dependant(dependant: Dependant, config: PatchConfig):
    if dependant.call in config.dependency_overrides:
        assert dependant.path is not None
        previous = dependant
        dependant = get_dependant(
            call=config.dependency_overrides[dependant.call],
            path=dependant.path,
            name=previous.name,
            use_cache=previous.use_cache,
            security_scopes=previous.security_scopes,
        )
    new_dependencies = [patch_dependant(x, config) for x in dependant.dependencies]
    should_clone = any(
        old is not new for old, new in zip(dependant.dependencies, new_dependencies)
    )
    if should_clone:
        dependant = copy(dependant)
        dependant.dependencies = new_dependencies

    return dependant

@plugin.setup(stage=100)
def patch_router_dependency_overrides(app: FastAPI, config: Config.Value):
    if not config.patch.dependency_overrides:
        return
    app.dependency_overrides.update(config.patch.dependency_overrides)

    for route in app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        route.dependant = patch_dependant(route.dependant, config.patch)
