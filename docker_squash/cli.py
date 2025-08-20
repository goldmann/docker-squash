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

        parser.add_argument(
            "image",
            help="Image name or tar file path to be squashed. If a .tar file is provided, it will be processed without requiring Docker daemon.",
        )

        parser.add_argument(
            "-f",
            "--from-layer",
            help="Number of layers to squash or ID of the layer (or image ID or image name) to squash from. In case the provided value is an integer, specified number of layers will be squashed. Every layer in the image will be squashed if the parameter is not provided.",
        )
        parser.add_argument(
            "-t",
            "--tag",
            help="Specify the tag to be used for the squashed image (recommended). Without this, the squashed image will have no repository tags to avoid overwriting the original image.",
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
            # Auto-detect if input is tar file or image name
            if self._is_tar_file(args.image):
                self.log.debug(f"Detected tar file: {args.image}")
                self._run_tar_mode(args)
            else:
                self.log.debug(f"Detected image name: {args.image}")
                self._run_image_mode(args)

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

    def _run_tar_mode(self, args):
        from docker_squash.tar_image import TarImage

        # Provide helpful guidance about --tag parameter
        if not args.tag:
            self.log.info(
                "💡 Tip: Consider using --tag to specify a name for your squashed image"
            )
            self.log.info("   Example: --tag myimage:squashed")

        tar_image = TarImage(
            log=self.log,
            tar_path=args.image,  # 这里改为 args.image
            from_layer=args.from_layer,
            tmp_dir=args.tmp_dir,
            tag=args.tag,
            comment=args.message,
        )

        try:
            new_image_id = tar_image.squash()
            self.log.info("New squashed image ID is %s" % new_image_id)

            if not args.output_path:
                import os

                self.output_path = os.path.join(
                    os.path.dirname(args.image), f"squashed-{new_image_id[:12]}.tar"
                )

            if args.output_path:
                tar_image.export_tar_archive(args.output_path)

            if args.load_image:
                tar_image.load_squashed_image()

            self.log.info("Done")

        finally:
            if not args.tmp_dir:
                tar_image.cleanup()

    def _run_image_mode(self, args):
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

    def _is_tar_file(self, input_path):
        """Detect if input is a tar file or image name"""
        import os
        import tarfile

        # Check if it's a file path that exists
        if os.path.isfile(input_path):
            # Check if it's a valid tar file
            try:
                with tarfile.open(input_path, "r"):
                    return True
            except (tarfile.TarError, OSError):
                return False

        # Check if it ends with .tar extension
        if input_path.endswith((".tar", ".tar.gz", ".tgz")):
            return True

        # Check for obvious file path patterns
        if (
            input_path.startswith(("/"))  # Absolute path
            or input_path.startswith(("./"))  # Current dir
            or input_path.startswith(("../"))  # Parent dir
            or input_path.startswith(("~/"))
        ):  # Home dir
            return True

        # Otherwise assume it's an image name (even if it contains '/')
        return False


def run():
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    run()
