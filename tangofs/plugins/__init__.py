"""
A hacky plugin system for file formatters
"""

# TODO: figure out a way to allow more than one plugin to work
# on an attribute, e.g. by using different file extensions?

import imp
import logging
import os
import glob


plugins = []

# register all modules in this directory, not very elegant
for f in glob.glob(os.path.dirname(__file__)+"/*.py"):
    name = os.path.splitext(os.path.basename(f))[0]
    if name != "__init__":
        try:
            plugin = imp.load_source(name, f)
        except Exception as e:
            pass  # TODO: handle broken plugins better
        plugins.append(plugin)


def get_plugins(info, data):
    "Find any suitable plugins given an attribute info object"
    matches = []
    for plugin in plugins:
        logging.debug("Testing plugin '%s' on '%s", plugin.__name__, info.name)
        if plugin.check(info, data):
            logging.debug("Plugin '%s' matches '%s'!", plugin.__name__, info.name)
            matches.append(plugin)
        else:
            logging.debug("Plugin '%s' does not match '%s'.", plugin.__name__, info.name)
    return matches
