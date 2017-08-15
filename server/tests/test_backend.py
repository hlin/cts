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
from mock import patch, MagicMock

from odcs.server import db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_FLAGS, COMPOSE_RESULTS, COMPOSE_STATES
from odcs.server.pdc import ModuleLookupError
from odcs.server.pungi import PungiSourceType
from odcs.server.backend import resolve_compose, get_reusable_compose
from utils import ModelsBaseTest

from pdc import mock_pdc

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
