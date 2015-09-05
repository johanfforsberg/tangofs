"A 'plugin' that handles image attributes by converting them to a picture"


import io

import PyTango
from scipy.misc import toimage


def check(info, data):
    return info.data_format == PyTango.AttrDataFormat.IMAGE


def convert(value):
    "Convert an IMAGE type value into a PNG image"
    img = toimage(value)
    with io.BytesIO() as s:
        img.save(s, format="PNG")
        image = s.getvalue()
    return image
