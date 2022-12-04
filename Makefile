PACKAGE = gtk-mac-bundler
VERSION = 0.7.4
OLD_VERSION = 0.7.3

DEVROOT?="$(HOME)"
bindir=$(DEVROOT)/.new_local/bin

all:
	@echo 'Run "make install" to install.'

install:
	@mkdir -p $(bindir)
	@sed "s,@PATH@,`pwd`,g" < gtk-mac-bundler.in > $(bindir)/gtk-mac-bundler
	@chmod a+x $(bindir)/gtk-mac-bundler

distdir = $(PACKAGE)-$(VERSION)
dist:
	if test -f Changelog; then \
		mv Changelog Changelog.old; \
	fi
	echo "Changes in version ${VERSION}:\n" > Changelog
	git log --format=" - %s (%aN)" --no-merges bundler-${OLD_VERSION}...HEAD >> Changelog
	echo "" >> Changelog
	cat Changelog.old >> Changelog
	rm Changelog.old
	-rm -rf $(distdir)
	mkdir $(distdir)
	cp -p README COPYING NEWS Changelog Makefile gtk-mac-bundler.in $(distdir)/
	mkdir $(distdir)/bundler
	cp -p bundler/*.py $(distdir)/bundler/
	cp -p bundler/*.sh $(distdir)/bundler/
	mkdir $(distdir)/examples
	cp -p examples/* $(distdir)/examples/
	chmod -R a+r $(distdir)
	tar czf $(distdir).tar.gz $(distdir)
	rm -rf $(distdir)

.PHONY: all install
