import PyTango

# The spec should constrain what attributes the plugin can handle.
# Currently only the "data_format" and "data_type" fields are checked.
spec = {
    "name": "scalar",
    "data_format": PyTango.AttrDataFormat.SCALAR,
}


def convert(value):
    """This function takes a Tango DeviceAttribute object and returns
    a string or bytes."""
    return str(value) + "\n"
