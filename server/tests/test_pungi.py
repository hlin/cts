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
import time

from mock import patch, MagicMock, mock_open, call
from kobo.conf import PyConfigParser

from odcs.server.pungi import (
    Pungi, PungiConfig, PungiSourceType, PungiLogs, RawPungiConfig)
from odcs.server import conf, db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_STATES, COMPOSE_RESULTS, COMPOSE_FLAGS
from odcs.server.utils import makedirs
from .utils import AnyStringWith, ModelsBaseTest

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
        pungi_cfg = PungiConfig(
            "MBS-512",
            "1",
            PungiSourceType.MODULE,
            "testmodule:master:1:1",
            module_defaults_url="git://localhost.tld/x.git master",
        )
        cfg = pungi_cfg.get_pungi_config()
        variants = pungi_cfg.get_variants_config()
        comps = pungi_cfg.get_comps_config()

        self.assertTrue(variants.find("<module>") != -1)
        self.assertEqual(comps, "")
        self.assertEqual(
            self._load_pungi_cfg(cfg)["module_defaults_dir"],
            {
                "branch": "master",
                "dir": ".",
                "repo": "git://localhost.tld/x.git",
                "scm": "git",
            },
        )

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
                                    "testmodule:master:1:1")
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
                                "testmodule:master:1:1")
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
                                    "testmodule:master:1:1",
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
                                    "testmodule:master:1:1",
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

    def test_get_pungi_conf_check_deps(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.KOJI_TAG,
                                    "f26")

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertIs(cfg["check_deps"], False)

            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.KOJI_TAG,
                                    "f26", flags=COMPOSE_FLAGS["check_deps"])
            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertIs(cfg["check_deps"], True)

    def test_get_pungi_conf_multilib(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.KOJI_TAG,
                                    "f26", multilib_arches=["x86_64", "s390x"],
                                    multilib_method=3)

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(set(cfg["multilib"][0][1].keys()), set(["s390x", "x86_64"]))
            for variant, arch_method_dict in cfg["multilib"]:
                for method in arch_method_dict.values():
                    self.assertEqual(set(method), set(['runtime', 'devel']))

    def test_get_pungi_conf_pkgset_koji_builds(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.KOJI_TAG,
                                    "f26", builds=["foo-1-1", "bar-1-1"])

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(set(cfg["pkgset_koji_builds"]),
                             set(["foo-1-1", "bar-1-1"]))
            self.assertEqual(cfg["additional_packages"],
                             [(u'^Temporary$', {u'*': [u'*']})])

    def test_get_pungi_conf_modular_koji_tags(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig(
                "MBS-512", "1", PungiSourceType.KOJI_TAG, "f26",
                modular_koji_tags="f26-modules",
                module_defaults_url="git://localhost.tld/x.git master",
                packages=["foo"])

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(set(cfg["pkgset_koji_module_tag"]),
                             set(["f26-modules"]))
            self.assertEqual(cfg["gather_method"], "hybrid")
            self.assertEqual(cfg["module_defaults_dir"], {
                'branch': 'master',
                'dir': '.',
                'repo': 'git://localhost.tld/x.git',
                'scm': 'git'})

            # The "<modules>" must appear in the variants.xml after the "<groups>".
            variants = pungi_cfg.get_variants_config()
            self.assertTrue(variants.find("<module>") != -1)
            self.assertTrue(variants.find("<groups>") != -1)
            self.assertTrue(variants.find("<module>") > variants.find("<groups>"))

    def test_get_pungi_conf_source_type_build(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.BUILD,
                                    "x", builds=["foo-1-1", "bar-1-1"])

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(cfg["pkgset_koji_tag"], '')
            self.assertEqual(set(cfg["pkgset_koji_builds"]),
                             set(["foo-1-1", "bar-1-1"]))
            self.assertEqual(cfg["additional_packages"],
                             [(u'^Temporary$', {u'*': [u'*']})])

    def test_get_pungi_conf_source_type_koji_tag_all_packages(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig(
                "MBS-512", "1", PungiSourceType.KOJI_TAG, "f26")

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(cfg["pkgset_koji_tag"], 'f26')
            self.assertEqual(cfg["additional_packages"],
                             [('^Temporary$', {'*': ['*']})])

    def test_get_pungi_conf_source_type_koji_tag_some_packages(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig(
                "MBS-512", "1", PungiSourceType.KOJI_TAG, "f26",
                packages=["file"])

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(cfg["pkgset_koji_tag"], 'f26')
            self.assertTrue("additional_packages" not in cfg)

    def test_get_pungi_conf_lookaside_repos(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig(
                "MBS-512", "1", PungiSourceType.KOJI_TAG, "f26",
                lookaside_repos="foo bar")

            template = pungi_cfg.get_pungi_config()
            cfg = self._load_pungi_cfg(template)
            self.assertEqual(
                cfg["gather_lookaside_repos"],
                [(u'^.*$', {u'*': [u'foo', u'bar']})])

    def test_get_pungi_conf_include_devel_modules(self):
        _, mock_path = tempfile.mkstemp()
        template_path = os.path.abspath(os.path.join(test_dir,
                                                     "../conf/pungi.conf"))
        shutil.copy2(template_path, mock_path)

        with patch("odcs.server.pungi.conf.pungi_conf_path", mock_path):
            pungi_cfg = PungiConfig(
                "MBS-512", "1", PungiSourceType.MODULE,
                "foo:1:1:1 foo-devel:1:1:1 bar-devel:1:1:1")

            self.assertEqual(
                pungi_cfg.source, "foo:1:1:1 foo-devel:1:1:1 bar-devel:1:1:1"
            )


class TestPungi(ModelsBaseTest):

    def setUp(self):
        super(TestPungi, self).setUp()

        def mocked_clone_repo(url, dest, branch='master', commit=None):
            makedirs(dest)
            makedirs(os.path.join(dest, "another"))
            with open(os.path.join(dest, "pungi.conf"), "w") as fd:
                lines = [
                    'release_name = "fake pungi conf 1"',
                    'release_short = "compose-1"',
                    'release_version = "10"',
                ]
                fd.writelines(lines)
            with open(os.path.join(dest, "another", "pungi.conf"), "w") as fd:
                lines = [
                    'release_name = "fake pungi conf 2"',
                    'release_short = "compose-2"',
                    'release_version = "10"',
                ]
                fd.writelines(lines)

        self.patch_clone_repo = patch("odcs.server.pungi.clone_repo")
        self.clone_repo = self.patch_clone_repo.start()
        self.clone_repo.side_effect = mocked_clone_repo

        self.patch_makedirs = patch("odcs.server.pungi.makedirs")
        self.makedirs = self.patch_makedirs.start()

        self.patch_ci_dump = patch("odcs.server.pungi.ComposeInfo.dump")
        self.ci_dump = self.patch_ci_dump.start()

        self.compose = MagicMock()
        self.compose.target_dir = conf.target_dir
        self.compose.toplevel_dir = os.path.join(conf.target_dir, "odcs-1")
        self.compose.compose_type = "test"

    def tearDown(self):
        super(TestPungi, self).tearDown()

        self.patch_clone_repo.stop()
        self.patch_makedirs.stop()
        self.patch_ci_dump.stop()

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run(self, execute_cmd):
        pungi_cfg = PungiConfig("MBS-512", "1", PungiSourceType.MODULE,
                                "testmodule:master:1:1")
        pungi = Pungi(1, pungi_cfg)
        pungi.run(self.compose)

        self.makedirs.assert_called_with(
            AnyStringWith("test_composes/odcs-1/"))
        self.makedirs.assert_called_with(
            AnyStringWith("work/global"))
        self.ci_dump.assert_called_once_with(
            AnyStringWith("work/global/composeinfo-base.json"))

        execute_cmd.assert_called_once_with(
            ['pungi-koji', AnyStringWith('pungi.conf'),
             AnyStringWith('--compose-dir='), '--nightly'],
            cwd=AnyStringWith('/tmp/'), timeout=3600,
            stderr=AnyStringWith("pungi-stderr.log"),
            stdout=AnyStringWith("pungi-stdout.log"))

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run_raw_config(self, execute_cmd):
        def mocked_execute_cmd(*args, **kwargs):
            topdir = kwargs["cwd"]
            with open(os.path.join(topdir, "pungi.conf"), "r") as f:
                data = f.read()
                self.assertTrue("fake pungi conf 1" in data)
        execute_cmd.side_effect = mocked_execute_cmd

        fake_raw_config_urls = {
            'pungi.conf': {
                "url": "http://localhost/test.git",
                "config_filename": "pungi.conf",
            }
        }
        with patch.object(conf, 'raw_config_urls', new=fake_raw_config_urls):
            pungi = Pungi(1, RawPungiConfig('pungi.conf#hash'))
            pungi.run(self.compose)

        self.makedirs.assert_called_with(
            AnyStringWith("test_composes/odcs-1/"))
        self.makedirs.assert_called_with(
            AnyStringWith("work/global"))
        self.ci_dump.assert_called_once_with(
            AnyStringWith("work/global/composeinfo-base.json"))

        execute_cmd.assert_called_once()
        self.clone_repo.assert_called_once_with(
            'http://localhost/test.git', AnyStringWith("/raw_config_repo"),
            commit='hash')
        compose_date = time.strftime("%Y%m%d", time.localtime())
        self.assertEqual(self.compose.pungi_compose_id,
                         "compose-1-10-%s.t.0" % compose_date)

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run_raw_config_respin(self, execute_cmd):
        compose = Compose.create(
            db.session, "me", PungiSourceType.RAW_CONFIG, "foo",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(compose)
        db.session.commit()

        def mocked_execute_cmd(*args, **kwargs):
            topdir = kwargs["cwd"]
            with open(os.path.join(topdir, "pungi.conf"), "r") as f:
                data = f.read()
                self.assertTrue("fake pungi conf 1" in data)
        execute_cmd.side_effect = mocked_execute_cmd

        fake_raw_config_urls = {
            'pungi.conf': {
                "url": "http://localhost/test.git",
                "config_filename": "pungi.conf",
            }
        }
        with patch.object(conf, 'raw_config_urls', new=fake_raw_config_urls):
            pungi = Pungi(1, RawPungiConfig('pungi.conf#hash'))
            pungi.run(compose)
            pungi.run(compose)

        compose_date = time.strftime("%Y%m%d", time.localtime())
        self.assertEqual(compose.pungi_compose_id,
                         "compose-1-10-%s.t.1" % compose_date)

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run_raw_config_subpath(self, execute_cmd):
        def mocked_execute_cmd(*args, **kwargs):
            topdir = kwargs["cwd"]
            with open(os.path.join(topdir, "pungi.conf"), "r") as f:
                data = f.read()
                self.assertTrue("fake pungi conf 2" in data)
        execute_cmd.side_effect = mocked_execute_cmd

        fake_raw_config_urls = {
            'pungi.conf': {
                "url": "http://localhost/test.git",
                "config_filename": "pungi.conf",
                "path": "another",
            }
        }
        with patch.object(conf, 'raw_config_urls', new=fake_raw_config_urls):
            pungi = Pungi(1, RawPungiConfig('pungi.conf#hash'))
            pungi.run(self.compose)

        execute_cmd.assert_called_once()
        self.clone_repo.assert_called_once_with(
            'http://localhost/test.git', AnyStringWith("/raw_config_repo"),
            commit='hash')

    @patch("odcs.server.utils.execute_cmd")
    def test_raw_config_validate(self, execute_cmd):
        fake_raw_config_urls = {
            'pungi.conf': {
                "url": "http://localhost/test.git",
                "config_filename": "pungi.conf",
                "schema_override": "/etc/odcs/extra_override.json"
            }
        }
        with patch.object(conf, 'raw_config_schema_override', new="/etc/odcs/default_override.json"):
            with patch.object(conf, 'raw_config_urls', new=fake_raw_config_urls):
                with patch.object(conf, 'pungi_config_validate', new="pungi-config-validate"):
                    pungi = Pungi(1, RawPungiConfig('pungi.conf#hash'))
                    pungi.run(self.compose)

        self.assertEqual(execute_cmd.mock_calls[0], call(
            ['pungi-config-validate', '--old-composes',
             '--schema-override', '/etc/odcs/default_override.json',
             '--schema-override', '/etc/odcs/extra_override.json',
             AnyStringWith('pungi.conf')],
            stderr=AnyStringWith("pungi-config-validate-stderr.log"),
            stdout=AnyStringWith("pungi-config-validate-stdout.log")))

    @patch("odcs.server.utils.execute_cmd")
    def test_pungi_run_raw_config_custom_timeout(self, execute_cmd):
        fake_raw_config_urls = {
            'pungi.conf': {
                "url": "http://localhost/test.git",
                "config_filename": "pungi.conf",
                "pungi_timeout": 7200,
            }
        }
        with patch.object(conf, 'raw_config_urls', new=fake_raw_config_urls):
            pungi = Pungi(1, RawPungiConfig('pungi.conf#hash'))
            pungi.run(self.compose)

        execute_cmd.assert_called_once_with(
            ['pungi-koji', AnyStringWith('pungi.conf'),
             AnyStringWith('--compose-dir='), '--nightly'],
            cwd=AnyStringWith('/tmp/'), timeout=7200,
            stderr=AnyStringWith("pungi-stderr.log"),
            stdout=AnyStringWith("pungi-stdout.log"))


class TestPungiLogs(ModelsBaseTest):

    def setUp(self):
        super(TestPungiLogs, self).setUp()
        self.compose = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "tag",
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        self.compose.state = COMPOSE_STATES["failed"]
        db.session.add(self.compose)
        db.session.commit()

    def tearDown(self):
        super(TestPungiLogs, self).tearDown()

    @patch("odcs.server.pungi.open", create=True)
    def test_error_string(self, patched_open):
        pungi_log = """
2018-03-23 03:38:42 [INFO    ] Writing pungi config
2018-03-23 03:38:42 [INFO    ] [BEGIN] Running pungi
2018-03-22 17:10:49 [ERROR   ] Compose run failed: No such entry in table tag: tag
2018-03-23 03:38:42 [ERROR   ] Compose run failed: ERROR running command: pungi -G
For more details see {0}/odcs-717-1-20180323.n.0/work/x86_64/pungi/Temporary.x86_64.log
2018-03-23 03:38:42 [ERROR   ] Extended traceback in: {0}/odcs-717-1-20180323.n.0/logs/global/traceback.global.log
2018-03-23 03:38:42 [CRITICAL] Compose failed: {0}/odcs-717-1-20180323.n.0
        """.format(conf.target_dir)
        patched_open.return_value = mock_open(
            read_data=pungi_log).return_value

        pungi_logs = PungiLogs(self.compose)
        errors = pungi_logs.get_error_string()
        self.assertEqual(
            errors,
            "Compose run failed: No such entry in table tag: tag\n"
            "Compose run failed: ERROR running command: pungi -G\n"
            "For more details see http://localhost/odcs/odcs-717-1-20180323.n.0/work/x86_64/pungi/Temporary.x86_64.log\n")

    @patch("odcs.server.pungi.open", create=True)
    def test_error_string_too_many_errors(self, patched_open):
        pungi_log = """
2018-03-23 03:38:42 [INFO    ] Writing pungi config
2018-03-22 17:10:49 [ERROR   ] Compose run failed: No such entry in table tag: tag
        """ * 100
        patched_open.return_value = mock_open(
            read_data=pungi_log).return_value

        pungi_logs = PungiLogs(self.compose)
        errors = pungi_logs.get_error_string()
        self.assertTrue("Too many errors" in errors)
        self.assertEqual(len(errors), 2058)

    @patch("odcs.server.pungi.open", create=True)
    def test_error_string_no_error(self, patched_open):
        pungi_log = """
2018-03-23 03:38:42 [INFO    ] Writing pungi config
2018-03-23 03:38:42 [INFO    ] [BEGIN] Running pungi
        """.format(conf.target_dir)
        patched_open.return_value = mock_open(
            read_data=pungi_log).return_value

        pungi_logs = PungiLogs(self.compose)
        errors = pungi_logs.get_error_string()
        self.assertEqual(errors, "")

    def test_error_string_no_log(self):
        pungi_logs = PungiLogs(self.compose)
        errors = pungi_logs.get_error_string()
        self.assertEqual(errors, "")

    def test_toplevel_work_dir(self):
        # The self.glob is inherited from ModelsBaseTest.
        pungi_logs = PungiLogs(self.compose)
        errors = pungi_logs.get_error_string()
        self.assertEqual(errors, "")

    @patch("odcs.server.pungi.open", create=True)
    def test_config_dump(self, patched_open):
        patched_open.return_value = mock_open(
            read_data="fake\npungi\nconf\n").return_value

        pungi_logs = PungiLogs(self.compose)
        ret = pungi_logs.get_config_dump()
        self.assertEqual(ret, "fake\npungi\nconf\n")

        patched_open.assert_called_once_with(AnyStringWith("logs/global/config-dump.global.log"), "r")
