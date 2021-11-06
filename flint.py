import json

from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import jsonschema

JSON = Dict[str, Union[str, int, List["JSON"], "JSON"]]


class LintResult(ABC):
    """
    A single result from a linting operation.
    """
    def __init__(self, path: Path) -> None:
        self.path = path

    def __repr__(self):
        return f"{self.__class__.__name__}({self.path})"

    def __str__(self):
        return f"{self.__class__.__name__}: {self.path}"


class LinterResults:
    """
    A map from the linted file or directory to a list of LintResults for that
    file or directory.
    """
    def __init__(self, path_map: Optional[Dict[Path, List[LintResult]]] = None) -> None:
        self.path_map = path_map if path_map else defaultdict(list)

    def update(self, other: "LinterResults") -> None:
        for k, v in other.path_map.items():
            self.path_map[k].extend(v)

    def add(self, path: Path, result: LintResult) -> None:
        self.path_map[path].append(result)

    def results(self) -> List[LintResult]:
        return [result for results in self.path_map.values() for result in results]

    def items(self) -> List[Tuple[Path, List[LintResult]]]:
        return list(self.path_map.items())

    def linted_paths(self) -> List[Path]:
        return list(self.path_map.keys())


class Error(LintResult):
    """
    An error discovered by a linting operation.
    """
    def __init__(self, path: Path, error: str) -> None:
        super().__init__(path)
        self.error = error

    def __str__(self):
        return f"{self.__class__.__name__.lower()}: {self.path}: {self.error}"


class Warning(LintResult):
    """
    An error discovered by a linting operation.
    """
    def __init__(self, path: Path, warning: str) -> None:
        super().__init__(path)
        self.warning = warning

    def __str__(self):
        return f"{self.__class__.__name__.lower()}: {self.path}: {self.warning}"


class LintContext:
    """
    Keeps track of LinterResults encountered during linting and what file or
    directory is currently being linted.
    """
    def __init__(self, path: Path, results: Optional[LinterResults] = None) -> None:
        self.path = path
        self.results = results or LinterResults()

    def update_results(self, results: LinterResults) -> None:
        self.results.update(results)

    def with_path(self, path: Path) -> Optional["LintContext"]:
        return LintContext(path, self.results)

    def in_directory(self, directory: Path) -> Optional["LintContext"]:
        return LintContext(directory, self.results) if directory.is_dir() else None

    def with_file(self, file: Path) -> Optional["LintContext"]:
        return LintContext(file, self.results) if file.is_file() else None

    def with_filename(self, filename: str) -> Optional["LintContext"]:
        return self.with_file(Path(self.path, filename))

    def cd(self, directory: str) -> Optional["LintContext"]:
        new_dir = Path(self.path / directory)
        return LintContext(new_dir, self.results) if new_dir.is_dir() else None

    def warning(self, message: str) -> None:
        self.results.add(self.path, Warning(self.path, message))

    def error(self, message: str) -> None:
        self.results.add(self.path, Error(self.path, message))

    def touch_path(self) -> None:
        """
        Records that the current file or directory was handled by at least linter.

        This is so that we can detect any files that had no linters applied to
        them when the Linter's strict_directory_contents flag is set to True.
        """
        self.results.path_map[self.path].extend([])


class Lintable(ABC):
    """An object that can be linted"""
    @abstractmethod
    def lint(self, context: LintContext) -> None:
        pass


class LintableGlobMatches(Lintable):
    """
    Multiple objects can match a glob. This object encapsulates logic for
    limits on matches.
    """
    def __init__(
        self, glob: str, max: Optional[int] = None, min: Optional[int] = None
    ) -> None:
        self.glob = glob
        self.max = max
        self.min = min

    def _check_limits(self, context: LintContext, num_lintables: int) -> LintContext:

        if self.min is not None and num_lintables < self.min:
            context.error(
                f"'{self.glob}' should have had at least {self.min} "
                f"matches but it only had {num_lintables} matches."
            )

        if self.max is not None and num_lintables > self.max:
            context.error(
                f"'{self.glob}' should have had at most {self.max} "
                f"matches but it had {num_lintables} matches.",
            )

        return context


class Directory(Lintable):
    """
    A directory that can be linted.

    Its contents can also be linted if any children are supplied.
    """
    def __init__(
        self,
        path: str,
        optional: bool = False,
        children: Optional[List[Lintable]] = None,
    ) -> None:
        self.path = path
        self.optional = optional
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> None:
        my_context = context.cd(self.path)
        if not my_context:
            if not self.optional:
                context.error(
                    f"required directory '{self.path}' does not exist",
                )
            return

        my_context.touch_path()
        for child in self.children:
            child.lint(my_context)


class File(Lintable):
    def __init__(self, path: str, optional: bool = False) -> None:
        self.path = path
        self.optional = optional

    def lint(self, context: LintContext) -> None:
        context.with_filename(self.path).touch_path()


class Files(LintableGlobMatches):
    """
    One or more files that match a glob, that can be linted.
    """
    def __init__(
        self,
        glob: str,
        min: Optional[int] = None,
        max: Optional[int] = None,
        optional: Optional[bool] = False,
        children: Optional[List[Lintable]] = None,
    ) -> None:
        super().__init__(glob, min, max)
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> None:
        matches = [match for match in context.path.glob(self.glob) if match.is_file()]

        for match in matches:
            match_context = context.with_file(match)
            match_context.touch_path()
            for child in self.children:
                child.lint(match_context)

        self._check_limits(context, len(matches))


class Directories(LintableGlobMatches):
    def __init__(
        self,
        glob: str,
        max: Optional[int] = None,
        min: Optional[int] = None,
        children: Optional[List[Lintable]] = None,
    ) -> None:
        super().__init__(glob, min, max)
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> None:
        matches = [match for match in context.path.glob(self.glob) if match.is_dir()]

        self._check_limits(context, len(matches))

        for match in matches:
            child_context = context.with_path(match)
            if child_context:
                for child in self.children:
                    child.lint(child_context)


class JsonRule(ABC):
    @abstractmethod
    def lint(self, json_obj: JSON, context: LintContext) -> None:
        pass


class JsonFollowsSchema(JsonRule):

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

        schema = self.SCHEMA_CACHE[path]
        try:
            jsonschema.validate(instance=json_obj, schema=schema)
        except jsonschema.exceptions.ValidationError as ex:
            context.error(f"{ex.message} JSON: {ex.instance}")


class JsonContent(Lintable):
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


class Linter:
    def __init__(
        self, children: List[Lintable], strict_directory_contents: bool = True
    ) -> None:
        self.children = list(children)
        self.strict_directory_contents = strict_directory_contents

    def run(self, root: Path) -> LinterResults:
        linted_map: Dict[Path, bool] = {entry: False for entry in root.iterdir()}

        # Lint selected files and directories
        context = LintContext(root)

        for child in self.children:
            child.lint(context)

        for path in context.results.linted_paths():
            linted_map[path] = True

        # Report unexpected entries in the directory
        if self.strict_directory_contents:
            for fso, linted in linted_map.items():
                if not linted:
                    fso_type = "directory" if fso.is_dir() else "file"
                    context.warning(f"unexpected {fso_type} '{fso}'")

        return context.results


def define_linter(children: List[Lintable], **kwargs):
    return Linter(children=children, **kwargs)


def directory(**kwargs):
    return Directory(**kwargs)


def directories(**args):
    return Directories(**args)


def files(**kwargs):
    return Files(**kwargs)


def file(**kwargs):
    return File(**kwargs)


def json_content(*args, **kwargs):
    return JsonContent(*args, **kwargs)


def follows_schema(schema_file_name: str) -> JsonRule:
    return JsonFollowsSchema(schema_file_name)
