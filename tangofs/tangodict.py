"""
The TangoDict is an attempt at a friendlier interface to then
Tango database than the basic C++ API. It presents the database
as a nested Python dict which is lazily loaded from the db as
it is accessed.
"""

import re
from abc import ABCMeta, abstractmethod
from functools import partial
from itertools import chain
from time import time
#from weakref import ref, ReferenceError

import PyTango

from ttldict import TTLDict
from caseless import CaselessDictionary


SERVER_REGEX = "^([_-\w]+)/([_-\w]+)$"
CLASS_REGEX = "\w+"
DEVICE_REGEX = "^([_-\w]+)/([_-\w]+)/([_-\w]+)$"

server_validator = lambda name, _: re.match(SERVER_REGEX, name)
class_validator = lambda name, _: re.match(CLASS_REGEX, name)
device_validator = lambda name, _: re.match(DEVICE_REGEX, name)


def create_ids():
    i = 0
    while True:
        yield i
        i += 1

idgen = create_ids()


class AbstractTangoDict(dict):

    """Abstract baseclass for part of a Tango tree.  Cannot be
    instantiated, only for inheritance.

    The idea is that instances work like dicts, and represent one
    branch in a Tango DB tree, e.g. all servers, all instances of one
    server, etc. The values in the dict are dicts of members one level
    down, i.e. instance->classes.

    The data is fetched from a Tango database (read-only for now) and
    cached in memory. You can optionally give a TTL ("time to live",
    in seconds) which causes the data to be refreshed from DB if it is
    accessed after the TTL has passed.
    """

    child_type = None
    __metaclass__ = ABCMeta

    def __init__(self, db=None, ttl=None, parent=None):
        self._db = db
        self._ttl = ttl
        self._parent = parent
        if ttl:
            self._dict_class = partial(TTLDict, default_ttl=ttl)
        else:
            self._dict_class = CaselessDictionary
        self._cache = self._dict_class()
        self._id = next(idgen)

    def refresh(self, recurse=False):
        print "refresh"
        items = self.get_items_from_db()
        self._cache = self._dict_class(**dict((str(name), None)
                                              for name in items))
        if recurse:
            for item in self._cache.values():
                item and item.refresh(True)

    @abstractmethod
    def get_items_from_db(self):
        pass

    @abstractmethod
    def make_child(self, name):
        pass

    @abstractmethod
    def make_parent(self):
        pass

    @property
    def parent(self):
        try:
            if self._parent:
                return self._parent
        except (TypeError, ReferenceError):
            pass
        parent = self.make_parent
        self._parent = parent  # a weak reference to loosen circularity..?
        return parent

    @property
    def path(self):
        return self.parent.path + (self.name,)

    def __repr__(self):
        return "%s(%d %ss) [%r]" % (
            self.__class__.__name__, len(self._cache.keys()),
            self.child_type, id(self))

    def __getitem__(self, name):
        if not self._cache:
            self.refresh()
        try:
            if name not in self._cache:
                raise KeyError("No such child to %s" % self.name)
            item = self._cache.get(name)
            if item is None:
                item = self.make_child(name)
                self._cache[name] = item
            return item
        except (ValueError, PyTango.DevFailed) as e:
            raise KeyError(e)

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    def __iter__(self):
        if not self._cache:
            self.refresh()
        return iter(sorted(self._cache.keys()))

    def keys(self):
        if not self._cache:
            self.refresh()
        return self._cache.keys()

    # def values(self):
    #     if not self._cache:
    #         self.refresh()
    #     for key in self._cache:
    #         self.get(key)
    #     return self._cache.values()

    def items(self):
        if not self._cache:
            self.refresh()
        for key in self._cache:
            self.get(key)
        return self._cache.items()

    def __len__(self):
        return len(self._cache.items())

    def __contains__(self, key):
        if not self._cache:
            self.refresh()
        return key in self._cache

    def to_dict(self):
        result = {}
        for key, value in self.items():
            if value:
                child = value.to_dict()
                if child:
                    result[key] = child
        return result

    def __del__(self):
        print "GC", self.name, self.parent._cache.get(self.name)


class DomainsDict(AbstractTangoDict):

    child_type = "domain"

    def get_items_from_db(self):
        self.name = "devices"
        result = self._db.get_device_domain("*")
        return result.value_string

    def make_child(self, domain):
        return FamiliesDict(self._db, domain, parent=self)


class FamiliesDict(AbstractTangoDict):

    child_type = "family"

    def __init__(self, db, domain, **kwargs):
        self.name = domain
        super(FamiliesDict, self).__init__(db, **kwargs)

    def get_items_from_db(self):
        result = self._db.get_device_family(self.name + "/*")
        families = result.value_string
        return families

    def make_child(self, family):
        return MembersDict(self._db, self.name, family, parent=self)


class MembersDict(AbstractTangoDict):

    child_type = "member"

    def __init__(self, db, domain, family, **kwargs):
        self.domain = domain
        self.name = family
        super(MembersDict, self).__init__(db, **kwargs)

    def get_items_from_db(self):
        result = self._db.get_device_member(self.domain + "/" + self.name + "/*")
        members = result.value_string
        return members

    def make_child(self, member):
        devname = "{0}/{1}/{2}".format(self.domain, self.name, member)
        return DeviceDict(self._db, devname, parent=self)


class ServersDict(AbstractTangoDict):

    child_type = "server"
    name = "servers"

    def get_items_from_db(self):
        result = self._db.get_server_name_list()
        return result.value_string

    def make_child(self, servername):
        return ServerDict(self._db, servername, ttl=self._ttl, parent=self)

    def make_parent(self):
        pass

    @property
    def path(self):
        return ("servers",)

    def add(self, srvname, instname, classname, devices):
        "add servers, instances and/or devices"
        servername = "%s/%s" % (srvname, instname)
        devinfos = []
        for dev in devices:
            devinfo = PyTango.DbDevInfo()
            devinfo.name = dev
            devinfo._class = classname
            devinfo.server = servername
            devinfos.append(devinfo)
        # if the server/instance doesn't exist, create it...
        if (srvname not in self
                or instname not in self.get(srvname, {})):
            self._db.add_server(servername, devinfos)
        else:  # ...otherwise, just create the devices
            for dev in devinfos:
                self._db.add_device(dev)
        # finally we must refresh the tree to see the new stuff
        self[srvname][instname][classname].refresh()

    def delete(self, srvname, instname):
        self[srvname].delete(instname)


class ServerDict(AbstractTangoDict):

    child_type = "instance"

    def __init__(self, db, name, **kwargs):
        servers = db.get_server_name_list()
        if name not in servers:
            raise KeyError("No server named '%s'!" % name)
        self.name = name
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        result = self._db.get_instance_name_list(self.name)
        return result.value_string

    def make_child(self, instancename):
        return InstanceDict(self._db, self.name, instancename, ttl=self._ttl,
                            parent=self)

    def make_parent(self):
        return ServersDict(self._db, self._ttl)

    def add(self, instname, classname, devices):
        self.parent.add(self.name, instname, classname, devices)

    def __delitem__(self, instancename):
        self.delete(instancename)

    def delete(self, instancename):
        self._db.delete_server("%s/%s" % (self.servername, self.name))
        self.refresh()


class InstanceDict(AbstractTangoDict):

    child_type = "class"

    def __init__(self, db, servername, name, **kwargs):
        insts = db.get_instance_name_list(servername)
        if name not in insts:
            raise KeyError("Server '%' has no instance '%s'!" %
                           (servername, name))
        self.servername = servername
        self.name = name
        self._info = None
        AbstractTangoDict.__init__(self, db, **kwargs)

    @property
    def info(self):
        if not self._info:
            self._info = self._db.get_server_info(
                "%s/%s" % (self.servername, self.name))
        return self._info

    def get_items_from_db(self):
        server_instance = "%s/%s" % (self.servername, self.name)
        result = self._db.get_server_class_list(server_instance)
        return result.value_string

    def make_child(self, classname):
        return ClassDict(self._db, self.servername, self.name,
                         classname, ttl=self._ttl, parent=self)

    def make_parent(self):
        return ServerDict(self._db, self.servername, ttl=self._ttl)

    def add(self, classname, devices):
        self.parent.add(self.name, classname, devices)

    def delete(self):
        self.parent.delete(self.name)


class ClassDict(AbstractTangoDict):

    child_type = "device"

    def __init__(self, db, servername, instancename, name, **kwargs):
        self.servername = servername
        self.instancename = instancename
        self.name = name
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        server_instance = "%s/%s" % (self.servername, self.instancename)
        result = self._db.get_device_name(server_instance, self.name)
        return result.value_string

    def make_child(self, devicename):
        return DeviceDict(self._db, devicename, ttl=self._ttl, parent=self)

    def make_parent(self):
        return InstanceDict(self._db, self.servername, self.instancename,
                            ttl=self._ttl)

    def add(self, devices):
        self.parent.add(self.name, devices)

    def delete(self, devicename):
        self._db.delete_device(devicename)

    def __delitem__(self, devicename):
        self.delete(devicename)


class DeviceDict(AbstractTangoDict):

    def __init__(self, db, name, **kwargs):
        self.name = name
        self._info = None
        self._proxy = None
        AbstractTangoDict.__init__(self, db, **kwargs)

    def make_child(self, name):
        if name == "properties":
            return PropertiesDict(self._db, self.name, parent=self, ttl=self._ttl)
        if name == "attributes":
            return AttributesDict(self._db, self.name, parent=self, ttl=self._ttl)
        if name == "commands":
            return CommandsDict(self._db, self.name, parent=self, ttl=self._ttl)

    def get_items_from_db(self):
        return ["properties", "attributes", "commands"]

    def make_parent(self):
        cls = self.info.class_name
        srv, inst = self.info.ds_full_name.split("/")
        return ClassDict(self._db, srv, inst, cls, ttl=self._ttl)

    @property
    def path(self):
        return self.parent.path + (self.name,)

    @property
    def proxy(self):
        if self._proxy:
            return self._proxy
        self._proxy = PyTango.DeviceProxy(self.name)
        return self._proxy

    @property
    def info(self):
        if not self._info:
            try:
                self._info = self._db.get_device_info(self.name)
            except PyTango.DevFailed:
                return None
        return self._info

    def delete(self):
        self.parent.delete(self.name)

    # def refresh(self, recurse=False):
    #     self._info = self._db.get_device_info(self.name)
    #     if recurse:
    #         self.properties.refresh()

    # def to_dict(self):
    #     return {"properties": self.properties.to_dict()}


class AttributesDict(AbstractTangoDict):

    child_type = "attribute"

    def __init__(self, db, devicename, **kwargs):
        self.devicename = devicename
        self.name = "attributes"
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        attrs = self.parent.proxy.get_attribute_list()
        return list(attrs)

    def make_child(self, attrname):
        return DeviceAttribute(self.devicename, attrname, self.parent)


class DeviceAttribute(object):

    def __init__(self, devicename, name, parent):
        self.devicename = devicename
        self.name = name
        self.parent = parent
        self._proxy = None
        self._config = None
        #self.data = self._attribute.read()
        self._last_read = 0
        self._value = None

    @property
    def config(self):
        if self._config:
            return self._config
        self._config = self.parent.proxy.get_attribute_config(self.name)
        return self._config

    def keys(self):
        return ["value"] + [attr for attr in dir(self.config)
                            if not attr.startswith("__")]
        # filter out some other stuff too?

    # add all config items as attributes
    def __getattr__(self, attr):
        if attr == "value":
            return self.value
        if hasattr(self.config, attr):
            return getattr(self.config, attr)

    @property
    def value(self):
        t = time()
        if t < self._last_read + 0.1:  # TODO: make this more sophisticated?
            return self._value
        self._value = self.parent.proxy.read_attribute(self.name).value
        self._last_read = t
        return self._value

    @value.setter
    def value(self, value):
        self.parent.proxy.write_attribute(self.name, value)


class CommandsDict(AbstractTangoDict):

    child_type = "command"

    def __init__(self, db, devicename, **kwargs):
        self._db = db
        self.devicename = devicename
        self.name = "commands"
        self._proxy = None
        AbstractTangoDict.__init__(self, db, **kwargs)

    @property
    def proxy(self):
        if self._proxy:
            return self._proxy
        self._proxy = PyTango.DeviceProxy(self.devicename)
        return self._proxy

    def get_items_from_db(self):
        commands = self.proxy.command_list_query()
        return [cmd.cmd_name for cmd in commands]

    def make_child(self, cmdname):
        return DeviceCommand(self.devicename, cmdname, self.parent)


class DeviceCommand(object):

    def __init__(self, devicename, name, parent):
        self.devicename = devicename
        self.name = name
        self.parent = parent
        self._info = None

    def run(self, param):
        result = self.parent.proxy.command_inout(self.name, param)
        return result

    @property
    def info(self):
        if self._info:
            return self._info
        self._info = self.parent.proxy.command_query(self.name)
        return self._info


class PropertiesDict(AbstractTangoDict):

    child_type = "property"
    name = "properties"

    def __init__(self, db, devicename, **kwargs):
        self._db = db
        self.devicename = devicename
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        result = self._db.get_device_property_list(self.devicename, "*")
        return result.value_string

    def make_child(self, propertyname):
        return DeviceProperty(self._db, self.devicename, propertyname,
                              parent=self)

    def make_parent(self):
        return DeviceDict(self._db, self.devicename,
                          ttl=self._ttl)

    def to_dict(self):
        return dict((name, prop.value)
                    for name, prop in self.items() if prop)

    def add(self, props, refresh=True):
        self._db.put_device_property(self.devicename, props)
        if refresh:
            self.refresh()

    def remove(self, prop, refresh=True):
        self._db.delete_device_property(self.devicename, prop)
        if refresh:
            self.refresh()
            #logging.debug("keys: %r", self.keys())

    def __setitem__(self, key, value):
        self.add({key: value})

    def __delitem__(self, key):
        self.remove(key)


class DeviceProperty(object):

    def __init__(self, db, devicename, name, parent=None):
        self._db = db
        self.devicename = devicename
        self.name = name
        self._parent = parent
        self._history = []
        self.value = None
        self.refresh()

    def refresh(self):
        result = self._db.get_device_property(self.devicename, self.name)
        self.value = list(result[self.name])

    @property
    def path(self):
        return self.parent.path + (self.name,)

    @property
    def history(self):
        return []
        #return self._db.get_device_property_history(self.devicename, self.name)

    @property
    def parent(self):
        return self._parent

    def __len__(self):
        return len(self.value) if self.value else 0

    def set_value(self, value):
        self._db.put_device_property(self.devicename, {self.name: value})
        self.refresh()

    def set_name(self, name):
        self.parent.remove(self.name, refresh=False)
        self.name = name
        self.parent.add({name: self.value})

    def remove(self):
        self.parent.remove(self.name)


class ObjectWrapper(object):

    """An object that allows all method calls and records them,
    then passes them on to a target object (if any)."""

    def __init__(self, target=None, logger=False):
        self.target = target
        self.calls = []
        self.logger = logger
        print self.logger

    def __getattr__(self, attr):

        def method(attr, *args, **kwargs):
            call = (attr, args, kwargs)
            self.calls.append(call)
            if self.logger:
                fmt = "%s(%s)" % (attr,
                                  ", ".join(chain(('"%s"' % a for a in args),
                                                  ("%s='%s'" % i
                                                   for i in kwargs.items()))))
                #self.logger.info(fmt)
                print "*", fmt
            if self.target:
                return getattr(self.target, attr)(*args, **kwargs)

        return partial(method, attr)


class TangoDict(dict):

    def __init__(self, ttl=None, db=None, logger=None, *args, **kwargs):
        self._db = db or ObjectWrapper(PyTango.Database(), logger=logger)
        self.logger = logger
        self["servers"] = ServersDict(self._db, ttl=ttl)
        self["devices"] = DomainsDict(self._db, ttl=ttl)
        self.nodes = {}

    def refresh(self):
        self["servers"].refresh(recurse=True)

    def to_dict(self):
        return {"servers": self["servers"].to_dict()}

    def get_path(self, path):
        if path == [u""]:
            return self
        target = self
        for part in path:
            target = target[str(part)]
        return target
