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

from datetime import datetime
from sqlalchemy.orm import validates

from odcs import db

COMPOSE_STATES = {
    # Compose is waiting to be generated
    "wait": 0,
    # Compose is being generated.
    "generating": 1,
    # Compose is generated - done.
    "done": 2,
    # Compose has been removed.
    "removed": 3,
    # Compose generation has failed.
    "failed": 4,
}

INVERSE_COMPOSE_STATES = {v: k for k, v in COMPOSE_STATES.items()}

COMPOSE_RESULTS = {
    "repository": 1,
    "iso": 2,
    "ostree": 4,
}


class ODCSBase(db.Model):
    __abstract__ = True


class Compose(ODCSBase):
    __tablename__ = "composes"
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    # PungiSourceType
    source_type = db.Column(db.Integer, nullable=False)
    # list of koji_tags or modules
    source = db.Column(db.String, nullable=False)
    # Koji event id at which the compose has been generated
    koji_event = db.Column(db.Integer)
    # COMPOSES_STATES
    state = db.Column(db.Integer, nullable=False)
    # COMPOSE_RESULTS
    results = db.Column(db.Integer, nullable=False)
    # Path/URL to resulting repo.
    result_repo = db.Column(db.String)
    # White-space separated list of packages
    packages = db.Column(db.String)
    seconds_to_live = db.Column(db.Integer, nullable=False)
    time_submitted = db.Column(db.DateTime, nullable=False)
    time_done = db.Column(db.DateTime)
    time_removed = db.Column(db.DateTime)

    @classmethod
    def create(cls, session, owner, source_type, source, results,
               seconds_to_live, packages=None):
        now = datetime.utcnow()
        compose = cls(
            owner=owner,
            source_type=source_type,
            source=source,
            state="wait",
            results=results,
            time_submitted=now,
            seconds_to_live=seconds_to_live,
            packages=packages
        )
        session.add(compose)
        return compose

    @validates('state')
    def validate_state(self, key, field):
        if field in COMPOSE_STATES.values():
            return field
        if field in COMPOSE_STATES:
            return COMPOSE_STATES[field]
        raise ValueError("%s: %s, not in %r" % (key, field, COMPOSE_STATES))

    def json(self):
        return {
            'id': self.id,
            'owner': self.owner,
            'source_type': self.source_type,
            'source': self.source,
            'state': self.state,
            'state_name': INVERSE_COMPOSE_STATES[self.state],
            'time_submitted': self._utc_datetime_to_iso(self.time_submitted),
            'time_done': self._utc_datetime_to_iso(self.time_done),
            'time_removed': self._utc_datetime_to_iso(self.time_removed),
            "result_repo": self.result_repo,
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
    def expired_composes(cls):
        # TODO
        return []

    def __repr__(self):
        return "<Compose %s, type %r, state %s, owner %s>" % (
            self.source, self.source_type,
            INVERSE_COMPOSE_STATES[self.state], self.owner)
