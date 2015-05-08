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

# Module level docker connection
# TODO: This could be made configurable later
DOCKER_CLIENT = docker.Client(
    base_url='unix://var/run/docker.sock',
    timeout=240)

# Module level logger
LOG = logging.getLogger()
_HANDLER = logging.StreamHandler()
_FORMATTER = logging.Formatter(
    '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
_HANDLER.setFormatter(_FORMATTER)
LOG.addHandler(_HANDLER)


class Chdir:

    """ Context manager for changing the current working directory """

    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


def _read_layers(layers, image_id):
    """ Reads the JSON metadata for specified layer / image id """

    layer = DOCKER_CLIENT.inspect_image(image_id)
    layers.append(layer['Id'])

    if 'Parent' in layer and layer['Parent']:
        _read_layers(layers, layer['Parent'])


def _save_image(image_id, tar_file):
    """ Saves the image as a tar archive under specified name """

    for x in xrange(3):
        LOG.info("Saving image %s to %s file..." % (image_id, tar_file))
        LOG.debug("Try #%s..." % (x+1))

        try:
            image = DOCKER_CLIENT.get_image(image_id)

            with open(tar_file, 'w') as f:
                f.write(image.data)

            LOG.info("Image saved!")
            return True
        except Exception as e:
            LOG.exception(e)
            LOG.warn("An error occured while saving the %s image, retrying..." % image_id)

    LOG.error("Couldn't save %s image!" % image_id)

    return False

def _unpack(tar_file, directory):
    """ Unpacks tar archive to selected directory """

    LOG.info("Unpacking %s tar file to %s directory" % (tar_file, directory))

    with tarfile.open(tar_file, 'r') as tar:
        tar.extractall(path=directory)

    # Remove the tar file early to save some space
    LOG.debug("Removing exported tar (%s)..." % tar_file)
    os.remove(tar_file)

    LOG.info("Archive unpacked!")


def _move_unmodified_layers(layers, squash_id, src, dest):
    """
    This moves all the layers that should be copied as-is.
    In other words - all layers that are not meant to be squashed will be
    moved from the old image to the new image untouched.
    """
    for layer in layers:
        LOG.debug("Moving unmodified layer %s..." % layer)
        shutil.move(os.path.join(src, layer), dest)
        if layer == squash_id:
            # Stop if we are at the first layer that was squashed
            return


def _marker_files(tar, layer_id):
    """
    Searches for marker files in the specified archive.

    Docker marker files are files taht have the .wh. prefix in the name.
    These files mark the corresponding file to be removed (hidden) when
    we start a container from the image.
    """
    marker_files = {}

    LOG.debug("Searching for marker files in '%s' archive..." % tar.name)

    for member in tar.getmembers():
        if '.wh.' in member.name:
            LOG.debug("Found '%s' marker file" % member.name)
            marker_files[member.name] = member

    if marker_files:
        LOG.debug("Following files are marked to skip in the %s layer: %s" % (
            layer_id, " ".join(marker_files.keys())))

    return marker_files


def _generate_target_json(old_image_id, new_image_id, squash_id, squashed_dir):
    json_file = os.path.join(squashed_dir, "json")
    squashed_tar = os.path.join(squashed_dir, "layer.tar")
    # Read the original metadata
    metadata = DOCKER_CLIENT.inspect_image(old_image_id)

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


def _generate_repositories_json(repositories_file, new_image_id, tag):
    if ':' in tag:
        name, tag = tag.split(':')
    else:
        name = tag
        tag = "latest"

    repos = {}
    repos[name] = {}
    repos[name][tag] = new_image_id

    with open(repositories_file, 'w') as f:
        json.dump(repos, f)


def _generate_image_id():
    while True:
        image_id = hashlib.sha256(str(random.getrandbits(128))).hexdigest()

        try:
            int(image_id[0:10])
        except ValueError:
            # All good!
            return image_id


def _load_image(directory):
    c = cStringIO.StringIO()

    with tarfile.open(mode='w', fileobj=c) as tar:
        LOG.debug("Generating tar archive for the squashed image...")
        with Chdir(directory):
            tar.add(".")
        LOG.debug("Archive generated")

    LOG.info("Loading squashed image...")
    DOCKER_CLIENT.load_image(c.getvalue())
    LOG.info("Image loaded!")

    c.close()


def _layers_to_squash(layers, from_layer):
    """ Prepares a list of layer IDs that should be squashed """
    to_squash = []

    for l in reversed(layers):
        if l == from_layer:
            break

        to_squash.append(l)

    to_squash.reverse()

    return to_squash


def _prepare_tmp_directory(provided_tmp_dir):
    """ Creates temporary directory that is used to work on layers """
    if provided_tmp_dir:
        if os.path.exists(provided_tmp_dir):
            LOG.error(
                "The '%s' directory already exists, please remove it before you proceed, aborting." % provided_tmp_dir)
            sys.exit(1)
        os.makedirs(provided_tmp_dir)
        return provided_tmp_dir
    else:
        return tempfile.mkdtemp(prefix="tmp-docker-squash-")


def _squash_layers(layers_to_squash, squashed_tar_file, old_image_dir):
    # Reverse the layers to squash - we begin with the newest one
    # to make the tar lighter
    layers_to_squash.reverse()

    LOG.info("Starting squashing...")

    with tarfile.open(squashed_tar_file, 'w') as squashed_tar:
        unskipped_markers = {}

        for layer_id in layers_to_squash:
            layer_tar_file = os.path.join(old_image_dir, layer_id, "layer.tar")

            LOG.info("Squashing layer %s..." % layer_id)

            # Open the exiting layer to squash
            with tarfile.open(layer_tar_file, 'r') as layer_tar:
                # Find all marker files for all layers
                markers = _marker_files(layer_tar, layer_id)
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
                    LOG.debug("Following files are marked to skip when squashing layer %s: %s" % (
                        layer_id, to_skip))

                # Copy all the files to the new tar
                for member in layer_tar.getmembers():
                    # Skip files that are marked to be skipped
                    if member.name in to_skip:
                        LOG.debug(
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
                        LOG.debug(
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
            LOG.debug(
                "Adding '%s' marker file back since the file it refers to was not found in any layers we squashed..." % marker_name)
            squashed_tar.addfile(marker['info'], marker['file'])

    LOG.debug("Squashing done!")


def main(args):

    if args.verbose:
        LOG.setLevel(logging.DEBUG)
    else:
        LOG.setLevel(logging.INFO)

    LOG.info("Squashing image '%s'..." % args.image )

    # The image id or name of the image to be squashed
    try:
        old_image_id = DOCKER_CLIENT.inspect_image(args.image)['Id']
    except:
        LOG.error(
            "Could not get the image ID to squash, please check provided 'image' argument: %s" % args.image)
        sys.exit(1)

    if args.tag:
        if ':' in args.tag:
            tag = args.tag
        else:
            tag = "%s:latest" % args.tag
    else:
        tag = args.image

    old_layers = []

    # Read all layers in the image
    _read_layers(old_layers, old_image_id)

    old_layers.reverse()

    # The id or name of the layer/image that the squashing should begin from
    # This layer WILL NOT be squashed, but all next layers will
    if args.from_layer:
      from_layer = args.from_layer
    else:
      from_layer = old_layers[0]

    try:
        squash_id = DOCKER_CLIENT.inspect_image(from_layer)['Id']
    except:
        LOG.error(
            "Could not get the layer ID to squash, please check provided 'layer' argument: %s" % from_layer)
        sys.exit(1)

    LOG.info("Old image has %s layers", len(old_layers))
    LOG.debug("Old layers: %s", old_layers)

    if not squash_id in old_layers:
        LOG.error("Couldn't find the provided layer (%s) in the %s image" % (
            args.layer, args.image))
        sys.exit(1)

    # Find the layers to squash
    layers_to_squash = _layers_to_squash(old_layers, squash_id)

    LOG.info("Attepmting to squash from layer %s...", squash_id)
    LOG.info("Checking if squashing is necessary...")

    if len(layers_to_squash) <= 1:
        LOG.warning("%s layer(s) in this image marked to squash, no squashing is required, exiting" % len(layers_to_squash))
        sys.exit(0)

    LOG.info("We have %s layers to squash", len(layers_to_squash))
    LOG.debug("Layers to squash: %s", layers_to_squash)

    # Prepare temporary directory where all the work will be executed
    tmp_dir = _prepare_tmp_directory(args.tmp_dir)

    # Location of the tar with the old image
    old_image_tar = os.path.join(tmp_dir, "image.tar")

    # Save the image in tar format in the tepmorary directory
    if not _save_image(old_image_id, old_image_tar):
      sys.exit(1)

    # Directory where the old layers will be unpacked
    old_image_dir = os.path.join(tmp_dir, "old")
    os.makedirs(old_image_dir)

    # Unpack the image
    _unpack(old_image_tar, old_image_dir)

    # Directory where the new layers will be unpacked in prepareation to
    # import it to Docker
    new_image_dir = os.path.join(tmp_dir, "new")
    os.makedirs(new_image_dir)

    # Generate a new image id for the squashed layer
    new_image_id = _generate_image_id()

    LOG.info("New layer ID for squashed content will be: %s" % new_image_id)

    # Prepare a directory for squashed layer content
    squashed_dir = os.path.join(new_image_dir, new_image_id)
    os.makedirs(squashed_dir)

    # Location of the tar archive with the squashed layers
    squashed_tar = os.path.join(squashed_dir, "layer.tar")

    # Append all the layers on each other
    _squash_layers(layers_to_squash, squashed_tar, old_image_dir)

    # Move all the layers that should be untouched
    _move_unmodified_layers(
        old_layers, squash_id, old_image_dir, new_image_dir)

    # Generate the metadata JSON based on the original one
    _generate_target_json(old_image_id, new_image_id, squash_id, squashed_dir)

    # Generate the metadata JSON with information about the images
    _generate_repositories_json(
        os.path.join(new_image_dir, "repositories"), new_image_id, tag)

    # And finally tar everything up and load into Docker
    _load_image(new_image_dir)

    # Cleanup the temporary directory
    shutil.rmtree(tmp_dir)

    LOG.info("Finished, image registered as '%s'", tag)

if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(
        description='Squashes all layers in the image from the layer specified as "layer" argument.')
    PARSER.add_argument('image', help='Image to be squashed')
    PARSER.add_argument(
        '-f', '--from-layer', help='ID of the layer or image ID or image name. If not specified will squash up to last layer (FROM instruction)')
    PARSER.add_argument(
        '-t', '--tag', help="Specify the tag to be used for the new image. By default it'll be set to 'image' argument")
    PARSER.add_argument(
        '--tmp-dir', help='Temporary directory to be used')
    PARSER.add_argument(
        '-v', '--verbose', action='store_true', help='Verbose output')
    ARGS = PARSER.parse_args()

    main(ARGS)
