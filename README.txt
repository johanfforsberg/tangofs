TangoFS

This is a simple FUSE based filesystem that can be used to interact with a Tango (http://tango-controls.org) controlsystem.

To use it, you need PyTango and fusepy (https://github.com/terencehonles/fusepy) installed, and a Tango database to talk to.

Examples:

  $ mkdir mountpoint
  $ TANGO_HOST=your-tango-db:10000 tangofs mountpoint
  
  $ ls mountpoint/servers  # list servers!
    ...
    
  $ cat mountpoint/servers/TangoTest/1/TangoTest/sys%tg_test%1/properties/someProperty   # read properties!
    ...
    
  $ cd mountpoint/servers/OtherServer/17/OtherServer   # walk the tree!

  $ echo Hello > my%nice%device/properties/SomeProperty   # write properties!
  
  $ cat my%nice%device/attributes/A/value  # read attributes!
    45.6
    
  $ my%nice%device/commands/Init   # run commands!

  $ grep ham mountpoint/devices/*/A5/*/properties/Breakfast  # wield shell power!
    ...

You get the idea. Properties and attributes are represented as files, commands as executables and everything else as a directory hierarchy resembling a Jive tree. Properties can be written, but not attributes, yet. Creating servers and devices still needs to be figured out.

The point is to enable easy direct access to Tango data with standard programs that understand files and directories. Various representations and formats of the data might provided, e.g. image formats.

Beware: this is a very fresh project. There are many corner cases to cover and beaviors to consider. Don't use it for anything remotely important. There are bugs hiding everywhere! Also, any aspect of how it works might change in the future.

Pull requests are welcome!


TIPS & TRICKS

Tango names are not case sensitive, and so neither is tangofs. However, bash is case sensitive by default which can be annoying. There are settings for it though:

    bind "set completion-ignore-case on"
    shopt -s nocaseglob

Now you can enjoy caseless completion and globbing!

