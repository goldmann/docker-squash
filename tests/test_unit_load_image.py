import os
import shutil
import tempfile
import unittest

import mock

from docker_squash.errors import SquashError
from docker_squash.v2_image import V2Image


class TestLoadImage(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = V2Image(
            self.log, self.docker_client, "whatever", None, tmp_dir=self.tmp_dir
        )
        self.image._tar_image = mock.Mock(side_effect=self._fake_tar)

    def _fake_tar(self, target, directory):
        with open(target, "wb") as f:
            f.write(b"x")

    def test_returns_id_from_loaded_image_id_message(self):
        self.docker_client.load_image.return_value = iter(
            [{"stream": "Loaded image ID: sha256:abc123\n"}]
        )

        self.assertEqual(self.image._load_image("dir"), "abc123")
        self.docker_client.inspect_image.assert_not_called()

    def test_resolves_id_from_loaded_image_reference(self):
        self.docker_client.load_image.return_value = iter(
            [{"stream": "Loaded image: repo:tag\n"}]
        )
        self.docker_client.inspect_image.return_value = {"Id": "sha256:def456"}

        self.assertEqual(self.image._load_image("dir"), "def456")
        self.docker_client.inspect_image.assert_called_with("repo:tag")

    def test_returns_none_when_reply_cannot_be_parsed(self):
        self.docker_client.load_image.return_value = iter([{"stream": "something"}])

        self.assertIsNone(self.image._load_image("dir"))

    def test_raises_when_daemon_rejects_the_archive(self):
        self.docker_client.load_image.return_value = iter(
            [{"error": 'layer "blobs/sha256/abc" not found'}]
        )

        with self.assertRaises(SquashError):
            self.image._load_image("dir")


class TestMoveLayers(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = os.path.join(self.root, "src")
        self.dest = os.path.join(self.root, "dest")
        os.makedirs(self.dest)
        self.image = V2Image(mock.Mock(), mock.Mock(), "whatever", None)

    def test_keeps_relative_path_of_oci_layers(self):
        os.makedirs(os.path.join(self.src, "blobs", "sha256"))
        with open(os.path.join(self.src, "blobs", "sha256", "abc"), "w") as f:
            f.write("layer")

        self.image._move_layers(["blobs/sha256/abc"], self.src, self.dest)

        self.assertTrue(os.path.isfile(os.path.join(self.dest, "blobs/sha256/abc")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "abc")))

    def test_moves_legacy_layer_directories(self):
        os.makedirs(os.path.join(self.src, "abc"))
        with open(os.path.join(self.src, "abc", "layer.tar"), "w") as f:
            f.write("layer")

        self.image._move_layers(["abc"], self.src, self.dest)

        self.assertTrue(os.path.isfile(os.path.join(self.dest, "abc", "layer.tar")))
