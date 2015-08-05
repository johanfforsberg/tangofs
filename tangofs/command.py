#!/usr/bin/python
"A simple script that runs {command}() on {device}"

import sys
sys.path = sys.path[1:]  # this is a HACK to prevent python from looking
                         # in PWD for modules. Find a better way.
import optparse
import PyTango


proxy = PyTango.DeviceProxy("{device}")
info = proxy.command_query("{command}")

USAGE = str(info)  # TODO: nicer help presentation
parser = optparse.OptionParser(usage=USAGE)
parser.add_option("-t", "--timeout", dest="timeout", default=3, type="int",
                  help="Adjust the timeout for the command (in seconds)")
parser.add_option("-f", "--forget", dest="forget", default=False,
                  action="store_true", help="Ignore the result")
options, args = parser.parse_args()

# Check arguments
if info.in_type == PyTango.ArgType.DevVoid:
    if not len(args) == 0:
        sys.exit("No arguments allowed!")
    argument = None
elif PyTango.is_scalar_type(info.in_type):
    if not len(args) == 1:
        sys.exit("Exactly one argument must be given!")
    argument = PyTango.utils.seqStr_2_obj(args, info.in_type)
else:
    argument = PyTango.utils.seqStr_2_obj(args, info.in_type)

# run command
proxy.set_timeout_millis(int(options.timeout * 1000))
if options.forget:
    result = proxy.command_inout_asynch("{command}", argument, options.forget)
else:
    result = proxy.command_inout("{command}", argument)

# output
if not options.forget and result is not None:
    if PyTango.is_array_type(info.out_type):
        print "\n".join(result)
    else:
        print result
