"""
flint.py - a module that allows you to define linting operations to perform on
           a directory and its subdirectories and files.
"""
import json
import subprocess

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


class _LintContext:
    """
    Keeps track of LinterResults encountered during linting and what file or
    directory is currently being linted.
    """

    def __init__(self, path: Path, results: Optional[LinterResults] = None) -> None:
        self.path = path
        self.results = results or LinterResults()

    def update_results(self, results: LinterResults) -> None:
        self.results.update(results)

    def with_path(self, path: Path) -> Optional["_LintContext"]:
        return _LintContext(path, self.results)

    def in_directory(self, directory: Path) -> Optional["_LintContext"]:
        return _LintContext(directory, self.results) if directory.is_dir() else None

    def with_file(self, file: Path) -> Optional["_LintContext"]:
        return _LintContext(file, self.results) if file.is_file() else None

    def with_filename(self, filename: str) -> Optional["_LintContext"]:
        return self.with_file(Path(self.path, filename))

    def cd(self, directory: str) -> Optional["_LintContext"]:
        new_dir = Path(self.path / directory)
        return _LintContext(new_dir, self.results) if new_dir.is_dir() else None

    def warning(self, message: str) -> None:
        self.results.add(self.path, Warning(self.path, message))

    def error(self, message: str) -> None:
        self.results.add(self.path, Error(self.path, message))

    def touch_path(self) -> None:
        """
        Records that the current file or directory was handled by at least linter.

        This is so that we can detect any files that had no linters applied to
        them when the _Linter's strict_directory_contents flag is set to True.
        """
        self.results.path_map[self.path].extend([])


class _Lintable(ABC):
    """An object that can be linted"""

    @abstractmethod
    def lint(self, context: _LintContext) -> None:
        pass


class LintableGlobMatches(_Lintable):
    """
    Multiple objects can match a glob. This object encapsulates logic for
    limits on matches.
    """

    def __init__(
        self,
        glob: str,
        max_matches: Optional[int] = None,
        min_matches: Optional[int] = None,
    ) -> None:
        self.glob = glob
        self.max_matches = max_matches
        self.min_matches = min_matches

    def _check_limits(self, context: _LintContext, num_lintables: int) -> _LintContext:

        if self.min_matches is not None and num_lintables < self.min_matches:
            context.error(
                f"'{self.glob}' should have had at least {self.min_matches} "
                f"matches but it only had {num_lintables} matches."
            )

        if self.max_matches is not None and num_lintables > self.max_matches:
            context.error(
                f"'{self.glob}' should have had at most {self.max_matches} "
                f"matches but it had {num_lintables} matches.",
            )

        return context


class _Directory(_Lintable):
    """
    A directory that can be linted.

    Its contents can also be linted if any children are supplied.
    """

    def __init__(
        self,
        path: str,
        optional: bool = False,
        children: Optional[List[_Lintable]] = None,
    ) -> None:
        self.path = path
        self.optional = optional
        self.children = list(children) if children else []

    def lint(self, context: _LintContext) -> None:
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


class _File(_Lintable):
    def __init__(
        self,
        path: str,
        optional: bool = False,
        children: Optional[List[_Lintable]] = None,
    ) -> None:
        self.path = path
        self.optional = optional
        self.children = list(children) if children else []

    def lint(self, context: _LintContext) -> None:
        file_context = context.with_filename(self.path)
        file_context.touch_path()

        for child in self.children:
            child.lint(file_context)


class _Files(LintableGlobMatches):
    """
    One or more files that match a glob, that can be linted.
    """

    def __init__(
        self,
        glob: str,
        min_matches: Optional[int] = None,
        max_matches: Optional[int] = None,
        optional: Optional[bool] = False,
        children: Optional[List[_Lintable]] = None,
    ) -> None:
        super().__init__(glob, min_matches, max_matches)
        self.children = list(children) if children else []

    def lint(self, context: _LintContext) -> None:
        matches = [match for match in context.path.glob(self.glob) if match.is_file()]

        for match in matches:
            match_context = context.with_file(match)
            match_context.touch_path()
            for child in self.children:
                child.lint(match_context)

        self._check_limits(context, len(matches))


class _Directories(LintableGlobMatches):
    def __init__(
        self,
        glob: str,
        max_matches: Optional[int] = None,
        min_matches: Optional[int] = None,
        children: Optional[List[_Lintable]] = None,
    ) -> None:
        super().__init__(glob, min_matches, max_matches)
        self.children = list(children) if children else []

    def lint(self, context: _LintContext) -> None:
        matches = [match for match in context.path.glob(self.glob) if match.is_dir()]

        self._check_limits(context, len(matches))

        for match in matches:
            child_context = context.with_path(match)
            if child_context:
                for child in self.children:
                    child.lint(child_context)


class JsonRule(ABC):
    """
    A linting rule that is applied to a JSON object.

    This class is not private because it is intended for extension by users.
    """

    @abstractmethod
    def lint(self, json_obj: JSON, context: _LintContext) -> None:
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

    def lint(self, json_obj: JSON, context: _LintContext) -> None:
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


class _JsonContent(_Lintable):
    def __init__(self, children: Optional[List[JsonRule]] = None) -> None:
        self.children = list(children) if children else []

    def lint(self, context: _LintContext) -> None:
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


class _ShellCommand(_Lintable):
    def __init__(self, command_line: List[str]) -> None:
        self.command_line = list(command_line)

    def lint(self, context: _LintContext) -> None:
        if not context.path.is_file():
            context.error(f"{context.path} is not a file")
        else:
            command_line = [
                x.replace("%s", str(context.path)) for x in self.command_line
            ]
            try:
                output = subprocess.run(command_line, capture_output=True)
                if output.returncode != 0:
                    context.error(
                        f"non-zero return code ({output.returncode})"
                        f" returned from '{' '.join(command_line)}'."
                        f" Output: {output.stderr.decode('utf-8')}"
                    )
            except FileNotFoundError as ex:
                context.error(f"{str(ex)}")
            except subprocess.CalledProcessError as ex:
                context.error(f"{str(ex)}")


class _Linter:
    def __init__(
        self, children: List[_Lintable], strict_directory_contents: bool = True
    ) -> None:
        self.children = list(children)
        self.strict_directory_contents = strict_directory_contents

    def run(self, root: Path) -> LinterResults:
        linted_map: Dict[Path, bool] = {entry: False for entry in root.iterdir()}

        # Lint selected files and directories
        context = _LintContext(root)

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


def define_linter(children: List[_Lintable], *args, **kwargs):
    return _Linter(children=children, *args, **kwargs)


def directory(*args, **kwargs) -> _Lintable:
    return _Directory(*args, **kwargs)


def directories(*args, **kwargs) -> _Lintable:
    return _Directories(*args, **kwargs)


def files(*args, **kwargs) -> _Lintable:
    return _Files(*args, **kwargs)


def file(*args, **kwargs) -> _Lintable:
    return _File(*args, **kwargs)


def json_content(*args, **kwargs) -> _Lintable:
    return _JsonContent(*args, **kwargs)


def follows_schema(schema_file_name: str) -> JsonRule:
    return _JsonFollowsSchema(schema_file_name)


def shell_command(*args, **kwargs) -> _Lintable:
    return _ShellCommand(*args, **kwargs)
