
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software # Foundation, either version 2 of the License, or
# (at your option) any later version.

SUBDIRS := server client common

.PHONY: build
build:
	set -e; for i in $(SUBDIRS); do $(MAKE) -C $$i build; done

.PHONY: install
install:
	set -e; for i in $(SUBDIRS); do $(MAKE) -C $$i install; done

.PHONY: clean
clean:
	set -e; for i in $(SUBDIRS); do $(MAKE) -C $$i clean; done

.PHONY: check
check:
	# Hack swig opts to workaround m2crypto < 0.27 installation
	# failure under Fedora 26 python3.6
	SWIG_FEATURES=-I/usr/include/openssl/ tox -r -e py27,py3,flake8
