import hashlib
import os
import random
import shutil

from docker_squash.image import Image


class V1Image(Image):
    FORMAT = 'v1'

    def _generate_image_id(self):
        while True:
            image_id = hashlib.sha256(
                str(random.getrandbits(128)).encode('utf8')).hexdigest()

            try:
                int(image_id[0:10])
            except ValueError:
                # All good!
                return image_id

    def _before_squashing(self):
        super(V1Image, self)._before_squashing()

        if self.layers_to_move:
            self.squash_id = self.layers_to_move[-1]

    def _squash(self):
        # Prepare the directory
        os.makedirs(self.squashed_dir)
        self._squash_layers(self.layers_to_squash, self.layers_to_move)
        self._write_version_file(self.squashed_dir)
        # Move all the layers that should be untouched
        self._move_layers(self.layers_to_move,
                          self.old_image_dir, self.new_image_dir)

        config_file = os.path.join(
            self.old_image_dir, self.old_image_id, "json")

        image_id = self._update_squashed_layer_metadata(
            config_file, self.squashed_dir)
        shutil.move(self.squashed_dir, os.path.join(
            self.new_image_dir, image_id))
        repositories_file = os.path.join(self.new_image_dir, "repositories")
        self._generate_repositories_json(
            repositories_file, image_id, self.image_name, self.image_tag)

        return image_id

    def _update_squashed_layer_metadata(self, old_json_file, squashed_dir):
        image_id = self._generate_image_id()

        metadata = self._read_old_metadata(old_json_file)

        # Modify common metadata fields
        if self.squash_id:
            metadata['config']['Image'] = self.squash_id
        else:
            metadata['config'].pop('Image', None)

        if 'parent_id' in metadata and self.squash_id:
            metadata['parent_id'] = "sha256:%s" % self.squash_id
        else:
            metadata.pop('parent_id', None)

        metadata.pop('layer_id', None)

        metadata['created'] = self.date

        # Remove unnecessary fields
        del metadata['container_config']
        del metadata['container']
        del metadata['config']['Hostname']

        if self.squash_id:
            metadata['parent'] = self.squash_id
        else:
            metadata.pop('parent', None)

        metadata['id'] = image_id
        metadata['Size'] = os.path.getsize(
            os.path.join(squashed_dir, "layer.tar"))
        json_metadata = self._dump_json(metadata)[0]

        self._write_json_metadata(
            "%s" % json_metadata, os.path.join(squashed_dir, "json"))

        return image_id
