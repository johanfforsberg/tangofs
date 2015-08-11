"A 'plugin' that handles spectrum attributes by converting them to a string"


import PyTango


def check(info, data):
    """Gets an AttributeInfo object and data, and should return True if
    the plugin thinks it is able to handle the attribute data."""
    return info.data_format == PyTango.AttrDataFormat.SPECTRUM


def convert(value):
    """This function takes a Tango DeviceAttribute object and returns
    a string or bytes."""
    return "\n".join(str(v) for v in value) + "\n"
