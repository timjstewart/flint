from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Union

import json

import jsonschema

from flint import LintContext, Lintable

JSON = Dict[str, Union[str, int, List["JSON"], "JSON"]]

JsonPathElement = Union[str, int]


class JsonRule(ABC):
    """
    A linting rule that is applied to a JSON object.

    This class is not private because it is intended for extension by users.
    """

    @abstractmethod
    def lint(self, json_obj: JSON, context: LintContext) -> None:
        pass


def try_as_int(s: str) -> Union[str, int]:
    try:
        return int(s)
    except ValueError:
        return s


class JsonPath:
    def __init__(self, elements: List[JsonPathElement]) -> None:
        self.elements = list(elements)

    @staticmethod
    def compile(s: str) -> "JsonPath":
        elements = [try_as_int(x) for x in s.split("/") if x]
        if not elements:
            raise ValueError(f"could not compile '{s}' into JsonPath")
        return JsonPath(elements)

    def matches(self, context: LintContext, json_object: JSON) -> List[JSON]:
        current = [json_object]
        try:
            for element in self.elements:
                # Array index
                if isinstance(element, int):
                    if isinstance(current[0], list):
                        current = [x[element] for x in current]
                    else:
                        return []
                # Object property lookup
                elif isinstance(element, str):
                    if isinstance(current[0], dict):
                        current = [x[element] for x in current]
                    elif isinstance(current[0], list):
                        if element == "*":
                            current = [elem for elems in current for elem in elems]
                    else:
                        return []
        except KeyError as ex:
            context.error(f"could not find key: {ex}")
        return current

    def __str__(self) -> str:
        return "/".join(self.elements)


class _JsonCollectValues(JsonRule):
    def __init__(
        self, json_path: JsonPath, group: str, key: str, optional: bool = False
    ) -> None:
        self.json_path = json_path
        self.group = group
        self.key = key
        self.optional = optional

    def lint(self, json_obj: JSON, context: LintContext) -> None:
        found = []
        for match in self.json_path.matches(context, json_obj):
            found.append(match)
        context.extend_property(self.group, self.key, found)
        if not self.optional and not found:
            context.error(f"JsonPath {self.json_path} did not match any elements")


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
        schema = self.load_schema_file(Path(self.schema_filename), context)
        if schema is None:
            return
        try:
            jsonschema.validate(instance=json_obj, schema=schema)
        except jsonschema.exceptions.ValidationError as ex:
            context.error(f"{ex.message} JSON: {ex.instance}")

    @staticmethod
    def find_schema_file(
            path: Path,
            context: LintContext
            ) -> Optional[Path]:
        if path.is_absolute():
            return path

        search_paths = [Path.cwd()]
        for schema_dir in context.args.schema_directories:
            if schema_dir.is_absolute():
                search_paths.append(Path(schema_dir))
            else:
                search_paths.append(Path(Path.cwd(), Path(schema_dir)))

        for search_path in search_paths:
            try_path = Path(search_path, path)
            if try_path.is_file():
                return try_path

        return None

    @staticmethod
    def load_schema_file(
            path: Path,
            context: LintContext
            ) -> Optional[JSON]:
        result = _JsonFollowsSchema.SCHEMA_CACHE.get(path, None)
        if result is None:
            schema_path = _JsonFollowsSchema.find_schema_file(path, context)
            if schema_path:
                try:
                    result = json.loads(schema_path.read_text())
                    _JsonFollowsSchema.SCHEMA_CACHE[path] = result
                    return result
                except json.decoder.JSONDecodeError as ex:
                    context.error(f"Malformed JSON found in schema file: {schema_path} - {ex}")
                    return None
                except FileNotFoundError as ex:
                    context.error(f"Could not find JSON schema file: {schema_path} - {ex}")
                    return None
                except jsonschema.exceptions.SchemaError as ex:
                    context.error(f"Invalid JSON schema file: {schema_path} - {ex.message}")
                    return None
            else:
                context.error(f"Could not find JSON schema file: {path} in {','.join(str(p) for p in context.args.schema_directories)}")
        return result


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


def collect_values(*args, **kwargs):
    return _JsonCollectValues(*args, **kwargs)
