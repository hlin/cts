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


import requests
import ldap

from itertools import chain

from six.moves import urllib_parse
from flask import abort
from flask import g
from flask import request

from odcs.models import User, Group
from odcs import db, conf, log


def find_user_by_email(email):
    try:
        return db.session.query(User).filter(User.email == email)[0]
    except IndexError:
        return None


def create_user(username, email, krb_realm=None, groups=[]):
    user = User(username=username, email=email, krb_realm=krb_realm)
    db.session.add(user)

    for group in groups:
        user.groups.append(Group(name=group))
    db.session.commit()

    return user


def load_krb_user_from_request():
    """Load Kerberos user from current request

    REMOTE_USER needs to be set in environment variable, that is set by
    frontend Apache authentication module.
    """
    remote_user = request.environ.get('REMOTE_USER')
    if not remote_user:
        abort(401, 'REMOTE_USER is not present in request.')

    username, realm = remote_user.split('@')

    try:
        groups = query_ldap_groups(username)
    except ldap.SERVER_DOWN as e:
        log.error('Cannot query groups of %s from LDAP. Error: %s',
                  username, e.args[0]['desc'])
        groups = []

    email = remote_user.lower()

    user = find_user_by_email(email)
    if not user:
        user = create_user(username=username,
                           email=email,
                           krb_realm=realm,
                           groups=groups)
    g.user = user


def query_ldap_groups(uid):
    ldap_server = conf.auth_ldap_server
    assert ldap_server, 'LDAP server must be configured in advance.'

    group_base = conf.auth_ldap_group_base
    assert group_base, 'Group base must be configured in advance.'

    client = ldap.initialize(ldap_server)
    groups = client.search_s(group_base,
                             ldap.SCOPE_ONELEVEL,
                             attrlist=['cn', 'gidNumber'],
                             filterstr='memberUid={0}'.format(uid))

    group_names = list(chain(*[info['cn'] for _, info in groups]))
    return group_names


def load_openidc_user():
    """Load FAS user from current request"""
    username = request.environ.get('REMOTE_USER')
    if not username:
        abort(401, 'REMOTE_USER is not present in request.')

    token = request.environ.get('OIDC_access_token')
    if not token:
        abort(401, 'Missing token passed into ODCS.')

    scope = request.environ.get('OIDC_CLAIM_scope')
    if not scope:
        abort(401, 'Missing OIDC_CLAIM_scope.')
    validate_scopes(scope)

    user_info = get_user_info(token)
    email = user_info.get('email')
    if not email:
        log.warning('Seems email is not present. Please check scope in client.'
                    ' Fallback to use iss to construct email address.')
        domain = urllib_parse.urlparse(request.environ['OIDC_CLAIM_iss']).netloc
        email = '{0}@{1}'.format(username, domain)
    groups = user_info.get('groups', [])

    user = find_user_by_email(email)
    if not user:
        user = create_user(username=username, email=email, groups=groups)
    g.user = user


def validate_scopes(scope):
    """Validate if request scopes are all in required scope

    :param str scope: scope passed in from.
    :raises: Unauthorized if any of required scopes is not present.
    """
    scopes = scope.split(' ')
    required_scopes = conf.auth_openidc_required_scopes
    for scope in required_scopes:
        if scope not in scopes:
            abort(401, 'Required OIDC scope {0} not present.'.format(scope))


def get_user_info(token):
    """Query FAS groups from Fedora"""
    headers = {
        'authorization': 'Bearer {0}'.format(token)
    }
    r = requests.get(conf.auth_openidc_userinfo_uri, headers=headers)
    if r.status_code != 200:
        abort(401, 'Cannot get user information from {0} endpoint.'.format(
            conf.auth_openidc_userinfo_uri))
    return r.json()


def init_auth(app, backend=None):
    if backend is None or backend == 'noauth':
        return
    if backend == 'kerberos':
        global load_krb_user_from_request
        load_krb_user_from_request = app.before_request(load_krb_user_from_request)
    elif backend == 'openidc':
        global load_openidc_user
        load_openidc_user = app.before_request(load_openidc_user)
    else:
        raise ValueError('Unknown backend name {0}.'.format(backend))
