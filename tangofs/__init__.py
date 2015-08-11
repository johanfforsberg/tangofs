import logging
import optparse

from fuse import FUSE

from tangofs import TangoFS


def main():

    parser = optparse.OptionParser()
    parser.add_option("-v", "--verbose", help="Print debug info",
                      action="store_true", default=False)
    parser.add_option("-f", "--foreground", help="Don't daemonize",
                      action="store_true", default=False)
    options, arguments = parser.parse_args()

    if options.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.basicConfig()

    FUSE(TangoFS(), arguments[0], foreground=options.foreground,
         nothreads=False)
