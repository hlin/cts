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

import contextlib
import datetime
import json

import flask

from freezegun import freeze_time
from mock import patch, PropertyMock

import odcs.server.auth

from odcs.server import db, app, login_manager
from odcs.server.models import Compose, User
from odcs.server.types import COMPOSE_STATES, COMPOSE_RESULTS
from odcs.server.pungi import PungiSourceType
from utils import ModelsBaseTest


@login_manager.user_loader
def user_loader(username):
    return User.find_user_by_name(username=username)


class TestViews(ModelsBaseTest):
    maxDiff = None

    def setUp(self):
        super(TestViews, self).setUp()

        patched_allowed_clients = {'groups': ['composer'], 'users': ['dev']}
        patched_admins = {'groups': ['admin'], 'users': ['root']}
        self.patch_allowed_clients = patch.object(odcs.server.auth.conf,
                                                  'allowed_clients',
                                                  new=patched_allowed_clients)
        self.patch_admins = patch.object(odcs.server.auth.conf,
                                         'admins',
                                         new=patched_admins)
        self.patch_allowed_clients.start()
        self.patch_admins.start()

        self.client = app.test_client()

        self.initial_datetime = datetime.datetime(year=2016, month=1, day=1,
                                                  hour=0, minute=0, second=0)
        with freeze_time(self.initial_datetime):
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
        super(TestViews, self).tearDown()

        self.patch_allowed_clients.stop()
        self.patch_admins.stop()

    @contextlib.contextmanager
    def test_request_context(self, user=None, groups=None, **kwargs):
        with app.test_request_context(**kwargs):
            patch_auth_backend = None
            if user is not None:
                # authentication is disabled with auth_backend=noauth
                patch_auth_backend = patch.object(odcs.server.auth.conf,
                                                  'auth_backend',
                                                  new='kerberos')
                patch_auth_backend.start()
                if not User.find_user_by_name(user):
                    User.create_user(username=user)
                    db.session.commit()
                flask.g.user = User.find_user_by_name(user)

                if groups is not None:
                    if isinstance(groups, list):
                        flask.g.groups = groups
                    else:
                        flask.g.groups = [groups]
                else:
                    flask.g.groups = []
                with self.client.session_transaction() as sess:
                    sess['user_id'] = user
                    sess['_fresh'] = True
            try:
                yield
            finally:
                if patch_auth_backend is not None:
                    patch_auth_backend.stop()

    def test_submit_build(self):
        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'module', 'source': 'testmodule-master'}}))
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
        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'tag', 'source': 'f26', 'packages': ['ed']},
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

        with self.test_request_context(user='dev'):
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

        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps({'id': 1}))
            data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['id'], 3)
        self.assertEqual(data['state_name'], 'wait')
        self.assertEqual(data['source'], 'testmodule-master')
        self.assertEqual(data['time_removed'], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_build_resurrection_no_removed(self):
        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps({'id': 1}))
            data = json.loads(rv.data.decode('utf8'))

        self.assertEqual(data['message'], 'No expired or failed compose with id 1')

    def test_submit_build_resurrection_not_found(self):
        with self.test_request_context(user='dev'):
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

    def test_delete_compose(self):
        with freeze_time(self.initial_datetime) as frozen_datetime:
            c3 = Compose.create(
                db.session, "unknown", PungiSourceType.MODULE, "testmodule-master",
                COMPOSE_RESULTS["repository"], 60)
            c3.state = COMPOSE_STATES['done']
            db.session.add(c3)
            db.session.commit()

            self.assertEqual(len(Compose.composes_to_expire()), 0)

            with self.test_request_context(user='root'):
                resp = self.client.delete("/odcs/1/composes/%s" % c3.id)
                data = json.loads(resp.data.decode('utf8'))

            self.assertEqual(resp.status, '202 ACCEPTED')

            self.assertEqual(data['status'], 202)
            self.assertEqual(data['message'],
                             "The delete request for compose (id=%s) has been accepted and will be processed by backend later." % c3.id)

            self.assertEqual(c3.time_to_expire, self.initial_datetime)

            frozen_datetime.tick()
            self.assertEqual(len(Compose.composes_to_expire()), 1)
            expired_compose = Compose.composes_to_expire().pop()
            self.assertEqual(expired_compose.id, c3.id)

    def test_delete_not_allowed_states_compose(self):
        for state in COMPOSE_STATES.keys():
            if state not in ['done', 'failed']:
                new_c = Compose.create(
                    db.session, "unknown", PungiSourceType.MODULE, "testmodule-master",
                    COMPOSE_RESULTS["repository"], 60)
                new_c.state = COMPOSE_STATES[state]
                db.session.add(new_c)
                db.session.commit()
                compose_id = new_c.id

                with self.test_request_context(user='root'):
                    resp = self.client.delete("/odcs/1/composes/%s" % compose_id)
                    data = json.loads(resp.data.decode('utf8'))

                self.assertEqual(resp.status, '400 BAD REQUEST')
                self.assertEqual(data['status'], 400)
                self.assertRegexpMatches(data['message'],
                                         r"Compose \(id=%s\) can not be removed, its state need to be in .*." % new_c.id)
                self.assertEqual(data['error'], 'Bad Request')

    def test_delete_non_exist_compose(self):
        with self.test_request_context(user='root'):
            resp = self.client.delete("/odcs/1/composes/999999")
            data = json.loads(resp.data.decode('utf8'))

        self.assertEqual(resp.status, '404 NOT FOUND')
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['message'], "No such compose found.")
        self.assertEqual(data['error'], 'Not Found')

    def test_delete_compose_with_non_admin_user(self):
        with self.test_request_context(user='dev'):
            resp = self.client.delete("/odcs/1/composes/%s" % self.c1.id)
            data = json.loads(resp.data.decode('utf8'))

        self.assertEqual(resp.status, '403 FORBIDDEN')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data['status'], 403)
        self.assertEqual(data['message'], 'User dev is not in role admins.')

    def test_can_not_create_compose_with_non_composer_user(self):
        with self.test_request_context(user='qa'):
            resp = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'module', 'source': 'testmodule-master'}}))
            data = json.loads(resp.data.decode('utf8'))

        self.assertEqual(resp.status, '403 FORBIDDEN')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data['status'], 403)
        self.assertEqual(data['message'], 'User qa is not in role allowed_clients.')

    def test_can_create_compose_with_user_in_configured_groups(self):
        with self.test_request_context(user='another_user', groups=['composer']):
            resp = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'module', 'source': 'testmodule-rawhide'}}))
        db.session.expire_all()

        self.assertEqual(resp.status, '200 OK')
        self.assertEqual(resp.status_code, 200)
        c = db.session.query(Compose).filter(Compose.source == 'testmodule-rawhide').one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_can_delete_compose_with_user_in_configured_groups(self):
        c3 = Compose.create(
            db.session, "unknown", PungiSourceType.MODULE, "testmodule-testbranch",
            COMPOSE_RESULTS["repository"], 60)
        c3.state = COMPOSE_STATES['done']
        db.session.add(c3)
        db.session.commit()

        with self.test_request_context(user='another_admin', groups=['admin']):
            resp = self.client.delete("/odcs/1/composes/%s" % c3.id)
            data = json.loads(resp.data.decode('utf8'))

        self.assertEqual(resp.status, '202 ACCEPTED')
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(data['status'], 202)
        self.assertRegexpMatches(data['message'],
                                 r"The delete request for compose \(id=%s\) has been accepted and will be processed by backend later." % c3.id)

    @patch.object(odcs.server.config.Config, 'max_seconds_to_live', new_callable=PropertyMock)
    @patch.object(odcs.server.config.Config, 'seconds_to_live', new_callable=PropertyMock)
    def test_use_seconds_to_live_in_request(self, mock_seconds_to_live, mock_max_seconds_to_live):
        # if we have 'seconds-to-live' in request < conf.max_seconds_to_live
        # the value from request will be used
        mock_seconds_to_live.return_value = 60 * 60 * 24
        mock_max_seconds_to_live.return_value = 60 * 60 * 24 * 3

        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'module', 'source': 'testmodule-master'}, 'seconds-to-live': 60 * 60 * 12}))
            data = json.loads(rv.data.decode('utf8'))

        time_submitted = datetime.datetime.strptime(data['time_submitted'], "%Y-%m-%dT%H:%M:%SZ")
        time_to_expire = datetime.datetime.strptime(data['time_to_expire'], "%Y-%m-%dT%H:%M:%SZ")
        delta = datetime.timedelta(hours=12)
        self.assertEqual(time_to_expire - time_submitted, delta)

    @patch.object(odcs.server.config.Config, 'max_seconds_to_live', new_callable=PropertyMock)
    @patch.object(odcs.server.config.Config, 'seconds_to_live', new_callable=PropertyMock)
    def test_use_max_seconds_to_live_in_conf(self, mock_seconds_to_live, mock_max_seconds_to_live):
        # if we have 'seconds-to-live' in request > conf.max_seconds_to_live
        # conf.max_seconds_to_live will be used
        mock_seconds_to_live.return_value = 60 * 60 * 24
        mock_max_seconds_to_live.return_value = 60 * 60 * 24 * 3

        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'module', 'source': 'testmodule-master'}, 'seconds-to-live': 60 * 60 * 24 * 7}))
            data = json.loads(rv.data.decode('utf8'))

        time_submitted = datetime.datetime.strptime(data['time_submitted'], "%Y-%m-%dT%H:%M:%SZ")
        time_to_expire = datetime.datetime.strptime(data['time_to_expire'], "%Y-%m-%dT%H:%M:%SZ")
        delta = datetime.timedelta(days=3)
        self.assertEqual(time_to_expire - time_submitted, delta)

    @patch.object(odcs.server.config.Config, 'max_seconds_to_live', new_callable=PropertyMock)
    @patch.object(odcs.server.config.Config, 'seconds_to_live', new_callable=PropertyMock)
    def test_use_seconds_to_live_in_conf(self, mock_seconds_to_live, mock_max_seconds_to_live):
        # if we don't have 'seconds-to-live' in request, conf.seconds_to_live will be used
        mock_seconds_to_live.return_value = 60 * 60 * 24
        mock_max_seconds_to_live.return_value = 60 * 60 * 24 * 3

        with self.test_request_context(user='dev'):
            rv = self.client.post('/odcs/1/composes/', data=json.dumps(
                {'source': {'type': 'module', 'source': 'testmodule-master'}}))
            data = json.loads(rv.data.decode('utf8'))

        time_submitted = datetime.datetime.strptime(data['time_submitted'], "%Y-%m-%dT%H:%M:%SZ")
        time_to_expire = datetime.datetime.strptime(data['time_to_expire'], "%Y-%m-%dT%H:%M:%SZ")
        delta = datetime.timedelta(hours=24)
        self.assertEqual(time_to_expire - time_submitted, delta)
