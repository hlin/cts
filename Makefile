
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software # Foundation, either version 2 of the License, or
# (at your option) any later version.

SUBDIRS := odcs-server odcs-client odcs-common
ifdef WITH_SERVER
    SUBDIRS += Server
endif
ifdef WITH_LABCONTROLLER
    SUBDIRS += LabController
endif
ifdef WITH_INTTESTS
    SUBDIRS += IntegrationTests
endif

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
	tox -r -e py27,py35,flake8
