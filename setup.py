#!/usr/bin/python

from setuptools import setup, find_packages

version = "0.3.3"

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name = "docker-scripts",
    version = version,
    packages = find_packages(),
    url = 'https://github.com/goldmann/docker-scripts',
    download_url = "https://github.com/goldmann/docker-scripts/archive/%s.tar.gz" % version,
    author = 'Marek Goldmann',
    author_email = 'marek.goldmann@gmail.com',
    description = 'A swiss-knife tool that could be useful for people working with Docker',
    license='MIT',
    keywords = 'docker',
    long_description = open('README.rst').read(),
    entry_points = {
        'console_scripts': ['docker-scripts=docker_scripts.cli:run'],
    },
    install_requires=requirements
)
