# -*- coding: utf-8 -*-
# Copyright (c) 2020  Red Hat, Inc.
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

"""SQLAlchemy Database models for the Flask app"""


import json
from flask_login import UserMixin
from productmd import ComposeInfo
from datetime import datetime

from cts import db
from cts.events import cache_composes_if_state_changed
from cts.events import start_to_publish_messages

from sqlalchemy import event
from sqlalchemy.orm import backref
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import FlushError
from flask_sqlalchemy import SignallingSession

event.listen(SignallingSession, "after_flush", cache_composes_if_state_changed)

event.listen(SignallingSession, "after_commit", start_to_publish_messages)


def commit_on_success(func):
    def _decorator(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.commit()

    return _decorator


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


class CTSBase(db.Model):
    __abstract__ = True


class User(CTSBase, UserMixin):
    """User information table"""

    __tablename__ = "users"

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

    @classmethod
    def get_or_create(cls, username):
        """Look up user with given username, creating one if not exist.

        :param str username: a string of username to find/create user.
        :return: user object.
        :rtype: User
        """
        user = cls.find_user_by_name(username)
        if user:
            return user
        else:
            return cls.create_user(username)


composes_to_composes = db.Table(
    "composes_to_composes",
    db.Column(
        "parent_compose_id", db.String, db.ForeignKey("composes.id"), nullable=False
    ),
    db.Column(
        "child_compose_id", db.String, db.ForeignKey("composes.id"), nullable=False
    ),
    db.UniqueConstraint(
        "parent_compose_id", "child_compose_id", name="unique_composes"
    ),
)


tags_to_composes = db.Table(
    "tags_to_composes",
    db.Column("compose_id", db.String, db.ForeignKey("composes.id"), nullable=False),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), nullable=False),
    db.UniqueConstraint("compose_id", "tag_id", name="unique_tags"),
)


taggers = db.Table(
    "taggers",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), nullable=False),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), nullable=False),
    db.UniqueConstraint("user_id", "tag_id", name="unique_taggers"),
)


untaggers = db.Table(
    "untaggers",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), nullable=False),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), nullable=False),
    db.UniqueConstraint("user_id", "tag_id", name="unique_untaggers"),
)


class TaggerGroups(CTSBase):
    __tablename__ = "tagger_groups"
    group = db.Column(db.String(200), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), nullable=False)
    __table_args__ = (
        db.PrimaryKeyConstraint("group", "tag_id", name="tagger_groups_pk"),
    )


class UntaggerGroups(CTSBase):
    __tablename__ = "untagger_groups"
    group = db.Column(db.String(200), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), nullable=False)
    __table_args__ = (
        db.PrimaryKeyConstraint("group", "tag_id", name="untagger_groups_pk"),
    )


class TagChange(CTSBase):
    __tablename__ = "tag_changes"

    id = db.Column(db.Integer, primary_key=True)
    # Time when this Tag change happened
    time = db.Column(db.DateTime, nullable=False)
    # Tag associated with this record.
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), nullable=False)
    # Action: "created", "add_tagger", "remove_tagger", "add_tagger", "remove_untagger"
    action = db.Column(db.String)
    # User which did the Tag change.
    user_id = db.Column(
        "user_id", db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    user = db.relationship("User", lazy=False)
    # Automatic message with more information about this change.
    message = db.Column(db.String, nullable=True)
    # User data associated with this change further describing it.
    user_data = db.Column(db.String, nullable=True)

    @classmethod
    def create(cls, session, tag, username, **kwargs):
        user = User.find_user_by_name(username)
        tag_change = cls(
            time=datetime.utcnow(), tag_id=tag.id, user_id=user.id, **kwargs
        )
        session.add(tag_change)
        session.commit()
        return tag_change

    def json(self):
        return {
            "time": _utc_datetime_to_iso(self.time),
            "action": self.action,
            "user": self.user.username,
            "message": self.message,
            "user_data": self.user_data,
        }


class Tag(CTSBase):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, unique=True)
    # Short description of the tag.
    description = db.Column(db.String, nullable=False)
    # Link to tag documentation.
    documentation = db.Column(db.String, nullable=False)
    # Users allowed to tag the compose with this tag.
    taggers = db.relationship("User", secondary=taggers)
    # Users allowed to untag the compose with this tag.
    untaggers = db.relationship("User", secondary=untaggers)
    # Groups allowed to tag the compose with this tag.
    tagger_groups = db.relationship("TaggerGroups", cascade="all, delete-orphan")
    # Groups allowed to untag the compose with this tag.
    untagger_groups = db.relationship("UntaggerGroups", cascade="all, delete-orphan")

    changes = db.relationship("TagChange")

    @classmethod
    def create(cls, session, logged_user, user_data=None, **kwargs):
        tag = cls(**kwargs)
        session.add(tag)
        session.commit()

        TagChange.create(
            session, tag, logged_user, action="created", user_data=user_data
        )
        return tag

    @classmethod
    def get_by_name(cls, tag_name):
        """Find a Tag by its name

        :param str tag_name: Tag name.
        :return Tag: Tag object.
        """
        try:
            return db.session.query(cls).filter(cls.name == tag_name)[0]
        except IndexError:
            return None

    def add_tagger(self, logged_user, username=None, group=None, user_data=None):
        """
        Grant `username` or `group` permissions to tag the compose with this tag.

        :param str logged_user: Username of the logged user.
        :param str username: Username to add permission to.
        :param str group: Group to add permission to.
        :param str user_data: User data to add to TagChange record.
        :return bool: True if permissions granted, False if user does not exist.
        """
        if username:
            u = User.get_or_create(username)

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="add_tagger",
                user_data=user_data,
                message='Tagger permission granted to user "%s".' % username,
            )
            self.taggers.append(u)

        if group:
            tg = TaggerGroups.query.filter_by(group=group, tag_id=self.id).first()
            if tg:
                # Permission granted already.
                return True

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="add_tagger",
                user_data=user_data,
                message='Tagger permission granted to group "%s".' % group,
            )
            self.tagger_groups.append(TaggerGroups(group=group))

        return True

    def remove_tagger(self, logged_user, username=None, group=None, user_data=None):
        """
        Revoke `username` or `group` permissions to tag the compose with this tag.

        :param str logged_user: Username of the logged user.
        :param str username: Username to remove permission from.
        :param str group: Group to remove permission from.
        :param str user_data: User data to add to TagChange record.
        :return bool: True if permissions revoked, False if user does not exist.
        """
        if username:
            u = User.find_user_by_name(username)
            if not u:
                return False

            try:
                self.taggers.remove(u)
            except ValueError:
                # User is not there, so return True.
                return True

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="remove_tagger",
                user_data=user_data,
                message='Tagger permission removed from user "%s".' % username,
            )

        if group:
            tg = TaggerGroups.query.filter_by(group=group, tag_id=self.id).first()
            try:
                self.tagger_groups.remove(tg)
            except ValueError:
                # Group is not there, so return True.
                return True

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="remove_tagger",
                user_data=user_data,
                message='Tagger permission removed from group "%s".' % group,
            )

        return True

    def add_untagger(self, logged_user, username=None, group=None, user_data=None):
        """
        Grant `username` or `group` permissions to untag the compose with this tag.

        :param str logged_user: Username of the logged user.
        :param str username: Username to add permission to.
        :param str group: Group to add permission to.
        :param str user_data: User data to add to TagChange record.
        :return bool: True if permissions granted, False if user does not exist.
        """
        if username:
            u = User.get_or_create(username)

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="add_untagger",
                user_data=user_data,
                message='Untagger permission granted to user "%s".' % username,
            )

            self.untaggers.append(u)

        if group:
            tg = UntaggerGroups.query.filter_by(group=group, tag_id=self.id).first()
            if tg:
                # Permission granted already.
                return True

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="add_untagger",
                user_data=user_data,
                message='Untagger permission granted to group "%s".' % group,
            )

            self.untagger_groups.append(UntaggerGroups(group=group))

        return True

    def remove_untagger(self, logged_user, username=None, group=None, user_data=None):
        """
        Revoke `username` or `group` permissions to untag the compose with this tag.

        :param str logged_user: Username of the logged user.
        :param str username: Username to remove permission from.
        :param str group: Group to remove permission from.
        :param str user_data: User data to add to TagChange record.
        :return bool: True if permissions revoked, False if user does not exist.
        """
        if username:
            u = User.find_user_by_name(username)
            if not u:
                return False

            try:
                self.untaggers.remove(u)
            except ValueError:
                # User is not there, so return True.
                return True

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="remove_untagger",
                user_data=user_data,
                message='Untagger permission removed from user "%s".' % username,
            )

        if group:
            tg = UntaggerGroups.query.filter_by(group=group, tag_id=self.id).first()
            try:
                self.untagger_groups.remove(tg)
            except ValueError:
                # Group is not there, so return True.
                return True

            TagChange.create(
                db.session,
                self,
                logged_user,
                action="remove_untagger",
                user_data=user_data,
                message='Untagger permission removed from group "%s".' % group,
            )

        return True

    def json(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "documentation": self.documentation,
            "taggers": [u.username for u in self.taggers],
            "untaggers": [u.username for u in self.untaggers],
            "tagger_groups": [g.group for g in self.tagger_groups],
            "untagger_groups": [g.group for g in self.untagger_groups],
        }


class ComposeChange(CTSBase):
    __tablename__ = "compose_changes"

    id = db.Column(db.Integer, primary_key=True)
    # Time when this Compose change happened.
    time = db.Column(db.DateTime, nullable=False)
    # Compose associated with this change.
    compose_id = db.Column(db.String, db.ForeignKey("composes.id"), nullable=False)
    # Action: "created", "tagged", "untagged"
    action = db.Column(db.String)
    # User which did the Compose change.
    user_id = db.Column(
        "user_id", db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    user = db.relationship("User", lazy=False)
    # Automatic message with more information about this change.
    message = db.Column(db.String, nullable=True)
    # User data associated with this change further describing it.
    user_data = db.Column(db.String, nullable=True)

    @classmethod
    def create(cls, session, compose, username, **kwargs):
        user = User.find_user_by_name(username)
        compose_change = cls(
            time=datetime.utcnow(), compose_id=compose.id, user_id=user.id, **kwargs
        )
        session.add(compose_change)
        session.commit()
        return compose_change

    def json(self):
        return {
            "time": _utc_datetime_to_iso(self.time),
            "action": self.action,
            "user": self.user.username,
            "message": self.message,
            "user_data": self.user_data,
        }


class Compose(CTSBase):
    __tablename__ = "composes"

    # productmd.ComposeInfo.Compose fields
    id = db.Column(db.String, primary_key=True)
    date = db.Column(db.String)
    respin = db.Column(db.Integer)
    type = db.Column(db.String)
    label = db.Column(db.String, nullable=True)
    final = db.Column(db.Boolean, default=False)

    # This is a redundant column combined of date.respin, e.g 20221123.1
    # Adding this column as date and respin are expected unique together
    # for new composes and existing data proabaly violates this constraint.
    date_respin = db.Column(db.String, nullable=True, unique=True)
    # This is a redundant column combining release_short, release_version,
    # date and respin. It's used to make date.respin combination unique for
    # each release stream.
    # Old data violates this, thus it's nullable.
    release_date_respin = db.Column(db.String, nullable=True, unique=True)

    # productmd.ComposeInfo.Release fields
    release_name = db.Column(db.String)
    release_version = db.Column(db.String)
    release_short = db.Column(db.String)
    release_is_layered = db.Column(db.Boolean, default=False)
    release_type = db.Column(db.String, nullable=True)
    release_internal = db.Column(db.Boolean, default=False)

    # productmd.ComposeInfo.BaseProduct
    base_product_name = db.Column(db.String, nullable=True)
    base_product_short = db.Column(db.String, nullable=True)
    base_product_version = db.Column(db.String, nullable=True)
    base_product_type = db.Column(db.String, nullable=True)

    # Name of the user account which built the compose.
    builder = db.Column(db.String)
    # Compose tags.
    tags = db.relationship("Tag", secondary=tags_to_composes)
    # Add "parents" and "children" relationships between composes.
    parents = db.relationship(
        "Compose",
        secondary=composes_to_composes,
        primaryjoin=id == composes_to_composes.c.child_compose_id,
        secondaryjoin=id == composes_to_composes.c.parent_compose_id,
        backref="children",
    )

    respin_of_id = db.Column(db.String, db.ForeignKey("composes.id"))
    # Add "respin_of" and "respun_by" relationships between composes.
    respin_of = db.relationship(
        "Compose",
        remote_side=[id],
        backref=backref("respun_by"),
        uselist=False,
        foreign_keys=[respin_of_id],
    )

    # Current URL to the top level directory of this compose
    compose_url = db.Column(db.String, nullable=True)

    changes = db.relationship("ComposeChange", order_by="ComposeChange.time")

    @classmethod
    def create(
        cls,
        session,
        builder,
        ci,
        user_data=None,
        parent_compose_ids=None,
        respin_of=None,
        compose_url=None,
    ):
        """
        Creates new Compose and commits it to database ensuring that its ID is unique.

        :param session: SQLAlchemy session.
        :param str builder: Name of the user (service) building this compose.
        :param productmd.ComposeInfo ci: ComposeInfo metadata.
        :param str user_data: Optional user data to add to ComposeChange record.
        :param list parent_compose_ids: List of parent compose IDs.
        :param str respin_of: Compose ID of compose this compose respins.
        :param str compose_url: Current URL to the top level directory of this compose.
        :return tuple: (Compose, productmd.ComposeInfo) - tuple with newly created
            Compose and changed ComposeInfo metadata.
        """

        # Find parent Compose instances before creating the Compose to be sure
        # the parent_compose_ids are correct.
        parent_composes = []
        for parent_compose_id in parent_compose_ids or []:
            parent_compose = Compose.query.filter(
                Compose.id == parent_compose_id
            ).first()
            if not parent_compose:
                raise ValueError(
                    "Cannot find parent compose with id %s." % parent_compose_id
                )
            parent_composes.append(parent_compose)

        # Find respin_of Compose instance before creating the Compose to be sure
        # the respin_of is correct.
        if respin_of:
            respin_of_compose = Compose.query.filter(Compose.id == respin_of).first()
            if not respin_of_compose:
                raise ValueError(
                    "Cannot find respin_of compose with id %s." % respin_of
                )

        while True:
            release = f"{ci.release.short}-{ci.release.version}"
            date_respin = f"{ci.compose.date}.{ci.compose.respin}"
            release_date_respin = f"{release}-{date_respin}"
            kwargs = {
                "id": ci.create_compose_id(),
                "date": ci.compose.date,
                "respin": ci.compose.respin,
                "release_date_respin": release_date_respin,
                "type": ci.compose.type,
                "label": ci.compose.label,
                "final": ci.compose.final,
                "release_name": ci.release.name,
                "release_version": ci.release.version,
                "release_short": ci.release.short,
                "release_is_layered": ci.release.is_layered,
                "release_type": ci.release.type,
                "release_internal": ci.release.internal,
                "base_product_name": ci.base_product.name,
                "base_product_short": ci.base_product.short,
                "base_product_version": ci.base_product.version,
                "base_product_type": ci.base_product.type,
                "builder": builder,
                "compose_url": compose_url,
            }
            compose = cls(**kwargs)
            session.add(compose)
            try:
                session.commit()
                break
            except (IntegrityError, FlushError):
                # Both IntegrityError and FlushError can be raised when the compose with
                # the same ID already exists in database.
                session.rollback()

                # Really check that the IntegrityError was caused by
                # existing compose.
                existing_compose = Compose.query.filter(
                    (Compose.id == kwargs["id"])
                    | (Compose.release_date_respin == release_date_respin)
                ).first()
                if not existing_compose:
                    raise
            # In case session.commit() failed with IntegrityErroir, increase
            # the `respin` and try again.
            ci.compose.respin += 1
            ci.compose.id = ci.create_compose_id()

        # Add parent composes.
        for parent_compose in parent_composes:
            compose.parents.append(parent_compose)
        # Add respin_of compose:
        if respin_of:
            compose.respin_of = respin_of_compose
        session.commit()

        ComposeChange.create(
            session, compose, builder, action="created", user_data=user_data
        )
        return compose, ci

    def json(self, full=False):
        ci = ComposeInfo()
        ci.compose.id = self.id
        ci.compose.type = self.type
        ci.compose.date = self.date
        ci.compose.respin = self.respin
        ci.compose.label = self.label
        ci.release.name = self.release_name
        ci.release.short = self.release_short
        ci.release.version = self.release_version
        ci.release.is_layered = self.release_is_layered
        ci.release.type = self.release_type
        ci.release.internal = self.release_internal
        ci.base_product.name = self.base_product_name
        ci.base_product.short = self.base_product_short
        ci.base_product.version = self.base_product_version
        ci.base_product.type = self.base_product_type

        return {
            "compose_info": json.loads(ci.dumps()),
            "builder": self.builder,
            "tags": [tag.name for tag in self.tags],
            "parents": [c.id for c in self.parents],
            "children": [c.id for c in self.children],
            "respin_of": self.respin_of.id if self.respin_of else None,
            "respun_by": [c.id for c in self.respun_by],
            "compose_url": self.compose_url,
        }

    def tag(self, logged_user, tag_name, user_data=None):
        """
        Tag the compose with tag `tag_name.

        :param str logged_user: Username of the logged user.
        :param str tag_name: Name of the tag.
        :param str user_data: User data to add to ComposeChange record.
        :return bool: True if compose tagged, False if tag does not exist.
        """
        t = Tag.get_by_name(tag_name)
        if not t:
            return False

        if t in self.tags:
            # Tag is already added.
            return True

        user = User.find_user_by_name(logged_user)
        change = ComposeChange(
            time=datetime.utcnow(),
            compose_id=self.id,
            user_id=user.id,
            action="tagged",
            user_data=user_data,
            message='User "%s" added "%s" tag.' % (logged_user, tag_name),
        )
        self.changes.append(change)
        self.tags.append(t)
        return True

    def untag(self, logged_user, tag_name, user_data=None):
        """
        Remove the tag `tag_name from the compose.

        :param str logged_user: Username of the logged user.
        :param str tag_name: Name of the tag.
        :param str user_data: User data to add to ComposeChange record.
        :return bool: True if compose untagged, False if tag does not exist.
        """
        t = Tag.get_by_name(tag_name)
        if not t:
            return False

        if t not in self.tags:
            # Tag is not there, so return True.
            return True

        user = User.find_user_by_name(logged_user)
        change = ComposeChange(
            time=datetime.utcnow(),
            compose_id=self.id,
            user_id=user.id,
            action="untagged",
            user_data=user_data,
            message='User "%s" removed "%s" tag.' % (logged_user, tag_name),
        )
        self.changes.append(change)
        self.tags.remove(t)
        return True

    def retag_stale_composes(self, logged_user, timeout, user_data=None):
        """
        Find and retag the composes with -requested tag and retag if the timeout occurs.

        :param str logged_user: Username of the logged user.
        :param int timeout: Timeout value in hours for retagging.
        :param str user_data: User data to add to ComposeChange record.
        :return Generator: The tag information that is retagged.
        """
        for tag in self.tags[:]:
            if "requested" in tag.name:
                # Get the latest requested tag info
                last_change = (
                    ComposeChange.query.filter(
                        ComposeChange.compose_id == self.id,
                        ComposeChange.action == "tagged",
                        ComposeChange.message.contains('"' + tag.name + '"'),
                    )
                    .order_by(ComposeChange.time.desc())
                    .first()
                )
                if datetime.utcnow() - last_change.time > timeout:
                    # Untag compose
                    self.untag(logged_user, tag.name, user_data)
                    db.session.commit()

                    # Tag compose again with -requested
                    self.tag(logged_user, tag.name, user_data)
                    db.session.commit()
                yield tag
