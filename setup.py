#!/usr/bin/python

from setuptools import setup, find_packages
from docker_scripts.version import version

import codecs

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name = "docker-scripts",
    version = version,
    packages = find_packages(exclude=["tests"]),
    url = 'https://github.com/goldmann/docker-scripts',
    download_url = "https://github.com/goldmann/docker-scripts/archive/%s.tar.gz" % version,
    author = 'Marek Goldmann',
    author_email = 'marek.goldmann@gmail.com',
    description = 'A swiss-knife tool that could be useful for people working with Docker',
    license='MIT',
    keywords = 'docker',
    long_description = codecs.open('README.rst', encoding="utf8").read(),
    entry_points = {
        'console_scripts': ['docker-scripts=docker_scripts.cli:run'],
    },
    tests_require = ['mock'],
    install_requires=requirements
)
