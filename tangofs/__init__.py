import logging
import optparse

from fuse import FUSE

from tangofs import TangoFS


def main():

    parser = optparse.OptionParser()
    options, arguments = parser.parse_args()

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # TODO: figure out how to enable logging
    FUSE(TangoFS(logger), arguments[0], foreground=True, nothreads=False)
