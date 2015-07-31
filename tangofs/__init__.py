import StringIO
import logging
import os
import stat
from errno import ENOENT
from time import time

from datetime import datetime
from tangodict import ClassDict, DeviceAttribute, DeviceCommand, DeviceDict, \
    DeviceProperty, InstanceDict, PropertiesDict, TangoDict

import PyTango
from dateutil import parser
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations


# load the command script template
with open("/".join(__path__) + "/command.py") as f:
    EXE = f.read()


def unix_time(dt):
    epoch = datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return delta.total_seconds()


class TangoFS(LoggingMixIn, Operations):

    def __init__(self):
        self.tree = TangoDict()
        self.tmp = {}

    def _get_path(self, path):
        # decode device slashes
        p = [str(part.replace("%", "/")) for part in path[1:].split("/")]
        target = self.tree.get_path(p)
        return target

    @staticmethod
    def make_node(mode, size=0, timestamp=None):
        # TODO: find something meaningful to do with all this
        timestamp = timestamp or time()
        return {
            'st_mode': mode,
            'st_ino': 0,
            'st_dev': 0,
            'st_nlink': 1,
            'st_uid': os.getuid(),  # file object's user id
            'st_gid': os.getgid(),  # file object's group id
            'st_size': size,
            'st_atime': timestamp,  # last access time in seconds
            'st_mtime': timestamp,  # last modified time in seconds
            'st_ctime': timestamp,
            # st_blocks is the amount of blocks of the file object, and
            # depends on the block size of the file system (here: 512
            # Bytes)
            'st_blocks': int((size + 511) / 512)
        }

    # # #  FUSE API  # # #

    def getattr(self, path, fh=None):
        "getattr gets run all the time"

        try:
            # Firs check if the path is directly accessible
            target = self._get_path(path)
        except (KeyError, TypeError):
            try:
                # Attribute access needs special treatment
                parent, child = path.rsplit("/", 1)
                target = self._get_path(parent)
                if isinstance(target, DeviceAttribute):
                    # Note: This is inefficient since we'll read the attribute twice.
                    # Once here to get the size, and once in read()
                    size = len(str(getattr(target, child))) + 1  # to add newline
                else:
                    size = 0
                mode = stat.S_IFREG
                return self.make_node(mode=mode, size=size)
            except KeyError:
                # OK, what we're looking for is not in the DB. Let's
                # check if there is any pending creation operations going
                # on
                try:
                    placeholder = self.tmp.pop(path)
                    if placeholder == "PROPERTY":
                        # This means the user is creating something
                        return self.make_node(mode=stat.S_IFREG)
                    # ... other types of pending operations ...
                    else:
                        print "This can't happen..?!"
                except KeyError:
                    raise FuseOSError(ENOENT)

        # properties correspond to files
        if type(target) == DeviceProperty:
            # use last history date as timestamp
            timestamp = parser.parse(target.history[-1].get_date())
            return self.make_node(
                mode=stat.S_IFREG, timestamp=unix_time(timestamp),
                size=len("\n".join(target.value)) + 1)
        elif isinstance(target, DeviceCommand):
            # TODO: use the real size
            return self.make_node(mode=stat.S_IFREG | 755, size=1000)
        # If the device is exported, mark the node as executable
        elif isinstance(target, DeviceDict):
            # these timestamp formats are completely made up, but
            # hopefully the dateutils parser will hold together...
            timestamp = parser.parse(target.info.started_date)
            mode = stat.S_IFDIR
            if target.info and target.info.exported:
                # If the device is exported, mark the node as executable
                mode |= 777
            return self.make_node(mode=mode, timestamp=unix_time(timestamp))
        # otherwise show it as a directory
        else:
            return self.make_node(mode=stat.S_IFDIR, size=0)

    def readdir(self, path, fh):
        print "readdir", path
        try:
            target = self._get_path(path)
        except PyTango.DevFailed:
            return None
        # Since slashes are not allowed in file names, we encode
        # them as percent signs (%) to sanitize device names
        nodes = [name.replace("/", "%") for name in target.keys()]
        if isinstance(target, DeviceDict):
            nodes.append(".info")
        if isinstance(target, PropertiesDict):
            nodes.extend([node + ".history" for node in nodes])
        return [".", ".."] + nodes

    def mkdir(self, path, mode):
        print "mkdir", path, mode
        parent, name = path.rsplit("/", 1)
        target = self._get_path(parent)
        if isinstance(target, ClassDict):  # creating a device
            target.add([name.replace("%", "/")])

    def read(self, path, size, offset, fh):
        print "read", path, size, offset
        try:
            target = self._get_path(path)
        except KeyError:
            print "no such path", path
            raise FuseOSError(ENOENT)
        except TypeError:  # ugh
            parent, child = path.rsplit("/", 1)
            target = self._get_path(parent)
            if isinstance(target, DeviceAttribute):
                return str(getattr(target, child)) + "\n"
        if isinstance(target, DeviceCommand):
            return EXE.format(device=target.devicename, command=target.name)
        if isinstance(target, DeviceProperty):
            return "\n".join(target.value) + "\n"

    def write(self, path, data, offset, fh):
        "Write data to a file"
        print "write", path, offset, fh
        # TODO: currently we just overwrite, figure out append
        try:
            target = self._get_path(path)
        except KeyError:
            parent, prop = path.rsplit("/", 1)
            target = self._get_path(parent)
            if isinstance(target, PropertiesDict):
                # creating a new property
                target.add({str(prop): data.split()})
        if isinstance(target, DeviceProperty):
            if offset:
                olddata = "\n".join(target.value) + "\n"
                newdata = (olddata[:offset] + data +
                           olddata[offset + len(data):])
                target.set_value(newdata.split())
            else:
                target.set_value(data.split())

        return len(data)  # ?

    def create(self, path, mode, fi=None):
        print "create", path, mode, fi
        # In order to create properties we need to temporarily
        # remember them. Otherwise getattr will fail. We could
        # first create an empty property I guess, but that would
        # be inefficient. This feels a bit hacky, though...
        self.tmp[path] = "PROPERTY"
        return 0

    def unlink(self, path):
        # remove a file
        print "unlink", path
        target = self._get_path(path)
        if isinstance(target, DeviceProperty):
            target.delete()

    def rmdir(self, path):
        """Removing a directory should delete the corresponding
        thing in the DB, e.g. a device"""
        # TODO: how do we handle non-empty things? Should it
        # even be possible to remove a server with more than
        # one instance inside? How do we handle things that are
        # running; write protect them?
        target = self._get_path(path)
        if isinstance(target, (InstanceDict, DeviceDict)):
            target.delete()

    def truncate(self, path, length, fh=None):
        # I don't think this will be very useful..?
        pass

    def open(self, path, flags):
        print "open", path, flags
        # TODO: figure out how appending works.
        # It must be a set of flags. Then we need to
        # somehow save the fact that we're appending
        # and not overwriting...

        # TODO: "ls something" always works regardless
        # of the existence of "something". Open() is the only
        # thing that gets called. I guess we need to check
        # existance if flags are not writing, but what to
        # return?

        return flags

    def flush(self, path, fh):
        print "flush", path

    def fsync(self, path, fdatasync, fh):
        print "fsync", path, fdatasync

    def release(self, path, flags):
        print "release", path, flags


def main(mountpoint):
    logging.getLogger().setLevel(logging.DEBUG)
    FUSE(TangoFS(), mountpoint, foreground=True, nothreads=False)
