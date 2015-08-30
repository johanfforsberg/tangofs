from errno import ENOENT, EPERM, EINVAL  # lots of meaningful errors here!
from datetime import datetime
import os
import re
import stat
from time import time

from dateutil import parser
from fuse import FuseOSError, LoggingMixIn, Operations
import PyTango

from tangodict import (ServersDict, ClassDict, DeviceAttribute, DeviceCommand,
                       DeviceDict, DeviceProperty, InstanceDict,
                       PropertiesDict, TangoDict, ServerDict,
                       AttributesDict)
from plugins import get_plugins
from . import __path__


# load the command script template
with open("/".join(__path__) + "/command.py") as f:
    EXE = f.read()


# This is a bit of a hack, to allow sed to write temporary files
# Not sure if this is a good idea... but sed -i is so convenient
SEDTMP = re.compile("sed\w{6}")

# constants
SERVER = 0
CLASS = 1
PROPERTY = 2


def unix_time(dt):
    epoch = datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return delta.total_seconds()


class TangoFS(LoggingMixIn, Operations):

    "A FUSE filsystem representing a Tango control system"

    def __init__(self):
        self.tree = TangoDict()  # Tango interaction layer
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
        # TODO: refactor, this is too messy
        try:
            # Firs check if the path is directly accessible
            target = self._get_path(path)
        except (KeyError, TypeError):
            try:
                # Attribute access needs special treatment
                parent, child = path.rsplit("/", 1)
                target = self._get_path(parent)
                if isinstance(target, DeviceAttribute):
                    # store the value in tmp so we don't have to read
                    # it again in the read method. Also, otherwise the
                    # size might be wrong.
                    if child in ("value", "w_value"):
                        data = getattr(target, child)
                        plugins = get_plugins(target.info, data)
                        value = plugins[0].convert(data)
                        # TODO: handle the case when more than one plugin
                        # matches. I guess each plugin need to give a unique
                        # file extension or something.
                    else:
                        value = str(getattr(target, child)) + "\n"
                    self.tmp[path] = value
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
                    elif self.tmp[path] == SERVER:
                        self.log.debug("wheee")
                        return self.make_node(mode=stat.S_IFDIR, size=0)
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
            # Fixme: potential performance issue, commented out for now
            #timestamp = parser.parse(target.history[-1].get_date())
            value = self.tmp[path] = "\n".join(target.value) + "\n"
            return self.make_node(
                mode=stat.S_IFREG,  # timestamp=unix_time(timestamp),
                size=len(value))

        # commands are executables
        elif isinstance(target, DeviceCommand):
            exe = self.tmp[path] = EXE.format(device=target.devicename,
                                              command=target.name)
            return self.make_node(mode=stat.S_IFREG | 755, size=len(exe))

        # If a device is exported, mark the node as executable
        elif isinstance(target, DeviceDict):
            # these timestamp formats are completely made up, but
            # hopefully the dateutils parser will hold together...
            timestamp = parser.parse(target.info.started_date)
            mode = stat.S_IFDIR
            if target.info and target.info.exported:
                # If the device is exported, mark the node as executable
                mode |= (stat.S_IEXEC)
            return self.make_node(mode=mode, timestamp=unix_time(timestamp))

        elif isinstance(target, DeviceAttribute):
            # set mode according to whether the attr is read/writable
            mode = stat.S_IFDIR | stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH
            if target.writable != PyTango.AttrWriteType.READ:
                mode |= (stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
            return self.make_node(mode=mode)

        # otherwise show it as a directory
        else:
            return self.make_node(mode=stat.S_IFDIR, size=0)

    def readdir(self, path, fh):
        if path in self.tmp:
            return [".", "."]
        try:
            target = self._get_path(path)
        except PyTango.DevFailed:
            return None
        # Since slashes are not allowed in file names, we encode
        # them as percent signs (%) to sanitize device names
        nodes = [name.replace("/", "%") for name in target.keys()]
        # if isinstance(target, DeviceDict):
        #     nodes.append(".info")
        if isinstance(target, AttributesDict):
            for i, node in enumerate(nodes):
                if target[node].disp_level == PyTango.DispLevel.EXPERT:
                    nodes[i] = "." + node
        # if isinstance(target, PropertiesDict):
        #     nodes.extend([node + ".history" for node in nodes])
        return [".", ".."] + nodes

    def mkdir(self, path, mode):
        parent, child = path.rsplit("/", 1)

        if parent in self.tmp:
            # we are creating something
            thing = self.tmp[parent]
            if thing == SERVER:
                server = parent.rsplit("/", 1)[-1]
                self.tree["servers"].add(server, child)
            elif thing == CLASS:
                _, server, inst, clss = parent.split("/")
                self.tree["servers"].add(server, inst, clss, child)
        else:
            target = self._get_path(parent)
            if isinstance(target, ServersDict):
                self.tmp[path] = SERVER
            elif isinstance(target, InstanceDict):
                self.tmp[path] = CLASS
            elif isinstance(target, ClassDict):  # creating a device
                target.add([child.replace("%", "/")])

    def read(self, path, size, offset, fh):
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
                if target.data_format == PyTango.AttrDataFormat.SPECTRUM:
                    return "\n".join(getattr(target, child)) + "\n"
                return str(getattr(target, child)) + "\n"
        if isinstance(target, DeviceCommand):
            return EXE.format(device=target.devicename, command=target.name)
        if isinstance(target, DeviceProperty):
            return "\n".join(target.value) + "\n"

    def write(self, path, data, offset, fh):
        "Write data to a file"
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
                if attr in ("write", "w_value"):
                    dtype = target.info.data_type
                    try:
                        value = PyTango.utils.seqStr_2_obj(data, dtype)
                        setattr(target, attr, value)
                        return len(data)
                    except (ValueError, PyTango.DevFailed) as e:
                        self.log.debug(e)
                        raise FuseOSError(EINVAL)
                elif attr in ("label", "unit", "display_unit", "standard_unit",
                              "description", "format",
                              "min_value", "max_value", "min_alarm", "max_alarm",
                              "polling_period"):
                    setattr(target, attr, data.strip())

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
        return flags

    def flush(self, path, fh):
        pass

    def sync(self, path, fdatasync, fh):
        pass

    def release(self, path, flags):
        pass

    def mknod(*args):
        pass

    def rename(self, oldpath, newpath):

        # renaming currently only works for properties

        oldparent, oldchild = os.path.split(oldpath)
        newparent, newchild = os.path.split(newpath)
        if oldpath in self.tmp and SEDTMP.match(oldchild):
            # we are renaming a temporary file!
            # presumably it's created by sed
            value = self.tmp.pop(oldpath)
            if SEDTMP.match(newchild):
                # not sure if this ever happens
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
        pass

    def chmod(self, *args):
        # noop, but needs to exist to prevent errors
        pass
