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

from odcs.server import db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_STATES, COMPOSE_RESULTS
from odcs.server.backend import RemoveExpiredComposesThread
from odcs.server.pungi import PungiSourceType
from datetime import datetime, timedelta

from utils import ModelsBaseTest


class TestRemoveExpiredComposesThread(ModelsBaseTest):
    maxDiff = None

    def setUp(self):
        super(TestRemoveExpiredComposesThread, self).setUp()

        compose = Compose.create(
            db.session, "unknown", PungiSourceType.MODULE, "testmodule-master",
            COMPOSE_RESULTS["repository"], 60)
        db.session.add(compose)
        db.session.commit()

        self.thread = RemoveExpiredComposesThread()

    def test_does_not_remove_a_compose_which_state_is_not_done(self):
        """
        Test that we do not remove a composes on non-done state.
        """
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        c.time_to_expire = datetime.utcnow() - timedelta(seconds=-120)

        for name, state in COMPOSE_STATES.items():
            if name == "done":
                # Compose with state DONE would be removed.
                continue
            c.state = state
            db.session.add(c)
            db.session.commit()
            self.thread.do_work()
            db.session.expunge_all()
            c = db.session.query(Compose).filter(Compose.id == 1).one()
            self.assertEqual(c.state, state)

    def test_a_compose_which_state_is_done_is_removed(self):
        """
        Test that we do remove a compose in done state.
        """
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        c.time_to_expire = datetime.utcnow() - timedelta(seconds=120)
        c.state = COMPOSE_STATES["done"]
        db.session.add(c)
        db.session.commit()
        self.thread.do_work()
        db.session.expunge_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["removed"])

    def test_does_not_remove_a_compose_which_is_not_expired(self):
        """
        Test that we do not remove a compose if its time_to_expire has not been
        reached yet.
        """
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        c.state = COMPOSE_STATES["done"]
        db.session.add(c)
        db.session.commit()
        self.thread.do_work()
        db.session.expunge_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["done"])
