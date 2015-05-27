import unittest
import pytest
import mock
import six
import docker
import os
import json
import logging
import sys
import tarfile
import io
from io import BytesIO
import uuid

from docker_scripts.squash import Squash
from docker_scripts.errors import SquashError

if not six.PY3:
    import docker_scripts.lib.xtarfile


class TestIntegMarkerFiles(unittest.TestCase):

    docker = docker.Client(version='1.16')

    log = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    class Image(object):

        def __init__(self, dockerfile):
            self.dockerfile = dockerfile
            self.docker = TestIntegMarkerFiles.docker
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

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not os.getenv('CI'):
                self.docker.remove_image(image=self.tag, force=True)

    class SquashedImage(object):

        def __init__(self, image, number_of_layers):
            self.image = image
            self.number_of_layers = number_of_layers
            self.docker = TestIntegMarkerFiles.docker
            self.log = TestIntegMarkerFiles.log
            self.tag = "%s:squashed" % self.image.name

        def __enter__(self):
            from_layer = self.docker.history(
                self.image.tag)[self.number_of_layers]['Id']

            squash = Squash(
                self.log, self.image.tag, self.docker, tag=self.tag, from_layer=from_layer)
            squash.run()
            self.squashed_layer = self._squashed_layer()
            self.layers = [o['Id'] for o in self.docker.history(self.tag)]
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not os.getenv('CI'):
                self.docker.remove_image(image=self.tag, force=True)

        def _save_image(self):
            image = self.docker.get_image(self.tag)

            buf = io.BytesIO()
            buf.write(image.data)
            buf.seek(0)  # Rewind

            return buf

        def _extract_file(self, name, tar_object):
            with tarfile.open(fileobj=tar_object, mode='r') as tar:
                member = tar.getmember(name)
                return tar.extractfile(member)

        def _squashed_layer(self):
            image_id = self.docker.inspect_image(self.tag)['Id']
            image = self._save_image()

            return self._extract_file(image_id + '/layer.tar', image)

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
                assert member.islnk() == False, "File '%s' should not be a hard link, but it is" % name

    class Container(object):

        def __init__(self, image):
            self.image = image
            self.docker = TestIntegMarkerFiles.docker
            self.log = TestIntegMarkerFiles.log

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


    def test_all_files_should_be_in_squashed_layer(self):
        """
        We squash all layers in RUN, all files should be in the resulting squashed layer.
        """
        dockerfile = '''
        FROM busybox
        RUN touch /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        '''

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
        FROM busybox
        RUN touch /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        '''

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
        FROM busybox
        RUN touch /somefile_layer1
        RUN rm /somefile_layer1
        RUN touch /somefile_layer3
        '''

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
        FROM busybox
        RUN touch /somefile_layer1
        RUN rm /somefile_layer1
        RUN touch /somefile_layer2
        RUN touch /somefile_layer3
        RUN rm /somefile_layer2
        RUN touch /somefile_layer4
        '''

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
        FROM busybox
        RUN mkdir -p /some/dir/tree
        RUN touch /some/dir/tree/file1
        RUN touch /some/dir/tree/file2
        RUN touch /some/dir/file1
        RUN touch /some/dir/file2
        RUN rm -rf /some/dir/tree
        '''

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
        FROM busybox
        RUN touch /file
        RUN chmod -R 777 /file
        RUN rm -rf /file
        '''

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
        FROM busybox
        RUN touch /file
        RUN chmod -R 777 /file
        RUN rm -rf /file
        RUN touch /file
        '''

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
        FROM busybox
        RUN mkdir -p /some/dir/tree
        RUN touch /some/dir/tree/file1
        RUN touch /some/dir/tree/file2
        RUN touch /some/dir/file1
        RUN touch /some/dir/file2
        RUN chmod -R 777 /some
        RUN rm -rf /some/dir/tree
        '''

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


if __name__ == '__main__':
    unittest.main()
