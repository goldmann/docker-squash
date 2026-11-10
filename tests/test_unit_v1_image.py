import builtins
import io
import os
import pathlib
import shutil
import tarfile
import tempfile
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
            "/opt/webserver/something", [["/opt/eap", "/opt/webserver/something"]]
        )
        self.assertEqual(ret, 1)

    def test_should_not_skip_file_not_in_path_to_skip(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp", [["/opt/eap", "/opt/webserver/something"]]
        )
        self.assertEqual(ret, 0)

    def test_should_not_skip_the_file_that_name_is_similar_to_skipped_path(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp1234", [["/opt/eap", "/opt/webserver/tmp"]]
        )
        self.assertEqual(ret, 0)

    def test_should_skip_files_in_subdirectory(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp/abc", [["/opt/eap", "/opt/webserver/tmp"]]
        )
        self.assertEqual(ret, 1)

    def test_should_skip_files_in_other_layer(self):
        ret = self.squash._file_should_be_skipped(
            "/opt/webserver/tmp/abc", [["a"], ["b"], ["/opt/eap", "/opt/webserver/tmp"]]
        )
        self.assertEqual(ret, 3)


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

        tar = mock.Mock()
        markers = self.squash._marker_files(tar, files)

        self.assertTrue(len(markers) == 1)
        self.assertTrue(list(markers)[0].name == "/opt/eap/.wh.to_skip")

    def test_should_return_empty_dict_when_no_files_are_in_the_tar(self):
        tar = mock.Mock()
        markers = self.squash._marker_files(tar, [])
        self.assertTrue(markers == {})

    def test_should_return_empty_dict_when_no_marker_files_are_found(self):
        files = []

        for path in ["/opt/eap", "/opt/eap/one"]:
            files.append(self._tar_member(path))

        tar = mock.Mock()
        markers = self.squash._marker_files(tar, files)

        self.assertTrue(len(markers) == 0)
        self.assertTrue(markers == {})


class TestFilesInLayers(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.squash = Image(self.log, self.docker_client, "whatever", None)
        self.squash.oci_format = True
        self.tmp = tempfile.mkdtemp()
        self.squash.old_image_dir = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_layer(self, name, members):
        with tarfile.open(os.path.join(self.tmp, name), "w") as tar:
            for member in members:
                tar.addfile(tarfile.TarInfo(name=member))

    def test_should_return_a_set_of_normalized_files_per_layer(self):
        # Some tar archives prefix the names with './'
        self._make_layer("layer1", ["./abc", "def", "dir/file"])
        self._make_layer("layer2", ["./xyz"])

        files = self.squash._files_in_layers(["layer1", "layer2"])

        self.assertEqual(files["layer1"], {"/abc", "/def", "/dir/file"})
        self.assertEqual(files["layer2"], {"/xyz"})
        self.assertIsInstance(files["layer1"], set)

    def test_should_return_empty_dict_for_no_layers(self):
        self.assertEqual(self.squash._files_in_layers([]), {})


class TestAddMarkers(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_not_fail_with_empty_list_of_markers_to_add(self):
        self.squash._add_markers({}, None, None, [])

    def test_should_add_all_marker_files_to_empty_tar(self):
        tar = mock.Mock()
        tar.getnames.return_value = []

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value=".wh.marker_1")

        markers = {marker_1: "file"}
        self.squash._add_markers(markers, tar, {}, [])

        self.assertTrue(len(tar.addfile.mock_calls) == 1)
        tar_info, marker_file = tar.addfile.call_args[0]
        self.assertIsInstance(tar_info, tarfile.TarInfo)
        self.assertTrue(marker_file == "file")
        self.assertTrue(tar_info.isfile())

    def test_should_add_all_marker_files_to_empty_tar_besides_what_should_be_skipped(
        self,
    ):
        tar = mock.Mock()
        tar.getnames.return_value = []

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value=".wh.marker_1")
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value=".wh.marker_2")

        markers = {marker_1: "file1", marker_2: "file2"}
        self.squash._add_markers(
            markers, tar, {"1234layerdid": ["/marker_1", "/marker_2"]}, [["/marker_1"]]
        )

        self.assertEqual(len(tar.addfile.mock_calls), 1)
        tar_info, marker_file = tar.addfile.call_args[0]
        self.assertIsInstance(tar_info, tarfile.TarInfo)
        self.assertTrue(marker_file == "file2")
        self.assertTrue(tar_info.isfile())

    def test_should_skip_a_marker_file_if_file_is_in_unsquashed_layers(self):
        tar = mock.Mock()
        # List of files in the squashed tar
        tar.getnames.return_value = ["marker_1"]

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value=".wh.marker_1")
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value=".wh.marker_2")
        # List of marker files to add back
        markers = {marker_1: "marker_1", marker_2: "marker_2"}
        # List of files in all layers to be moved
        files_in_moved_layers = {"1234layerdid": ["/some/file", "/marker_2"]}
        self.squash._add_markers(markers, tar, files_in_moved_layers, [])

        self.assertEqual(len(tar.addfile.mock_calls), 1)
        tar_info, marker_file = tar.addfile.call_args[0]
        self.assertIsInstance(tar_info, tarfile.TarInfo)
        self.assertTrue(marker_file == "marker_2")
        self.assertTrue(tar_info.isfile())

    def test_should_not_add_any_marker_files(self):
        tar = mock.Mock()
        tar.getnames.return_value = ["marker_1", "marker_2"]

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value=".wh.marker_1")
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value=".wh.marker_2")

        markers = {marker_1: "file1", marker_2: "file2"}
        self.squash._add_markers(
            markers, tar, {"1234layerdid": ["some/file", "marker_1", "marker_2"]}, []
        )

        self.assertTrue(len(tar.addfile.mock_calls) == 0)

    # https://github.com/goldmann/docker-squash/issues/108
    def test_should_add_marker_file_when_tar_has_prefixed_entries(self):
        tar = mock.Mock()
        # Files already in tar
        tar.getnames.return_value = ["./abc", "./def"]

        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value=".wh.some/file")
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value=".wh.file2")

        markers = {marker_1: "filecontent1", marker_2: "filecontent2"}

        # List of layers to move (and files in these layers), already normalized
        self.squash._add_markers(
            markers, tar, {"1234layerdid": ["/some/file", "/other/file", "/stuff"]}, []
        )

        self.assertEqual(len(tar.addfile.mock_calls), 1)
        tar_info, marker_file = tar.addfile.call_args[0]
        self.assertIsInstance(tar_info, tarfile.TarInfo)
        # We need to add the marker file because we need to
        # override the already existing file
        self.assertEqual(marker_file, "filecontent1")
        self.assertTrue(tar_info.isfile())


class TestReduceMarkers(unittest.TestCase):
    def setUp(self):
        self.docker_client = mock.Mock()
        self.log = mock.Mock()
        self.image = "whatever"
        self.squash = Image(self.log, self.docker_client, self.image, None)

    def test_should_not_reduce_any_marker_files(self):
        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value=".wh.some/file")
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(return_value=".wh.file2")

        markers = {marker_1: "filecontent1", marker_2: "filecontent2"}

        self.squash._reduce(markers)

        assert len(markers) == 2
        assert markers[marker_1] == "filecontent1"
        assert markers[marker_2] == "filecontent2"

    def test_should_reduce_marker_files(self):
        marker_1 = mock.Mock()
        type(marker_1).name = mock.PropertyMock(return_value="opt/.wh.testing")
        marker_2 = mock.Mock()
        type(marker_2).name = mock.PropertyMock(
            return_value="opt/testing/something/.wh.file"
        )
        marker_3 = mock.Mock()
        type(marker_3).name = mock.PropertyMock(
            return_value="opt/testing/something/.wh.other_file"
        )

        markers = {
            marker_1: "filecontent1",
            marker_2: "filecontent2",
            marker_3: "filecontent3",
        }

        self.squash._reduce(markers)

        assert len(markers) == 1
        assert markers[marker_1] == "filecontent1"


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


class TestSquashLayersReplacedDirectory(unittest.TestCase):
    """
    https://github.com/goldmann/docker-squash/issues/253
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)
        self.squash = Image(mock.Mock(), mock.Mock(), "whatever", None)
        self.squash.old_image_dir = os.path.join(self.tmp_dir, "old")
        self.squash.squashed_tar = os.path.join(self.tmp_dir, "squashed.tar")

    def _write_layer(self, layer_id, entries):
        layer_dir = os.path.join(self.squash.old_image_dir, layer_id)
        os.makedirs(layer_dir)
        with tarfile.open(os.path.join(layer_dir, "layer.tar"), "w") as tar:
            for name, kind in entries:
                info = tarfile.TarInfo(name)
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    tar.addfile(info)
                else:
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(b""))

    def _squash_layers(self, layers, layers_to_move=()):
        self.squash._squash_layers(list(layers), list(layers_to_move))
        with tarfile.open(self.squash.squashed_tar) as tar:
            return {m.name: m for m in tar.getmembers()}

    def test_should_drop_files_below_a_directory_replaced_by_a_file(self):
        self._write_layer(
            "1", [("tmp", "dir"), ("tmp/dir", "dir"), ("tmp/dir/f", "file")]
        )
        self._write_layer("2", [("tmp", "dir"), ("tmp/dir", "file")])

        members = self._squash_layers(["1", "2"])

        self.assertTrue(members["tmp/dir"].isfile())
        self.assertNotIn("tmp/dir/f", members)

    def test_should_drop_markers_below_a_directory_replaced_by_a_file(self):
        self._write_layer(
            "1", [("tmp", "dir"), ("tmp/dir", "dir"), ("tmp/dir/f", "file")]
        )
        self._write_layer(
            "2", [("tmp", "dir"), ("tmp/dir", "dir"), ("tmp/dir/.wh.f", "file")]
        )
        self._write_layer("3", [("tmp", "dir"), ("tmp/dir", "file")])

        members = self._squash_layers(["2", "3"], ["1"])

        self.assertTrue(members["tmp/dir"].isfile())
        self.assertNotIn("tmp/dir/.wh.f", members)

    def test_should_keep_files_below_a_directory_that_is_still_a_directory(self):
        self._write_layer(
            "1", [("tmp", "dir"), ("tmp/dir", "dir"), ("tmp/dir/f", "file")]
        )
        self._write_layer(
            "2", [("tmp", "dir"), ("tmp/dir", "dir"), ("tmp/dir/g", "file")]
        )

        members = self._squash_layers(["1", "2"])

        self.assertTrue(members["tmp/dir"].isdir())
        self.assertIn("tmp/dir/f", members)
        self.assertIn("tmp/dir/g", members)
