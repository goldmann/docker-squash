#!/usr/bin/python

from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name = "docker-scripts",
    version = "0.3.0",
    packages = find_packages(),
    url='https://github.com/goldmann/docker-scripts',
    author='Marek Goldmann',
    author_email='marek.goldmann@gmail.com',
    license='MIT',
    entry_points={
        'console_scripts': ['docker-scripts=docker_scripts.cli.main:run'],
    },
    install_requires=requirements
)
