# -*- coding: utf-8 -*-

import docker
import os


def docker_client():
    if os.environ.get('DOCKER_CONNECTION'):
        return docker.Client(base_url=os.environ['DOCKER_CONNECTION'])
    else:
        return docker.Client(base_url='unix://var/run/docker.sock',
                             timeout=240)
