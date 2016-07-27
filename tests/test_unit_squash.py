import unittest
import mock
import six
import logging

from docker_squash.squash import Squash
from docker_squash.image import Image
from docker_squash.errors import SquashError


class TestSquash(unittest.TestCase):
    
    def setUp(self):
        self.log = mock.Mock()
        self.docker_client = mock.Mock()
        self.docker_client.version.return_value = {'GitCommit': "commit/9.9.9", 'ApiVersion': "9.99"}

    def test_handle_case_when_no_image_is_provided(self):
        squash = Squash(self.log, None, self.docker_client)
        with self.assertRaises(SquashError) as cm:
            squash.run()
        self.assertEquals(
            str(cm.exception), "Image is not provided")

    def test_exit_if_no_output_path_provided_and_loading_is_disabled_too(self):
        squash = Squash(self.log, 'image', self.docker_client, load_image=False, output_path=None)
        squash.run()
        self.log.warn.assert_called_with("No output path specified and loading into Docker is not selected either; squashed image would not accessible, proceeding with squashing doesn't make sense")

    @mock.patch('docker_squash.squash.V2Image')
    def test_should_not_cleanup_after_squashing(self, v2_image):
        squash = Squash(self.log, 'image', self.docker_client, load_image=True)
        squash.run()
    
        v2_image.cleanup.assert_not_called()

    @mock.patch('docker_squash.squash.V2Image')
    def test_should_cleanup_after_squashing(self, v2_image):
        self.docker_client.inspect_image.return_value = {'Id': "abcdefgh"}
        squash = Squash(self.log, 'image', self.docker_client, load_image=True, cleanup=True)
        squash.run()
    
        self.docker_client.remove_image.assert_called_with('abcdefgh', force=False, noprune=False)
