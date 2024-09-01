import codecs
import json
import logging
import os
import re
import shutil
import tarfile
import unittest
import uuid
from io import BytesIO

import docker.errors
import mock
import pytest
from packaging import version as packaging_version
from parameterized import parameterized

from docker_squash.errors import SquashError, SquashUnnecessaryError
from docker_squash.lib import common
from docker_squash.squash import Squash


class ImageHelper(object):
    @staticmethod
    def top_layer_path(tar):
        # tar_object.seek(0)
        reader = codecs.getreader("utf-8")

        if "repositories" in tar.getnames():
            repositories_member = tar.getmember("repositories")
            repositories = json.load(reader(tar.extractfile(repositories_member)))
            return repositories.popitem()[1].popitem()[1]

        if "manifest.json" in tar.getnames():
            manifest_member = tar.getmember("manifest.json")
            manifest = json.load(reader(tar.extractfile(manifest_member)))
            return manifest[0]["Layers"][-1].split("/")[0]


class IntegSquash(unittest.TestCase):
    BUSYBOX_IMAGE = "busybox:1.36.1"

    log = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s %(filename)s:%(lineno)-10s %(levelname)-5s %(message)s"
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    docker = common.docker_client(log)

    @classmethod
    def build_image(cls, dockerfile):
        IntegSquash.image = IntegSquash.Image(dockerfile)
        IntegSquash.image.__enter__()

    @classmethod
    def cleanup_image(cls):
        IntegSquash.image.__exit__(None, None, None)

    class Image(object):
        def __init__(self, dockerfile, tag="latest"):
            self.dockerfile = dockerfile
            self.docker = TestIntegSquash.docker
            self.name = "integ-%s" % uuid.uuid1()
            self.tag = f"{self.name}:{tag}"

        def __enter__(self):
            f = BytesIO(self.dockerfile.encode("utf-8"))
            for line in self.docker.build(fileobj=f, tag=self.tag, rm=True):
                try:
                    print(json.loads(line.decode("utf-8"))["stream"].strip())
                except KeyError:
                    print(line)

            self.history = self.docker.history(self.tag)
            self.layers = [o["Id"] for o in self.history]
            self.metadata = self.docker.inspect_image(self.tag)
            self.tar = self._save_image()

            with tarfile.open(fileobj=self.tar, mode="r") as tar:
                self.tarnames = tar.getnames()

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not os.getenv("CI"):
                try:
                    self.docker.remove_image(image=self.tag, force=True)
                except docker.errors.DockerException:
                    # Can throw if cleanup results in the same image being deleted.
                    pass

        # Duplicated, I know...
        def _save_image(self):
            image = self.docker.get_image(self.tag)

            buf = BytesIO()
            for chunk in image:
                buf.write(chunk)
            buf.seek(0)  # Rewind

            return buf

        def assertFileExistsInLayer(self, name, layer=-1):
            self.tar.seek(0)  # Rewind
            reader = codecs.getreader("utf-8")

            with tarfile.open(fileobj=self.tar, mode="r") as tar:
                manifest_member = tar.getmember("manifest.json")
                manifest_file = tar.extractfile(manifest_member)
                manifest = json.load(reader(manifest_file))

                layer_member = tar.getmember(manifest[0]["Layers"][layer])
                layer_file = tar.extractfile(layer_member)

                with tarfile.open(fileobj=layer_file, mode="r") as layer_tar:
                    assert (
                        name in layer_tar.getnames()
                    ), "File '%s' was not found in layer files: %s" % (
                        name,
                        layer_tar.getnames(),
                    )

    class SquashedImage(object):
        def __init__(
            self,
            image,
            number_of_layers=None,
            output_path=None,
            load_image=True,
            numeric=False,
            tmp_dir=None,
            log=None,
            tag=True,
            cleanup=False,
        ):
            self.image = image
            self.number_of_layers = number_of_layers
            self.docker = TestIntegSquash.docker
            self.log = log or TestIntegSquash.log
            if tag:
                self.tag = "%s:squashed" % self.image.name
            else:
                self.tag = None
            self.output_path = output_path
            self.load_image = load_image
            self.numeric = numeric
            self.tmp_dir = tmp_dir
            self.cleanup = cleanup

        def __enter__(self):
            from_layer = self.number_of_layers

            if self.number_of_layers and not self.numeric:
                from_layer = self.docker.history(self.image.tag)[self.number_of_layers][
                    "Id"
                ]

            squash = Squash(
                self.log,
                self.image.tag,
                self.docker,
                tag=self.tag,
                from_layer=from_layer,
                output_path=self.output_path,
                load_image=self.load_image,
                tmp_dir=self.tmp_dir,
                cleanup=self.cleanup,
            )

            self.image_id = squash.run()

            if not self.output_path:
                self.history = self.docker.history(self.image_id)

                if self.tag:
                    self.tar = self._save_image()

                    with tarfile.open(fileobj=self.tar, mode="r") as tar:
                        self.tarnames = tar.getnames()

                    self.squashed_layer = self._squashed_layer()
                    self.layers = [o["Id"] for o in self.docker.history(self.image_id)]
                    self.metadata = self.docker.inspect_image(self.image_id)

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not (os.getenv("CI") or self.output_path):
                self.docker.remove_image(image=self.image_id, force=True)

        def _save_image(self):
            image = self.docker.get_image(self.tag)

            buf = BytesIO()
            for chunk in image:
                buf.write(chunk)
            buf.seek(0)  # Rewind

            return buf

        def _extract_file(self, name, tar_object):
            tar_object.seek(0)
            with tarfile.open(fileobj=tar_object, mode="r") as tar:
                member = tar.getmember(name)
                return tar.extractfile(member)

        def _squashed_layer(self):
            self.tar.seek(0)
            with tarfile.open(fileobj=self.tar, mode="r") as tar:
                self.squashed_layer_path = ImageHelper.top_layer_path(tar)
            if packaging_version.parse(
                self.docker.version().get("Version")
            ) >= packaging_version.parse("25.0"):
                return self._extract_file(
                    "blobs/sha256/%s" % self.squashed_layer_path, self.tar
                )
            else:
                return self._extract_file(
                    "%s/layer.tar" % self.squashed_layer_path, self.tar
                )

        def assertFileExists(self, name):
            self.squashed_layer.seek(0)  # Rewind
            with tarfile.open(fileobj=self.squashed_layer, mode="r") as tar:
                assert (
                    name in tar.getnames()
                ), "File '%s' was not found in the squashed files: %s" % (
                    name,
                    tar.getnames(),
                )

        def assertFileDoesNotExist(self, name):
            self.squashed_layer.seek(0)  # Rewind
            with tarfile.open(fileobj=self.squashed_layer, mode="r") as tar:
                assert (
                    name not in tar.getnames()
                ), "File '%s' was found in the squashed layer files: %s" % (
                    name,
                    tar.getnames(),
                )

        def assertFileIsNotHardLink(self, name):
            self.squashed_layer.seek(0)  # Rewind
            with tarfile.open(fileobj=self.squashed_layer, mode="r") as tar:
                member = tar.getmember(name)
                assert member.islnk() is False, (
                    "File '%s' should not be a hard link, but it is" % name
                )

        def assert_target_tag_exists(self):
            if self.tag:
                # Raise exception if it doesn't exist
                self.docker.inspect_image(self.tag)

    class Container(object):
        def __init__(self, image):
            self.image = image
            self.docker = TestIntegSquash.docker
            self.log = TestIntegSquash.log

        def __enter__(self):
            self.container = self.docker.create_container(image=self.image.tag)
            data = self.docker.export(self.container)

            self.content = BytesIO()
            for chunk in data:
                self.content.write(chunk)
            self.content.seek(0)  # Rewind

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not os.getenv("CI"):
                self.docker.remove_container(self.container, force=True)

        def assertFileExists(self, name):
            self.content.seek(0)  # Rewind
            with tarfile.open(fileobj=self.content, mode="r") as tar:
                assert (
                    name in tar.getnames()
                ), "File %s was not found in the container files: %s" % (
                    name,
                    tar.getnames(),
                )

        def assertFileDoesNotExist(self, name):
            self.content.seek(0)  # Rewind
            with tarfile.open(fileobj=self.content, mode="r") as tar:
                assert (
                    name not in tar.getnames()
                ), "File %s was found in the container files: %s" % (
                    name,
                    tar.getnames(),
                )


class TestIntegSquash(IntegSquash):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, caplog):
        self.caplog = caplog

    def test_same_source_and_target_image_tag_should_not_be_deleted(self):
        self.caplog.set_level(logging.DEBUG, logger="cekit")
        dockerfile = (
            """
            FROM %s
            RUN touch /somefile_layer1
            RUN touch /somefile_layer2
            """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile, tag="squashed") as image:
            with self.SquashedImage(image, 2, cleanup=True) as squashed_image:
                squashed_image.assert_target_tag_exists()
        assert "Tag is the same as image; preventing cleanup" in self.caplog.text

    def test_all_files_should_be_in_squashed_layer(self):
        """
        We squash all layers in RUN, all files should be in the resulting squashed layer.
        """
        dockerfile = (
            """
        FROM %s
        RUN touch /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3) as squashed_image:
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer1")
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer2")
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer3")
                squashed_image.assertFileExists("somefile_layer1")
                squashed_image.assertFileExists("somefile_layer2")
                squashed_image.assertFileExists("somefile_layer3")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("somefile_layer1")
                    container.assertFileExists("somefile_layer2")
                    container.assertFileExists("somefile_layer3")

                    # We should have two layers less in the image
                    self.assertTrue(len(squashed_image.layers) == len(image.layers) - 2)

    def test_only_files_from_squashed_image_should_be_in_squashed_layer(self):
        """
        We squash all layers in RUN, all files should be in the resulting squashed layer.
        """
        dockerfile = (
            """
        FROM %s
        RUN touch /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer2")
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer3")
                # This file should not be in the squashed layer
                squashed_image.assertFileDoesNotExist("somefile_layer1")
                # Nor a marker files for it
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer1")
                squashed_image.assertFileExists("somefile_layer2")
                squashed_image.assertFileExists("somefile_layer3")

                with self.Container(squashed_image) as container:
                    # This file should be in the container
                    container.assertFileExists("somefile_layer1")
                    container.assertFileExists("somefile_layer2")
                    container.assertFileExists("somefile_layer3")

                    # We should have two layers less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    def test_there_should_be_a_marker_file_in_the_squashed_layer(self):
        """
        Here we're testing that the squashed layer should contain a '.wh.somefile_layer1'
        file, because the file was not found in the squashed tar and it is present in
        the layers we do not squash.
        """

        dockerfile = (
            """
        FROM %s
        RUN touch /somefile_layer1
        RUN rm /somefile_layer1
        RUN touch /somefile_layer3
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist("somefile_layer1")
                squashed_image.assertFileExists("somefile_layer3")
                squashed_image.assertFileExists(".wh.somefile_layer1")
                squashed_image.assertFileIsNotHardLink(".wh.somefile_layer1")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("somefile_layer3")
                    container.assertFileDoesNotExist("somefile_layer1")

                    # We should have one layer less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    def test_there_should_be_a_marker_file_in_the_squashed_layer_even_more_complex(
        self,
    ):
        dockerfile = (
            """
        FROM %s
        RUN touch /somefile_layer1
        RUN rm /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        RUN rm /somefile_layer2
        RUN touch /somefile_layer4
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist("somefile_layer1")
                squashed_image.assertFileDoesNotExist("somefile_layer2")
                squashed_image.assertFileDoesNotExist("somefile_layer3")
                squashed_image.assertFileExists("somefile_layer4")

                squashed_image.assertFileDoesNotExist(".wh.somefile_layer1")
                squashed_image.assertFileExists(".wh.somefile_layer2")
                squashed_image.assertFileIsNotHardLink(".wh.somefile_layer2")
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer3")
                squashed_image.assertFileDoesNotExist(".wh.somefile_layer4")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("somefile_layer3")
                    container.assertFileExists("somefile_layer4")
                    container.assertFileDoesNotExist("somefile_layer1")
                    container.assertFileDoesNotExist("somefile_layer2")

                    # We should have one layer less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    def test_should_handle_removal_of_directories(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir -p /some/dir/tree
        RUN touch /some/dir/tree/file1
        RUN touch /some/dir/tree/file2
        RUN touch /some/dir/file1
        RUN touch /some/dir/file2
        RUN rm -rf /some/dir/tree
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist("some/dir/tree/file1")
                squashed_image.assertFileDoesNotExist("some/dir/tree/file2")
                squashed_image.assertFileDoesNotExist("some/dir/file1")
                squashed_image.assertFileExists("some/dir/file2")

                squashed_image.assertFileExists("some/dir/.wh.tree")
                squashed_image.assertFileIsNotHardLink("some/dir/.wh.tree")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("some/dir/file1")
                    container.assertFileExists("some/dir/file2")
                    container.assertFileDoesNotExist("some/dir/tree")
                    container.assertFileDoesNotExist("some/dir/tree/file1")
                    container.assertFileDoesNotExist("some/dir/tree/file2")

                    # We should have one layer less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    def test_should_skip_files_when_these_are_modified_and_removed_in_squashed_layer(
        self,
    ):
        dockerfile = (
            """
        FROM %s
        RUN touch /file
        RUN chmod -R 777 /file
        RUN rm -rf /file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist("file")
                squashed_image.assertFileExists(".wh.file")
                squashed_image.assertFileIsNotHardLink(".wh.file")

                with self.Container(squashed_image) as container:
                    container.assertFileDoesNotExist("file")

                    # We should have one layer less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    def test_should_skip_files_when_these_are_removed_and_modified_in_squashed_layer(
        self,
    ):
        dockerfile = (
            """
        FROM %s
        RUN touch /file
        RUN chmod -R 777 /file
        RUN rm -rf /file
        RUN touch /file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3) as squashed_image:
                squashed_image.assertFileExists("file")
                squashed_image.assertFileDoesNotExist(".wh.file")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("file")

                    # We should have two layers less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 2)

    def test_should_handle_multiple_changes_to_files_in_squashed_layers(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir -p /some/dir/tree
        RUN touch /some/dir/tree/file1
        RUN touch /some/dir/tree/file2
        RUN touch /some/dir/file1
        RUN touch /some/dir/file2
        RUN chmod -R 777 /some
        RUN rm -rf /some/dir/tree
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                squashed_image.assertFileDoesNotExist("some/dir/tree/file1")
                squashed_image.assertFileDoesNotExist("some/dir/tree/file2")
                squashed_image.assertFileExists("some/dir/file1")
                squashed_image.assertFileExists("some/dir/file2")

                squashed_image.assertFileExists("some/dir/.wh.tree")
                squashed_image.assertFileIsNotHardLink("some/dir/.wh.tree")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("some/dir/file1")
                    container.assertFileExists("some/dir/file2")
                    container.assertFileDoesNotExist("some/dir/tree")
                    container.assertFileDoesNotExist("some/dir/tree/file1")
                    container.assertFileDoesNotExist("some/dir/tree/file2")

                    # We should have one layer less in the image
                    self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    # https://github.com/goldmann/docker-squash/issues/97
    def test_should_leave_whiteout_entries_as_is(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir -p /opt/test.one
        RUN mkdir -p /opt/test.two
        RUN mkdir -p /opt/foo
        RUN touch /opt/test.one/file
        RUN touch /opt/test.two/file
        RUN touch /opt/foo/file
        RUN rm -rvf /opt/test*/*
        RUN rm -rvf /opt/foo/*
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                squashed_image.assertFileDoesNotExist("opt/test.one/file")
                squashed_image.assertFileDoesNotExist("opt/test.two/file")
                squashed_image.assertFileDoesNotExist("opt/foo/file")
                squashed_image.assertFileExists("opt/test.one")
                squashed_image.assertFileExists("opt/test.two")
                squashed_image.assertFileExists("opt/foo")
                squashed_image.assertFileExists("opt/test.one/.wh.file")
                squashed_image.assertFileExists("opt/test.two/.wh.file")
                squashed_image.assertFileExists("opt/foo/.wh.file")

                with self.Container(squashed_image) as container:
                    container.assertFileDoesNotExist("opt/test.one/file")
                    container.assertFileDoesNotExist("opt/test.two/file")
                    container.assertFileDoesNotExist("opt/foo/file")
                    container.assertFileExists("opt/foo")
                    container.assertFileExists("opt/test.one")
                    container.assertFileExists("opt/test.two")

    # https://github.com/goldmann/docker-scripts/issues/28
    def test_docker_version_in_metadata_should_be_set_after_squashing(self):
        dockerfile = (
            """
        FROM %s
        RUN touch file
        RUN touch another_file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)
                self.assertEqual(
                    image.metadata["DockerVersion"],
                    squashed_image.metadata["DockerVersion"],
                )

    # https://github.com/goldmann/docker-scripts/issues/30
    # https://github.com/goldmann/docker-scripts/pull/31
    def test_files_in_squashed_tar_not_prefixed_wth_dot(self):
        dockerfile = (
            """
        FROM %s
        RUN touch file
        RUN touch another_file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, output_path="image.tar"):
                with tarfile.open("image.tar", mode="r") as tar:
                    all_files = tar.getnames()
                    for name in all_files:
                        self.assertFalse(name.startswith("."))

    # https://github.com/goldmann/docker-scripts/issues/32
    def test_version_file_exists_in_squashed_layer(self):
        dockerfile = (
            """
        FROM %s
        RUN touch file
        RUN touch another_file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, output_path="image.tar"):
                with tarfile.open("image.tar", mode="r") as tar:
                    squashed_layer_path = ImageHelper.top_layer_path(tar)

                    all_files = tar.getnames()

                    self.assertIn("%s/json" % squashed_layer_path, all_files)
                    self.assertIn("%s/layer.tar" % squashed_layer_path, all_files)
                    self.assertIn("%s/VERSION" % squashed_layer_path, all_files)

    # https://github.com/goldmann/docker-scripts/issues/33
    def test_docker_size_in_metadata_should_be_upper_case(self):
        dockerfile = (
            """
        FROM %s
        RUN touch file
        RUN touch another_file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)
                self.assertIsInstance(image.metadata["Size"], int)
                with self.assertRaisesRegex(KeyError, "'size'"):
                    self.assertEqual(image.metadata["size"], None)

    def test_handle_correctly_squashing_layers_without_data(self):
        dockerfile = (
            """
        FROM %s
        ENV a=1
        ENV b=2
        ENV c=3
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)
                image_data_layers = [s for s in image.tarnames if "layer.tar" in s]
                squashed_image_data_layers = [
                    s for s in squashed_image.tarnames if "layer.tar" in s
                ]

                if "manifest.json" in image.tarnames:
                    # For v2
                    # For V2 only layers with data contain layer.tar archives
                    # In our test case we did not add any data, so the count should
                    # be the same
                    self.assertEqual(
                        len(image_data_layers), len(squashed_image_data_layers)
                    )
                else:
                    # For v1
                    # V1 image contains as many layer.tar archives as the image has layers
                    # We squashed 2 layers, so squashed image contains one layer less
                    self.assertEqual(
                        len(image_data_layers), len(squashed_image_data_layers) + 1
                    )

    # This is an edge case where we try to squash last 2 layers
    # but these layers do not create any content on filesystem
    # https://github.com/goldmann/docker-scripts/issues/54
    def test_should_squash_exactly_2_layers_without_data(self):
        dockerfile = (
            """
        FROM %s
        CMD /bin/env
        LABEL foo bar
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 1)

    def test_should_squash_exactly_3_layers_with_data(self):
        dockerfile = (
            """
        FROM %s
        RUN touch /abc
        CMD /bin/env
        LABEL foo bar
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 2)

    def test_should_not_squash_if_only_one_layer_is_to_squash(self):
        dockerfile = (
            """
        FROM %s
        CMD /bin/env
        LABEL foo bar
        RUN touch /abc
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.assertRaises(SquashUnnecessaryError) as cm:
                with self.SquashedImage(image, 1):
                    pass

        self.assertEqual(
            str(cm.exception), "Single layer marked to squash, no squashing is required"
        )

    # https://github.com/goldmann/docker-scripts/issues/52
    # Test may be misleading, but squashing all layers makes sure we hit
    # at least one <missing> layer
    def test_should_squash_every_layer(self):
        dockerfile = (
            """
        FROM %s
        RUN touch /tmp/test1
        RUN touch /tmp/test2
        CMD /bin/env
        LABEL foo bar
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image) as squashed_image:
                self.assertEqual(len(squashed_image.layers), 1)

    # https://github.com/goldmann/docker-scripts/issues/44
    def test_remove_tmp_dir_after_failure(self):
        self.caplog.set_level(logging.DEBUG, logger="cekit")
        dockerfile = """
        FROM busybox:1.36.1
        LABEL foo bar
        """

        with self.Image(dockerfile) as image:
            with self.assertRaisesRegex(
                SquashError,
                r"Cannot squash 20 layers, the .* image contains only \d " r"layers",
            ):
                with self.SquashedImage(image, 20, numeric=True):
                    pass
        tmp_location = re.search(
            ".*Using (.*)as the temporary directory.*", self.caplog.text
        )

        assert tmp_location
        assert "Cleaning up %s temporary directory", (
            tmp_location.group(1) in self.caplog.text
        )

        self.assertFalse(os.path.exists(tmp_location.group(1)))

    def test_should_not_remove_tmp_dir_after_failure_if_development_mode_is_on(self):
        dockerfile = """
        FROM busybox:1.36.1
        LABEL foo bar
        """

        tmp_dir = "/tmp/docker-squash-integ-tmp-dir"
        log = mock.Mock()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertFalse(os.path.exists(tmp_dir))

        with self.Image(dockerfile) as image:
            with self.assertRaisesRegex(
                SquashError,
                r"Cannot squash 20 layers, the .* image contains only \d " r"layers",
            ):
                with self.SquashedImage(
                    image, 20, numeric=True, tmp_dir=tmp_dir, log=log
                ):
                    pass

        log.debug.assert_any_call(
            "Using /tmp/docker-squash-integ-tmp-dir as the temporary directory"
        )

        self.assertTrue(os.path.exists(tmp_dir))

    # https://github.com/goldmann/docker-squash/issues/80
    def test_should_not_fail_with_hard_links(self):
        dockerfile = (
            """
        FROM %s
        RUN touch /file && ln file link
        RUN rm file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, None):
                pass

    # https://github.com/goldmann/docker-squash/issues/99
    # TODO: try not to use centos:6.6 image - this slows down testsuite
    def test_should_not_fail_with_hard_links_to_files_gh_99(self):
        dockerfile = """
        FROM centos:7
        RUN yum clean all
        """

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, None):
                pass

    # https://github.com/goldmann/docker-squash/issues/66
    def test_build_without_tag(self):
        dockerfile = (
            """
        FROM %s
        RUN touch file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, None, tag=False):
                pass

    # https://github.com/goldmann/docker-squash/issues/94
    def test_should_squash_correctly_hardlinks(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir -p /usr/libexec/git-core && \
            echo foo > /usr/libexec/git-core/git-remote-ftp && \
            ln /usr/libexec/git-core/git-remote-ftp \
            /usr/libexec/git-core/git-remote-http
        CMD /bin/bash
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 2)
                squashed_image.assertFileExists("usr/libexec/git-core/git-remote-ftp")
                squashed_image.assertFileExists("usr/libexec/git-core/git-remote-http")

    # https://github.com/goldmann/docker-squash/issues/104
    def test_should_handle_symlinks_to_nonexisting_locations(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir -p /var/log
        RUN touch /var/log/somelog
        RUN mv /var/log /var/log-removed && ln -sf /data/var/log /var/log
        RUN rm -rf /var/log-removed
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                self.assertEqual(len(squashed_image.layers), len(image.layers) - 2)

    def test_should_squash_every_layer_from_an_image_from_docker_hub(self):
        dockerfile = """
        FROM python:3.5-alpine
        """

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image) as squashed_image:
                self.assertEqual(len(squashed_image.layers), 1)

    # https://github.com/goldmann/docker-squash/issues/111
    def test_correct_symlinks_squashing(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir -p /zzz
        RUN ln -s /zzz /xxx
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image) as squashed_image:
                squashed_image.assertFileExists("zzz")
                squashed_image.assertFileExists("xxx")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("zzz")
                    container.assertFileExists("xxx")

    # https://github.com/goldmann/docker-squash/issues/112
    def test_should_add_broken_symlinks_back(self):
        dockerfile = (
            """
        FROM %s
        RUN touch a
        RUN touch b
        RUN ln -s /zzz /xxx
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                squashed_image.assertFileExists("xxx")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("xxx")

    def test_should_add_hard_hard_link_back_if_target_exists_in_moved_files(self):
        dockerfile = (
            """
        FROM %s
        RUN touch a
        RUN touch b
        RUN ln /a /link
        RUN touch c
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                squashed_image.assertFileExists("link")
                squashed_image.assertFileExists("b")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("link")
                    container.assertFileExists("b")
                    container.assertFileExists("a")
                    container.assertFileExists("c")

    # https://github.com/goldmann/docker-squash/issues/112
    def test_should_add_sym_link_back_if_it_was_broken_before(self):
        dockerfile = (
            """
        FROM %s
        RUN touch a
        RUN touch b
        RUN touch c
        RUN ln -s /a /link
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                squashed_image.assertFileExists("link")
                squashed_image.assertFileExists("b")
                squashed_image.assertFileExists("c")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("link")
                    container.assertFileExists("a")
                    container.assertFileExists("b")
                    container.assertFileExists("c")

    # https://github.com/goldmann/docker-squash/issues/116
    def test_should_not_skip_sym_link(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir /dir
        RUN touch /dir/a
        RUN touch /dir/b
        RUN mkdir /dir/dir
        RUN touch /dir/dir/file
        RUN mv /dir/dir /newdir
        RUN ln -s /newdir /dir/dir
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                with self.Container(squashed_image) as container:
                    container.assertFileExists("dir")
                    container.assertFileExists("dir/a")
                    container.assertFileExists("dir/b")
                    container.assertFileExists("dir/dir")
                    container.assertFileExists("newdir/file")

    # https://github.com/goldmann/docker-squash/issues/118
    def test_should_not_skip_hard_link(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir /dir
        RUN touch /dir/a
        RUN touch /dir/b
        RUN mkdir /dir/dir
        RUN touch /dir/dir/file
        RUN mkdir /newdir
        RUN mv /dir/dir/file /newdir/file
        RUN ln /newdir/file /dir/dir/file
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                with self.Container(squashed_image) as container:
                    container.assertFileExists("dir")
                    container.assertFileExists("dir/a")
                    container.assertFileExists("dir/b")
                    container.assertFileExists("dir/dir")
                    container.assertFileExists("newdir/file")

    # https://github.com/goldmann/docker-squash/issues/118
    def test_should_not_add_hard_link_if_exists_in_other_squashed_layer(self):
        dockerfile = (
            """
        FROM %s
        RUN echo "base" > file && ln file link
        RUN echo "first layer" > file && ln -f file link
        RUN echo "second layer" > file && ln -f file link
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                with self.Container(squashed_image):
                    pass

    # https://github.com/goldmann/docker-squash/issues/120
    def test_should_handle_symlinks_to_directory(self):
        dockerfile = (
            """
        FROM %s
        RUN mkdir /tmp/dir
        RUN touch /tmp/dir/file
        RUN set -e ; cd / ; mkdir /data-template ; tar cf - ./tmp/dir/ | ( cd /data-template && tar xf - ) ; mkdir -p $( dirname /tmp/dir ) ; rm -rf /tmp/dir ; ln -sf /data/tmp/dir /tmp/dir
        """
            % TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                with self.Container(squashed_image) as container:
                    container.assertFileExists("data-template")
                    container.assertFileExists("data-template/tmp")
                    container.assertFileExists("data-template/tmp/dir")
                    container.assertFileExists("data-template/tmp/dir/file")
                    container.assertFileExists("tmp/dir")
                    container.assertFileDoesNotExist("tmp/dir/file")

    # https://github.com/goldmann/docker-squash/issues/122
    def test_should_not_add_duplicate_files(self):
        dockerfile = """
        FROM {}
        RUN mkdir -p /etc/systemd/system/multi-user.target.wants
        RUN mkdir -p /etc/systemd/system/default.target.wants
        RUN touch /etc/systemd/system/multi-user.target.wants/remote-fs.target
        RUN touch /etc/systemd/system/default.target.wants/remote-fs.target
        # End of preparations, going to squash from here
        RUN find /etc/systemd/system/* '!' -name '*.wants' | xargs rm -rvf
        RUN rmdir -v /etc/systemd/system/multi-user.target.wants && mkdir /etc/systemd/system/container-ipa.target.wants && ln -s /etc/systemd/system/container-ipa.target.wants /etc/systemd/system/multi-user.target.wants
        RUN ln -s /etc/group /etc/systemd/system/default.target
        RUN ln -s /etc/group /etc/systemd/system/container-ipa.target.wants/ipa-server-configure-first.service
        RUN echo "/etc/systemd/system" > /etc/volume-data-list
        RUN set -e ; cd / ; mkdir /data-template ; cat /etc/volume-data-list | while read i ; do echo $i ; if [ -e $i ] ; then tar cf - .$i | ( cd /data-template && tar xf - ) ; fi ; mkdir -p $( dirname $i ) ; if [ "$i" == /var/log/ ] ; then mv /var/log /var/log-removed ; else rm -rf $i ; fi ; ln -sf /data$i $i ; done
        """.format(
            TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(
                image, 6, numeric=True, output_path="tox.tar"
            ) as squashed_image:
                with self.Container(squashed_image) as container:
                    container.assertFileExists(
                        "data-template/etc/systemd/system/container-ipa.target.wants"
                    )
                    container.assertFileExists(
                        "data-template/etc/systemd/system/default.target.wants"
                    )
                    container.assertFileExists(
                        "data-template/etc/systemd/system/default.target"
                    )
                    container.assertFileExists(
                        "data-template/etc/systemd/system/multi-user.target.wants"
                    )
                    container.assertFileExists(
                        "data-template/etc/systemd/system/container-ipa.target.wants/ipa-server-configure-first.service"
                    )
                    container.assertFileExists("etc/systemd/system")

    # https://github.com/goldmann/docker-squash/issues/181
    def test_should_not_add_marker_files_in_already_marked_directories(self):
        dockerfile = """
        FROM {}
        RUN mkdir -p /opt/testing/some/dir/structure
        RUN touch /opt/testing/some/dir/structure/1_base_file /opt/testing/some/dir/structure/2_base_file /opt/testing/some/dir/structure/3_base_file
        RUN rm /opt/testing/some/dir/structure/2_base_file /opt/testing/some/dir/structure/3_base_file
        RUN touch /opt/testing/some/dir/structure/new_file
        RUN rm -rf /opt/testing
        RUN rm -rf /opt
        """.format(
            TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 4, numeric=True) as squashed_image:
                squashed_image.assertFileExists(".wh.opt")

                with self.Container(squashed_image) as container:
                    container.assertFileDoesNotExist("/opt")

    # https://github.com/goldmann/docker-squash/issues/181
    def test_should_not_add_marker_files_in_already_marked_directories_multiple_removal(
        self,
    ):
        dockerfile = """
        FROM {}
        RUN mkdir -p /opt/testing/some/dir/structure
        RUN touch /opt/testing/some/dir/structure/1_base_file /opt/testing/some/dir/structure/2_base_file /opt/testing/some/dir/structure/3_base_file
        RUN rm /opt/testing/some/dir/structure/2_base_file /opt/testing/some/dir/structure/3_base_file
        RUN touch /opt/testing/some/dir/structure/new_file
        RUN rm -rf /opt/testing
        """.format(
            TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                squashed_image.assertFileExists("opt/.wh.testing")

                with self.Container(squashed_image) as container:
                    container.assertFileDoesNotExist("/opt/testing")

    # https://github.com/goldmann/docker-squash/issues/186
    def test_should_handle_opaque_dirs(self):
        dockerfile = """
        FROM {}
        RUN mkdir -p /d1 && touch /d1/foobar
        RUN rm -rf /d1 && mkdir -p /d1 && touch /d1/foo
        """.format(
            TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, numeric=True) as squashed_image:
                with self.Container(image) as container:
                    container.assertFileExists("d1/foo")
                    container.assertFileDoesNotExist("d1/foobar")

                with self.Container(squashed_image) as container:
                    container.assertFileExists("d1/foo")
                    container.assertFileDoesNotExist("d1/foobar")

    # https://github.com/goldmann/docker-squash/issues/186
    # https://github.com/opencontainers/image-spec/blob/master/layer.md#whiteouts
    def test_should_handle_opaque_dirs_spec_example(self):
        dockerfile = """
        FROM {}
        RUN mkdir -p a/b/c && touch a/b/c/bar
        RUN rm -rf a
        RUN mkdir -p a/b/c && touch a/b/c/foo
        """.format(
            TestIntegSquash.BUSYBOX_IMAGE
        )

        with self.Image(dockerfile) as image:
            image.assertFileExistsInLayer("a", -3)
            image.assertFileExistsInLayer("a/b", -3)
            image.assertFileExistsInLayer("a/b/c", -3)
            image.assertFileExistsInLayer("a/b/c/bar", -3)

            image.assertFileExistsInLayer(".wh.a", -2)

            image.assertFileExistsInLayer("a")
            image.assertFileExistsInLayer("a/b")
            image.assertFileExistsInLayer("a/b/c")
            image.assertFileExistsInLayer("a/b/c/foo")

            with self.SquashedImage(image, 3, numeric=True) as squashed_image:
                squashed_image.assertFileExists("a")
                squashed_image.assertFileExists("a/b")
                squashed_image.assertFileExists("a/b/c")
                squashed_image.assertFileExists("a/b/c/foo")
                squashed_image.assertFileDoesNotExist("a/b/c/bar")

    def test_without_io_failure(self):
        dockerfile = """
        FROM  docker.elastic.co/elasticsearch/elasticsearch:7.14.2
        RUN rm -rf /usr/share/elasticsearch/jdk/*
        """

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, None):
                pass


class NumericValues(IntegSquash):
    @classmethod
    def setUpClass(cls):
        dockerfile = """
        FROM busybox:1.36.1
        RUN touch /tmp/test1
        RUN touch /tmp/test2
        CMD /bin/env
        LABEL foo bar
        """

        IntegSquash.build_image(dockerfile)

    @classmethod
    def tearDownClass(cls):
        IntegSquash.cleanup_image()

    def test_should_not_squash_more_layers_than_image_has(self):
        with self.assertRaisesRegex(
            SquashError,
            r"Cannot squash 20 layers, the .* image contains only \d layers",
        ):
            with self.SquashedImage(NumericValues.image, 20, numeric=True):
                pass

    def test_should_not_squash_negative_number_of_layers(self):
        with self.assertRaisesRegex(
            SquashError,
            "Number of layers to squash cannot be less or equal 0, provided: -1",
        ):
            with self.SquashedImage(NumericValues.image, -1, numeric=True):
                pass

    def test_should_not_squash_zero_number_of_layers(self):
        with self.assertRaisesRegex(
            SquashError,
            "Number of layers to squash cannot be less or equal 0, provided: 0",
        ):
            with self.SquashedImage(NumericValues.image, 0, numeric=True):
                pass

    def test_should_not_squash_single_layer(self):
        with self.assertRaisesRegex(
            SquashUnnecessaryError,
            "Single layer marked to squash, no squashing is required",
        ):
            with self.SquashedImage(NumericValues.image, 1, numeric=True):
                pass

    @parameterized.expand([(2,), (3,), (4,)])
    def test_should_squash_n_layers(self, number_of_layers):
        with self.SquashedImage(
            NumericValues.image, number_of_layers, numeric=True
        ) as squashed_image:
            i_h = NumericValues.image.history[number_of_layers:]
            s_h = squashed_image.history[1:]

            self.assertEqual(
                len(squashed_image.layers),
                len(NumericValues.image.layers) - (number_of_layers - 1),
            )

            for c in range(len(i_h)):
                for key in "CreatedBy", "Comment", "Size":
                    self.assertEqual(s_h[c][key], i_h[c][key])
            self.assertEqual(squashed_image.history[0]["Comment"], "")
            self.assertEqual(squashed_image.history[0]["CreatedBy"], "")


if __name__ == "__main__":
    unittest.main()
