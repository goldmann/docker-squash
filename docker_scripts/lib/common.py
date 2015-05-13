# -*- coding: utf-8 -*-

import docker
import os
import sys
import requests


def docker_client():
    if os.environ.get('DOCKER_CONNECTION'):
        try:
            client = docker.Client(base_url=os.environ['DOCKER_CONNECTION'])
        except docker.errors.DockerException as e:
            print("Error while creating the Docker client: %s" % e)
            print(
                "Please make sure that you specified valid parameters in the 'DOCKER_CONNECTION' environment variable.")
            sys.exit(1)
    else:
        client = docker.Client(base_url='unix://var/run/docker.sock',
                               timeout=240)

    if client and valid_docker_connection(client):
        return client
    else:
        print(
            "Could not connect to the Docker daemon, please make sure the Docker daemon is running.")

        if os.environ.get('DOCKER_CONNECTION'):
            print(
                "If the Docker is running, please make sure that you specified valid parameters in the 'DOCKER_CONNECTION' environment variable.")

        sys.exit(1)


def valid_docker_connection(client):
    try:
        return client.ping()
    except requests.exceptions.ConnectionError:
        return False
