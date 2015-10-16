# -*- coding: utf-8 -*-

import argparse
import logging
import sys

from docker_scripts import squash, layers
from docker_scripts.version import version
from docker_scripts.errors import Error

class MyParser(argparse.ArgumentParser):

    def error(self, message):
        self.print_help()
        sys.stderr.write('\nError: %s\n' % message)
        sys.exit(2)


class CLI(object):

    def __init__(self):
        self.log = logging.getLogger()
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
        handler.setFormatter(formatter)
        self.log.addHandler(handler)

    def run_squash(self, args):
        squash.Squash(log=self.log, image=args.image,
                      from_layer=args.from_layer, tag=args.tag, output_path=args.output_path, tmp_dir=args.tmp_dir).run()

    def run_layers(self, args):
        layers.Layers(log=self.log, image=args.image,
                      dockerfile=args.dockerfile, tags=args.tags, machine=args.machine, commands=args.commands).run()

    def run(self):
        parser = MyParser(
            description='Set of helpers scripts fo Docker')

        parser.add_argument(
            '-v', '--verbose', action='store_true', help='Verbose output')

        parser.add_argument(
            '--version', action='version', help='Show version and exit', version=version)

        subparsers = parser.add_subparsers(title='Available commands')

        # Squash
        parser_squash = subparsers.add_parser(
            'squash', help='Squash layers in the specified image')
        parser_squash.set_defaults(func=self.run_squash)
        parser_squash.add_argument('image', help='Image to be squashed')
        parser_squash.add_argument(
            '-f', '--from-layer', help='ID of the layer or image ID or image name. If not specified will squash up to last layer (FROM instruction)')
        parser_squash.add_argument(
            '-t', '--tag', help="Specify the tag to be used for the new image. By default it'll be set to 'image' argument")
        parser_squash.add_argument(
            '--tmp-dir', help='Temporary directory to be used')
        parser_squash.add_argument(
            '--output-path', help='Path where the image should be stored after squashing. If not provided, image will be loaded into Docker daemon')

        # Layers
        parser_layers = subparsers.add_parser(
            'layers', help='Show layers in the specified image')
        parser_layers.set_defaults(func=self.run_layers)
        parser_layers.add_argument(
            'image', help='ID of the layer or image ID or image name')
        parser_layers.add_argument('-c', '--commands', action='store_true',
                                   help='Show commands executed to create the layer (if any)')
        parser_layers.add_argument('-d', '--dockerfile', action='store_true',
                                   help='Create Dockerfile out of the layers [EXPERIMENTAL!]')
        parser_layers.add_argument(
            '-m', '--machine', action='store_true', help='Machine parseable output')
        parser_layers.add_argument(
            '-t', '--tags', action='store_true', help='Print layer tags if available')

        args = parser.parse_args()

        if args.verbose:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

        self.log.debug("Running version %s", version)

        try:
            args.func(args)
        except Error as e:
            self.log.exception(e)
            sys.exit(1)


def run():
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    run()
