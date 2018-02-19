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

import inspect
import requests
import re

from pdc_client import PDCClient
from beanbag.bbexcept import BeanBagException

import odcs.server.utils
from odcs.server import log

import gi
gi.require_version('Modulemd', '1.0') # noqa
from gi.repository import Modulemd


class ModuleLookupError(Exception):
    pass


class PDC(object):
    def __init__(self, config):
        # pdc_url, pdc_develop and pdc_insecure should be avaiable in config
        self.config = config
        self.session = self.get_client_session()

    def get_client_session(self):
        """
        Return pdc_client.PDCClient instance
        """
        if 'ssl_verify' in inspect.getargspec(PDCClient.__init__).args:
            # New API
            return PDCClient(
                server=self.config.pdc_url,
                develop=self.config.pdc_develop,
                ssl_verify=not self.config.pdc_insecure,
            )
        else:
            # Old API
            return PDCClient(
                server=self.config.pdc_url,
                develop=self.config.pdc_develop,
                insecure=self.config.pdc_insecure,
            )

    def variant_dict_from_str(self, module_str):
        """
        Method which parses module NSV string and returns a module info
        dictionary instead.

        For more information about format of module_str, read:
        https://pagure.io/modularity/blob/master/f/source/development/
        building-modules/naming-policy.rst

        ODCS supports only N:S and N:S:V, because other combinations do not
        have sense for composes.

        :param str module_str: string, the NS(V) of module
        """

        # The new format can be distinguished by colon in module_str, because
        # there is not module in Fedora with colon in a name or stream and it is
        # now disallowed to create one. So if colon is there, it must be new
        # naming policy format.
        if module_str.find(":") != -1:
            module_info = {}
            module_info['variant_type'] = 'module'

            nsv = module_str.split(":")
            if len(nsv) > 3:
                raise ValueError(
                    "Module string \"%s\" is not allowed. "
                    "Only NAME:STREAM or NAME:STREAM:VERSION is allowed.")
            if len(nsv) > 2:
                module_info["variant_release"] = nsv[2]
            if len(nsv) > 1:
                module_info["variant_version"] = nsv[1]
            module_info["variant_id"] = nsv[0]
            return module_info
        else:
            # Fallback to previous old format with '-' delimiter.
            log.warn(
                "Variant file uses old format of module definition with '-'"
                "delimiter, please switch to official format defined by "
                "Modules Naming Policy.")

            module_info = {}
            # The regex is matching a string which should represent the release number
            # of a module. The release number is in format: "%Y%m%d%H%M%S"
            release_regex = re.compile("^(\d){14}$")

            section_start = module_str.rfind('-')
            module_str_first_part = module_str[section_start + 1:]
            if release_regex.match(module_str_first_part):
                module_info['variant_release'] = module_str_first_part
                module_str = module_str[:section_start]
                section_start = module_str.rfind('-')
                module_info['variant_version'] = module_str[section_start + 1:]
            else:
                module_info['variant_version'] = module_str_first_part
            module_info['variant_id'] = module_str[:section_start]
            module_info['variant_type'] = 'module'

            return module_info

    def get_latest_module(self, **kwargs):
        """
        Query PDC and return the latest version of the module specified by kwargs

        :param kwargs: query parameters in keyword arguments, should only provide
                    valid query parameters supported by PDC's module query API.
                    Must include 'variant_id' and 'variant_version'.
        :raises ModuleLookupError: if the module couldn't be found
        :return: the latest version of the module.
        """
        if 'active' not in kwargs:
            kwargs['active'] = True

        if 'variant_release' not in kwargs:
            # Ordering doesn't work
            # https://github.com/product-definition-center/product-definition-center/issues/439,
            # so if a release isn't specified, we have to get all builds and sort ourselves.
            # We do this two-step to avoid downloading modulemd for all builds.
            retval = self.get_modules(fields=['variant_release'], **kwargs)
            if not retval:
                raise ModuleLookupError(
                    "Failed to find module {variant_id}-{variant_version} in the PDC."
                    .format(**kwargs))
            kwargs['variant_release'] = str(max(int(d['variant_release']) for d in retval))

        retval = self.get_modules(**kwargs)
        if not retval:
            raise ModuleLookupError(
                "Failed to find module {variant_id}-{variant_version}-{variant_release} in the PDC."
                .format(**kwargs))
        if len(retval) > 1:
            raise ModuleLookupError(
                "Multiple modules found in the PDC for "
                "{variant_id}-{variant_version}-{variant_release}. "
                "This shouldn't happen, please contact the ODCS maintainers."
                .format(**kwargs))
        return retval[0]

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
            # But otherwise get the latest module in this name:stream from PDC
            # and add it to new_modules/module_map.
            for deps in mmd.get_dependencies():
                for name, streams in deps.get_requires().items():
                    for stream in streams.get():
                        key = "%s:%s" % (name, stream)
                        if key not in module_map:
                            new_module = self.get_latest_module(
                                variant_id=name, variant_version=stream)
                            new_modules.append(new_module)
                            module_map[key] = new_module

        return new_modules

    def validate_module_list(self, modules, expand=True):
        """
        Given a list of modules, checks that there are no conflicting duplicates,
        removes any exact duplicates, and if ``expand`` is set, recursively adds
        in required modules until all dependencies are specified.

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
        # Temporary dict with "name:stream" as key and module dict as value.
        module_map = {}

        for module in modules:
            key = "%s:%s" % (module['variant_id'], module['variant_version'])

            # If this module is not in `new_modules` yet, add it there and
            # continue to next module.
            if key not in module_map:
                module_map[key] = module
                new_modules.append(module)
                continue

            # Check if there is already this module in new_modules, but in
            # different version. If so, raise an exception.
            old_module = module_map[key]
            if (module['variant_release'] != old_module['variant_release']):
                raise ModuleLookupError("%s conflicts with %s" % (module['variant_uid'],
                                                                  old_module['variant_uid']))

        if expand:
            added_module_list = new_modules
            while True:
                added_module_list = self._add_new_dependencies(module_map, added_module_list)
                if len(added_module_list) == 0:
                    break
                new_modules.extend(added_module_list)

        return new_modules

    @odcs.server.utils.retry(wait_on=(requests.ConnectionError, BeanBagException), logger=log)
    def get_modules(self, **kwargs):
        """
        Query PDC with specified query parameters and return a list of modules.

        :param kwargs: query parameters in keyword arguments
        :return: a list of modules
        """
        modules = self.session['unreleasedvariants/'](page_size=-1, **kwargs)
        return modules
