# -*- coding: utf-8 -*-

from .lib import common


class Layers(object):

    def __init__(self, log, image, docker=None, commands=False, dockerfile=False, machine=False, tags=False):
        self.log = log
        self.docker = docker
        self.image = image
        self.commands = commands
        self.dockerfile = dockerfile
        self.machine = machine
        self.tags = tags

        if not docker:
            self.docker = common.docker_client()

    def _read_layer(self, layers, image_id):
        metadata = self.docker.inspect_image(image_id)
        layers.append(metadata)

        if 'Parent' in metadata and metadata['Parent']:
            self._read_layer(layers, metadata['Parent'])

    def _read_tags(self):
        images = self.docker.images(all=True)
        tags = {}

        for image in images:
            if len(image['RepoTags']) == 1 and image['RepoTags'][0] == '<none>:<none>':
                continue

            tags[image['Id']] = image['RepoTags']

        return tags

    def run(self):

        image_id = self.image
        layers = []
        self._read_layer(layers, image_id)
        layers.reverse()

        if self.tags:
            tags = self._read_tags()

        i = 0

        for l in layers:

            command = None

            if 'ContainerConfig' in l and l['ContainerConfig'] and l['ContainerConfig']['Cmd']:
                command = " ".join(l['ContainerConfig']['Cmd'])

            if self.dockerfile:
                if not command:
                    print("FROM %s" % l['Id'])
                else:
                    if l['ContainerConfig']['Cmd'][-1].startswith("#(nop) "):
                        # TODO: special case: ADD
                        # TODO: special case: EXPOSE
                        print(
                            l['ContainerConfig']['Cmd'][-1].split("#(nop) ")[-1])
                    else:
                        print("RUN %s" % l['ContainerConfig']['Cmd'][-1])
            else:
                if self.machine:
                    line = l['Id']
                    if self.tags:
                        line += "|"
                        if l['Id'] in tags:
                            line += "%s" % ",".join(sorted(tags[l['Id']]))
                    if self.commands:
                        line += "|"
                        if command:
                            line += "%s" % command
                else:
                    line = "%s" % " " * i

                    if l != layers[0]:
                        line += u'└─ '

                    line += "%s" % l['Id']

                    if self.commands and command:
                        line += " [%s]" % command

                    if self.tags:

                        if l['Id'] in tags.keys():
                            # Poor man's sorting
                            line += " %s" % sorted(tags[l['Id']])

                print(line.encode("UTF-8"))

            i += 1
