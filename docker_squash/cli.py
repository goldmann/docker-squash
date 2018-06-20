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
            return (record.levelno != self.passlevel)
        else:
            return (record.levelno == self.passlevel)


class MyParser(argparse.ArgumentParser):

    def error(self, message):
        self.print_help()
        sys.stderr.write('\nError: %s\n' % message)
        sys.exit(2)


class CLI(object):

    def __init__(self):
        handler_out = logging.StreamHandler(sys.stdout)
        handler_err = logging.StreamHandler(sys.stderr)

        handler_out.addFilter(SingleLevelFilter(logging.INFO, False))
        handler_err.addFilter(SingleLevelFilter(logging.INFO, True))

        self.log = logging.getLogger()
        formatter = logging.Formatter(
            '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')

        handler_out.setFormatter(formatter)
        handler_err.setFormatter(formatter)

        self.log.addHandler(handler_out)
        self.log.addHandler(handler_err)

    def run(self):
        parser = MyParser(
            description='Docker layer squashing tool')

        parser.add_argument(
            '-v', '--verbose', action='store_true', help='Verbose output')

        parser.add_argument(
            '--version', action='version', help='Show version and exit', version=version)

        parser.add_argument('image', help='Image to be squashed')
        parser.add_argument('-r', '--rebase',
                            help='Rebase the image on a different "FROM"')
        parser.add_argument('-d', '--development', action='store_true',
                            help='Does not clean up after failure for easier debugging')
        parser.add_argument('-f', '--from-layer',
                            help='ID of the layer or image ID or image name. '
                                 'If not specified will squash all layers in the image')
        parser.add_argument('-t', '--tag',
                            help="Specify the tag to be used for the new image. If not specified no tag will be applied")
        parser.add_argument('-c', '--cleanup', action='store_true',
                            help="Remove source image from Docker after squashing")
        parser.add_argument('--tmp-dir',
                            help='Temporary directory to be created and used')
        parser.add_argument('--output-path',
                            help='Path where the image should be stored after squashing. '
                                 'If not provided, image will be loaded into Docker daemon')

        args = parser.parse_args()

        if args.verbose:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

        self.log.debug("Running version %s", version)

        try:
            squash.Squash(log=self.log, image=args.image,
                          from_layer=args.from_layer, tag=args.tag, output_path=args.output_path, tmp_dir=args.tmp_dir,
                          development=args.development, cleanup=args.cleanup, rebase=args.rebase).run()
        except KeyboardInterrupt:
            self.log.error("Program interrupted by user, exiting...")
            sys.exit(1)
        except:
            e = sys.exc_info()[1]

            if args.development or args.verbose:
                self.log.exception(e)
            else:
                self.log.error(str(e))

            self.log.error("Execution failed, consult logs above. "
                           "If you think this is our fault, please file an issue: "
                           "https://github.com/goldmann/docker-squash/issues, thanks!")

            if isinstance(e, SquashError):
                sys.exit(e.code)

            sys.exit(1)


def run():
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    run()
