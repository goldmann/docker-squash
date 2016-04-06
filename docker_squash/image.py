
import datetime
import hashlib
import json
import os
import re
import shutil
import six
import tarfile
import tempfile

from docker_squash.errors import SquashError

if not six.PY3:
    import docker_squash.lib.xtarfile


class Chdir(object):

    """ Context manager for changing the current working directory """

    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


class Image(object):
    """
    Base class for all Docker image formats. Contains many functions that are handy
    while squashing the image.

    This class should not be used directly.
    """

    FORMAT = None
    """ Image format version """

    def __init__(self, log, docker, image, from_layer, tmp_dir=None, tag=None):
        self.log = log
        self.docker = docker
        self.image = image
        self.from_layer = from_layer
        self.tag = tag
        self.image_name = None
        self.image_tag = None
        self.squash_id = None

        # Workaround for https://play.golang.org/p/sCsWMXYxqy
        #
        # Golang doesn't add padding to microseconds when marshaling
        # microseconds in date into JSON. Python does.
        # We need to produce same output as Docker's to not generate
        # different metadata. That's why we need to strip all zeros at the
        # end of the date string...
        self.date = re.sub(
            r'0*Z$', 'Z', datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        """ Date used in metadata, already formatted using the `%Y-%m-%dT%H:%M:%S.%fZ` format """

        self.tmp_dir = tmp_dir
        """ Main temporary directory to save all working files. This is the root directory for all other temporary files. """

    def squash(self):
        self._before_squashing()
        ret = self._squash()
        self._after_squashing()

        return ret

    def _squash(self):
        pass

    def cleanup(self):
        """ Cleanup the temporary directory """

        self.log.debug("Cleaning up %s temporary directory" % self.tmp_dir)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _initialize_directories(self):
        # Prepare temporary directory where all the work will be executed
        try:
            self.tmp_dir = self._prepare_tmp_directory(self.tmp_dir)
        except:
            raise SquashError("Preparing temporary directory failed")

        # Temporary location on the disk of the old, unpacked *image*
        self.old_image_dir = os.path.join(self.tmp_dir, "old")
        # Temporary location on the disk of the new, unpacked, squashed *image*
        self.new_image_dir = os.path.join(self.tmp_dir, "new")
        # Temporary location on the disk of the squashed *layer*
        self.squashed_dir = os.path.join(self.new_image_dir, "squashed")

        for d in self.old_image_dir, self.new_image_dir:
            os.makedirs(d)

    def _squash_id(self, layer):
        if layer == "<missing>":
            self.log.warn(
                "You try to squash from layer that does not have it's own ID, we'll try to find it later")
            return None

        try:
            squash_id = self.docker.inspect_image(layer)['Id']
        except:
            raise SquashError(
                "Could not get the layer ID to squash, please check provided 'layer' argument: %s" % layer)

        if squash_id not in self.old_image_layers:
            raise SquashError(
                "Couldn't find the provided layer (%s) in the %s image" % (layer, self.image))

        self.log.debug("Layer ID to squash from: %s" % squash_id)

        return squash_id

    def _validate_number_of_layers(self, number_of_layers):
        """
        Makes sure that the specified number of layers to squash
        is a valid number
        """

        # Only positive numbers are correct
        if number_of_layers <= 0:
            raise SquashError(
                "Number of layers to squash cannot be less or equal 0, provided: %s" % number_of_layers)

        # Do not squash if provided number of layer to squash is bigger
        # than number of actual layers in the image
        if number_of_layers > len(self.old_image_layers):
            raise SquashError(
                "Cannot squash %s layers, the %s image contains only %s layers" % (number_of_layers, self.image, len(self.old_image_layers)))

    def _before_squashing(self):
        self._initialize_directories()

        # Location of the exported tar archive with the image to squash
        self.old_image_tar = os.path.join(self.old_image_dir, "image.tar")
        # Location of the tar archive with squashed layers
        self.squashed_tar = os.path.join(self.squashed_dir, "layer.tar")

        if self.tag:
            self.image_name, self.image_tag = self._parse_image_name(self.tag)

        # The image id or name of the image to be squashed
        try:
            self.old_image_id = self.docker.inspect_image(self.image)['Id']
        except SquashError:
            raise SquashError(
                "Could not get the image ID to squash, please check provided 'image' argument: %s" % self.image)

        self.old_image_layers = []

        # Read all layers in the image
        self._read_layers(self.old_image_layers, self.old_image_id)

        self.old_image_layers.reverse()

        self.log.info("Old image has %s layers", len(self.old_image_layers))
        self.log.debug("Old layers: %s", self.old_image_layers)

        # By default - squash all layers.
        if self.from_layer == None:
            self.from_layer = len(self.old_image_layers)

        try:
            number_of_layers = int(self.from_layer)

            self.log.debug(
                "We detected number of layers as the argument to squash")
        except ValueError:
            self.log.debug("We detected layer as the argument to squash")

            squash_id = self._squash_id(self.from_layer)

            if not squash_id:
                raise SquashError(
                    "The %s layer could not be found in the %s image" % (self.from_layer, self.image))

            number_of_layers = len(self.old_image_layers) - \
                self.old_image_layers.index(squash_id) - 1

        self._validate_number_of_layers(number_of_layers)

        marker = len(self.old_image_layers) - number_of_layers

        self.layers_to_squash = self.old_image_layers[marker:]
        self.layers_to_move = self.old_image_layers[:marker]

        self.log.info("Checking if squashing is necessary...")

        if len(self.layers_to_squash) <= 1:
            raise SquashError("%s layer(s) in this image marked to squash, no squashing is required" % len(
                self.layers_to_squash))

        self.log.info("Attempting to squash last %s layers...",
                      number_of_layers)
        self.log.debug("Layers to squash: %s", self.layers_to_squash)
        self.log.debug("Layers to move: %s", self.layers_to_move)

        # Save the image in tar format in the tepmorary directory
        self._save_image(self.old_image_id, self.old_image_tar)

        # Unpack exported image
        self._unpack(self.old_image_tar, self.old_image_dir)

        # Remove the tar file early to save some space
        self.log.debug("Removing exported tar (%s)..." % self.old_image_tar)
        os.remove(self.old_image_tar)

        self.log.info("Squashing image '%s'..." % self.image)

    def _after_squashing(self):
        pass

    def layer_paths(self):
        """
        Returns name of directories to layers in the exported tar archive.
        """
        pass

    def export_tar_archive(self, target_tar_file):
        self._tar_image(target_tar_file, self.new_image_dir)
        self.log.info("Image available at '%s'" % target_tar_file)

    def load_squashed_image(self):
        self._load_image(self.new_image_dir)

        if self.tag:
            self.log.info("Image registered in Docker daemon as %s:%s" %
                          (self.image_name, self.image_tag))

    def _files_in_layers(self, layers, directory):
        """
        Prepare a list of files in all layers
        """
        files = {}

        for layer in layers:
            self.log.debug("Generating list of files in layer '%s'..." % layer)
            tar_file = os.path.join(directory, layer, "layer.tar")
            with tarfile.open(tar_file, 'r', format=tarfile.PAX_FORMAT) as tar:
                files[layer] = tar.getnames()
            self.log.debug("Done, found %s files" % len(files[layer]))

        return files

    def _prepare_tmp_directory(self, tmp_dir):
        """ Creates temporary directory that is used to work on layers """

        if tmp_dir:
            if os.path.exists(tmp_dir):
                raise SquashError(
                    "The '%s' directory already exists, please remove it before you proceed" % tmp_dir)
            os.makedirs(tmp_dir)
        else:
            tmp_dir = tempfile.mkdtemp(prefix="docker-squash-")

        self.log.debug("Using %s as the temporary directory" % tmp_dir)

        return tmp_dir

    def _load_image(self, directory):

        tar_file = os.path.join(self.tmp_dir, "image.tar")

        self._tar_image(tar_file, directory)

        with open(tar_file, 'rb') as f:
            self.log.debug("Loading squashed image...")
            self.docker.load_image(f)
            self.log.debug("Image loaded!")

        os.remove(tar_file)

    def _tar_image(self, target_tar_file, directory):
        with tarfile.open(target_tar_file, 'w', format=tarfile.PAX_FORMAT) as tar:
            self.log.debug("Generating tar archive for the squashed image...")
            with Chdir(directory):
                # docker produces images like this:
                #   repositories
                #   <layer>/json
                # and not:
                #   ./
                #   ./repositories
                #   ./<layer>/json
                for f in os.listdir("."):
                    tar.add(f)
            self.log.debug("Archive generated")

    def _layers_to_squash(self, layers, from_layer):
        """ Prepares a list of layer IDs that should be squashed """
        to_squash = []
        to_leave = []
        should_squash = True

        for l in reversed(layers):
            if l == from_layer:
                should_squash = False

            if should_squash:
                to_squash.append(l)
            else:
                to_leave.append(l)

        to_squash.reverse()
        to_leave.reverse()

        return to_squash, to_leave

    def _save_image(self, image_id, tar_file):
        """ Saves the image as a tar archive under specified name """

        for x in [0, 1, 2]:
            self.log.info("Saving image %s to %s file..." %
                          (image_id, tar_file))
            self.log.debug("Try #%s..." % (x + 1))

            try:
                image = self.docker.get_image(image_id)

                with open(tar_file, 'wb') as f:
                    while True:
                        # Read about 10 MB of the tar archive
                        data = image.read(1024000)

                        if not data:
                            break

                        f.write(data)

                self.log.info("Image saved!")
                return True
            except Exception as e:
                self.log.exception(e)
                self.log.warn(
                    "An error occured while saving the %s image, retrying..." % image_id)

        raise SquashError("Couldn't save %s image!" % image_id)

    def _unpack(self, tar_file, directory):
        """ Unpacks tar archive to selected directory """

        self.log.info("Unpacking %s tar file to %s directory" %
                      (tar_file, directory))

        with tarfile.open(tar_file, 'r') as tar:
            tar.extractall(path=directory)

        self.log.info("Archive unpacked!")

    def _read_layers(self, layers, image_id):
        """ Reads the JSON metadata for specified layer / image id """

        for layer in self.docker.history(image_id):
            layers.append(layer['Id'])

    def _parse_image_name(self, image):
        """
        Parses the provided image name and splits it in the
        name and tag part, if possible. If no tag is provided
        'latest' is used.
        """
        if ':' in image and '/' not in image.split(':')[-1]:
            image_tag = image.split(':')[-1]
            image_name = image[:-(len(image_tag) + 1)]
        else:
            image_tag = "latest"
            image_name = image

        return (image_name, image_tag)

    def _dump_json(self, data, new_line=False):
        """
        Helper function to marshal object into JSON string.
        Additionally a sha256sum of the created JSON string is generated.
        """

        # We do not want any spaces between keys and values in JSON
        json_data = json.dumps(data, separators=(',', ':'))

        if new_line:
            json_data = "%s\n" % json_data

        # Generate sha256sum of the JSON data, may be handy
        sha = hashlib.sha256(json_data.encode('utf-8')).hexdigest()

        return json_data, sha

    def _generate_repositories_json(self, repositories_file, image_id, name, tag):
        if not image_id:
            raise SquashError("Provided image id cannot be null")

        if name == tag == None:
            self.log.debug("No name and tag provided for the image, skipping generating repositories file")
            return

        repos = {}
        repos[name] = {}
        repos[name][tag] = image_id

        data = json.dumps(repos, separators=(',', ':'))

        with open(repositories_file, 'w') as f:
            f.write(data)
            f.write("\n")

    def _write_version_file(self, squashed_dir):
        version_file = os.path.join(squashed_dir, "VERSION")

        with open(version_file, 'w') as f:
            f.write("1.0")

    def _write_json_metadata(self, metadata, metadata_file):
        with open(metadata_file, 'w') as f:
            f.write(metadata)

    def _read_old_metadata(self, old_json_file):
        self.log.debug("Reading JSON metadata file '%s'..." % old_json_file)

        # Read original metadata
        with open(old_json_file, 'r') as f:
            metadata = json.load(f)

        return metadata

    def _move_layers(self, layers, src, dest):
        """
        This moves all the layers that should be copied as-is.
        In other words - all layers that are not meant to be squashed will be
        moved from the old image to the new image untouched.
        """
        for layer in layers:
            layer_id = layer.replace('sha256:', '')

            self.log.debug("Moving unmodified layer '%s'..." % layer_id)
            shutil.move(os.path.join(src, layer_id), dest)

    def _file_should_be_skipped(self, file_name, skipped_paths):
        for file_path in skipped_paths:
            if file_name == file_path or file_name.startswith(file_path + "/"):
                return True

        return False

    def _marker_files(self, tar, members):
        """
        Searches for marker files in the specified archive.

        Docker marker files are files taht have the .wh. prefix in the name.
        These files mark the corresponding file to be removed (hidden) when
        we start a container from the image.
        """
        marker_files = {}

        self.log.debug(
            "Searching for marker files in '%s' archive..." % tar.name)

        for member in members:
            if '.wh.' in member.name:
                self.log.debug("Found '%s' marker file" % member.name)
                marker_files[member] = tar.extractfile(member)

        return marker_files

    def _add_markers(self, markers, tar, files_in_layers):
        """
        This method is responsible for adding back all markers that were not
        added to the squashed layer AND files they refer to can be found in layers
        we do not squash.
        """

        if markers:
            self.log.debug("Marker files to add: %s" %
                           [o.name for o in markers.keys()])
        else:
            # No marker files to add
            return

        for marker, marker_file in six.iteritems(markers):
            actual_file = marker.name.replace('.wh.', '')
            should_be_added_back = False

            if files_in_layers:
                for files in files_in_layers.values():
                    if not self._file_should_be_skipped(actual_file, files):
                        should_be_added_back = True
                        break
            else:
                # There are no previous layers, so we need to add it back
                # In fact this shouldn't happen since having a marker file
                # where there is no previous layer doesn not make sense.
                should_be_added_back = True

            if should_be_added_back:
                self.log.debug(
                    "Adding '%s' marker file back..." % marker.name)
                # Marker files on AUFS are hardlinks, we need to create
                # regular files, therefore we need to recreate the tarinfo
                # object
                tar.addfile(tarfile.TarInfo(name=marker.name), marker_file)
            else:
                self.log.debug(
                    "Skipping '%s' marker file..." % marker.name)

    def _squash_layers(self, layers_to_squash, layers_to_move):
        self.log.info("Starting squashing...")

        # Reverse the layers to squash - we begin with the newest one
        # to make the tar lighter
        layers_to_squash.reverse()

        with tarfile.open(self.squashed_tar, 'w', format=tarfile.PAX_FORMAT) as squashed_tar:
            to_skip = []
            missed_markers = {}
            # List of filenames in the squashed archive
            squashed_files = []

            for layer_id in layers_to_squash:
                layer_tar_file = os.path.join(
                    self.old_image_dir, layer_id, "layer.tar")

                self.log.info("Squashing file '%s'..." % layer_tar_file)

                # Open the exiting layer to squash
                with tarfile.open(layer_tar_file, 'r', format=tarfile.PAX_FORMAT) as layer_tar:
                    # Find all marker files for all layers
                    # We need the list of marker files upfront, so we can
                    # skip unnecessary files
                    members = layer_tar.getmembers()
                    markers = self._marker_files(layer_tar, members)

                    # Iterate over the marker files found for this particular
                    # layer and if in the squashed layers file corresponding
                    # to the marker file is found, then skip both files
                    for marker, marker_file in six.iteritems(markers):
                        actual_file = marker.name.replace('.wh.', '')
                        to_skip.append(marker.name)
                        to_skip.append(actual_file)

                        if not self._file_should_be_skipped(actual_file, squashed_files):
                            self.log.debug(
                                "Marker file '%s' not found in the squashed files, we'll try at the end of squashing one more time" % marker.name)
                            missed_markers[marker] = marker_file

                    # Copy all the files to the new tar
                    for member in members:
                        # Skip files that are marked to be skipped
                        if self._file_should_be_skipped(member.name, to_skip):
                            self.log.debug(
                                "Skipping '%s' file because it's on the list to skip files" % member.name)
                            continue

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
                        elif member.islnk():
                            if member.linkname in to_skip:
                                self.log.debug("Found a hard link to a file which is marked to be skipped: %s, skipping hard link too" % member.linkname)
                                to_skip.append(member.name)
                        else:
                            # Finally add the file to archive
                            squashed_tar.addfile(
                                member, layer_tar.extractfile(member))

                        # We added a file to the squashed tar, so let's note it
                        squashed_files.append(member.name)

            if layers_to_move:
                # Find all files in layers that we don't squash
                files_in_layers_to_move = self._files_in_layers(
                    layers_to_move, self.old_image_dir)

                self._add_markers(missed_markers, squashed_tar,
                                  files_in_layers_to_move)

        self.log.info("Squashing finished!")
