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
# Written by Owen Taylor <otaylor@redhat.com>

from functools import wraps
import json
import responses
from six.moves.urllib.parse import urlparse, parse_qs

from odcs.server import conf

import gi
gi.require_version('Modulemd', '1.0') # noqa
from gi.repository import Modulemd


def make_module(name, stream, version, requires={}, mdversion=1):
    mmd = Modulemd.Module()
    mmd.set_mdversion(mdversion)
    mmd.set_name(name)
    mmd.set_stream(stream)
    mmd.set_version(version)
    mmd.set_summary("foo")
    mmd.set_description("foo")
    licenses = Modulemd.SimpleSet()
    licenses.add("GPL")
    mmd.set_module_licenses(licenses)

    if mdversion == 1:
        mmd.set_requires(requires)
    else:
        deps = Modulemd.Dependencies()
        for req_name, req_stream in requires.items():
            deps.add_requires_single(req_name, req_stream)
        mmd.set_dependencies((deps, ))

    return {
        'variant_id': name,
        'variant_version': stream,
        'variant_release': str(version),
        'variant_uid': name + '-' + stream + '-' + str(version),
        'modulemd': mmd.dumps()
    }


TEST_PDC_MODULES_MMDv1 = [
    # test_backend.py
    make_module('moduleA', 'f26', 20170809000000,
                {'moduleB': 'f26'}),
    make_module('moduleA', 'f26', 20170805000000,
                {'moduleB': 'f26'}),

    make_module('moduleB', 'f26', 20170808000000,
                {'moduleC': 'f26', 'moduleD': 'f26'}),
    make_module('moduleB', 'f27', 2017081000000,
                {'moduleC': 'f27'}),

    make_module('moduleC', 'f26', 20170807000000,
                {'moduleD': 'f26'}),

    make_module('moduleD', 'f26', 20170806000000),

    # test_composerthread.py
    make_module('testmodule', 'master', 20170515074418),
    make_module('testmodule', 'master', 20170515074419)
]


TEST_PDC_MODULES_MMDv2 = [
    # test_backend.py
    make_module('moduleA', 'f26', 20170809000000,
                {'moduleB': 'f26'}, 2),
    make_module('moduleA', 'f26', 20170805000000,
                {'moduleB': 'f26'}, 2),

    make_module('moduleB', 'f26', 20170808000000,
                {'moduleC': 'f26', 'moduleD': 'f26'}, 2),
    make_module('moduleB', 'f27', 2017081000000,
                {'moduleC': 'f27'}, 2),

    make_module('moduleC', 'f26', 20170807000000,
                {'moduleD': 'f26'}, 2),

    make_module('moduleD', 'f26', 20170806000000, {}, 2),

    # test_composerthread.py
    make_module('testmodule', 'master', 20170515074418, {}, 2),
    make_module('testmodule', 'master', 20170515074419, {}, 2)
]


def mock_pdc(mdversion=2):
    """
    Decorator that sets up a test environment so that calls to the PDC to look up
    modules are redirected to return results from the TEST_MODULES array above.
    """
    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            def handle_unreleasedvariants(request):
                query = parse_qs(urlparse(request.url).query)
                variant_id = query['variant_id']
                variant_version = query['variant_version']
                variant_release = query.get('variant_release', None)

                if mdversion == 1:
                    modules = TEST_PDC_MODULES_MMDv1
                else:
                    modules = TEST_PDC_MODULES_MMDv2

                body = []
                for module in modules:
                    if module['variant_id'] not in variant_id:
                        continue
                    if module['variant_version'] not in variant_version:
                        continue
                    if variant_release is not None:
                        if module['variant_release'] not in variant_release:
                            continue

                    fields = query.get('fields', None)
                    if fields is not None:
                        return_module = {}
                        for field in fields:
                            return_module[field] = module[field]
                    else:
                        return_module = module

                    body.append(return_module)

                return (200, {}, json.dumps(body))

            responses.add_callback(
                responses.GET, conf.pdc_url + '/unreleasedvariants/',
                content_type='application/json',
                callback=handle_unreleasedvariants)

            return f(*args, **kwargs)

        return responses.activate(wrapped)
    return wrapper
