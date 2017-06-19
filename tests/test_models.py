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

import unittest

from odcs import db
from odcs.models import Compose, COMPOSE_RESULTS
from odcs.pungi import PungiSourceType


class TestModels(unittest.TestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_creating_event_and_builds(self):
        compose = Compose.create(
            db.session, "me", PungiSourceType.MODULE, "testmodule-master",
            COMPOSE_RESULTS["repository"], 3600)
        db.session.commit()
        db.session.expire_all()

        c = db.session.query(Compose).filter(compose.id == 1).one()
        self.assertEqual(c.owner, "me")
        self.assertEqual(c.source_type, PungiSourceType.MODULE)
        self.assertEqual(c.source, "testmodule-master")
        self.assertEqual(c.results, COMPOSE_RESULTS["repository"])
        self.assertTrue(c.time_to_expire)

        expected_json = {'source_type': 2, 'state': 0, 'time_done': None,
                         'state_name': 'wait', 'source': u'testmodule-master',
                         'owner': u'me',
                         'result_repo': 'http://localhost/odcs/latest-odcs-1-1/compose/Temporary',
                         'time_submitted': c.json()["time_submitted"], 'id': 1,
                         'time_removed': None,
                         'time_to_expire': c.json()["time_to_expire"],
                         'flags': []}
        self.assertEqual(c.json(), expected_json)
