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
    shell_command,
)


def main():
    linter = define_linter(
        # If you set this to False, any files or directories that are not
        # linted by one of the defined linters, will not cause an error.
        strict_directory_contents=True,
        children=[
            file(
                path="requirements.txt",
                children=[
                    shell_command(["funions", "%s"]),
                    shell_command(["wc", "-l", "%s"]),
                ],
            ),
            directory(path="venv"),
            directory(
                path="sample_data",
                optional=False,
                children=[
                    # sample data contains some .json files so we specify a
                    # child linter to lint those files.
                    files(
                        glob="*.json",
                        children=[
                            # Make sure the JSON in these files are well-formed
                            # and that they follow a jsonschema schema.
                            json_content(
                                children=[follows_schema("json_schemas/menu.schema")]
                            )
                        ],
                    )
                ],
            ),
            directories(glob="sample_data/subdir_*", min_matches=1, max_matches=3),
            directory(path="json_schemas", optional=True),
            directory(path=".git", optional=False),
            directory(path="optional", optional=True),
            directory(path=".mypy_cache", optional=True),
            directory(path="must", optional=False),
            files(glob="*.py", optional=True),
            file(path=".gitignore", optional=True),
            file(path=".flake8", optional=True),
            files(glob="logfile.*.log", min_matches=3),
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
