#!/usr/bin/python

from setuptools import setup, find_packages
setup(
    name = "docker-scripts",
    version = "0.2.2",
    packages = find_packages(),
    entry_points={
        'console_scripts': ['docker-scripts=docker_scripts.cli.main:run'],
    },
)
