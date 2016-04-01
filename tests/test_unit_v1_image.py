import unittest
import mock
import six
import tarfile

from docker_squash.squash import Squash
from docker_squash.image import Image
from docker_squash.v1_image import V1Image
from docker_squash.errors import SquashError


class TestSkippingFiles(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

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
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_parse_name_name_with_proper_tag(self):
        self.assertEqual(self.squash._parse_image_name(
            'jboss/wildfly:abc'), ('jboss/wildfly', 'abc'))
        self.assertEqual(
            self.squash._parse_image_name('jboss:abc'), ('jboss', 'abc'))

    def test_should_parse_name_name_without_tag(self):
        self.assertEqual(self.squash._parse_image_name(
            'jboss/wildfly'), ('jboss/wildfly', 'latest'))
        self.assertEqual(
            self.squash._parse_image_name('jboss'), ('jboss', 'latest'))


class TestPrepareTemporaryDirectory(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    @mock.patch('docker_squash.image.tempfile')
    def test_create_tmp_directory_if_not_provided(self, mock_tempfile):
        self.squash._prepare_tmp_directory(None)
        mock_tempfile.mkdtemp.assert_called_with(prefix="docker-squash-")

    @mock.patch('docker_squash.image.tempfile')
    @mock.patch('docker_squash.image.os.path.exists', return_value=True)
    def test_should_raise_if_directory_already_exists(self, mock_path, mock_tempfile):
        with self.assertRaises(SquashError) as cm:
            self.squash._prepare_tmp_directory('tmp')
        self.assertEquals(
            str(cm.exception), "The 'tmp' directory already exists, please remove it before you proceed")
        mock_path.assert_called_with('tmp')
        self.assertTrue(len(mock_tempfile.mkdtemp.mock_calls) == 0)

    @mock.patch('docker_squash.image.os.path.exists', return_value=False)
    @mock.patch('docker_squash.image.os.makedirs', return_value=False)
    def test_should_use_provided_tmp_dir(self, mock_makedirs, mock_path):
        self.assertEqual(self.squash._prepare_tmp_directory('tmp'), 'tmp')
        mock_path.assert_called_with('tmp')
        mock_makedirs.assert_called_with('tmp')


class TestPrepareLayersToSquash(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    # The order is from oldest to newest
    def test_should_generate_list_of_layers(self):
        self.assertEquals(self.squash._layers_to_squash(
            ['abc', 'def', 'ghi', 'jkl'], 'def'), (['ghi', 'jkl'], ['abc', 'def']))

    def test_should_not_fail_with_empty_list_of_layers(self):
        self.assertEquals(self.squash._layers_to_squash([], 'def'), ([], []))

    def test_should_return_all_layers_if_from_layer_is_not_found(self):
        self.assertEquals(self.squash._layers_to_squash(
            ['abc', 'def', 'ghi', 'jkl'], 'asdasdasd'), (['abc', 'def', 'ghi', 'jkl'], []))

class TestGenerateV1ImageId(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = V1Image(self.log, self.docker_client, self.image, None)

    def test_should_generate_id(self):
        image_id = self.squash._generate_image_id()
        self.assertEquals(len(image_id), 64)
        self.assertEquals(isinstance(image_id, str), True)

    @mock.patch('docker_squash.image.hashlib.sha256')
    def test_should_generate_id_that_is_not_integer_shen_shortened(self, mock_random):
        first_pass = mock.Mock()
        first_pass.hexdigest.return_value = '12683859385754f68e0652f13eb771725feff397144cd60886cb5f9800ed3e22'

        second_pass = mock.Mock()
        second_pass.hexdigest.return_value = '10aaeb89980554f68e0652f13eb771725feff397144cd60886cb5f9800ed3e22'

        mock_random.side_effect = [first_pass, second_pass]
        image_id = self.squash._generate_image_id()
        self.assertEquals(mock_random.call_count, 2)
        self.assertEquals(len(image_id), 64)


class TestGenerateRepositoriesJSON(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_generate_json(self):
        image_id = '12323dferwt4awefq23rasf'
        with mock.patch.object(six.moves.builtins, 'open', mock.mock_open()) as mock_file:
            self.squash._generate_repositories_json(
                'file', image_id, 'name', 'tag')

            self.assertIn(mock.call().write('{"name":{"tag":"12323dferwt4awefq23rasf"}}'), mock_file.mock_calls)
            self.assertIn(mock.call().write('\n'), mock_file.mock_calls)

    def test_handle_empty_image_id(self):
        with mock.patch.object(six.moves.builtins, 'open', mock.mock_open()) as mock_file:
            with self.assertRaises(SquashError) as cm:
                self.squash._generate_repositories_json(
                    'file', None, 'name', 'tag')

            self.assertEquals(
                str(cm.exception), 'Provided image id cannot be null')
            mock_file().write.assert_not_called()


class TestMarkerFiles(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def _tar_member(self, ret_val):
        member = mock.Mock()
        member.name = ret_val
        return member

    def test_should_find_all_marker_files(self):
        files = []

        for path in ['/opt/eap', '/opt/eap/one', '/opt/eap/.wh.to_skip']:
            files.append(self._tar_member(path))

        tar = mock.Mock()
        markers = self.squash._marker_files(tar, files)

        self.assertTrue(len(markers) == 1)
        self.assertTrue(list(markers)[0].name == '/opt/eap/.wh.to_skip')

    def test_should_return_empty_dict_when_no_files_are_in_the_tar(self):
        tar = mock.Mock()
        markers = self.squash._marker_files(tar, [])
        self.assertTrue(markers == {})

    def test_should_return_empty_dict_when_no_marker_files_are_found(self):
        files = []

        for path in ['/opt/eap', '/opt/eap/one']:
            files.append(self._tar_member(path))

        tar = mock.Mock()
        markers = self.squash._marker_files(tar, files)

        self.assertTrue(len(markers) == 0)
        self.assertTrue(markers == {})


class TestAddMarkers(unittest.TestCase):

    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_not_fail_with_empty_list_of_markers_to_add(self):
        self.squash._add_markers({}, None, None)

    def test_should_add_all_marker_files_to_empty_tar(self):
        tar = mock.Mock()

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value='.wh.marker_1')

        markers = {marker_1: 'file'}
        with mock.patch('docker_squash.image.Image._files_in_layers', return_value={}):
            self.squash._add_markers(markers, tar, None)

        self.assertTrue(len(tar.addfile.mock_calls) == 1)
        tar_info, marker_file = tar.addfile.call_args[0]
        self.assertIsInstance(tar_info, tarfile.TarInfo)
        self.assertTrue(marker_file == 'file')
        self.assertTrue(tar_info.isfile())

    def test_should_skip_a_marker_file_if_file_is_in_unsquashed_layers(self):
        tar = mock.Mock()

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value='.wh.marker_1')
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value='.wh.marker_2')

        markers = {marker_1: 'file1', marker_2: 'file2'}
        self.squash._add_markers(markers, tar, {'1234layerdid': ['some/file', 'marker_1']})

        self.assertEqual(len(tar.addfile.mock_calls), 1)
        tar_info, marker_file = tar.addfile.call_args[0]
        self.assertIsInstance(tar_info, tarfile.TarInfo)
        self.assertTrue(marker_file == 'file2')
        self.assertTrue(tar_info.isfile())

    def test_should_not_add_any_marker_files(self):
        tar = mock.Mock()

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value='.wh.marker_1')
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value='.wh.marker_2')

        markers = {marker_1: 'file1', marker_2: 'file2'}
        self.squash._add_markers(markers, tar, {'1234layerdid': ['some/file', 'marker_1', 'marker_2']})

        self.assertTrue(len(tar.addfile.mock_calls) == 0)

class TestGeneral(unittest.TestCase):

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

if __name__ == '__main__':
    unittest.main()
