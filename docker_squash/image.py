import datetime
import hashlib
import itertools
import json
import logging
import os
import pathlib
import re
import shutil
import tarfile
import tempfile
import threading
from typing import Iterable, List, Optional, Set, Union

import docker as docker_library

from docker_squash.errors import SquashError, SquashUnnecessaryError


class Chdir(object):
    """Context manager for changing the current working directory"""

    def __init__(self, new_path):
        self.newPath = os.path.expanduser(new_path)

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

    def __init__(
        self,
        log,
        docker,
        image,
        from_layer,
        tmp_dir: Optional[str] = None,
        tag: Optional[str] = None,
        comment: Optional[str] = "",
    ):
        self.log: logging.Logger = log
        self.debug = self.log.isEnabledFor(logging.DEBUG)
        self.docker = docker
        self.image: str = image
        self.from_layer: str = from_layer
        self.tag: str = tag
        self.comment: str = comment
        self.image_name = None
        self.image_tag = None
        self.squash_id = None
        self.oci_format = False

        # Workaround for https://play.golang.org/p/sCsWMXYxqy
        #
        # Golang doesn't add padding to microseconds when marshaling
        # microseconds in date into JSON. Python does.
        # We need to produce same output as Docker's to not generate
        # different metadata. That's why we need to strip all zeros at the
        # end of the date string...
        self.date = re.sub(
            r"0*Z$", "Z", datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        )
        """ Date used in metadata, already formatted using the `%Y-%m-%dT%H:%M:%S.%fZ` format """

        self.tmp_dir: str = tmp_dir
        """ Main temporary directory to save all working files. This is the root directory for all other temporary files. """

    def squash(self):
        self._before_squashing()
        ret = self._squash()
        self._after_squashing()

        return ret

    def _squash(self):
        pass

    def cleanup(self):
        """Cleanup the temporary directory"""

        self.log.debug("Cleaning up %s temporary directory" % self.tmp_dir)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _initialize_directories(self):
        # Prepare temporary directory where all the work will be executed
        try:
            self.tmp_dir = self._prepare_tmp_directory(self.tmp_dir)
        except Exception:
            raise SquashError("Preparing temporary directory failed")

        # Temporary location on the disk of the old, unpacked *image*
        self.old_image_dir: str = os.path.join(self.tmp_dir, "old")
        # Temporary location on the disk of the new, unpacked, squashed *image*
        self.new_image_dir: str = os.path.join(self.tmp_dir, "new")
        # Temporary location on the disk of the squashed *layer*
        self.squashed_dir: str = os.path.join(self.new_image_dir, "squashed")

        for d in self.old_image_dir, self.new_image_dir:
            os.makedirs(d)

    def _squash_id(self, layer):
        if layer == "<missing>":
            self.log.warning(
                "You try to squash from layer that does not have it's own ID, we'll try to find it later"
            )
            return None

        try:
            squash_id = self.docker.inspect_image(layer)["Id"]
        except Exception:
            raise SquashError(
                f"Could not get the layer ID to squash, please check provided 'layer' argument: {layer}"
            )

        if squash_id not in self.old_image_layers:
            raise SquashError(
                f"Couldn't find the provided layer ({layer}) in the {self.image} image"
            )

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
                f"Number of layers to squash cannot be less or equal 0, provided: {number_of_layers}"
            )

        # Do not squash if provided number of layer to squash is bigger
        # than number of actual layers in the image
        if number_of_layers > len(self.old_image_layers):
            raise SquashError(
                f"Cannot squash {number_of_layers} layers, the {self.image} image contains only {len(self.old_image_layers)} layers"
            )

    def _before_squashing(self):
        self._initialize_directories()

        # Location of the tar archive with squashed layers
        self.squashed_tar = os.path.join(self.squashed_dir, "layer.tar")

        if self.tag:
            self.image_name, self.image_tag = self._parse_image_name(self.tag)

        # The image id or name of the image to be squashed
        try:
            self.old_image_id = self.docker.inspect_image(self.image)["Id"]
        except SquashError:
            raise SquashError(
                f"Could not get the image ID to squash, please check provided 'image' argument: {self.image}"
            )

        self.old_image_layers = []

        # Read all layers in the image
        self._read_layers(self.old_image_layers, self.old_image_id)
        self.old_image_layers.reverse()
        self.log.info("Old image has %s layers", len(self.old_image_layers))
        self.log.debug("Old layers: %s", self.old_image_layers)

        # By default - squash all layers.
        if self.from_layer is None:
            self.from_layer = len(self.old_image_layers)

        try:
            number_of_layers = int(self.from_layer)

            self.log.debug(
                f"We detected number of layers ({number_of_layers}) as the argument to squash"
            )
        except ValueError:
            squash_id = self._squash_id(self.from_layer)
            self.log.debug(f"We detected layer ({squash_id}) as the argument to squash")

            if not squash_id:
                raise SquashError(
                    f"The {self.from_layer} layer could not be found in the {self.image} image"
                )

            number_of_layers = (
                len(self.old_image_layers) - self.old_image_layers.index(squash_id) - 1
            )

        self._validate_number_of_layers(number_of_layers)

        marker = len(self.old_image_layers) - number_of_layers

        self.layers_to_squash = self.old_image_layers[marker:]
        self.layers_to_move = self.old_image_layers[:marker]

        self.log.info("Checking if squashing is necessary...")

        if len(self.layers_to_squash) < 1:
            raise SquashError(
                f"Invalid number of layers to squash: {len(self.layers_to_squash)}"
            )

        if len(self.layers_to_squash) == 1:
            raise SquashUnnecessaryError(
                "Single layer marked to squash, no squashing is required"
            )

        self.log.info(f"Attempting to squash last {number_of_layers} layers...")
        self.log.debug(f"Layers to squash: {self.layers_to_squash}")
        self.log.debug(f"Layers to move: {self.layers_to_move}")

        # Fetch the image and unpack it on the fly to the old image directory
        self._save_image(self.old_image_id, self.old_image_dir)

        self.size_before = self._dir_size(self.old_image_dir)

        self.log.info("Squashing image '%s'..." % self.image)

    def _after_squashing(self):
        self.log.debug("Removing from disk already squashed layers...")
        self.log.debug("Cleaning up %s temporary directory" % self.old_image_dir)
        shutil.rmtree(self.old_image_dir, ignore_errors=True)

        self.size_after = self._dir_size(self.new_image_dir)

        size_before_mb = float(self.size_before) / 1024 / 1024
        size_after_mb = float(self.size_after) / 1024 / 1024

        self.log.info("Original image size: %.2f MB" % size_before_mb)
        self.log.info("Squashed image size: %.2f MB" % size_after_mb)

        if size_after_mb >= size_before_mb:
            self.log.info(
                "If the squashed image is larger than original it means that there were no meaningful files to squash and it just added metadata. Are you sure you specified correct parameters?"
            )
        else:
            self.log.info(
                "Image size decreased by %.2f %%"
                % float(((size_before_mb - size_after_mb) / size_before_mb) * 100)
            )

    def _dir_size(self, directory):
        size = 0

        for path, dirs, files in os.walk(directory):
            for f in files:
                size += os.path.getsize(os.path.join(path, f))

        return size

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
            self.log.info(
                "Image registered in Docker daemon as %s:%s"
                % (self.image_name, self.image_tag)
            )

    def _files_in_layers(self, layers: List[str]) -> Set[str]:
        """
        Prepare a list of files in all layers
        """
        files = set()

        for layer in layers:
            self.log.debug("Generating list of files in layer '%s'..." % layer)
            tar_file = self._extract_tar_name(layer)
            with tarfile.open(tar_file, "r", format=tarfile.PAX_FORMAT) as tar:
                layer_files = [self._normalize_path(x) for x in tar.getnames()]
            files.update(layer_files)
            self.log.debug("Done, found %s files" % len(layer_files))

        return files

    def _prepare_tmp_directory(self, tmp_dir: Optional[str]) -> str:
        """Creates temporary directory that is used to work on layers"""

        if tmp_dir:
            if os.path.exists(tmp_dir):
                raise SquashError(
                    f"The '{tmp_dir}' directory already exists, please remove it before you proceed"
                )
            os.makedirs(tmp_dir)
        else:
            tmp_dir = tempfile.mkdtemp(prefix="docker-squash-")

        self.log.debug("Using %s as the temporary directory" % tmp_dir)

        return tmp_dir

    def _load_image(self, directory):
        tar_file = os.path.join(self.tmp_dir, "image.tar")

        self._tar_image(tar_file, directory)

        with open(tar_file, "rb") as f:
            self.log.debug("Loading squashed image...")
            self.docker.load_image(f)
            self.log.debug("Image loaded!")

        os.remove(tar_file)

    def _tar_image(self, target_tar_file, directory):
        with tarfile.open(target_tar_file, "w", format=tarfile.PAX_FORMAT) as tar:
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
        """Prepares a list of layer IDs that should be squashed"""
        to_squash = []
        to_leave = []
        should_squash = True

        for reversed_layer in reversed(layers):
            if reversed_layer == from_layer:
                should_squash = False

            if should_squash:
                to_squash.append(reversed_layer)
            else:
                to_leave.append(reversed_layer)

        to_squash.reverse()
        to_leave.reverse()

        return to_squash, to_leave

    def _extract_tar(self, fileobj, directory):
        with tarfile.open(fileobj=fileobj, mode="r|") as tar:
            tar.extractall(path=directory)

    def _save_image(self, image_id, directory):
        """Saves the image as a tar archive under specified name"""

        for x in [0, 1, 2]:
            self.log.info("Saving image %s to %s directory..." % (image_id, directory))
            self.log.debug("Try #%s..." % (x + 1))

            try:
                image = self.docker.get_image(image_id)

                if int(docker_library.__version__.split(".")[0]) < 3:
                    # Docker library prior to 3.0.0 returned the requests
                    # object directly which could be used to read from
                    self.log.debug(
                        "Extracting image using HTTPResponse object directly"
                    )
                    self._extract_tar(image, directory)
                else:
                    # Docker library >=3.0.0 returns iterator over raw data
                    self.log.debug("Extracting image using iterator over raw data")

                    fd_r, fd_w = os.pipe()

                    r = os.fdopen(fd_r, "rb")
                    w = os.fdopen(fd_w, "wb")

                    extracter = threading.Thread(
                        target=self._extract_tar, args=(r, directory)
                    )
                    extracter.start()

                    for chunk in image:
                        w.write(chunk)

                    w.flush()
                    w.close()

                    extracter.join()
                    r.close()
                self.log.info("Image saved!")
                return True
            except Exception as e:
                self.log.exception(e)
                self.log.warning(
                    f"An error occurred while saving the {image_id} image, retrying..."
                )

        raise SquashError(f"Couldn't save {image_id} image!")

    def _unpack(self, tar_file, directory):
        """Unpacks tar archive to selected directory"""

        self.log.info("Unpacking %s tar file to %s directory" % (tar_file, directory))

        with tarfile.open(tar_file, "r") as tar:
            tar.extractall(path=directory)

        self.log.info("Archive unpacked!")

    def _read_layers(self, layers, image_id):
        """Reads the JSON metadata for specified layer / image id"""

        for layer in self.docker.history(image_id):
            layers.append(layer["Id"])

    def _parse_image_name(self, image):
        """
        Parses the provided image name and splits it in the
        name and tag part, if possible. If no tag is provided
        'latest' is used.
        """
        if ":" in image and "/" not in image.split(":")[-1]:
            image_tag = image.split(":")[-1]
            image_name = image[: -(len(image_tag) + 1)]
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
        json_data = json.dumps(data, separators=(",", ":"))

        if new_line:
            json_data = "%s\n" % json_data

        # Generate sha256sum of the JSON data, may be handy
        sha = hashlib.sha256(json_data.encode("utf-8")).hexdigest()

        return json_data, sha

    def _generate_repositories_json(self, repositories_file, image_id, name, tag):
        if not image_id:
            raise SquashError("Provided image id cannot be null")

        if name is None and tag is None:
            self.log.debug(
                "No name and tag provided for the image, skipping generating repositories file"
            )
            return

        repos = {}
        repos[name] = {}
        repos[name][tag] = image_id

        data = json.dumps(repos, separators=(",", ":"))

        with open(repositories_file, "w") as f:
            f.write(data)
            f.write("\n")

    def _write_version_file(self, squashed_dir):
        version_file = os.path.join(squashed_dir, "VERSION")

        with open(version_file, "w") as f:
            f.write("1.0")

    def _write_json_metadata(self, metadata, metadata_file):
        with open(metadata_file, "w") as f:
            f.write(metadata)

    def _read_old_metadata(self, old_json_file):
        self.log.debug("Reading JSON metadata file '%s'..." % old_json_file)

        # Read original metadata
        with open(old_json_file, "r") as f:
            metadata = json.load(f)

        return metadata

    def _move_layers(self, layers, src: str, dest: str):
        """
        This moves all the layers that should be copied as-is.
        In other words - all layers that are not meant to be squashed will be
        moved from the old image to the new image untouched.
        """
        for layer in layers:
            layer_id = layer.replace("sha256:", "")

            self.log.debug("Moving unmodified layer '%s'..." % layer_id)
            shutil.move(os.path.join(src, layer_id), dest)

    def _file_should_be_skipped(
        self, file_name: str, files_to_skip: Set[str], directories_to_skip: Set[str]
    ) -> bool:
        if file_name in files_to_skip:
            self.log.debug(
                "Skipping file '%s' because it is marked to be skipped" % file_name
            )
            return True

        for parent in self._path_hierarchy(file_name):
            if parent in files_to_skip or parent in directories_to_skip:
                self.log.debug(
                    "Skipping file '%s' because its parent directory '%s' is marked to be skipped"
                    % (file_name, parent)
                )
                return True

        return False

    def _marker_files(self, members: List[tarfile.TarInfo]) -> List[tarfile.TarInfo]:
        """
        Searches for marker files in the specified archive.

        Docker marker files are files that have the .wh. prefix in the name.
        These files mark the corresponding file to be removed (hidden) when
        we start a container from the image.
        """
        marker_files = []

        self.log.debug("Searching for marker files")

        for member in members:
            if ".wh." in member.name:
                self.log.debug("Found '%s' marker file" % member.name)
                marker_files.append(member)

        self.log.debug("Found %s marker files" % len(marker_files))

        return marker_files

    def _normalize_path(self, path: str) -> str:
        return os.path.normpath(os.path.join("/", path))

    def _squash_layers(self, layers_to_squash: List[str], layers_to_move: List[str]):
        self.log.info(f"Starting squashing for {self.squashed_tar}...")

        # Reverse the layers to squash - we begin with the newest one
        # to make the tar lighter
        layers_to_squash.reverse()

        # Find all files in layers that we don't squash
        files_in_layers_to_move: Set[str] = self._files_in_layers(layers_to_move)

        with tarfile.open(
            self.squashed_tar, "w", format=tarfile.PAX_FORMAT
        ) as squashed_tar:
            files_to_skip: Set[str] = set()
            squashed_files: Set[str] = set()
            directories_to_skip: Set[str] = set()

            for layer_id in layers_to_squash:
                layer_tar_file = self._extract_tar_name(layer_id)
                self.log.info("Squashing file '%s'..." % layer_tar_file)

                # Open the exiting layer to squash
                layer_tar: tarfile.TarFile = tarfile.open(
                    layer_tar_file, "r", format=tarfile.PAX_FORMAT
                )
                members: List[tarfile.TarInfo] = layer_tar.getmembers()
                markers: List[tarfile.TarInfo] = self._marker_files(members)

                # List of opaque directories found in this layer.
                # We will add it to 'directories_to_skip' at the end of processing the layer
                opaque_dirs: List[str] = []

                # Iterate over marker files found for this particular
                # layer and if a file in the squashed layers file corresponding
                # to the marker file is found, then skip both files
                for marker in markers:
                    normalized_name = self._normalize_path(marker.name)
                    # We have an opaque directory marker file
                    # https://github.com/opencontainers/image-spec/blob/master/layer.md#opaque-whiteout
                    if normalized_name.endswith(".wh..wh..opq"):
                        opaque_dir = os.path.dirname(normalized_name)
                        self.log.debug("Found opaque directory: '%s'" % opaque_dir)
                        opaque_dirs.append(opaque_dir)
                    else:
                        actual_file = normalized_name.replace(".wh.", "")
                        files_to_skip.add(actual_file)
                        if (
                            actual_file in squashed_files
                            or actual_file not in files_in_layers_to_move
                        ):
                            self.log.debug(
                                "Skipping marker file '%s'" % normalized_name
                            )
                            files_to_skip.add(normalized_name)

                # Copy all the files to the new tar
                for member in members:
                    normalized_name = self._normalize_path(member.name)

                    if self._file_should_be_skipped(
                        normalized_name, files_to_skip, directories_to_skip
                    ):
                        continue

                    # Check if file is already added to the archive
                    if normalized_name in squashed_files:
                        # File already exist in the squashed archive, skip it because
                        # file want to add is older than the one already in the archive.
                        # This is true because we do reverse squashing - from
                        # newer to older layer
                        self.log.debug(
                            "Skipping file '%s' because it is older than file already added to the archive"
                            % normalized_name
                        )
                        continue

                    if not member.isdir():
                        # https://github.com/goldmann/docker-squash/issues/253
                        directories_to_skip.add(normalized_name)

                    content = None

                    if member.isfile():
                        content = layer_tar.extractfile(member)

                    # We convert hardlinks to regular files to avoid issues with deleting
                    # link's target file
                    if member.islnk():
                        target = layer_tar.getmember(member.linkname)
                        content = layer_tar.extractfile(target)
                        member.type = target.type
                        member.size = target.size

                    squashed_tar.addfile(member, content)
                    squashed_files.add(normalized_name)

                directories_to_skip.update(opaque_dirs)
                layer_tar.close()

        self.log.info("Squashing finished!")

    def _path_hierarchy(self, path: Union[str, pathlib.PurePath]) -> Iterable[str]:
        """
        Creates a full hierarchy of directories for a given path.

        For a particular path, a list will be returned
        containing paths from the root directory, through all
        levels up to the path specified.

        Example:
            Path '/opt/testing/some/dir/structure/file'

            will return:

            ['/', '/opt', '/opt/testing', '/opt/testing/some', '/opt/testing/some/dir', '/opt/testing/some/dir/structure']
        """
        if not path:
            raise SquashError("No path provided to create the hierarchy for")

        if not isinstance(path, pathlib.PurePath):
            path = pathlib.PurePath(path)

        if len(path.parts) == 1:
            return path.parts

        return itertools.accumulate(
            path.parts[:-1], func=lambda head, tail: str(path.__class__(head, tail))
        )

    def _extract_tar_name(self, path: str) -> str:
        if self.oci_format:
            return os.path.join(self.old_image_dir, path)
        else:
            return os.path.join(self.old_image_dir, path, "layer.tar")
