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
import modulemd
import responses
from six.moves.urllib.parse import urlparse, parse_qs

from odcs.server import conf


def make_module(name, stream, version, requires={}):
    mmd = modulemd.ModuleMetadata()
    mmd.name = name
    mmd.stream = stream
    mmd.version = version
    mmd.requires.update(requires)

    return {
        'variant_id': name,
        'variant_version': stream,
        'variant_release': str(version),
        'variant_uid': name + '-' + stream + '-' + str(version),
        'modulemd': mmd.dumps()
    }


TEST_PDC_MODULES = [
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


def mock_pdc(f):
    """
    Decorator that sets up a test environment so that calls to the PDC to look up
    modules are redirected to return results from the TEST_MODULES array above.
    """

    @wraps(f)
    def wrapped(*args, **kwargs):
        def handle_unreleasedvariants(request):
            query = parse_qs(urlparse(request.url).query)
            variant_id = query['variant_id']
            variant_version = query['variant_version']
            variant_release = query.get('variant_release', None)

            body = []
            for module in TEST_PDC_MODULES:
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

        responses.add_callback(responses.GET, conf.pdc_url + '/unreleasedvariants/',
                               content_type='application/json',
                               callback=handle_unreleasedvariants)

        return f(*args, **kwargs)

    return responses.activate(wrapped)
