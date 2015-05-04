# -*- coding: utf-8 -*-

import sys
import subprocess
import json
import argparse
import tempfile
import shutil
import os

import random
import hashlib
import datetime
import docker

# TODO Maybe use Python's tarfile? Dunno if it's possible to append to a file

d = docker.Client(base_url='unix://var/run/docker.sock')

def _read_layers(layers, image_id):
  """ Reads the JSON metadata for specified layer / image id """

  layer = d.inspect_image(image_id)
  layers.append(layer['Id'])

  if 'Parent' in layer and layer['Parent']:
    _read_layers(layers, layer['Parent'])

  layers.reverse()

def _save_image(image_id, f):
  """ Saves the image as a tar archive under specified name """

  image = d.get_image(image_id)
  image_tar = open(f,'w')
  image_tar.write(image.data)
  image_tar.close()

def _unpack(tar, directory):
  """ Unpacks the exported tar archive to selected directory """
  try:
    subprocess.check_output("tar -xf %s -C %s" % (tar, directory), shell=True)
  except subprocess.CalledProcessError as e:
    print e
    print "Error while unpacking %s file to %s directory." % (tar, directory)
    sys.exit(2)

def _move_layers(layers, squash_id, src, dest):
  """
  This moves all the layers that should be copied as-is.
  In other words - all layers that are not meant to be squashed will be
  moved from the old image to the new image untouched.
  """
  for layer in reversed(layers):
    shutil.move(os.path.join(src, layer), dest)
    if layer == squash_id:
      return

def _marker_files(tar):
  markers = []

  try:
    files = subprocess.check_output("tar -tf %s" % tar, shell=True).strip().split('\n')
  except subprocess.CalledProcessError as e:
    print e
    print "Error while reading marker files from %s archive." % tar
    sys.exit(2)

  for f in files:
    if '.wh.' in f:
      markers.append(f)

  return markers

def _generate_target_json(old_image_id, new_image_id, squash_id, squashed_dir):
  json_file = os.path.join(squashed_dir, "json")
  # Read the original metadata
  metadata = d.inspect_image(old_image_id)

  # Update the fields
  metadata['Id'] = new_image_id
  metadata['Parent'] = squash_id
  metadata['Config']['Image'] = squash_id
  metadata['Created'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

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
  try:
    subprocess.check_output("cd %s && tar -cf - . | docker load" % directory, shell=True)
  except subprocess.CalledProcessError as e:
    print e
    print "Error while loading the created image from %s directory." % directory
    sys.exit(2)

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
      print "The '%s' directory already exists, please remove it before you proceed, aborting." % provided_tmp_dir
      sys.exit(1)
    os.makedirs(provided_tmp_dir)
    return provided_tmp_dir
  else:
    return tempfile.mkdtemp(prefix="tmp-docker-squash-")

def _append_layers(to_squash, squashed_tar, old_image_dir):
  # Move the first layer that is marked to be squashed.
  # This will be the base for all other layers - we'll
  # append to this base tar file.
  shutil.move(os.path.join(old_image_dir, to_squash[0], "layer.tar"), squashed_tar)

  # Remove the first element, since we already moved the layer
  del to_squash[0]

  # We have the first layer avialable, let's append
  # all subsequent layers to that one
  for layer_id in to_squash:
    layer_tar = os.path.join(old_image_dir, layer_id, "layer.tar")
    # TODO Use --delete to remove duplicate files to save space
    try:
      subprocess.check_output("tar -f %s -A %s" % (squashed_tar, layer_tar), shell=True)
    except subprocess.CalledProcessError as e:
      print "Error while combining %s archive with %s file." % (layer_tar, squashed_tar)
      sys.exit(2)

# TODO symlinks / hardlinks
def _clean_squashed_tar(squashed_tar):
  for f in _marker_files(squashed_tar):
    # Remove the marker files itself
    subprocess.check_output("tar -f %s --delete %s" % (squashed_tar, f), shell=True)
    # Remove the files that were marked to be deleted
    subprocess.check_output("tar -f %s --delete %s" % (squashed_tar, f.replace('.wh.', '')), shell=True)

def main(args):

  # The image id or name of the image to be squashed
  old_image_id = args.image
  # The id or name of the layer/image that the squashing should begin from
  # This layer WILL NOT be squashed, but all next layers will
  try:
    squash_id = d.inspect_image(args.layer)['Id']
  except:
    print "Could not get the layer ID to squash, please check provided 'layer' argument: %s" % args.layer
    sys.exit(1)

  old_layers = []

  # Read all layers in the image
  _read_layers(old_layers, old_image_id)

  if not squash_id in old_layers:
    print "Couldn't find the provided layer (%s) in the %s image" % (args.layer, args.image)
    sys.exit(1)

  # Find the layers to squash
  to_squash = _layers_to_squash(old_layers, squash_id)

  if len(to_squash) == 0:
    print "There are no layers to squash, aborting."
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
  _unpack(old_image_tar, old_image_dir)

  # Remove the tar file early to save some space
  os.remove(old_image_tar)

  # Directory where the new layers will be unpacked in prepareation to
  # import it to Docker
  new_image_dir = os.path.join(tmp_dir, "new")
  os.makedirs(new_image_dir)

  # Generate a new image id for the squashed layer
  new_image_id = hashlib.sha256(str(random.getrandbits(128))).hexdigest()

  # Prepare a directory for squashed layer content
  squashed_dir = os.path.join(new_image_dir, new_image_id)
  os.makedirs(squashed_dir)

  # Location of the tar archive with the squashed layers
  squashed_tar = os.path.join(squashed_dir, "layer.tar")

  # Append all the layers on each other
  _append_layers(to_squash, squashed_tar, old_image_dir)

  # Move all the layers that should be untouched
  _move_layers(old_layers, squash_id, old_image_dir, new_image_dir)

  # Handle marker files
  _clean_squashed_tar(squashed_tar)

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
