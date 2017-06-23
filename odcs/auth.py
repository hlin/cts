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


import ldap

from itertools import chain

from flask import abort
from flask import g
from flask import request

from odcs.models import User, Group
from odcs import db, conf, log


def load_krb_user_from_request():
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

    q = db.session.query(User).filter(User.email == email)
    if not db.session.query(User.id).filter(q.exists()).scalar():
        user = User(username=username, email=email, krb_realm=realm)
        db.session.add(user)

        for group in groups:
            user.groups.append(Group(name=group))
        db.session.commit()

    g.user = db.session.query(User).filter(User.email == email)[0]


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


def init_auth(app, backend=None):
    if backend is None or backend == 'noauth':
        return
    if backend == 'kerbers':
        global load_krb_user_from_request
        load_krb_user_from_request = app.before_request(load_krb_user_from_request)
