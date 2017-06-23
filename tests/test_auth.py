# -*- coding: utf-8 -*-
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
# Written by Chenxiong Qi <cqi@redhat.com>


import unittest

from mock import patch

from odcs import db
from odcs.models import User
from odcs.auth import load_krb_user_from_request
from odcs.auth import query_ldap_groups
from utils import ModelsBaseTest
from werkzeug.exceptions import Unauthorized


class TestLoadKrbUserFromRequest(ModelsBaseTest):

    def setUp(self):
        super(TestLoadKrbUserFromRequest, self).setUp()

        self.user = User(username='tester1',
                         email='tester1@example.com',
                         krb_realm='EXAMPLE.COM')
        db.session.add(self.user)
        db.session.commit()

    @patch('odcs.auth.query_ldap_groups', return_value=['devel', 'admin'])
    @patch('odcs.auth.request')
    @patch('odcs.auth.g')
    def test_create_new_user(self, g, request, query_ldap_groups):
        request.environ.get.return_value = 'newuser@EXAMPLE.COM'

        load_krb_user_from_request()

        expected_user = db.session.query(User).filter(
            User.email == 'newuser@example.com')[0]

        self.assertEqual(expected_user.id, g.user.id)
        self.assertEqual(expected_user.username, g.user.username)
        self.assertEqual(expected_user.email, g.user.email)
        self.assertEqual(expected_user.krb_realm, g.user.krb_realm)

        # Ensure user's groups are created
        self.assertEqual(2, len(g.user.groups))
        names = [group.name for group in g.user.groups]
        self.assertEqual(['admin', 'devel'], sorted(names))

    @patch('odcs.auth.query_ldap_groups', return_value=['devel', 'admin'])
    @patch('odcs.auth.request')
    @patch('odcs.auth.g')
    def test_return_existing_user(self, g, request, query_ldap_groups):
        request.environ.get.return_value = \
            '{0}@EXAMPLE.COM'.format(self.user.username)

        original_users_count = db.session.query(User.id).count()

        load_krb_user_from_request()

        self.assertEqual(original_users_count, db.session.query(User.id).count())
        self.assertEqual(self.user.id, g.user.id)
        self.assertEqual(self.user.username, g.user.username)
        self.assertEqual(self.user.email, g.user.email)
        self.assertEqual(self.user.krb_realm, g.user.krb_realm)
        self.assertEqual(len(self.user.groups), len(g.user.groups))

    @patch('odcs.auth.request')
    @patch('odcs.auth.g')
    def test_401_if_remote_user_not_present(self, g, request):
        request.environ.get.return_value = None

        self.assertRaises(Unauthorized, load_krb_user_from_request)


class TestQueryLdapGroups(unittest.TestCase):
    """Test auth.query_ldap_groups"""

    @patch('odcs.auth.ldap.initialize')
    def test_get_groups(self, initialize):
        initialize.return_value.search_s.return_value = [
            ('cn=odcsdev,ou=Groups,dc=example,dc=com',
             {'gidNumber': ['5523'], 'cn': ['odcsdev']}),
            ('cn=freshmakerdev,ou=Groups,dc=example,dc=com',
             {'gidNumber': ['17861'], 'cn': ['freshmakerdev']}),
            ('cn=devel,ou=Groups,dc=example,dc=com',
             {'gidNumber': ['5781'], 'cn': ['devel']})
        ]

        groups = query_ldap_groups('me')
        self.assertEqual(sorted(['odcsdev', 'freshmakerdev', 'devel']),
                         sorted(groups))
