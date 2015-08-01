import logging
import os
import re
import stat
from errno import ENOENT
from time import time

from convert import make_tango_type
from datetime import datetime
from tangodict import ClassDict, DeviceAttribute, DeviceCommand, DeviceDict, \
    DeviceProperty, InstanceDict, PropertiesDict, TangoDict, ServerDict

import PyTango
from dateutil import parser
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations


# load the command script template
with open("/".join(__path__) + "/command.py") as f:
    EXE = f.read()


# This is a bit of a hack, to allow sed to write temporary files
# Not sure if this is a good idea... but sed -i is so convenient
SEDTMP = re.compile("sed\w{6}")

# constants
PROPERTY = 0


def unix_time(dt):
    epoch = datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return delta.total_seconds()


class TangoFS(LoggingMixIn, Operations):

    def __init__(self, logger=None):
        self.tree = TangoDict(logger=logger)  # Tango interaction layer
        self.tmp = {}  # for keeping track of temporary stuff "in flight"

    def _get_path(self, path):
        # decode device slashes
        p = [str(part.replace("%", "/")) for part in path[1:].split("/")]
        target = self.tree.get_path(p)
        return target

    @staticmethod
    def make_node(mode, size=0, timestamp=None):
        # TODO: find out the meaning of all this and use it for something
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
            'st_ctime': timestamp,  # creation time?
            # st_blocks is the amount of blocks of the file object, and
            # depends on the block size of the file system (here: 512
            # Bytes)
            'st_blocks': int((size + 511) / 512)
        }

    # # #  Filesystem API  # # #

    def getattr(self, path, fh=None):
        "getattr gets run all the time"
        print "getattr", path, fh
        try:
            # Firs check if the path is directly accessible
            target = self._get_path(path)
        except (KeyError, TypeError):
            try:
                # Attribute access needs special treatment
                parent, child = path.rsplit("/", 1)
                target = self._get_path(parent)
                if isinstance(target, DeviceAttribute):
                    # store the value in tmp so we don't have to read it
                    # again in the read method. This is all supposed to be
                    # an atomic operation, right?
                    value = self.tmp[path] = str(getattr(target, child)) + "\n"
                    size = len(value)
                    mode = stat.S_IFREG
                    return self.make_node(mode=mode, size=size)
                # OK, what we're looking for is not in the DB. Let's
                # check if there is any pending creation operations going
                # on
                elif path in self.tmp:
                    if self.tmp[path] == PROPERTY:
                        # This means the user is creating a property
                        del self.tmp[path]
                    # ... insert other types of pending operations ...
                    return self.make_node(mode=stat.S_IFREG)
                else:
                    # none
                    raise FuseOSError(ENOENT)
            except KeyError:
                raise FuseOSError(ENOENT)

        # properties correspond to files
        if type(target) == DeviceProperty:
            # use last history date as timestamp
            value = self.tmp[path] = "\n".join(target.value) + "\n"
            #timestamp = parser.parse(target.history[-1].get_date())
            return self.make_node(
                mode=stat.S_IFREG,  # timestamp=unix_time(timestamp),
                size=len(value))
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
        # if isinstance(target, PropertiesDict):
        #     nodes.extend([node + ".history" for node in nodes])
        return [".", ".."] + nodes

    def mkdir(self, path, mode):
        print "mkdir", path, mode
        parent, name = path.rsplit("/", 1)
        target = self._get_path(parent)
        if isinstance(target, ClassDict):  # creating a device
            target.add([name.replace("%", "/")])

    def read(self, path, size, offset, fh):
        print "read", path, size, offset
        if path in self.tmp:
            return self.tmp.pop(path)
        try:
            target = self._get_path(path)
        except KeyError:
            raise FuseOSError(ENOENT)
        except TypeError:  # ugh
            parent, child = path.rsplit("/", 1)
            target = self._get_path(parent)
            if isinstance(target, DeviceAttribute):
                # really we should never get here... the value should
                # always be in tmp since self.getattr()
                return str(getattr(target, child)) + "\n"
        if isinstance(target, DeviceCommand):
            return EXE.format(device=target.devicename, command=target.name)
        if isinstance(target, DeviceProperty):
            return "\n".join(target.value) + "\n"

    def write(self, path, data, offset, fh):
        "Write data to a file"
        print "write", path, data, offset, fh
        try:
            target = self._get_path(path)
        except KeyError:
            # writing to somethin
            parent, prop = os.path.split(path)
            target = self._get_path(parent)
            if isinstance(target, PropertiesDict):
                # creating a new property
                if SEDTMP.match(prop):
                    if offset:  # change/append
                        olddata = self.tmp[path]
                        newdata = (olddata[:offset] + data +
                                   olddata[offset + len(data):])
                        self.tmp[path] = newdata
                    else:
                        self.tmp[path] = data
                else:
                    target.add({str(prop): data.strip().split("\n")})
        except TypeError:
            # a bit crude, but since DeviceAttribute is not a dict
            # we can't access things like e.g. ["value"]
            parent, attr = os.path.split(path)
            target = self._get_path(parent)
            if isinstance(target, DeviceAttribute):
                dtype = target.config.data_type
                try:
                    value = make_tango_type(dtype, data)
                    setattr(target, attr, value)
                    return len(data)
                except (ValueError, PyTango.DevFailed) as e:
                    print e
                    raise FuseOSError(ENOENT)
        if isinstance(target, DeviceProperty):
            if offset:
                olddata = "\n".join(target.value) + "\n"
                newdata = (olddata[:offset] + data +
                           olddata[offset + len(data):])
                target.value = newdata.strip().split("\n")
            else:
                target.value = data.strip().split("\n")

        return len(data)  # ?

    def create(self, path, mode, fi=None):
        print "create", path, mode, fi
        # In order to create properties we need to temporarily
        # remember them. Otherwise getattr will fail. We could
        # first create an empty property I guess, but that would
        # be inefficient. This feels a bit hacky, though...
        parent, child = os.path.split(path)
        if SEDTMP.match(child):
            self.tmp[path] = ""
        else:
            self.tmp[path] = PROPERTY
        return 0

    def unlink(self, path):
        # remove a file
        print "unlink", path
        self.tmp.pop(path)
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
        # I don't think this will be very useful
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

    def mknod(*args):
        print "mknod", args

    def rename(self, oldpath, newpath):
        print "rename", oldpath, newpath
        oldparent, oldchild = os.path.split(oldpath)
        newparent, newchild = os.path.split(newpath)
        if oldpath in self.tmp and SEDTMP.match(oldchild):
            # we are renaming a temporary file!
            # presumably it's created by sed
            value = self.tmp.pop(oldpath)
            if SEDTMP.match(newchild):
                self.tmp[newpath] = value
                return 0
            else:
                value = value.strip().split("\n")
                target = self._get_path(newpath)
                if isinstance(target, DeviceProperty):
                    target.value = value
        else:
            source = self._get_path(oldpath)
            if isinstance(source, (DeviceProperty, InstanceDict)):
                source.rename(str(newchild))
            else:
                # immovable object
                raise FuseOSError(ENOENT)

    def readlink(self, *args):
        # might be useful for aliases..?
        print "readlink", args

    def chmod(self, *args):
        # noop, but needs to exist to prevent errors
        print "chmod", args


def main(mountpoint):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    FUSE(TangoFS(logger), mountpoint, foreground=True, nothreads=False)
