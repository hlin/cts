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
import koji

from mock import patch, MagicMock, call
from kobo.conf import PyConfigParser

from odcs.server.pungi import (Pungi, PungiConfig, PungiSourceType,
                               COMPOSE_RESULTS)
import odcs.server.pungi
from odcs.server import conf
from .utils import ConfigPatcher, AnyStringWith

test_dir = os.path.abspath(os.path.dirname(__file__))


class TestPungiConfig(unittest.TestCase):

    def setUp(self):
        super(TestPungiConfig, self).setUp()

    def tearDown(self):
        super(TestPungiConfig, self).tearDown()

    def _load_pungi_cfg(self, cfg):
        conf = PyConfigParser()
        conf.load_from_string(cfg)
        return conf

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
                                "f26", packages=["file"], sigkeys="123 456",
                                arches=["ppc64", "s390"])
        cfg = pungi_cfg.get_pungi_config()
        variants = pungi_cfg.get_variants_config()
        comps = pungi_cfg.get_comps_config()

        self.assertTrue(variants.find("<groups>") != -1)
        self.assertTrue(variants.find("ppc64") != -1)
        self.assertTrue(variants.find("s390") != -1)
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
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(cfg["release_name"], "MBS-512")
            self.assertEqual(cfg["release_short"], "MBS-512")
            self.assertEqual(cfg["release_version"], "1")
            self.assertTrue("createiso" in cfg["skip_phases"])
            self.assertTrue("buildinstall" in cfg["skip_phases"])

    @patch("odcs.server.pungi.log")
    def test_get_pungi_conf_exception(self, log):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        _, mock_path = tempfile.mkstemp(suffix='-pungi.conf')
        with open(mock_path, 'w') as f:
            # write an invalid jinja2 template file
            f.write('{{\n')
        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg.get_pungi_config()
            log.exception.assert_called_once()
        os.remove(mock_path)

    def test_get_pungi_conf_iso(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                    "testmodule-master",
                                    results=COMPOSE_RESULTS["iso"])
            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertTrue("createiso" not in cfg["skip_phases"])

    def test_get_pungi_conf_boot_iso(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                    "testmodule-master",
                                    results=COMPOSE_RESULTS["boot.iso"])
            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertTrue("buildinstall" not in cfg["skip_phases"])

    def test_get_pungi_conf_koji_inherit(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.KOJI_TAG,
                                    "f26")

            pungi_cfg.pkgset_koji_inherit = False
            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertFalse(cfg["pkgset_koji_inherit"])

            pungi_cfg.pkgset_koji_inherit = True
            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertTrue(cfg["pkgset_koji_inherit"])


class TestPungi(unittest.TestCase):

    def setUp(self):
        super(TestPungi, self).setUp()

        self.patch_download_file = patch("odcs.server.pungi.download_file")
        self.download_file = self.patch_download_file.start()

        self.compose = MagicMock()

    def tearDown(self):
        super(TestPungi, self).tearDown()

        self.patch_download_file.stop()

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run(self, execute_cmd):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        pungi = Pungi(pungi_cfg)
        pungi.run(self.compose)

        execute_cmd.assert_called_once_with(
            ['pungi-koji', AnyStringWith('pungi.conf'),
             AnyStringWith('--target-dir'), '--nightly'],
            cwd=AnyStringWith('/tmp/'), timeout=3600)

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run_raw_config(self, execute_cmd):
        pungi_cfg = "http://localhost/pungi.conf#hash"
        pungi = Pungi(pungi_cfg)
        pungi.run(self.compose)

        execute_cmd.assert_called_once()
        self.download_file.assert_called_once_with(
            "http://localhost/pungi.conf#hash", AnyStringWith("/raw_config.conf"))


class TestPungiRunroot(unittest.TestCase):

    def setUp(self):
        super(TestPungiRunroot, self).setUp()

        self.config_patcher = ConfigPatcher(odcs.server.auth.conf)
        self.config_patcher.patch('pungi_runroot_enabled', True)
        self.config_patcher.patch('pungi_parent_runroot_channel', 'channel')
        self.config_patcher.patch('pungi_parent_runroot_packages', ['pungi'])
        self.config_patcher.patch('pungi_parent_runroot_mounts', ['/mnt/odcs-secrets'])
        self.config_patcher.patch('pungi_parent_runroot_weight', 3.5)
        self.config_patcher.patch('pungi_parent_runroot_tag', 'f26-build')
        self.config_patcher.patch('pungi_parent_runroot_arch', 'x86_64')
        self.config_patcher.patch('pungi_runroot_target_dir', '/mnt/koji/compose/odcs')
        self.config_patcher.patch('pungi_runroot_target_dir_url', 'http://kojipkgs.fedoraproject.org/compose/odcs')
        self.config_patcher.start()

        self.patch_make_koji_session = patch("odcs.server.pungi.Pungi.make_koji_session")
        self.make_koji_session = self.patch_make_koji_session.start()
        self.koji_session = MagicMock()
        self.koji_session.runroot.return_value = 123
        self.make_koji_session.return_value = self.koji_session

        self.patch_unique_path = patch("odcs.server.pungi.Pungi._unique_path")
        unique_path = self.patch_unique_path.start()
        unique_path.return_value = "odcs/unique_path"

        def mocked_download_file(url, output_path):
            with open(output_path, "w") as fd:
                fd.write("fake pungi.conf")
        self.patch_download_file = patch("odcs.server.pungi.download_file")
        self.download_file = self.patch_download_file.start()
        self.download_file.side_effect = mocked_download_file

        self.compose = MagicMock()

    def tearDown(self):
        super(TestPungiRunroot, self).tearDown()
        self.config_patcher.stop()
        self.patch_make_koji_session.stop()
        self.patch_unique_path.stop()
        self.patch_download_file.stop()

        conf_topdir = os.path.join(conf.target_dir, "odcs/unique_path")
        shutil.rmtree(conf_topdir)

    def test_pungi_run_runroot(self):
        self.koji_session.getTaskInfo.return_value = {"state": koji.TASK_STATES["CLOSED"]}

        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule-master")
        pungi = Pungi(pungi_cfg)
        pungi.run(self.compose)

        conf_topdir = os.path.join(conf.target_dir, "odcs/unique_path")
        self.koji_session.uploadWrapper.assert_any_call(
            os.path.join(conf_topdir, 'pungi.conf'), 'odcs/unique_path', callback=None)
        self.koji_session.uploadWrapper.assert_any_call(
            os.path.join(conf_topdir, 'variants.xml'), 'odcs/unique_path', callback=None)
        self.koji_session.uploadWrapper.assert_any_call(
            os.path.join(conf_topdir, 'comps.xml'), 'odcs/unique_path', callback=None)

        self.koji_session.runroot.assert_called_once_with(
            'f26-build', 'x86_64',
            'cp /mnt/koji/work/odcs/unique_path/* . && '
            'cp ./odcs_koji.conf /etc/koji.conf.d/ && '
            'pungi-koji --config=./pungi.conf --target-dir=/mnt/koji/compose/odcs --nightly',
            channel='channel', mounts=['/mnt/odcs-secrets'], packages=['pungi'], weight=3.5)

        self.koji_session.taskFinished.assert_called_once_with(123)
        self.assertEqual(self.compose.koji_task_id, 123)

    def test_pungi_run_runroot_raw_config(self):
        self.koji_session.getTaskInfo.return_value = {"state": koji.TASK_STATES["CLOSED"]}

        pungi_cfg = "http://localhost/pungi.conf#hash"
        pungi = Pungi(pungi_cfg)
        pungi.run(self.compose)

        conf_topdir = os.path.join(conf.target_dir, "odcs/unique_path")
        self.koji_session.uploadWrapper.assert_has_calls(
            [call(os.path.join(conf_topdir, 'odcs_koji.conf'),
                  'odcs/unique_path', callback=None),
             call(os.path.join(conf_topdir, 'pungi.conf'),
                  'odcs/unique_path', callback=None),
             call(os.path.join(conf_topdir, 'raw_config.conf'),
                  'odcs/unique_path', callback=None)])

        self.koji_session.runroot.assert_called_once_with(
            'f26-build', 'x86_64',
            'cp /mnt/koji/work/odcs/unique_path/* . && '
            'cp ./odcs_koji.conf /etc/koji.conf.d/ && '
            'pungi-koji --config=./pungi.conf --target-dir=/mnt/koji/compose/odcs --nightly',
            channel='channel', mounts=['/mnt/odcs-secrets'], packages=['pungi'], weight=3.5)

        self.koji_session.taskFinished.assert_called_once_with(123)
        self.assertEqual(self.compose.koji_task_id, 123)
