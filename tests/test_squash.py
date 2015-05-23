import unittest
import mock
from docker_scripts.squash import Squash


class TestSkippingFiles(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
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


class TestParseImageName(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Squash(self.log, self.image, self.docker_client)

    def test_should_parse_name_name_with_proper_tag(self):
        self.assertEqual(self.squash._parse_image_name('jboss/wildfly:abc'), ('jboss/wildfly', 'abc'))
        self.assertEqual(self.squash._parse_image_name('jboss:abc'), ('jboss', 'abc'))

    def test_should_parse_name_name_without_tag(self):
        self.assertEqual(self.squash._parse_image_name('jboss/wildfly'), ('jboss/wildfly', 'latest'))
        self.assertEqual(self.squash._parse_image_name('jboss'), ('jboss', 'latest'))

class TestPrepareTemporaryDirectory(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Squash(self.log, self.image, self.docker_client)

    @mock.patch('docker_scripts.squash.tempfile')
    def test_create_tmp_directory_if_not_provided(self, mock_tempfile):
        self.squash._prepare_tmp_directory(None)
        mock_tempfile.mkdtemp.assert_called_with(prefix="docker-squash-")

    @mock.patch('docker_scripts.squash.os.path.exists', return_value=True)
    def test_should_return_none_if_directory_already_exists(self, mock_path):
        self.assertEqual(self.squash._prepare_tmp_directory('tmp'), None)
        mock_path.assert_called_with('tmp')

    @mock.patch('docker_scripts.squash.os.path.exists', return_value=False)
    @mock.patch('docker_scripts.squash.os.makedirs', return_value=False)
    def test_should_use_provided_tmp_dir(self, mock_makedirs, mock_path):
        self.assertEqual(self.squash._prepare_tmp_directory('tmp'), 'tmp')
        mock_path.assert_called_with('tmp')
        mock_makedirs.assert_called_with('tmp')

if __name__ == '__main__':
    unittest.main()

