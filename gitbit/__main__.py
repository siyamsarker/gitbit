"""
Entry point for module invocation: python -m gitbit.

This file allows gitbit to be run directly without installing the console-script
entry point defined in pyproject.toml. It is equivalent to running `gitbit` from
the command line once the package is installed.

The actual command group and all subcommands are defined in gitbit.cli.
"""
from gitbit.cli import main

if __name__ == "__main__":
    main()
