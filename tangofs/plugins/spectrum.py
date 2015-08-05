import PyTango

# The spec should constrain what attributes the plugin can handle.
# Only included fields are tested, absent fields are treated as automatic
# matches.
# Currently only the "data_format" and "data_type" fields are checked.
spec = {
    "name": "spectrum",
    "data_format": PyTango.AttrDataFormat.SPECTRUM,
}


def convert(value):
    """This function takes a Tango DeviceAttribute object and returns
    a string or bytes."""
    return "\n".join(str(v) for v in value) + "\n"
