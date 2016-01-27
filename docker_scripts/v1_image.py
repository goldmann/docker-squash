import hashlib
import os
import random
import shutil

from docker_scripts.image import Image

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

    def _squash(self):
        self._squash_layers(self.layers_to_squash, self.layers_to_move)
        self._write_version_file(self.squashed_dir)
        # Move all the layers that should be untouched
        self._move_layers(self.layers_to_move, self.old_image_dir, self.new_image_dir)
        
        config_file = os.path.join(self.old_image_dir, self.old_image_id, "json")
        
        image_id = self.update_squashed_layer_metadata(config_file, self.squashed_dir)
        shutil.move(self.squashed_dir, os.path.join(self.new_image_dir, image_id))
        repositories_file = os.path.join(self.new_image_dir, "repositories")
        self._generate_repositories_json(repositories_file, image_id, self.image_name, self.image_tag)

    def update_squashed_layer_metadata(self, old_json_file, squashed_dir):
        image_id = self._generate_image_id()

        metadata = self._layer_metadata(old_json_file)
        metadata['parent'] = self.squash_id
        metadata['id'] = image_id
        metadata['Size'] = os.path.getsize(os.path.join(self.squashed_dir, "layer.tar"))
        json_metadata = self._dump_json(metadata)[0]

        self._write_json_metadata("%s" % json_metadata, os.path.join(self.squashed_dir, "json"))

        return image_id
