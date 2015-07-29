#!/usr/bin/python
"A simple script that runs {command}() on {device}"

import sys
sys.path = sys.path[1:]  # this is a HACK to prevent python from looking
                         # in PWD for modules. Find a better way.
import optparse
import PyTango


proxy = PyTango.DeviceProxy("{device}")
info = proxy.command_query("{command}")

# TODO: nicer help presentation
USAGE = str(info)
parser = optparse.OptionParser(usage=USAGE)
options, args = parser.parse_args()

# TODO: handle arguments
result = proxy.{command}()
if result is not None:
    print result
