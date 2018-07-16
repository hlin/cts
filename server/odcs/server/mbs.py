# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

import requests

import odcs.server.utils
from odcs.server import log

import gi
gi.require_version('Modulemd', '1.0') # noqa
from gi.repository import Modulemd


class ModuleLookupError(Exception):
    pass


class MBS(object):
    def __init__(self, config):
        self.mbs_url = config.mbs_url.rstrip("/")

    @odcs.server.utils.retry(wait_on=(requests.ConnectionError, ), logger=log)
    def get_modules(self, **params):
        url = self.mbs_url + "/1/module-builds/"
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def get_latest_modules(self, nsvc):
        """
        Query MBS and return the latest version of the module specified by nsvc.

        :param nsvc: N:S:V[:C] of a module to include in a compose.
        :raises ModuleLookupError: if the module couldn't be found
        :return: the latest version of the module.
        """
        params = {
            "nsvc": nsvc,
            "state": 5,  # 5 is "ready".
            "verbose": True,  # Needed to get modulemd in response.
            "order_desc_by": "version",
        }
        modules = self.get_modules(**params)

        if not modules["meta"]["total"]:
            raise ModuleLookupError(
                "Failed to find module %s in the MBS." % nsvc)

        ret = []
        # In case the nsvc is just "name:stream", there might be multiple
        # versions of a module in MBS response. The modules in response are
        # sorted DESC by version, so the latest module is always the first
        # one. So simply get the first module and add to `ret` all the next
        # modules in a response list which have the same version - this
        # basically adds all the contexts of the module with latest version
        # to `ret`.
        for module in modules["items"]:
            if ret and ret[0]["version"] != module["version"]:
                break
            ret.append(module)
        return ret

    def _add_new_dependencies(self, module_map, modules):
        """
        Helper for ``validate_module_list()`` - scans ``modules`` and adds any missing
        requirements to ``module_map``.

        :param module_map: dict mapping module name:stream to module.
        :param modules: the list of modules to scan for dependencies.
        :return: a list of any modules that were added to ``module_map``.
        """

        new_modules = []
        for module in modules:
            mmd = Modulemd.Module.new_from_string(module['modulemd'])
            mmd.upgrade()

            # Check runtime dependency (name:stream) of a module and if this
            # dependency is already in module_map/new_modules, do nothing.
            # But otherwise get the latest module in this name:stream from MBS
            # and add it to new_modules/module_map.
            for deps in mmd.get_dependencies():
                for name, streams in deps.get_requires().items():
                    for stream in streams.get():
                        key = "%s:%s" % (name, stream)
                        if key not in module_map:
                            new_module = self.get_latest_modules(key)
                            new_modules += new_module
                            module_map[key] = [new_modules]

        return new_modules

    def validate_module_list(self, modules, expand=True):
        """
        Given a list of modules as returned by `get_modules()`, checks that
        there are no conflicting duplicates, removes any exact duplicates,
        and if ``expand`` is set, recursively adds in required modules until
        all dependencies are specified.

        :param modules: a list of modules as returned by ``get_modules()`` or
                ``get_latest_module()``
        :param expand: if required modules should be included in the returned
                list.
        :return: the list of modules with deduplication and expansion.
        :raises ModuleLookupError: if a required module couldn't be found, or a
                conflict occurred when resolving dependencies.
        """

        # List of modules we are going to return.
        new_modules = []
        # Temporary dict with "name:stream" as key and list of module dicts
        # as value.
        module_map = {}

        for module in modules:
            key = "%s:%s" % (module['name'], module['stream'])

            # If this module is not in `new_modules` yet, add it there and
            # continue to next module.
            if key not in module_map:
                module_map[key] = [module]
                new_modules.append(module)
                continue

            # Check if there is already this module in new_modules, but in
            # different version. If so, raise an exception.
            old_modules = module_map[key]
            if (module['version'] != old_modules[0]['version']):
                raise ModuleLookupError(
                    "%s:%s:%s:%s conflicts with %s:%s:%s:%s" % (
                        module['name'], module["stream"], module["version"],
                        module["context"], old_modules[0]['name'],
                        old_modules[0]["stream"], old_modules[0]["version"],
                        old_modules[0]["context"]))
            else:
                module_map[key].append(module)

        if expand:
            added_module_list = new_modules
            while True:
                added_module_list = self._add_new_dependencies(module_map, added_module_list)
                if len(added_module_list) == 0:
                    break
                new_modules.extend(added_module_list)

        return new_modules
