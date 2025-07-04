import builtins
import pathlib
import unittest

import mock

from docker_squash.errors import SquashError
from docker_squash.image import Image
from docker_squash.v1_image import V1Image


class TestSkippingFiles(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_skip_exact_files(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/something", {"/opt/eap", "/opt/webserver/something"}, set()
        )
        self.assertTrue(ret)

    def test_should_not_skip_file_not_in_path_to_skip(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp", {"/opt/eap", "/opt/webserver/something"}, set()
        )
        self.assertFalse(ret)

    def test_should_not_skip_the_file_that_name_is_similar_to_skipped_path(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp1234", {"/opt/eap", "/opt/webserver/tmp"}, set()
        )
        self.assertFalse(ret)

    def test_should_skip_files_in_subdirectory(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp/abc", {"/opt/eap", "/opt/webserver/tmp"}, set()
        )
        self.assertTrue(ret)

    def test_should_skip_files_in_directory(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp/abc", {"/opt/eap"}, {"/opt/webserver/tmp"}
        )
        self.assertTrue(ret)

    def test_should_not_skip_directory(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp/abc", {"/opt/eap"}, {"/opt/webserver/tmp/abc"}
        )
        self.assertFalse(ret)


class TestParseImageName(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_parse_name_name_with_proper_tag(self):
        self.assertEqual(
            self.squash._parse_image_name("jboss/wildfly:abc"), ("jboss/wildfly", "abc")
        )
        self.assertEqual(self.squash._parse_image_name("jboss:abc"), ("jboss", "abc"))

    def test_should_parse_name_name_without_tag(self):
        self.assertEqual(
            self.squash._parse_image_name("jboss/wildfly"), ("jboss/wildfly", "latest")
        )
        self.assertEqual(self.squash._parse_image_name("jboss"), ("jboss", "latest"))


class TestPrepareTemporaryDirectory(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    @mock.patch("docker_squash.image.tempfile")
    def test_create_tmp_directory_if_not_provided(self, mock_tempfile):
        self.squash._prepare_tmp_directory(None)
        mock_tempfile.mkdtemp.assert_called_with(prefix="docker-squash-")

    @mock.patch("docker_squash.image.tempfile")
    @mock.patch("docker_squash.image.os.path.exists", return_value=True)
    def test_should_raise_if_directory_already_exists(self, mock_path, mock_tempfile):
        with self.assertRaises(SquashError) as cm:
            self.squash._prepare_tmp_directory("tmp")
        self.assertEqual(
            str(cm.exception),
            "The 'tmp' directory already exists, please remove it before you proceed",
        )
        mock_path.assert_called_with("tmp")
        self.assertTrue(len(mock_tempfile.mkdtemp.mock_calls) == 0)

    @mock.patch("docker_squash.image.os.path.exists", return_value=False)
    @mock.patch("docker_squash.image.os.makedirs", return_value=False)
    def test_should_use_provided_tmp_dir(self, mock_makedirs, mock_path):
        self.assertEqual(self.squash._prepare_tmp_directory("tmp"), "tmp")
        mock_path.assert_called_with("tmp")
        mock_makedirs.assert_called_with("tmp")


class TestPrepareLayersToSquash(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    # The order is from oldest to newest
    def test_should_generate_list_of_layers(self):
        self.assertEqual(
            self.squash._layers_to_squash(["abc", "def", "ghi", "jkl"], "def"),
            (["ghi", "jkl"], ["abc", "def"]),
        )

    def test_should_not_fail_with_empty_list_of_layers(self):
        self.assertEqual(self.squash._layers_to_squash([], "def"), ([], []))

    def test_should_return_all_layers_if_from_layer_is_not_found(self):
        self.assertEqual(
            self.squash._layers_to_squash(["abc", "def", "ghi", "jkl"], "asdasdasd"),
            (["abc", "def", "ghi", "jkl"], []),
        )


class TestGenerateV1ImageId(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = V1Image(self.log, self.docker_client, self.image, None)

    def test_should_generate_id(self):
        image_id = self.squash._generate_image_id()
        self.assertEqual(len(image_id), 64)
        self.assertEqual(isinstance(image_id, str), True)

    @mock.patch("docker_squash.image.hashlib.sha256")
    def test_should_generate_id_that_is_not_integer_shen_shortened(self, mock_random):
        first_pass = mock.Mock()
        first_pass.hexdigest.return_value = (
            "12683859385754f68e0652f13eb771725feff397144cd60886cb5f9800ed3e22"
        )

        second_pass = mock.Mock()
        second_pass.hexdigest.return_value = (
            "10aaeb89980554f68e0652f13eb771725feff397144cd60886cb5f9800ed3e22"
        )

        mock_random.side_effect = [first_pass, second_pass]
        image_id = self.squash._generate_image_id()
        self.assertEqual(mock_random.call_count, 2)
        self.assertEqual(len(image_id), 64)


class TestGenerateRepositoriesJSON(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_generate_json(self):
        image_id = "12323dferwt4awefq23rasf"
        with mock.patch.object(builtins, "open", mock.mock_open()) as mock_file:
            self.squash._generate_repositories_json("file", image_id, "name", "tag")

            self.assertIn(
                mock.call().write('{"name":{"tag":"12323dferwt4awefq23rasf"}}'),
                mock_file.mock_calls,
            )
            self.assertIn(mock.call().write("\n"), mock_file.mock_calls)

    def test_handle_empty_image_id(self):
        with mock.patch.object(builtins, "open", mock.mock_open()) as mock_file:
            with self.assertRaises(SquashError) as cm:
                self.squash._generate_repositories_json("file", None, "name", "tag")

            self.assertEqual(str(cm.exception), "Provided image id cannot be null")
            mock_file().write.assert_not_called()

    def test_should_not_generate_repositories_if_name_and_tag_is_missing(self):
        self.squash._generate_repositories_json("file", "abcd", None, None)
        self.log.debug.assert_called_with(
            "No name and tag provided for the image, skipping generating repositories file"
        )


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

        for path in ["/opt/eap", "/opt/eap/one", "/opt/eap/.wh.to_skip"]:
            files.append(self._tar_member(path))

        markers = self.squash._marker_files(files)

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].name, "/opt/eap/.wh.to_skip")

    def test_should_return_empty_dict_when_no_files_are_in_the_tar(self):
        markers = self.squash._marker_files([])
        self.assertEqual(len(markers), 0)

    def test_should_return_empty_dict_when_no_marker_files_are_found(self):
        files = []

        for path in ["/opt/eap", "/opt/eap/one"]:
            files.append(self._tar_member(path))

        markers = self.squash._marker_files(files)

        self.assertEqual(len(markers), 0)


class TestPathHierarchy(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_prepare_path_hierarchy(self):
        actual = self.squash._path_hierarchy(
            pathlib.PurePosixPath("/opt/testing/some/dir/structure/file")
        )
        expected = [
            "/",
            "/opt",
            "/opt/testing",
            "/opt/testing/some",
            "/opt/testing/some/dir",
            "/opt/testing/some/dir/structure",
        ]
        self.assertEqual(expected, list(actual))

    def test_should_handle_root(self):
        actual = self.squash._path_hierarchy(pathlib.PurePosixPath("/"))
        self.assertEqual(["/"], list(actual))

    def test_should_handle_empty(self):
        with self.assertRaises(SquashError) as cm:
            self.squash._path_hierarchy("")
        self.assertEqual(
            str(cm.exception), "No path provided to create the hierarchy for"
        )

    def test_should_handle_windows_path(self):
        expected = [
            "C:\\",
            "C:\\Windows",
            "C:\\Windows\\System32",
            "C:\\Windows\\System32\\drivers",
            "C:\\Windows\\System32\\drivers\\etc",
        ]
        actual = self.squash._path_hierarchy(
            pathlib.PureWindowsPath("C:\\Windows\\System32\\drivers\\etc\\hosts")
        )

        self.assertEqual(expected, list(actual))


if __name__ == "__main__":
    unittest.main()
