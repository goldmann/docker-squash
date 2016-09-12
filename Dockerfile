FROM python:3-onbuild
MAINTAINER "https://github.com/goldmann/docker-squash"
ENTRYPOINT [ "python", "-m", "docker_squash.cli" ]
