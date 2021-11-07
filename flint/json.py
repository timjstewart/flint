from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Union

import json

import jsonschema

from flint import LintContext, Lintable

JSON = Dict[str, Union[str, int, List["JSON"], "JSON"]]


class JsonRule(ABC):
    """
    A linting rule that is applied to a JSON object.

    This class is not private because it is intended for extension by users.
    """

    @abstractmethod
    def lint(self, json_obj: JSON, context: LintContext) -> None:
        pass


class _JsonFollowsSchema(JsonRule):
    """
    Validates JSON content against a JSON schema.

    See: https://json-schema.org/
    """

    # Try not to load the same schema more than once
    SCHEMA_CACHE: Dict[Path, JSON] = {}

    def __init__(self, schema_filename: str) -> None:
        self.schema_filename = schema_filename

    def lint(self, json_obj: JSON, context: LintContext) -> None:
        path = Path(self.schema_filename)
        if not path.is_absolute():
            path = Path(Path.cwd() / self.schema_filename)

        if path not in self.SCHEMA_CACHE:
            try:
                self.SCHEMA_CACHE[path] = json.loads(path.read_text())
            except json.decoder.JSONDecodeError as ex:
                context.error(f"Malformed JSON found in schema file: {path} - {ex}")
                return
            except FileNotFoundError as ex:
                context.error(f"Could not find JSON schema file: {path} - {ex}")
                return
            except jsonschema.exceptions.SchemaError as ex:
                context.error(f"Invalid JSON schema file: {path} - {ex.message}")
                return

        schema = self.SCHEMA_CACHE[path]
        try:
            jsonschema.validate(instance=json_obj, schema=schema)
        except jsonschema.exceptions.ValidationError as ex:
            context.error(f"{ex.message} JSON: {ex.instance}")


class _JsonContent(Lintable):
    def __init__(self, children: Optional[List[JsonRule]] = None) -> None:
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> None:
        if not context.path.is_file():
            context.error(f"Can only check JSON content for files:  {context.path}")

        json_text = context.path.read_text()
        try:
            json_object = json.loads(json_text)
        except json.decoder.JSONDecodeError as ex:
            context.error(str(ex))
        else:
            for child in self.children:
                child.lint(json_object, context)


def json_content(*args, **kwargs) -> Lintable:
    return _JsonContent(*args, **kwargs)


def follows_schema(schema_file_name: str) -> JsonRule:
    return _JsonFollowsSchema(schema_file_name)
