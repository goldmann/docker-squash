#!/usr/bin/python

from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name = "docker-scripts",
    version = "0.3.0",
    packages = find_packages(),
    entry_points={
        'console_scripts': ['docker-scripts=docker_scripts.cli.main:run'],
    },
    install_requires=requirements
)
