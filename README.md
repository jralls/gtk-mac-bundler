# GTK Mac Bundler
  
The script **gtk-mac-bundler** is a helper script that creates application
bundles from GTK+ executables for Mac OS X. The resulting bundle
contains a complete self-hosting GTK+ installation, ready to run on any
computer running Mac OS X 10.4 or later.

GTK+ and its companion libraries are automatically put into the
bundle, but the application packager must tell the script what other
files and directories to copy.

**Note:** This tool is written to work with a jhbuild built GTK+, not
Macports. If you build with Macports, make sure that the Pango atsui
module is built in to the Pango library, by using the configure flag:

    --with-included-modules=basic-atsui.


## Setting up

Run `make install`; this installs the script into `~/bin` folder. Make sure you
have that directory in your `PATH`, or use the absolute path when starting
the script.


## Prerequisites

You need to have a GTK+ installation as done for example by using
jhbuild as described on the [GTK+ OS X project site](http://wiki.gnome.org/Projects/GTK%2B/OSX/Building)

The `gtk-mac-bundler` command needs to be run inside an environment
setup for running the GTK+, for example inside a jhbuild shell.

For the more in-depth parts described here, you are expected to be
familiar with the layout of OS X bundles.


## Quick introduction

You need to create a configuration file describing the application
bundle. The very simple example, `example.bundle`:

    <?xml version="1.0"?> <!--*- mode: xml -*-->
    <app-bundle>
      <meta>
        <prefix>/opt/gtk</prefix>
      </meta>
    
      <plist>${project}/Info.plist</plist>

      <!-- Optionally specify a launcher script to use. Builtin script is used if not specified.  -->
      <!--launcher-script>${project}/launcher.sh</launcher-script-->

      <!-- The executable for the application -->
      <main-binary>${prefix}/bin/my-app</main-binary>
    
      <!-- Modules for GTK+ (image loaders, etc) -->
      <binary>${prefix}/lib/gtk-2.0</binary>
    
      <!-- Any additional data, like images, or Glade files -->
      <data>
        ${prefix}/share/my-app
      </data>
    
    </app-bundle>

Put this file into a directory, together with the standard `Info.plist`
file that all Mac OS X bundles need. Then run the script with the
bundle configuration path as argument. This will create a bundle in
the current directory.


## In-depth look at file format

The simple example above works for small and simple applications, but
often you will need to specify more data to copy in, or to have more
detailed control over what is copied. 

Here we go through in more depth how this can be acheived. Every file
and directory to copy is specified with a source path, and an optional
destination path. An example that copies an entire directory
recursively, from the installation prefix:

    <data>
      ${prefix}/share/my-data
    </data>

Since no destination path is specified, the directory will be copied
into the standard location. Note that the special value `${prefix}` is
used in the source path, which makes the default destination path be
relative to the `bundle prefix`, which is the `Contents/Resources`
directory inside the bundle. Applications that use the free desktop
`data dir` specification to find their data will automatically find
its data this way (applications can also use the Carbon or Cocoa
bundle APIs to find data).

Another useful "special value" that can be used in source paths is
`${project}`, which refers to the directory where the XML file is
located. An example:

    <data dest="${bundle}/Contents/Resources/etc/gtk-2.0/gtkrc">
      ${project}/gtkrc
    </data>

Here you notice that a destination path is supplied. This must be done
since there is no way to figure out where to put the file that doesn't
come from a `${prefix}` location. You can also see another variable
used, this time in the destination path, `${bundle}`. All destination
paths must be either unset or start with `${bundle}`.

The remaining variables are:

 * `${env:name}` - evaluates to the environment variable `name`

 * `${pkg:module:name}` - evaluates to the value of the pkg-config
                      variable `name` in the module `module`

An example use case of the latter is for finding files that are
located in a versioned directory without having to maintain the
directory name manually. For example:

    <binary>
      ${prefix}/lib/gtk-2.0/${pkg:gtk+-2.0:gtk_binary_version}/loaders
    </binary>


## Metadata

Now that we know how paths can be specified, let's back up and see the
beginning of a more extensive example. The first thing to setup is some
metadata:

    <app-bundle>
    
      <meta>
        <prefix name="default">${env:PREFIX}</prefix>
        <destination overwrite="yes">${env:HOME}/Desktop</destination>
      </meta>
    
      [...]

    </app-bundle>

We use the `${env}` variable to get the installation prefix (which comes
from the **jhbuild** build script). We also use it to set the destination
of the app bundle on the current user's desktop.

You can set additional prefixes and refer to them in paths:

      <meta>
        <prefix name="default">${env:PREFIX}</prefix>
        <prefix name="gst">/opt/gstreamer</prefix>
        <prefix name="stuff">/opt/stuff</prefix>
      </meta>

The additional prefixes are referred to by using `${prefix:name}`, where
`name` is one of the names defined above.


## Installed data

Next you need to list the data to install. Some is required for the
app bundle to be complete:

    <plist>${project}/../data/Info.plist</plist>
    
    <launcher-script>${project}/launcher.sh</launcher-script>
    
    <main-binary>${prefix}/bin/giggle</main-binary>

The file `Info.plist` is the standard Mac OS file for bundles. See [documentation](https://developer.apple.com/library/content/documentation/General/Reference/InfoPlistKeyReference/Introduction/Introduction.html) on those.

The launcher script is used to setup the necessary environment for the
application to work. If your application does this itself, you can
leave it out. Many applications will work out of the box with the
launcher script though. If no script is specified in the tag, a
default one is used, that sets up the needed environent for most GTK+
applications.

Unsurprisingly, the main-binary tag specifies the executable to launch
when starting the application.


## General application data

Next we handle any general data to copy into the bundle. A
straight-forward example:

    <data dest="${bundle}/Contents/Resources">
      ${project}/Giggle.icns
    </data>
    
    <data dest="${bundle}/Contents/Resources/etc/gtk-2.0/gtkrc">
      ${project}/gtkrc
    </data>


## Binaries

When it comes to binaries (executables and loadable modules), the tag
`binary` should be used. The difference between `binary` and `data` is
that all copied binaries are scanned for library dependencies, which
are automatically copied into the bundle. This way, you only need to
list your executables and plugins. Again, an example:

    <binary>
      ${prefix}/lib/pango/${pkg:pango:pango_module_version}/modules/pango-basic-atsui.so
    </binary>

This will copy the ATSUI font module for Pango. This in turn will pull
in any needed libraries that it links to.

Note that you can use wildcards for all data and binary tags, but only
in the last path component, for example:

    <binary>
      ${prefix}/lib/gtk/2.10.0/loaders/*.so
    </binary>

An intereseting twist is that some libraries that are built as dylibs
are used as loadable modules. Dlopen doesn't have a problem with this,
it will cheerfully open either. The problem comes because unlike
Linux, Mac OS X uses different file extensions and formats, so libtool
will set up dlopen to search for **libfoo.so** after it built
**libfoo.dylib**. Libtool also makes **libfoo.la** which will tell dlopen
where to look, but **gtk-mac-bundler** deletes those files from the
application bundle. If you're bundling an app that needs **libfoo.la**,
just put it in a data element and **gtk-mac-integration** (version 0.5.2
and later) will copy it in *after* doing the `*.l?a cleanup: <data>
${prefix}/lib/libfoo*.la </data>`


## Code Signing

Until mid 2016 **gtk-mac-bundler** depended upon a launcher shell script
to configure the environment. You can still do this, but it causes
problems with code-signing. Apple recommends that one not install
scripts into the Contents/MacOS folder of a bundle, nor should one
attempt to sign scripts. Doing so will produce signatures that are
incompatible across different versions of MacOS.

That means that for compiled-executable programs you need to launch
first and then configure the environment before starting gettext,
Gtk+, and any other libraries that read the environment for their
configuration. There are a variety of ways to do this, including
adding a module which reads configuration data from MacOS's *'defaults'*
preferences system or reading a YAML (a.k.a *'ini'*) file and exporting
the results to the environment with `setenv()`.

For script-based programs one must create a small executable program
which prepares the interpreter, launches it, and points it at a
startup script which configutres the environment. Such a program,
written in C, is provided in `examples/python-launcher.c`; a companion
startup script, `gtk_launcher.py`, does the environment
configuration. `python-launcher.c` should work as-is for most python
programs; `gtk_launcher.py` will require a bit of specializing to work,
in particular the import statement and startup call at the end of
the file.

To build `python-launcher.c`, start a jhbuild shell for your target and run:

    gcc -L$PREFIX/lib `python-config --cflags --ldflags` -o $PREFIX/bin/your-launcher \path/to/gtk-mac-bundler/examples/python-launcher.c

Remove the `<launcher-script>` element from your bundle file and change
the main-binary element to:

     <main-binary>
         ${prefix}/bin/your-launcher
     </main-binary>
     
In this case, leaving the name as `your-launcher` will actually work:
The bundler will rename the file to the value of the
CFBundleExecutable key in `Info.plist`.

Copy `gtk_launcher.py` to the folder where your bundle file is, rename
it to your liking (`your_launcher.py`, from now on), and edit it as
necessary.

Add a data element for `your_launcher.py` to your bundle file:

    <data dest=${bundle}/Contents/Resources>
      ${project}/your_launcher.py
    </data>

Add the following key to the top dict in `Info.plist` for your project:
    
    <key>GtkOSXLaunchScriptFile</key>
    <string>your_launcher.py</string>


## Icon themes

GTK+ icon themes have their own tag, `icon-theme`. The name of the
theme (which currently must reside in the default prefix) specifies
which theme to copy, and the `icons` property specifies which icons to
copy. The valid values are:

  * `auto` - tries to copy all icons names that match strings in all
         copied binaries; this will not always work perfectly but is
         good for getting started, and for simple applications

  * `all` - copies all icons

  * `none` - copies no icons, this can be used in combination with
         specifying icons manually with a regular data tag; the icon
         theme itself must be listed in order to get the index theme
         copied and an icon cache generated

Note that the base theme `hicolor` is always copied, since it is
required by GTK+. An example:

    <icon-theme icons="auto">
      Tango
    </icon-theme>


## Debugging the bundle

In order to debug the created app bundle (most notably the launcher
script), you can set the environment variable `GTK_DEBUG_LAUNCHER` before
starting the applications directly from a terminal. e.g.:

    GTK_DEBUG_LAUNCHER=yes MyApp.app/Contents/MacOS/MyApp

This will print out the steps performed by the launcher script before
the application executable is started.

Note also that the Console.app program that comes with OS X is very
useful when debugging app bundle problems. You can use it to see any
output from the application the console log window.

To run the application under gdb, do:

    GTK_DEBUG_GDB=yes MyApp.app/Contents/MacOS/MyApp


## License

The script is Copyright (C) 2007, 2008 Imendio AB, and licensed under
the GNU General Public License version 2. Note that the resulting bundle created
by the script is not covered by that, each invidiual library has its
own license. See `COPYING` for more.
