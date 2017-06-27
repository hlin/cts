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
import json

from odcs import db, app
from odcs.models import Compose, COMPOSE_STATES, COMPOSE_RESULTS
from odcs.pungi import PungiSourceType


class TestViews(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.client = app.test_client()
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.c1 = Compose.create(
            db.session, "unknown", PungiSourceType.MODULE, "testmodule-master",
            COMPOSE_RESULTS["repository"], 60)
        self.c2 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60)
        db.session.add(self.c1)
        db.session.add(self.c2)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_submit_build(self):
        rv = self.client.post('/odcs/1/composes/', data=json.dumps(
            {'source_type': 'module', 'source': 'testmodule-master'}))
        data = json.loads(rv.data.decode('utf8'))

        expected_json = {'source_type': 2, 'state': 0, 'time_done': None,
                         'state_name': 'wait', 'source': u'testmodule-master',
                         'owner': u'Unknown',
                         'result_repo': 'http://localhost/odcs/latest-odcs-%d-1/compose/Temporary' % data['id'],
                         'time_submitted': data["time_submitted"], 'id': data['id'],
                         'time_removed': None,
                         'time_to_expire': data["time_to_expire"],
                         'flags': []}
        self.assertEqual(data, expected_json)

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_nodeps(self):
        rv = self.client.post('/odcs/1/composes/', data=json.dumps(
            {'source_type': 'tag', 'source': 'f26', 'packages': ['ed'],
             'flags': ['no_deps']}))
        data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['flags'], ['no_deps'])

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_resurrection_removed(self):
        self.c1.state = COMPOSE_STATES["removed"]
        self.c1.reused_id = 1
        db.session.commit()
        rv = self.client.post('/odcs/1/composes/', data=json.dumps({'id': 1}))
        data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['id'], 3)
        self.assertEqual(data['state_name'], 'wait')
        self.assertEqual(data['source'], 'testmodule-master')
        self.assertEqual(data['time_removed'], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_build_resurrection_failed(self):
        self.c1.state = COMPOSE_STATES["failed"]
        self.c1.reused_id = 1
        db.session.commit()
        rv = self.client.post('/odcs/1/composes/', data=json.dumps({'id': 1}))
        data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['id'], 3)
        self.assertEqual(data['state_name'], 'wait')
        self.assertEqual(data['source'], 'testmodule-master')
        self.assertEqual(data['time_removed'], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_build_resurrection_no_removed(self):
        db.session.commit()
        rv = self.client.post('/odcs/1/composes/', data=json.dumps({'id': 1}))
        data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['message'], 'No expired or failed compose with id 1')

    def test_submit_build_resurrection_not_found(self):
        db.session.commit()
        rv = self.client.post('/odcs/1/composes/', data=json.dumps({'id': 100}))
        data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['message'], 'No expired or failed compose with id 100')

    def test_query_compose(self):
        resp = self.client.get('/odcs/1/composes/1')
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['source'], "testmodule-master")

    def test_query_composes(self):
        resp = self.client.get('/odcs/1/composes/')
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 2)

    def test_query_compose_owner(self):
        resp = self.client.get('/odcs/1/composes/?owner=me')
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['source'], 'f26')

    def test_query_compose_state_done(self):
        resp = self.client.get(
            '/odcs/1/composes/?state=%d' % COMPOSE_STATES["done"])
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 0)

    def test_query_compose_state_wait(self):
        resp = self.client.get(
            '/odcs/1/composes/?state=%d' % COMPOSE_STATES["wait"])
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 2)

    def test_query_compose_source_type(self):
        resp = self.client.get(
            '/odcs/1/composes/?source_type=%d' % PungiSourceType.MODULE)
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 1)

    def test_query_compose_source(self):
        resp = self.client.get(
            '/odcs/1/composes/?source=f26')
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 1)
