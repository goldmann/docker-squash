
import hashlib
import json
import os
import shutil

from collections import OrderedDict
from docker_scripts.image import Image

class MyOrderedDict(OrderedDict):

    def prepend(self, key, value, dict_setitem=dict.__setitem__):

        root = self._OrderedDict__root
        first = root[1]

        if key in self:
            link = self._OrderedDict__map[key]
            link_prev, link_next, _ = link
            link_prev[1] = link_next
            link_next[0] = link_prev
            link[0] = root
            link[1] = first
            root[1] = first[0] = link
        else:
            root[1] = first[0] = self._OrderedDict__map[key] = [root, first, key]
            dict_setitem(self, key, value)

class V2Image(Image):
    FORMAT = 'v2'

    def _squash(self):
        self._read_manifest_file()
        self._read_config_file()
        self._read_layer_paths()

        self._squash_layers(self.layer_path_to_squash, self.layer_path_to_move)
        # Generate image metadata
        metadata = self._generate_image_metadata()

        json_metadata = "%s\n" % json.dumps(metadata, separators=(',', ':'))
        # Calculate image ID from JSON
        image_id = hashlib.sha256(json_metadata).hexdigest()

        image_metadata_file = os.path.join(self.new_image_dir, "%s.json" % image_id)
        self._write_json_metadata(json_metadata, image_metadata_file)

        metadata = self._generate_squashed_layer_metadata()

        chain_ids = self._new_chain_ids()
        layer_path_id = self._generate_squashed_layer_path_id(self.old_image_config, chain_ids[-1])

        # Update id - it should be the path to the layer
        metadata['id'] = layer_path_id 
        metadata['parent'] = self.layer_path_to_move[-1]

        layer_metadata_file = os.path.join(self.squashed_dir, "json")
        json_metadata = json.dumps(metadata, separators=(',', ':'))

        self._write_json_metadata("%s" % json_metadata, layer_metadata_file)

        self._write_version_file(self.squashed_dir)
        # Move all the layers that should be untouched
        self._move_layers(self.layer_path_to_move, self.old_image_dir, self.new_image_dir)

        shutil.move(self.squashed_dir, os.path.join(self.new_image_dir, layer_path_id))

        manifest = OrderedDict()
        manifest['Config'] = "%s.json" % image_id
        manifest['RepoTags'] = ["%s:%s" % (self.image_name, self.image_tag)]
        manifest['Layers'] = self.old_image_manifest['Layers'][:len(self.layer_path_to_move)]
        manifest['Layers'].append("%s/layer.tar" % layer_path_id)

        manifest_file = os.path.join(self.new_image_dir, "manifest.json")
        json_manifest = json.dumps([manifest], separators=(',', ':'))

        self._write_json_metadata("%s\n" % json_manifest, manifest_file)
        repositories_file = os.path.join(self.new_image_dir, "repositories")
        self._generate_repositories_json(repositories_file, layer_path_id, self.image_name, self.image_tag)

        return image_id

    def _read_manifest_file(self):
        manifest_file = os.path.join(self.old_image_dir, "manifest.json")

        self.log.debug("Reading old image manifest file: '%s'..." % manifest_file)

        # Read manifest.json file which contains information about
        # layers stored with the image
        with open(manifest_file, 'r') as f:
            self.old_image_manifest = json.load(f)[0]

    def _read_config_file(self):
        config_file = os.path.join(self.old_image_dir, self.old_image_manifest['Config'])

        self.log.debug("Reading old image config file: '%s'..." % config_file)

        # Read image configuration file - it contains information about
        # image history
        with open(config_file, 'r') as f:
            self.old_image_config = json.load(f, object_pairs_hook=OrderedDict)

    def _read_layer_paths(self):
        """
        In case of v2 format, layerd id's are not the same as the id's
        used in the exported tar archive to name directories for layers.
        These id's can be found in the configuration files saved with
        the image - we need to read them.
        """

        current_manifest_layer = 0

        self.layer_path_to_move = []
        self.layer_path_to_squash = []

        # Iterate over image history, from base image to top layer
        for i, layer in enumerate(self.old_image_config['history']):

            # If it's not an empty layer
            if not layer.get('empty_layer', False):
                layer_id = self.old_image_manifest['Layers'][current_manifest_layer].rsplit('/')[0]

                if len(self.layers_to_move) > i:
                    self.layer_path_to_move.append(layer_id)
                else:
                    self.layer_path_to_squash.append(layer_id)

                current_manifest_layer += 1


        return self.layer_path_to_squash, self.layer_path_to_move


    def _generate_chain_id(self, parent_chain_id, diff_ids, chain_ids):
        if parent_chain_id == None:
            return self._generate_chain_id(diff_ids[0], diff_ids[1:], chain_ids)

        chain_ids.append(parent_chain_id) 

        if len(diff_ids) == 0:
            return parent_chain_id

        # This probably should not be hardcoded
        to_hash = "sha256:%s sha256:%s" % (parent_chain_id, diff_ids[0])
        digest = hashlib.sha256(str(to_hash).encode('utf8')).hexdigest()

        return self._generate_chain_id(digest, diff_ids[1:], chain_ids)

    def _new_diff_ids(self):
        diff_ids = []

        for path in self.layer_path_to_move:
            with open(os.path.join(self.old_image_dir, path, "layer.tar"), 'rb') as f:
                # Make this more efficient, layers can be big!
                diff_ids.append(hashlib.sha256(f.read()).hexdigest())

        with open(os.path.join(self.squashed_dir, "layer.tar"), 'rb') as f:
            diff_ids.append(hashlib.sha256(f.read()).hexdigest())

        return diff_ids

    def _new_chain_ids(self):
        diff_ids = self._new_diff_ids()
        chain_ids = []

        self._generate_chain_id(None, diff_ids, chain_ids)

        return chain_ids

    def _generate_squashed_layer_path_id(self, metadata, chain_id):
        """
        This function generates the id used to name the directory to
        store the squashed layer content in the archive.

        This mimics what Docker does here: https://github.com/docker/docker/blob/v1.10.0-rc1/image/v1/imagev1.go#L42
        To make it simpler we do reuse old image metadata and
        modify it to what it should look which means to be exact
        as https://github.com/docker/docker/blob/v1.10.0-rc1/image/v1/imagev1.go#L64
        """

        # Using OrderedDict, because order of JSON keys is important
        v1_metadata = OrderedDict(metadata)

        # Update image creation date
        v1_metadata['created'] = self.date

        # Remove unnecessary elements
        # Do not fail if key is not found
        for key in 'history', 'rootfs', 'container':
            v1_metadata.pop(key, None)

        # Docker internally changes the order of keys between
        # exported metadata (why oh why?!). We need to add 'os'
        # element after 'layer_id'
        operating_system = v1_metadata.pop('os', None)

        # The 'layer_id' element is the chain_id of the
        # squashed layer
        v1_metadata['layer_id'] = "sha256:%s" % chain_id

        # Add back 'os' element
        if operating_system:
            v1_metadata['os'] = operating_system

        # The 'parent' element is the name of the directory (inside the
        # exported tar archive) of the last layer that we move
        # (layer below squashed layer)
        v1_metadata['parent'] =  "sha256:%s" % self.layer_path_to_move[-1]

        # The 'Image' element is the id of the layer from which we squash
        v1_metadata['config']['Image'] = self.squash_id

        # Get the sha256sum of the JSON exported metadata,
        # we do not care about the metadata anymore
        _, sha = self._dump_json(v1_metadata)

        return sha

    def _dump_json(self, data):
        # We do not want any spaces between keys and values in JSON
        json_data = json.dumps(data, separators=(',', ':'))
        # Generate sha256sum of the JSON data, may be handy
        sha = hashlib.sha256("%s" % json_data).hexdigest()
        
        return json_data, sha

    def _generate_squashed_layer_metadata(self):
        config_file = os.path.join(self.old_image_dir, self.layer_path_to_squash[0], "json")
        with open(config_file, 'r') as f:
            config = json.load(f, object_pairs_hook=OrderedDict)
        
        config['created'] = self.date
        config['config']['Image'] = self.squash_id
        del config['container']
        print"config"
        print config
        return config

    def _generate_image_metadata(self):
        
        # First - read old image config, we'll update it instead of
        # generating one from scratch
        metadata = OrderedDict(self.old_image_config)
        print metadata
        # Update image creation date
        metadata['created'] = self.date

        # Remove unnecessary or old fields
        del metadata['container']
        #del metadata['container_config']
        #del metadata['config']['Hostname']

        # Remove squashed layers from history
        metadata['history'] = metadata['history'][:len(self.layers_to_move)]
        # Add new entry for squashed layer to history
        # TODO: what with empty layers?!
        metadata['history'].append({'comment': '', 'created': self.date})

        # Remove diff_ids for squashed layers
        metadata['rootfs']['diff_ids'] = metadata['rootfs']['diff_ids'][:len(self.layer_path_to_move)]
        # Add diff_ids for the squashed layer
        metadata['rootfs']['diff_ids'].append("sha256:%s" % self._new_diff_ids()[-1])

        # Update image id, should be one layer below squashed layer
        #metadata['config']['Image'] = self.layers_to_move[0]
        metadata['config']['Image'] = self.squash_id

        return metadata
