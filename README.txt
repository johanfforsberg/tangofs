This is a simple FUSE based filesystem that can be used to interact with a Tango (http://tango-controls.org) database.

To use it, you need PyTango and pyfuse installed, and of course a Tango database to talk to.

Usage:

  $ mkdir mountpoint
  $ TANGO_HOST=your-tango-db:10000 tangofs mountpoint
  $ ls mountpoint/servers
    ...
  $ cat mountpoint/servers/Server/1/ServerClass/sys%tg_test%1/properties/someProperty
    ...
  $ cd mountpoint/servers/OtherServer/17

You get the idea. Properties are represented as files, and everything else as a directory hierarchy. The filesystem is read-only for now, and only contains device properties. Some caching is done, but currently data is only kept for 10 seconds. There is a tradeoff between performance and being up-to-date.

The idea is to work somethimg like Jive, with various representations of the database content. Also it would be nice to be able to write too, but I'm not sure how that would work in all cases.

Beware: this is an extremely fresh project. It barely works :)
