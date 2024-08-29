from typing import get_args
from pydantic import BaseModel, create_model
from pydantic_core import core_schema
from pydantic.json_schema import SkipJsonSchema


class Patch[T: BaseModel]:
    """Helper type for patch routes

    Usage:
    ```
    @router.patch("/model/{id}")
    @transaction()
    async def update_model(input: Patch[ModelInput], model: get_model.Result) -> Model:
        input.apply(model)
        return model
    ```
    """

    def __init__(self, data: T) -> None:
        self.data = data

    def apply(self, to: object):
        for field in self.data.__pydantic_fields_set__:
            setattr(to, field, getattr(self.data, field))

    @classmethod
    def _update_model[B: BaseModel](cls, model: type[B]) -> type[B]:
        return create_model(
            f"{model.__name__}Patch",
            __doc__=model.__doc__,
            __base__=(model,),
            __module__=model.__module__,
            **{
                k: (v.annotation | SkipJsonSchema[None], None)
                for k, v in model.model_fields.items()
            },  # type: ignore
        )

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        instance_schema = core_schema.is_instance_schema(cls)

        args = get_args(source)
        updated = cls._update_model(args[0])
        t_schema = handler.generate_schema(updated)

        non_instance_schema = core_schema.no_info_after_validator_function(
            cls, schema=t_schema
        )
        return core_schema.union_schema([instance_schema, non_instance_schema])

    def __str__(self):
        return f"{type(self).__name__}({self.data})"

    def __repr__(self):
        return f"{type(self).__name__}({self.data!r})"
