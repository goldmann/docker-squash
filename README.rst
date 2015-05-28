``docker-scripts``
==================

.. image:: https://circleci.com/gh/goldmann/docker-scripts.svg?style=svg
    :target: https://circleci.com/gh/goldmann/docker-scripts

.. image:: https://landscape.io/github/goldmann/docker-scripts/master/landscape.svg?style=flat
   :target: https://landscape.io/github/goldmann/docker-scripts/master

.. image:: https://badges.gitter.im/Join%20Chat.svg
   :target: https://gitter.im/goldmann/docker-scripts

Features
--------

Current list of features:

-  Squashing
-  Listing layers in a Docker image

Installation
------------

From source code

::

    $ git clone https://github.com/goldmann/docker-scripts.git
    $ cd docker-scripts
    $ pip install --user .

From PyPi

::

    $ pip install docker-scripts

Usage
-----

::

    $ docker-scripts -h
    usage: docker-scripts [-h] [-v] {squash,layers} ...

    Set of helpers scripts fo Docker

    optional arguments:
      -h, --help       show this help message and exit
      -v, --verbose    Verbose output

    Available commands:
      {squash,layers}
        squash         Squash layers in the specified image
        layers         Show layers in the specified image

License
-------

MIT

Layers
------

Simple script to show all the layers of which the image is built.

Layers usage
~~~~~~~~~~~~

::

    $ docker-scripts layers -h
    usage: docker-scripts layers [-h] [-c] [-d] [-m] [-t] image

    positional arguments:
      image             ID of the layer or image ID or image name

    optional arguments:
      -h, --help        show this help message and exit
      -c, --commands    Show commands executed to create the layer (if any)
      -d, --dockerfile  Create Dockerfile out of the layers [EXPERIMENTAL!]
      -m, --machine     Machine parseable output
      -t, --tags        Print layer tags if available

Examples
~~~~~~~~

Default output
^^^^^^^^^^^^^^

::

    $ docker-scripts layers jboss/wildfly:latest
    511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158
     └─ 782cf93a8f16d3016dae352188cd5cfedb6a15c37d4dbd704399f02d1bb89dab
      └─ 7d3f07f8de5fb3a20c6cb1e4447773a5741e3641c1aa093366eaa0fc690c6417
       └─ 1ef0a50fe8b1394d3626a7624a58b58cff9560ddb503743099a56bbe95ab481a
        └─ 20a1abe1d9bfb9b1e46d5411abd5a38b6104a323b7c4fb5c0f1f161b8f7278c2
         └─ cd5bb934bb6755e910d19ac3ae4cfd09221aa2f98c3fbb51a7486991364dc1ae
          └─ 379edb00ab0764276787ea777243990da697f2f93acb5d9166ff73ad01511a87
           └─ 4d37cbbfc67dd508e682a5431a99d8c1feba1bd8352ffd3ea794463d9cfa81cc
            └─ 2ea8562cac7c25a308b4565b66d4f7e11a1d2137a599ef2b32ed23c78f0a0378
             └─ 7759146eab1a3aa5ba5ed12483d03e64a6bf1061a383d5713a5e21fc40554457
              └─ b17a20d6f5f8e7ed0a1dba277acd3f854c531b0476b03d63a8f0df4caf78c763
               └─ e02bdb6c4ed5436da02c958d302af5f06c1ebb1821791f60d45e190ebb55130f
                └─ 72d585299bb5c5c1c326422cfffadc93d8bb4020f35bf072b2d91d287967807a
                 └─ 90832e1f0bb9e9f98ecd42f6df6b124c1e6768babaddc23d646cd75c7b2fddec
                  └─ b2b7d0c353b9b7500d23d2670c99abf35c4285a5f396df7ef70386848b45d162
                   └─ 3759d5cffae63d6ddc9f2db9142403ad39bd54e305bb5060ae860aac9b9dec1d
                    └─ 5c98b1e90cdcdb322601091f1f8654bc551015caa9ec41da040ef9a1d8466839
                     └─ 8ac46a315e1ef48cfbe30e9d15242f8f73b322e8ede54c30d93f6859708d48f7
                      └─ 2ac466861ca121d4c5e17970f4939cc3df3755a7fd90a6d11542b7432c03e215

Output with commands
^^^^^^^^^^^^^^^^^^^^

::

    $ docker-scripts layers -c jboss/wildfly:latest
    511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158
     └─ 782cf93a8f16d3016dae352188cd5cfedb6a15c37d4dbd704399f02d1bb89dab [/bin/sh -c #(nop) MAINTAINER Lokesh Mandvekar <lsm5@fedoraproject.org> - ./buildcontainers.sh]
      └─ 7d3f07f8de5fb3a20c6cb1e4447773a5741e3641c1aa093366eaa0fc690c6417 [/bin/sh -c #(nop) ADD file:285fdeab65d637727f6b79392a309135494d2e6046c6cc2fbd2f23e43eaac69c in /]
       └─ 1ef0a50fe8b1394d3626a7624a58b58cff9560ddb503743099a56bbe95ab481a [/bin/sh -c #(nop) MAINTAINER Marek Goldmann <mgoldman@redhat.com>]
        └─ 20a1abe1d9bfb9b1e46d5411abd5a38b6104a323b7c4fb5c0f1f161b8f7278c2 [/bin/sh -c yum -y update && yum clean all]
         └─ cd5bb934bb6755e910d19ac3ae4cfd09221aa2f98c3fbb51a7486991364dc1ae [/bin/sh -c yum -y install xmlstarlet saxon augeas bsdtar unzip && yum clean all]
          └─ 379edb00ab0764276787ea777243990da697f2f93acb5d9166ff73ad01511a87 [/bin/sh -c groupadd -r jboss -g 1000 && useradd -u 1000 -r -g jboss -m -d /opt/jboss -s /sbin/nologin -c "JBoss user" jboss]
           └─ 4d37cbbfc67dd508e682a5431a99d8c1feba1bd8352ffd3ea794463d9cfa81cc [/bin/sh -c #(nop) WORKDIR /opt/jboss]
            └─ 2ea8562cac7c25a308b4565b66d4f7e11a1d2137a599ef2b32ed23c78f0a0378 [/bin/sh -c #(nop) USER jboss]
             └─ 7759146eab1a3aa5ba5ed12483d03e64a6bf1061a383d5713a5e21fc40554457 [/bin/sh -c #(nop) MAINTAINER Marek Goldmann <mgoldman@redhat.com>]
              └─ b17a20d6f5f8e7ed0a1dba277acd3f854c531b0476b03d63a8f0df4caf78c763 [/bin/sh -c #(nop) USER root]
               └─ e02bdb6c4ed5436da02c958d302af5f06c1ebb1821791f60d45e190ebb55130f [/bin/sh -c yum -y install java-1.7.0-openjdk-devel && yum clean all]
                └─ 72d585299bb5c5c1c326422cfffadc93d8bb4020f35bf072b2d91d287967807a [/bin/sh -c #(nop) USER jboss]
                 └─ 90832e1f0bb9e9f98ecd42f6df6b124c1e6768babaddc23d646cd75c7b2fddec [/bin/sh -c #(nop) ENV JAVA_HOME=/usr/lib/jvm/java]
                  └─ b2b7d0c353b9b7500d23d2670c99abf35c4285a5f396df7ef70386848b45d162 [/bin/sh -c #(nop) ENV WILDFLY_VERSION=8.2.0.Final]
                   └─ 3759d5cffae63d6ddc9f2db9142403ad39bd54e305bb5060ae860aac9b9dec1d [/bin/sh -c cd $HOME && curl http://download.jboss.org/wildfly/$WILDFLY_VERSION/wildfly-$WILDFLY_VERSION.tar.gz | tar zx && mv $HOME/wildfly-$WILDFLY_VERSION $HOME/wildfly]
                    └─ 5c98b1e90cdcdb322601091f1f8654bc551015caa9ec41da040ef9a1d8466839 [/bin/sh -c #(nop) ENV JBOSS_HOME=/opt/jboss/wildfly]
                     └─ 8ac46a315e1ef48cfbe30e9d15242f8f73b322e8ede54c30d93f6859708d48f7 [/bin/sh -c #(nop) EXPOSE 8080/tcp]
                      └─ 2ac466861ca121d4c5e17970f4939cc3df3755a7fd90a6d11542b7432c03e215 [/bin/sh -c #(nop) CMD [/opt/jboss/wildfly/bin/standalone.sh -b 0.0.0.0]]

Machine parseable output
~~~~~~~~~~~~~~~~~~~~~~~~

::

    $ python layers.py jboss/torquebox -c -m
    511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158|
    ff75b0852d47a18f23ebf57d2ef7974f470a754c534fa44dfb94d5deec69e6c0|/bin/sh -c #(nop) MAINTAINER Lokesh Mandvekar <lsm5@fedoraproject.org> - ./buildcontainers.sh
    5cc8a068a7372437b21bdb4bafd547cedf4d1ea41fa624aad8df4d8e22ea9ab7|/bin/sh -c #(nop) ADD file:18d3d85c0c8e9ba35d7ae7d1596d97a838ff268a21250819f0fe7278282d1df5 in /
    e6903a263bcc2c8034ad03691163ecaf3511d211e3855c4667a8390cc1518344|/bin/sh -c yum -y update && yum clean all
    a6bda5b9c9ba17dda855e787fb3f25e9b4c1f2cb75e41c3121ea001b9f5ea5ab|/bin/sh -c yum -y install java-1.7.0-openjdk-devel unzip && yum clean all
    ab89a864acfaecf8e69fe26e0fd3177494eb1e7ef468708c8035437577d041f4|/bin/sh -c #(nop) ENV TORQUEBOX_VERSION=3.1.1
    f267f0b474a2037c3ba0d185f3a7ac20a9b1e1967955745fcd5ee9abb0c5da4c|/bin/sh -c cd /opt && curl -L https://d2t70pdxfgqbmq.cloudfront.net/release/org/torquebox/torquebox-dist/$TORQUEBOX_VERSION/torquebox-dist-$TORQUEBOX_VERSION-bin.zip -o torquebox.zip && unzip -q torquebox.zip && rm torquebox.zip
    889e1cbf6afb1aec5cd8cd145188c42c06ec4dc7e9c91c67f86b7bb72d9c6979|/bin/sh -c groupadd -r torquebox -g 434 && useradd -u 432 -r -g torquebox -d /opt/torquebox-$TORQUEBOX_VERSION -s /sbin/nologin -c "TorqueBox user" torquebox
    26d480777a056bc6ddc6f9eb5cb2f5d962eae5aca1880e4a308eef4d8837949b|/bin/sh -c chown -R torquebox:torquebox /opt/torquebox-$TORQUEBOX_VERSION
    904472e47182e3b34c944cc0a4e9e21a096afd64c913e47f3be314fa023239d7|/bin/sh -c #(nop) EXPOSE map[8080/tcp:{}]
    4ca0e3ea46ff37e49831c6bb27e9488f48b8db0fc4f6d7eda70bd4a04408daf7|/bin/sh -c #(nop) USER torquebox
    b621dc5d4989677e62bf8ee0316f557156b5cba2b551e8bbb6368fb5920ae3aa|/bin/sh -c #(nop) CMD [/bin/sh -c /opt/torquebox-$TORQUEBOX_VERSION/jboss/bin/standalone.sh -b 0.0.0.0]

Show tags if available
~~~~~~~~~~~~~~~~~~~~~~

**NOTE:** Only tags available locally will be shown.

::

    $ docker-scripts layers -t jboss/wildfly:latest
    511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158
     └─ 782cf93a8f16d3016dae352188cd5cfedb6a15c37d4dbd704399f02d1bb89dab
      └─ 7d3f07f8de5fb3a20c6cb1e4447773a5741e3641c1aa093366eaa0fc690c6417
       └─ 1ef0a50fe8b1394d3626a7624a58b58cff9560ddb503743099a56bbe95ab481a
        └─ 20a1abe1d9bfb9b1e46d5411abd5a38b6104a323b7c4fb5c0f1f161b8f7278c2
         └─ cd5bb934bb6755e910d19ac3ae4cfd09221aa2f98c3fbb51a7486991364dc1ae
          └─ 379edb00ab0764276787ea777243990da697f2f93acb5d9166ff73ad01511a87
           └─ 4d37cbbfc67dd508e682a5431a99d8c1feba1bd8352ffd3ea794463d9cfa81cc
            └─ 2ea8562cac7c25a308b4565b66d4f7e11a1d2137a599ef2b32ed23c78f0a0378 [u'docker.io/jboss/base:latest']
             └─ 7759146eab1a3aa5ba5ed12483d03e64a6bf1061a383d5713a5e21fc40554457
              └─ b17a20d6f5f8e7ed0a1dba277acd3f854c531b0476b03d63a8f0df4caf78c763
               └─ e02bdb6c4ed5436da02c958d302af5f06c1ebb1821791f60d45e190ebb55130f
                └─ 72d585299bb5c5c1c326422cfffadc93d8bb4020f35bf072b2d91d287967807a
                 └─ 90832e1f0bb9e9f98ecd42f6df6b124c1e6768babaddc23d646cd75c7b2fddec [u'docker.io/jboss/base-jdk:7']
                  └─ b2b7d0c353b9b7500d23d2670c99abf35c4285a5f396df7ef70386848b45d162
                   └─ 3759d5cffae63d6ddc9f2db9142403ad39bd54e305bb5060ae860aac9b9dec1d
                    └─ 5c98b1e90cdcdb322601091f1f8654bc551015caa9ec41da040ef9a1d8466839
                     └─ 8ac46a315e1ef48cfbe30e9d15242f8f73b322e8ede54c30d93f6859708d48f7
                      └─ 2ac466861ca121d4c5e17970f4939cc3df3755a7fd90a6d11542b7432c03e215 [u'docker.io/jboss/wildfly:latest']

Squashing
---------

Squashing... This is a long story. It wasn't merged upstrem despite many
PR that were opened.

Squashing helps with organizing images in logical layers. Instead of
having an image with multiple (in almost all cases) unnecessary layers -
we can control the structure of the image.

Squashing usage
~~~~~~~~~~~~~~~

::

    $ docker-scripts squash -h
    usage: docker-scripts squash [-h] [-f FROM_LAYER] [-t TAG] [--tmp-dir TMP_DIR]
                                 image

    positional arguments:
      image                 Image to be squashed

    optional arguments:
      -h, --help            show this help message and exit
      -f FROM_LAYER, --from-layer FROM_LAYER
                            ID of the layer or image ID or image name. If not
                            specified will squash up to last layer (FROM
                            instruction)
      -t TAG, --tag TAG     Specify the tag to be used for the new image. By
                            default it'll be set to 'image' argument
      --tmp-dir TMP_DIR     Temporary directory to be used

Example
~~~~~~~

We start with image like this:

::

    $ docker-scripts layers -t jboss/wildfly
    511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158
     └─ 782cf93a8f16d3016dae352188cd5cfedb6a15c37d4dbd704399f02d1bb89dab
      └─ 7d3f07f8de5fb3a20c6cb1e4447773a5741e3641c1aa093366eaa0fc690c6417
       └─ 1ef0a50fe8b1394d3626a7624a58b58cff9560ddb503743099a56bbe95ab481a
        └─ 20a1abe1d9bfb9b1e46d5411abd5a38b6104a323b7c4fb5c0f1f161b8f7278c2
         └─ cd5bb934bb6755e910d19ac3ae4cfd09221aa2f98c3fbb51a7486991364dc1ae
          └─ 379edb00ab0764276787ea777243990da697f2f93acb5d9166ff73ad01511a87
           └─ 4d37cbbfc67dd508e682a5431a99d8c1feba1bd8352ffd3ea794463d9cfa81cc
            └─ 2ea8562cac7c25a308b4565b66d4f7e11a1d2137a599ef2b32ed23c78f0a0378 [u'docker.io/jboss/base:latest']
             └─ 7759146eab1a3aa5ba5ed12483d03e64a6bf1061a383d5713a5e21fc40554457
              └─ b17a20d6f5f8e7ed0a1dba277acd3f854c531b0476b03d63a8f0df4caf78c763
               └─ e02bdb6c4ed5436da02c958d302af5f06c1ebb1821791f60d45e190ebb55130f
                └─ 72d585299bb5c5c1c326422cfffadc93d8bb4020f35bf072b2d91d287967807a
                 └─ 90832e1f0bb9e9f98ecd42f6df6b124c1e6768babaddc23d646cd75c7b2fddec [u'docker.io/jboss/base-jdk:7']
                  └─ b2b7d0c353b9b7500d23d2670c99abf35c4285a5f396df7ef70386848b45d162
                   └─ 3759d5cffae63d6ddc9f2db9142403ad39bd54e305bb5060ae860aac9b9dec1d
                    └─ 5c98b1e90cdcdb322601091f1f8654bc551015caa9ec41da040ef9a1d8466839
                     └─ 8ac46a315e1ef48cfbe30e9d15242f8f73b322e8ede54c30d93f6859708d48f7
                      └─ 2ac466861ca121d4c5e17970f4939cc3df3755a7fd90a6d11542b7432c03e215 [u'docker.io/jboss/wildfly:latest']

And we want to squash all the layers down to ``jboss/base:latest``
image.

::

    $ docker-scripts squash jboss/wildfly -f jboss/base:latest -t jboss/wildfly:squashed
    2015-05-11 10:23:35,602 root         INFO     Squashing image 'jboss/wildfly'...
    2015-05-11 10:23:35,857 root         INFO     Old image has 19 layers
    2015-05-11 10:23:35,857 root         INFO     Attempting to squash from layer 2ea8562cac7c25a308b4565b66d4f7e11a1d2137a599ef2b32ed23c78f0a0378...
    2015-05-11 10:23:35,857 root         INFO     Checking if squashing is necessary...
    2015-05-11 10:23:35,857 root         INFO     We have 10 layers to squash
    2015-05-11 10:23:35,858 root         INFO     Saving image 2ac466861ca121d4c5e17970f4939cc3df3755a7fd90a6d11542b7432c03e215 to /tmp/tmp-docker-squash-3NmyuU/image.tar file...
    2015-05-11 10:24:51,357 root         INFO     Image saved!
    2015-05-11 10:24:51,361 root         INFO     Unpacking /tmp/tmp-docker-squash-3NmyuU/image.tar tar file to /tmp/tmp-docker-squash-3NmyuU/old directory
    2015-05-11 10:25:09,890 root         INFO     Archive unpacked!
    2015-05-11 10:25:09,891 root         INFO     New layer ID for squashed content will be: b7e845026f73f67ebeb59ed1958d021aa79c069145d66b1233b7e9ba9fffa729
    2015-05-11 10:25:09,891 root         INFO     Starting squashing...
    2015-05-11 10:25:09,891 root         INFO     Squashing layer 2ac466861ca121d4c5e17970f4939cc3df3755a7fd90a6d11542b7432c03e215...
    2015-05-11 10:25:09,892 root         INFO     Squashing layer 8ac46a315e1ef48cfbe30e9d15242f8f73b322e8ede54c30d93f6859708d48f7...
    2015-05-11 10:25:09,892 root         INFO     Squashing layer 5c98b1e90cdcdb322601091f1f8654bc551015caa9ec41da040ef9a1d8466839...
    2015-05-11 10:25:09,893 root         INFO     Squashing layer 3759d5cffae63d6ddc9f2db9142403ad39bd54e305bb5060ae860aac9b9dec1d...
    2015-05-11 10:25:10,592 root         INFO     Squashing layer b2b7d0c353b9b7500d23d2670c99abf35c4285a5f396df7ef70386848b45d162...
    2015-05-11 10:25:10,593 root         INFO     Squashing layer 90832e1f0bb9e9f98ecd42f6df6b124c1e6768babaddc23d646cd75c7b2fddec...
    2015-05-11 10:25:10,594 root         INFO     Squashing layer 72d585299bb5c5c1c326422cfffadc93d8bb4020f35bf072b2d91d287967807a...
    2015-05-11 10:25:10,594 root         INFO     Squashing layer e02bdb6c4ed5436da02c958d302af5f06c1ebb1821791f60d45e190ebb55130f...
    2015-05-11 10:25:16,796 root         INFO     Squashing layer b17a20d6f5f8e7ed0a1dba277acd3f854c531b0476b03d63a8f0df4caf78c763...
    2015-05-11 10:25:16,799 root         INFO     Squashing layer 7759146eab1a3aa5ba5ed12483d03e64a6bf1061a383d5713a5e21fc40554457...
    2015-05-11 10:25:17,334 root         INFO     Loading squashed image...
    2015-05-11 10:26:14,505 root         INFO     Image loaded!
    2015-05-11 10:26:14,720 root         INFO     Finished, image registered as 'jboss/wildfly:squashed'

We can now confirm the layer structure:

::

    $ docker-scripts layers -t jboss/wildfly:squashed
    511136ea3c5a64f264b78b5433614aec563103b4d4702f3ba7d4d2698e22c158
     └─ 782cf93a8f16d3016dae352188cd5cfedb6a15c37d4dbd704399f02d1bb89dab
      └─ 7d3f07f8de5fb3a20c6cb1e4447773a5741e3641c1aa093366eaa0fc690c6417
       └─ 1ef0a50fe8b1394d3626a7624a58b58cff9560ddb503743099a56bbe95ab481a
        └─ 20a1abe1d9bfb9b1e46d5411abd5a38b6104a323b7c4fb5c0f1f161b8f7278c2
         └─ cd5bb934bb6755e910d19ac3ae4cfd09221aa2f98c3fbb51a7486991364dc1ae
          └─ 379edb00ab0764276787ea777243990da697f2f93acb5d9166ff73ad01511a87
           └─ 4d37cbbfc67dd508e682a5431a99d8c1feba1bd8352ffd3ea794463d9cfa81cc
            └─ 2ea8562cac7c25a308b4565b66d4f7e11a1d2137a599ef2b32ed23c78f0a0378 [u'docker.io/jboss/base:latest']
             └─ b7e845026f73f67ebeb59ed1958d021aa79c069145d66b1233b7e9ba9fffa729 [u'jboss/wildfly:squashed']

