from __future__ import annotations
from functools import update_wrapper
from typing import (
    Annotated,
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Generic,
    ParamSpec,
    Type,
    TypeVar,
    overload,
)
from fastapi import Depends
from fastapi import params

P = ParamSpec("P")
T = TypeVar("T")
R = TypeVar("R")


class DependableWrapper(Generic[P, R, T], params.Depends):
    def __init__(self, callable: Callable[P, R]) -> None:
        update_wrapper(self, callable)
        super().__init__(callable)

    def _return_type(self) -> Type[T]: ...

    @property
    def Result(self) -> Type[T]:
        type_ = self._return_type()
        return Annotated[type_, Depends(self.dependency)]  # type: ignore

    def __call__(self, *args: P.args, **kwds: P.kwargs) -> R:
        assert self.dependency
        return self.dependency(*args, **kwds)


@overload
def Dependable(  # /NOSONAR
    fn: Callable[P, Awaitable[R]],
) -> DependableWrapper[P, Awaitable[R], R]: ...


@overload
def Dependable(  # /NOSONAR
    fn: Callable[P, AsyncGenerator[R, None]],
) -> DependableWrapper[P, AsyncGenerator[R, None], R]: ...


@overload
def Dependable(  # /NOSONAR
    fn: Callable[P, Awaitable[R]],
) -> DependableWrapper[P, Awaitable[R], R]: ...


@overload
def Dependable(  # /NOSONAR
    fn: Callable[P, AsyncIterable[R]],
) -> DependableWrapper[P, AsyncIterable[R], R]: ...


@overload
def Dependable(fn: Callable[P, R]) -> DependableWrapper[P, R, R]:  # /NOSONAR
    ...


def Dependable(fn):  # /NOSONAR
    return DependableWrapper(fn)
