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

import os
import shutil

from mock import patch, MagicMock, mock_open
from productmd.rpms import Rpms

from odcs.server import db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_FLAGS, COMPOSE_RESULTS, COMPOSE_STATES
from odcs.server.pdc import ModuleLookupError
from odcs.server.pungi import PungiSourceType
from odcs.server.backend import (resolve_compose, get_reusable_compose,
                                 generate_pulp_compose, validate_pungi_compose,
                                 generate_pungi_compose, _write_repo_file,
                                 _read_repo_file, generate_odcs_compose_compose)
from odcs.server.utils import makedirs
import odcs.server.backend
from .utils import ModelsBaseTest

from .pdc import mock_pdc

thisdir = os.path.abspath(os.path.dirname(__file__))


class TestBackend(ModelsBaseTest):

    def test_resolve_compose_repo(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        db.session.commit()

        resolve_compose(c)
        db.session.commit()
        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.koji_event, 1496834159)

    @mock_pdc
    def test_resolve_compose_module(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.MODULE,
            "moduleA-f26",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source,
                         ' '.join(["moduleA-f26-20170809000000",
                                   "moduleB-f26-20170808000000",
                                   "moduleC-f26-20170807000000",
                                   "moduleD-f26-20170806000000"]))

    @mock_pdc
    def test_resolve_compose_module_no_deps(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.MODULE,
            "moduleA-f26 moduleA-f26",
            COMPOSE_RESULTS["repository"], 3600,
            flags=COMPOSE_FLAGS["no_deps"])
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source, "moduleA-f26-20170809000000")

    @mock_pdc
    def expect_module_lookup_error(self, source, match):
        c = Compose.create(
            db.session, "me", PungiSourceType.MODULE,
            source,
            COMPOSE_RESULTS["repository"], 3600)
        db.session.commit()

        with self.assertRaisesRegexp(ModuleLookupError, match):
            resolve_compose(c)

    def test_resolve_compose_module_not_found(self):
        self.expect_module_lookup_error("moduleA-f30",
                                        "Failed to find")

    def test_resolve_compose_module_not_found2(self):
        self.expect_module_lookup_error("moduleA-f26-00000000000000",
                                        "Failed to find")

    def test_resolve_compose_module_conflict(self):
        self.expect_module_lookup_error("moduleA-f26 moduleB-f27",
                                        "which conflicts with")

    def test_resolve_compose_module_conflict2(self):
        self.expect_module_lookup_error("moduleB-f26 moduleB-f27",
                                        "conflicts with")

    @patch("odcs.server.backend.create_koji_session")
    def test_resolve_compose_repo_no_override_koji_event(
            self, create_koji_session):
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.getLastEvent.return_value = {"id": 123}

        c = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        c.koji_event = 1
        db.session.commit()

        resolve_compose(c)
        db.session.commit()
        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.koji_event, 1)

    def test_get_reusable_compose(self):
        old_c = Compose.create(
            db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        resolve_compose(old_c)
        old_c.state = COMPOSE_STATES["done"]
        c = Compose.create(
            db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        resolve_compose(c)
        db.session.add(old_c)
        db.session.add(c)
        db.session.commit()

        reused_c = get_reusable_compose(c)
        self.assertEqual(reused_c, old_c)

    def test_get_reusable_compose_attrs_not_the_same(self):
        old_c = Compose.create(
            db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"], 3600, packages="ed", sigkeys="123")
        old_c.state = COMPOSE_STATES["done"]
        resolve_compose(old_c)
        db.session.add(old_c)
        db.session.commit()

        attrs = {}
        attrs["packages"] = "ed foo"
        attrs["sigkeys"] = "321"
        attrs["koji_event"] = 123456
        attrs["source"] = "123"
        for attr, value in attrs.items():
            c = Compose.create(
                db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo"),
                COMPOSE_RESULTS["repository"], 3600, packages="ed")
            setattr(c, attr, value)

            # Do not resolve compose for non-existing source...
            if attr != "source":
                resolve_compose(c)

            db.session.add(c)
            db.session.commit()
            reused_c = get_reusable_compose(c)
            self.assertEqual(reused_c, None)

    def test_write_repo_file(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-1 foo-2",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()

        m = mock_open()
        with patch('odcs.server.backend.open', m, create=True):
            _write_repo_file(c)

        expected_repo_file = """[odcs-1]
name=ODCS repository for odcs-1
baseurl=http://localhost/odcs/latest-odcs-1-1/compose/Temporary/$basearch/os
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1

"""

        handle = m()
        handle.write.assert_called_once_with(expected_repo_file)

    def test_write_repo_file_repos_defined(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-1 foo-2",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()
        repos = {
            'foo-2': 'http://localhost/content/2/x86_64/os',
            'foo-1': 'http://localhost/content/1/x86_64/os'
        }

        m = mock_open()
        with patch('odcs.server.backend.open', m, create=True):
            _write_repo_file(c, repos)

        expected_repo_file = """[foo-1]
name=ODCS repository for foo-1
baseurl=http://localhost/content/1/x86_64/os
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1

[foo-2]
name=ODCS repository for foo-2
baseurl=http://localhost/content/2/x86_64/os
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1

"""

        handle = m()
        handle.write.assert_called_once_with(expected_repo_file)

    def test_read_repo_file(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-1 foo-2",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()
        repo_file = """[foo-2]
name=ODCS repository for foo-2
baseurl=http://localhost/content/2/x86_64/os
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1

[foo-1]
name=ODCS repository for foo-1
baseurl=http://localhost/content/1/x86_64/os
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1

"""

        makedirs(os.path.dirname(c.result_repofile_path))
        try:
            with open(c.result_repofile_path, "w") as f:
                f.write(repo_file)

            repos = _read_repo_file(c)
        finally:
            shutil.rmtree(c.toplevel_dir)

        expected_repos = {
            'foo-2': 'http://localhost/content/2/x86_64/os',
            'foo-1': 'http://localhost/content/1/x86_64/os'
        }

        self.assertEqual(repos, expected_repos)

    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose(
            self, _write_repo_file, pulp_rest_post):
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                },
            },
            {
                "notes": {
                    "relative_url": "content/2/x86_64/os",
                    "content_set": "foo-2",
                }
            }
        ]

        c = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-1 foo-2",
            COMPOSE_RESULTS["repository"], 3600)
        with patch.object(odcs.server.backend.conf, 'pulp_server_url',
                          "https://localhost/"):
            generate_pulp_compose(c)

        expected_query = {
            "criteria": {
                "fields": ["notes.relative_url", "notes.content_set"],
                "filters": {
                    "notes.arch": "x86_64",
                    "notes.content_set": {"$in": ["foo-1", "foo-2"]},
                    "notes.include_in_download_service": "True"
                }
            }
        }
        pulp_rest_post.assert_called_once_with('repositories/search/',
                                               expected_query)

        expected_repos = {
            'foo-2': 'http://localhost/content/2/x86_64/os',
            'foo-1': 'http://localhost/content/1/x86_64/os'
        }

        _write_repo_file.assert_called_once_with(c, expected_repos)

    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose_content_set_not_found(
            self, _write_repo_file, pulp_rest_post):
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                },
            },
        ]

        c = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-1 foo-2",
            COMPOSE_RESULTS["repository"], 3600)
        self.assertRaises(ValueError, generate_pulp_compose, c)

        expected_query = {
            "criteria": {
                "fields": ["notes.relative_url", "notes.content_set"],
                "filters": {
                    "notes.arch": "x86_64",
                    "notes.content_set": {"$in": ["foo-1", "foo-2"]},
                    "notes.include_in_download_service": "True"
                }
            }
        }
        pulp_rest_post.assert_called_once_with('repositories/search/',
                                               expected_query)
        _write_repo_file.assert_not_called()


class TestGeneratePungiCompose(ModelsBaseTest):

    def setUp(self):
        super(TestGeneratePungiCompose, self).setUp()

        self.patch_resolve_compose = patch("odcs.server.backend.resolve_compose")
        self.resolve_compose = self.patch_resolve_compose.start()

        self.patch_get_reusable_compose = patch("odcs.server.backend.get_reusable_compose")
        self.get_reusable_compose = self.patch_get_reusable_compose.start()
        self.get_reusable_compose.return_value = False

        self.patch_write_repo_file = patch("odcs.server.backend._write_repo_file")
        self.write_repo_file = self.patch_write_repo_file.start()

        # Mocked method to store Pungi.pungi_cfg to self.pungi_cfg, so we can
        # run asserts against it.
        self.pungi_config = None

        def fake_pungi_run(pungi_cls):
            self.pungi_config = pungi_cls.pungi_cfg

        self.patch_pungi_run = patch("odcs.server.pungi.Pungi.run", autospec=True)
        self.pungi_run = self.patch_pungi_run.start()
        self.pungi_run.side_effect = fake_pungi_run

    def tearDown(self):
        super(TestGeneratePungiCompose, self).tearDown()
        self.patch_resolve_compose.stop()
        self.patch_get_reusable_compose.stop()
        self.patch_write_repo_file.stop()
        self.patch_pungi_run.stop()
        self.pungi_config = None

    def test_generate_pungi_compose(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1 pkg2 pkg3')
        c.id = 1

        generate_pungi_compose(c)

        self.resolve_compose.assert_called_once_with(c)
        self.get_reusable_compose.assert_called_once_with(c)
        self.write_repo_file.assert_called_once_with(c)

        self.assertEqual(self.pungi_config.gather_method, "deps")
        self.assertEqual(self.pungi_config.pkgset_koji_inherit, True)

    def test_generate_pungi_compose_nodeps(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1 pkg2 pkg3',
            flags=COMPOSE_FLAGS["no_deps"])
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(self.pungi_config.gather_method, "nodeps")
        self.assertEqual(self.pungi_config.pkgset_koji_inherit, True)

    def test_generate_pungi_compose_noinheritance(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1 pkg2 pkg3',
            flags=COMPOSE_FLAGS["no_inheritance"])
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(self.pungi_config.gather_method, "deps")
        self.assertEqual(self.pungi_config.pkgset_koji_inherit, False)


class TestGenerateODCSComposeCompose(ModelsBaseTest):

    def setUp(self):
        super(TestGenerateODCSComposeCompose, self).setUp()

        self.patch_write_repo_file = patch("odcs.server.backend._write_repo_file")
        self.write_repo_file = self.patch_write_repo_file.start()

        self.patch_read_repo_file = patch("odcs.server.backend._read_repo_file")
        self.read_repo_file = self.patch_read_repo_file.start()
        self.read_repo_file.side_effect = [
            {
                'foo-2': 'http://localhost/content/2/x86_64/os',
                'foo-1': 'http://localhost/content/1/x86_64/os'
            },
            {
                'foo-2': 'http://localhost/content/4/x86_64/os',
                'foo-3': 'http://localhost/content/3/x86_64/os'
            },
        ]

        self.patch_mergerepo = patch("odcs.server.utils.mergerepo")
        self.mergerepo = self.patch_mergerepo.start()

        self.tag_compose1 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1 pkg2 pkg3')
        db.session.add(self.tag_compose1)

        self.tag_compose2 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f27",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1 pkg2 pkg3')
        db.session.add(self.tag_compose2)

        self.pulp_compose1 = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-1 foo-2",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(self.pulp_compose1)

        self.pulp_compose2 = Compose.create(
            db.session, "me", PungiSourceType.PULP, "foo-3 foo-4",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(self.pulp_compose2)

        self.repo_compose1 = Compose.create(
            db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        db.session.add(self.repo_compose1)

        self.repo_compose2 = Compose.create(
            db.session, "me", PungiSourceType.REPO, os.path.join(thisdir, "repo2"),
            COMPOSE_RESULTS["repository"], 3600, packages="ed")
        db.session.add(self.repo_compose2)
        db.session.commit()

    def tearDown(self):
        super(TestGenerateODCSComposeCompose, self).tearDown()
        self.patch_mergerepo.stop()
        self.patch_write_repo_file.stop()
        self.patch_read_repo_file.stop()

    def test_generate_odcs_compose_single_compose(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "1",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()

        self.assertRaises(ValueError, generate_odcs_compose_compose, c)

    def test_generate_odcs_compose_wrong_input(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "1   a",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()

        self.assertRaises(ValueError, generate_odcs_compose_compose, c)

    def test_generate_odcs_compose_tag_and_tag(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.tag_compose1.id, self.tag_compose2.id),
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()

        generate_odcs_compose_compose(c)
        self.mergerepo.assert_called_once_with(
            ['http://localhost/odcs/latest-odcs-1-1/compose/Temporary/x86_64/os',
             'http://localhost/odcs/latest-odcs-2-1/compose/Temporary/x86_64/os'],
            c.result_repo_dir("x86_64"), True)
        self.assertEqual(c.state, COMPOSE_STATES["done"])

        repos = {
            'odcs-7': 'http://localhost/odcs/latest-odcs-7-1/compose/Temporary/$basearch/os'
        }
        self.write_repo_file.assert_called_once_with(c, repos)

    def test_generate_odcs_compose_tag_and_pulp_wrong_name(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.tag_compose1.id, self.pulp_compose1.id),
            COMPOSE_RESULTS["repository"], 3600)
        db.session.add(c)
        db.session.commit()

        self.assertRaises(ValueError, generate_odcs_compose_compose, c)

    def test_generate_odcs_compose_tag_and_pulp(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.tag_compose1.id, self.pulp_compose1.id),
            COMPOSE_RESULTS["repository"], 3600, result_repo_name="foo-2")
        db.session.add(c)
        db.session.commit()

        generate_odcs_compose_compose(c)
        self.mergerepo.assert_called_once_with(
            ['http://localhost/odcs/latest-odcs-1-1/compose/Temporary/x86_64/os',
             'http://localhost/content/2/x86_64/os'],
            c.result_repo_dir("x86_64"), True)
        self.assertEqual(c.state, COMPOSE_STATES["done"])

        repos = {
            'foo-1': 'http://localhost/content/1/x86_64/os',
            'foo-2': 'http://localhost/odcs/latest-odcs-7-1/compose/Temporary/$basearch/os',
        }
        self.write_repo_file.assert_called_once_with(c, repos)

    def test_generate_odcs_compose_tag_and_repo(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.tag_compose1.id, self.repo_compose1.id),
            COMPOSE_RESULTS["repository"], 3600, result_repo_name="foo-2")
        db.session.add(c)
        db.session.commit()

        generate_odcs_compose_compose(c)
        self.mergerepo.assert_called_once_with(
            ['http://localhost/odcs/latest-odcs-1-1/compose/Temporary/x86_64/os',
             'file://' + self.repo_compose1.result_repo_dir("x86_64")],
            c.result_repo_dir("x86_64"), True)
        self.assertEqual(c.state, COMPOSE_STATES["done"])

        repos = {
            'foo-2': 'http://localhost/odcs/latest-odcs-7-1/compose/Temporary/$basearch/os'
        }
        self.write_repo_file.assert_called_once_with(c, repos)

    def test_generate_odcs_compose_pulp_and_pulp(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.pulp_compose1.id, self.pulp_compose2.id),
            COMPOSE_RESULTS["repository"], 3600, result_repo_name="foo-2")
        db.session.add(c)
        db.session.commit()

        generate_odcs_compose_compose(c)
        self.mergerepo.assert_called_once_with(
            ['http://localhost/content/2/x86_64/os',
             'http://localhost/content/4/x86_64/os'],
            c.result_repo_dir("x86_64"), True)
        self.assertEqual(c.state, COMPOSE_STATES["done"])

        repos = {
            'foo-2': 'http://localhost/odcs/latest-odcs-7-1/compose/Temporary/$basearch/os',
            'foo-3': 'http://localhost/content/3/x86_64/os',
            'foo-1': 'http://localhost/content/1/x86_64/os'
        }
        self.write_repo_file.assert_called_once_with(c, repos)

    def test_generate_odcs_compose_pulp_and_repo(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.pulp_compose1.id, self.repo_compose1.id),
            COMPOSE_RESULTS["repository"], 3600, result_repo_name="foo-2")
        db.session.add(c)
        db.session.commit()

        generate_odcs_compose_compose(c)
        self.mergerepo.assert_called_once_with(
            ['http://localhost/content/2/x86_64/os',
             'file://' + self.repo_compose1.result_repo_dir("x86_64")],
            c.result_repo_dir("x86_64"), True)
        self.assertEqual(c.state, COMPOSE_STATES["done"])

        repos = {
            'foo-2': 'http://localhost/odcs/latest-odcs-7-1/compose/Temporary/$basearch/os',
            'foo-1': 'http://localhost/content/1/x86_64/os'
        }
        self.write_repo_file.assert_called_once_with(c, repos)

    def test_generate_odcs_compose_repo_repo(self):
        c = Compose.create(
            db.session, "me", PungiSourceType.ODCS_COMPOSE,
            "%d %d" % (self.repo_compose1.id, self.repo_compose2.id),
            COMPOSE_RESULTS["repository"], 3600, result_repo_name="foo-2")
        db.session.add(c)
        db.session.commit()

        generate_odcs_compose_compose(c)
        self.mergerepo.assert_called_once_with(
            ['file://' + self.repo_compose1.result_repo_dir("x86_64"),
             'file://' + self.repo_compose2.result_repo_dir("x86_64")],
            c.result_repo_dir("x86_64"), True)
        self.assertEqual(c.state, COMPOSE_STATES["done"])

        repos = {
            'foo-2': 'http://localhost/odcs/latest-odcs-7-1/compose/Temporary/$basearch/os',
        }
        self.write_repo_file.assert_called_once_with(c, repos)


class TestValidatePungiCompose(ModelsBaseTest):
    """Test validate_pungi_compose"""

    def setUp(self):
        super(TestValidatePungiCompose, self).setUp()

        self.c = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1 pkg2 pkg3')
        db.session.commit()

        compose_dir = os.path.join(self.c.toplevel_dir, 'compose')
        metadata_dir = os.path.join(compose_dir, 'metadata')
        self.rpms_metadata = os.path.join(metadata_dir, 'rpms.json')
        makedirs(metadata_dir)

        rm = Rpms()
        rm.header.version = "1.0"
        rm.compose.id = "Me-26-20161212.0"
        rm.compose.type = "production"
        rm.compose.date = "20161212"
        rm.compose.respin = 0

        # pkg1
        rm.add(
            "Temporary",
            "x86_64",
            "pkg1-0:2.18-11.fc26.x86_64.rpm",
            path="Temporary/x86_64/os/Packages/p/pkg1-2.18-11.fc26.x86_64.rpm",
            sigkey="246110c1",
            category="binary",
            srpm_nevra="pkg1-0:2.18-11.fc26.src.rpm",
        )
        rm.add(
            "Temporary",
            "x86_64",
            "pkg1-0:2.18-11.fc26.src.rpm",
            path="Temporary/source/SRPMS/p/pkg1-2.18-11.fc26.x86_64.rpm",
            sigkey="246110c1",
            category="source",
        )
        # pkg2
        rm.add(
            "Temporary",
            "x86_64",
            "pkg2-0:2.18-11.fc26.x86_64.rpm",
            path="Temporary/x86_64/os/Packages/p/pkg2-0.18-11.fc26.x86_64.rpm",
            sigkey="246110c1",
            category="binary",
            srpm_nevra="pkg2-0:0.18-11.fc26.src.rpm",
        )
        rm.add(
            "Temporary",
            "x86_64",
            "pkg2-0:0.18-11.fc26.src.rpm",
            path="Temporary/source/SRPMS/p/pkg2-0.18-11.fc26.x86_64.rpm",
            sigkey="246110c1",
            category="source",
        )
        rm.dump(self.rpms_metadata)

    def tearDown(self):
        shutil.rmtree(self.c.toplevel_dir)
        super(TestValidatePungiCompose, self).tearDown()

    def test_missing_packages(self):
        with self.assertRaisesRegexp(RuntimeError, 'not present.+pkg3'):
            validate_pungi_compose(self.c)

    def test_all_packages_are_included(self):
        self.c.packages = 'pkg1 pkg2'
        db.session.commit()

        validate_pungi_compose(self.c)
