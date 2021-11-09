from pathlib import Path

from flint import (
    directory,
    file,
    files,
    function,
    directories,
    define_linter,
    print_results,
    process_results,
    shell_command,
    LintContext,
    LinterArgs
)

from flint.json import follows_schema, json_content, collect_values, JsonPath


def named_success_function(context: LintContext) -> bool:
    return True


def named_failing_function(context: LintContext) -> bool:
    return False


def main():
    process_results(
        define_linter(
            # If you set this to False, any files or directories that are not
            # linted by one of the defined linters, will not cause an error.
            strict_directory_contents=True,
            print_properties=False,
            children=[
                file(
                    path="lorem.txt",
                    children=[
                        # The "%s" argument will be replaced by the full path
                        # to the file being linted.
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
                                        collect_values(
                                            JsonPath.compile("/menu/items/*"),
                                            "menu",
                                            "items",
                                        ),
                                        collect_values(
                                            JsonPath.compile("/menu/items/0"),
                                            "menu",
                                            "first_item",
                                        ),
                                        follows_schema(
                                            "menu.schema"
                                        ),
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
                function(lambda c: None, name="succeed with None"),
                function(lambda c: "foo", name="fail with foo"),
                function(lambda c: False, name="bool_fail_func"),
                function(lambda c: True, name="bool_success_func"),
                function(named_failing_function),
                function(named_success_function),
            ],
        ).run(LinterArgs(
            directory=Path(Path.cwd() / "example_dir"),
            schema_directories=[
                Path("example_dir/json_schemas")
                ]
            ))
    )


if __name__ == "__main__":
    main()
