# -*- coding: utf-8 -*-

import os
import uuid

from distutils.version import StrictVersion

from docker_squash.v1_image import V1Image
from docker_squash.v2_image import V2Image
from docker_squash.lib import common
from docker_squash.errors import SquashError
from docker_squash.version import version


class Squash(object):

    def __init__(self, log, image, docker=None, from_layer=None, tag=None, tmp_dir=None,
                 output_path=None, load_image=True, development=False, cleanup=False):
        self.log = log
        self.docker = docker
        self.image = image
        self.from_layer = from_layer
        self.tag = tag
        self.tmp_tag = "docker-squash-%s" % uuid.uuid4().hex[:8]
        self.tmp_dir = tmp_dir
        self.output_path = output_path
        self.load_image = load_image
        self.development = development
        self.cleanup = cleanup

        if not docker:
            self.docker = common.docker_client(self.log)

    def run(self):
        docker_version = self.docker.version()
        self.log.info("docker-squash version %s, Docker %s, API %s..." %
                      (version, docker_version['GitCommit'], docker_version['ApiVersion']))

        if self.image is None:
            raise SquashError("Image is not provided")

        if not (self.output_path or self.load_image):
            self.log.warn(
                "No output path specified and loading into Docker is not selected either; squashed image would not accessible, proceeding with squashing doesn't make sense")
            return

        if self.output_path and os.path.exists(self.output_path):
            self.log.warn(
                "Path '%s' specified as output path where the squashed image should be saved already exists, it'll be overriden" % self.output_path)

        if StrictVersion(docker_version['ApiVersion']) >= StrictVersion("1.22"):
            image = V2Image(self.log, self.docker, self.image,
                            self.from_layer, self.tmp_dir, self.tmp_tag)
        else:
            image = V1Image(self.log, self.docker, self.image,
                            self.from_layer, self.tmp_dir, self.tmp_tag)

        self.log.info("Using %s image format" % image.FORMAT)

        try:
            return self.squash(image)
        except:
            # https://github.com/goldmann/docker-scripts/issues/44
            # If development mode is not enabled, make sure we clean up the
            # temporary directory
            if not self.development:
                image.cleanup()

            raise

    def _remove_image(self, image_name, remove_by_id=True):
        try:
            image = self.docker.inspect_image(image_name)['Id'] if remove_by_id else image_name
        except:
            self.log.warn("Could not get the image ID for %s image, skipping cleanup after squashing" % self.image)
            return

        self.log.info("Removing old %s image..." % image_name)
        self.docker.remove_image(image, force=False, noprune=False)
        self.log.info("Image removed!")

    def _cleanup(self):
        self._remove_image(self.image)
        # https://github.com/goldmann/docker-squash/issues/172
        # Use temporary image and create the desired name base on it
        # so we will not delete the requested image when source==target image
        self._switch_tmp_image_to_target_tag()

    def _switch_tmp_image_to_target_tag(self):
        if self.tag:
            image,tag = self.tag.split(":", 2) if ":" in self.tag else (self.tag, None)
            # tag the client requested tag same as the new squashed image name by tmp_lable
            self.docker.tag(self.tmp_tag, image, tag=tag, force=True)
            # remove by name since both have the same SHAID
            self._remove_image(self.tmp_tag, remove_by_id=False)

    def squash(self, image):
        # Do the actual squashing
        new_image_id = image.squash()

        self.log.info("New squashed image ID is %s" % new_image_id)

        if self.output_path:
            # Move the tar archive to the specified path
            image.export_tar_archive(self.output_path)

        if self.load_image:
            # Load squashed image into Docker
            image.load_squashed_image()

        # Clean up all temporary files
        image.cleanup()

        # Remove the source image - this is the only possible way
        # to remove orphaned layers from Docker daemon at the build time.
        # We cannot use here a tag name because it could be used as the target,
        # squashed image tag - we need to use the image ID.
        if self.cleanup:
            self._cleanup()

        self.log.info("Done")

        return new_image_id
