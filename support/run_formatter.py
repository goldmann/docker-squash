#!/usr/bin/env python3
"""run_formatter.py - A tool to run the various formatters with the project settings"""
import sys
from pathlib import Path
from subprocess import CalledProcessError, run

import argparse

from docker_squash.image import Chdir



def main(check: bool=False, verbose: bool=False) -> None:
    """Main function

    :params check: Flag to return the status without overwriting any file.
    """
    options = []
    verbose_opt = []

    parser = argparse.ArgumentParser(prog='Formatter')
    parser.add_argument('--check', required=False, action='store_true', help="Don't write the files back, just return the status.")
    parser.add_argument(
            '-v', '--verbose', required=False, action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.check:
        options.append("--check")
    if args.verbose:
        verbose_opt.append("--verbose")

    repo_root = str(Path(__file__).parent.parent)
    print(f"Repository root is {repo_root}")

    # Run the various formatters, stop on the first error
    for formatter in [
        ["isort"],
        ["black"],
    ]:
        try:
            with Chdir(repo_root):
                run(formatter + options + verbose_opt + ["."], check=True)
        except CalledProcessError as err:
            sys.exit(err.returncode)

    # Flake8 does not support a --check flag
    for formatter in [
        ["flake8"],
    ]:
        try:
            with Chdir(repo_root):
                run(formatter + verbose_opt + ["."], check=True)
        except CalledProcessError as err:
            sys.exit(err.returncode)

    sys.exit(0)


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
