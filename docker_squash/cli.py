# -*- coding: utf-8 -*-

import argparse
import logging
import sys

from docker_squash import squash
from docker_squash.errors import SquashError
from docker_squash.version import version


# Source: http://stackoverflow.com/questions/1383254/logging-streamhandler-and-standard-streams
class SingleLevelFilter(logging.Filter):
    def __init__(self, passlevel, reject):
        self.passlevel = passlevel
        self.reject = reject

    def filter(self, record):
        if self.reject:
            return record.levelno != self.passlevel
        else:
            return record.levelno == self.passlevel


class MyParser(argparse.ArgumentParser):
    # noinspection PyMethodMayBeStatic
    def str2bool(self, v: str) -> bool:
        if isinstance(v, bool):
            return v
        if v.lower() in ("yes", "true", "t", "y", "1"):
            return True
        elif v.lower() in ("no", "false", "f", "n", "0"):
            return False
        else:
            raise argparse.ArgumentTypeError("Boolean value expected.")

    def error(self, message):
        self.print_help()
        sys.stderr.write("\nError: %s\n" % message)
        sys.exit(2)


class CLI(object):
    def __init__(self):
        handler_out = logging.StreamHandler(sys.stdout)
        handler_err = logging.StreamHandler(sys.stderr)

        handler_out.addFilter(SingleLevelFilter(logging.INFO, False))
        handler_err.addFilter(SingleLevelFilter(logging.INFO, True))

        self.log = logging.getLogger()
        formatter = logging.Formatter(
            "%(asctime)s %(filename)s:%(lineno)-10s %(levelname)-5s %(message)s"
        )

        handler_out.setFormatter(formatter)
        handler_err.setFormatter(formatter)

        self.log.addHandler(handler_out)
        self.log.addHandler(handler_err)

    def run(self):
        parser = MyParser(description="Docker layer squashing tool")

        parser.add_argument(
            "-v", "--verbose", action="store_true", help="Verbose output"
        )

        parser.add_argument(
            "--version", action="version", help="Show version and exit", version=version
        )

        parser.add_argument("image", help="Image to be squashed")
        parser.add_argument(
            "-f",
            "--from-layer",
            help="Number of layers to squash or ID of the layer (or image ID or image name) to squash from. In case the provided value is an integer, specified number of layers will be squashed. Every layer in the image will be squashed if the parameter is not provided.",
        )
        parser.add_argument(
            "-t",
            "--tag",
            help="Specify the tag to be used for the new image. If not specified no tag will be applied",
        )
        parser.add_argument(
            "-m",
            "--message",
            default="",
            help="Specify a commit message (comment) for the new image.",
        )
        parser.add_argument(
            "-c",
            "--cleanup",
            action="store_true",
            help="Remove source image from Docker after squashing",
        )
        parser.add_argument(
            "--tmp-dir",
            help="Temporary directory to be created and used. This will NOT be deleted afterwards for easier debugging.",
        )
        parser.add_argument(
            "--output-path",
            help="Path where the image may be stored after squashing.",
        )
        parser.add_argument(
            "--load-image",
            type=parser.str2bool,
            const=True,
            nargs="?",
            default=True,
            help="Whether to load the image into Docker daemon after squashing",
        )

        args = parser.parse_args()

        if args.verbose:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

        self.log.debug("Running version %s", version)
        try:
            squash.Squash(
                log=self.log,
                image=args.image,
                from_layer=args.from_layer,
                tag=args.tag,
                comment=args.message,
                output_path=args.output_path,
                load_image=args.load_image,
                tmp_dir=args.tmp_dir,
                cleanup=args.cleanup,
            ).run()
        except KeyboardInterrupt:
            self.log.error("Program interrupted by user, exiting...")
            sys.exit(1)
        except Exception:
            e = sys.exc_info()[1]

            if args.verbose:
                self.log.exception(e)
            else:
                self.log.error(str(e))

            self.log.error(
                "Execution failed, consult logs above. If you think this is our fault, please file an issue: https://github.com/goldmann/docker-squash/issues, thanks!"
            )

            if isinstance(e, SquashError):
                sys.exit(e.code)

            sys.exit(1)


def run():
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    run()
