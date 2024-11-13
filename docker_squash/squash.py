# -*- coding: utf-8 -*-

import os
from logging import Logger
from typing import Optional

import docker.errors as docker_errors
from packaging import version as packaging_version

from docker_squash.errors import SquashError
from docker_squash.image import Image
from docker_squash.lib import common
from docker_squash.v1_image import V1Image
from docker_squash.v2_image import V2Image
from docker_squash.version import version


class Squash(object):
    def __init__(
        self,
        log,
        image,
        docker=None,
        from_layer: Optional[str] = None,
        tag: Optional[str] = None,
        comment: Optional[str] = "",
        tmp_dir: Optional[str] = None,
        output_path: Optional[str] = None,
        load_image: Optional[bool] = True,
        cleanup: Optional[bool] = False,
    ):
        self.log: Logger = log
        self.docker = docker
        self.image: str = image
        self.from_layer: str = from_layer
        self.tag: str = tag
        self.comment: str = comment
        self.tmp_dir: str = tmp_dir
        self.output_path: str = output_path
        self.load_image: bool = load_image
        self.cleanup: bool = cleanup
        self.development = False

        if tag == image and cleanup:
            log.warning("Tag is the same as image; preventing cleanup")
            self.cleanup = False
        if tmp_dir:
            self.development = True
        if not docker:
            self.docker = common.docker_client(self.log)

    def run(self):
        docker_version = self.docker.version()
        self.log.info(
            "docker-squash version %s, Docker %s, API %s..."
            % (version, docker_version["Version"], docker_version["ApiVersion"])
        )

        if self.image is None:
            raise SquashError("Image is not provided")

        if not (self.output_path or self.load_image):
            self.log.warning(
                "No output path specified and loading into Docker is not selected either; squashed image would not accessible, proceeding with squashing doesn't make sense"
            )
            return

        if self.output_path and os.path.exists(self.output_path):
            self.log.warning(
                "Path '%s' specified as output path where the squashed image should be saved already exists, it'll be overriden"
                % self.output_path
            )

        if packaging_version.parse(
            docker_version["ApiVersion"]
        ) >= packaging_version.parse("1.22"):
            image: Image = V2Image(
                self.log,
                self.docker,
                self.image,
                self.from_layer,
                self.tmp_dir,
                self.tag,
                self.comment,
            )
        else:
            image: Image = V1Image(
                self.log,
                self.docker,
                self.image,
                self.from_layer,
                self.tmp_dir,
                self.tag,
            )

        self.log.info("Using %s image format" % image.FORMAT)

        try:
            return self.squash(image)
        except Exception:
            # https://github.com/goldmann/docker-scripts/issues/44
            # If development mode is not enabled, make sure we clean up the
            # temporary directory
            if not self.development:
                image.cleanup()

            raise

    def _cleanup(self):
        try:
            image_id = self.docker.inspect_image(self.image)["Id"]
        except docker_errors.APIError as ex:
            self.log.warning(
                "Could not get the image ID for {} image: {}, skipping cleanup after squashing".format(
                    self.image, str(ex)
                )
            )
            return

        self.log.info("Removing old {} image...".format(self.image))

        try:
            self.docker.remove_image(image_id, force=False, noprune=False)
            self.log.info("Image {} removed!".format(self.image))
        except docker_errors.APIError as ex:
            self.log.warning(
                "Could not remove image {}: {}, skipping cleanup after squashing".format(
                    self.image, str(ex)
                )
            )

    def squash(self, image: Image):
        # Do the actual squashing
        new_image_id = image.squash()

        self.log.info("New squashed image ID is %s" % new_image_id)

        if self.output_path:
            # Move the tar archive to the specified path
            image.export_tar_archive(self.output_path)

        if self.load_image:
            # Load squashed image into Docker
            image.load_squashed_image()

        # If development mode is not enabled, make sure we clean up the
        # temporary directory
        if not self.development:
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
