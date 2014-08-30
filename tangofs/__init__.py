from datetime import datetime
from errno import ENOENT
import os
import stat
from time import time

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
from tangodict import TangoDict, DeviceProperty, DeviceDict


def unix_time(dt):
    epoch = datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return delta.total_seconds()


class TangoFS(LoggingMixIn, Operations):

    def __init__(self):
        self.tree = TangoDict(ttl=10)

    def chmod(self, path, mode):
        return 0

    def _get_path(self, path):
        p = [str(part.replace("%", "/")) for part in path[1:].split("/")]
        try:
            target = self.tree.get_path(p)
            return target
        except KeyError:
            raise FuseOSError(ENOENT)

    def getattr(self, path, fh=None):
        target = self._get_path(path)

        # set timestamp to last modification for properties
        if type(target) == DeviceProperty:
            mode = stat.S_IFREG
            last_mod = datetime.strptime(target._history[-1].get_date(), "%d/%m/%Y %H:%M:%S")
            now = unix_time(last_mod)
        else:
            mode = stat.S_IFDIR
            now = time()

        # If the device is exported, mark the node as executable
        if type(target) == DeviceDict:
            if target.info.exported:
                mode |= 0111
                try:
                    # these timestamp formats are completely made up :(
                    started = datetime.strptime(target.info.started_date.lower(), "%dth %B %Y at %H:%M:%S")
                    now = unix_time(started)
                except ValueError:
                    print "could not parse", target.info.started_date

        size = len("\n".join(target.value)) if type(target) == DeviceProperty else 0
        st = {}
        st['st_mode']   = mode
        st['st_ino']    = 0
        st['st_dev']    = 0
        st['st_nlink']  = 1
        st['st_uid']    = os.getuid() #file object's user id
        st['st_gid']    = os.getgid() #file object's group id
        st['st_size']   = size
        st['st_atime']  = now  #last access time in seconds
        st['st_mtime']  = now  #last modified time in seconds
        st['st_ctime']  = now
        #st_blocks is the amount of blocks of the file object, and
        #depends on the block size of the file system (here: 512
        #Bytes)
        st['st_blocks'] = (int) ((st['st_size'] + 511) / 512)
        return st

    def readdir(self, path, fh):
        target = self._get_path(path)
        return [".", ".."] + [name.encode('utf-8').replace("/", "%") for name in target]

    def read(self, path, size, offset, fh):
        target = self._get_path(path)
        return "\n".join(target.value)


def main(directory):
    FUSE(TangoFS(), directory, foreground=True, nothreads=True)


if __name__ == '__main__':
    import sys
    main(sys.argv[1])
