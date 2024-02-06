import builtins
import unittest
from collections import OrderedDict

import mock

from docker_squash.v2_image import V2Image


class TestReadingConfigFiles(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.image = V2Image(self.log, self.docker_client, self.image, None)

    def test_should_read_json_file(self):
        manifest_example = '[{"Config":"96bdd3be20fa51b22dc9aaf996b49d403a403adf96e35d7e8b98519267c21c21.json","RepoTags":["busybox-to-squash:squashed"],"Layers":["980a6c63f88351bea42851fc101e4e2f61b12e1bf70122aad1f25186a736a404/layer.tar","977b2156300ec11226ffc7f9382e2fe4ec10a9cdfe445e062542b430aa09d82d/layer.tar","8a646a2ab402ca2774063c602182ad22c09d4af236ed84bdddb6d1205309accf/layer.tar"]}]'

        with mock.patch.object(
            builtins, "open", mock.mock_open(read_data=manifest_example)
        ):
            manifest = self.image._read_json_file("/tmp/old/manifest.json")

        # Manifest is an array
        manifest = manifest[0]

        self.assertEqual(
            manifest["Config"],
            "96bdd3be20fa51b22dc9aaf996b49d403a403adf96e35d7e8b98519267c21c21.json",
        )
        self.assertEqual(manifest["RepoTags"], ["busybox-to-squash:squashed"])
        self.assertEqual(
            manifest["Layers"],
            [
                "980a6c63f88351bea42851fc101e4e2f61b12e1bf70122aad1f25186a736a404/layer.tar",
                "977b2156300ec11226ffc7f9382e2fe4ec10a9cdfe445e062542b430aa09d82d/layer.tar",
                "8a646a2ab402ca2774063c602182ad22c09d4af236ed84bdddb6d1205309accf/layer.tar",
            ],
        )
        self.log.debug.assert_called_with(
            "Reading '/tmp/old/manifest.json' JSON file..."
        )


class TestGeneratingMetadata(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.image = V2Image(self.log, self.docker_client, self.image, None)

    def test_generate_manifest(self):
        old_image_manifest = {
            "Layers": ["layer_a/layer.tar", "layer_b/layer.tar", "layer_c/layer.tar"]
        }
        layer_paths_to_move = ["layer_a", "layer_b"]

        metadata = self.image._generate_manifest_metadata(
            "this_is_image_id",
            "image",
            "squashed",
            old_image_manifest,
            layer_paths_to_move,
            "this_is_layer_path_id",
        )

        self.assertEqual(len(metadata), 1)

        metadata = metadata[0]

        self.assertEqual(type(metadata), OrderedDict)
        self.assertEqual(metadata["Config"], "this_is_image_id.json")
        self.assertEqual(metadata["RepoTags"], ["image:squashed"])
        self.assertEqual(
            metadata["Layers"],
            [
                "layer_a/layer.tar",
                "layer_b/layer.tar",
                "this_is_layer_path_id/layer.tar",
            ],
        )

    def test_generate_image_metadata_without_any_layers_to_squash(self):
        self.image.old_image_dir = "/tmp/old"
        self.image.squash_id = "squash_id"
        self.image.date = "squashed_date"
        self.image.diff_ids = ["diffid_1", "diffid_2"]
        # We want to move 3 layers (including empty)
        self.image.layers_to_move = ["layer_id_1", "layer_id_2", "layer_id_3"]
        # We want to move 2 layers with content
        self.image.layer_paths_to_move = ["layer_path_1", "layer_path_2"]
        self.image.layer_paths_to_squash = []
        # Image that contains:
        # - 4 layers
        # - 3 layers that have content
        self.image.old_image_config = OrderedDict(
            {
                "config": {"Image": "some_id"},
                "container": "container_id",
                "created": "old_date",
                "history": [
                    {"created": "date1"},
                    {"created": "date2"},
                    {"created": "date3"},
                    {"created": "date4"},
                ],
                "rootfs": {"diff_ids": ["sha256:a", "sha256:b", "sha256:c"]},
            }
        )

        metadata = self.image._generate_image_metadata()

        self.assertEqual(type(metadata), OrderedDict)
        # 2 layer data's from moved layers, no squashed layer
        self.assertEqual(metadata["rootfs"]["diff_ids"], ["sha256:a", "sha256:b"])
        # 3 moved layers + squashed layer info
        self.assertEqual(
            metadata["history"],
            [
                {"created": "date1"},
                {"created": "date2"},
                {"created": "date3"},
                {"comment": "", "created": "squashed_date", "empty_layer": True},
            ],
        )

    def test_generate_image_metadata(self):
        self.image.old_image_dir = "/tmp/old"
        self.image.squash_id = "squash_id"
        self.image.date = "squashed_date"
        self.image.diff_ids = ["diffid_1", "diffid_2"]
        # We want to move 3 layers (including empty)
        self.image.layers_to_move = ["lauer_id_1", "layer_id_2", "layer_id_3"]
        # We want to move 2 layers with content
        self.image.layer_paths_to_move = ["layer_path_1", "layer_path_2"]
        self.image.layer_paths_to_squash = ["layer_path_3", "layer_path_4"]
        # Image that contains:
        # - 4 layers
        # - 3 layers that have content
        self.image.old_image_config = OrderedDict(
            {
                "config": {"Image": "some_id"},
                "container": "container_id",
                "created": "old_date",
                "history": [
                    {"created": "date1"},
                    {"created": "date2"},
                    {"created": "date3"},
                    {"created": "date4"},
                ],
                "rootfs": {"diff_ids": ["sha256:a", "sha256:b", "sha256:c"]},
            }
        )

        metadata = self.image._generate_image_metadata()

        self.assertEqual(type(metadata), OrderedDict)
        self.assertEqual(metadata["created"], "squashed_date")
        self.assertEqual(metadata["config"]["Image"], "squash_id")
        # 2 layer data's from moved layers + 1 layer data from squashed
        # layer
        self.assertEqual(
            metadata["rootfs"]["diff_ids"], ["sha256:a", "sha256:b", "sha256:diffid_2"]
        )
        # 3 moved layers + 1 squashed layer in history
        self.assertEqual(
            metadata["history"],
            [
                {"created": "date1"},
                {"created": "date2"},
                {"created": "date3"},
                {"comment": "", "created": "squashed_date"},
            ],
        )
        self.assertEqual(metadata.pop("container", None), None)

    def test_generate_squashed_layer_metadata(self):
        self.image.date = "squashed_date"
        self.image.old_image_dir = "/tmp/old"
        self.image.squash_id = "squash_id"
        self.image.layer_paths_to_squash = ["layer_a", "layer_b"]
        self.image.layer_paths_to_move = ["layer_c", "layer_d"]

        layer_config = '{"created": "old_created", "config": {"Image": "old_id"}, "container": "container_id"}'

        with mock.patch.object(
            builtins, "open", mock.mock_open(read_data=layer_config)
        ):
            metadata = self.image._generate_last_layer_metadata(
                "squashed_layer_path_id", "squashed_layer_path_id"
            )

            self.assertEqual(type(metadata), OrderedDict)
            self.assertEqual(metadata.pop("container", None), None)
            self.assertEqual(metadata["created"], "squashed_date")
            self.assertEqual(metadata["parent"], "layer_d")
            self.assertEqual(metadata["id"], "squashed_layer_path_id")
            self.assertEqual(metadata["config"]["Image"], "squash_id")

    def test_generate_squashed_layer_path_id(self):
        # We need to preserve order here
        self.image.old_image_config = OrderedDict(
            [
                ("config", {"Image": "some_id"}),
                ("container", "container_id"),
                ("os", "linux"),
                ("created", "old_date"),
                (
                    "history",
                    [
                        {"created": "date1"},
                        {"created": "date2"},
                        {"created": "date3"},
                        {"created": "date4"},
                    ],
                ),
                ("rootfs", {"diff_ids": ["sha256:a", "sha256:b", "sha256:c"]}),
            ]
        )
        self.image.layer_paths_to_squash = ["layer_a", "layer_b"]
        self.image.layer_paths_to_move = ["layer_c", "layer_d"]
        self.image.squash_id = "squash_id"
        self.image.chain_ids = ["chain_id1", "chain_id2", "chain_id3", "chain_id4"]
        self.image.date = "squashed_date"

        # Generated JSON: {"config":{"Image":"squash_id"},"created":"squashed_date","layer_id":"sha256:chain_id4","os":"linux","parent":"sha256:layer_d"}
        # sha256sum of it:
        # 2c52e8c273e5169fcca086c5a35ae2244cf4a561bd7323f65577109a3489a2e3

        self.assertEqual(
            self.image._generate_squashed_layer_path_id(),
            "2c52e8c273e5169fcca086c5a35ae2244cf4a561bd7323f65577109a3489a2e3",
        )


class TestWritingMetadata(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.image = V2Image(self.log, self.docker_client, self.image, None)

    @mock.patch.object(V2Image, "_write_json_metadata")
    def test_write_image_metadata(self, mock_method):
        self.image.new_image_dir = "/tmp/new"
        metadata = OrderedDict([("a", "something"), ("b", 12)])
        image_id = self.image._write_image_metadata(metadata)

        mock_method.assert_called_with(
            '{"a":"something","b":12}\n',
            "/tmp/new/b3a8bc9dad2103f11e99ebc5ce113c08d1dc31299c247ddd87aca1f048560db3.json",
        )

        self.assertEqual(
            image_id, "b3a8bc9dad2103f11e99ebc5ce113c08d1dc31299c247ddd87aca1f048560db3"
        )

    @mock.patch.object(V2Image, "_write_json_metadata")
    def test_write_squashed_layer_metadata(self, mock_method):
        self.image.squashed_dir = "/tmp/squashed"
        metadata = OrderedDict([("a", "something"), ("b", 12)])
        self.image._write_squashed_layer_metadata(metadata)
        mock_method.assert_called_with('{"a":"something","b":12}', "/tmp/squashed/json")

    @mock.patch.object(V2Image, "_write_json_metadata")
    def test_write_manifest_metadata(self, mock_method):
        self.image.new_image_dir = "/tmp/new"
        metadata = OrderedDict([("a", "something"), ("b", 12)])
        self.image._write_manifest_metadata(metadata)
        mock_method.assert_called_with(
            '{"a":"something","b":12}\n', "/tmp/new/manifest.json"
        )


if __name__ == "__main__":
    unittest.main()
