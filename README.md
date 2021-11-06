# Flint - A file linter

If you have a collection of files and directories whose structure and content you want to lint, flint can help.

# Examples

See example.py for an example.

# Functions

## define_linter

Creates a top-level linter and any file or directory linters you want it to run.

## file

Creates a linter for a single file.

## files

Creates a linter for all files matching a glob.

## directory

Creates a linter for a single directory.

## directories

Creates a linter for all directories matching a glob.

## json_content

Creates a linter that can operate on files to ensure they have well-formed JSON.

## follows_schema

Creates a linter that can operate on JSON content to ensure that it adheres to a JSON schema.
