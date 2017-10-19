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

import os
import shutil
import tempfile
import unittest

from mock import patch

import odcs.server
from odcs.server.pungi import Pungi, PungiConfig, PungiSourceType

test_dir = os.path.abspath(os.path.dirname(__file__))


class TestPungiConfig(unittest.TestCase):

    def setUp(self):
        super(TestPungiConfig, self).setUp()
        patched_pungi_conf_path = os.path.join(test_dir, '../conf/pungi.conf')
        self.patch_pungi_conf_path = patch.object(odcs.server.conf,
                                                  'pungi_conf_path',
                                                  new=patched_pungi_conf_path)
        self.patch_pungi_conf_path.start()

    def tearDown(self):
        super(TestPungiConfig, self).tearDown()
        self.patch_pungi_conf_path.stop()

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
                                "f26", packages=["file"], sigkeys="123 456")
        cfg = pungi_cfg.get_pungi_config()
        variants = pungi_cfg.get_variants_config()
        comps = pungi_cfg.get_comps_config()

        self.assertTrue(variants.find("<groups>") != -1)
        self.assertTrue(comps.find("file</packagereq>") != -1)
        self.assertTrue(cfg.find("sigkeys = [\"123\", \"456\"]"))

    def test_get_pungi_conf(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                    "testmodule-master")
            template = pungi_cfg.get_pungi_config()
            self.assertTrue(len(template))
            self.assertTrue("release_name = 'MBS-512'" in template)
            self.assertTrue("release_short = 'MBS-512'" in template)
            self.assertTrue("release_version = '1'" in template)

    @patch("odcs.server.pungi.log")
    def test_get_pungi_conf_exception(self, log):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        mock_path = "/tmp/non_existant_pungi_conf"
        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg.get_pungi_config()
            log.exception.assert_called_once()


class TestPungi(unittest.TestCase):

    def setUp(self):
        super(TestPungi, self).setUp()
        patched_pungi_conf_path = os.path.join(test_dir, '../conf/pungi.conf')
        self.patch_pungi_conf_path = patch.object(odcs.server.conf,
                                                  'pungi_conf_path',
                                                  new=patched_pungi_conf_path)
        self.patch_pungi_conf_path.start()

    def tearDown(self):
        super(TestPungi, self).tearDown()
        self.patch_pungi_conf_path.stop()

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run(self, execute_cmd):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        pungi = Pungi(pungi_cfg)
        pungi.run()

        execute_cmd.assert_called_once()
