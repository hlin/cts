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


from functools import wraps
import requests
import ldap
import flask

from itertools import chain

from flask import abort
from flask import g

from odcs.server import conf, log
from odcs.server.models import User
from odcs.server.models import commit_on_success


@commit_on_success
def load_krb_user_from_request(request):
    """Load Kerberos user from current request

    REMOTE_USER needs to be set in environment variable, that is set by
    frontend Apache authentication module.
    """
    remote_user = request.environ.get('REMOTE_USER')
    if not remote_user:
        abort(401, 'REMOTE_USER is not present in request.')

    username, realm = remote_user.split('@')

    user = User.find_user_by_name(username)
    if not user:
        user = User.create_user(username=username)

    try:
        groups = query_ldap_groups(username)
    except ldap.SERVER_DOWN as e:
        log.error('Cannot query groups of %s from LDAP. Error: %s',
                  username, e.args[0]['desc'])
        groups = []

    g.groups = groups
    g.user = user
    return user


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


@commit_on_success
def load_openidc_user(request):
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

    user = User.find_user_by_name(username)
    if not user:
        user = User.create_user(username=username)

    g.groups = user_info.get('groups', [])
    g.user = user
    return user


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


def init_auth(login_manager, backend):
    """Initialize authentication backend

    Enable and initialize authentication backend to work with frontend
    authentication module running in Apache.
    """
    if backend == 'noauth':
        # Do not enable any authentication backend working with frontend
        # authentication module in Apache.
        return
    if backend == 'kerberos':
        global load_krb_user_from_request
        load_krb_user_from_request = login_manager.request_loader(
            load_krb_user_from_request)
    elif backend == 'openidc':
        global load_openidc_user
        load_openidc_user = login_manager.request_loader(load_openidc_user)
    else:
        raise ValueError('Unknown backend name {0}.'.format(backend))


def requires_role(role):
    """Check if user is in the configured role.

    :param str role: role name, supported roles: 'allowed_clients', 'admins'.
    """
    valid_roles = ['allowed_clients', 'admins']
    if role not in valid_roles:
        raise ValueError("Unknown role <%s> specified, supported roles: %s." % (role, str(valid_roles)))

    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            groups = getattr(conf, role).get('groups', [])
            users = getattr(conf, role).get('users', [])
            in_groups = bool(set(flask.g.groups) & set(groups))
            in_users = flask.g.user.username in users
            if in_groups or in_users:
                return f(*args, **kwargs)
            abort(401, 'User %s is not in role %s.' % (flask.g.user.username, role))
        return wrapped
    return wrapper
