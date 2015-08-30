#!/usr/bin/python
"A simple script that runs {command}() on {device}"

import sys
sys.path = sys.path[1:]  # this is a HACK to prevent python from looking
                         # in the cirectory for modules. Find a better way!
import optparse
import PyTango


proxy = PyTango.DeviceProxy("{device}")
info = proxy.command_query("{command}")

def format_usage(info):
    usage = "{command}"
    if info.in_type == PyTango._PyTango.CmdArgType.DevVoid:
        return usage
    else:
        return usage + " " + str(info.in_type)

def format_description(info):
    # TODO: formatting isn't great, optparse messes with the newlines.
    desc = ["Run the command '{command}' on the device '{device}'."]
    if info.in_type_desc != "Uninitialised":
        desc.append("Input: %s." % info.in_type_desc)
    if info.out_type_desc != "Uninitialised":
        desc.append("Output: %s." % info.out_type_desc)
    return "\n".join(desc)


parser = optparse.OptionParser(usage=format_usage(info),
                               description=format_description(info))

parser.add_option("-t", "--timeout", dest="timeout", default=3.0, type="float",
                  help="Adjust the timeout for the command (in seconds)")
parser.add_option("-f", "--forget", dest="forget", default=False,
                  action="store_true",
                  help="Ignore the result, return immediately")
options, args = parser.parse_args()

# Check arguments
if info.in_type == PyTango.ArgType.DevVoid:
    if not len(args) == 0:
        sys.exit("No arguments expected!")
    argument = None
else:
    if PyTango.is_scalar_type(info.in_type) and not len(args) == 1:
        sys.exit("Exactly one argument expected!")
    argument = PyTango.utils.seqStr_2_obj(args, info.in_type)


# run command
proxy.set_timeout_millis(int(options.timeout * 1000))
if options.forget:
    result = proxy.command_inout_asynch("{command}", argument, options.forget)
else:
    result = proxy.command_inout("{command}", argument)

# output
if result is not None and not options.forget:
    if PyTango.is_array_type(info.out_type):
        print "\n".join(result)
    else:
        print result
