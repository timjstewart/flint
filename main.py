from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


class LintResult:

    def __init__(self, path: Path, lintable: Optional['Lintable']) -> None:
        self.path = path
        self.lintable = lintable

    def __repr__(self):
        return f"{self.__class__.__name__}({self.path})"

    def __str__(self):
        return f"{self.__class__.__name__}: {self.path}"


# A map from the linted file or directory to a list of LintResults for that
# file or directory
LinterResults = Dict[Path, List[LintResult]]


def merge_results(lhs: LinterResults,
                  rhs: LinterResults) -> LinterResults:
    results: LinterResults = defaultdict(list)
    for k, v in lhs.items():
        results[k].extend(v)
    for k, v in rhs.items():
        results[k].extend(v)
    return results


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
        results: LinterResults = defaultdict(list)
        my_context = context.cd(self.path)
        if not my_context:
            if not self.optional:
                results[context.cwd].append(Error(
                    context.cwd, self,
                    f"required directory '{self.path}' does not exist"))
            return results

        for child in self.children:
            results = merge_results(results, child.lint(my_context))
        return results


class File(Lintable):

    def __init__(self, path: str, optional: bool = False) -> None:
        self.path = path
        self.optional = optional

    def lint(self, context: LintContext) -> LinterResults:
        return {}


class Files(Lintable):

    def __init__(self, glob: str) -> None:
        self.glob = glob

    def lint(self, context: LintContext) -> LinterResults:
        return {}


class Directories(Lintable):

    def lint(self, context: LintContext) -> LinterResults:
        return {}


class Linter:

    def __init__(self,
                 children: List[Lintable],
                 strict_directory_contents: bool = True
                 ) -> None:
        self.children = list(children)
        self.strict_directory_contents = strict_directory_contents

    def run(self, root: Path) -> LinterResults:
        results: LinterResults = defaultdict(list)

        linted_map: Dict[Path, bool] = {
            entry: False for entry in root.iterdir()}

        # Lint selected files and directories
        context = LintContext(root)
        for child in self.children:
            lint_results = child.lint(context)
            results = merge_results(results, lint_results)
            for result in lint_results:
                linted_map[result] = True

        # Report unexpected entries in the directory
        if self.strict_directory_contents:
            for fso, linted in linted_map.items():
                if not linted:
                    fso_type = "directory" if fso.is_dir() else "file"
                    results[root].append(
                        Warning(fso, None, f"unexpected {fso_type}"))

        return results


def define_linter(children: List[Lintable], **kwargs):
    return Linter(children=children, **kwargs)


def directory(**kwargs):
    return Directory(**kwargs)


def directories(**args):
    return Directories()


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
            directory(path=".gitr", optional=False),
            directories(glob="subdir_*", min=1),
            files(glob="logfile.*.log")
        ])

    for obj, results in (linter.run(Path.cwd())).items():
        print(f"{obj}:")
        for result in results:
            print(f"  {str(result)}")


if __name__ == '__main__':
    main()
