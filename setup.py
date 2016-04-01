#!/usr/bin/python

from setuptools import setup, find_packages
from docker_squash.version import version

import codecs

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name = "docker-squash",
    version = version,
    packages = find_packages(exclude=["tests"]),
    url = 'https://github.com/goldmann/docker-squash',
    download_url = "https://github.com/goldmann/docker-squash/archive/%s.tar.gz" % version,
    author = 'Marek Goldmann',
    author_email = 'marek.goldmann@gmail.com',
    description = 'Docker layer squashing tool',
    license='MIT',
    keywords = 'docker',
    long_description = codecs.open('README.rst', encoding="utf8").read(),
    entry_points = {
        'console_scripts': ['docker-squash=docker_squash.cli:run'],
    },
    tests_require = ['mock'],
    install_requires=requirements
)
