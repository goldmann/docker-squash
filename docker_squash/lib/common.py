# -*- coding: utf-8 -*-

import os

import docker
import requests

from docker_squash.errors import Error

# First try to import Docker client using the API
# available in version 2 of the library and fall
# back to version 1
try:
    from docker.api.client import APIClient as APIClientClass
except ImportError:
    from docker.client import Client as APIClientClass

DEFAULT_TIMEOUT_SECONDS = 600


def docker_client(log):
    log.debug("Preparing Docker client...")

    # Default timeout 10 minutes
    try:
        timeout = int(os.getenv("DOCKER_TIMEOUT", 600))
    except ValueError:
        raise Error(
            "Provided timeout value: %s cannot be parsed as integer, exiting."
            % os.getenv("DOCKER_TIMEOUT")
        )

    if not timeout > 0:
        raise Error(
            "Provided timeout value needs to be greater than zero, currently: %s, exiting."
            % timeout
        )

    # backwards compat
    try:
        os.environ["DOCKER_HOST"] = os.environ["DOCKER_CONNECTION"]
        log.warn("DOCKER_CONNECTION is deprecated, please use DOCKER_HOST instead")
    except KeyError:
        pass

    params = {"version": "auto"}
    params.update(docker.utils.kwargs_from_env())
    params["timeout"] = timeout

    try:
        client = APIClientClass(**params)
    except docker.errors.DockerException as e:
        log.error(
            "Could not create Docker client, please make sure that you specified valid parameters in the 'DOCKER_HOST' environment variable."
        )
        raise Error("Error while creating the Docker client: %s" % e)

    if client and valid_docker_connection(client):
        log.debug("Docker client ready")
        return client
    else:
        log.error(
            "Could not connect to the Docker daemon, please make sure the Docker daemon is running."
        )

        if os.environ.get("DOCKER_HOST"):
            log.error(
                "If Docker daemon is running, please make sure that you specified valid parameters in the 'DOCKER_HOST' environment variable."
            )

        raise Error("Cannot connect to Docker daemon")


def valid_docker_connection(client):
    try:
        return client.ping()
    except requests.exceptions.ConnectionError:
        return False
