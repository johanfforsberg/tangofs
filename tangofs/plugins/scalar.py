"A 'plugin' that handles scalar attributes by converting them to a string"

import PyTango


def check(info, _):
    return info.data_format == PyTango.AttrDataFormat.SCALAR


def convert(value):
    return str(value) + "\n"
