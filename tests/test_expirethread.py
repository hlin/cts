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

import unittest

from odcs import db
from odcs.models import Compose, COMPOSE_STATES, COMPOSE_RESULTS
from odcs.backend import ExpireThread
from odcs.pungi import PungiSourceType
from datetime import datetime, timedelta


class TestExpireThread(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        compose = Compose.create(
            db.session, "unknown", PungiSourceType.MODULE, "testmodule-master",
            COMPOSE_RESULTS["repository"], 60)
        db.session.add(compose)
        db.session.commit()

        self.expire = ExpireThread()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_no_expire(self):
        """
        Test that we do not expire composes on non-done state.
        """
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        c.time_to_expire = datetime.utcnow() - timedelta(seconds=-120)

        for name, state in COMPOSE_STATES.items():
            if name == "done":
                # Compose with state DONE would expire.
                continue
            c.state = state
            db.session.add(c)
            db.session.commit()
            self.expire.do_work()
            db.session.expunge_all()
            c = db.session.query(Compose).filter(Compose.id == 1).one()
            self.assertEqual(c.state, state)

    def test_expire_done(self):
        """
        Test that we do expire compose in done state.
        """
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        c.time_to_expire = datetime.utcnow() - timedelta(seconds=120)
        c.state = COMPOSE_STATES["done"]
        db.session.add(c)
        db.session.commit()
        self.expire.do_work()
        db.session.expunge_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["removed"])

    def test_no_expire_done_time_to_expire_in_future(self):
        """
        Test that we do not expire compose if time_to_expire has not been
        reached yet.
        """
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        c.state = COMPOSE_STATES["done"]
        db.session.add(c)
        db.session.commit()
        self.expire.do_work()
        db.session.expunge_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["done"])
