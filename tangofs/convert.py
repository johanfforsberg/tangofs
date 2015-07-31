import PyTango


def make_tango_type(ttype, string):
    """Convert the given string into a python value compatible with
    the given Tango type"""

    if PyTango.is_str_type(ttype):
        return str(string)
    if PyTango.is_float_type(ttype):
        return float(string)
    if PyTango.is_int_type(ttype):
        return int(string)
    if PyTango.is_bool_type(ttype):
        return bool(string)

    # TODO: cover array, image types...
