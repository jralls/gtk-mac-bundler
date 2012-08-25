import errno
import sys
import re
import os
import xml.dom.minidom
from xml.dom.minidom import Node
from plistlib import Plist
import utils

# Base class for anything that can be copied into a bundle with a
# source and dest.
class Path:
    def __init__(self, source, dest=None, recurse=False):
        if source and len(source) == 0:
            source = None
        if dest and len(dest) == 0:
            dest = None

        if source and os.path.isabs(source):
            source = os.path.normpath(source)
        if dest and os.path.isabs(dest):
            dest = os.path.normpath(dest)
            
        self.source = source
        self.dest = dest
        self.recurse = recurse

    def from_node(cls, node, validate=True):
        source = utils.node_get_string(node)
        dest = node.getAttribute("dest")
        recurse = node.getAttribute("recurse")
        if len(dest) == 0:
            dest = None
        if recurse == "True":
            recurse = True
        else:
            recurse = False
        if validate:
            Path.validate(source, dest)
            
        return Path(source, dest, recurse)
    from_node = classmethod(from_node)

    def validate(cls, source, dest):
        if source and len(source) == 0:
            source = None
        if dest and len(dest) == 0:
            dest = None

        if not source or len(source) == 0:
            raise Exception("The source path cannot be empty")
        
        if source.startswith("${bundle}"):
            raise Exception("The source path cannot use a ${bundle} macro")

        if dest and dest.startswith("${prefix"):
            raise Exception("The destination path cannot use a ${prefix} macro")

        if not os.path.isabs(source):
            if not (source.startswith("${project}") or source.startswith("${env:") or \
                    source.startswith("${pkg:") or source.startswith("${prefix}") or \
                    source.startswith("${prefix:")):
                raise Exception("The source path must be absolute or use one of the "
                                "predefined macros ${project}, ${prefix}, ${prefix:*}, "
                                "${env:*}, or ${pkg:*:*}")

        if not source.startswith("${prefix") and os.path.isabs(source):
            if not dest:
                raise Exception("If the source doesn't use a ${prefix} or ${prefix:*} "
                                "macro, the destination path must be set " + dest)

        if not dest and not source.startswith("${prefix"):
            raise Exception("If the destination path is empty, the source must use "
                            "a ${prefix} or ${prefix:*} macro")

        if dest and len(dest) > 0 and not dest.startswith("${bundle}"):
            raise Exception("The destination path must start with ${bundle}")

        return True
    validate = classmethod(validate)

# Used for anything that has a name and value.
class Variable:
    def __init__(self, node):
        self.name = node.getAttribute("name")
        self.value = utils.node_get_string(node)

class Environment:
    def __init__(self, node):
        self.runtime_variables = []
        self.scripts = []

        variables = utils.node_get_elements_by_tag_name(node, "runtime-variable")
        for child in variables:
            self.runtime_variables.append(Variable(child))

        scripts = utils.node_get_elements_by_tag_name(node, "script")
        for child in scripts:
            script = Path(utils.node_get_string(child), "${bundle}/Resources/Scripts")
            self.scripts.append(script)

class Meta:
    def __init__(self, node):
        self.prefixes = {}

        prefixes = utils.node_get_elements_by_tag_name(node, "prefix")
        for child in prefixes:
            name = child.getAttribute("name")
            if len(name) == 0:
                name = "default"
            value = utils.evaluate_environment_variables(utils.node_get_string(child))
            self.prefixes[name] = value

        child = utils.node_get_element_by_tag_name(node, "image")
        if child:
            pass # FIXME: implement
        
        child = utils.node_get_element_by_tag_name(node, "run-install-name-tool")
        if child:
            self.run_install_name_tool = True
        else:
            self.run_install_name_tool = False

        child = utils.node_get_element_by_tag_name(node, "destination")
        self.overwrite = utils.node_get_property_boolean(child, "overwrite", False)
        self.dest = utils.node_get_string(child, "${project}")

        child = utils.node_get_element_by_tag_name(node, "gtk")
        if child:
            self.gtk = utils.node_get_string(child)
        else:
            self.gtk = "gtk+-2.0"

class Framework(Path):
    def __init__(self, source):
        Path.__init__(self, source, self.get_dest_path_from_source(source))

    def from_node(cls, node):
        framework = Path.from_node(node, validate=False)
        framework.dest = Framework.get_dest_path_from_source(framework.source)

        return framework
    from_node = classmethod(from_node)

    def get_dest_path_from_source(cls, source):
        (head, tail) = os.path.split(source)
        return "${bundle}/Contents/Frameworks/" + tail
    get_dest_path_from_source = classmethod(get_dest_path_from_source)

class Binary(Path):
    def __init__(self, source, dest):
        Path.__init__(self, source, dest)

    def from_node(cls, node):
        binary = Path.from_node(node)

        if not binary.source:
            raise "The tag 'binary' must have a 'source' property"

        return binary
    from_node = classmethod(from_node)

class Translation(Path):
    def __init__(self, name, sourcepath, destpath):
        Path.__init__(self, sourcepath, destpath)
        self.name = name

    def from_node(cls, node):
        source = utils.node_get_string(node)
        dest = node.getAttribute("dest")
        if len(dest) == 0:
            dest = None
        name = node.getAttribute("name")
        if len(name) == 0:
            raise "The tag 'translations' must have a 'name' property"

        return Translation(name, source, dest)
    from_node = classmethod(from_node)


        

class Data(Path):
    pass

class IconTheme:
    ICONS_NONE, ICONS_ALL, ICONS_AUTO = range(3)
    
    def __init__(self, name, icons=ICONS_AUTO):
        self.name = name
        self.source = "${prefix}/share/icons/" + name

        self.icons = icons

    def from_node(cls, node):
        name = utils.node_get_string(node)
        if not name:
            raise Exception("Icon theme must have a 'name' property")
        
        string = node.getAttribute("icons")
        if string == "all":
            icons = IconTheme.ICONS_ALL
        elif string == "none":
            icons = IconTheme.ICONS_NONE
        elif string == "auto" or len(string) == 0:
            icons = IconTheme.ICONS_AUTO
            
        return IconTheme(name, icons)
    from_node = classmethod(from_node)

class Project:
    def __init__(self, project_path=None):
        if not os.path.isabs(project_path):
            project_path = os.path.join(os.getcwd(), project_path)
        self.project_path = project_path
        self.root = None

        if project_path and os.path.exists(project_path):
            try:
                doc = xml.dom.minidom.parse(project_path)
                # Get the first app-bundle tag and ignore any others.
                self.root = utils.node_get_element_by_tag_name(doc, "app-bundle")
            except:
                print "Could not load project %s:" % (project_path)
                raise

        # The directory the project file is in (as opposed to
        # project_path which is the path including the filename).
        self.project_dir, tail = os.path.split(project_path)
        self.meta = self.get_meta()

        plist_path = self.get_plist_path()
        try:
            plist = Plist.fromFile(plist_path)
        except EnvironmentError, e:
            if e.errno == errno.ENOENT:
                print "Info.plist file not found: " + plist_path
                sys.exit(1)
            else:
                raise
        self.name = plist.CFBundleExecutable
        if plist.has_key("CFBundleName"):
            self.bundle_name = plist.CFBundleName
        else:
            self.bundle_name = plist.CFBundleExecutable
 
    """
     Replace ${env:?}, ${prefix}, ${prefix:?}, ${project}, ${gtk}, ${gtkdir},
     ${gtkversion}, ${pkg:?:?}, ${bundle}, and ${name} variables.
    """
    def evaluate_path(self, path, include_bundle=True):
        p = re.compile("^\${prefix}")
        path = p.sub(self.get_prefix(), path)

        p = re.compile("^\${prefix:(.*?)}")
        m = p.match(path)
        if m:
            path = p.sub(self.get_prefix(m.group(1)), path)

        p = re.compile("^\${project}")
        path = p.sub(self.project_dir, path)

        p = re.compile("\${gtk}")
        path = p.sub(self.meta.gtk, path)

        p = re.compile("\${gtkdir}")
        path = p.sub(self.get_gtk_dir(), path)

        p = re.compile("\${gtkversion}")
        path = p.sub(self.get_gtk_version(), path)

        try:
            p = re.compile("\${name}")
            path = p.sub(self.name, path)
        except AttributeError:
            pass # can be used before name path is set

        if include_bundle:
            try:
                p = re.compile("^\${bundle}")
                path = p.sub(self.get_bundle_path(), path)
            except AttributeError:
                pass # can be used before bundle path is set

        path = utils.evaluate_environment_variables(path)
        path = utils.evaluate_pkgconfig_variables(path)

        return os.path.normpath(path)

    def get_name(self):
        return self.name

    def get_bundle_name(self):
        return self.bundle_name

    def get_prefix(self, name="default"):
        meta = self.get_meta()
        return meta.prefixes[name]

    def get_project_path(self):
        return self.project_path

    def get_project_dir(self):
        return self.project_dir

    def get_bundle_path(self, *args):
        dest = self.get_meta().dest
        bundle_path = os.path.join(dest, "." + self.get_name() + ".app")
        bundle_path = self.evaluate_path(bundle_path, False)
        return os.path.join(bundle_path, *args)

    def get_plist_path(self):
        plist = utils.node_get_element_by_tag_name(self.root, "plist")
        if not plist:
            raise Exception("The 'plist' tag is required")
        return  self.evaluate_path(utils.node_get_string(plist))

    def get_launcher_script(self):
        node = utils.node_get_element_by_tag_name(self.root, "launcher-script")
        if node:
            path = Path.from_node(node, False)
            path.dest = "${bundle}/Contents/MacOS/${name}"
        else:
            # Use the default launcher.
            launcher = os.path.join(os.path.dirname(__file__), "launcher.sh")
            path = Path(launcher, "${bundle}/Contents/MacOS/${name}")

        return path

    def get_icon_themes(self):
        themes = []

        nodes = utils.node_get_elements_by_tag_name(self.root, "icon-theme")
        for node in nodes:
            themes.append(IconTheme.from_node(node))

        # The hicolor theme is mandatory.
        if not filter(lambda l: l.name == "hicolor", themes):
            themes.append(IconTheme("hicolor"))

        return themes

    def get_meta(self):
        node = utils.node_get_element_by_tag_name(self.root, "meta")
        return Meta(node)

    def get_gtk_version(self):
        if self.meta.gtk == "gtk+-3.0":
            return "3.0"
        else:
            return "2.0"

    def get_gtk_dir(self):
        if self.meta.gtk == "gtk+-3.0":
            return "gtk-3.0"
        else:
            return "gtk-2.0"

    def get_environment(self):
        node = utils.node_get_element_by_tag_name(self.root, "environment")
        return Environment(node)

    def get_frameworks(self):
        frameworks = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "framework")
        for node in nodes:
            frameworks.append(Framework.from_node(node))
        return frameworks

    def get_translations(self):
        translations = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "translations")
        for node in nodes:
            translations.append(Translation.from_node(node))
        return translations

    def get_main_binary(self):
        node = utils.node_get_element_by_tag_name(self.root, "main-binary")
        if not node:
            raise Exception("The file has no <main-binary> tag")

        binary = Binary.from_node(node)

        launcher = self.get_launcher_script()
        if launcher:
            suffix = "-bin"
        else:
            suffix = ""
        binary.dest = "${bundle}/Contents/MacOS/${name}" + suffix

        return binary

    def get_binaries(self):
        binaries = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "binary")
        for node in nodes:
            binaries.append(Binary.from_node(node))
        return binaries

    def get_data(self):
        data = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "data")
        for node in nodes:
            data.append(Data.from_node(node))
        return data
            
if __name__ == '__main__':
    project = Project(os.path.join(os.getcwd(), 'giggle.bundle'))

    print "General:"
    print "  Project path: %s" % (project.get_project_path())
    print "  Plist path: %s" % (project.get_plist_path())
    print "  App name: %s" % (project.name)
    print "  Destination: %s" % (project.get_meta().dest)
    print "  Overwrite: %s" % (str(project.get_meta().overwrite))

    environment = project.get_environment()
    print "Environment:"
    for variable in environment.runtime_variables:
        print "  %s=%s" % (variable.name, variable.value)
    for script in environment.scripts:
        print "  %s => %s" % (script.source, script.dest)

    print "Frameworks:"
    for framework in project.get_frameworks():
        print " ", framework

    print "Main binary:"
    binary = project.get_main_binary()
    print "  %s => %s" % (binary.source, binary.dest)

    print "Launcher:"
    launcher_script = project.get_launcher_script()
    print "  %s => %s" % (launcher_script.source, launcher_script.dest)

    print "Binaries:"
    for binary in project.get_binaries():
        print "  %s => %s" % (binary.source, binary.dest)

