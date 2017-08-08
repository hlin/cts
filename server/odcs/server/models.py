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
# Written by Jan Kaluza <jkaluza@redhat.com>

""" SQLAlchemy Database models for the Flask app
"""

import os

from datetime import datetime, timedelta
from odcs.server import conf
from sqlalchemy.orm import validates
from flask_login import UserMixin

from odcs.server import db
from odcs.server.types import (
    COMPOSE_STATES, INVERSE_COMPOSE_STATES, COMPOSE_FLAGS)


def commit_on_success(func):
    def _decorator(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except:
            db.session.rollback()
            raise
        finally:
            db.session.commit()
    return _decorator


class ODCSBase(db.Model):
    __abstract__ = True


class User(ODCSBase, UserMixin):
    """User information table"""

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), nullable=False, unique=True)

    @classmethod
    def find_user_by_name(cls, username):
        """Find a user by username

        :param str username: a string of username to find user
        :return: user object if found, otherwise None is returned.
        :rtype: User
        """
        try:
            return db.session.query(cls).filter(cls.username == username)[0]
        except IndexError:
            return None

    @classmethod
    def create_user(cls, username):
        user = cls(username=username)
        db.session.add(user)
        return user


class Compose(ODCSBase):
    __tablename__ = "composes"
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    # PungiSourceType
    source_type = db.Column(db.Integer, nullable=False)
    # White-space separated list of koji_tags or modules
    source = db.Column(db.String, nullable=False)
    # Koji event id at which the compose has been generated
    koji_event = db.Column(db.Integer)
    # COMPOSES_STATES
    state = db.Column(db.Integer, nullable=False)
    # COMPOSE_RESULTS
    results = db.Column(db.Integer, nullable=False)
    # White-space separated list of packages
    packages = db.Column(db.String)
    # COMPOSE_FLAGS
    flags = db.Column(db.Integer)
    time_to_expire = db.Column(db.DateTime, nullable=False)
    time_submitted = db.Column(db.DateTime, nullable=False)
    time_done = db.Column(db.DateTime)
    time_removed = db.Column(db.DateTime)
    reused_id = db.Column(db.Integer)

    @classmethod
    def create(cls, session, owner, source_type, source, results,
               seconds_to_live, packages=None, flags=0):
        now = datetime.utcnow()
        compose = cls(
            owner=owner,
            source_type=source_type,
            source=source,
            state="wait",
            results=results,
            time_submitted=now,
            time_to_expire=now + timedelta(seconds=seconds_to_live),
            packages=packages,
            flags=flags,
        )
        session.add(compose)
        return compose

    @classmethod
    def create_copy(cls, session, compose, owner=None, seconds_to_live=None):
        """
        Creates new compose with all the options influencing the resulting
        compose copied from the `compose`. The `owner` and `seconds_to_live`
        can be set independently. The state of copies compose is "wait".
        """
        now = datetime.utcnow()
        if not seconds_to_live:
            seconds_to_live = conf.seconds_to_live

        compose = cls(
            owner=owner or compose.owner,
            source_type=compose.source_type,
            source=compose.source,
            state="wait",
            results=compose.results,
            time_submitted=now,
            time_to_expire=now + timedelta(seconds=seconds_to_live),
            packages=compose.packages,
            flags=compose.flags,
            koji_event=compose.koji_event,
        )
        session.add(compose)
        return compose

    @property
    def name(self):
        if self.reused_id:
            return "odcs-%d" % self.reused_id
        else:
            return "odcs-%d" % self.id

    @property
    def latest_dir(self):
        return "latest-%s-1" % self.name

    @property
    def toplevel_dir(self):
        return os.path.join(conf.target_dir, self.latest_dir)

    @property
    def result_repo_dir(self):
        """
        Returns path to compose directory with per-arch repositories with
        results.
        """
        return os.path.join(self.toplevel_dir, "compose", "Temporary")

    @property
    def result_repo_url(self):
        """
        Returns public URL to compose directory with per-arch repositories.
        """
        return conf.target_dir_url + "/" \
            + os.path.join(self.latest_dir, "compose", "Temporary")

    @validates('state')
    def validate_state(self, key, field):
        if field in COMPOSE_STATES.values():
            return field
        if field in COMPOSE_STATES:
            return COMPOSE_STATES[field]
        raise ValueError("%s: %s, not in %r" % (key, field, COMPOSE_STATES))

    def json(self):
        flags = []
        for name, value in COMPOSE_FLAGS.items():
            if value == 0:
                continue
            if self.flags & value:
                flags.append(name)
        return {
            'id': self.id,
            'owner': self.owner,
            'source_type': self.source_type,
            'source': self.source,
            'state': self.state,
            'state_name': INVERSE_COMPOSE_STATES[self.state],
            'time_to_expire': self._utc_datetime_to_iso(self.time_to_expire),
            'time_submitted': self._utc_datetime_to_iso(self.time_submitted),
            'time_done': self._utc_datetime_to_iso(self.time_done),
            'time_removed': self._utc_datetime_to_iso(self.time_removed),
            'result_repo': self.result_repo_url,
            'flags': flags,
        }

    @staticmethod
    def _utc_datetime_to_iso(datetime_object):
        """
        Takes a UTC datetime object and returns an ISO formatted string
        :param datetime_object: datetime.datetime
        :return: string with datetime in ISO format
        """
        if datetime_object:
            # Converts the datetime to ISO 8601
            return datetime_object.strftime("%Y-%m-%dT%H:%M:%SZ")

        return None

    @classmethod
    def composes_to_expire(cls):
        now = datetime.utcnow()
        return Compose.query.filter(
            Compose.state == COMPOSE_STATES["done"],
            Compose.time_to_expire < now).all()

    def __repr__(self):
        return "<Compose %s, type %r, state %s, owner %s>" % (
            self.source, self.source_type,
            INVERSE_COMPOSE_STATES[self.state], self.owner)
