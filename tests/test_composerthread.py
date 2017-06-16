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
import time

from mock import patch
from odcs import db, app
from odcs.models import Compose, COMPOSE_STATES, COMPOSE_RESULTS
from odcs.backend import ComposerThread
from odcs.pungi import PungiSourceType


class TestComposerThread(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.client = app.test_client()
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        compose = Compose.create(
            db.session, "unknown", PungiSourceType.MODULE, "testmodule-master",
            COMPOSE_RESULTS["repository"], 60)
        db.session.add(compose)
        db.session.commit()

        self.composer = ComposerThread()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def _wait_for_compose_state(self, state):
        c = None
        for i in range(20):
            db.session.expire_all()
            c = db.session.query(Compose).filter(Compose.id == 1).one()
            if c.state == state:
                return c
            time.sleep(0.1)
        return c

    @patch("odcs.utils.execute_cmd")
    def test_submit_build(self, execute_cmd):
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

        self.composer.do_work()
        c = self._wait_for_compose_state(COMPOSE_STATES["done"])
        self.assertEqual(c.state, COMPOSE_STATES["done"])
        self.assertEqual(c.result_repo_dir, "./latest-odcs-1-1/compose/Temporary")
        self.assertEqual(c.result_repo_url, "http://localhost/odcs/latest-odcs-1-1/compose/Temporary")
