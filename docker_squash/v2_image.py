import hashlib
import json
import os
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import List, Tuple

from docker_squash.errors import SquashError
from docker_squash.image import Image


class V2Image(Image):
    FORMAT = "v2"

    def _before_squashing(self):
        super(V2Image, self)._before_squashing()

        # Read old image manifest file
        self.old_image_manifest = self._get_manifest()
        self.log.debug(
            f"Retrieved manifest {json.dumps(self.old_image_manifest, indent=4)}"
        )

        # Read old image config file
        self.old_image_config = self._read_json_file(
            os.path.join(self.old_image_dir, self.old_image_manifest["Config"])
        )

        # Read layer paths inside of the tar archive
        # We split it into layers that needs to be squashed
        # and layers that needs to be moved as-is
        self.layer_paths_to_squash: List[str] = []
        self.layer_paths_to_move: List[str] = []
        self.layer_paths_to_squash, self.layer_paths_to_move = self._read_layer_paths(
            self.old_image_config, self.old_image_manifest, self.layers_to_move
        )

        if self.layer_paths_to_move:
            self.squash_id = self.layer_paths_to_move[-1]

        self.log.debug(f"Layers paths to squash: {self.layer_paths_to_squash}")
        self.log.debug(f"Layers paths to move: {self.layer_paths_to_move}")

    def _squash(self):
        if self.layer_paths_to_squash:
            # Prepare the directory
            os.makedirs(self.squashed_dir)
            # Merge data layers
            self._squash_layers(self.layer_paths_to_squash, self.layer_paths_to_move)

        self.diff_ids = self._generate_diff_ids()
        self.chain_ids = self._generate_chain_ids(self.diff_ids)

        metadata = self._generate_image_metadata()
        image_id = self._write_image_metadata(metadata)

        layer_path_id = None

        if self.layer_paths_to_squash:
            # Compute layer id to use to name the directory where
            # we store the layer data inside of the tar archive
            layer_path_id = self._generate_squashed_layer_path_id()

            if self.oci_format:
                old_layer_path = self.old_image_manifest["Config"]
            else:
                if self.layer_paths_to_squash[0]:
                    old_layer_path = self.layer_paths_to_squash[0]
                else:
                    old_layer_path = layer_path_id
                old_layer_path = os.path.join(old_layer_path, "json")

            metadata = self._generate_last_layer_metadata(layer_path_id, old_layer_path)
            self._write_squashed_layer_metadata(metadata)

            # Write version file to the squashed layer
            # Even Docker doesn't know why it's needed...
            self._write_version_file(self.squashed_dir)

            # Move the temporary squashed layer directory to the correct one
            shutil.move(
                self.squashed_dir, os.path.join(self.new_image_dir, layer_path_id)
            )

        manifest = self._generate_manifest_metadata(
            image_id,
            self.image_name,
            self.image_tag,
            self.old_image_manifest,
            self.layer_paths_to_move,
            layer_path_id,
        )

        self._write_manifest_metadata(manifest)

        repository_image_id = manifest[0]["Layers"][-1].split("/")[0]

        # Move all the layers that should be untouched
        self._move_layers(
            self.layer_paths_to_move, self.old_image_dir, self.new_image_dir
        )

        repositories_file = os.path.join(self.new_image_dir, "repositories")
        self._generate_repositories_json(
            repositories_file, repository_image_id, self.image_name, self.image_tag
        )

        return image_id

    def _write_image_metadata(self, metadata):
        # Create JSON from the metadata
        # Docker adds new line at the end
        json_metadata, image_id = self._dump_json(metadata, True)
        image_metadata_file = os.path.join(self.new_image_dir, "%s.json" % image_id)

        self._write_json_metadata(json_metadata, image_metadata_file)

        return image_id

    def _write_squashed_layer_metadata(self, metadata):
        layer_metadata_file = os.path.join(self.squashed_dir, "json")
        json_metadata = self._dump_json(metadata)[0]

        self._write_json_metadata(json_metadata, layer_metadata_file)

    def _write_manifest_metadata(self, manifest):
        manifest_file = os.path.join(self.new_image_dir, "manifest.json")
        json_manifest = self._dump_json(manifest, True)[0]

        self._write_json_metadata(json_manifest, manifest_file)

    def _generate_manifest_metadata(
        self,
        image_id,
        image_name,
        image_tag,
        old_image_manifest,
        layer_paths_to_move,
        layer_path_id=None,
    ):
        manifest = OrderedDict()
        manifest["Config"] = "%s.json" % image_id

        if image_name and image_tag:
            manifest["RepoTags"] = ["%s:%s" % (image_name, image_tag)]

        manifest["Layers"] = old_image_manifest["Layers"][: len(layer_paths_to_move)]

        if layer_path_id:
            manifest["Layers"].append("%s/layer.tar" % layer_path_id)

        return [manifest]

    def _read_json_file(self, json_file):
        """Helper function to read JSON file as OrderedDict"""

        self.log.debug(f"Reading '{json_file}' JSON file...")

        with open(json_file, "r") as f:
            return json.load(f, object_pairs_hook=OrderedDict)

    def _read_layer_paths(
        self, old_image_config, old_image_manifest, layers_to_move: List[str]
    ) -> Tuple[List[str], List[str]]:
        """
        In case of v2 format, layer id's are not the same as the id's
        used in the exported tar archive to name directories for layers.
        These id's can be found in the configuration files saved with
        the image - we need to read them.
        """

        # In manifest.json we do not have listed all layers
        # but only layers that do contain some data.
        current_manifest_layer = 0

        layer_paths_to_move = []
        layer_paths_to_squash = []

        # Iterate over image history, from base image to top layer
        for i, layer in enumerate(old_image_config["history"]):
            # If it's not an empty layer get the id
            # (directory name) where the layer's data is
            # stored
            if not layer.get("empty_layer", False):
                # Under <25 layers look like
                # 27f9b97654306a5389e8e48ba3486a11026d34055e1907672231cbd8e1380481/layer.tar
                # while >=25 layers look like
                # blobs/sha256/d6a7fc1fb44b63324d3fc67f016e1ef7ecc1a5ae6668ae3072d2e17230e3cfbc
                if self.oci_format:
                    layer_id = old_image_manifest["Layers"][current_manifest_layer]
                else:
                    layer_id = old_image_manifest["Layers"][
                        current_manifest_layer
                    ].rsplit("/")[0]

                # Check if this layer should be moved or squashed
                if len(layers_to_move) > i:
                    layer_paths_to_move.append(layer_id)
                else:
                    layer_paths_to_squash.append(layer_id)

                current_manifest_layer += 1

        return layer_paths_to_squash, layer_paths_to_move

    def _generate_chain_id(self, chain_ids, diff_ids, parent_chain_id):
        if parent_chain_id is None:
            return self._generate_chain_id(chain_ids, diff_ids[1:], diff_ids[0])

        chain_ids.append(parent_chain_id)

        if len(diff_ids) == 0:
            return parent_chain_id

        # This probably should not be hardcoded
        to_hash = "sha256:%s sha256:%s" % (parent_chain_id, diff_ids[0])
        digest = hashlib.sha256(str(to_hash).encode("utf8")).hexdigest()

        return self._generate_chain_id(chain_ids, diff_ids[1:], digest)

    def _generate_chain_ids(self, diff_ids):
        chain_ids = []

        self._generate_chain_id(chain_ids, diff_ids, None)

        return chain_ids

    def _generate_diff_ids(self):
        diff_ids = []

        for path in self.layer_paths_to_move:
            sha256 = self._compute_sha256(self._extract_tar_name(path))
            diff_ids.append(sha256)

        if self.layer_paths_to_squash:
            sha256 = self._compute_sha256(os.path.join(self.squashed_dir, "layer.tar"))
            diff_ids.append(sha256)

        return diff_ids

    def _compute_sha256(self, layer_tar):
        sha256 = hashlib.sha256()

        with open(layer_tar, "rb") as f:
            while True:
                # Read in 10MB chunks
                data = f.read(10485760)

                if not data:
                    break

                sha256.update(data)

        return sha256.hexdigest()

    def _generate_squashed_layer_path_id(self):
        """
        This function generates the id used to name the directory to
        store the squashed layer content in the archive.

        This mimics what Docker does here: https://github.com/docker/docker/blob/v1.10.0-rc1/image/v1/imagev1.go#L42
        To make it simpler we do reuse old image metadata and
        modify it to what it should look which means to be exact
        as https://github.com/docker/docker/blob/v1.10.0-rc1/image/v1/imagev1.go#L64
        """

        # Using OrderedDict, because order of JSON elements is important
        v1_metadata = OrderedDict(self.old_image_config)

        # Update image creation date
        v1_metadata["created"] = self.date

        # Remove unnecessary elements
        # Do not fail if key is not found
        for key in "history", "rootfs", "container":
            v1_metadata.pop(key, None)

        # Docker internally changes the order of keys between
        # exported metadata (why oh why?!). We need to add 'os'
        # element after 'layer_id'
        operating_system = v1_metadata.pop("os", None)

        # The 'layer_id' element is the chain_id of the
        # squashed layer
        v1_metadata["layer_id"] = "sha256:%s" % self.chain_ids[-1]

        # Add back 'os' element
        if operating_system:
            v1_metadata["os"] = operating_system

        # The 'parent' element is the name of the directory (inside the
        # exported tar archive) of the last layer that we move
        # (layer below squashed layer)

        if self.layer_paths_to_move:
            if self.layer_paths_to_squash:
                parent = self.layer_paths_to_move[-1]
            else:
                parent = self.layer_paths_to_move[0]

            v1_metadata["parent"] = "sha256:%s" % parent

        # The 'Image' element is the id of the layer from which we squash
        if self.squash_id:
            # Update image id, should be one layer below squashed layer
            v1_metadata["config"]["Image"] = self.squash_id
        else:
            v1_metadata["config"]["Image"] = ""

        # Get the sha256sum of the JSON exported metadata,
        # we do not care about the metadata anymore
        sha = self._dump_json(v1_metadata)[1]

        return sha

    def _generate_last_layer_metadata(self, layer_path_id, old_layer_path: Path):
        config_file = os.path.join(self.old_image_dir, old_layer_path)
        with open(config_file, "r") as f:
            config = json.load(f, object_pairs_hook=OrderedDict)

        config["created"] = self.date

        if self.squash_id:
            # Update image id, should be one layer below squashed layer
            config["config"]["Image"] = self.squash_id
        else:
            config["config"]["Image"] = ""

        # Update 'parent' - it should be path to the last layer to move
        if self.layer_paths_to_move:
            config["parent"] = self.layer_paths_to_move[-1]
        else:
            config.pop("parent", None)
        # Update 'id' - it should be the path to the layer
        config["id"] = layer_path_id
        config.pop("container", None)
        return config

    def _generate_image_metadata(self):
        # First - read old image config, we'll update it instead of
        # generating one from scratch
        metadata = OrderedDict(self.old_image_config)
        # Update image creation date
        metadata["created"] = self.date

        # Remove unnecessary or old fields
        metadata.pop("container", None)

        # Remove squashed layers from history
        metadata["history"] = metadata["history"][: len(self.layers_to_move)]
        # Remove diff_ids for squashed layers
        metadata["rootfs"]["diff_ids"] = metadata["rootfs"]["diff_ids"][
            : len(self.layer_paths_to_move)
        ]

        history = {"comment": self.comment, "created": self.date}

        if self.layer_paths_to_squash:
            # Add diff_ids for the squashed layer
            metadata["rootfs"]["diff_ids"].append("sha256:%s" % self.diff_ids[-1])
        else:
            history["empty_layer"] = True

        # Add new entry for squashed layer to history
        metadata["history"].append(history)

        if self.squash_id:
            # Update image id, should be one layer below squashed layer
            metadata["config"]["Image"] = self.squash_id
        else:
            metadata["config"]["Image"] = ""

        return metadata

    def _get_manifest(self):
        if os.path.exists(os.path.join(self.old_image_dir, "index.json")):
            # New OCI Archive format type
            self.oci_format = True
            # Not using index.json to extract manifest details as while the config
            # sha could be extracted via some indirection i.e.
            #
            # index.json:manifest/digest::sha256:<intermediary>
            # blobs/sha256/<intermediary>:config/digest::sha256:<config>
            #
            # Docker spec currently will always include a manifest.json so will standardise
            # on using that. Further we rely upon the original manifest format in order to write
            # it back.
            if os.path.exists(os.path.join(self.old_image_dir, "manifest.json")):
                return (
                    self._read_json_file(
                        os.path.join(self.old_image_dir, "manifest.json")
                    )
                )[0]
            else:
                raise SquashError("Unable to locate manifest.json")
        else:
            return (
                self._read_json_file(os.path.join(self.old_image_dir, "manifest.json"))
            )[0]
