import re
import os
import errno

def evaluate_environment_variables(string):
    p = re.compile("\${env:(.+?)}")
    m = p.search(string)
    while m:
        env = m.group(1)
        value = os.getenv(env)
        if not value:
            raise Exception("Environment variable %s is undefined" % (env))
        string = p.sub(value, string, 1)
        m = p.search(string)

    return string

def has_pkgconfig_module(module):
    """Returns True if the pkg-config module exists"""
    f = os.popen("pkg-config --exists " + module)
    f.read().strip()
    return f.close() is None

def has_pkgconfig_variable(module, key):
    """Returns True if the pkg-config variable exists for the given
    module
    """
    f = os.popen("pkg-config --variable=" + key + " " + module)
    status = bool(f.read().strip())
    f.close()
    return status

def evaluate_pkgconfig_variables(string):
    p = re.compile("\${pkg:(.*?):(.*?)}")
    m = p.search(string)
    while m:
        module = m.group(1)
        key = m.group(2)
        f = os.popen("pkg-config --variable=" + key + " " + module)
        value = f.read().strip()
        if not value:
            # pango 1.38 removed modules, try to give a helpful
            # message in case something tries to reference the no
            # longer existing variable (most likely from old bundle
            # xml files) when using a newer pango build.
            if module == "pango" and key == "pango_module_version":
                if has_pkgconfig_module("pango"):
                    raise Exception(
                        "'%s' got removed in '%s' "
                        "1.38. Remove any reference to pango "
                        "modules in your bundle xml." % (
                            key, module))
            raise Exception("pkg-config variable '%s %s' is undefined" % (key, module))
        string = p.sub(value, string, 1)
        m = p.search(string)

    return string

def makedirs(path):
    try:
        os.makedirs(path)
    except EnvironmentError as e:
        if e.errno != errno.EEXIST:
            raise

def node_get_elements_by_tag_name(node, name):
    try:
        return node.getElementsByTagName(name)
    except:
        return []

def node_get_element_by_tag_name(node, name):
    try:
        (data,) = node.getElementsByTagName(name)
        return data 
    except:
        return None

def node_get_string(node, default=None):
    try:
        return node.firstChild.data.strip()
    except:
        return default

def node_get_property_boolean(node, name, default=False):
    try:
        value = node.getAttribute(name)
        if value in [ "true", "yes" ]:
            return True
    except:
        pass

    return default

def filterlines(p, lines):
    for line in lines:
        match = p.match(line)
        if match:
            yield match.group(1)
