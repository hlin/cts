# -*- coding: utf-8 -*-
#
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

import unittest

from mock import patch

from odcs.pungi import Pungi, PungiConfig, PungiSourceType


class TestPungiConfig(unittest.TestCase):

    def setUp(self):
        pass

    def test_pungi_config_module(self):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        pungi_cfg.get_pungi_config()
        variants = pungi_cfg.get_variants_config()
        comps = pungi_cfg.get_comps_config()

        self.assertTrue(variants.find("<module>") != -1)
        self.assertEqual(comps, "")

    def test_pungi_config_tag(self):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.KOJI_TAG,
                                "f26", packages=["file"])
        pungi_cfg.get_pungi_config()
        variants = pungi_cfg.get_variants_config()
        comps = pungi_cfg.get_comps_config()

        self.assertTrue(variants.find("<groups>") != -1)
        self.assertTrue(comps.find("file</packagereq>") != -1)


class TestPungi(unittest.TestCase):

    def setUp(self):
        pass

    @patch("odcs.utils.execute_cmd")
    def test_pungi_run(self, execute_cmd):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        pungi = Pungi(pungi_cfg)
        pungi.run()

        execute_cmd.assert_called_once()
