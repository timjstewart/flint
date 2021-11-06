import sys
from pathlib import Path

from flint import (
    directory,
    file,
    files,
    directories,
    json_content,
    define_linter,
    follows_schema,
)


def main():
    linter = define_linter(
        strict_directory_contents=True,
        children=[
            file(path="requirements.txt"),
            directory(path="venv", optional=False),
            directory(
                path="sample_data",
                optional=False,
                children=[
                    files(
                        glob="*.json",
                        children=[
                            json_content(
                                children=[follows_schema("json_schemas/menu.schema")]
                            )
                        ],
                    )
                ],
            ),
            directory(path="optional", optional=True),
            directory(path="json_schemas", optional=True),
            directory(path=".mypy_cache", optional=True),
            directory(path="must", optional=False),
            directory(path=".git", optional=False),
            files(glob="*.py", optional=True),
            file(path=".gitignore", optional=True),
            file(path=".flake8", optional=True),
            directories(glob="sample_data/subdir_*", min=1, max=3),
            files(glob="logfile.*.log", min=3),
        ],
    )

    exit_code = 0

    for obj, results in (linter.run(Path.cwd())).items():
        if results:
            exit_code = 1
            for result in results:
                print(f"{str(result)}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
