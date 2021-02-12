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
from collections import defaultdict

from odcs.server.utils import retry, to_text_type
from odcs.server import log

import gi

gi.require_version("Modulemd", "2.0")
from gi.repository import Modulemd  # noqa: E402


class ModuleLookupError(Exception):
    pass


class MBS(object):
    def __init__(self, config):
        self.mbs_url = config.mbs_url.rstrip("/")

    @retry(wait_on=(requests.ConnectionError,), logger=log)
    def get_modules(self, **params):
        url = self.mbs_url + "/1/module-builds/"
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def get_latest_modules(
        self,
        nsvc,
        include_done=False,
        base_module_br_name=None,
        base_module_br_stream=None,
        base_module_br_stream_version_lte=None,
        base_module_br_stream_version_gte=None,
    ):
        """
        Query MBS and return the latest version of the module specified by nsvc.

        :param str nsvc: N:S:V[:C] of a module to include in a compose.
        :param bool include_done: When True, also module builds in the "done" state
            are included in a result.
        :param str base_module_br_name: The name of a base module the module buildrequires.
        :param str base_module_br_stream: The stream of a base module the module buildrequires.
        :param str base_module_br_stream_version_lte: The stream version of base module
            to compare less-than-equal.
        :param str base_module_br_stream_version_gte: The stream version of base module
            to compare greater-than-equal.
        :raises ModuleLookupError: if the module couldn't be found
        :return: the latest version of the module.
        """
        if not nsvc:
            # Return an empty list of no NSVC is defined.
            return []

        params = {
            "nsvc": nsvc,
            "state": [3, 5] if include_done else [5],  # 5 is "ready", 3 is "done".
            "verbose": True,  # Needed to get modulemd in response.
            "order_desc_by": "version",
        }
        if base_module_br_name:
            params.update({"base_module_br_name": base_module_br_name})
        if base_module_br_stream:
            params.update({"base_module_br_stream": base_module_br_stream})
        if base_module_br_stream_version_lte:
            params.update(
                {
                    "base_module_br_stream_version_lte": str(
                        base_module_br_stream_version_lte
                    )
                }
            )
        if base_module_br_stream_version_gte:
            params.update(
                {
                    "base_module_br_stream_version_gte": str(
                        base_module_br_stream_version_gte
                    )
                }
            )
        modules = self.get_modules(**params)

        # True if the module is "-devel" module.
        devel_module = False
        if not modules["meta"]["total"]:
            # In case this is "-devel" module, it won't be included in MBS,
            # but it exists as CG build in Koji. It therefore can be used
            # to generate the compose, but to actually find the MBS build,
            # we need to remove the "-devel" suffix from the NSVC.
            n = nsvc.split(":")[0]
            if n.endswith("-devel"):
                params["nsvc"] = n[: -len("-devel")] + params["nsvc"][len(n) :]
                modules = self.get_modules(**params)
                devel_module = True

        if not modules["meta"]["total"]:
            state_msg = "ready or done" if include_done else "ready"
            raise ModuleLookupError(
                "Failed to find module %s in %s state in the MBS." % (nsvc, state_msg)
            )

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
            if devel_module:
                # Add -devel to module metadata in case we are composing devel
                # module.
                module["name"] += "-devel"
                # Devel module always depend on the non-devel version
                mmd = Modulemd.ModuleStream.read_string(
                    module["modulemd"],
                    strict=True,
                    module_name=None,
                    module_stream=None,
                )
                mmd = mmd.upgrade(2)
                for dep in mmd.get_dependencies():
                    dep.add_runtime_stream(mmd.get_module_name(), mmd.get_stream_name())
                mod_index = Modulemd.ModuleIndex.new()
                mod_index.add_module_stream(mmd)
                module["modulemd"] = to_text_type(mod_index.dump_to_string())
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
            mmd = Modulemd.ModuleStream.read_string(
                module["modulemd"], strict=True, module_name=None, module_stream=None
            )
            mmd = mmd.upgrade(2)

            # Check runtime dependency (name:stream) of a module and if this
            # dependency is already in module_map/new_modules, do nothing.
            # But otherwise get the latest module in this name:stream from MBS
            # and add it to new_modules/module_map.
            for deps in mmd.get_dependencies():
                for name in deps.get_runtime_modules():
                    for stream in deps.get_runtime_streams(name):
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
        module_map = defaultdict(list)

        for module in modules:
            key = "%s:%s" % (module["name"], module["stream"])

            # In case this is the first module with this name:stream,
            # just add it to new_modules.
            old_modules = module_map[key]
            if not old_modules:
                module_map[key].append(module)
                new_modules.append(module)
                continue

            # Check if there is already this module in new_modules, but in
            # different version. If so, raise an exception.
            if module["version"] != old_modules[0]["version"]:
                raise ModuleLookupError(
                    "%s:%s:%s:%s conflicts with %s:%s:%s:%s"
                    % (
                        module["name"],
                        module["stream"],
                        module["version"],
                        module["context"],
                        old_modules[0]["name"],
                        old_modules[0]["stream"],
                        old_modules[0]["version"],
                        old_modules[0]["context"],
                    )
                )

            # Check if there is already this module in new_modules in the very
            # same context - do not add it there, because it would be duplicate.
            if module["context"] in [m["context"] for m in old_modules]:
                continue

            # Add it to new_modules/module_map.
            module_map[key].append(module)
            new_modules.append(module)

        if expand:
            added_module_list = new_modules
            while True:
                added_module_list = self._add_new_dependencies(
                    module_map, added_module_list
                )
                if len(added_module_list) == 0:
                    break
                new_modules.extend(added_module_list)

        return new_modules
