from abc import ABCMeta, abstractmethod
from functools import partial
import re

import PyTango

from ttldict import TTLDict


SERVER_REGEX = "^([-\w]+)/([-\w]+)$"
CLASS_REGEX = "\w+"
DEVICE_REGEX = "^([-\w]+)/([-\w]+)/([-\w]+)$"

server_validator = lambda name, _: re.match(SERVER_REGEX, name)
class_validator = lambda name, _: re.match(CLASS_REGEX, name)
device_validator = lambda name, _: re.match(DEVICE_REGEX, name)


class AbstractTangoDict(object):

    """Abstract baseclass for part of a Tango tree.  Cannot be
    instantiated, only for inheritance.

    The idea is that instances work like dicts, and represent one
    branch in a Tango DB tree, e.g. all servers, all instances of one
    server, etc. The values in the dict are lists of members one level
    down, i.e. instance->classes.

    The data is fetched from a Tango database (read-only for now) and
    cached in memory. You can optionally give a TTL ("time to live",
    in seconds) which causes the data to be refreshed from DB if it is
    accessed after the TTL has passed.
    """

    __metaclass__ = ABCMeta

    def __init__(self, db, ttl=None):
        self._db = db
        self._ttl = ttl
        if ttl:
            self._dict_class = partial(TTLDict, default_ttl=ttl)
        else:
            self._dict_class = dict
        self._cache = self._dict_class()
        self.refresh()

    def refresh(self, recurse=False):
        items = self.get_items_from_db()
        self._cache = self._dict_class(**dict((name, self._cache.get(name)) for name in items))
        if recurse:
            for item in self._cache.values():
                item and item.refresh(True)

    @abstractmethod
    def get_items_from_db(self):
        pass

    def __repr__(self):
        return "%s(%d) [%r]" % (self.__class__.__name__, len(self._cache.keys()), id(self))

    def __getitem__(self, name):
        if self._cache.get(name) is not None:
            return self._cache[name]
        print self, "did not find", name, "in cache"
        try:
            item = self.make_child(name)
            self._cache[name] = item
            return item
        except:
            raise KeyError

    def __iter__(self):
        return iter(sorted(self._cache.keys()))

    def keys(self):
        return self._cache.keys()

    def items(self):
        return self._items.keys()

    # def values(self):
    #     self._update_if_old()
    #     return self._items.values()


class ServersDict(AbstractTangoDict):

    def get_items_from_db(self):
        result = self._db.get_server_name_list()
        return result.value_string

    def make_child(self, servername):
        return InstancesDict(self._db, servername, ttl=self._ttl)


class InstancesDict(AbstractTangoDict):

    def __init__(self, db, servername, **kwargs):
        self.servername = servername
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        result = self._db.get_instance_name_list(self.servername)
        return result.value_string

    def make_child(self, instancename):
        return ClassesDict(self._db, self.servername, instancename, ttl=self._ttl)


class ClassesDict(AbstractTangoDict):

    def __init__(self, db, servername, instancename, **kwargs):
        self.servername = servername
        self.instancename = instancename
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        server_instance = "%s/%s" % (self.servername, self.instancename)
        result = self._db.get_server_class_list(server_instance)
        return result.value_string

    def make_child(self, classname):
        return DevicesDict(self._db, self.servername, self.instancename,
                           classname, ttl=self._ttl)


class DevicesDict(AbstractTangoDict):

    def __init__(self, db, servername, instancename, classname, **kwargs):
        self.servername = servername
        self.instancename = instancename
        self.classname = classname
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        server_instance = "%s/%s" % (self.servername, self.instancename)
        result = self._db.get_device_name(server_instance, self.classname)
        return result.value_string

    def make_child(self, devicename):
        return DeviceDict(self._db, devicename, ttl=self._ttl)


class DeviceDict(dict):

    def __init__(self, db, name, ttl=None):
        self._db = db
        self.name = name
        self.info = None
        dict.__init__(self)
        self["properties"] = self.properties = PropertiesDict(db, name, ttl=ttl)
        self.refresh()

    def refresh(self, recurse=False):
        info = self._db.get_device_info(self.name)
        self.info = info
        if recurse:
            self.properties.refresh()


class PropertiesDict(AbstractTangoDict):

    def __init__(self, db, devicename, **kwargs):
        self._db = db
        self.devicename = devicename
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        result = self._db.get_device_property_list(self.devicename, "*")
        return result.value_string

    def make_child(self, propertyname):
        return DeviceProperty(self._db, self.devicename, propertyname)


class DeviceProperty(object):

    def __init__(self, db, devicename, propertyname):
        self._db = db
        self.devicename = devicename
        self.propertyname = propertyname
        self._history = []
        self.value = None
        self.refresh()

    def refresh(self):
        result = self._db.get_device_property(self.devicename, self.propertyname)
        self.value = result[self.propertyname]
        self._history = self._db.get_device_property_history(self.devicename, self.propertyname)


class ObjectWrapper(object):

    """An object that allows all method calls and records them,
    then passes them on to a target object (if any)."""

    def __init__(self, target=None, log=False):
        self.target = target
        self.calls = []
        self.log = log

    def __getattr__(self, attr):

        def method(attr, *args, **kwargs):
            call = (attr, args, kwargs)
            self.calls.append(call)
            if self.log:
                print call
            if self.target:
                return getattr(self.target, attr)(*args, **kwargs)

        return partial(method, attr)


class TangoDict(dict):

    def __init__(self, ttl=None, *args, **kwargs):
        self._db = ObjectWrapper(PyTango.Database())
        self["servers"] = ServersDict(self._db, ttl=ttl)

    def refresh(self):
        self.servers.refresh(recurse=True)

    def get_path(self, path):
        if path == [u""]:
            return self
        target = self
        for part in path:
            target = target[part]
        return target
