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

import os
from datetime import datetime
from datetime import timedelta

from odcs.server import db, conf
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_RESULTS, COMPOSE_STATES
from odcs.server.models import User
from odcs.server.pungi import PungiSourceType

import pytest

from .utils import ModelsBaseTest


class TestModels(ModelsBaseTest):
    def test_creating_event_and_builds(self):
        compose = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testmodule-master",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()
        db.session.expire_all()

        c = db.session.query(Compose).filter(compose.id == 1).one()
        c.pungi_config_dump = "test"
        self.assertEqual(c.owner, "me")
        self.assertEqual(c.source_type, PungiSourceType.MODULE)
        self.assertEqual(c.source, "testmodule-master")
        self.assertEqual(c.results, COMPOSE_RESULTS["repository"])
        self.assertTrue(c.time_to_expire)

        expected_json = {
            "source_type": 2,
            "state": 0,
            "time_done": None,
            "state_name": "wait",
            "state_reason": None,
            "source": u"testmodule-master",
            "owner": u"me",
            "result_repo": "http://localhost/odcs/odcs-1/compose/Temporary",
            "result_repofile": "http://localhost/odcs/odcs-1/compose/Temporary/odcs-1.repo",
            "time_submitted": c.json()["time_submitted"],
            "id": 1,
            "time_started": None,
            "time_removed": None,
            "removed_by": None,
            "time_to_expire": c.json()["time_to_expire"],
            "flags": [],
            "results": ["repository"],
            "sigkeys": "",
            "koji_event": None,
            "koji_task_id": None,
            "packages": None,
            "builds": None,
            "arches": "x86_64",
            "multilib_arches": "",
            "multilib_method": 0,
            "lookaside_repos": None,
            "modular_koji_tags": None,
            "module_defaults_url": None,
            "label": None,
            "compose_type": None,
            "pungi_compose_id": None,
            "pungi_config_dump": "test",
            "target_dir": "default",
            "toplevel_url": "http://localhost/odcs/odcs-1",
            "scratch_modules": None,
            "modules": None,
            "parent_pungi_compose_ids": None,
            "scratch_build_tasks": None,
            "respin_of": None,
            "base_module_br_name": None,
            "base_module_br_stream": None,
            "base_module_br_stream_version_lte": None,
            "base_module_br_stream_version_gte": None,
        }
        self.assertEqual(c.json(True), expected_json)

    def test_compose_paths(self):
        compose = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testmodule-master",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        compose.id = 1
        self.assertEqual(compose.toplevel_dir, os.path.join(conf.target_dir, "odcs-1"))
        self.assertEqual(
            compose.result_repofile_path,
            os.path.join(conf.target_dir, "odcs-1/compose/Temporary/odcs-1.repo"),
        )
        self.assertEqual(
            compose.result_repo_dir,
            os.path.join(conf.target_dir, "odcs-1/compose/Temporary"),
        )

    def test_target_dir_none(self):
        compose = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testmodule-master",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        compose.target_dir = None
        db.session.commit()
        self.assertEqual(compose.target_dir, conf.target_dir)

    def test_create_copy(self):
        """
        Tests that the Compose atttributes stored in database are copied
        by Compose.create_copy() method.
        """
        compose = Compose.create(
            db.session,
            "me",
            PungiSourceType.MODULE,
            "testmodule-master",
            COMPOSE_RESULTS["repository"],
            3600,
        )
        db.session.commit()

        # Generate non-default data for every attribute in compose, so we can
        # later verify they have been copied to new compose.
        for c in Compose.__table__.columns:
            t = str(c.type)
            if t == "INTEGER":
                new_value = 4
            elif t == "VARCHAR":
                new_value = "non default value"
            elif t == "DATETIME":
                new_value = datetime.utcnow()
            else:
                raise ValueError(
                    "New column type %r added, please handle it " "in this test" % t
                )
            setattr(compose, c.name, new_value)

        db.session.commit()
        db.session.expire_all()

        copy = Compose.create_copy(db.session, compose)
        for c in Compose.__table__.columns:
            # Following are list of fields which should not be copied
            # in create_copy() method.
            if c.name in [
                "id",
                "state",
                "state_reason",
                "time_to_expire",
                "time_done",
                "time_submitted",
                "time_removed",
                "removed_by",
                "reused_id",
                "koji_task_id",
                "time_started",
                "pungi_compose_id",
                "celery_task_id",
            ]:
                assertMethod = self.assertNotEqual
            else:
                assertMethod = self.assertEqual
            assertMethod(
                [c.name, getattr(compose, c.name)], [c.name, getattr(copy, c.name)]
            )


class TestUserModel(ModelsBaseTest):
    def test_find_by_email(self):
        db.session.add(User(username="tester1"))
        db.session.add(User(username="admin"))
        db.session.commit()

        user = User.find_user_by_name("admin")
        self.assertEqual("admin", user.username)

    def test_create_user(self):
        User.create_user(username="tester2")
        db.session.commit()

        user = User.find_user_by_name("tester2")
        self.assertEqual("tester2", user.username)

    def test_no_group_is_added_if_no_groups(self):
        User.create_user(username="tester1")
        db.session.commit()

        user = User.find_user_by_name("tester1")
        self.assertEqual("tester1", user.username)


class ComposeModel(ModelsBaseTest):
    """Test Compose Model"""

    def setUp(self):
        super(ComposeModel, self).setUp()

        self.c1 = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
        )
        self.c2 = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1",
        )
        self.c3 = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1",
        )
        self.c4 = Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            packages="pkg1",
        )

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

    def test_transition_to_done_updates_time_to_expire(self):
        in_five_minutes = datetime.utcnow() + timedelta(seconds=300)
        self.c1.transition(COMPOSE_STATES["done"], "it's finished", in_five_minutes)
        # The compose should expire about 60 seconds (give or take a tenth of a
        # second) after the time it was finished.
        expires_in = self.c1.time_to_expire - self.c1.time_done
        assert expires_in.total_seconds() == pytest.approx(60, abs=0.1)

    def test_transition_to_failed_updates_time_to_expire(self):
        now = datetime.utcnow()
        in_five_minutes = now + timedelta(seconds=300)
        # Fail the compose in five minutes...
        self.c1.transition(COMPOSE_STATES["failed"], "it's finished", in_five_minutes)
        # so that it expires in about 6 minutes
        expires_in = self.c1.time_to_expire - now
        assert expires_in.total_seconds() == pytest.approx(360, abs=0.1)

    def test_transition_to_generating_updates_time_started(self):
        now = datetime.utcnow()
        in_five_minutes = now + timedelta(seconds=300)
        self.c1.transition(COMPOSE_STATES["generating"], "it started", in_five_minutes)
        assert self.c1.time_started == in_five_minutes
