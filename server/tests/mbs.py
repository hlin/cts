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
# Written by Jan Kaluza <jkaluza@redhat.com>

from functools import wraps
import json
import responses
from six.moves.urllib.parse import urlparse, parse_qs

from odcs.server import conf

import gi

gi.require_version("Modulemd", "2.0")
from gi.repository import Modulemd  # noqa: E402


def dump_mmd(mmd):
    mod_index = Modulemd.ModuleIndex.new()
    mod_index.add_module_stream(mmd)
    return mod_index.dump_to_string()


def make_module(name, stream, version, requires={}, mdversion=1, context=None, state=5):
    if mdversion == 1:
        mmd = Modulemd.ModuleStreamV1.new(name, stream)
    else:
        mmd = Modulemd.ModuleStreamV2.new(name, stream)
    mmd.set_version(version)
    mmd.set_context(context or "00000000")
    mmd.set_summary("foo")
    mmd.set_description("foo")
    mmd.add_module_license("GPL")

    if mdversion == 1:
        for req_name, req_stream in requires.items():
            mmd.add_runtime_requirement(req_name, req_stream)
    else:
        deps = Modulemd.Dependencies()
        for req_name, req_stream in requires.items():
            deps.add_runtime_stream(req_name, req_stream)
        mmd.add_dependencies(deps)

    return {
        "name": name,
        "stream": stream,
        "version": str(version),
        "context": context or "00000000",
        "modulemd": dump_mmd(mmd),
        "state": state,
    }


TEST_MBS_MODULES_MMDv1 = [
    # test_backend.py
    make_module("moduleA", "f26", 20170809000000, {"moduleB": "f26"}),
    make_module("moduleA", "f26", 20170805000000, {"moduleB": "f26"}),
    make_module("moduleB", "f26", 20170808000000, {"moduleC": "f26", "moduleD": "f26"}),
    make_module("moduleB", "f27", 2017081000000, {"moduleC": "f27"}),
    make_module("moduleC", "f26", 20170807000000, {"moduleD": "f26"}),
    make_module("moduleD", "f26", 20170806000000),
    # test_composerthread.py
    make_module("testmodule", "master", 20170515074418),
    make_module("testmodule", "master", 20170515074419),
]


TEST_MBS_MODULES_MMDv2 = [
    # test_backend.py
    make_module("moduleA", "f26", 20170809000000, {"moduleB": "f26"}, 2),
    make_module("moduleA", "f26", 20170805000000, {"moduleB": "f26"}, 2),
    make_module(
        "moduleB", "f26", 20170808000000, {"moduleC": "f26", "moduleD": "f26"}, 2
    ),
    make_module("moduleB", "f27", 2017081000000, {"moduleC": "f27"}, 2),
    make_module("moduleC", "f26", 20170807000000, {"moduleD": "f26"}, 2),
    make_module("moduleD", "f26", 20170806000000, {}, 2),
    # module builds in "done" state.
    make_module("testmodule", "master", 20180515074419, {}, 2, state=3),
    # test_composerthread.py
    make_module("testmodule", "master", 20170515074418, {}, 2),
    make_module("testmodule", "master", 20170515074419, {}, 2),
    # multiple contexts
    make_module("parent", "master", 1, {}, 2, context="a"),
    make_module("parent", "master", 1, {}, 2, context="b"),
    make_module("testcontexts", "master", 1, {"parent": "master"}, 2, context="a"),
    make_module("testcontexts", "master", 1, {"parent": "master"}, 2, context="b"),
]


def mock_mbs(mdversion=2):
    """
    Decorator that sets up a test environment so that calls to the MBS to look
    up modules are redirected to return results from the TEST_MODULES array
    above.
    """

    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            def handle_module_builds(request):
                query = parse_qs(urlparse(request.url).query)
                states = [int(s) for s in query["state"]]
                if "nsvc" in query:
                    nsvc = query["nsvc"][0]
                    nsvc_parts = nsvc.split(":")
                    nsvc_keys = ["name", "stream", "version", "context"]
                    nsvc_dict = {}
                    for key, part in zip(nsvc_keys, nsvc_parts):
                        nsvc_dict[key] = part
                else:
                    # Empty keys and dict in case nsvc is not specitified.
                    # This means no filtering based on the nsvc will be done.
                    nsvc_keys = []
                    nsvc_dict = {}

                if mdversion == 1:
                    modules = TEST_MBS_MODULES_MMDv1
                else:
                    modules = TEST_MBS_MODULES_MMDv2

                body = {"items": [], "meta": {"total": 0}}
                for module in modules:
                    skip = False
                    for key in nsvc_keys:
                        if key in nsvc_dict and nsvc_dict[key] != module[key]:
                            skip = True
                            break
                    if module["state"] not in states:
                        skip = True
                    if skip:
                        continue
                    body["items"].append(module)

                body["meta"]["total"] = len(body["items"])
                return (200, {}, json.dumps(body))

            responses.add_callback(
                responses.GET,
                conf.mbs_url + "/1/module-builds/",
                content_type="application/json",
                callback=handle_module_builds,
            )

            return f(*args, **kwargs)

        return responses.activate(wrapped)

    return wrapper
