import unittest
import pytest
import mock
import six
import codecs
import docker
import os
import json
import logging
import shutil
import sys
import tarfile
import io
from io import BytesIO
import uuid

from docker_squash.squash import Squash
from docker_squash.errors import SquashError

if not six.PY3:
    import docker_squash.lib.xtarfile

class ImageHelper(object):
    @staticmethod
    def top_layer_path(tar):
        #tar_object.seek(0)
        reader = codecs.getreader("utf-8")

        if 'repositories' in tar.getnames():
            repositories_member = tar.getmember('repositories')
            repositories = json.load(reader(tar.extractfile(repositories_member)))
            return repositories.popitem()[1].popitem()[1]
        else:
            manifest_member = tar.getmember('manifest.json')
            manifest = json.load(reader(tar.extractfile(manifest_member)))
            return manifest[0]["Layers"][-1].split("/")[0]

class IntegSquash(unittest.TestCase):

    BUSYBOX_IMAGE = "busybox:1.24"

    # Default base url for the connection
    base_url = os.getenv('DOCKER_CONNECTION', 'unix://var/run/docker.sock')
    docker = docker.AutoVersionClient(base_url=base_url)

    log = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    @classmethod
    def build_image(cls, dockerfile):
        IntegSquash.image = IntegSquash.Image(dockerfile)
        IntegSquash.image.__enter__()

    @classmethod
    def cleanup_image(cls):
        IntegSquash.image.__exit__(None, None, None)

    class Image(object):

        def __init__(self, dockerfile):
            self.dockerfile = dockerfile
            self.docker = TestIntegSquash.docker
            self.name = "integ-%s" % uuid.uuid1()
            self.tag = "%s:latest" % self.name

        def __enter__(self):
            f = BytesIO(self.dockerfile.encode('utf-8'))
            for line in self.docker.build(fileobj=f, tag=self.tag, rm=True):
                try:
                    print(json.loads(line)["stream"].strip())
                except:
                    print(line)

            self.history = self.docker.history(self.tag)
            self.layers = [o['Id'] for o in self.history]
            self.metadata = self.docker.inspect_image(self.tag)
            self.tar = self._save_image()

            with tarfile.open(fileobj=self.tar, mode='r') as tar:
                self.tarnames = tar.getnames()

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not os.getenv('CI'):
                self.docker.remove_image(image=self.tag, force=True)

        # Duplicated, I know...
        def _save_image(self):
            image = self.docker.get_image(self.tag)

            buf = io.BytesIO()
            buf.write(image.data)
            buf.seek(0)  # Rewind

            return buf

    class SquashedImage(object):

        def __init__(self, image, number_of_layers=None, output_path=None, load_image=True, numeric=False, tmp_dir=None, log=None, development=False):
            self.image = image
            self.number_of_layers = number_of_layers
            self.docker = TestIntegSquash.docker
            self.log = log or TestIntegSquash.log
            self.tag = "%s:squashed" % self.image.name
            self.output_path = output_path
            self.load_image = load_image
            self.numeric = numeric
            self.tmp_dir = tmp_dir
            self.development = development

        def __enter__(self):
            from_layer = self.number_of_layers

            if self.number_of_layers and not self.numeric:
                from_layer = self.docker.history(
                    self.image.tag)[self.number_of_layers]['Id']

            squash = Squash(
                self.log, self.image.tag, self.docker, tag=self.tag, from_layer=from_layer,
                output_path=self.output_path, load_image=self.load_image, tmp_dir=self.tmp_dir, development=self.development)

            self.image_id = squash.run()

            if not self.output_path:
                self.history = self.docker.history(self.tag)

                self.tar = self._save_image()

                with tarfile.open(fileobj=self.tar, mode='r') as tar:
                    self.tarnames = tar.getnames()

                self.squashed_layer = self._squashed_layer()
                self.layers = [o['Id'] for o in self.docker.history(self.tag)]
                self.metadata = self.docker.inspect_image(self.tag)

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not (os.getenv('CI') or self.output_path):
                self.docker.remove_image(image=self.tag, force=True)

        def _save_image(self):
            image = self.docker.get_image(self.tag)

            buf = io.BytesIO()
            buf.write(image.data)
            buf.seek(0)  # Rewind

            return buf

        def _extract_file(self, name, tar_object):
            tar_object.seek(0)
            with tarfile.open(fileobj=tar_object, mode='r') as tar:
                member = tar.getmember(name)
                return tar.extractfile(member)

        def _squashed_layer(self):
            self.tar.seek(0)
            with tarfile.open(fileobj=self.tar, mode='r') as tar:
                self.squashed_layer_path = ImageHelper.top_layer_path(tar)
            return self._extract_file("%s/layer.tar" % self.squashed_layer_path, self.tar)

        def assertFileExists(self, name):
            self.squashed_layer.seek(0)  # Rewind
            with tarfile.open(fileobj=self.squashed_layer, mode='r') as tar:
                assert name in tar.getnames(
                ), "File '%s' was not found in the squashed files: %s" % (name, tar.getnames())

        def assertFileDoesNotExist(self, name):
            self.squashed_layer.seek(0)  # Rewind
            with tarfile.open(fileobj=self.squashed_layer, mode='r') as tar:
                assert name not in tar.getnames(
                ), "File '%s' was found in the squashed layer files: %s" % (name, tar.getnames())

        def assertFileIsNotHardLink(self, name):
            self.squashed_layer.seek(0)  # Rewind
            with tarfile.open(fileobj=self.squashed_layer, mode='r') as tar:
                member = tar.getmember(name)
                assert member.islnk(
                ) == False, "File '%s' should not be a hard link, but it is" % name

    class Container(object):

        def __init__(self, image):
            self.image = image
            self.docker = TestIntegSquash.docker
            self.log = TestIntegSquash.log

        def __enter__(self):
            self.container = self.docker.create_container(image=self.image.tag)
            data = self.docker.export(self.container)
            self.content = six.BytesIO(data.read())
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not os.getenv('CI'):
                self.docker.remove_container(self.container, force=True)

        def assertFileExists(self, name):
            self.content.seek(0)  # Rewind
            with tarfile.open(fileobj=self.content, mode='r') as tar:
                assert name in tar.getnames(
                ), "File %s was not found in the container files: %s" % (name, tar.getnames())

        def assertFileDoesNotExist(self, name):
            self.content.seek(0)  # Rewind
            with tarfile.open(fileobj=self.content, mode='r') as tar:
                assert name not in tar.getnames(
                ), "File %s was found in the container files: %s" % (name, tar.getnames())

class TestIntegSquash(IntegSquash):

    def test_all_files_should_be_in_squashed_layer(self):
        """
        We squash all layers in RUN, all files should be in the resulting squashed layer.
        """
        dockerfile = '''
        FROM %s
        RUN touch /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3) as squashed_image:
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer1')
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer2')
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer3')
                squashed_image.assertFileExists('somefile_layer1')
                squashed_image.assertFileExists('somefile_layer2')
                squashed_image.assertFileExists('somefile_layer3')

                with self.Container(squashed_image) as container:
                    container.assertFileExists('somefile_layer1')
                    container.assertFileExists('somefile_layer2')
                    container.assertFileExists('somefile_layer3')

                    # We should have two layers less in the image
                    self.assertTrue(
                        len(squashed_image.layers) == len(image.layers) - 2)

    def test_only_files_from_squashed_image_should_be_in_squashed_layer(self):
        """
        We squash all layers in RUN, all files should be in the resulting squashed layer.
        """
        dockerfile = '''
        FROM %s
        RUN touch /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer2')
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer3')
                # This file should not be in the squashed layer
                squashed_image.assertFileDoesNotExist('somefile_layer1')
                # Nor a marker files for it
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer1')
                squashed_image.assertFileExists('somefile_layer2')
                squashed_image.assertFileExists('somefile_layer3')

                with self.Container(squashed_image) as container:
                    # This file should be in the container
                    container.assertFileExists('somefile_layer1')
                    container.assertFileExists('somefile_layer2')
                    container.assertFileExists('somefile_layer3')

                    # We should have two layers less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 1)

    def test_there_should_be_a_marker_file_in_the_squashed_layer(self):
        """
        Here we're testing that the squashed layer should contain a '.wh.somefile_layer1'
        file, because the file was not found in the squashed tar and it is present in
        the layers we do not squash.
        """

        dockerfile = '''
        FROM %s
        RUN touch /somefile_layer1
        RUN rm /somefile_layer1
        RUN touch /somefile_layer3
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist('somefile_layer1')
                squashed_image.assertFileExists('somefile_layer3')
                squashed_image.assertFileExists('.wh.somefile_layer1')
                squashed_image.assertFileIsNotHardLink('.wh.somefile_layer1')

                with self.Container(squashed_image) as container:
                    container.assertFileExists('somefile_layer3')
                    container.assertFileDoesNotExist('somefile_layer1')

                    # We should have one layer less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 1)

    def test_there_should_be_a_marker_file_in_the_squashed_layer_even_more_complex(self):
        dockerfile = '''
        FROM %s
        RUN touch /somefile_layer1
        RUN rm /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        RUN rm /somefile_layer2
        RUN touch /somefile_layer4
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist('somefile_layer1')
                squashed_image.assertFileDoesNotExist('somefile_layer2')
                squashed_image.assertFileDoesNotExist('somefile_layer3')
                squashed_image.assertFileExists('somefile_layer4')

                squashed_image.assertFileDoesNotExist('.wh.somefile_layer1')
                squashed_image.assertFileExists('.wh.somefile_layer2')
                squashed_image.assertFileIsNotHardLink('.wh.somefile_layer2')
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer3')
                squashed_image.assertFileDoesNotExist('.wh.somefile_layer4')

                with self.Container(squashed_image) as container:
                    container.assertFileExists('somefile_layer3')
                    container.assertFileExists('somefile_layer4')
                    container.assertFileDoesNotExist('somefile_layer1')
                    container.assertFileDoesNotExist('somefile_layer2')

                    # We should have one layer less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 1)

    def test_should_handle_removal_of_directories(self):
        dockerfile = '''
        FROM %s
        RUN mkdir -p /some/dir/tree
        RUN touch /some/dir/tree/file1
        RUN touch /some/dir/tree/file2
        RUN touch /some/dir/file1
        RUN touch /some/dir/file2
        RUN rm -rf /some/dir/tree
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist('some/dir/tree/file1')
                squashed_image.assertFileDoesNotExist('some/dir/tree/file2')
                squashed_image.assertFileDoesNotExist('some/dir/file1')
                squashed_image.assertFileExists('some/dir/file2')

                squashed_image.assertFileExists('some/dir/.wh.tree')
                squashed_image.assertFileIsNotHardLink('some/dir/.wh.tree')

                with self.Container(squashed_image) as container:
                    container.assertFileExists('some/dir/file1')
                    container.assertFileExists('some/dir/file2')
                    container.assertFileDoesNotExist('some/dir/tree')
                    container.assertFileDoesNotExist('some/dir/tree/file1')
                    container.assertFileDoesNotExist('some/dir/tree/file2')

                    # We should have one layer less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 1)

    def test_should_skip_files_when_these_are_modified_and_removed_in_squashed_layer(self):
        dockerfile = '''
        FROM %s
        RUN touch /file
        RUN chmod -R 777 /file
        RUN rm -rf /file
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist('file')
                squashed_image.assertFileExists('.wh.file')
                squashed_image.assertFileIsNotHardLink('.wh.file')

                with self.Container(squashed_image) as container:
                    container.assertFileDoesNotExist('file')

                    # We should have one layer less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 1)

    def test_should_skip_files_when_these_are_removed_and_modified_in_squashed_layer(self):
        dockerfile = '''
        FROM %s
        RUN touch /file
        RUN chmod -R 777 /file
        RUN rm -rf /file
        RUN touch /file
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3) as squashed_image:
                squashed_image.assertFileExists('file')
                squashed_image.assertFileDoesNotExist('.wh.file')

                with self.Container(squashed_image) as container:
                    container.assertFileExists('file')

                    # We should have two layers less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 2)

    def test_should_handle_multiple_changes_to_files_in_squashed_layers(self):
        dockerfile = '''
        FROM %s
        RUN mkdir -p /some/dir/tree
        RUN touch /some/dir/tree/file1
        RUN touch /some/dir/tree/file2
        RUN touch /some/dir/file1
        RUN touch /some/dir/file2
        RUN chmod -R 777 /some
        RUN rm -rf /some/dir/tree
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                squashed_image.assertFileDoesNotExist('some/dir/tree/file1')
                squashed_image.assertFileDoesNotExist('some/dir/tree/file2')
                squashed_image.assertFileExists('some/dir/file1')
                squashed_image.assertFileExists('some/dir/file2')

                squashed_image.assertFileExists('some/dir/.wh.tree')
                squashed_image.assertFileIsNotHardLink('some/dir/.wh.tree')

                with self.Container(squashed_image) as container:
                    container.assertFileExists('some/dir/file1')
                    container.assertFileExists('some/dir/file2')
                    container.assertFileDoesNotExist('some/dir/tree')
                    container.assertFileDoesNotExist('some/dir/tree/file1')
                    container.assertFileDoesNotExist('some/dir/tree/file2')

                    # We should have one layer less in the image
                    self.assertEqual(
                        len(squashed_image.layers), len(image.layers) - 1)

    # https://github.com/goldmann/docker-scripts/issues/28
    def test_docker_version_in_metadata_should_be_set_after_squashing(self):
        dockerfile = '''
        FROM %s
        RUN touch file
        RUN touch another_file
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                self.assertEqual(
                    len(squashed_image.layers), len(image.layers) - 1)
                self.assertEqual(
                    image.metadata['DockerVersion'], squashed_image.metadata['DockerVersion'])

    # https://github.com/goldmann/docker-scripts/issues/30
    # https://github.com/goldmann/docker-scripts/pull/31
    def test_files_in_squashed_tar_not_prefixed_wth_dot(self):
        dockerfile = '''
        FROM %s
        RUN touch file
        RUN touch another_file
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, output_path="image.tar"):
                with tarfile.open("image.tar", mode='r') as tar:
                    all_files = tar.getnames()
                    for name in all_files:
                        self.assertFalse(name.startswith('.'))

    # https://github.com/goldmann/docker-scripts/issues/32
    def test_version_file_exists_in_squashed_layer(self):
        dockerfile = '''
        FROM %s
        RUN touch file
        RUN touch another_file
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2, output_path="image.tar"):
                with tarfile.open("image.tar", mode='r') as tar:
                    squashed_layer_path = ImageHelper.top_layer_path(tar)
                    
                    all_files = tar.getnames()

                    self.assertIn("%s/json" % squashed_layer_path, all_files)
                    self.assertIn("%s/layer.tar" % squashed_layer_path, all_files)
                    self.assertIn("%s/VERSION" % squashed_layer_path, all_files)

    # https://github.com/goldmann/docker-scripts/issues/33
    def test_docker_size_in_metadata_should_be_upper_case(self):
        dockerfile = '''
        FROM %s
        RUN touch file
        RUN touch another_file
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                self.assertEqual(
                    len(squashed_image.layers), len(image.layers) - 1)
                self.assertIsInstance(image.metadata['Size'], int)
                with self.assertRaisesRegexp(KeyError, "'size'"):
                    self.assertEqual(image.metadata['size'], None)

    def test_handle_correctly_squashing_layers_without_data(self):
        dockerfile = '''
        FROM %s
        ENV a=1
        ENV b=2
        ENV c=3
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                self.assertEqual(
                    len(squashed_image.layers), len(image.layers) - 1)
                image_data_layers = [s for s in image.tarnames if "layer.tar" in s]
                squashed_image_data_layers = [s for s in squashed_image.tarnames if "layer.tar" in s]

                if 'manifest.json' in image.tarnames:
                    # For v2
                    # For V2 only layers with data contain layer.tar archives
                    # In our test case we did not add any data, so the count should
                    # be the same
                    self.assertEqual(len(image_data_layers), len(squashed_image_data_layers))
                else:
                    # For v1
                    # V1 image contains as many layer.tar archives as the image has layers
                    # We squashed 2 layers, so squashed image contains one layer less
                    self.assertEqual(len(image_data_layers), len(squashed_image_data_layers) + 1)

    # This is an edge case where we try to squash last 2 layers
    # but these layers do not create any content on filesystem
    # https://github.com/goldmann/docker-scripts/issues/54
    def test_should_squash_exactly_2_layers_without_data(self):
        dockerfile = '''
        FROM %s
        CMD /bin/env
        LABEL foo bar
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 2) as squashed_image:
                self.assertEqual(
                    len(squashed_image.layers), len(image.layers) - 1)

    def test_should_squash_exactly_3_layers_with_data(self):
        dockerfile = '''
        FROM %s
        RUN touch /abc
        CMD /bin/env
        LABEL foo bar
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image, 3) as squashed_image:
                self.assertEqual(
                    len(squashed_image.layers), len(image.layers) - 2)

    def test_should_not_squash_if_only_one_layer_is_to_squash(self):
        dockerfile = '''
        FROM %s
        RUN touch /abc
        CMD /bin/env
        LABEL foo bar
        ''' % TestIntegSquash.BUSYBOX_IMAGE

        with self.Image(dockerfile) as image:
            with self.assertRaises(SquashError) as cm:
                with self.SquashedImage(image, 1) as squashed_image:
                    pass

        self.assertEquals(str(cm.exception), '1 layer(s) in this image marked to squash, no squashing is required')

    # https://github.com/goldmann/docker-scripts/issues/52
    # Test may be misleading, but squashing all layers makes sure we hit
    # at least one <missing> layer
    def test_should_squash_every_layer(self):
        dockerfile = '''
        FROM busybox:1.24.0
        RUN touch /tmp/test1
        RUN touch /tmp/test2
        CMD /bin/env
        LABEL foo bar
        '''

        with self.Image(dockerfile) as image:
            with self.SquashedImage(image) as squashed_image:
                pass

    # https://github.com/goldmann/docker-scripts/issues/44
    def test_remove_tmp_dir_after_failure(self):
        dockerfile = '''
        FROM busybox:1.24.0
        LABEL foo bar
        '''

        tmp_dir = "/tmp/docker-squash-integ-tmp-dir"
        log = mock.Mock()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertFalse(os.path.exists(tmp_dir))

        with self.Image(dockerfile) as image:
            with self.assertRaisesRegexp(SquashError, "Cannot squash 20 layers, the .* image contains only \d layers"):
                with self.SquashedImage(image, 20, numeric=True, tmp_dir=tmp_dir, log=log):
                    pass

        log.debug.assert_any_call("Using /tmp/docker-squash-integ-tmp-dir as the temporary directory")
        log.debug.assert_any_call("Cleaning up /tmp/docker-squash-integ-tmp-dir temporary directory")

        self.assertFalse(os.path.exists(tmp_dir))

    def test_should_not_remove_tmp_dir_after_failure_if_development_mode_is_on(self):
        dockerfile = '''
        FROM busybox:1.24.0
        LABEL foo bar
        '''

        tmp_dir = "/tmp/docker-squash-integ-tmp-dir"
        log = mock.Mock()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertFalse(os.path.exists(tmp_dir))

        with self.Image(dockerfile) as image:
            with self.assertRaisesRegexp(SquashError, "Cannot squash 20 layers, the .* image contains only \d layers"):
                with self.SquashedImage(image, 20, numeric=True, tmp_dir=tmp_dir, log=log, development=True):
                    pass

        log.debug.assert_any_call("Using /tmp/docker-squash-integ-tmp-dir as the temporary directory")

        self.assertTrue(os.path.exists(tmp_dir))


class NumericValues(IntegSquash):
    @classmethod
    def setUpClass(cls):
        dockerfile = '''
        FROM busybox:1.24.0
        RUN touch /tmp/test1
        RUN touch /tmp/test2
        CMD /bin/env
        LABEL foo bar
        '''

        IntegSquash.build_image(dockerfile)

    @classmethod
    def tearDownClass(cls):
        IntegSquash.cleanup_image()

    def test_should_not_squash_more_layers_than_image_has(self):
        with self.assertRaisesRegexp(SquashError, "Cannot squash 20 layers, the .* image contains only \d layers"):
            with self.SquashedImage(NumericValues.image, 20, numeric=True):
                pass

    def test_should_not_squash_negative_number_of_layers(self):
        with self.assertRaisesRegexp(SquashError, "Number of layers to squash cannot be less or equal 0, provided: -1"):
            with self.SquashedImage(NumericValues.image, -1, numeric=True):
                pass

    def test_should_not_squash_zero_number_of_layers(self):
        with self.assertRaisesRegexp(SquashError, "Number of layers to squash cannot be less or equal 0, provided: 0"):
            with self.SquashedImage(NumericValues.image, 0, numeric=True):
                pass

    def test_should_squash_2_layers(self):
        with self.SquashedImage(NumericValues.image, 2, numeric=True) as squashed_image:
            self.assertEqual(squashed_image.history[-1], NumericValues.image.history[-1])
            self.assertEqual(
                len(squashed_image.layers), len(NumericValues.image.layers) - 1)

    def test_should_squash_3_layers(self):
        with self.SquashedImage(NumericValues.image, 3, numeric=True) as squashed_image:
            self.assertEqual(squashed_image.history[-1], NumericValues.image.history[-1])
            self.assertEqual(
                len(squashed_image.layers), len(NumericValues.image.layers) - 2)

    def test_should_squash_4_layers(self):
        with self.SquashedImage(NumericValues.image, 4, numeric=True) as squashed_image:
            self.assertEqual(squashed_image.history[-1], NumericValues.image.history[-1])
            self.assertEqual(
                len(squashed_image.layers), len(NumericValues.image.layers) - 3)

if __name__ == '__main__':
    unittest.main()
