from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class LintResult:

    def __init__(self, path: Path, lintable: Optional['Lintable']) -> None:
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

    def __init__(
            self,
            path_map: Optional[Dict[Path, List[LintResult]]] = None
            ) -> None:
        self.path_map = path_map if path_map else defaultdict(list)

    def update(self, other: 'LinterResults') -> None:
        for k, v in other.path_map.items():
            self.path_map[k].extend(v)

    def add(self, path: Path, result: LintResult) -> None:
        self.path_map[path].append(result)

    def results(self) -> List[LintResult]:
        return [result for results in self.path_map.values()
                for result in results]

    def items(self) -> List[Tuple[Path, List[LintResult]]]:
        return list(self.path_map.items())


class Error(LintResult):

    def __init__(self,
                 path: Path,
                 lintable: Optional['Lintable'],
                 error: str
                 ) -> None:
        super().__init__(path, lintable)
        self.error = error

    def __str__(self):
        return f"{self.__class__.__name__} in: {self.path}: {self.error}"


class Warning(LintResult):

    def __init__(self,
                 path: Path,
                 lintable: Optional['Lintable'],
                 warning: str
                 ) -> None:
        super().__init__(path, lintable)
        self.warning = warning

    def __str__(self):
        return f"{self.__class__.__name__} in: {self.path}: {self.warning}"


class Skipped(LintResult):
    pass


class LintContext:

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def with_cwd(self, directory: Path) -> Optional['LintContext']:
        if not directory.is_dir():
            return None
        else:
            return LintContext(directory)

    def cd(self, directory: str) -> Optional['LintContext']:
        new_dir = Path(self.cwd / directory)
        if not new_dir.is_dir():
            return None
        else:
            return LintContext(new_dir)


class Lintable(ABC):

    @abstractmethod
    def lint(self, context: LintContext) -> LinterResults:
        pass


class Directory(Lintable):

    def __init__(self, path: str,
                 optional: bool = False,
                 children: Optional[List[Lintable]] = None) -> None:
        self.path = path
        self.optional = optional
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> LinterResults:
        results = LinterResults()
        my_context = context.cd(self.path)
        if not my_context:
            if not self.optional:
                results.add(context.cwd, Error(
                    context.cwd, self,
                    f"required directory '{self.path}' does not exist"))
            return results

        for child in self.children:
            results.update(child.lint(my_context))
        return results


class File(Lintable):

    def __init__(self, path: str, optional: bool = False) -> None:
        self.path = path
        self.optional = optional

    def lint(self, context: LintContext) -> LinterResults:
        return LinterResults()


class Files(Lintable):

    def __init__(self,
                 glob: str,
                 max: Optional[int] = None,
                 min: Optional[int] = None,
                 children: Optional[List[Lintable]] = None
                 ) -> None:
        self.glob = glob
        self.min = min
        self.max = max
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> LinterResults:
        results = LinterResults()

        matches = [match for match in context.cwd.glob(self.glob)
                   if match.is_file()]

        for match in matches:
            for child in self.children:
                results.update(child.lint(context))

        return results


class Directories(Lintable):

    def __init__(self,
                 glob: str,
                 max: Optional[int] = None,
                 min: Optional[int] = None,
                 children: Optional[List[Lintable]] = None
                 ) -> None:
        self.glob = glob
        self.max = max
        self.min = min
        self.children = list(children) if children else []

    def lint(self, context: LintContext) -> LinterResults:
        results = LinterResults()

        matches = [match for match in context.cwd.glob(self.glob)
                   if match.is_dir()]

        if self.min is not None and len(matches) < self.min:
            results.add(
                context.cwd,
                Error(context.cwd, self,
                      f"'{self.glob}' should have had at least {self.min} "
                      f"matches but it only had {len(matches)} matches."))

        if self.max is not None and len(matches) > self.max:
            results.add(
                context.cwd,
                Error(context.cwd, self,
                      f"'{self.glob}' should have had at most {self.max} "
                      f"matches but it had {len(matches)} matches."))

        for match in matches:
            child_context = context.with_cwd(match)
            if child_context:
                for child in self.children:
                    results.update(child.lint(child_context))

        return results


class Linter:

    def __init__(self,
                 children: List[Lintable],
                 strict_directory_contents: bool = True
                 ) -> None:
        self.children = list(children)
        self.strict_directory_contents = strict_directory_contents

    def run(self, root: Path) -> LinterResults:
        results = LinterResults()

        linted_map: Dict[Path, bool] = {
            entry: False for entry in root.iterdir()}

        # Lint selected files and directories
        context = LintContext(root)
        for child in self.children:
            lint_results = child.lint(context)
            results.update(lint_results)
            for result in lint_results.results():
                linted_map[result.path] = True

        # Report unexpected entries in the directory
        if self.strict_directory_contents:
            for fso, linted in linted_map.items():
                if not linted:
                    fso_type = "directory" if fso.is_dir() else "file"
                    results.add(root,
                                Warning(fso, None, f"unexpected {fso_type}"))

        return results


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


def main():
    linter = define_linter(
        strict_directory_contents=False,
        children=[
            file(path="requirements.txt"),
            directory(path="venv", optional=False),
            directory(path="sample_data", optional=False, children=[
                files(glob="*.json")
            ]),
            directory(path="optional", optional=True),
            directory(path="must", optional=False),
            directory(path=".git", optional=False),
            directories(glob="sample_data/subdir_*", min=1, max=3),
            files(glob="logfile.*.log", min=3)
        ])

    for obj, results in (linter.run(Path.cwd())).items():
        print(f"{obj}:")
        for result in results:
            print(f"  {str(result)}")


if __name__ == '__main__':
    main()
