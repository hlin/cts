# -*- coding: utf-8 -*-

# Copyright (c) 2016  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

import imp
import os

from os import sys
from odcs.server import logger


def init_config(app):
    """
    Configure ODCS
    """
    config_module = None
    config_file = '/etc/odcs/config.py'
    config_section = 'DevConfiguration'

    # automagically detect production environment:
    #   - existing and readable config_file presets ProdConfiguration
    try:
        with open(config_file):
            config_section = 'ProdConfiguration'
    except:
        pass

    # try getting config_file from os.environ
    if 'ODCS_CONFIG_FILE' in os.environ:
        config_file = os.environ['ODCS_CONFIG_FILE']
    # try getting config_section from os.environ
    if 'ODCS_CONFIG_SECTION' in os.environ:
        config_section = os.environ['ODCS_CONFIG_SECTION']
    # TestConfiguration shall only be used for running tests, otherwise...
    if any(['nosetests' in arg or 'noserunner.py' in arg or 'py.test' in arg or 'pytest.py' in arg for arg in sys.argv]):
        config_section = 'TestConfiguration'
        from conf import config
        config_module = config
    # ...ODCS_DEVELOPER_ENV has always the last word
    # and overrides anything previously set before!
    # In any of the following cases, use configuration directly from ODCS
    # package -> /conf/config.py.

    elif ('ODCS_DEVELOPER_ENV' in os.environ and
          os.environ['ODCS_DEVELOPER_ENV'].lower() in (
            '1', 'on', 'true', 'y', 'yes')):
        config_section = 'DevConfiguration'
        from conf import config
        config_module = config
    # try loading configuration from file
    if not config_module:
        try:
            config_module = imp.load_source('odcs_runtime_config',
                                            config_file)
        except:
            raise SystemError("Configuration file {} was not found."
                              .format(config_file))

    # finally configure ODCS
    config_section_obj = getattr(config_module, config_section)
    conf = Config(config_section_obj)
    app.config.from_object(config_section_obj)
    return conf


class Config(object):
    """Class representing the odcs configuration."""
    _defaults = {
        'debug': {
            'type': bool,
            'default': False,
            'desc': 'Debug mode'},
        'log_backend': {
            'type': str,
            'default': None,
            'desc': 'Log backend'},
        'log_file': {
            'type': str,
            'default': '',
            'desc': 'Path to log file'},
        'log_level': {
            'type': str,
            'default': 0,
            'desc': 'Log level'},
        'net_timeout': {
            'type': int,
            'default': 120,
            'desc': 'Global network timeout for read/write operations, in seconds.'},
        'net_retry_interval': {
            'type': int,
            'default': 30,
            'desc': 'Global network retry interval for read/write operations, in seconds.'},
        'pdc_url': {
            'type': str,
            'default': '',
            'desc': 'PDC URL.'},
        'pdc_insecure': {
            'type': bool,
            'default': False,
            'desc': 'Allow insecure connection to PDC.'},
        'pdc_develop': {
            'type': bool,
            'default': False,
            'desc': 'PDC Development mode, basically noauth.'},
        'koji_profile': {
            'type': str,
            'default': None,
            'desc': 'Koji config profile.'},
        'arches': {
            'type': list,
            'default': ["x86_64"],
            'desc': 'Compose architectures.'},
        'pungi_koji': {
            'type': str,
            'default': "pungi-koji",
            'desc': 'Name or full-path to pungi-koji binary.'},
        'target_dir': {
            'type': str,
            'default': "./",
            'desc': 'Path to target dir to which store composes'},
        'target_dir_url': {
            'type': str,
            'default': "http://localhost/odcs",
            'desc': 'Public facing URL to target_dir.'},
        'seconds_to_live': {
            'type': int,
            'default': 24 * 60 * 60,
            'desc': 'Default number of seconds for which the compose is available.'},
        'max_seconds_to_live': {
            'type': int,
            'default': 72 * 60 * 60,
            'desc': 'Max number of seconds for which the compose is available.'},
        'num_concurrent_pungi': {
            'type': int,
            'default': 2,
            'desc': 'Number of concurrent Pungi processes.'},
        'auth_ldap_server': {
            'type': str,
            'default': '',
            'desc': "Server URL to query user's groups."},
        'auth_ldap_group_base': {
            'type': str,
            'default': '',
            'desc': "Group base to query user's groups from LDAP server."},
        'allowed_clients': {
            'type': dict,
            'default': {'groups': [], 'users': []},
            'desc': "Groups and users that are allowed to generate composes."},
        'admins': {
            'type': dict,
            'default': {'groups': [], 'users': []},
            'desc': "Admin groups and users."},
        'auth_backend': {
            'type': str,
            'default': 'noauth',
            'desc': "Select which authentication backend is enabled and work "
                    "with frond-end authentication together."},
        'auth_openidc_userinfo_uri': {
            'type': str,
            'default': '',
            'desc': 'UserInfo endpoint to get user information from FAS.'},
        'auth_openidc_required_scopes': {
            'type': list,
            'default': [],
            'desc': 'Required scopes for submitting request to run new compose.'},
        'authorize_disabled': {
            'type': bool,
            'default': False,
            'desc': 'Disable group based authorization.'},
    }

    def __init__(self, conf_section_obj):
        """
        Initialize the Config object with defaults and then override them
        with runtime values.
        """

        # set defaults
        for name, values in self._defaults.items():
            self.set_item(name, values['default'])

        # override defaults
        for key in dir(conf_section_obj):
            # skip keys starting with underscore
            if key.startswith('_'):
                continue
            # set item (lower key)
            self.set_item(key.lower(), getattr(conf_section_obj, key))

    def set_item(self, key, value):
        """
        Set value for configuration item. Creates the self._key = value
        attribute and self.key property to set/get/del the attribute.
        """
        if key == 'set_item' or key.startswith('_'):
            raise Exception("Configuration item's name is not allowed: %s" % key)

        # Create the empty self._key attribute, so we can assign to it.
        setattr(self, "_" + key, None)

        # Create self.key property to access the self._key attribute.
        # Use the setifok_func if available for the attribute.
        setifok_func = '_setifok_{}'.format(key)
        if hasattr(self, setifok_func):
            setx = lambda self, val: getattr(self, setifok_func)(val)
        else:
            setx = lambda self, val: setattr(self, "_" + key, val)
        getx = lambda self: getattr(self, "_" + key)
        delx = lambda self: delattr(self, "_" + key)
        setattr(Config, key, property(getx, setx, delx))

        # managed/registered configuration items
        if key in self._defaults:
            # type conversion for configuration item
            convert = self._defaults[key]['type']
            if convert in [bool, int, list, str, set, dict]:
                try:
                    # Do no try to convert None...
                    if value is not None:
                        value = convert(value)
                except:
                    raise TypeError("Configuration value conversion failed for name: %s" % key)
            # unknown type/unsupported conversion
            elif convert is not None:
                raise TypeError("Unsupported type %s for configuration item name: %s" % (convert, key))

        # Set the attribute to the correct value
        setattr(self, key, value)

    #
    # Register your _setifok_* handlers here
    #

    def _setifok_log_backend(self, s):
        if s is None:
            self._log_backend = "console"
        elif s not in logger.supported_log_backends():
            raise ValueError("Unsupported log backend")
        self._log_backend = str(s)

    def _setifok_log_file(self, s):
        if s is None:
            self._log_file = ""
        else:
            self._log_file = str(s)

    def _setifok_log_level(self, s):
        level = str(s).lower()
        self._log_level = logger.str_to_log_level(level)
