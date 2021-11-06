from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json


class LintResult:
    def __init__(self, path: Path, lintable: Optional["Lintable"]) -> None:
        self.path = path
        self.lintable = lintable

    def __repr__(self):
        return f"{self.__class__.__name__}({self.path})"

    def __str__(self):
        return f"{self.__class__.__name__}: {self.path}"


class LinterResults:
    """
    A map from the linted file or directory to a list of LintResults for that
    file or directory
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
    def __init__(self, path: Path, lintable: Optional["Lintable"], error: str) -> None:
        super().__init__(path, lintable)
        self.error = error

    def __str__(self):
        return f"{self.__class__.__name__} in: {self.path}: {self.error}"


class Warning(LintResult):
    def __init__(
        self, path: Path, lintable: Optional["Lintable"], warning: str
    ) -> None:
        super().__init__(path, lintable)
        self.warning = warning

    def __str__(self):
        return f"{self.__class__.__name__} in: {self.path}: {self.warning}"


class Skipped(LintResult):
    pass


class LintContext:
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

    def cd(self, directory: str) -> Optional["LintContext"]:
        new_dir = Path(self.path / directory)
        return LintContext(new_dir, self.results) if new_dir.is_dir() else None

    def warning(self, message: str) -> None:
        self.results.add(self.path, Warning(self.path, None, message))

    def error(self, message: str) -> None:
        self.results.add(self.path, Warning(self.path, None, message))


class Lintable(ABC):
    @abstractmethod
    def lint(self, context: LintContext) -> None:
        pass


class PatternLintable(Lintable):
    def __init__(
        self, glob: str, max: Optional[int] = None, min: Optional[int] = None
    ) -> None:
        self.glob = glob
        self.max = max
        self.min = min

    def _check_count(self, context: LintContext, num_lintables: int) -> LintContext:

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

        for child in self.children:
            child.lint(my_context)


class File(Lintable):
    def __init__(self, path: str, optional: bool = False) -> None:
        self.path = path
        self.optional = optional

    def lint(self, context: LintContext) -> None:
        pass


class Files(PatternLintable):
    def __init__(
        self,
        glob: str,
        min: Optional[int] = None,
        max: Optional[int] = None,
        children: Optional[List[Lintable]] = None,
    ) -> None:
        super().__init__(glob, min, max)
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> None:
        matches = [match for match in context.path.glob(self.glob) if match.is_file()]

        self._check_count(context, len(matches))

        for match in matches:
            for child in self.children:
                child.lint(context.with_file(match))


class Directories(PatternLintable):
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

        self._check_count(context, len(matches))

        for match in matches:
            child_context = context.with_path(match)
            if child_context:
                for child in self.children:
                    child.lint(child_context)


class JsonContent(Lintable):
    def lint(self, context: LintContext) -> None:
        if not context.path.is_file():
            context.error(f"Can only check JSON content for files:  {context.path}")

        json_text = context.path.read_text()
        try:
            json_obj = json.loads(json_text)
        except json.decoder.JSONDecodeError as ex:
            context.error(str(ex))


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
                    context.warning(f"unexpected {fso_type}")

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


def json_content():
    return JsonContent()


def main():
    linter = define_linter(
        strict_directory_contents=False,
        children=[
            file(path="requirements.txt"),
            directory(path="venv", optional=False),
            directory(
                path="sample_data",
                optional=False,
                children=[files(glob="*.json", children=[json_content()])],
            ),
            directory(path="optional", optional=True),
            directory(path="must", optional=False),
            directory(path=".git", optional=False),
            directories(glob="sample_data/subdir_*", min=1, max=3),
            files(glob="logfile.*.log", min=3),
        ],
    )

    for obj, results in (linter.run(Path.cwd())).items():
        print(f"{obj}:")
        for result in results:
            print(f"  {str(result)}")


if __name__ == "__main__":
    main()
