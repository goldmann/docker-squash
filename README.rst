``docker-squash``
==================

.. image:: https://circleci.com/gh/goldmann/docker-squash.svg?style=svg
    :target: https://circleci.com/gh/goldmann/docker-squash

.. image:: https://landscape.io/github/goldmann/docker-squash/master/landscape.svg?style=flat
   :target: https://landscape.io/github/goldmann/docker-squash/master

.. image:: https://badges.gitter.im/Join%20Chat.svg
   :target: https://gitter.im/goldmann/docker-squash

The problem
-----------

Docker creates many layers while building the image. Sometimes it's not necessary or desireable
to have them in the image. For example a Dockerfile `ADD` instruction creates a single layer
with files you want to make available in the image. The problem arises when these files are
only temporary files (for example product distribution that you want to unpack). Docker will
carry this unnecessary layer always with the image, even if you delete these files in next
layer. This a waste of time (more data to push/load/save) and resources (bigger image).

Squashing helps with organizing images in logical layers. Instead of
having an image with multiple (in almost all cases) unnecessary layers -
we can control the structure of the image.

Features
--------

- Can squash last n layers from an image
- Can squash from a selected layer to the end (not always possible, depends on the image)
- Support for Docker 1.9 or newer (older releases may run perfectly fine too, try it!)
- Squashed image can be loaded back to the Docker daemon or stored as tar archive somewhere

Installation
------------

From source code

::

    $ pip install --user https://github.com/goldmann/docker-squash/archive/master.zip

From PyPi

::

    $ pip install docker-squash

Usage
-----

::

    $ docker-squash -h
    usage: cli.py [-h] [-v] [--version] [-d] [-f FROM_LAYER] [-t TAG]
                  [--tmp-dir TMP_DIR] [--output-path OUTPUT_PATH]
                  image

    Docker layer squashing tool

    positional arguments:
      image                 Image to be squashed

    optional arguments:
      -h, --help            show this help message and exit
      -v, --verbose         Verbose output
      --version             Show version and exit
      -d, --development     Does not clean up after failure for easier debugging
      -f FROM_LAYER, --from-layer FROM_LAYER
                            ID of the layer or image ID or image name. If not
                            specified will squash all layers in the image
      -t TAG, --tag TAG     Specify the tag to be used for the new image. By
                            default it'll be set to 'image' argument
      --tmp-dir TMP_DIR     Temporary directory to be used
      --output-path OUTPUT_PATH
                            Path where the image should be stored after squashing.
                            If not provided, image will be loaded into Docker
                            daemon

License
-------

MIT

Examples
--------

We start with image like this:

::

    $ docker history jboss/wildfly:latest
    IMAGE               CREATED             CREATED BY                                      SIZE                COMMENT
    25954e6d2300        3 weeks ago         /bin/sh -c #(nop) CMD ["/opt/jboss/wildfly/bi   0 B                 
    5ae69cb454a5        3 weeks ago         /bin/sh -c #(nop) EXPOSE 8080/tcp               0 B                 
    dc24712f35c4        3 weeks ago         /bin/sh -c #(nop) ENV LAUNCH_JBOSS_IN_BACKGRO   0 B                 
    d929129d4c8e        3 weeks ago         /bin/sh -c cd $HOME     && curl -O https://do   160.8 MB            
    b8fa3caf7d6d        3 weeks ago         /bin/sh -c #(nop) ENV JBOSS_HOME=/opt/jboss/w   0 B                 
    38b8f85e74bf        3 weeks ago         /bin/sh -c #(nop) ENV WILDFLY_SHA1=c0dd7552c5   0 B                 
    ae79b646b9a9        3 weeks ago         /bin/sh -c #(nop) ENV WILDFLY_VERSION=10.0.0.   0 B                 
    2b4606dc9dc7        3 weeks ago         /bin/sh -c #(nop) ENV JAVA_HOME=/usr/lib/jvm/   0 B                 
    118fa9e33576        3 weeks ago         /bin/sh -c #(nop) USER [jboss]                  0 B                 
    5f7e8f36c3bb        3 weeks ago         /bin/sh -c yum -y install java-1.8.0-openjdk-   197.4 MB            
    3d4d0228f161        3 weeks ago         /bin/sh -c #(nop) USER [root]                   0 B                 
    f7ab4ea19708        3 weeks ago         /bin/sh -c #(nop) MAINTAINER Marek Goldmann <   0 B                 
    4bb15f3b6977        3 weeks ago         /bin/sh -c #(nop) USER [jboss]                  0 B                 
    5dc1e49f4361        3 weeks ago         /bin/sh -c #(nop) WORKDIR /opt/jboss            0 B                 
    7f0f9eb31174        3 weeks ago         /bin/sh -c groupadd -r jboss -g 1000 && usera   4.349 kB            
    bd515f044af7        3 weeks ago         /bin/sh -c yum update -y && yum -y install xm   25.18 MB            
    b78336099045        3 weeks ago         /bin/sh -c #(nop) MAINTAINER Marek Goldmann <   0 B                 
    4816a298548c        3 weeks ago         /bin/sh -c #(nop) CMD ["/bin/bash"]             0 B                 
    6ee235cf4473        3 weeks ago         /bin/sh -c #(nop) LABEL name=CentOS Base Imag   0 B                 
    474c2ee77fa3        3 weeks ago         /bin/sh -c #(nop) ADD file:72852fc7626d233343   196.6 MB            
    1544084fad81        6 months ago        /bin/sh -c #(nop) MAINTAINER The CentOS Proje   0 B

And we want to squash all the layers down to layer ``4bb15f3b6977``.

::

    $ docker-squash -f 4bb15f3b6977 -t jboss/wildfly:squashed jboss/wildfly:latest
    2016-04-01 13:11:02,358 root         INFO     docker-scripts version 1.0.0dev, Docker 7206621, API 1.21...
    2016-04-01 13:11:02,358 root         INFO     Using v1 image format
    2016-04-01 13:11:02,374 root         INFO     Old image has 21 layers
    2016-04-01 13:11:02,378 root         INFO     Checking if squashing is necessary...
    2016-04-01 13:11:02,378 root         INFO     Attempting to squash last 12 layers...
    2016-04-01 13:11:02,378 root         INFO     Saving image 25954e6d230006235eecb7f0cc560264d73146985c2d2e663bac953d660b8730 to /tmp/docker-squash-fbxZz4/old/image.tar file...
    2016-04-01 13:11:08,003 root         INFO     Image saved!
    2016-04-01 13:11:08,031 root         INFO     Unpacking /tmp/docker-squash-fbxZz4/old/image.tar tar file to /tmp/docker-squash-fbxZz4/old directory
    2016-04-01 13:11:08,588 root         INFO     Archive unpacked!
    2016-04-01 13:11:08,636 root         INFO     Squashing image 'jboss/wildfly:latest'...
    2016-04-01 13:11:08,637 root         INFO     Starting squashing...
    2016-04-01 13:11:08,637 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/25954e6d230006235eecb7f0cc560264d73146985c2d2e663bac953d660b8730/layer.tar'...
    2016-04-01 13:11:08,637 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/5ae69cb454a5a542f63e148ce40fb9e01de5bb01805b4ded238841bc2ce8e895/layer.tar'...
    2016-04-01 13:11:08,637 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/dc24712f35c40e958be8aca2731e7bf8353b9b18baa6a94ad84c6952cbc77004/layer.tar'...
    2016-04-01 13:11:08,638 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/d929129d4c8e61ea3661eb42c30d01f4c152418689178afc7dc8185a37814528/layer.tar'...
    2016-04-01 13:11:09,113 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/b8fa3caf7d6dc228bf2499a3af86e5073ad0c17304c3900fa341e9d2fe4e5655/layer.tar'...
    2016-04-01 13:11:09,115 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/38b8f85e74bfa773a0ad69da2205dc0148945e6f5a7ceb04fa4e8619e1de425b/layer.tar'...
    2016-04-01 13:11:09,115 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/ae79b646b9a9a287c5f6a01871cc9d9ee596dafee2db942714ca3dea0c06eef3/layer.tar'...
    2016-04-01 13:11:09,115 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/2b4606dc9dc773aa220a65351fe8d54f03534c58fea230960e95915222366074/layer.tar'...
    2016-04-01 13:11:09,115 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/118fa9e33576ecc625ebbbfdf2809c1527e716cb4fd5cb40548eb6d3503a75a9/layer.tar'...
    2016-04-01 13:11:09,115 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/5f7e8f36c3bb20c9db7470a22f828710b4d28aede64966c425add48a1b14fe23/layer.tar'...
    2016-04-01 13:11:10,127 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/3d4d0228f161b67eb46fdb425ad148c31d9944dcb822f67eac3e2ac2effefc73/layer.tar'...
    2016-04-01 13:11:10,129 root         INFO     Squashing file '/tmp/docker-squash-fbxZz4/old/f7ab4ea197084ab7483a2ca5409bdcf5473141bfb61b8687b1329943359cc3fe/layer.tar'...
    2016-04-01 13:11:10,732 root         INFO     Squashing finished!
    2016-04-01 13:11:10,737 root         INFO     New squashed image ID is 52255e75d3eb83123e074f897e8c971dec9d1168a5c82d7c1496a190da2e40ef
    2016-04-01 13:11:14,563 root         INFO     Image registered in Docker daemon as jboss/wildfly:squashed
    2016-04-01 13:11:14,652 root         INFO     Done

We can now confirm the layer structure:

::

    $ docker history jboss/wildfly:squashed
    IMAGE               CREATED             CREATED BY                                      SIZE                COMMENT
    52255e75d3eb        40 seconds ago                                                      358.2 MB            
    4bb15f3b6977        3 weeks ago         /bin/sh -c #(nop) USER [jboss]                  0 B                 
    5dc1e49f4361        3 weeks ago         /bin/sh -c #(nop) WORKDIR /opt/jboss            0 B                 
    7f0f9eb31174        3 weeks ago         /bin/sh -c groupadd -r jboss -g 1000 && usera   4.349 kB            
    bd515f044af7        3 weeks ago         /bin/sh -c yum update -y && yum -y install xm   25.18 MB            
    b78336099045        3 weeks ago         /bin/sh -c #(nop) MAINTAINER Marek Goldmann <   0 B                 
    4816a298548c        3 weeks ago         /bin/sh -c #(nop) CMD ["/bin/bash"]             0 B                 
    6ee235cf4473        3 weeks ago         /bin/sh -c #(nop) LABEL name=CentOS Base Imag   0 B                 
    474c2ee77fa3        3 weeks ago         /bin/sh -c #(nop) ADD file:72852fc7626d233343   196.6 MB            
    1544084fad81        6 months ago        /bin/sh -c #(nop) MAINTAINER The CentOS Proje   0 B

Other option is to specify how many layers (counting from the newest layer) we want to squash.\
Let's squash last 10 layers from the ``jboss/wildfly:latest`` image:

::

    $ docker-squash -f 10 -t jboss/wildfly:squashed jboss/wildfly:latest
    2016-04-01 13:15:06,488 root         INFO     docker-scripts version 1.0.0dev, Docker 7206621, API 1.21...
    2016-04-01 13:15:06,488 root         INFO     Using v1 image format
    2016-04-01 13:15:06,504 root         INFO     Old image has 21 layers
    2016-04-01 13:15:06,504 root         INFO     Checking if squashing is necessary...
    2016-04-01 13:15:06,504 root         INFO     Attempting to squash last 10 layers...
    2016-04-01 13:15:06,505 root         INFO     Saving image 25954e6d230006235eecb7f0cc560264d73146985c2d2e663bac953d660b8730 to /tmp/docker-squash-fu80CX/old/image.tar file...
    2016-04-01 13:15:12,136 root         INFO     Image saved!
    2016-04-01 13:15:12,167 root         INFO     Unpacking /tmp/docker-squash-fu80CX/old/image.tar tar file to /tmp/docker-squash-fu80CX/old directory
    2016-04-01 13:15:12,706 root         INFO     Archive unpacked!
    2016-04-01 13:15:12,756 root         INFO     Squashing image 'jboss/wildfly:latest'...
    2016-04-01 13:15:12,756 root         INFO     Starting squashing...
    2016-04-01 13:15:12,756 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/25954e6d230006235eecb7f0cc560264d73146985c2d2e663bac953d660b8730/layer.tar'...
    2016-04-01 13:15:12,757 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/5ae69cb454a5a542f63e148ce40fb9e01de5bb01805b4ded238841bc2ce8e895/layer.tar'...
    2016-04-01 13:15:12,757 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/dc24712f35c40e958be8aca2731e7bf8353b9b18baa6a94ad84c6952cbc77004/layer.tar'...
    2016-04-01 13:15:12,757 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/d929129d4c8e61ea3661eb42c30d01f4c152418689178afc7dc8185a37814528/layer.tar'...
    2016-04-01 13:15:13,234 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/b8fa3caf7d6dc228bf2499a3af86e5073ad0c17304c3900fa341e9d2fe4e5655/layer.tar'...
    2016-04-01 13:15:13,235 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/38b8f85e74bfa773a0ad69da2205dc0148945e6f5a7ceb04fa4e8619e1de425b/layer.tar'...
    2016-04-01 13:15:13,235 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/ae79b646b9a9a287c5f6a01871cc9d9ee596dafee2db942714ca3dea0c06eef3/layer.tar'...
    2016-04-01 13:15:13,235 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/2b4606dc9dc773aa220a65351fe8d54f03534c58fea230960e95915222366074/layer.tar'...
    2016-04-01 13:15:13,236 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/118fa9e33576ecc625ebbbfdf2809c1527e716cb4fd5cb40548eb6d3503a75a9/layer.tar'...
    2016-04-01 13:15:13,236 root         INFO     Squashing file '/tmp/docker-squash-fu80CX/old/5f7e8f36c3bb20c9db7470a22f828710b4d28aede64966c425add48a1b14fe23/layer.tar'...
    2016-04-01 13:15:14,848 root         INFO     Squashing finished!
    2016-04-01 13:15:14,853 root         INFO     New squashed image ID is fde7edd2e5683c97bedf9c0bf52ad5150db5650e421de3d9293ce5223b256455
    2016-04-01 13:15:18,963 root         INFO     Image registered in Docker daemon as jboss/wildfly:squashed
    2016-04-01 13:15:19,059 root         INFO     Done

Let's confirm the image structure now:

::

    $ docker history jboss/wildfly:squashed
    IMAGE               CREATED             CREATED BY                                      SIZE                COMMENT
    fde7edd2e568        32 seconds ago                                                      358.2 MB            
    3d4d0228f161        3 weeks ago         /bin/sh -c #(nop) USER [root]                   0 B                 
    f7ab4ea19708        3 weeks ago         /bin/sh -c #(nop) MAINTAINER Marek Goldmann <   0 B                 
    4bb15f3b6977        3 weeks ago         /bin/sh -c #(nop) USER [jboss]                  0 B                 
    5dc1e49f4361        3 weeks ago         /bin/sh -c #(nop) WORKDIR /opt/jboss            0 B                 
    7f0f9eb31174        3 weeks ago         /bin/sh -c groupadd -r jboss -g 1000 && usera   4.349 kB            
    bd515f044af7        3 weeks ago         /bin/sh -c yum update -y && yum -y install xm   25.18 MB            
    b78336099045        3 weeks ago         /bin/sh -c #(nop) MAINTAINER Marek Goldmann <   0 B                 
    4816a298548c        3 weeks ago         /bin/sh -c #(nop) CMD ["/bin/bash"]             0 B                 
    6ee235cf4473        3 weeks ago         /bin/sh -c #(nop) LABEL name=CentOS Base Imag   0 B                 
    474c2ee77fa3        3 weeks ago         /bin/sh -c #(nop) ADD file:72852fc7626d233343   196.6 MB            
    1544084fad81        6 months ago        /bin/sh -c #(nop) MAINTAINER The CentOS Proje   0 B

