from datetime import datetime
from errno import ENOENT
import os
import stat
from time import time
from dateutil import parser
import tempfile

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
from tangodict import TangoDict, DeviceProperty, DeviceDict
import PyTango


def unix_time(dt):
    epoch = datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return delta.total_seconds()


class TangoFS(LoggingMixIn, Operations):

    def __init__(self):
        self.tree = TangoDict(ttl=10)

    def _get_path(self, path):
        # decode device slashes
        p = [str(part.replace("%", "/")) for part in path[1:].split("/")]
        try:
            target = self.tree.get_path(p)
            return target
        except KeyError:
            raise FuseOSError(ENOENT)

    def getattr(self, path, fh=None):

        target = self._get_path(path)

        # show properties as files
        if type(target) == DeviceProperty:
            mode = stat.S_IFREG
            # these timestamp formats are completely made up, but
            # hopefully the dateutils parser will hold together...
            last_mod = parser.parse(target.history[-1].get_date())
            now = unix_time(last_mod)
            size = len("\n".join(target.value))
        # otherwise show it as a directory
        else:
            mode = stat.S_IFDIR
            now = time()
            size = 0

        # If the device is exported, mark the node as executable
        if type(target) == DeviceDict:
            if target.info.exported:
                mode |= 0111
                started = parser.parse(target.info.started_date)
                now = unix_time(started)

        mode |= 0755

        # TODO: find something meaningful to do with all this
        return {
            'st_mode': mode,
            'st_ino': 0,
            'st_dev': 0,
            'st_nlink': 1,
            'st_uid': os.getuid(),  # file object's user id
            'st_gid': os.getgid(),  # file object's group id
            'st_size': size,
            'st_atime': now,  # last access time in seconds
            'st_mtime': now,  # last modified time in seconds
            'st_ctime': now,
            # st_blocks is the amount of blocks of the file object, and
            # depends on the block size of the file system (here: 512
            # Bytes)
            'st_blocks': int((size + 511) / 512)
        }

    def readdir(self, path, fh):
        try:
            target = self._get_path(path)
        except PyTango.DevFailed:
            return None
        # Since slashes are not allowed in file names, we encode
        # them as percent signs (%)
        nodes = [".", ".."] + [name.replace("/", "%")
                               for name in target.keys()]
        if isinstance(target, DeviceDict):
            nodes.append(".info")
        return nodes

    def read(self, path, size, offset, fh):
        subpath, nodename = path.rsplit("/", 1)
        target = self._get_path(path)
        return "\n".join(target.value)

    def write(self, path, buf, offset, fh):
        print path, buf, offset, fh
        return 100

    def create(self, path, mode, fi=None):
        return 0

    def open(self, path, flags):
        print path, flags
        subpath, nodename = path.rsplit("/", 1)
        target = self._get_path(path)
        tf = tempfile.NamedTemporaryFile()
        tf.writelines(target.value)
        return 0


def main(directory):
    FUSE(TangoFS(), directory, foreground=True, nothreads=True)


if __name__ == '__main__':
    import sys
    main(sys.argv[1])
