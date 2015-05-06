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

d = docker.Client(base_url='unix://var/run/docker.sock', timeout = 240)

log = logging.getLogger()
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)
log.setLevel(logging.DEBUG)

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

  layer = d.inspect_image(image_id)
  layers.append(layer['Id'])

  if 'Parent' in layer and layer['Parent']:
    _read_layers(layers, layer['Parent'])

def _save_image(image_id, tar_file):
  """ Saves the image as a tar archive under specified name """

  log.debug("Saving image %s to %s file..." % (image_id, tar_file))

  image = d.get_image(image_id)

  with open(tar_file, 'w') as f:
    f.write(image.data)

  log.debug("Image saved!")

def _unpack(tar_file, directory):
  """ Unpacks tar archive to selected directory """

  log.debug("Unpacking %s tar file to %s directory" % (tar_file, directory))

  with tarfile.open(tar_file, 'r') as tar:
    tar.extractall(path=directory)

  log.debug("Archive unpacked!")

def _move_unmodified_layers(layers, squash_id, src, dest):
  """
  This moves all the layers that should be copied as-is.
  In other words - all layers that are not meant to be squashed will be
  moved from the old image to the new image untouched.
  """
  for layer in layers:
    log.debug("Moving umnodified layer %s..." % layer)
    shutil.move(os.path.join(src, layer), dest)
    if layer == squash_id:
      # Stop if we are at the first layer that was squashed
      return

def _files_to_skip(to_squash, old_image_dir):
  to_skip = []

  log.debug("Searching for marker files...")

  for layer_id in to_squash:
    layer_tar = os.path.join(old_image_dir, layer_id, "layer.tar")

    log.debug("Searching for marker files in '%s' archive..." % layer_tar)

    with tarfile.open(layer_tar, 'r') as tar:
      for member in tar.getmembers():
        if '.wh.' in member.name:
          log.debug("Found '%s' marker file" % member.name)
          to_skip.append(member.name)
          to_skip.append(member.name.replace('.wh.', ''))

  if to_skip:
    log.debug("Following files were found: %s" % " ".join(to_skip))

  return to_skip

def _generate_target_json(old_image_id, new_image_id, squash_id, squashed_dir):
  json_file = os.path.join(squashed_dir, "json")
  squashed_tar = os.path.join(squashed_dir, "layer.tar")
  # Read the original metadata
  metadata = d.inspect_image(old_image_id)

  # Update the fields
  metadata['Id'] = new_image_id
  metadata['Parent'] = squash_id
  metadata['Config']['Image'] = squash_id
  metadata['Created'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
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

def _load_image(directory):
  c = cStringIO.StringIO()

  with tarfile.open(mode='w', fileobj=c) as tar:
    log.debug("Generating tar archive for the squashed image...")
    with Chdir(directory):
      tar.add(".")
    log.debug("Archive generated")

  log.debug("Uploading image...")
  d.load_image(c.getvalue())
  log.debug("Image uploaded")

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
      log.error("The '%s' directory already exists, please remove it before you proceed, aborting." % provided_tmp_dir)
      sys.exit(1)
    os.makedirs(provided_tmp_dir)
    return provided_tmp_dir
  else:
    return tempfile.mkdtemp(prefix="tmp-docker-squash-")

def _squash_layers(layers_to_squash, squashed_tar_file, old_image_dir):

  # Find all files that should be skipped
  #
  # TODO: we probably should do it for current layer and
  # apply only on the previous layer
  to_skip = _files_to_skip(layers_to_squash, old_image_dir)

  log.debug("Starting squashing...")

  with tarfile.open(squashed_tar_file, 'w') as squashed_tar:

    for layer_id in layers_to_squash:
      layer_tar_file = os.path.join(old_image_dir, layer_id, "layer.tar")

      log.debug("Squashing layer %s..." % layer_id)

      # Open the exiting layer to squash
      with tarfile.open(layer_tar_file, 'r') as layer_tar:

        # Copy all the files to the new tar
        for member in layer_tar.getmembers():
          if not member.name in to_skip:
            # Special case: symlinks
            if member.issym():
              squashed_tar.addfile(member)
            else:
              squashed_tar.addfile(member, layer_tar.extractfile(member))
          else:
            log.debug("Skipping '%s' file because it's on the list to skip files" % member.name)

    log.debug("Squashing done!")

def main(args):

  # The image id or name of the image to be squashed
  try:
    old_image_id = d.inspect_image(args.image)['Id']
  except:
    log.error("Could not get the image ID to squash, please check provided 'image' argument: %s" % args.image)
    sys.exit(1)

  # The id or name of the layer/image that the squashing should begin from
  # This layer WILL NOT be squashed, but all next layers will
  try:
    squash_id = d.inspect_image(args.layer)['Id']
  except:
    log.error("Could not get the layer ID to squash, please check provided 'layer' argument: %s" % args.layer)
    sys.exit(1)

  old_layers = []

  # Read all layers in the image
  _read_layers(old_layers, old_image_id)

  old_layers.reverse()

  log.info("Old image has %s layers", len(old_layers))
  log.debug("Old layers: %s", old_layers)

  if not squash_id in old_layers:
    log.error("Couldn't find the provided layer (%s) in the %s image" % (args.layer, args.image))
    sys.exit(1)

  # Find the layers to squash
  layers_to_squash = _layers_to_squash(old_layers, squash_id)

  log.info("We have %s layers to squash", len(layers_to_squash))
  log.debug("Layers to squash: %s", layers_to_squash)

  if len(layers_to_squash) == 0:
    log.error("There are no layers to squash, aborting")
    sys.exit(1)

  # Prepare temporary directory where all the work will be executed
  tmp_dir = _prepare_tmp_directory(args.tmp_dir)

  # Location of the tar with the old image
  old_image_tar = os.path.join(tmp_dir, "image.tar")

  # Save the image in tar format in the tepmorary directory 
  _save_image(old_image_id, old_image_tar)

  # Directory where the old layers will be unpacked
  old_image_dir = os.path.join(tmp_dir, "old")
  os.makedirs(old_image_dir)

  # Unpack the image
  log.info("Unpacking exported tar (%s)..." % old_image_tar)
  _unpack(old_image_tar, old_image_dir)

  # Remove the tar file early to save some space
  log.info("Removing exported tar (%s)..." % old_image_tar)
  os.remove(old_image_tar)

  # Directory where the new layers will be unpacked in prepareation to
  # import it to Docker
  new_image_dir = os.path.join(tmp_dir, "new")
  os.makedirs(new_image_dir)

  # Generate a new image id for the squashed layer
  new_image_id = hashlib.sha256(str(random.getrandbits(128))).hexdigest()

  log.info("New layer ID for squashed content will be: %s" % new_image_id)

  # Prepare a directory for squashed layer content
  squashed_dir = os.path.join(new_image_dir, new_image_id)
  os.makedirs(squashed_dir)

  # Location of the tar archive with the squashed layers
  squashed_tar = os.path.join(squashed_dir, "layer.tar")

  # Append all the layers on each other
  _squash_layers(layers_to_squash, squashed_tar, old_image_dir)

  # Move all the layers that should be untouched
  _move_unmodified_layers(old_layers, squash_id, old_image_dir, new_image_dir)

  # Generate the metadata JSON based on the original one
  _generate_target_json(old_image_id, new_image_id, squash_id, squashed_dir)
  
  # Generate the metadata JSON with information about the images
  _generate_repositories_json(os.path.join(new_image_dir, "repositories"), new_image_id, args.tag)

  # And finally tar everything up and load into Docker
  _load_image(new_image_dir)

  # Cleanup the temporary directory
  shutil.rmtree(tmp_dir)

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Squashes all layers in the image from the layer specified as "layer" argument.')
  parser.add_argument('image', help='Image to be squashed')
  parser.add_argument('layer', help='ID of the layer or image ID or image name')
  parser.add_argument('tag', help='Specify the tag to be used for the new image')
  parser.add_argument('-t', '--tmp-dir', help='Temporary directory to be used')
  args = parser.parse_args()

  main(args)
