import unittest
import logging
import mock
from docker_scripts.squash import Squash


class TestSkippingFiles(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = logger = logging.getLogger(__name__)
        self.image = "wahtever"
        self.squash = Squash(self.log, self.image, self.docker_client)

    def test_should_skip_exact_files(self):
        ret = self.squash._file_should_be_skipped(
            '/opt/webserver/something', ['/opt/eap', '/opt/webserver/something'])
        self.assertTrue(ret)

    def test_should_not_skip_file_not_in_path_to_skip(self):
        ret = self.squash._file_should_be_skipped(
            '/opt/webserver/tmp', ['/opt/eap', '/opt/webserver/something'])
        self.assertFalse(ret)

    def test_should_not_skip_the_file_that_name_is_similar_to_skipped_path(self):
        ret = self.squash._file_should_be_skipped(
            '/opt/webserver/tmp1234', ['/opt/eap', '/opt/webserver/tmp'])
        self.assertFalse(ret)

    def test_should_skip_files_in_subdirectory(self):
        ret = self.squash._file_should_be_skipped(
            '/opt/webserver/tmp/abc', ['/opt/eap', '/opt/webserver/tmp'])
        self.assertTrue(ret)

if __name__ == '__main__':
    unittest.main()
