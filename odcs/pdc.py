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

import odcs.utils
from odcs import log


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
        Method which parses module NVR string and returns a module info
        dictionary instead.
        :param str module_str: string, the NV(R) of module
        """
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

    def get_latest_modules(self, **kwargs):
        """
        Query PDC with query parameters in kwargs and return a list of modules
        which contains latest modules of each (module_name, module_version).

        :param kwargs: query parameters in keyword arguments, should only provide
                    valid query parameters supported by PDC's module query API.
        :return: a list of modules
        """
        modules = self.get_modules(**kwargs)
        active = kwargs.get('active', 'true')
        latest_modules = []
        for (name, version) in set([(m.get('variant_name'), m.get('variant_version')) for m in modules]):
            mods = self.get_modules(variant_name=name, variant_version=version, active=active)
            latest_modules.append(sorted(mods, key=lambda x: x['variant_release']).pop())
        return list(filter(lambda x: x in latest_modules, modules))

    @odcs.utils.retry(wait_on=(requests.ConnectionError, BeanBagException), logger=log)
    def get_modules(self, **kwargs):
        """
        Query PDC with specified query parameters and return a list of modules.

        :param kwargs: query parameters in keyword arguments
        :return: a list of modules
        """
        modules = self.session['unreleasedvariants/'](page_size=-1, **kwargs)
        return modules
