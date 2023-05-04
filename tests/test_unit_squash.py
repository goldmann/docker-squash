import unittest

import docker
import mock

from docker_squash.errors import SquashError
from docker_squash.squash import Squash


class TestSquash(unittest.TestCase):
    def setUp(self):
        self.log = mock.Mock()
        self.docker_client = mock.Mock()
        self.docker_client.version.return_value = {
            "Version": "20.10.23",
            "ApiVersion": "9.99",
        }

    def test_handle_case_when_no_image_is_provided(self):
        squash = Squash(self.log, None, self.docker_client)
        with self.assertRaises(SquashError) as cm:
            squash.run()
        self.assertEqual(str(cm.exception), "Image is not provided")

    def test_exit_if_no_output_path_provided_and_loading_is_disabled_too(self):
        squash = Squash(
            self.log, "image", self.docker_client, load_image=False, output_path=None
        )
        squash.run()
        self.log.warning.assert_called_with(
            "No output path specified and loading into Docker is not selected either; squashed image would not accessible, proceeding with squashing doesn't make sense"
        )

    @mock.patch("docker_squash.squash.V2Image")
    def test_should_not_cleanup_after_squashing(self, v2_image):
        squash = Squash(self.log, "image", self.docker_client, load_image=True)
        squash.run()

        v2_image.cleanup.assert_not_called()

    @mock.patch("docker_squash.squash.V2Image")
    def test_should_cleanup_after_squashing(self, v2_image):
        self.docker_client.inspect_image.return_value = {"Id": "abcdefgh"}

        squash = Squash(
            self.log, "image", self.docker_client, load_image=True, cleanup=True
        )
        squash.run()

        self.docker_client.remove_image.assert_called_with(
            "abcdefgh", force=False, noprune=False
        )
        self.log.info.assert_any_call("Image image removed!")

    @mock.patch("docker_squash.squash.V2Image")
    def test_should_handle_cleanup_error_while_getting_image_id(self, v2_image):
        self.docker_client.inspect_image.side_effect = docker.errors.APIError("Message")

        squash = Squash(
            self.log, "image", self.docker_client, load_image=True, cleanup=True
        )
        squash.run()

        self.docker_client.remove_image.assert_not_called()
        self.log.warning.assert_any_call(
            "Could not get the image ID for image image: Message, skipping cleanup after squashing"
        )

    @mock.patch("docker_squash.squash.V2Image")
    def test_should_handle_cleanup_error_when_removing_image(self, v2_image):
        self.docker_client.inspect_image.return_value = {"Id": "abcdefgh"}
        self.docker_client.remove_image.side_effect = docker.errors.APIError("Message")

        squash = Squash(
            self.log, "image", self.docker_client, load_image=True, cleanup=True
        )
        squash.run()

        self.log.info.assert_any_call("Removing old image image...")
        self.log.warning.assert_any_call(
            "Could not remove image image: Message, skipping cleanup after squashing"
        )
