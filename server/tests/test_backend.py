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
from textwrap import dedent

import six
import os
import requests.exceptions
import shutil

from mock import patch, MagicMock, call, Mock
from productmd.rpms import Rpms

from odcs.server import conf, db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_FLAGS, COMPOSE_RESULTS, COMPOSE_STATES
from odcs.server.mbs import ModuleLookupError
from odcs.server.pungi import PungiSourceType
from odcs.server.backend import (
    resolve_compose,
    get_reusable_compose,
    generate_compose,
    generate_pulp_compose,
    generate_pungi_compose,
    validate_pungi_compose,
    koji_get_inherited_tags,
)
from odcs.server.utils import makedirs
import odcs.server.backend
from .utils import ModelsBaseTest, AnyStringWith

from .mbs import mock_mbs

thisdir = os.path.abspath(os.path.dirname(__file__))


class TestBackend(ModelsBaseTest):
    def test_resolve_compose_repo(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.REPO,
            os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()
        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.koji_event, 1496834159)

    @patch("odcs.server.backend.create_koji_session")
    def test_resolve_compose_raw_config(self, create_koji_session):
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.getLastEvent.return_value = {"id": 123}

        for default_koji_event in [None, 1]:
            c = Compose.create(
                db.session,
                "me",
                PungiSourceType.RAW_CONFIG,
                "eln#eln",
                COMPOSE_RESULTS["repository"],
                3600,
            )
            c.koji_event = default_koji_event
            db.session.commit()

            resolve_compose(c)
            self.assertEqual(c.koji_event, default_koji_event or 123)

    @mock_mbs()
    def test_resolve_compose_module(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleA:f26",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(
            c.source,
            " ".join(
                [
                    "moduleA:f26:20170809000000:00000000",
                    "moduleB:f26:20170808000000:00000000",
                    "moduleC:f26:20170807000000:00000000",
                    "moduleD:f26:20170806000000:00000000",
                ]
            ),
        )

    @mock_mbs()
    def test_resolve_compose_module_empty_source(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source, "")

    @mock_mbs()
    def test_resolve_compose_module_include_done_modules(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testmodule:master",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["include_done_modules"],
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source, "testmodule:master:20180515074419:00000000")

    @mock_mbs()
    def test_resolve_compose_module_include_done_modules_full_nsvc(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testmodule:master:20180515074419:00000000",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source, "testmodule:master:20180515074419:00000000")

    @mock_mbs()
    def test_resolve_compose_module_devel(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleA:f26 moduleA-devel:f26",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(
            c.source,
            " ".join(
                [
                    "moduleA-devel:f26:20170809000000:00000000",
                    "moduleA:f26:20170809000000:00000000",
                    "moduleB:f26:20170808000000:00000000",
                    "moduleC:f26:20170807000000:00000000",
                    "moduleD:f26:20170806000000:00000000",
                ]
            ),
        )

    @mock_mbs()
    def test_resolve_compose_module_devel_deps_resolving(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleA-devel:f26",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(
            c.source,
            " ".join(
                [
                    "moduleA-devel:f26:20170809000000:00000000",
                    "moduleA:f26:20170809000000:00000000",
                    "moduleB:f26:20170808000000:00000000",
                    "moduleC:f26:20170807000000:00000000",
                    "moduleD:f26:20170806000000:00000000",
                ]
            ),
        )

    @mock_mbs()
    def test_resolve_compose_module_multiple_contexts_no_deps(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testcontexts:master:1",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["no_deps"],
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(
            c.source, " ".join(["testcontexts:master:1:a", "testcontexts:master:1:b"])
        )

    @mock_mbs()
    def test_resolve_compose_module_multiple_contexts_deps(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testcontexts:master:1",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(
            c.source,
            " ".join(
                [
                    "parent:master:1:a",
                    "parent:master:1:b",
                    "testcontexts:master:1:a",
                    "testcontexts:master:1:b",
                ]
            ),
        )

    @mock_mbs()
    def test_resolve_compose_module_no_deps(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleA:f26 moduleA:f26",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["no_deps"],
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source, "moduleA:f26:20170809000000:00000000")

    @mock_mbs()
    def expect_module_lookup_error(self, source, match, flags=0):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            source,
            COMPOSE_RESULTS["repository"],
            3600,
            flags=flags,
        )
        db.session.commit()

        with six.assertRaisesRegex(self, ModuleLookupError, match):
            resolve_compose(c)

    @mock_mbs(1)
    def test_resolve_compose_module_mmdv1(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleA:f26",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(
            c.source,
            " ".join(
                [
                    "moduleA:f26:20170809000000:00000000",
                    "moduleB:f26:20170808000000:00000000",
                    "moduleC:f26:20170807000000:00000000",
                    "moduleD:f26:20170806000000:00000000",
                ]
            ),
        )

    @mock_mbs(1)
    def test_resolve_compose_module_no_deps_mmdv1(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleA:f26 moduleA:f26",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["no_deps"],
        )
        db.session.commit()

        resolve_compose(c)
        db.session.commit()

        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.source, "moduleA:f26:20170809000000:00000000")

    @mock_mbs(1)
    def expect_module_lookup_error_mmdv1(self, source, match, flags=0):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            source,
            COMPOSE_RESULTS["repository"],
            3600,
            flags=flags,
        )
        db.session.commit()

        with six.assertRaisesRegex(self, ModuleLookupError, match):
            resolve_compose(c)

    def test_resolve_compose_module_not_found(self):
        self.expect_module_lookup_error("moduleA:f30", "Failed to find")

    def test_resolve_compose_module_not_found2(self):
        self.expect_module_lookup_error("moduleA:f26:00000000000000", "Failed to find")

    def test_resolve_compose_module_conflict(self):
        self.expect_module_lookup_error(
            "moduleA:f26:20170809000000 moduleA:f26:20170805000000", "conflicts with"
        )

    @mock_mbs()
    def test_resolve_compose_module_not_conflict(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleB:f26 moduleB:f27",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["no_deps"],
        )
        db.session.commit()

        resolve_compose(c)

    @mock_mbs(1)
    def test_resolve_compose_module_not_conflict_mmdv1(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "moduleB:f26 moduleB:f27",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["no_deps"],
        )
        db.session.commit()

        resolve_compose(c)

    def test_resolve_compose_module_dep_not_found(self):
        self.expect_module_lookup_error(
            "moduleB:f26 moduleB:f27",
            "Failed to find module moduleC:f27 in ready state in the MBS.",
        )

    @patch("odcs.server.backend.create_koji_session")
    def test_resolve_compose_repo_no_override_koji_event(self, create_koji_session):
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.getLastEvent.return_value = {"id": 123}

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        c.koji_event = 1
        db.session.commit()

        resolve_compose(c)
        db.session.commit()
        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.koji_event, 1)

    def test_get_reusable_compose(self):
        old_c = Compose.create(
            db.session,
            "me",
            PungiSourceType.REPO,
            os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        resolve_compose(old_c)
        old_c.state = COMPOSE_STATES["done"]
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.REPO,
            os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        resolve_compose(c)
        db.session.add(old_c)
        db.session.add(c)
        db.session.commit()

        reused_c = get_reusable_compose(c)
        self.assertEqual(reused_c, old_c)

    def test_koji_get_inherited_tags_unknown_tag(self):
        koji_session = MagicMock()
        koji_session.getTag.return_value = None

        with six.assertRaisesRegex(self, ValueError, "Unknown Koji tag foo."):
            koji_get_inherited_tags(koji_session, "foo")

    @patch("odcs.server.backend.koji_get_inherited_tags")
    @patch("odcs.server.backend.create_koji_session")
    def test_get_reusable_tag_compose(
        self, create_koji_session, koji_get_inherited_tags
    ):
        koji_get_inherited_tags.return_value = ["foo", "bar"]
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.tagChangedSinceEvent.return_value = False

        old_c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        old_c.koji_event = 1
        old_c.state = COMPOSE_STATES["done"]
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        c.koji_event = 2
        db.session.add(old_c)
        db.session.add(c)
        db.session.commit()

        reused_c = get_reusable_compose(c)
        self.assertEqual(reused_c, old_c)

    @patch("odcs.server.backend.koji_get_inherited_tags")
    @patch("odcs.server.backend.create_koji_session")
    def test_get_reusable_tag_compose_none_koji_event(
        self, create_koji_session, koji_get_inherited_tags
    ):
        koji_get_inherited_tags.return_value = ["foo", "bar"]
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.tagChangedSinceEvent.return_value = False

        old_c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        old_c.koji_event = None
        old_c.state = COMPOSE_STATES["done"]
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        c.koji_event = 2
        db.session.add(old_c)
        db.session.add(c)
        db.session.commit()

        reused_c = get_reusable_compose(c)
        self.assertEqual(reused_c, old_c)

    @patch("odcs.server.backend.koji_get_inherited_tags")
    @patch("odcs.server.backend.create_koji_session")
    def test_get_reusable_tag_compose_tag_changed(
        self, create_koji_session, koji_get_inherited_tags
    ):
        koji_get_inherited_tags.return_value = ["foo", "bar"]
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.tagChangedSinceEvent.return_value = True

        old_c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        old_c.koji_event = 1
        old_c.state = COMPOSE_STATES["done"]
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        c.koji_event = 2
        db.session.add(old_c)
        db.session.add(c)
        db.session.commit()

        reused_c = get_reusable_compose(c)
        self.assertEqual(reused_c, None)

    @patch("odcs.server.backend.koji_get_inherited_tags")
    @patch("odcs.server.backend.create_koji_session")
    def test_get_reusable_tag_compose_renew(
        self, create_koji_session, koji_get_inherited_tags
    ):
        koji_get_inherited_tags.return_value = ["foo", "bar"]
        koji_session = MagicMock()
        create_koji_session.return_value = koji_session
        koji_session.tagChangedSinceEvent.return_value = False

        old_c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        old_c.koji_event = 10
        old_c.state = COMPOSE_STATES["done"]
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo",
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
        )
        # c.koji_event is lower than old_c.koji_event, because "c" is actually
        # older than old_c and we are testing that its renewal does not reuse
        # the newer "c" compose.
        c.koji_event = 9
        db.session.add(old_c)
        db.session.add(c)
        db.session.commit()

        reused_c = get_reusable_compose(c)
        self.assertEqual(reused_c, None)

    def test_get_reusable_compose_attrs_not_the_same(self):
        old_c = Compose.create(
            db.session,
            "me",
            PungiSourceType.REPO,
            os.path.join(thisdir, "repo"),
            COMPOSE_RESULTS["repository"],
            3600,
            packages="ed",
            sigkeys="123",
            builds="foo-1-1",
        )
        old_c.state = COMPOSE_STATES["done"]
        resolve_compose(old_c)
        db.session.add(old_c)
        db.session.commit()

        attrs = {}
        attrs["packages"] = "ed foo"
        attrs["builds"] = "foo-1-1 bar-1-1"
        attrs["sigkeys"] = "321"
        attrs["koji_event"] = 123456
        attrs["source"] = "123"
        attrs["arches"] = "ppc64 x86_64"
        attrs["multilib_arches"] = "x86_64 i686"
        attrs["multilib_method"] = 1
        attrs["lookaside_repos"] = "foo bar"
        attrs["modular_koji_tags"] = "f26-modules"
        attrs["module_defaults_url"] = "git://localhost/x.git#branch"
        attrs["target_dir"] = "private"
        for attr, value in attrs.items():
            c = Compose.create(
                db.session,
                "me",
                PungiSourceType.REPO,
                os.path.join(thisdir, "repo"),
                COMPOSE_RESULTS["repository"],
                3600,
                packages="ed",
                sigkeys="123",
                builds="foo-1-1",
            )
            setattr(c, attr, value)

            # Do not resolve compose for non-existing source and in case we
            # change koji_event, because it would be overwriten.
            if attr not in ["source", "koji_event"]:
                resolve_compose(c)

            db.session.add(c)
            db.session.commit()
            reused_c = get_reusable_compose(c)
            self.assertEqual(reused_c, None)

    @patch("odcs.server.utils.write_empty_repo")
    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.pulp.Pulp._rest_get")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose(
        self, _write_repo_file, pulp_rest_get, pulp_rest_post, write_empty_repo
    ):
        """General case for generating a pulp compose

        - Content sets foo-1, foo-2 and foo-3 must be included.
        - Repo with id repo3 should not be included because content set foo-3 includes this repo.
        - Repo with id repo4 and repo5 must be included.
        - repo5 is included because flag include_unpublished_pulp_repos is set.
        """
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                    "arch": "x86_64",
                    "signatures": "SIG1,SIG2",
                    "product_versions": "",
                },
                "id": "repo1",
            },
            {
                "notes": {
                    "relative_url": "content/2/x86_64/os",
                    "content_set": "foo-2",
                    "arch": "x86_64",
                    "signatures": "SIG1,SIG2",
                    "product_versions": "",
                },
                "id": "repo2",
            },
            {
                "notes": {
                    "relative_url": "content/3/ppc64/os",
                    "content_set": "foo-3",
                    "arch": "ppc64",
                    "signatures": "SIG1,SIG3",
                    "product_versions": "",
                },
                "id": "repo3",
            },
        ]

        def _rest_get(endpoint):
            if endpoint.endswith("repo4/"):
                return {
                    "notes": {
                        "relative_url": "content/100/s390/os",
                        "content_set": "foo-100",
                        "arch": "s390",
                        "signatures": "SIG2,SIG4",
                        "product_versions": "",
                        "include_in_download_service": True,
                    },
                    "id": "repo4",
                }
            elif endpoint.endswith("repo3/"):
                return {
                    "notes": {
                        "relative_url": "content/3/ppc64/os",
                        "content_set": "foo-3",
                        "arch": "ppc64",
                        "signatures": "SIG1,SIG3",
                        "product_versions": "",
                    },
                    "id": "repo3",
                }
            elif endpoint.endswith("repo5/"):
                return {
                    "notes": {
                        "relative_url": "content/101/x86_64/os",
                        "content_set": "foo-100",
                        "arch": "x86_64",
                        "signatures": "SIG1,SIG2",
                        "product_versions": "",
                        "include_in_download_service": False,
                    },
                    "id": "repo5",
                }

        pulp_rest_get.side_effect = _rest_get

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PULP,
            # repo3 is included in the content set foo-3
            "foo-1 foo-2 repo4 foo-3 repo3 repo5",
            COMPOSE_RESULTS["repository"],
            3600,
            # repo5 must be included due to this flag
            flags=COMPOSE_FLAGS["include_unpublished_pulp_repos"],
        )
        with patch.object(
            odcs.server.backend.conf, "pulp_server_url", "https://localhost/"
        ):
            generate_pulp_compose(c)

        expected_query = {
            "criteria": {
                "fields": ["notes", "id"],
                "filters": {
                    "notes.content_set": {
                        "$in": ["foo-1", "foo-2", "repo4", "foo-3", "repo3", "repo5"]
                    },
                },
            }
        }
        pulp_rest_post.assert_called_once_with("repositories/search/", expected_query)

        expected_repofile = dedent(
            """
            [foo-1]
            name=foo-1
            baseurl=http://localhost/content/1/x86_64/os
            enabled=1
            gpgcheck=0

            [foo-2]
            name=foo-2
            baseurl=http://localhost/content/2/x86_64/os
            enabled=1
            gpgcheck=0

            [foo-3]
            name=foo-3
            baseurl=http://localhost/content/3/ppc64/os
            enabled=1
            gpgcheck=0

            [repo4]
            name=repo4
            baseurl=http://localhost/content/100/s390/os
            enabled=1
            gpgcheck=0

            [repo5]
            name=repo5
            baseurl=http://localhost/content/101/x86_64/os
            enabled=1
            gpgcheck=0
            """
        )
        _write_repo_file.assert_called_once_with(c, expected_repofile)

        self.assertEqual(c.state, COMPOSE_STATES["done"])
        self.assertEqual(c.state_reason, "Compose is generated successfully")
        self.assertEqual(set(c.arches.split(" ")), {"x86_64", "ppc64", "s390"})
        self.assertEqual(set(c.sigkeys.split(" ")), {"SIG1", "SIG2", "SIG3", "SIG4"})
        write_empty_repo.assert_not_called()

    @patch("odcs.server.utils.write_empty_repo")
    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.backend._write_repo_file")
    @patch("os.symlink")
    def test_generate_pulp_compose_include_inpublished_pulp_repos_passed(
        self, symlink, _write_repo_file, pulp_rest_post, write_empty_repo
    ):
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                    "arch": "ppc64",
                    "signatures": "SIG1,SIG2",
                },
                "id": "repo1",
            },
        ]

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PULP,
            "foo-1 foo-2",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["include_unpublished_pulp_repos"],
        )
        db.session.add(c)
        db.session.commit()

        with patch.object(
            odcs.server.backend.conf, "pulp_server_url", "https://localhost/"
        ):
            generate_compose(1)

        expected_query = {
            "criteria": {
                "fields": ["notes", "id"],
                "filters": {"notes.content_set": {"$in": ["foo-1", "foo-2"]}},
            }
        }
        pulp_rest_post.assert_called_once_with("repositories/search/", expected_query)
        symlink.assert_not_called()
        write_empty_repo.assert_not_called()

    @patch("odcs.server.utils.write_empty_repo")
    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.pulp.Pulp._rest_get")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose_content_set_not_found(
        self, _write_repo_file, pulp_rest_get, pulp_rest_post, write_empty_repo
    ):
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                    "arch": "ppc64",
                    "signatures": "SIG1,SIG2",
                    "product_versions": "",
                },
                "id": "repo1",
            },
        ]

        # No repository is found for source foo-2 eventually, whatever it is a
        # content set or a repo id.
        mock_response = Mock(status_code=404)
        mock_response.json.return_value = {
            "error_message": "Missing resource(s): repository=foo-2"
        }
        pulp_rest_get.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PULP,
            "foo-1 foo-2",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        with patch.object(
            odcs.server.backend.conf, "pulp_server_url", "https://localhost/"
        ):
            generate_compose(1)

        expected_query = {
            "criteria": {
                "fields": ["notes", "id"],
                "filters": {
                    "notes.content_set": {"$in": ["foo-1", "foo-2"]},
                    "notes.include_in_download_service": "True",
                },
            }
        }
        pulp_rest_post.assert_called_once_with("repositories/search/", expected_query)
        _write_repo_file.assert_not_called()

        c1 = Compose.query.filter(Compose.id == 1).one()
        self.assertEqual(c1.state, COMPOSE_STATES["failed"])
        six.assertRegex(
            self,
            c1.state_reason,
            r"Error while generating compose: Failed to find all the source\(s\).*",
        )
        write_empty_repo.assert_not_called()

    @patch("odcs.server.utils.write_empty_repo")
    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.pulp.Pulp._rest_get")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose_content_set_not_found_allow_absent(
        self, _write_repo_file, pulp_rest_get, pulp_rest_post, write_empty_repo
    ):
        pulp_rest_post.return_value = [
            {
                "notes": {
                    "relative_url": "content/1/x86_64/os",
                    "content_set": "foo-1",
                    "arch": "ppc64",
                    "signatures": "SIG1,SIG2",
                    "product_versions": "",
                },
                "id": "repo1",
            },
        ]

        # No repository is found for source foo-2 eventually, whatever it is a
        # content set or a repo id.
        mock_response = Mock(status_code=404)
        mock_response.json.return_value = {
            "error_message": "Missing resource(s): repository=repo2"
        }
        pulp_rest_get.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PULP,
            "foo-1 foo-2",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["ignore_absent_pulp_repos"],
        )
        db.session.add(c)
        db.session.commit()

        with patch.object(
            odcs.server.backend.conf, "pulp_server_url", "https://localhost/"
        ):
            generate_compose(1)

        expected_query = {
            "criteria": {
                "fields": ["notes", "id"],
                "filters": {
                    "notes.content_set": {"$in": ["foo-1", "foo-2"]},
                    "notes.include_in_download_service": "True",
                },
            }
        }
        pulp_rest_post.assert_called_once_with("repositories/search/", expected_query)
        expected_repofile = dedent(
            """
            [foo-1]
            name=foo-1
            baseurl=http://localhost/content/1/x86_64/os
            enabled=1
            gpgcheck=0
            """
        )
        _write_repo_file.assert_called_once_with(c, expected_repofile)
        write_empty_repo.assert_not_called()

        c1 = Compose.query.filter(Compose.id == 1).one()
        self.assertEqual(c1.state, COMPOSE_STATES["done"])
        self.assertEqual(c1.source, "foo-1")

    @patch("odcs.server.utils.write_empty_repo")
    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.pulp.Pulp._rest_get")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose_content_set_not_found_any_allow_absent(
        self, _write_repo_file, pulp_rest_get, pulp_rest_post, write_empty_repo
    ):
        pulp_rest_post.return_value = []

        # No repository is found for source foo-2 eventually, whatever it is a
        # content set or a repo id.
        mock_response = Mock(status_code=404)
        mock_response.json.return_value = {
            "error_message": "Missing resource(s): repository=repo2"
        }
        pulp_rest_get.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PULP,
            "foo-2",
            COMPOSE_RESULTS["repository"],
            3600,
            flags=COMPOSE_FLAGS["ignore_absent_pulp_repos"],
        )
        db.session.add(c)
        db.session.commit()

        with patch.object(
            odcs.server.backend.conf, "pulp_server_url", "https://localhost/"
        ):
            generate_compose(1)

        expected_query = {
            "criteria": {
                "fields": ["notes", "id"],
                "filters": {
                    "notes.content_set": {"$in": ["foo-2"]},
                    "notes.include_in_download_service": "True",
                },
            }
        }
        pulp_rest_post.assert_called_once_with("repositories/search/", expected_query)
        _write_repo_file.assert_called_once_with(c, "")
        write_empty_repo.assert_called_once_with(c, conf.allowed_arches)

        c1 = Compose.query.filter(Compose.id == 1).one()
        self.assertEqual(c1.state, COMPOSE_STATES["done"])
        self.assertEqual(c1.source, "")

    @patch("odcs.server.backend.resolve_compose")
    @patch("odcs.server.backend.generate_pungi_compose")
    @patch("odcs.server.pungi.PungiLogs.get_error_string")
    def test_generate_compose_exception(
        self, get_error_string, generate_pungi_compose, resolve_compose
    ):
        get_error_string.return_value = "Compose failed for unknown reason."
        generate_pungi_compose.side_effect = RuntimeError(
            "Expected exception, see %s" % os.path.join(conf.target_dir, "foo.log")
        )

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo-1",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        generate_compose(1)

        get_error_string.assert_called_once()

        c1 = Compose.query.filter(Compose.id == 1).one()
        self.assertEqual(c1.state, COMPOSE_STATES["failed"])
        six.assertRegex(
            self,
            c1.state_reason,
            r"Error while generating compose: Expected exception, see "
            "http://localhost/odcs/foo.log\n"
            "Compose failed for unknown reason*",
        )

    @patch("odcs.server.backend.resolve_compose")
    @patch("odcs.server.backend.generate_pungi_compose")
    @patch("odcs.server.pungi.PungiLogs.get_error_string")
    def test_generate_compose_pungi_logs_exceptions(
        self, get_error_string, generate_pungi_compose, resolve_compose
    ):
        get_error_string.side_effect = RuntimeError("PungiLogs Expected exception")
        generate_pungi_compose.side_effect = RuntimeError("Expected exception")

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo-1",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        generate_compose(1)

        c1 = Compose.query.filter(Compose.id == 1).one()
        self.assertEqual(c1.state, COMPOSE_STATES["failed"])
        six.assertRegex(
            self,
            c1.state_reason,
            r"Error while generating compose: Expected exception*",
        )

    @patch("odcs.server.backend.tag_changed", return_value=True)
    @patch("odcs.server.backend.create_koji_session")
    def test_resolve_compose_from_koji_tag_get_last_event_if_tag_changed(
        self, create_koji_session, tag_changed
    ):
        session = create_koji_session.return_value
        fake_koji_event = {"id": 234567}
        session.getLastEvent.return_value = fake_koji_event

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo-1",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        with patch.dict("odcs.server.backend.LAST_EVENTS_CACHE", {"foo-1": 123456}):
            resolve_compose(c)
            c.koji_event = fake_koji_event["id"]

    @patch("odcs.server.backend.tag_changed")
    @patch("odcs.server.backend.create_koji_session")
    def test_resolve_compose_from_koji_tag_reuse_koji_event_if_tag_not_changed(
        self, create_koji_session, tag_changed
    ):
        tag_changed.return_value = False
        session = create_koji_session.return_value

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo-1",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        with patch.dict("odcs.server.backend.LAST_EVENTS_CACHE", {"foo-1": 123456}):
            resolve_compose(c)
            c.koji_event = 123456

            session.getLastEvent.assert_not_called()

    @patch("odcs.server.backend.tag_changed")
    @patch("odcs.server.backend.create_koji_session")
    def test_resolve_compose_from_koji_tag_get_last_koji_event_if_tag_not_cached(
        self, create_koji_session, tag_changed
    ):
        fake_koji_event = {"id": 789065}
        session = create_koji_session.return_value
        session.getLastEvent.return_value = fake_koji_event

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "foo-1",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        with patch.dict("odcs.server.backend.LAST_EVENTS_CACHE", {"bar-2": 123456}):
            resolve_compose(c)
            c.koji_event = fake_koji_event["id"]

            tag_changed.assert_not_called()

    @patch("odcs.server.mbs.MBS.validate_module_list")
    @patch("odcs.server.mbs.MBS.get_latest_modules")
    def test_resolve_compose_module_filter_base_module(
        self, get_latest_modules, validate_module_list
    ):
        modules = [
            {"name": "foo", "stream": "0", "version": 1, "context": "x"},
            {"name": "bar", "stream": "0", "version": 1, "context": "y"},
        ]
        get_latest_modules.return_value = modules
        validate_module_list.return_value = modules + [
            {"name": "platform", "stream": "0", "version": 1, "context": "z"}
        ]

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "foo:0 bar:0",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        # Default conf.base_module_names includes "platform" module, so it
        # should be removed from the source list.
        resolve_compose(c)
        self.assertEqual(c.source, "bar:0:1:y foo:0:1:x")

        # Now try removing "platform" from the conf.base_module_names, so it
        # should appear in a compose source.
        with patch.object(
            odcs.server.config.Config, "base_module_names", new=["random_name"]
        ):
            resolve_compose(c)
            self.assertEqual(c.source, "bar:0:1:y foo:0:1:x platform:0:1:z")

    @patch("odcs.server.pungi_compose.PungiCompose.get_rpms_data")
    def test_resolve_compose_pungi_compose_source_type(self, get_rpms_data):
        get_rpms_data.return_value = {
            "sigkeys": set(["sigkey1", None]),
            "arches": set(["x86_64"]),
            "builds": {
                "flatpak-rpm-macros-29-6.module+125+c4f5c7f2": set(
                    [
                        "flatpak-rpm-macros-0:29-6.module+125+c4f5c7f2.src",
                        "flatpak-rpm-macros-0:29-6.module+125+c4f5c7f2.x86_64",
                    ]
                ),
                "flatpak-runtime-config-29-4.module+125+c4f5c7f2": set(
                    [
                        "flatpak-runtime-config-0:29-4.module+125+c4f5c7f2.src",
                        "flatpak-runtime-config2-0:29-4.module+125+c4f5c7f2.x86_64",
                    ]
                ),
            },
        }

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PUNGI_COMPOSE,
            "http://localhost/compose/Temporary",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.add(c)
        db.session.commit()

        resolve_compose(c)
        self.assertEqual(c.sigkeys.split(" "), ["sigkey1", ""])
        self.assertEqual(c.arches.split(" "), ["x86_64"])
        self.assertEqual(
            set(c.builds.split(" ")),
            set(
                [
                    "flatpak-rpm-macros-29-6.module+125+c4f5c7f2",
                    "flatpak-runtime-config-29-4.module+125+c4f5c7f2",
                ]
            ),
        )
        self.assertEqual(
            set(c.packages.split(" ")),
            set(
                [
                    "flatpak-rpm-macros",
                    "flatpak-runtime-config",
                    "flatpak-runtime-config2",
                ]
            ),
        )

    @patch("odcs.server.pulp.Pulp._rest_post")
    @patch("odcs.server.pulp.Pulp._rest_get")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pulp_compose_by_repo_id(
        self, _write_repo_file, pulp_rest_get, pulp_rest_post
    ):
        # No repository is found first the time to query Pulp by treating the
        # repo ids as content sets.
        pulp_rest_post.return_value = []

        def _rest_get(endpoint):
            if endpoint.endswith("repo1/"):
                return {
                    "notes": {
                        "relative_url": "content/1/s390/os",
                        "content_set": "foo-1",
                        "arch": "s390",
                        "signatures": "SIG1,SIG2",
                        "product_versions": "",
                        "include_in_download_service": True,
                    },
                    "id": "repo1",
                }
            # No repository is found for source foo-2 eventually, whatever it is a
            # content set or a repo id.
            elif endpoint.endswith("repo2/"):
                mock_response = Mock(status_code=404)
                mock_response.json.return_value = {
                    "error_message": "Missing resource(s): repository=repo2"
                }
                raise requests.exceptions.HTTPError(response=mock_response)

        pulp_rest_get.side_effect = _rest_get

        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.PULP,
            "repo1 repo2",
            COMPOSE_RESULTS["repository"],
            3600,
            # Ignore the absent repo id: repo2
            flags=COMPOSE_FLAGS["ignore_absent_pulp_repos"],
        )
        db.session.add(c)
        db.session.commit()

        with patch.object(
            odcs.server.backend.conf, "pulp_server_url", "https://localhost/"
        ):
            generate_pulp_compose(c)

        pulp_rest_post.assert_called_once_with(
            "repositories/search/",
            {
                "criteria": {
                    "fields": ["notes", "id"],
                    "filters": {
                        "notes.content_set": {"$in": ["repo1", "repo2"]},
                        "notes.include_in_download_service": "True",
                    },
                }
            },
        )

        expected_repofile = dedent(
            """
            [repo1]
            name=repo1
            baseurl=http://localhost/content/1/s390/os
            enabled=1
            gpgcheck=0
            """
        )
        _write_repo_file.assert_called_once_with(c, expected_repofile)

        c1 = Compose.query.filter(Compose.id == 1).one()
        self.assertEqual(c1.state, COMPOSE_STATES["done"])
        self.assertEqual(c1.source, "repo1")


class TestGeneratePungiCompose(ModelsBaseTest):
    def setUp(self):
        super(TestGeneratePungiCompose, self).setUp()

        self.patch_resolve_compose = patch("odcs.server.backend.resolve_compose")
        self.resolve_compose = self.patch_resolve_compose.start()

        self.patch_get_reusable_compose = patch(
            "odcs.server.backend.get_reusable_compose"
        )
        self.get_reusable_compose = self.patch_get_reusable_compose.start()
        self.get_reusable_compose.return_value = False

        self.patch_write_repo_file = patch("odcs.server.backend._write_repo_file")
        self.write_repo_file = self.patch_write_repo_file.start()

        self.patch_is_cached = patch("odcs.server.backend.KojiTagCache.is_cached")
        self.is_cached = self.patch_is_cached.start()

        self.patch_reuse_cached = patch("odcs.server.backend.KojiTagCache.reuse_cached")
        self.reuse_cached = self.patch_reuse_cached.start()

        self.patch_update_cache = patch("odcs.server.backend.KojiTagCache.update_cache")
        self.update_cache = self.patch_update_cache.start()

        self.patch_validate_pungi_compose = patch(
            "odcs.server.backend.validate_pungi_compose"
        )
        self.validate_pungi_compose = self.patch_validate_pungi_compose.start()

        # Mocked method to store Pungi.pungi_cfg to self.pungi_cfg, so we can
        # run asserts against it.
        self.pungi_config = None
        self.old_compose = None

        def fake_pungi_run(pungi_cls, compose):
            self.pungi_config = pungi_cls.pungi_cfg
            self.old_compose = pungi_cls.old_compose

        self.patch_pungi_run = patch("odcs.server.pungi.Pungi.run", autospec=True)
        self.pungi_run = self.patch_pungi_run.start()
        self.pungi_run.side_effect = fake_pungi_run

    def tearDown(self):
        super(TestGeneratePungiCompose, self).tearDown()
        self.patch_resolve_compose.stop()
        self.patch_get_reusable_compose.stop()
        self.patch_write_repo_file.stop()
        self.patch_pungi_run.stop()
        self.patch_reuse_cached.stop()
        self.patch_update_cache.stop()
        self.validate_pungi_compose.stop()
        self.patch_is_cached.stop()
        self.pungi_config = None

    def test_generate_pungi_compose(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1 pkg2 pkg3",
            arches="x86_64 s390",
            multilib_arches="i686 x86_64",
            multilib_method=1,
        )
        c.id = 1

        generate_pungi_compose(c)

        self.resolve_compose.assert_called_once_with(c)
        self.get_reusable_compose.assert_called_once_with(c)
        self.write_repo_file.assert_called_once_with(c)
        self.is_cached.assert_called_once_with(c)
        self.reuse_cached.assert_called_once_with(c)
        self.update_cache.assert_called_once_with(c)
        self.validate_pungi_compose.assert_called_once_with(c)

        self.assertEqual(self.pungi_config.gather_method, "deps")
        self.assertEqual(self.pungi_config.pkgset_koji_inherit, True)
        self.assertEqual(set(self.pungi_config.arches), set(["x86_64", "s390"]))
        self.assertEqual(
            set(self.pungi_config.multilib_arches), set(["i686", "x86_64"])
        )
        self.assertEqual(self.pungi_config.multilib_method, ["runtime"])

    def test_generate_pungi_compose_multiarch_arches_None(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1 pkg2 pkg3",
            arches="x86_64 s390",
            multilib_arches=None,
            multilib_method=None,
        )
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(set(self.pungi_config.multilib_arches), set([]))
        self.assertEqual(self.pungi_config.multilib_method, [])

    def test_generate_pungi_compose_nodeps(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1 pkg2 pkg3",
            flags=COMPOSE_FLAGS["no_deps"],
        )
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(self.pungi_config.gather_method, "nodeps")
        self.assertEqual(self.pungi_config.pkgset_koji_inherit, True)

    def test_generate_pungi_compose_noinheritance(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1 pkg2 pkg3",
            flags=COMPOSE_FLAGS["no_inheritance"],
        )
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(self.pungi_config.gather_method, "deps")
        self.assertEqual(self.pungi_config.pkgset_koji_inherit, False)

    def test_generate_pungi_compose_builds(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            builds="foo-1-1 bar-1-1",
            flags=COMPOSE_FLAGS["no_inheritance"],
        )
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(self.pungi_config.builds, ["foo-1-1", "bar-1-1"])

    def test_generate_pungi_compose_source_type_build(self):
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.BUILD,
            "x",
            COMPOSE_RESULTS["repository"],
            60,
            builds="foo-1-1 bar-1-1",
            flags=COMPOSE_FLAGS["no_inheritance"],
        )
        c.id = 1

        generate_pungi_compose(c)
        self.assertEqual(self.pungi_config.koji_tag, None)
        self.assertEqual(self.pungi_config.builds, ["foo-1-1", "bar-1-1"])

    @patch.object(
        odcs.server.config.Config,
        "raw_config_urls",
        new={
            "pungi_cfg": {
                "url": "git://localhost/test.git",
                "config_filename": "pungi.conf",
            }
        },
    )
    @patch("odcs.server.utils.makedirs")
    @patch("os.symlink")
    @patch("os.unlink")
    @patch("odcs.server.pungi.PungiLogs.get_config_dump")
    @patch("odcs.server.backend._write_repo_file")
    def test_generate_pungi_compose_raw_config(
        self, write_repo_file, config_dump, unlink, symlink, makedirs
    ):
        self.is_cached.return_value = False
        config_dump.return_value = "fake\npungi\nconf\n"
        c = Compose.create(
            db.session,
            "me",
            PungiSourceType.RAW_CONFIG,
            "pungi_cfg#hash",
            COMPOSE_RESULTS["repository"],
            60,
        )
        c.compose_type = "production"
        c.pungi_compose_id = "compose-1-10-2020110.n.0"
        c.id = 1

        fake_raw_config_urls = {
            "pungi_cfg": {
                "url": "git://localhost/test.git",
                "config_filename": "pungi.conf",
            }
        }
        with patch.object(conf, "raw_config_urls", new=fake_raw_config_urls):
            generate_pungi_compose(c)

        self.assertEqual(c.pungi_config_dump, "fake\npungi\nconf\n")
        self.assertEqual(
            self.pungi_config.pungi_cfg,
            {
                "url": "git://localhost/test.git",
                "config_filename": "pungi.conf",
                "commit": "hash",
            },
        )
        self.assertEqual(self.old_compose, AnyStringWith("/test_composes/production"))

        makedirs.assert_called_once_with(AnyStringWith("/test_composes/production"))
        symlink.assert_has_calls(
            [
                call(
                    "../odcs-1",
                    AnyStringWith("/test_composes/production/compose-1-10-2020110.n.0"),
                ),
                call(
                    "../odcs-1",
                    AnyStringWith("/test_composes/production/latest-compose-1"),
                ),
            ]
        )
        unlink.assert_called_with(
            AnyStringWith("/test_composes/production/latest-compose-1")
        )
        write_repo_file.assert_not_called()


class TestValidatePungiCompose(ModelsBaseTest):
    """Test validate_pungi_compose"""

    def setUp(self):
        super(TestValidatePungiCompose, self).setUp()

        self.c = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1 pkg2 pkg3",
        )
        db.session.commit()

        # Remove any previous toplevel_dir.
        if os.path.exists(self.c.toplevel_dir):
            shutil.rmtree(self.c.toplevel_dir)

        compose_dir = os.path.join(self.c.toplevel_dir, "compose")
        metadata_dir = os.path.join(compose_dir, "metadata")
        self.rpms_metadata = os.path.join(metadata_dir, "rpms.json")
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
            "pkg1-lib-0:2.18-11.fc26.x86_64.rpm",
            path="Temporary/x86_64/os/Packages/p/pkg1-lib-2.18-11.fc26.x86_64.rpm",
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
            "pkg2-lib-0:2.18-11.fc26.x86_64.rpm",
            path="Temporary/x86_64/os/Packages/p/pkg2-lib-0.18-11.fc26.x86_64.rpm",
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
        with six.assertRaisesRegex(self, RuntimeError, "not present.+pkg3"):
            validate_pungi_compose(self.c)

    def test_all_packages_are_included(self):
        self.c.packages = "pkg1 pkg1-lib pkg2 pkg2-lib"
        db.session.commit()

        validate_pungi_compose(self.c)
