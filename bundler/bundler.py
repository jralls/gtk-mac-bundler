import sys
import os, errno, glob
import dircache, shutil
import re
from plistlib import Plist
from distutils import dir_util

from project import *
import utils

class Bundler:
    def __init__(self, project):
        self.project = project

        self.project_dir = project.get_project_dir()

        plist_path = self.project.get_plist_path()
        self.plist = Plist.fromFile(plist_path)

        # List of paths that should be recursively searched for
        # binaries that are used to find library dependencies.
        self.binary_paths = []

        # Create the bundle in a temporary location first and move it
        # to the final destination when done.
        dest = project.get_meta().dest
        self.bundle_path = os.path.join(dest, "." + project.get_name() + ".app")

    def recursive_rm(self, dirname):
        # Extra safety ;)
        if dirname in [ "/", os.getenv("HOME"), os.path.join(os.getenv("HOME"), "Desktop") ]:
            print "Eek, trying to remove a bit much, eh? (%s)" % (dirname)
            sys.exit(1)

        if not os.path.exists(dirname):
            return
        
        files = dircache.listdir(dirname)
        for file in files:
            path = os.path.join (dirname, file)
            if os.path.isdir(path):
                self.recursive_rm(path)
            else:
                retval = os.unlink(path)

        os.rmdir(dirname)

    def create_skeleton(self):
        utils.makedirs(self.project.get_bundle_path("Contents/Resources"))
        utils.makedirs(self.project.get_bundle_path("Contents/MacOS"))

    def create_pkglist(self):
        path = self.project.get_bundle_path("Contents", "PkgInfo")
        path = self.project.evaluate_path(path)
        f = open (path, "w")
        f.write(self.plist.CFBundleSignature)
        f.close()

    def copy_plist(self):
        path = Path(self.project.get_plist_path(),
                    self.project.get_bundle_path("Contents"))
        self.copy_path(path)

    def create_pango_setup(self):
        # Create a temporary pangorc file just for creating the
        # modules file with the right modules.
        modulespath = self.project.get_bundle_path("Contents/Resources/lib/pango/" +
                                                   "${pkg:pango:pango_module_version}/"+
                                                   "modules")
        modulespath = utils.evaluate_pkgconfig_variables (modulespath)

        import tempfile
        fd, tmp_filename = tempfile.mkstemp()
        f = os.fdopen(fd, "w")
        f.write("[Pango]\n")
        f.write("ModulesPath=" + modulespath)
        f.write("\n")
        f.close()

        cmd = "PANGO_RC_FILE=" + tmp_filename + " pango-querymodules"
        f = os.popen(cmd)

        path = self.project.get_bundle_path("Contents/Resources/etc/pango")
        utils.makedirs(path)
        fout = open(os.path.join(path, "pango.modules"), "w")

        prefix = self.project.get_bundle_path("Contents/Resources")

        for line in f:
            line = line.strip()
            if line.startswith("#"):
                continue

            # Replace the hardcoded bundle path with @executable_path...
            if line.startswith(prefix):
                line = line[len(prefix):]
                line = "@executable_path/../Resources" + line

            fout.write(line)
        fout.close()

        os.unlink(tmp_filename)

        # Create the final pangorc file
        path = self.project.get_bundle_path("Contents/Resources/etc/pango")
        utils.makedirs(path)
        f = open(os.path.join(path, "pangorc"), "w")
        f.write("[Pango]\n")
        f.write("ModuleFiles=./pango.modules\n")
        f.close()

    def create_gtk_immodules_setup(self):
        path = self.project.get_bundle_path("Contents/Resources")
        cmd = "GTK_EXE_PREFIX=" + path + " gtk-query-immodules-2.0"
        f = os.popen(cmd)

        path = self.project.get_bundle_path("Contents/Resources/etc/gtk-2.0")
        utils.makedirs(path)
        fout = open(os.path.join(path, "gtk.immodules"), "w")

        prefix = "\"" + self.project.get_bundle_path("Contents/Resources")

        for line in f:
            line = line.strip()
            if line.startswith("#"):
                continue

            # Replace the hardcoded bundle path with @executable_path...
            if line.startswith(prefix):
                line = line[len(prefix):]
                line = "\"@executable_path/../Resources" + line
            fout.write(line)
            fout.write("\n")
        fout.close()

    def create_gdk_pixbuf_loaders_setup(self):
        modulespath = self.project.get_bundle_path("Contents/Resources/lib/gtk-2.0/" +
                                                   "${pkg:gtk+-2.0:gtk_binary_version}/"+
                                                   "loaders")
        modulespath = utils.evaluate_pkgconfig_variables (modulespath)

        cmd = "GDK_PIXBUF_MODULEDIR=" + modulespath + " gdk-pixbuf-query-loaders"
        f = os.popen(cmd)

        path = self.project.get_bundle_path("Contents/Resources/etc/gtk-2.0")
        utils.makedirs(path)
        fout = open(os.path.join(path, "gdk-pixbuf.loaders"), "w")

        prefix = "\"" + self.project.get_bundle_path("Contents/Resources")

        for line in f:
            line = line.strip()
            if line.startswith("#"):
                continue

            # Replace the hardcoded bundle path with @executable_path...
            if line.startswith(prefix):
                line = line[len(prefix):]
                line = "\"@executable_path/../Resources" + line
            fout.write(line)
            fout.write("\n")
        fout.close()

    def copy_binaries(self, binaries):
        for path in binaries:
            dest = self.copy_path(path)

            self.binary_paths.append(dest)

            # Clean up duplicates
            self.binary_paths = list(set(self.binary_paths))

            # Clean out any libtool (*.la) files and static libraries
            if os.path.isdir(dest):
                for root, dirs, files in os.walk(dest):
                    for name in filter(lambda l: l.endswith(".la") or l.endswith(".a"), files):
                        os.remove(os.path.join(root, name))

    # Copies from Path.source to Path.dest, evaluating any variables
    # in the paths, and returns the real dest.
    def copy_path(self, Path):
        source = self.project.evaluate_path(Path.source)
        if Path.dest:
            dest = self.project.evaluate_path(Path.dest)
        else:
            # Source must begin with a prefix if we don't have a
            # dest. Skip past the source prefix and replace it with
            # the right bundle path instead.
            p = re.compile("^\${prefix(:.*?)?}/")
            m = p.match(Path.source)
            if m:
                relative_dest = self.project.evaluate_path(Path.source[m.end():])
                dest = self.project.get_bundle_path("Contents/Resources", relative_dest)
            else:
                print "Invalid bundle file, missing or invalid 'dest' property: " + Path.dest
                sys.exit(1)

        (dest_parent, dest_tail) = os.path.split(dest)
        utils.makedirs(dest_parent)

        # Check that the source only has wildcards in the last component.
        p = re.compile("[\*\?]")
        (source_parent, source_tail) = os.path.split(source)
        if p.search(source_parent):
            print "Can't have wildcards except in the last path component: " + source
            sys.exit(1)

        if p.search(source_tail):
            source_check = source_parent
        else:
            source_check = source
        if not os.path.exists(source_check):
            print "Cannot find source to copy: " + source
            sys.exit(1)

        # If the destination has a wildcard as last component (copied
        # from the source in dest-less paths), ignore the tail.
        if p.search(dest_tail):
            dest = dest_parent

        for globbed_source in glob.glob(source):
            try:
                if os.path.isdir(globbed_source):
                    #print "dir: %s => %s" % (globbed_source, dest)
                    dir_util.copy_tree (str(globbed_source), str(dest),
                                        preserve_mode=1,
                                        preserve_times=1,
                                        preserve_symlinks=1,
                                        update=1,
                                        verbose=1,
                                        dry_run=0)
                else:
                    #print "file: %s => %s" % (globbed_source, dest)
                    shutil.copy(globbed_source, dest)
            except EnvironmentError, e:
                if e.errno == errno.ENOENT:
                    print "Warning, source file missing: " + globbed_source
                elif e.errno == errno.EEXIST:
                    print "Warning, path already exits: " + dest
                else:
                    print "Error when copying file: " + globbed_source
                    sys.exit(1)
        return dest

    # Lists all the binaries copied in so far. Used in the library
    # dependency resolution and icon theme lookup.
    def list_copied_binaries(self):
        paths = []
        for path in self.binary_paths:
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    paths.extend(map(lambda l: os.path.join(root, l), files))
            else:
                paths.append(path)

        # FIXME: Should filter this list so it only contains .so,
        # .dylib, and executable binaries.
        #return filter(lambda l: l.endswith(".so") or l.endswith(".dylib") or os.access(l, os.X_OK), paths)
        return paths

    def resolve_library_dependencies(self):
        # Get the libraries we link to, filter out anything that
        # doesn't come from any of the prefixes we have declared. Then
        # copy in the resulting list, and repeat until the list
        # doesn't change. At that point, all dependencies are
        # resolved.
        n_iterations = 0
        n_paths = 0
        paths = self.list_copied_binaries()
        while n_paths != len(paths):
            cmds = [ "otool -L " ]
            for path in paths:
                cmds.append(path + " ")

            cmd = ''.join(cmds)
            f = os.popen(cmd)

            prefixes = self.project.get_meta().prefixes

            def relative_path_map(line):
                if not os.path.isabs(line):
                    # FIXME: Try all prefixes here.
                    return os.path.join(self.project.get_prefix(), "lib", line)
                return line

            def prefix_filter(line):
                if not "(compatibility" in line:
                    return False

                if line.startswith("/usr/X11"):
                    print "Warning, found X11 library dependency, you most likely don't want that:", line.strip().split()[0]

                if os.path.isabs(line):
                    for prefix in prefixes.values():
                        if prefix in line:
                            return True
                    
                    if not line.startswith("/usr/lib") and not line.startswith("/System/Library"):
                        print "Warning, library not available in any prefix:", line.strip().split()[0]

                    return False

                return True

            lines = filter(prefix_filter, [line.strip() for line in f])
            lines = map(relative_path_map, lines)

            p = re.compile("(.*\.dylib\.?.*)\s\(compatibility.*$")
            lines = utils.filterlines(p, lines)

            new_libraries = []
            for library in set(lines):
                # Replace the real path with the right prefix so we can
                # create a Path object.
                for (key, value) in prefixes.items():
                    if library.startswith(value):
                        path = Path("${prefix:" + key + "}" + library[len(value):])
                        new_libraries.append(path)

            n_paths = len(paths)
            n_iterations += 1
            if n_iterations > 10:
                print "Too many tries to resolve library dependencies"
                sys.exit(1)
            
            self.copy_binaries(new_libraries)
            paths = self.list_copied_binaries()

    def run_install_name_tool(self):
        print "Running install name tool"

        paths = self.list_copied_binaries()
        prefixes = self.project.get_meta().prefixes

        # First change all references in libraries.
        for prefix in prefixes:
            prefix_path = self.project.get_prefix(prefix)
            print "Going through prefix: " + prefix_path
            for path in paths:
                cmd = os.path.join(os.path.dirname(__file__), "run-install-name-tool-change.sh") + " " + path + " " + prefix_path
                f = os.popen(cmd)
                for line in f:
                    print line

        # Then change the id of all libraries. Skipping this part for now
        #for path in paths:
        #    cmd = os.path.join(os.path.dirname(__file__), "run-install-name-tool-id.sh") + " " + path
        #    print cmd
        #    f = os.popen(cmd)
        #    for line in f:
        #        print line

    def strip_debugging(self):
        paths = self.list_copied_binaries()
        for path in paths:
            if path.endswith(".dylib") or path.endswith(".so"):
                os.chmod(path, 0644)
                os.system("strip -x " + path + " 2>/dev/null")
                os.chmod(path, 0444)
            else:
                os.chmod(path, 0755)
                os.system("strip -ur " + path + " 2>/dev/null")
                os.chmod(path, 0555)

    def copy_icon_themes(self):
        all_icons = set()

        themes = self.project.get_icon_themes()

        for theme in themes:
            self.copy_path(Path(os.path.join(theme.source, "index.theme")))

        for theme in themes:
            if theme.icons == IconTheme.ICONS_NONE:
                continue
            
            for root, dirs, files in os.walk(self.project.evaluate_path(theme.source)):
                for f in files:
                    (head, tail) = os.path.splitext(f)
                    if tail in [".png", ".svg"]:
                        all_icons.add(head)

        strings = set()

        # Get strings from binaries.
        for f in self.list_copied_binaries():
            p = os.popen("strings " + f)
            for string in p:
                string = string.strip()
                strings.add(string)

        # FIXME: Also get strings from glade files.

        used_icons = all_icons.intersection(strings)
        prefix = self.project.get_prefix()

        for theme in themes:
            if theme.icons == IconTheme.ICONS_NONE:
                continue

            for root, dirs, files in os.walk(self.project.evaluate_path(theme.source)):
                for f in files:
                    # Go through every file, if it matches the icon
                    # set, copy it.
                    (head, tail) = os.path.splitext(f)
                    if head in used_icons or theme.icons == IconTheme.ICONS_ALL:
                        path = os.path.join(root, f)

                        # Note: Skipping svgs for now, they are really
                        # big and not really used.
                        if path.endswith(".svg"):
                            continue

                        # Replace the real paths with the prefix macro
                        # so we can use copy_path.
                        self.copy_path(Path("${prefix}" + path[len(prefix):]))

        # Generate icon caches.
        for theme in themes:
            path = self.project.get_bundle_path("Contents/Resources/share/icons", theme.name)
            cmd = "gtk-update-icon-cache -f " + path + " 2>/dev/null"
            os.popen(cmd)

    def run(self):
        # Remove the temp location forcefully.
        path = self.project.evaluate_path(self.bundle_path)
        self.recursive_rm(path)

        meta = self.project.get_meta()

        final_path = os.path.join(meta.dest, self.project.get_name() + ".app")
        final_path = self.project.evaluate_path(final_path)

        if not meta.overwrite and os.path.exists(final_path):
            print "Bundle already exists: " + final_path
            sys.exit(1)

        self.create_skeleton()
        self.create_pkglist()
        self.copy_plist()

        # Note: could move this to xml file...
        self.copy_path(Path("${prefix}/lib/charset.alias"))

        # Launcher script, if necessary.
        launcher_script = self.project.get_launcher_script()
        if launcher_script:
            self.copy_path(launcher_script)

        # Main binary
        path = self.project.get_main_binary()
        source = self.project.evaluate_path(path.source)
        if not os.path.exists(source):
            print "Cannot find main binary: " + source
            sys.exit(1)

        dest = self.copy_path(path)
        self.binary_paths.append(dest)

        # Additional binaries (executables, libraries, modules)
        self.copy_binaries(self.project.get_binaries())
        self.resolve_library_dependencies()

        # Data
        for path in self.project.get_data():
            self.copy_path(path)

        # Frameworks
        frameworks = self.project.get_frameworks()
        for path in frameworks:
            self.copy_path(path)

        self.copy_icon_themes()

        self.create_pango_setup()
        self.create_gtk_immodules_setup()
        self.create_gdk_pixbuf_loaders_setup()

        if meta.run_install_name_tool:
            self.run_install_name_tool()

        #self.strip_debugging()

        if meta.overwrite:
            self.recursive_rm(final_path)
        shutil.move(self.project.get_bundle_path(), final_path)

class App_Bundler(Bundler):
    pass

class FW_Bundler(Bundler):
    pass

class BundlerFactory:
    def get(self, project):
        bundle_type = project.get_bundle_type()
        if bundle_type == "app":
            return App_Bundler(project)
        elif bundle_type == "fw":
            return FW_Bundler(project)
        else:
            raise NameError('Invalid Bundle Type')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print "Usage: %s <bundle descriptopn file>" % (sys.argv[0])
        sys.exit(2)

    if not os.path.exists(sys.argv[1]):
        print "File %s does not exist" % (sys.argv[1])
        sys.exit(2)

    project = Project(sys.argv[1])
    bundler = Bundler(project)

    bundler.run()
