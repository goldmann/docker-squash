# -*- coding: utf-8 -*-

import docker
import os
import sys
import requests


DEFAULT_TIMEOUT_SECONDS = 600


def docker_client():
    # Default timeout 10 minutes
    try:
        timeout = int(os.getenv('DOCKER_TIMEOUT', 600))
    except ValueError as e:
        print("Provided timeout value: %s cannot be parsed as integer, exiting." %
              os.getenv('DOCKER_TIMEOUT'))
        sys.exit(1)

    if not timeout > 0:
        print(
            "Provided timeout value needs to be greater than zero, currently: %s, exiting." % timeout)
        sys.exit(1)

    # Default base url for the connection
    base_url = os.getenv('DOCKER_CONNECTION', 'unix://var/run/docker.sock')

    try:
        client = docker.AutoVersionClient(base_url=base_url, timeout=timeout)
    except docker.errors.DockerException as e:
        print("Error while creating the Docker client: %s" % e)
        print(
            "Please make sure that you specified valid parameters in the 'DOCKER_CONNECTION' environment variable.")
        sys.exit(1)

    if client and valid_docker_connection(client):
        return client
    else:
        print(
            "Could not connect to the Docker daemon, please make sure the Docker daemon is running.")

        if os.environ.get('DOCKER_CONNECTION'):
            print(
                "If Docker daemon is running, please make sure that you specified valid parameters in the 'DOCKER_CONNECTION' environment variable.")

        sys.exit(1)


def valid_docker_connection(client):
    try:
        return client.ping()
    except requests.exceptions.ConnectionError:
        return False
