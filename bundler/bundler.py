import sys
import os, errno, glob
import shutil
import re
from subprocess import Popen
from plistlib import Plist
from .project import *
from . import utils

class Bundler:
    def __init__(self, project):
        self.project = project

        self.project_dir = project.get_project_dir()

        plist_path = self.project.get_plist_path()
        self.plist = Plist.fromFile(plist_path)

        # List of paths that should be recursively searched for
        # binaries that are used to find library dependencies.
        self.binaries_to_copy = []
        self.copied_binaries = []
        #List of frameworks moved into the bundle which need to be set
        #up for private use.
        self.frameworks = []

        # Create the bundle in a temporary location first and move it
        # to the final destination when done.
        self.meta = project.get_meta()
        self.bundle_path = os.path.join(self.meta.dest, "." + project.get_bundle_name() + ".app")

    def recursive_rm(self, dirname):
        # Extra safety ;)
        if dirname in [ "/", os.getenv("HOME"), os.path.join(os.getenv("HOME"), "Desktop"), self.meta.dest ]:
            print("Eek, trying to remove a bit much, eh? (%s)" % (dirname))
            sys.exit(1)

        if not os.path.exists(dirname):
            return

        files = os.listdir(dirname)
        for file in files:
            path = os.path.join (dirname, file)
            if os.path.isdir(path):
                self.recursive_rm(path)
            else:
                retval = os.unlink(path)
        if (os.path.islink(dirname)):
            os.unlink(dirname)
        else:
            os.rmdir(dirname)

    def create_skeleton(self):
        utils.makedirs(self.project.get_bundle_path("Contents/Resources"))
        utils.makedirs(self.project.get_bundle_path("Contents/MacOS"))

    def create_pkglist(self):
        path = self.project.get_bundle_path("Contents", "PkgInfo")
        path = self.project.evaluate_path(path)
        f = open (path, "w")
        f.write(self.plist.CFBundlePackageType)
        f.write(self.plist.CFBundleSignature)
        f.close()

    def copy_plist(self):
        path = Path(self.project.get_plist_path(),
                    self.project.get_bundle_path("Contents/Info.plist"))
        path.copy_target(self.project)
    def run_module_catalog(self, env_var, env_val, exe_name):
        exepath = self.project.evaluate_path('${prefix}/bin/%s' % exe_name)
        temppath = self.project.get_bundle_path('Contents/MacOS/', exe_name)
        path = Binary(exepath, temppath)
        path.copy_target(self.project)

        local_env = os.environ.copy()
        local_env[env_var] = env_val
        p = Popen(temppath, env=local_env, stdout=PIPE)
        f = p.communicate()[0].splitlines()
        os.remove(temppath)
        return f

    def create_pango_setup(self):
        if utils.has_pkgconfig_module("pango") and \
                not utils.has_pkgconfig_variable("pango", "pango_module_version"):
            # Newer pango (>= 1.38) no longer has modules, skip this
            # step in that case.
            return

        # Create a temporary pangorc file just for creating the
        # modules file with the right modules.
        module_version = utils.evaluate_pkgconfig_variables("${pkg:pango:pango_module_version}")
        module_dir = 'Resources' if self.project.have_binaries else 'Plugins'
        modules_path = os.path.join('Contents', module_dir, 'lib', 'pango',
                                    module_version, 'modules')
        modulespath = self.project.get_bundle_path(modules_path)

        from distutils.version import StrictVersion as V
        import tempfile

        fd, tmp_filename = tempfile.mkstemp()
        f = os.fdopen(fd, "w")
        f.write("[Pango]\n")
        f.write("ModulesPath=" + modulespath)
        f.write("\n")
        f.close()

        env_var = "PANGO_RC_FILE"
        f = self.run_module_catalog(env_var, tmp_filename, 'pango-querymodules')

        path = self.project.get_bundle_path("Contents/Resources/etc/pango")
        utils.makedirs(path)
        fout = open(os.path.join(path, "pango.modules"), "w")

        if V(module_version) < V('1.8.0'):
            prefix_path  = os.path.join("Contents", module_dir)
        else:
            prefix_path = modules_path

        prefix = self.project.get_bundle_path(prefix_path)

        for line in f:
            line = line.strip()
            if line.startswith("# ModulesPath"):
                continue

            # Replace the hardcoded bundle path with @executable_path...
            if line.startswith(prefix):
                line = line[len(prefix):]
#Newer versions of pango have been modified to look in the right place
#for modules (providing the PANGO_LIB_DIR is set to point to the
#bundle_lib folder).
                if V(module_version) < V('1.8.0'):
                    line = "@executable_path/../" + module_dir + line

            fout.write(line)
            fout.write("\n")
        fout.close()

        os.unlink(tmp_filename)

        # Create the final pangorc file
        f = open(os.path.join(path, "pangorc"), "w")
        f.write("[Pango]\n")
#Pango 2.32 (corresponding to module_version 1.8.0) and later don't
#interpret "./" to mean the same directory that the rc file is in, so
#this doesn't work any more. However, pango does know to look in the
#bundle directory (when given the right environment variable), so we
#don't need this, either.
        if V(module_version) < V('1.8.0'):
            f.write("ModuleFiles=./pango.modules\n")
        f.close()

    def create_gtk_immodules_setup(self):
        module_dir = 'Resources' if self.project.have_binaries else 'Plugins'
        path = self.project.get_bundle_path(os.path.join('Contents', module_dir))
        env_var = "GTK_EXE_PREFIX"
        exe_name = 'gtk-query-immodules-' + self.project.get_gtk_version()
        f = self.run_module_catalog(env_var, path, exe_name)

        path = self.project.get_bundle_path("Contents/Resources/etc/",
                                            self.project.get_gtk_dir())
        utils.makedirs(path)
        fout = open(os.path.join(path, "gtk.immodules"), "w")

        prefix = "\"" + self.project.get_bundle_path("Contents", module_dir)

        for line in f:
            line = line.strip()
            if line.startswith("#"):
                continue

            # Replace the hardcoded bundle path with @executable_path...
            if line.startswith(prefix):
                line = line[len(prefix):]
                line = "\"@executable_path/../%s/%s" % (module_dir, line)
            fout.write(line)
            fout.write("\n")
        fout.close()

    def create_gdk_pixbuf_loaders_setup(self):
        module_dir = 'Resources' if self.project.have_binaries else 'Plugins'
        pixbuf_ver = ''
        if os.path.exists(os.path.join(self.project.get_prefix(), "lib",
                                       "gdk-pixbuf-2.0")):
            pixbuf_ver = 'gdk-pixbuf-2.0'
        elif os.path.exists(os.path.join(self.project.get_prefix(), "lib",
                                       "gdk-pixbuf-3.0")):
            pixbuf_ver = 'gdk-pixbuf-3.0'
        else:
            raise RuntimeError("No supported gdk-pixbuf modules directory found.")

        pixbuf_bin_ver = '${pkg:' + pixbuf_ver + ':gdk_pixbuf_binary_version}'
        module_path = os.path.join('Contents', module_dir, 'lib', pixbuf_ver,
                                   pixbuf_bin_ver)
        cache_path = os.path.join('Contents', 'Resources', 'lib', pixbuf_ver,
                                   pixbuf_bin_ver)

        modulespath = self.project.get_bundle_path(module_path, 'loaders')
        cachepath = self.project.get_bundle_path(cache_path, "loaders.cache")

        modulespath = utils.evaluate_pkgconfig_variables (modulespath)
        cachepath = utils.evaluate_pkgconfig_variables (cachepath)

        env_var = 'GDK_PIXBUF_MODULEDIR'
        f = self.run_module_catalog(env_var, modulespath,
                                    'gdk-pixbuf-query-loaders')

        utils.makedirs(os.path.dirname(cachepath))
        fout = open(cachepath, "w")

        prefix = "\"" + self.project.get_bundle_path("Contents", module_dir)
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                continue

            # Replace the hardcoded bundle path with @executable_path...
            if line.startswith(prefix):
                line = line[len(prefix):]
                line = "\"@executable_path/../%s/%s" % (module_dir, line)
            fout.write(line)
            fout.write("\n")
        fout.close()

    def copy_binaries(self):
        #clean up duplicates
        binaries = list(set(self.binaries_to_copy))
        for path in binaries:
            if not isinstance(path, Path):
                print("Warning, %s not a Path object, skipping." % path)
                continue
            if os.path.islink(path.source):
                continue
            if (path.compute_destination(self.project) in binaries):
                continue
            copied_paths = path.copy_target(self.project)
            if isinstance(copied_paths, basestring):
                print("Warning: copy_target returned string %s" % copied_paths)
                copied_paths = [copied_paths]
            bad_paths = [p for p in copied_paths if (p.endswith('.la')
                                                     or p.endswith('.a'))]
            for path in bad_paths:
                os.remove(path)
                copied_paths.remove(path)
            self.copied_binaries.extend(copied_paths)


    def list_copied_binaries(self):
        def filter_path(path):
            if os.path.islink(path):
                return False
            if path.endswith(".so") or path.endswith(".dylib") or os.access(path, os.X_OK):
                return True
            return False

        paths = []
        for path in self.copied_binaries:
            try:
                if os.path.isdir(path):
                    print ("Recursing down copied binary path %s." % path)
                    for root, dirs, files in os.walk(path):
                        paths.extend([os.path.join(root, l) for l in files])
                    else:
                        paths.append(path)
            except TypeError as err:
                if isinstance(path, Path):
                    print("Warning, Path object for %s in copied binaries list."
                          % path.source)
                else:
                    print("Warning: Wrong object of type %s in copied_binaries list."
                      % type(path))
                continue

        paths = list(filter(filter_path, paths))
        return list(set(paths))

    def resolve_library_dependencies(self):
        # Get the libraries we link to, filter out anything that
        # doesn't come from any of the prefixes we have declared. Then
        # copy in the resulting list, and repeat until the list
        # doesn't change. At that point, all dependencies are
        # resolved.
        n_iterations = 0
        n_paths = 0
        paths = self.binaries_to_copy

        def relative_path_map(line):
            if not os.path.isabs(line):
                for prefix in list(prefixes.values()):
                    path = os.path.join(prefix, "lib", line)
                    if os.path.exists(path):
                        return path
                print("Cannot find a matching prefix for %s" % (line))
            return line

        def prefix_filter(line):
            if not "(compatibility" in line:
                #print "Removed %s" % line
                return False

            if line.startswith("/usr/X11"):
                print("Warning, found X11 library dependency, you most likely don't want that:", line.strip().split()[0])

            if os.path.isabs(line):
                for prefix in list(prefixes.values()):
                    if prefix in line:
                        return True

                if not line.startswith("/usr/lib") and not line.startswith("/System/Library"):
                    print("Warning, library not available in any prefix:",
                          line.strip().split()[0])
                return False

            return True

        while n_paths != len(paths):
            cmds = ['otool', '-L']
            binaries= []
            for path in paths:
                if isinstance(path, Path):
                    source = path.compute_source_path(self.project)
                    if path.is_source_glob():
                        dir, pattern = os.path.split(source)
                        for root, dirs, files in os.walk(dir):
                            for item in glob.glob(os.path.join(root, pattern)):
                                binaries.append(os.path.join(root, item))
                    elif os.path.isdir(source):
                        for root, dirs, files in os.walk(source):
                            for item in glob.glob(os.path.join(root, '*.so')):
                                binaries.append(os.path.join(root, item))
                            for item in glob.glob(os.path.join(root, '*.dylib')):
                                binaries.append(os.path.join(root, item))
                    else:
                        binaries.append(source)
                else:
                    binaries.append(path)

            if not binaries:
                break
            cmds.extend(binaries)
            f = Popen(cmds, stdout=PIPE, stderr=PIPE)
            results, errors = f.communicate()
            if errors:
                print("otool errors:\n%s" % errors)
            prefixes = self.meta.prefixes
            lines = list(filter(prefix_filter,
                                [line.strip() for line in results.splitlines()]))
            p = re.compile("(.*\.dylib\.?.*)\s\(compatibility.*$")
            lines = utils.filterlines(p, lines)
            lines = list(map(relative_path_map, lines))
            new_libraries = []
            for library in set(lines):
                # Replace the real path with the right prefix so we can
                # create a Path object.
                for (key, value) in list(prefixes.items()):
                    if library.startswith(value):
                        if (self.project.have_binaries):
                            path = Binary("${prefix:" + key + "}" + library[len(value):])
                        else:
                            path = Library("${prefix:" + key + "}" + library[len(value):])
                        new_libraries.append(path)

            n_paths = len(paths)
            n_iterations += 1
            if n_iterations > 10:
                print("Too many tries to resolve library dependencies")
                sys.exit(1)

            self.binaries_to_copy.extend(new_libraries)
            paths = new_libraries


#
# If you want to sign your application, set $APPLICATION_CERT with the
# appropriate certificate name in your default Keychain. This function
# will sign every binary in the bundle with the certificate and the
# bundle's id string.
#

    def copy_icon_themes(self):
        all_icons = set()

        themes = self.project.get_icon_themes()

        for theme in themes:
            theme.copy_target
            all_icons |= theme.enumerate_icons(self.project)

        strings = set()

        # Get strings from binaries.
        for f in self.list_copied_binaries():
            p = os.popen("strings " + f)
            for string in p:
                string = string.strip()
                strings.add(string)

        # FIXME: Also get strings from glade files.

        used_icons = all_icons.intersection(strings)
        for theme in themes:
            theme.copy_icons(self.project, used_icons)

    def copy_translations(self):
        for translation in self.project.get_translations():
            translation.copy_target(self.project)

    def install_gir(self):
        if not self.project.get_gir():
            return
        gir_dest = self.project.get_bundle_path('Contents', 'Resources',
                                                'share', 'gir-1.0')
        typelib_dest = self.project.get_bundle_path('Contents', 'Resources',
                                                    'lib', 'girepository-1.0')
        lib_path = os.path.join(self.project.get_prefix(), 'lib')
        utils.makedirs(gir_dest)
        utils.makedirs(typelib_dest)

        for gir in self.project.get_gir():
            self.binaries_to_copy.extend(gir.copy_target(self.project, gir_dest,
                                                     typelib_dest, lib_path))

    def run(self):
        # Remove the temp location forcefully.
        path = self.project.evaluate_path(self.bundle_path)
        self.recursive_rm(path)

        final_path = os.path.join(self.meta.dest, self.project.get_bundle_name() + ".app")
        final_path = self.project.evaluate_path(final_path)

        if not self.meta.overwrite and os.path.exists(final_path):
            print("Bundle already exists: " + final_path)
            sys.exit(1)

        self.create_skeleton()
        self.create_pkglist()
        self.copy_plist()

        # Note: could move this to xml file...
        Path("${prefix}/lib/charset.alias").copy_target(self.project)

        # Main binary
        main_binary_path = self.project.get_main_binary()
        source = self.project.evaluate_path(main_binary_path.source)
        if not os.path.exists(source):
            print("Cannot find main binary: " + source)
            sys.exit(1)

        self.binaries_to_copy.append(main_binary_path)
        self.binaries_to_copy.extend(self.project.get_binaries())
        self.resolve_library_dependencies()
        self.binaries_to_copy.remove(main_binary_path)

        # Additional binaries (executables, libraries, modules)
        self.copy_binaries()
        self.resolve_library_dependencies()

        # Gir and Typelibs
        self.install_gir()

        # Data
        for path in self.project.get_data():
            path.copy_target(self.project)

        # Translations
        self.copy_translations()

        # Frameworks
        frameworks = self.project.get_frameworks()
        for path in frameworks:
            dest = path.copy_target(self.project)
            self.frameworks.append(dest)

        self.copy_icon_themes()

        self.create_pango_setup()
        self.create_gtk_immodules_setup()
        self.create_gdk_pixbuf_loaders_setup()

        main_binary_path.copy_target(self.project)

        # Launcher script, if necessary.
        launcher_script = self.project.get_launcher_script()
        if launcher_script:
            path = launcher_script.copy_target(self.project)
            if "APPLICATION_CERT" in os.environ:
                cert = os.environ["APPLICATION_CERT"]
                ident = self.project.get_bundle_id()
                cmdargs = ['codesign', '-s', cert, '-i', ident, "-f", path]
                result = os.spawnvp(os.P_WAIT, 'codesign', cmdargs)
                if result:
                    raise OSError('"'+ " ".join(cmdargs) + '" failed %d' % result)

        if self.meta.overwrite:
            self.recursive_rm(final_path)
        shutil.move(self.project.get_bundle_path(), final_path)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: %s <bundle descriptopn file>" % (sys.argv[0]))
        sys.exit(2)

    if not os.path.exists(sys.argv[1]):
        print("File %s does not exist" % (sys.argv[1]))
        sys.exit(2)

    project = Project(sys.argv[1])
    bundler = Bundler(project)

    bundler.run()
