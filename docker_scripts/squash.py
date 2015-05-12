# -*- coding: utf-8 -*-

import sys
import json
import argparse
import tempfile
import shutil
import os

import random
import hashlib
import datetime
import docker
import logging
import tarfile
import cStringIO


class Chdir:

    """ Context manager for changing the current working directory """

    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


class Squash:

    def __init__(self, log, docker, image, from_layer=None, tag=None, tmp_dir=None):
        self.log = log
        self.docker = docker
        self.image = image
        self.from_layer = from_layer
        self.tag = tag
        self.tmp_dir = tmp_dir

    def _read_layers(self, layers, image_id):
        """ Reads the JSON metadata for specified layer / image id """

        layer = self.docker.inspect_image(image_id)
        layers.append(layer['Id'])

        if 'Parent' in layer and layer['Parent']:
            self._read_layers(layers, layer['Parent'])

    def _save_image(self, image_id, tar_file):
        """ Saves the image as a tar archive under specified name """

        for x in xrange(3):
            self.log.info("Saving image %s to %s file..." %
                          (image_id, tar_file))
            self.log.debug("Try #%s..." % (x + 1))

            try:
                image = self.docker.get_image(image_id)

                with open(tar_file, 'w') as f:
                    f.write(image.data)

                self.log.info("Image saved!")
                return True
            except Exception as e:
                self.log.exception(e)
                self.log.warn(
                    "An error occured while saving the %s image, retrying..." % image_id)

        self.log.error("Couldn't save %s image!" % image_id)

        return False

    def _unpack(self, tar_file, directory):
        """ Unpacks tar archive to selected directory """

        self.log.info("Unpacking %s tar file to %s directory" %
                      (tar_file, directory))

        with tarfile.open(tar_file, 'r') as tar:
            tar.extractall(path=directory)

        # Remove the tar file early to save some space
        self.log.debug("Removing exported tar (%s)..." % tar_file)
        os.remove(tar_file)

        self.log.info("Archive unpacked!")

    def _move_unmodified_layers(self, layers, squash_id, src, dest):
        """
        This moves all the layers that should be copied as-is.
        In other words - all layers that are not meant to be squashed will be
        moved from the old image to the new image untouched.
        """
        for layer in layers:
            self.log.debug("Moving unmodified layer %s..." % layer)
            shutil.move(os.path.join(src, layer), dest)
            if layer == squash_id:
                # Stop if we are at the first layer that was squashed
                return

    def _marker_files(self, tar, layer_id):
        """
        Searches for marker files in the specified archive.

        Docker marker files are files taht have the .wh. prefix in the name.
        These files mark the corresponding file to be removed (hidden) when
        we start a container from the image.
        """
        marker_files = {}

        self.log.debug(
            "Searching for marker files in '%s' archive..." % tar.name)

        for member in tar.getmembers():
            if '.wh.' in member.name:
                self.log.debug("Found '%s' marker file" % member.name)
                marker_files[member.name] = member

        if marker_files:
            self.log.debug("Following files are marked to skip in the %s layer: %s" % (
                layer_id, " ".join(marker_files.keys())))

        return marker_files

    def _generate_target_json(self, old_image_id, new_image_id, squash_id, squashed_dir):
        json_file = os.path.join(squashed_dir, "json")
        squashed_tar = os.path.join(squashed_dir, "layer.tar")
        # Read the original metadata
        metadata = self.docker.inspect_image(old_image_id)

        # Update the fields
        metadata['Id'] = new_image_id
        metadata['Parent'] = squash_id
        metadata['Config']['Image'] = squash_id
        metadata['Created'] = datetime.datetime.utcnow().strftime(
            '%Y-%m-%dT%H:%M:%S.%fZ')
        metadata['Size'] = os.path.getsize(squashed_tar)

        # Remove unnecessary fields
        del metadata['ContainerConfig']
        del metadata['Container']
        del metadata['Config']['Hostname']

        with open(json_file, 'w') as f:
            json.dump(metadata, f)

    def _generate_repositories_json(self, repositories_file, new_image_id, name, tag):
        repos = {}
        repos[name] = {}
        repos[name][tag] = new_image_id

        with open(repositories_file, 'w') as f:
            json.dump(repos, f)

    def _generate_image_id(self):
        while True:
            image_id = hashlib.sha256(str(random.getrandbits(128))).hexdigest()

            try:
                int(image_id[0:10])
            except ValueError:
                # All good!
                return image_id

    def _load_image(self, directory):
        c = cStringIO.StringIO()

        with tarfile.open(mode='w', fileobj=c) as tar:
            self.log.debug("Generating tar archive for the squashed image...")
            with Chdir(directory):
                tar.add(".")
            self.log.debug("Archive generated")

        self.log.info("Loading squashed image...")
        self.docker.load_image(c.getvalue())
        self.log.info("Image loaded!")

        c.close()

    def _layers_to_squash(self, layers, from_layer):
        """ Prepares a list of layer IDs that should be squashed """
        to_squash = []

        for l in reversed(layers):
            if l == from_layer:
                break

            to_squash.append(l)

        to_squash.reverse()

        return to_squash

    def _prepare_tmp_directory(self, provided_tmp_dir):
        """ Creates temporary directory that is used to work on layers """
        if provided_tmp_dir:
            if os.path.exists(provided_tmp_dir):
                self.log.error(
                    "The '%s' directory already exists, please remove it before you proceed, aborting." % provided_tmp_dir)
                sys.exit(1)
            os.makedirs(provided_tmp_dir)
            return provided_tmp_dir
        else:
            return tempfile.mkdtemp(prefix="tmp-docker-squash-")

    def _parse_image_name(self, image):
        if ':' in image and not '/' in image.split(':')[-1]:
            image_tag = image.split(':')[-1]
            image_name = image[:-(len(image_tag) + 1)]
        else:
            image_tag = "latest"
            image_name = image

        return (image_name, image_tag)

    def _squash_layers(self, layers_to_squash, squashed_tar_file, old_image_dir):
        # Reverse the layers to squash - we begin with the newest one
        # to make the tar lighter
        layers_to_squash.reverse()

        self.log.info("Starting squashing...")

        with tarfile.open(squashed_tar_file, 'w') as squashed_tar:
            unskipped_markers = {}

            for layer_id in layers_to_squash:
                layer_tar_file = os.path.join(
                    old_image_dir, layer_id, "layer.tar")

                self.log.info("Squashing layer %s..." % layer_id)

                # Open the exiting layer to squash
                with tarfile.open(layer_tar_file, 'r') as layer_tar:
                    # Find all marker files for all layers
                    markers = self._marker_files(layer_tar, layer_id)
                    tar_files = [o.name for o in layer_tar.getmembers()]

                    to_skip = []

                    for marker_name in unskipped_markers.keys():
                        actual_file = marker_name.replace('.wh.', '')

                        if actual_file in tar_files:
                            to_skip.append(marker_name)
                            to_skip.append(actual_file)
                            del(unskipped_markers[marker_name])

                    for marker_name, marker in markers.iteritems():
                        actual_file = marker_name.replace('.wh.', '')
                        to_skip.append(marker_name)

                        if actual_file in tar_files:
                            to_skip.append(actual_file)
                        else:
                            # We can safely add the file content, because marker
                            # files are empty
                            unskipped_markers[marker_name] = {
                                'file': layer_tar.extractfile(marker), 'info': marker}

                    if to_skip:
                        self.log.debug("Following files are marked to skip when squashing layer %s: %s" % (
                            layer_id, to_skip))

                    # Copy all the files to the new tar
                    for member in layer_tar.getmembers():
                        # Skip files that are marked to be skipped
                        if member.name in to_skip:
                            self.log.debug(
                                "Skipping '%s' file because it's on the list to skip files" % member.name)
                            continue

                        # List of filenames in the squashed archive
                        squashed_files = [
                            o.name for o in squashed_tar.getmembers()]

                        # Check if file is already added to the archive
                        if member.name in squashed_files:
                            # File already exist in the squashed archive, skip it because
                            # file want to add is older than the one already in the archive.
                            # This is true because we do reverse squashing - from
                            # newer to older layer
                            self.log.debug(
                                "Skipping '%s' file because it's older than file already added to the archive" % member.name)
                            continue

                        if member.issym():
                            # Special case: symlinks
                            squashed_tar.addfile(member)
                        else:
                            # Finally add the file to archive
                            squashed_tar.addfile(
                                member, layer_tar.extractfile(member))

            # We copied all the files from all layers, but if there are
            # still some marker files - we need to add them back because these
            # remove (technically: hide) files from layers unaffected
            # by squashing
            for marker_name, marker in unskipped_markers.iteritems():
                self.log.debug(
                    "Adding '%s' marker file back since the file it refers to was not found in any layers we squashed..." % marker_name)
                squashed_tar.addfile(marker['info'], marker['file'])

        self.log.debug("Squashing done!")

    def run(self):

        self.log.info("Squashing image '%s'..." % self.image)

        # The image id or name of the image to be squashed
        try:
            old_image_id = self.docker.inspect_image(self.image)['Id']
        except:
            self.log.error(
                "Could not get the image ID to squash, please check provided 'image' argument: %s" % self.image)
            sys.exit(1)

        if self.tag:
            image_name, image_tag = self._parse_image_name(self.tag)
        else:
            image_name, image_tag = self._parse_image_name(self.image)

        old_layers = []

        # Read all layers in the image
        self._read_layers(old_layers, old_image_id)

        old_layers.reverse()

        # The id or name of the layer/image that the squashing should begin from
        # This layer WILL NOT be squashed, but all next layers will
        if self.from_layer:
            from_layer = self.from_layer
        else:
            from_layer = old_layers[0]

        try:
            squash_id = self.docker.inspect_image(from_layer)['Id']
        except:
            self.log.error(
                "Could not get the layer ID to squash, please check provided 'layer' argument: %s" % from_layer)
            sys.exit(1)

        self.log.info("Old image has %s layers", len(old_layers))
        self.log.debug("Old layers: %s", old_layers)

        if not squash_id in old_layers:
            self.log.error("Couldn't find the provided layer (%s) in the %s image" % (
                self.layer, self.image))
            sys.exit(1)

        # Find the layers to squash
        layers_to_squash = self._layers_to_squash(old_layers, squash_id)

        self.log.info("Attempting to squash from layer %s...", squash_id)
        self.log.info("Checking if squashing is necessary...")

        if len(layers_to_squash) <= 1:
            self.log.warning(
                "%s layer(s) in this image marked to squash, no squashing is required, exiting" % len(layers_to_squash))
            sys.exit(0)

        self.log.info("We have %s layers to squash", len(layers_to_squash))
        self.log.debug("Layers to squash: %s", layers_to_squash)

        # Prepare temporary directory where all the work will be executed
        tmp_dir = self._prepare_tmp_directory(self.tmp_dir)

        # Location of the tar with the old image
        old_image_tar = os.path.join(tmp_dir, "image.tar")

        # Save the image in tar format in the tepmorary directory
        if not self._save_image(old_image_id, old_image_tar):
            sys.exit(1)

        # Directory where the old layers will be unpacked
        old_image_dir = os.path.join(tmp_dir, "old")
        os.makedirs(old_image_dir)

        # Unpack the image
        self._unpack(old_image_tar, old_image_dir)

        # Directory where the new layers will be unpacked in prepareation to
        # import it to Docker
        new_image_dir = os.path.join(tmp_dir, "new")
        os.makedirs(new_image_dir)

        # Generate a new image id for the squashed layer
        new_image_id = self._generate_image_id()

        self.log.info(
            "New layer ID for squashed content will be: %s" % new_image_id)

        # Prepare a directory for squashed layer content
        squashed_dir = os.path.join(new_image_dir, new_image_id)
        os.makedirs(squashed_dir)

        # Location of the tar archive with the squashed layers
        squashed_tar = os.path.join(squashed_dir, "layer.tar")

        # Append all the layers on each other
        self._squash_layers(layers_to_squash, squashed_tar, old_image_dir)

        # Move all the layers that should be untouched
        self._move_unmodified_layers(
            old_layers, squash_id, old_image_dir, new_image_dir)

        # Generate the metadata JSON based on the original one
        self._generate_target_json(
            old_image_id, new_image_id, squash_id, squashed_dir)

        # Generate the metadata JSON with information about the images
        self._generate_repositories_json(
            os.path.join(new_image_dir, "repositories"), new_image_id, image_name, image_tag)

        # And finally tar everything up and load into Docker
        self._load_image(new_image_dir)

        # Cleanup the temporary directory
        shutil.rmtree(tmp_dir)

        self.log.info("Finished, image registered as '%s:%s'" %
                      (image_name, image_tag))
