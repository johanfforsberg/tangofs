TangoFS

This is a simple FUSE based filesystem that can be used to interact with a Tango (http://tango-controls.org) controlsystem.

To use it, you need python (2.x ATM), PyTango, fusepy (https://github.com/terencehonles/fusepy) and dateutils installed, and a Tango database to talk to.

It should work under Linux (tested) and possibly MacOS (not tested).


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

  # wield shell power!               
  $ grep ham mountpoint/devices/*/A5/*/properties/Breakfast
  ...
  $ sed s/ham/spam/g mountpoint/devices/*/A5/*/properties/Breakfast
  ... 
  $ head mountpoint/devices/*/A5/*/properties/*
  ...

  # interactive attribute plotting!
  $ gnuplot -p -e 'plot "/tmp/test/devices/sys/tg_test/1/attributes/wave/value"'  


You get the idea. Properties and attributes are represented as files, commands as executables and everything else as a directory hierarchy resembling a Jive tree.

The point is to enable easy direct access to Tango data with standard programs that understand files and directories. Various representations and formats of the data could be provided, e.g. image formats, to make it easy to use your favorite software.

Beware: this is a very fresh project with known bugs and very limited testing. Don't use it anywhere near an important system!


TODO/IDEAS

- Creating servers
- Modes and dates should carry meaning where that makes sense.
- Represent property history, device info, etc
- Differ between OPERATOR/EXPERT levels, perhaps using .hidden files?
- The plugin system for data formatting needs love
- Make attribute configuration writable
- Aliases (as links?)
- Classes toplevel to access class config (like Jive)
- How should errors be handled?
- Performance profiling of DB access, caching...
- Logging
- Unit testing!
- Python 3 support

Pull requests are welcome!


TIPS & TRICKS

Tango names are not case sensitive, and so neither is tangofs. However, bash is case sensitive by default which can be annoying. There are settings for it though:

    bind "set completion-ignore-case on"
    shopt -s nocaseglob

Now you can enjoy caseless completion and globbing!

