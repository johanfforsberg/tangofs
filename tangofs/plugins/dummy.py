"""This is a dummy plugin intended as an example"""


def check(info, value):
    """Gets an AttributeInfo object and value, and should return True if
    the plugin thinks it is able to handle the attribute."""
    return False


def convert(value):
    """This function takes a Tango DeviceAttribute object and returns
    a string (or bytes) which will be the contents of the file."""
    return str(value)
