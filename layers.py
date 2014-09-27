# -*- coding: utf-8 -*-

import sys
import subprocess
import json
import argparse

def read_layer(layers, image_id):
  try:
    output = subprocess.check_output("docker inspect %s" % image_id, shell=True, stderr=subprocess.STDOUT)
  except subprocess.CalledProcessError as e:
    print "Error while getting information about image / layer '%s'. Please make sure you specified correct information." % image_id
    sys.exit(2)
  
  metadata = json.loads(output)[0]

  layers.append(metadata)

  if 'Parent' in metadata and metadata['Parent']:
    read_layer(layers, metadata['Parent'])

def main(args):

  image_id = args.layer
  layers = []
  read_layer(layers, image_id)
  layers.reverse()

  i = 0

  for l in layers:
    command = None

    if 'ContainerConfig' in l and l['ContainerConfig'] and l['ContainerConfig']['Cmd']:
      command = " ".join(l['ContainerConfig']['Cmd'])

    if args.dockerfile:
      if not command:
        print "FROM %s" % l['Id']
      else:
        if l['ContainerConfig']['Cmd'][-1].startswith("#(nop) "):
          # TODO: special case: ADD
          # TODO: special case: EXPOSE
          print l['ContainerConfig']['Cmd'][-1].split("#(nop) ")[-1]
        else:
          print "RUN %s" % l['ContainerConfig']['Cmd'][-1]
    else:
      line = "%s" % " " * i

      if l != layers[0]:
        line += u'└─ '

      line += "%s" % l['Id']

      if args.commands:
        line += " [%s]" % command
      
      print line

    i+=1

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Print information about layers.')
  parser.add_argument('layer', help='ID of the layer or image ID or image name')
  parser.add_argument('-c', '--commands', action='store_true', help='Show commands executed to create the layer (if any)')
  parser.add_argument('-d', '--dockerfile', action='store_true', help='Create Dockerfile out of the layers [EXPERIMENTAL!]')
  args = parser.parse_args()

  main(args)
