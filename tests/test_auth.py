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


import flask
import unittest

from mock import patch, Mock

import odcs.auth

from odcs.auth import load_krb_user_from_request
from odcs.auth import load_openidc_user
from odcs.auth import query_ldap_groups
from odcs.auth import init_auth
from odcs import app, db
from odcs.models import User
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


class TestLoadOpenIDCUserFromRequest(ModelsBaseTest):

    def setUp(self):
        super(TestLoadOpenIDCUserFromRequest, self).setUp()

        self.user = User(username='tester1', email='tester1@example.com')
        db.session.add(self.user)
        db.session.commit()

    @patch('odcs.auth.requests.get')
    def test_create_new_user(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'email': 'new_user@example.com',
            'groups': ['tester', 'admin'],
            'name': 'new_user',
        }

        environ_base = {
            'REMOTE_USER': 'new_user',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            load_openidc_user()

            new_user = db.session.query(User).filter(
                User.email == 'new_user@example.com')[0]

            self.assertEqual(new_user, flask.g.user)
            self.assertEqual('new_user', flask.g.user.username)
            self.assertEqual('new_user@example.com', flask.g.user.email)
            self.assertEqual(sorted(['admin', 'tester']),
                             sorted([grp.name for grp in flask.g.user.groups]))

    @patch('odcs.auth.requests.get')
    def test_return_existing_user(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'email': self.user.email,
            'groups': ['tester', 'admin'],
            'name': self.user.username,
        }

        environ_base = {
            'REMOTE_USER': self.user.username,
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            original_users_count = db.session.query(User.id).count()

            load_openidc_user()

            users_count = db.session.query(User.id).count()
            self.assertEqual(original_users_count, users_count)

            # Ensure existing user is set in g
            self.assertEqual(self.user, flask.g.user)

    def test_401_if_remote_user_not_present(self):
        environ_base = {
            # Missing REMOTE_USER here
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            self.assertRaises(Unauthorized, load_openidc_user)

    def test_401_if_access_token_not_present(self):
        environ_base = {
            'REMOTE_USER': 'tester1',
            # Missing OIDC_access_token here
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            self.assertRaises(Unauthorized, load_openidc_user)

    @patch('odcs.auth.requests.get')
    def test_use_iss_to_construct_email_if_email_is_missing(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'groups': ['tester', 'admin'],
            'name': self.user.username,
        }

        environ_base = {
            'REMOTE_USER': 'new_user',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            load_openidc_user()
            self.assertEqual('new_user@iddev.fedorainfracloud.org',
                             flask.g.user.email)

    def test_401_if_scope_not_present(self):
        environ_base = {
            'REMOTE_USER': 'tester1',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            # Missing OIDC_CLAIM_scope here
        }
        with app.test_request_context(environ_base=environ_base):
            self.assertRaises(Unauthorized, load_openidc_user)

    def test_401_if_required_scope_not_present_in_token_scope(self):
        environ_base = {
            'REMOTE_USER': 'new_user',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with patch.object(odcs.auth.conf,
                          'auth_openidc_required_scopes',
                          ['new-compose']):
            with app.test_request_context(environ_base=environ_base):
                self.assertRaisesRegexp(
                    Unauthorized,
                    'Required OIDC scope new-compose not present.',
                    load_openidc_user)


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


class TestInitAuth(unittest.TestCase):
    """Test init_auth"""

    def test_select_kerberos_auth_backend(self):
        app = Mock()
        init_auth(app, 'kerberos')
        app.before_request.assert_called_once_with(load_krb_user_from_request)

    def test_select_openidc_auth_backend(self):
        app = Mock()
        init_auth(app, 'openidc')
        app.before_request.assert_called_once_with(load_openidc_user)

    def test_not_use_auth_backend(self):
        app = Mock()
        init_auth(app)
        app.before_request.assert_not_called()

        init_auth(app, 'noauth')
        app.before_request.assert_not_called()

    def test_error_if_select_an_unknown_backend(self):
        app = Mock()
        self.assertRaises(ValueError, init_auth, app, 'xxx')
        self.assertRaises(ValueError, init_auth, app, '')
