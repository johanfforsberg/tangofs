import imp
import os
import glob

plugins = []

for f in glob.glob(os.path.dirname(__file__)+"/*.py"):
    if f.endswith("__init__.py"):
        continue
    name = os.path.splitext(os.path.basename(f))[0]
    plugins.append(imp.load_source(name, f))


def get_plugins(info):
    "Find any suitable plugins for the given attribute"
    matches = []
    for plugin in plugins:
        print "testing", plugin.spec["name"],
        data_type = plugin.spec.get("data_type")
        data_format = plugin.spec.get("data_format")
        if all((data_type is None or data_type == info.data_type,
                data_format is None or data_format == info.data_format)):
            print "...matches!"
            matches.append(plugin)
        else:
            print "...does not match"
    return matches
