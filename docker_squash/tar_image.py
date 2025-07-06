# -*- coding: utf-8 -*-

import hashlib
import json
import logging
import os
import shutil
import tarfile
from collections import OrderedDict

from docker_squash.errors import SquashError
from docker_squash.image import Image


class TarImage(Image):
    """Process images from tar files without requiring Docker daemon"""

    FORMAT = "tar"

    def __init__(
        self, log, tar_path, from_layer=None, tmp_dir=None, tag=None, comment=""
    ):
        self.tar_path = tar_path
        self.log = log
        self.debug = self.log.isEnabledFor(logging.DEBUG)
        self.from_layer = from_layer
        self.tag = tag
        self.comment = comment
        self.tmp_dir = self._prepare_tmp_directory(tmp_dir)
        self.date = self._get_current_date()

        # Initialize attributes required by base class
        self.image_name = None
        self.image_tag = None
        self.squash_id = None
        self.oci_format = False

        # Set up directory structure
        self.old_image_dir = os.path.join(self.tmp_dir, "old")
        self.new_image_dir = os.path.join(self.tmp_dir, "new")
        self.squashed_dir = os.path.join(self.new_image_dir, "squashed")

        # Ensure directories exist
        os.makedirs(self.old_image_dir, exist_ok=True)
        os.makedirs(self.new_image_dir, exist_ok=True)
        os.makedirs(self.squashed_dir, exist_ok=True)

        # Initialize variables
        self.manifest = None
        self.old_image_config = None
        self.old_image_layers = []
        self.original_image_name = None
        self.old_image_id = None

        # Parse image name if provided
        if self.tag:
            self.image_name, self.image_tag = self._parse_image_name(self.tag)

        # Process the tar file
        self._extract_tar_image()
        self._detect_image_format()
        self._load_image_metadata()
        self.size_before = self._dir_size(self.old_image_dir)

    def squash(self):
        """Main squash method - follows base class pattern"""
        self._before_squashing()
        ret = self._squash()
        self._after_squashing()
        return ret

    def _get_current_date(self):
        """Get current date in Docker format"""
        import datetime
        import re

        # Workaround for Golang microsecond formatting
        date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return re.sub(r"0*Z$", "Z", date)

    def _extract_tar_image(self):
        """Extract tar image to temporary directory"""
        self.log.info(f"Extracting tar image from {self.tar_path}")

        if not os.path.exists(self.tar_path):
            raise SquashError(f"Tar file not found: {self.tar_path}")

        try:
            with tarfile.open(self.tar_path, "r") as tar:
                tar.extractall(self.old_image_dir)
        except Exception as e:
            raise SquashError(f"Failed to extract tar file: {e}")

        self.log.debug(f"Tar image extracted to {self.old_image_dir}")

    def _detect_image_format(self):
        """Detect if this is OCI format or Docker format"""
        index_file = os.path.join(self.old_image_dir, "index.json")
        manifest_file = os.path.join(self.old_image_dir, "manifest.json")

        if os.path.exists(index_file):
            self.log.info("Detected OCI format image")
            self.oci_format = True
        elif os.path.exists(manifest_file):
            self.log.info("Detected Docker format image")
            self.oci_format = False
        else:
            raise SquashError("Unable to detect image format - missing manifest files")

    def _load_image_metadata(self):
        """Load image metadata based on format"""
        if self.oci_format:
            self._load_oci_metadata()
        else:
            self._load_docker_metadata()

    def _load_oci_metadata(self):
        """Load OCI format metadata"""
        # Read index.json to get manifest reference
        index_file = os.path.join(self.old_image_dir, "index.json")
        with open(index_file, "r") as f:
            index_data = json.load(f, object_pairs_hook=OrderedDict)

        # Get the first manifest (assuming single image)
        if not index_data.get("manifests"):
            raise SquashError("No manifests found in index.json")

        manifest_desc = index_data["manifests"][0]
        manifest_digest = manifest_desc["digest"]

        # Read manifest from blobs
        manifest_path = os.path.join(
            self.old_image_dir, "blobs", "sha256", manifest_digest.split(":")[1]
        )
        if not os.path.exists(manifest_path):
            # Fallback to manifest.json if exists
            fallback_manifest = os.path.join(self.old_image_dir, "manifest.json")
            if os.path.exists(fallback_manifest):
                self.log.warning("Using fallback manifest.json for OCI image")
                self._load_docker_metadata()
                return
            else:
                raise SquashError(f"Manifest blob not found: {manifest_path}")

        with open(manifest_path, "r") as f:
            self.manifest = json.load(f, object_pairs_hook=OrderedDict)

        # Read config blob
        config_desc = self.manifest["config"]
        config_digest = config_desc["digest"]
        config_path = os.path.join(
            self.old_image_dir, "blobs", "sha256", config_digest.split(":")[1]
        )

        if not os.path.exists(config_path):
            raise SquashError(f"Config blob not found: {config_path}")

        with open(config_path, "r") as f:
            self.old_image_config = json.load(f, object_pairs_hook=OrderedDict)

        # Generate image ID from config hash
        self.old_image_id = f"sha256:{config_digest.split(':')[1]}"

        # Extract layer information
        self._extract_oci_layers()

    def _load_docker_metadata(self):
        """Load Docker format metadata"""
        manifest_file = os.path.join(self.old_image_dir, "manifest.json")
        with open(manifest_file, "r") as f:
            manifests = json.load(f, object_pairs_hook=OrderedDict)

        if not manifests:
            raise SquashError("Empty manifest.json")

        # Use the first manifest
        self.manifest = manifests[0]

        # Read config file
        config_path = os.path.join(self.old_image_dir, self.manifest["Config"])
        with open(config_path, "r") as f:
            self.old_image_config = json.load(f, object_pairs_hook=OrderedDict)

        # Generate image ID from config hash
        config_content = json.dumps(
            self.old_image_config, sort_keys=True, separators=(",", ":")
        )
        self.old_image_id = (
            f"sha256:{hashlib.sha256(config_content.encode()).hexdigest()}"
        )

        # Extract layer information
        self._extract_docker_layers()

    def _extract_oci_layers(self):
        """Extract layer information for OCI format - based on config history"""
        self.old_image_layers = []

        # Get actual layer digests from manifest (only non-empty layers)
        manifest_layers = []
        for layer_desc in self.manifest.get("layers", []):
            manifest_layers.append(layer_desc["digest"])

        # Build complete layer list from config.history (includes empty layers)
        manifest_layer_index = 0

        for i, history_entry in enumerate(self.old_image_config.get("history", [])):
            is_empty = history_entry.get("empty_layer", False)

            if is_empty:
                # Empty layer - create a virtual layer ID
                layer_id = f"<missing-{i}>"
                self.old_image_layers.append(layer_id)
            else:
                # Real layer - use digest from manifest
                if manifest_layer_index < len(manifest_layers):
                    layer_id = manifest_layers[manifest_layer_index]
                    self.old_image_layers.append(layer_id)
                    manifest_layer_index += 1
                else:
                    self.log.warning(f"Missing layer data for history entry {i}")

        self.log.debug(
            f"Found {len(self.old_image_layers)} layers in OCI image (including empty layers)"
        )
        self.log.debug(f"Manifest has {len(manifest_layers)} actual layer files")

    def _extract_docker_layers(self):
        """Extract layer information for Docker format - based on config history"""
        self.old_image_layers = []

        # Get actual layer paths from manifest (only non-empty layers)
        manifest_layers = self.manifest.get("Layers", [])
        manifest_layer_ids = []
        for layer_path in manifest_layers:
            # Extract layer ID from path (e.g., "abc123.../layer.tar" -> "abc123...")
            layer_id = layer_path.split("/")[0]
            manifest_layer_ids.append(f"sha256:{layer_id}")

        # Build complete layer list from config.history (includes empty layers)
        manifest_layer_index = 0

        for i, history_entry in enumerate(self.old_image_config.get("history", [])):
            is_empty = history_entry.get("empty_layer", False)

            if is_empty:
                # Empty layer - create a virtual layer ID
                layer_id = f"<missing-{i}>"
                self.old_image_layers.append(layer_id)
            else:
                # Real layer - use ID from manifest
                if manifest_layer_index < len(manifest_layer_ids):
                    layer_id = manifest_layer_ids[manifest_layer_index]
                    self.old_image_layers.append(layer_id)
                    manifest_layer_index += 1
                else:
                    self.log.warning(f"Missing layer data for history entry {i}")

        self.log.debug(
            f"Found {len(self.old_image_layers)} layers in Docker image (including empty layers)"
        )
        self.log.debug(f"Manifest has {len(manifest_layer_ids)} actual layer files")

    def _before_squashing(self):
        """Prepare for squashing operation"""
        self.log.info("Preparing for squashing...")

        # Ensure we have image layers
        if not self.old_image_layers:
            raise SquashError("No layers found in image")
        self.log.info("Old image has %s layers", len(self.old_image_layers))
        # Set up squashing parameters
        if self.from_layer is None:
            self.from_layer = len(self.old_image_layers)

        try:
            number_of_layers = int(self.from_layer)
            self.log.debug(f"Squashing last {number_of_layers} layers")
        except ValueError:
            # Handle layer ID as from_layer
            if self.from_layer in self.old_image_layers:
                layer_index = self.old_image_layers.index(self.from_layer)
                number_of_layers = len(self.old_image_layers) - layer_index - 1
            else:
                raise SquashError(f"Layer {self.from_layer} not found in image")

        if number_of_layers <= 0:
            raise SquashError("Number of layers to squash must be positive")

        if number_of_layers > len(self.old_image_layers):
            raise SquashError(
                f"Cannot squash {number_of_layers} layers from {len(self.old_image_layers)} total layers"
            )

        marker = len(self.old_image_layers) - number_of_layers
        self.layers_to_squash = self.old_image_layers[marker:]
        self.layers_to_move = self.old_image_layers[:marker]

        if len(self.layers_to_squash) <= 1:
            raise SquashError("Need at least 2 layers to squash")

        # Set squash_id like v2_image.py does - should be the last real (non-virtual) layer to move
        self.squash_id = None
        if self.layers_to_move:
            # Find the last non-virtual layer in layers_to_move
            for layer_id in reversed(self.layers_to_move):
                if not layer_id.startswith("<missing-"):
                    self.squash_id = layer_id
                    break

            if self.squash_id is None:
                # All layers_to_move are virtual, no squash_id
                self.log.debug("All layers to move are virtual - no squash_id set")

        # Set layer_paths for compatibility with v2_image.py patterns
        self.layer_paths_to_squash = self.layers_to_squash.copy()
        self.layer_paths_to_move = self.layers_to_move.copy()

        self.log.info(f"Will squash {len(self.layers_to_squash)} layers")
        self.log.debug(f"Layers to squash: {self.layers_to_squash}")
        self.log.debug(f"Layers to move: {self.layers_to_move}")
        if hasattr(self, "squash_id"):
            self.log.debug(f"Squash ID: {self.squash_id}")

    def _squash(self):
        """Perform the actual squashing"""
        self.log.info("Starting squashing process...")

        # Create squashed layer directory
        os.makedirs(self.squashed_dir, exist_ok=True)

        # Set up squashed tar path for base class
        self.squashed_tar = os.path.join(self.squashed_dir, "layer.tar")

        # Filter out virtual layers for actual squashing
        real_layers_to_squash = [
            layer_id
            for layer_id in self.layers_to_squash
            if not layer_id.startswith("<missing-")
        ]
        real_layers_to_move = [
            layer_id
            for layer_id in self.layers_to_move
            if not layer_id.startswith("<missing-")
        ]

        self.log.debug(
            f"Filtering for squashing: {len(real_layers_to_squash)} real squash layers, {len(real_layers_to_move)} real move layers"
        )

        # Perform layer squashing using base class method (only on real layers)
        if real_layers_to_squash:
            self._squash_layers(real_layers_to_squash, real_layers_to_move)
        else:
            self.log.info("No real layers to squash - all layers are empty/virtual")

        # Generate diff_ids and chain_ids like v2_image.py does
        self.diff_ids = self._generate_diff_ids()
        self.chain_ids = self._generate_chain_ids(self.diff_ids)

        # Generate new metadata using v2_image.py approach
        new_image_id = self._generate_new_metadata()

        # Create new manifest
        self._create_new_manifest(new_image_id)

        # Move preserved layers to new image directory
        self._move_preserved_layers()

        self.log.info("Squashing completed successfully")
        return new_image_id

    def _after_squashing(self):
        """Post-squashing cleanup and statistics - borrowed from base class"""
        self.size_after = self._dir_size(self.new_image_dir)

        size_before_mb = float(self.size_before) / 1024 / 1024
        size_after_mb = float(self.size_after) / 1024 / 1024

        self.log.info("Original image size: %.2f MB" % size_before_mb)
        self.log.info("Squashed image size: %.2f MB" % size_after_mb)

        if size_after_mb >= size_before_mb:
            self.log.info(
                "If the squashed image is larger than original it means that there were no meaningful files to squash and it just added metadata. Are you sure you specified correct parameters?"
            )

    def _dir_size(self, directory):
        """Calculate directory size - borrowed from base class"""
        size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                if os.path.exists(file_path):
                    size += os.path.getsize(file_path)
        return size

    def _move_preserved_layers(self):
        """Move preserved layers to new image directory"""
        for layer_id in self.layers_to_move:
            layer_tar_path = self._get_layer_tar_path(layer_id)

            if layer_tar_path is None:
                # Virtual/empty layer - skip moving
                self.log.debug(f"Skipping move for virtual layer: {layer_id}")
                continue

            if not os.path.exists(layer_tar_path):
                self.log.warning(f"Preserved layer tar not found: {layer_tar_path}")
                continue

            # Create layer directory in new image
            if self.oci_format:
                # For OCI format, copy the blob
                layer_dir = layer_id.split(":", 1)[1] if ":" in layer_id else layer_id
                dest_blob_dir = os.path.join(self.new_image_dir, "blobs", "sha256")
                os.makedirs(dest_blob_dir, exist_ok=True)
                dest_path = os.path.join(dest_blob_dir, layer_dir)

                # Copy the layer blob
                shutil.copy2(layer_tar_path, dest_path)
            else:
                # For Docker format, copy to layer directory
                layer_dir = layer_id.split(":", 1)[1] if ":" in layer_id else layer_id
                dest_layer_dir = os.path.join(self.new_image_dir, layer_dir)
                os.makedirs(dest_layer_dir, exist_ok=True)
                dest_tar_path = os.path.join(dest_layer_dir, "layer.tar")

                # Copy the layer tar
                shutil.copy2(layer_tar_path, dest_tar_path)

                # Copy the layer json metadata if it exists
                source_json_path = os.path.join(self.old_image_dir, layer_dir, "json")
                if os.path.exists(source_json_path):
                    dest_json_path = os.path.join(dest_layer_dir, "json")
                    shutil.copy2(source_json_path, dest_json_path)

                # Copy version file if it exists
                source_version_path = os.path.join(
                    self.old_image_dir, layer_dir, "VERSION"
                )
                if os.path.exists(source_version_path):
                    dest_version_path = os.path.join(dest_layer_dir, "VERSION")
                    shutil.copy2(source_version_path, dest_version_path)

            self.log.debug(f"Copied preserved layer {layer_id}")

    def _get_layer_tar_path(self, layer_id):
        """Get the path to a layer's tar file"""
        # Handle virtual/empty layers
        if layer_id.startswith("<missing-"):
            return None  # Virtual layer has no tar file

        if self.oci_format:
            # For OCI format, layers are in blobs/sha256/
            if layer_id.startswith("sha256:"):
                digest = layer_id.split(":", 1)[1]
            else:
                digest = layer_id
            return os.path.join(self.old_image_dir, "blobs", "sha256", digest)
        else:
            # For Docker format, layers are in directories
            if layer_id.startswith("sha256:"):
                layer_dir = layer_id.split(":", 1)[1]
            else:
                layer_dir = layer_id
            return os.path.join(self.old_image_dir, layer_dir, "layer.tar")

    def _generate_new_metadata(self):
        """Generate metadata for the new squashed image - based on v2_image.py approach"""
        # First - read old image config, we'll update it instead of generating one from scratch
        metadata = OrderedDict(self.old_image_config)

        # Update image creation date
        metadata["created"] = self.date

        # Remove unnecessary or old fields
        metadata.pop("container", None)

        # Remove squashed layers from history
        metadata["history"] = metadata["history"][: len(self.layers_to_move)]

        # Remove diff_ids for squashed layers
        # Note: diff_ids correspond only to non-empty layers, not all history entries
        if "rootfs" in metadata and "diff_ids" in metadata["rootfs"]:
            # Count non-empty layers in layers_to_move
            non_empty_moved_layers = 0
            for layer_id in self.layers_to_move:
                if not layer_id.startswith("<missing-"):
                    non_empty_moved_layers += 1

            metadata["rootfs"]["diff_ids"] = metadata["rootfs"]["diff_ids"][
                :non_empty_moved_layers
            ]

        # Create history entry for the squashed layer
        history = {"comment": self.comment or "Squashed layers", "created": self.date}

        # Check if we have actual file changes in squashed layers
        real_squashed_layers = [
            layer_id
            for layer_id in self.layers_to_squash
            if not layer_id.startswith("<missing-")
        ]

        if real_squashed_layers and hasattr(self, "diff_ids") and self.diff_ids:
            # Add diff_ids for the squashed layer (only if we have real layers)
            if "rootfs" not in metadata:
                metadata["rootfs"] = {"type": "layers", "diff_ids": []}
            if "diff_ids" not in metadata["rootfs"]:
                metadata["rootfs"]["diff_ids"] = []
            metadata["rootfs"]["diff_ids"].append("sha256:%s" % self.diff_ids[-1])
            self.log.debug(
                f"Added diff_id for squashed layer with {len(real_squashed_layers)} real layers"
            )
        else:
            # All squashed layers are empty - mark as empty layer
            history["empty_layer"] = True
            self.log.debug("Squashed layer marked as empty (all layers were virtual)")

        # Add new entry for squashed layer to history
        metadata["history"].append(history)

        # Update config.Image if we have a squash_id (like v2_image.py does)
        if (
            hasattr(self, "squash_id")
            and self.squash_id
            and not self.squash_id.startswith("<missing-")
        ):
            if "config" not in metadata:
                metadata["config"] = {}
            metadata["config"]["Image"] = self.squash_id
            self.log.debug(f"Set config.Image to squash_id: {self.squash_id}")
        else:
            if "config" in metadata:
                metadata["config"]["Image"] = ""
                self.log.debug("Cleared config.Image (no valid squash_id)")

        # Generate new image ID using the same method as base class
        image_id = self._write_image_metadata(metadata)

        # Create metadata for the squashed layer (Docker format only)
        if not self.oci_format and os.path.exists(
            os.path.join(self.squashed_dir, "layer.tar")
        ):
            self._create_squashed_layer_metadata()

        return image_id

    def _create_squashed_layer_metadata(self):
        """Create JSON metadata file for the squashed layer"""
        # Create layer metadata similar to original layers
        layer_metadata = OrderedDict()
        layer_metadata["id"] = "squashed"
        layer_metadata["created"] = self.date
        layer_metadata["comment"] = self.comment or "Squashed layers"

        # Set parent to the last preserved layer if any
        if self.layers_to_move:
            parent_layer = self.layers_to_move[-1]
            layer_metadata["parent"] = (
                parent_layer.split(":", 1)[1] if ":" in parent_layer else parent_layer
            )

        # Write JSON metadata
        json_path = os.path.join(self.squashed_dir, "json")
        with open(json_path, "w") as f:
            json.dump(layer_metadata, f, indent=2)

        # Write VERSION file
        version_path = os.path.join(self.squashed_dir, "VERSION")
        with open(version_path, "w") as f:
            f.write("1.0")

    def _create_new_manifest(self, new_image_id):
        """Create new manifest for the squashed image"""
        if self.oci_format:
            self._create_oci_manifest(new_image_id)
        else:
            self._create_docker_manifest(new_image_id)

    def _create_docker_manifest(self, new_image_id):
        """Create Docker format manifest"""
        new_manifest = OrderedDict()
        new_manifest["Config"] = f"{new_image_id.split(':')[1]}.json"

        # Handle RepoTags based on user input and original image
        if self.image_name and self.image_tag:
            # User specified a tag - use it
            new_manifest["RepoTags"] = [f"{self.image_name}:{self.image_tag}"]
            self.log.info(
                f"Using user-specified tag: {self.image_name}:{self.image_tag}"
            )
        elif self.tag and not (self.image_name and self.image_tag):
            # User provided tag but parsing failed - warn user
            self.log.warning(
                f"Could not parse tag '{self.tag}', image will have no repository tags"
            )
        else:
            # No user-specified tag - warn about potential consequences
            if self.manifest.get("RepoTags"):
                original_tags = self.manifest["RepoTags"]
                self.log.warning(
                    f"No --tag specified. Original image had tags: {original_tags}"
                )
                self.log.warning(
                    "Consider using --tag to specify a new tag for the squashed image"
                )
                # Don't reuse original tags to avoid overwriting
                self.log.info(
                    "Squashed image will have no repository tags to avoid overwriting original"
                )
            else:
                self.log.info(
                    "No --tag specified and original image had no tags. Squashed image will have no repository tags."
                )

        # Add layers - moved layers plus new squashed layer
        new_manifest["Layers"] = []
        for layer_id in self.layers_to_move:
            # Skip virtual layers
            if layer_id.startswith("<missing-"):
                continue

            if self.oci_format:
                # For OCI format, keep blob structure: blobs/sha256/digest
                layer_dir = layer_id.split(":", 1)[1] if ":" in layer_id else layer_id
                new_manifest["Layers"].append(f"blobs/sha256/{layer_dir}")
            else:
                # For Docker format, use layer directory structure
                layer_dir = layer_id.split(":", 1)[1] if ":" in layer_id else layer_id
                new_manifest["Layers"].append(f"{layer_dir}/layer.tar")

        # Add squashed layer
        if os.path.exists(os.path.join(self.squashed_dir, "layer.tar")):
            new_manifest["Layers"].append("squashed/layer.tar")

        # Write manifest
        manifest_path = os.path.join(self.new_image_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump([new_manifest], f, indent=2)

        # Create repositories.json file for Docker import compatibility
        self._create_repositories_json(new_image_id, new_manifest.get("RepoTags", []))

    def _create_repositories_json(self, image_id, repo_tags):
        """Create repositories.json file for Docker compatibility"""
        repositories = {}

        # Extract image ID without sha256: prefix
        short_image_id = image_id.split(":")[1] if ":" in image_id else image_id

        # Only create repositories entries if we have repo tags
        for repo_tag in repo_tags:
            if ":" in repo_tag:
                repo, tag = repo_tag.rsplit(":", 1)
            else:
                repo, tag = repo_tag, "latest"

            if repo not in repositories:
                repositories[repo] = {}
            repositories[repo][tag] = short_image_id

        # Only write repositories.json if we have tags to avoid confusion
        if repositories:
            repositories_path = os.path.join(self.new_image_dir, "repositories")
            with open(repositories_path, "w") as f:
                json.dump(repositories, f, indent=2)
            self.log.debug(
                f"Created repositories.json with {len(repositories)} repositories"
            )
        else:
            self.log.debug(
                "No repository tags to write, skipping repositories.json creation"
            )

    def _create_oci_manifest(self, new_image_id):
        """Create OCI format manifest"""
        # For OCI format, we'll create both index.json and manifest blob
        # This is a simplified implementation - full OCI support would need more work
        self.log.warning(
            "OCI output format not fully implemented - creating Docker format"
        )
        self._create_docker_manifest(new_image_id)

    def _extract_tar_name(self, layer_id):
        """Get the path to a layer's tar file - used by base class _squash_layers method"""
        return self._get_layer_tar_path(layer_id)

    def _generate_diff_ids(self):
        """Generate diff_ids for layers - borrowed from v2_image.py"""
        diff_ids = []

        for layer_id in self.layers_to_move:
            layer_tar_path = self._get_layer_tar_path(layer_id)

            if layer_tar_path is None:
                # Virtual/empty layer - skip diff_id calculation
                self.log.debug(f"Skipping diff_id for virtual layer: {layer_id}")
                continue

            if os.path.exists(layer_tar_path):
                sha256 = self._compute_sha256(layer_tar_path)
                diff_ids.append(sha256)
            else:
                self.log.warning(
                    f"Layer tar not found for diff_id calculation: {layer_tar_path}"
                )

        if self.layers_to_squash and os.path.exists(
            os.path.join(self.squashed_dir, "layer.tar")
        ):
            sha256 = self._compute_sha256(os.path.join(self.squashed_dir, "layer.tar"))
            diff_ids.append(sha256)

        self.log.debug(
            f"Generated {len(diff_ids)} diff_ids from {len(self.layers_to_move)} moved layers"
        )
        return diff_ids

    def _compute_sha256(self, file_path):
        """Compute SHA256 hash of a file - borrowed from v2_image.py"""
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            while True:
                # Read in 10MB chunks
                data = f.read(10485760)
                if not data:
                    break
                sha256.update(data)

        return sha256.hexdigest()

    def _generate_chain_ids(self, diff_ids):
        """Generate chain_ids from diff_ids - borrowed from v2_image.py"""
        chain_ids = []
        self._generate_chain_id(chain_ids, diff_ids, None)
        return chain_ids

    def _generate_chain_id(self, chain_ids, diff_ids, parent_chain_id):
        """Recursively generate chain_id - borrowed from v2_image.py"""
        if parent_chain_id is None:
            return self._generate_chain_id(chain_ids, diff_ids[1:], diff_ids[0])

        chain_ids.append(parent_chain_id)

        if len(diff_ids) == 0:
            return parent_chain_id

        # This probably should not be hardcoded
        to_hash = "sha256:%s sha256:%s" % (parent_chain_id, diff_ids[0])
        digest = hashlib.sha256(str(to_hash).encode("utf8")).hexdigest()

        return self._generate_chain_id(chain_ids, diff_ids[1:], digest)

    def _write_image_metadata(self, metadata):
        """Write image metadata and return image ID - borrowed from v2_image.py"""
        # Create JSON from the metadata
        # Docker adds new line at the end
        json_metadata, image_id = self._dump_json(metadata, True)
        image_metadata_file = os.path.join(self.new_image_dir, "%s.json" % image_id)

        self._write_json_metadata(json_metadata, image_metadata_file)

        return f"sha256:{image_id}"

    def _dump_json(self, data, new_line=False):
        """Dump JSON data and calculate hash - borrowed from base class"""
        json_metadata = json.dumps(data, sort_keys=True, separators=(",", ":"))

        if new_line:
            json_metadata += "\n"

        # Calculate image ID (SHA256 of the JSON metadata)
        image_id = hashlib.sha256(json_metadata.encode()).hexdigest()

        return json_metadata, image_id

    def _write_json_metadata(self, metadata, metadata_file):
        """Write JSON metadata to file - borrowed from base class"""
        with open(metadata_file, "w") as f:
            f.write(metadata)

    def export_tar_archive(self, output_path):
        """Export the squashed image as a tar archive"""
        self.log.info(f"Exporting squashed image to {output_path}")

        with tarfile.open(output_path, "w") as tar:
            # Add all files from new_image_dir
            for root, dirs, files in os.walk(self.new_image_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.new_image_dir)
                    tar.add(file_path, arcname=arcname)

        self.log.info("Export completed successfully")

    def load_squashed_image(self):
        """Load the squashed image into Docker daemon"""
        try:
            from docker_squash.lib import common

            docker = common.docker_client(self.log)

            # Create a temporary tar file for loading
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as temp_file:
                temp_tar_path = temp_file.name

            try:
                # Export the squashed image to temporary tar
                self.export_tar_archive(temp_tar_path)

                # Load into Docker
                self.log.info("Loading squashed image into Docker daemon...")
                with open(temp_tar_path, "rb") as f:
                    docker.load_image(f)

                self.log.info("Image loaded successfully")

            finally:
                # Clean up temporary file
                if os.path.exists(temp_tar_path):
                    os.unlink(temp_tar_path)

        except ImportError:
            self.log.warning(
                "Docker client not available - cannot load image into daemon"
            )
        except Exception as e:
            raise SquashError(f"Failed to load image into Docker daemon: {e}")

    def cleanup(self):
        """Clean up temporary directories"""
        if self.tmp_dir and os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            self.log.debug(f"Cleaned up temporary directory: {self.tmp_dir}")
