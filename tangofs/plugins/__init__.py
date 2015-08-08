"""
A hacky plugin system for file formatters
"""

import imp
import os
import glob


plugins = []

# register all modules in this directory, not very elegant
for f in glob.glob(os.path.dirname(__file__)+"/*.py"):
    name = os.path.splitext(os.path.basename(f))[0]
    if name != "__init__":
        plugin = imp.load_source(name, f)
        plugins.append(plugin)


def get_plugins(info):
    "Find any suitable plugins given an attribute info object"
    matches = []
    for plugin in plugins:
        print "Testing", plugin.spec["name"],
        data_type = plugin.spec.get("data_type")
        data_format = plugin.spec.get("data_format")
        if all((data_type is None or data_type == info.data_type,
                data_format is None or data_format == info.data_format)):
            print "...matches!"
            matches.append(plugin)
        else:
            print "...does not match"
    return matches
