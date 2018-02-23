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
# -*- coding: utf-8 -*-

from datetime import datetime
from datetime import timedelta

from odcs.server import db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_RESULTS, COMPOSE_STATES
from odcs.server.models import User
from odcs.server.pungi import PungiSourceType

from .utils import ModelsBaseTest


class TestModels(ModelsBaseTest):

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
                         'state_name': 'wait',
                         'state_reason': None,
                         'source': u'testmodule-master',
                         'owner': u'me',
                         'result_repo': 'http://localhost/odcs/latest-odcs-1-1/compose/Temporary',
                         'result_repofile': 'http://localhost/odcs/latest-odcs-1-1/compose/Temporary/odcs-1.repo',
                         'time_submitted': c.json()["time_submitted"], 'id': 1,
                         'time_removed': None,
                         'removed_by': None,
                         'time_to_expire': c.json()["time_to_expire"],
                         'flags': [],
                         'results': ['repository'],
                         'sigkeys': '',
                         'koji_event': None,
                         'koji_task_id': None,
                         'packages': None,
                         'arches': 'x86_64'}
        self.assertEqual(c.json(), expected_json)


class TestUserModel(ModelsBaseTest):

    def test_find_by_email(self):
        db.session.add(User(username='tester1'))
        db.session.add(User(username='admin'))
        db.session.commit()

        user = User.find_user_by_name('admin')
        self.assertEqual('admin', user.username)

    def test_create_user(self):
        User.create_user(username='tester2')
        db.session.commit()

        user = User.find_user_by_name('tester2')
        self.assertEqual('tester2', user.username)

    def test_no_group_is_added_if_no_groups(self):
        User.create_user(username='tester1')
        db.session.commit()

        user = User.find_user_by_name('tester1')
        self.assertEqual('tester1', user.username)


class ComposeModel(ModelsBaseTest):
    """Test Compose Model"""

    def setUp(self):
        super(ComposeModel, self).setUp()

        self.c1 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60)
        self.c2 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1')
        self.c3 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1')
        self.c4 = Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60, packages='pkg1')

        map(db.session.add, (self.c1, self.c2, self.c3, self.c4))
        db.session.commit()

        self.c1.reused_id = self.c3.id
        self.c2.reused_id = self.c3.id
        self.c3.reused_id = self.c4.id
        db.session.commit()

    def test_get_reused_compose(self):
        compose = self.c3.get_reused_compose()
        self.assertEqual(self.c4, compose)

    def test_get_reusing_composes(self):
        composes = self.c3.get_reusing_composes()
        self.assertEqual(2, len(composes))
        self.assertEqual([self.c1, self.c2], list(composes))

    def test_extend_expiration(self):
        from_now = datetime.utcnow()
        seconds_to_live = 100
        self.c1.extend_expiration(from_now, seconds_to_live)
        db.session.commit()

        expected_time_to_expire = from_now + timedelta(seconds=seconds_to_live)
        self.assertEqual(expected_time_to_expire, self.c1.time_to_expire)

    def test_not_extend_expiration(self):
        from_now = datetime.utcnow()
        seconds_to_live = (self.c1.time_to_expire - datetime.utcnow()).seconds / 2

        orig_time_to_expire = self.c1.time_to_expire
        self.c1.extend_expiration(from_now, seconds_to_live)

        self.assertEqual(orig_time_to_expire, self.c1.time_to_expire)

    def test_composes_to_expire(self):
        now = datetime.utcnow()
        self.c1.time_to_expire = now - timedelta(seconds=60)
        self.c1.state = COMPOSE_STATES["done"]
        self.c2.time_to_expire = now - timedelta(seconds=60)
        self.c2.state = COMPOSE_STATES["failed"]
        self.c3.time_to_expire = now + timedelta(seconds=60)
        self.c3.state = COMPOSE_STATES["done"]
        self.c4.time_to_expire = now + timedelta(seconds=60)
        self.c4.state = COMPOSE_STATES["failed"]
        db.session.commit()

        composes = Compose.composes_to_expire()
        self.assertTrue(self.c1 in composes)
        self.assertTrue(self.c2 in composes)
        self.assertTrue(self.c3 not in composes)
