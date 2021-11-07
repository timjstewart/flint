from pathlib import Path

from flint import (
    directory,
    file,
    files,
    directories,
    define_linter,
    print_results,
    shell_command,
)

from flint.json import (
    follows_schema,
    json_content,
)


def main():
    print_results(
        define_linter(
            # If you set this to False, any files or directories that are not
            # linted by one of the defined linters, will not cause an error.
            strict_directory_contents=True,
            children=[
                file(
                    path="lorem.txt",
                    children=[
                        shell_command(["funions", "%s"]),
                        shell_command(["wc", "-l", "%s"]),
                    ],
                ),
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
                                    children=[
                                        follows_schema("json_schemas/menu.schema")
                                    ]
                                )
                            ],
                        )
                    ],
                ),
                directories(glob="sample_data/subdir_*", min_matches=1, max_matches=3),
                directory(path="json_schemas", optional=True),
                directory(path="optional", optional=True),
                directory(path="must", optional=False),
                files(glob="*.json", optional=True),
            ],
        ).run(Path(Path.cwd() / "example_dir"))
    )


if __name__ == "__main__":
    main()
