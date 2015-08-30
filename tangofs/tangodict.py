"""
The TangoDict is an attempt at a friendlier interface to then
Tango database than the basic C++ API. It presents the database
as a nested Python dict which is lazily loaded from the db as
it is accessed.
"""

from abc import ABCMeta, abstractmethod
from functools import partial
from itertools import chain
import logging
import re


import PyTango

from ttldict import TTLDict
from caseless import CaselessDictionary


SERVER_REGEX = "^([_-\w]+)/([_-\w]+)$"
CLASS_REGEX = "\w+"
DEVICE_REGEX = "^([_-\w]+)/([_-\w]+)/([_-\w]+)$"

server_validator = lambda name, _: re.match(SERVER_REGEX, name)
class_validator = lambda name, _: re.match(CLASS_REGEX, name)
device_validator = lambda name, _: re.match(DEVICE_REGEX, name)


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

    def refresh(self, recurse=False):
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

    # def __del__(self):
    #     print "GC", self.name, self.parent._cache.get(self.name)


class DomainsDict(AbstractTangoDict):

    child_type = "domain"
    name = "domains"

    def get_items_from_db(self):
        result = self._db.get_device_domain("*")
        return [s.lower() for s in result.value_string]

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
        return [f.lower() for f in families]

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
        return [m.lower() for m in members]

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

    def add(self, srvname, instname, classname=None, devices=None):
        "add servers, instances and/or devices"
        servername = "%s/%s" % (srvname, instname)
        devinfos = []
        if classname and devices:
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
        self[srvname][instname][classname]._cache.clear()

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

    def rename_instance(self, oldname, newname):
        self._db.rename_server("%s/%s" % (self.name, oldname),
                               "%s/%s" % (self.name, newname))
        self._cache.clear()

    def __delitem__(self, instancename):
        self.delete(instancename)

    def delete(self, instancename):
        self._db.delete_server("%s/%s" % (self.name, instancename))
        self._cache.clear()


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

    def rename(self, name):
        self.parent.rename_instance(self.name, name)
        self.name = name

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
        return [s.lower() for s in result.value_string]

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
        self.name = name.lower()
        self._info = None
        self._proxy = None
        AbstractTangoDict.__init__(self, db, **kwargs)

    def make_child(self, name):
        if name == "properties":
            return PropertiesDict(self._db, self.name, parent=self, ttl=self._ttl)

        # TODO: this is awkward
        elif name == "attributes" and self.proxy:
            try:
                self.proxy.ping()
                return AttributesDict(self._db, self.name, parent=self, ttl=self._ttl)
            except PyTango.DevFailed:
                logging.debug("cannot communicate with device %s", self.name)
                return
        elif name == "commands" and self.proxy:
            try:
                self.proxy.ping()
                return CommandsDict(self._db, self.name, parent=self, ttl=self._ttl)
            except PyTango.DevFailed:
                logging.debug("cannot communicate with device %s", self.name)
                return

    def get_items_from_db(self):
        if self.proxy:
            try:
                self.proxy.ping()
                return ["properties", "attributes", "commands"]
            except PyTango.DevFailed:
                pass
        return ["properties"]

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
        try:
            self._proxy = ObjectWrapper(
                PyTango.DeviceProxy(self.name),
                logger=logging.getLogger("DeviceProxy(%s)" % self.name))
            return self._proxy
        except PyTango.DevFailed:
            logging.debug("cannot create proxy to device %s", self.name)
            pass

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
        self._infos = None
        AbstractTangoDict.__init__(self, db, **kwargs)

    def get_items_from_db(self):
        attrs = self.parent.proxy.get_attribute_list()
        # More efficient to read all info in one call than to do it for
        # each child (assuming that the children will eventually be created)
        self._infos = self.parent.proxy.get_attribute_config(attrs)
        return list(attrs)

    def make_child(self, attrname):
        info = None
        for info in self._infos:
            if attrname.lower() == info.name.lower():
                break
        return DeviceAttribute(self.devicename, attrname, self.parent,
                               info=info)


class DeviceAttribute(object):

    def __init__(self, devicename, name, parent, info=None):
        self.devicename = devicename
        self.name = name
        self.parent = parent
        self._proxy = None
        self._info = info
        #self.data = self._attribute.read()
        self._last_read = 0
        self._value = None

    @property
    def info(self):
        if self._info:
            return self._info
        self._info = self.parent.proxy.get_attribute_config(self.name)
        return self._info

    def set_config(self, attr, value):
        setattr(self.info, attr, value)
        self.parent.proxy.set_attribute_config(self.info)

    def keys(self):
        keys = (["value"] +
                [attr for attr in dir(self.info)
                 if not attr.startswith("__") and
                 # don't know what these are for...
                 attr not in ["extensions", "writable_attr_name"]])
        if self.info.writable == PyTango.AttrWriteType.WRITE:
            keys += ["w_value"]
        return keys

    @property
    def writable(self):
        return str(self.info.writable)

    # add all config items as attributes
    @property
    def data_type(self):
        return str(PyTango.ArgType.values[self.info.data_type])

    @property
    def disp_level(self):
        return self.info.disp_level

    @property
    def data_format(self):
        return self.info.data_format

    @property
    def max_dim_x(self):
        return self.info.max_dim_x

    @property
    def max_dim_y(self):
        return self.info.max_dim_y

    @property
    def value(self):
        self._value = self.parent.proxy.read_attribute(self.name).value
        return self._value

    @value.setter
    def value(self, value):
        self.parent.proxy.write_attribute(self.name, value)

    @property
    def w_value(self):
        self._w_value = self.parent.proxy.read_attribute(self.name).w_value
        return self._w_value

    @w_value.setter
    def w_value(self, value):
        self.parent.proxy.write_attribute(self.name, value)

    # Configuration #
    # TODO: I'm sure be more neatly done with __set/getattr__ magic...

    @property
    def min_value(self):
        return self.info.min_value

    @min_value.setter
    def min_value(self, value):
        self.set_config("min_value", value)

    @property
    def max_value(self):
        return self.info.max_value

    @max_value.setter
    def max_value(self, value):
        self.set_config("max_value", value)

    @property
    def min_alarm(self):
        return self.info.min_alarm

    @min_alarm.setter
    def min_alarm(self, value):
        self.set_config("min_alarm", value)

    @property
    def max_alarm(self):
        return self.info.max_alarm

    @max_alarm.setter
    def max_alarm(self, value):
        self.set_config("max_alarm", value)

    @property
    def description(self):
        return self.info.description

    @description.setter
    def description(self, desc):
        self.set_config("description", desc)

    @property
    def label(self):
        return self.info.label

    @label.setter
    def label(self, value):
        self.set_config("label", value)

    @property
    def unit(self):
        return self.info.unit

    @unit.setter
    def unit(self, value):
        self.set_config("unit", value)

    @property
    def standard_unit(self):
        return self.info.standard_unit

    @standard_unit.setter
    def standard_unit(self, value):
        self.set_config("standard_unit", value)

    @property
    def display_unit(self):
        return self.info.display_unit

    @display_unit.setter
    def display_unit(self, value):
        self.set_config("display_unit", value)

    @property
    def format(self):
        return self.info.format

    @format.setter
    def format(self, value):
        self.set_config("format", value)


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
        self._proxy = ObjectWrapper(
            PyTango.DeviceProxy(self.devicename),
            logger=logging.getLogger("DeviceProxy(%s)" % self.name))
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

    def add(self, props):
        print "add", self.name, props, [type(value) for value in props.values()]
        self._db.put_device_property(self.devicename, props)
        self._cache.clear()

    def delete(self, prop):
        self._db.delete_device_property(self.devicename, prop)
        self._cache.clear()

    def __setitem__(self, key, value):
        self.add({key: value})

    def __delitem__(self, key):
        self.delete(key)


class DeviceProperty(object):

    def __init__(self, db, devicename, name, parent=None):
        self._db = db
        self.devicename = devicename
        self.name = name
        self._parent = parent
        self._history = None
        self._value = None
        #self.refresh()

    # def refresh(self):
    #     result = self._db.get_device_property(self.devicename, self.name)
    #     self.value = list(result[self.name])

    @property
    def path(self):
        return self.parent.path + (self.name,)

    @property
    def value(self):
        if self._value is not None:
            return self._value
        self._value = list(self._db.get_device_property(
            self.devicename, self.name)[self.name])
        return self._value

    @value.setter
    def value(self, value):
        self._db.put_device_property(self.devicename, {self.name: value})
        self._value = value
        self._history = None

    @property
    def history(self):
        if self._history:
            return self._history
        self._history = self._db.get_device_property_history(
            self.devicename, self.name)
        return self._history

    @property
    def parent(self):
        return self._parent

    def __len__(self):
        return len(self.value)

    def rename(self, name):
        if name != self.name:
            self.parent.add({name: self.value})
            self.parent.delete(self.name)
            self.name = name

    def delete(self):
        self.parent.delete(self.name)


class ObjectWrapper(object):

    """An object that allows all method calls and records them,
    then passes them on to a target object (if any)."""

    def __init__(self, target=None, keep=False, logger=False):
        self.target = target
        self.keep = keep
        self.calls = []
        self._logger = logger

    def __getattr__(self, attr):

        if attr.startswith("_"):
            return getattr(self, attr)

        def method(attr, *args, **kwargs):
            call = (attr, args, kwargs)
            if self.keep:
                self.calls.append(call)
            if self.logger:
                fmt = "%s(%s)" % (attr,
                                  ", ".join(chain(("%r" % a for a in args),
                                                  ("%s=%r" % i
                                                   for i in kwargs.items()))))
                self._logger.debug(fmt)
            if self.target:
                return getattr(self.target, attr)(*args, **kwargs)

        return partial(method, attr)


class TangoDict(dict):

    def __init__(self, ttl=None, db=None, *args, **kwargs):
        logger = logging.getLogger("tangodb")
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
