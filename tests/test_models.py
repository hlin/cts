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

from odcs import db
from odcs.models import Compose, COMPOSE_RESULTS
from odcs.models import User, Group
from odcs.pungi import PungiSourceType

from utils import ModelsBaseTest


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
                         'state_name': 'wait', 'source': u'testmodule-master',
                         'owner': u'me',
                         'result_repo': 'http://localhost/odcs/latest-odcs-1-1/compose/Temporary',
                         'time_submitted': c.json()["time_submitted"], 'id': 1,
                         'time_removed': None,
                         'time_to_expire': c.json()["time_to_expire"],
                         'flags': []}
        self.assertEqual(c.json(), expected_json)


class TestUserGroups(ModelsBaseTest):

    def test_create_user_and_groups(self):
        user = User(username='tester 1',
                    email='tester1@example.com',
                    krb_realm='EXAMPLE.COM')
        db.session.add(user)
        user = User(username='tester 2',
                    email='tester2@example.com')
        db.session.add(user)
        db.session.commit()

        group = Group(name='default tester')
        db.session.add(group)
        group = Group(name='admin')
        db.session.add(group)
        db.session.commit()

        self.assertEqual(2, db.session.query(User).count())
        self.assertEqual(2, db.session.query(Group).count())

    def test_add_users_to_group(self):
        group = Group(name='default tester')
        group.users.append(
            User(username='tester 1',
                 email='tester1@example.com',
                 krb_realm='EXAMPLE.COM'))
        group.users.append(
            User(username='tester 2',
                 email='tester2@example.com',
                 krb_realm='EXAMPLE.COM'))
        group.users.append(
            User(username='tester 3',
                 email='tester3@example.com',
                 krb_realm='EXAMPLE.COM'))
        db.session.add(group)
        db.session.commit()

        group = db.session.query(Group).get(group.id)
        self.assertEqual(3, len(list(group.users)))

    def test_add_user_to_groups(self):
        group1 = Group(name='group1')
        group2 = Group(name='group2')
        user = User(username='tester 3',
                    email='tester3@example.com',
                    krb_realm='EXAMPLE.COM')
        db.session.add(group1)
        db.session.add(group2)
        db.session.add(user)
        user.groups.append(group1)
        user.groups.append(group2)
        db.session.commit()

        user = db.session.query(User).get(user.id)
        self.assertEqual('tester 3', user.username)
        self.assertEqual(2, len(list(user.groups)))


class TestUserModel(ModelsBaseTest):

    def test_user_in_any_given_groups(self):
        user = User(username='tester1',
                    email='tester1@example.com')
        db.session.add(user)
        user.groups.append(Group(name='admin'))
        user.groups.append(Group(name='manager'))
        user.groups.append(Group(name='default tester'))
        db.session.commit()

        user = db.session.query(User).filter(User.username == 'tester1')[0]
        self.assertTrue(user.in_groups(['manager', 'administrative']))
        self.assertTrue(user.in_groups(['manager', 'admin']))
        self.assertFalse(user.in_groups(['administrative']))
        self.assertFalse(user.in_groups([]))
