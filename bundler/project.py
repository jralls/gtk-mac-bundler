import errno
import sys
import re
import os
import glob
import shutil
from subprocess import call, check_call, Popen, PIPE, STDOUT
import xml.dom.minidom
from xml.dom.minidom import Node
import plistlib
from . import utils

# Base class for anything that can be copied into a bundle with a
# source and dest.
class Path(object):
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
        self.bundledir = 'Resources'

    @classmethod
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

        if node.tagName == "framework":
            return Framework(source, recurse)
        if node.tagName == "binary" or node.tagName == "main-binary":
            return Binary(source, dest, recurse)
        if node.tagName == "translations":
            name = node.getAttribute('name')
            if len(name) == 0:
                raise ValueError("The tag 'translations' must have a 'name' property.")
            return Translation(name, source, dest, recurse)
        if node.tagName == "gir":
            return GirFile(source, dest, recurse)
        if node.tagName == "icon-theme":
            name = utils.node_get_string(node)
            if not name:
                raise ValueError("Icon theme must have a 'name' property")

            icons = node.getAttribute("icons")
            return IconTheme(name, icons)

        return Path(source, dest, recurse)

    @classmethod
    def validate(cls, source, dest):
        if not source:
            raise ValueError("The source path cannot be empty")

        if source.startswith("${bundle}"):
            raise ValueError("The source path %s cannot use a ${bundle} macro"
                             % source)

        if dest and dest.startswith("${prefix"):
            raise ValueError("The destination path %s cannot use a ${prefix} "
                             "macro" % dest)

        p = re.compile("^\${(?:project}|prefix[:}]|pkg:|env:)")
        if not (os.path.isabs(source) or p.match(source)):
            raise ValueError("The source path %s must be absolute or use one of"
                             " the predefined macros ${project}, ${prefix},"
                             " ${prefix:*}, ${env:*}, or ${pkg:*:*}" % source)

        if not (source.startswith("${prefix") or dest):
            raise ValueError("If the source %s doesn't use a ${prefix} or "
                             "${prefix:*} macro, the destination path must be "
                             "set" % source)

        if dest and not dest.startswith("${bundle}"):
            raise ValueError("The destination path %s must start with ${bundle}"
                             % dest)

        return True

    def copy_file(self, project, source, dest):
        try:
            # print "Copying %s to %s" % (source, dest)
            shutil.copy2(source, dest)
        except EnvironmentError as e:
            if e.errno == errno.ENOENT:
                print("Warning, source file missing: " + source)
            elif e.errno in (errno.EEXIST, errno.EACCES):
                print("Warning, path already exists: " + dest)
            else:
                raise EnvironmentError("Error %s when copying file: %s"
                                       % (str(e), source))


    def copy_target_glob_recursive(self, project, source, dest):
        source_parent, source_tail = os.path.split(source)
        for root, dirs, files in os.walk(source_parent):
            destdir = os.path.join(dest, os.path.relpath(root, source_parent))
            glob_list = glob.glob(os.path.join(root, source_tail))
            if not glob_list:
                continue
            utils.makedirs(destdir)
            for globbed_source in glob_list:
                self.copy_file(project, globbed_source, destdir)

    def copy_target_recursive(self, project, source, dest):
        for root, dirs, files in os.walk(source):
            destdir = os.path.join(dest, os.path.relpath(root, source))
            if not files:
                continue
            utils.makedirs(destdir)
            for file in files:
                self.copy_file(project, os.path.join(root, file), destdir)


    def copy_target_glob(self, project, source, dest):
        for globbed_source in glob.glob(source):
                if os.path.isdir(globbed_source):
                    self.copy_target_recursive(project, globbed_source, dest)
                else:
                    self.copy_file(project, globbed_source, dest)

    def compute_destination(self, project):
        if self.dest:
            dest = project.evaluate_path(self.dest)
        else:
            # Source must begin with a prefix if we don't have a
            # dest. Skip past the source prefix and replace it with
            # the right bundle path instead.
            p = re.compile("^\${prefix(:.*?)?}/")
            m = p.match(self.source)
            if m:
                pathdir = os.path.join("Contents", self.bundledir)
                relative_dest = project.evaluate_path(self.source[m.end():])
                dest = project.get_bundle_path(pathdir, relative_dest)
            else:
                raise ValueError ("Invalid path, missing or invalid dest %s."
                                  % self.dest)
        # If the destination has a wildcard as last component (copied
        # from the source in dest-less paths), ignore the tail.
        (dest_parent, dest_tail) = os.path.split(dest)
        p = re.compile("[\*\?]")
        if p.search(dest_tail):
            dest = dest_parent

        utils.makedirs(dest_parent)
        return dest

    def is_source_glob(self):
        p = re.compile("[\*\?]")
        (source_parent, source_tail) = os.path.split(self.source)
        if p.search(source_tail):
            return True
        return False

    def compute_source_path(self, project):
        source = project.evaluate_path(self.source)
        # Check that the source only has wildcards in the last component.
        p = re.compile("[\*\?]")
        (source_parent, source_tail) = os.path.split(source)
        if p.search(source_parent):
            raise ValueError("Can't have wildcards except in the last path "
                             "component: " + source)

        if p.search(source_tail):
            source_check = source_parent
        else:
            source_check = source
        if not os.path.exists(source_check):
            raise ValueError("Cannot find source to copy: " + source)

        return source

    # Copies from source to dest, evaluating any variables
    # in the paths, and returns the real dest.
    def copy_target(self, project):
        source = self.compute_source_path(project)
        dest = self.compute_destination(project)
        if self.recurse:
            self.copy_target_glob_recursive(project, source, dest)
        else:
            self.copy_target_glob(project, source, dest)
        return dest

# Used for anything that has a name and value.
class Variable(object):
    def __init__(self, node):
        self.name = node.getAttribute("name")
        self.value = utils.node_get_string(node)

class Environment(object):
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

class Meta(object):
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

class Binary(Path):
    def __init__(self, source, dest=None, recurse=False):
        super(Binary, self).__init__(source, dest, recurse)
        self.bundledir = 'Resources'

    def copy_file(self, project, source, dest):
        path, ext = os.path.splitext(source)
        # Skip static libs and libtool files:
        if ext in ('.la', '.a'):
            return
        super(Binary, self).copy_file(project, source, dest)
        if os.path.isdir(dest):
            dest = os.path.join(dest, os.path.split(source)[1])
        # print ("Copy binary file %s to %s %s"
        #       % (source, 'directory' if os.path.isdir(dest) else 'file', dest))
        self.fix_rpaths(project, dest)
        # self.strip_debugging(dest)
        self.sign(project, dest)
        self.destinations.append(dest)

    def copy_target(self, project, log = False):
        self.destinations = []
        if os.path.isdir(self.compute_source_path(project)):
            source = self.source
            self.source = os.path.join(source, '*.so')
            self.recurse = True
            super(Binary, self).copy_target(project)
            self.source = os.path.join(source, '*.dylib')
            super(Binary, self).copy_target(project)
            self.source = source
        else:
            super(Binary, self).copy_target(project)
        return self.destinations

    def fix_rpaths(self, project, target, frameworks = []):
        if not project.get_meta().run_install_name_tool:
            return
        # Byte compiled scheme and python files don't have rpaths.
        if (target.endswith('.go') or target.endswith('.pyc') or
            target.endswith('.pyo')):
            return
        cmd = os.path.join(os.path.dirname(__file__),
                           "run-install-name-tool-change.sh")
        for prefix in project.get_meta().prefixes:
            prefix_path = project.get_prefix(prefix)
            call([cmd, target, prefix_path, self.bundledir, "change"])
            call([cmd, target, prefix_path, self.bundledir, "id"])
            for fw in frameworks:
                call([cmd, path, fw.get_name(), fw.get_bundlename(), 'change'])

    def sign(self, project, target):
        if "APPLICATION_CERT" not in os.environ:
            return
        cert = os.getenv("APPLICATION_CERT")
        ident = project.get_bundle_id()
        args = ['codesign', '-s', cert, '-i', ident, '--timestamp',
                '--options=runtime']
        entfile = project.get_entitlements_path()
        if entfile:
            args.extend(['--entitlements', entfile])
        args.append(target)
        output = Popen(args, stdout=PIPE, stderr=STDOUT)
        results = output.communicate()[0]
        if results:
            raise SystemError("Warning! Codesigning %s returned error %s."
                  % (target, results))

    def strip_debugging(self, target):
        if target.endswith(".dylib") or target.endswith(".so"):
            os.chmod(path, 0o644)
            os.system("strip -x " + target + " 2>/dev/null")
            os.chmod(target, 0o444)
        else:
            os.chmod(target, 0o755)
            os.system("strip -ur " + target + " 2>/dev/null")
            os.chmod(target, 0o555)


class Framework(Binary):
    def __init__(self, source, recurse):
        (head, tail) = os.path.split(source)
        dest = "${bundle}/Contents/Frameworks/" + tail
        super(Framework, self).__init__(source, dest, recurse);
        self.bundledir = "Frameworks"

    def get_name(self):
        fwname, fwext = os.path.splitext(os.path.basename(self.dest))
        return fwname

    def get_bundle_name(self):
        return os.path.join(self.bundledir, self.get_name())

    def fix_rpaths(self, project, frameworks):
        if not project.get_meta().run_install_name_tool:
            return
        dest = self.compute_desitnation(project)
        cmd = os.path.join(os.path.dirname(__file__),
                           "run-install-name-tool-change.sh")
        check_all([cmd, dest, self.get_name(), self.bundledir, 'id'])
        for dep in frameworks:
            if dep == self:
                continue
            check_call([cmd, dest, dep.get_name(),
                        dep.get_bundle_name(), 'change'])

class Translation(Path):
    def __init__(self, name, sourcepath, destpath, recurse):
        super(Translation, self).__init__(sourcepath, destpath, recurse)
        self.name = name

    def copy_target(self, project):
        if not self.name:
            raise ValueError("No program name to tranlate!")

        def name_filter(filename):
            name, ext = os.path.splitext(os.path.split(filename)[1])
            if name != self.name or ext not in (".mo", ".po"):
                return False
            return True

        source = project.evaluate_path(self.source)
        if source == None:
                raise ValueError("Failed to parse %s translation source!" % self.name)
        prefix = project.get_prefix()
        for root, trees, files in os.walk(source):
            for file in filter(name_filter, files):
                path = os.path.join(root, file)
                Path("${prefix}" + path[len(prefix):], self.dest).copy_target(project)


class GirFile(Path):
    def __init__(self, sourcepath, destpath, recurse):
        super(GirFile, self).__init__(sourcepath, destpath, recurse)
        self.bundle_path = '@executable_path/../Resources/lib'

    def copy_target(self, project, gir_dest, typelib_dest, lib_path):

        def transform_file(filename):
            path, fname = os.path.split(filename)
            name, ext = os.path.splitext(fname)

            with open (filename, "r", encoding="utf8") as source:
                lines = source.readlines()
            gir_file = os.path.join(gir_dest, fname)
            typelib = os.path.join(typelib_dest, name + '.typelib')
            with open (gir_file, "w", encoding="utf8") as target:
                for line in lines:
                    if re.match('\s*shared-library=', line):
                        (new_line, subs) = re.subn(lib_path, self.bundle_path, line)
                        if subs:
                            target.write(new_line)
                        else:
                            (car, cadr, cddr) = re.split('"', line, 2)
                            new_line = "".join([car, '"', os.path.join(self.bundle_path, cadr), '"'])
                            target.write(new_line)
                    else:
                        target.write(line)

            call(['g-ir-compiler', '--output=' + typelib, gir_file])
            return typelib

        filename = project.evaluate_path(self.source)
        typelib_paths = []
        for globbed_source in glob.glob(filename):
            try:
                typelib_paths.append(transform_file(globbed_source))
            except Exception as err:
                print('Error in transformation of %s: %s' % (globbed_source, err))
        return typelib_paths

class Data(Path):
    pass

class IconTheme(Path):
    ICONS_NONE, ICONS_ALL, ICONS_AUTO = list(range(3))

    def __init__(self, name, icons = "all"):
        super(IconTheme, self).__init__("${prefix}/share/icons/" + name)
        self.name = name
        if icons == "all":
            self.icons = IconTheme.ICONS_ALL
        elif icons == "none":
            self.icons = IconTheme.ICONS_NONE
        elif icons == "auto" or len(string) == 0:
            self.icons = IconTheme.ICONS_AUTO
        else:
            self.icons = IconTheme.ICONS_ALL

    def copy_target(self, project):
        source_base = self.source
        self.source = os.path.join(self.source, "index.theme")
        super(IconTheme, self).copy_target(project)
        self.source = source_base

    def enumerate_icons(self, project):
        all_icons = set()
        if self.icons == IconTheme.ICONS_NONE:
            return all_icons
        for root, dirs, files in os.walk(project.evaluate_path(self.source)):
            for f in files:
                (head, tail) = os.path.splitext(f)
                if tail in [".png", ".svg"]:
                    all_icons.add(head)
        return all_icons

    def copy_icons(self, project, used_icons):
        if self.icons == IconTheme.ICONS_NONE:
            return
        prefix = project.get_prefix()
        for root, dirs, files in os.walk(project.evaluate_path(self.source)):
            for f in files:
                # Go through every file, if it matches the icon
                # set, copy it.
                (head, tail) = os.path.splitext(f)

                if head.endswith('.symbolic'):
                    (head, tail) = os.path.splitext(head)

                if head in used_icons or self.icons == IconTheme.ICONS_ALL:
                    path = os.path.join(root, f)

                    # Note: Skipping svgs for now, they are really
                    # big and not really used.
                    if path.endswith(".svg"):
                        continue

                    # Replace the real paths with the prefix macro
                    # so we can use copy_target.
                    Path("${prefix}" + path[len(prefix):]).copy_target(project)

        # Generate icon cache.
        path = project.get_bundle_path("Contents/Resources/share/icons", self.name)
        cmd = "gtk-update-icon-cache -f " + path + " 2>/dev/null"
        os.popen(cmd)



class Project(object):
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
                print("Could not load project %s:" % (project_path))
                raise

        # The directory the project file is in (as opposed to
        # project_path which is the path including the filename).
        self.project_dir, tail = os.path.split(project_path)
        self.meta = self.get_meta()

        plist_path = self.get_plist_path()
        try:
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
        except EnvironmentError as e:
            if e.errno == errno.ENOENT:
                print("Info.plist file not found: " + plist_path)
                sys.exit(1)
            else:
                raise
        self.name = plist['CFBundleExecutable']
        if "CFBundleName" in plist:
            self.bundle_name = plist['CFBundleName']
        else:
            self.bundle_name = plist['CFBundleExecutable']

        self.bundle_id = plist['CFBundleIdentifier']

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

    def get_bundle_id(self):
        return self.bundle_id

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

    def get_entitlements_path(self):
        entitlements = utils.node_get_element_by_tag_name(self.root, "entitlements")
        if not entitlements:
            return None
        return self.evaluate_path(utils.node_get_string(entitlements))

    def get_launcher_script(self):
        node = utils.node_get_element_by_tag_name(self.root, "launcher-script")
        if node:
            path = Path.from_node(node, False)
            if not path.source:
                # Use the default launcher.
                launcher = os.path.join(os.path.dirname(__file__),
                                        "launcher.sh")
                path = Path(launcher, "${bundle}/Contents/MacOS/${name}")
            else:
                path.dest = "${bundle}/Contents/MacOS/${name}"
            return path
        return None

    def get_icon_themes(self):
        themes = []

        nodes = utils.node_get_elements_by_tag_name(self.root, "icon-theme")
        for node in nodes:
            themes.append(Path.from_node(node, False))

        # The hicolor theme is mandatory.
        if not [l for l in themes if l.name == "hicolor"]:
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
            frameworks.append(Path.from_node(node))
        return frameworks

    def get_translations(self):
        translations = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "translations")
        for node in nodes:
            translations.append(Path.from_node(node))
        return translations

    def get_gir(self):
        gir_files = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "gir")
        for node in nodes:
            gir_files.append(Path.from_node(node))
        return gir_files

    def get_main_binary(self):
        node = utils.node_get_element_by_tag_name(self.root, "main-binary")
        if not node:
            raise Exception("The file has no <main-binary> tag")

        binary = Path.from_node(node)

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
            binaries.append(Path.from_node(node))
        return binaries

    def get_data(self):
        data = []
        nodes = utils.node_get_elements_by_tag_name(self.root, "data")
        for node in nodes:
            data.append(Path.from_node(node))
        return data

if __name__ == '__main__':
    project = Project(os.path.join(os.getcwd(), 'giggle.bundle'))

    print("General:")
    print("  Project path: %s" % (project.get_project_path()))
    print("  Plist path: %s" % (project.get_plist_path()))
    print("  App name: %s" % (project.name))
    print("  Destination: %s" % (project.get_meta().dest))
    print("  Overwrite: %s" % (str(project.get_meta().overwrite)))

    environment = project.get_environment()
    print("Environment:")
    for variable in environment.runtime_variables:
        print("  %s=%s" % (variable.name, variable.value))
    for script in environment.scripts:
        print("  %s => %s" % (script.source, script.dest))

    print("Frameworks:")
    for framework in project.get_frameworks():
        print(" ", framework)

    print("Main binary:")
    binary = project.get_main_binary()
    print("  %s => %s" % (binary.source, binary.dest))

    print("Launcher:")
    launcher_script = project.get_launcher_script()
    print("  %s => %s" % (launcher_script.source, launcher_script.dest))

    print("Binaries:")
    for binary in project.get_binaries():
        print("  %s => %s" % (binary.source, binary.dest))
