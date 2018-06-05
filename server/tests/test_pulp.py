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

import unittest
from mock import patch

from odcs.server.pulp import Pulp


@patch("odcs.server.pulp.Pulp._rest_post")
class TestPulp(unittest.TestCase):

    def test_generate_pulp_compose_arch_merge(self, pulp_rest_post):
        """
        Tests that multiple repos in single content_set are merged into
        single one by replacing arch with $basearch variable if possible.
        """
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                    "arch": "x86_64",
                    "signatures": "SIG1,SIG2",
                },
            },
            {
                "notes": {
                    "relative_url": "content/1/ppc64le/os",
                    "content_set": "foo-1",
                    "arch": "ppc64le",
                    "signatures": "SIG1,SIG2",
                }
            },
            {
                "notes": {
                    "relative_url": "content/3/ppc64/os",
                    "content_set": "foo-2",
                    "arch": "ppc64",
                    "signatures": "SIG1,SIG3",
                }
            }
        ]

        pulp = Pulp("http://localhost/", "user", "pass")
        ret = pulp.get_repos_from_content_sets(["foo-1", "foo-2"])
        self.assertEqual(
            ret,
            {
                "foo-1": {
                    "url": "http://localhost/content/1/$basearch/os",
                    "arches": set(["x86_64", "ppc64le"]),
                    "sigkeys": ["SIG1", "SIG2"],
                },
                "foo-2": {
                    "url": "http://localhost/content/3/ppc64/os",
                    "arches": set(["ppc64"]),
                    "sigkeys": ["SIG1", "SIG3"],
                }
            })
