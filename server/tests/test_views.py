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

import six
import contextlib
import json

from datetime import datetime, timedelta

import flask

from werkzeug.exceptions import BadRequest
from freezegun import freeze_time
from mock import patch, PropertyMock, call

import odcs.server.auth

from odcs.server import conf, db, app, login_manager, version
from odcs.server.models import Compose, User
from odcs.common.types import (
    COMPOSE_STATES,
    COMPOSE_RESULTS,
    COMPOSE_FLAGS,
    MULTILIB_METHODS,
)
from odcs.server.pungi import PungiSourceType
from .utils import ModelsBaseTest
from odcs.server.api_utils import validate_json_data

import unittest


@login_manager.user_loader
def user_loader(username):
    return User.find_user_by_name(username=username)


class TestValidateJSONData(unittest.TestCase):
    def test_validate_json_data_allowed_dict(self):
        data = {"source": {"source": ""}}
        validate_json_data(data)

    def test_validate_json_data_unallowed_dict(self):
        data = {"source": {"source": {"k": "v"}}}
        self.assertRaises(ValueError, validate_json_data, data)

    def test_validate_json_data_unallowed_dict_toplevel(self):
        data = {"source2": {"source": {"k": "v"}}}
        self.assertRaises(ValueError, validate_json_data, data)

    def test_validate_json_data_list(self):
        data = {"source": ["1", "2"]}
        validate_json_data(data)

    def test_validate_json_data_list_unallowed_chars(self):
        for char in ["\n", "{", "}", "'", '"']:
            data = {"source": ["%s1" % char, "2"]}
            self.assertRaises(ValueError, validate_json_data, data)

    def test_validate_json_data_str_unallowed_chars(self):
        for char in ["\n", "{", "}", "'", '"']:
            data = {"source": {"x": char + "1"}}
            self.assertRaises(ValueError, validate_json_data, data)

    def test_validate_json_data_int(self):
        data = {"source": {"x": 1}}
        validate_json_data(data)

    def test_validate_json_data_float(self):
        data = {"source": {"x": 1.5}}
        validate_json_data(data)

    def test_validate_json_data_unallowed_type(self):
        data = {"source": {"x": PropertyMock()}}
        self.assertRaises(ValueError, validate_json_data, data)

    def test_validate_json_data_allowed_package(self):
        data = {"packages": ["gcc-g++"]}
        validate_json_data(data)

    def test_validate_json_data_not_list(self):
        data = {"source": {"builds": "kernel-4.0-1.el8"}}
        with self.assertRaises(ValueError) as ctx:
            validate_json_data(data)
        self.assertEqual("builds should be a list", str(ctx.exception))

    def test_validate_json_data_not_str(self):
        data = {"source": {"compose_type": 123}}
        with self.assertRaises(ValueError) as ctx:
            validate_json_data(data)
        self.assertEqual("compose_type should be a string", str(ctx.exception))

    def test_validate_json_data_not_int(self):
        data = {"source": {"koji_event": "abc"}}
        with self.assertRaises(ValueError) as ctx:
            validate_json_data(data)
        self.assertEqual("koji_event should be an integer", str(ctx.exception))


class ViewBaseTest(ModelsBaseTest):
    def setUp(self):
        super(ViewBaseTest, self).setUp()

        patched_allowed_clients = {
            "groups": {
                "composer": {},
                "dev2": {"source_types": ["module"]},
                "dev3": {"source_types": ["raw_config"]},
            },
            "users": {
                "dev": {"arches": ["ppc64", "s390", "x86_64"]},
                "dev2": {
                    "source_types": ["module", "raw_config"],
                    "compose_types": ["test", "nightly"],
                },
                "dev3": {"source_types": ["tag"], "target_dirs": ["releng-private"]},
                "dev4": {
                    "source_types": ["raw_config"],
                    "raw_config_keys": ["pungi_cfg2"],
                },
            },
        }
        patched_admins = {"groups": ["admin"], "users": ["root"]}
        self.patch_allowed_clients = patch.object(
            odcs.server.auth.conf, "allowed_clients", new=patched_allowed_clients
        )
        self.patch_admins = patch.object(
            odcs.server.auth.conf, "admins", new=patched_admins
        )
        self.patch_allowed_clients.start()
        self.patch_admins.start()

        self.client = app.test_client()

        self.setup_test_data()

    def tearDown(self):
        super(ViewBaseTest, self).tearDown()

        self.patch_allowed_clients.stop()
        self.patch_admins.stop()

    @contextlib.contextmanager
    def test_request_context(self, user=None, groups=None, **kwargs):
        with app.test_request_context(**kwargs):
            patch_auth_backend = None
            if user is not None:
                # authentication is disabled with auth_backend=noauth
                patch_auth_backend = patch.object(
                    odcs.server.auth.conf, "auth_backend", new="kerberos"
                )
                patch_auth_backend.start()
                if not User.find_user_by_name(user):
                    User.create_user(username=user)
                    db.session.commit()
                flask.g.user = User.find_user_by_name(user)

                if groups is not None:
                    if isinstance(groups, list):
                        flask.g.groups = groups
                    else:
                        flask.g.groups = [groups]
                else:
                    flask.g.groups = []
                with self.client.session_transaction() as sess:
                    sess["user_id"] = user
                    sess["_fresh"] = True
            try:
                yield
            finally:
                if patch_auth_backend is not None:
                    patch_auth_backend.stop()

    def setup_test_data(self):
        """Set up data for running tests"""


class TestOpenIDCLogin(ViewBaseTest):
    """Test that OpenIDC login"""

    def setUp(self):
        super(TestOpenIDCLogin, self).setUp()
        self.patch_auth_backend = patch.object(
            odcs.server.auth.conf, "auth_backend", new="openidc"
        )
        self.patch_auth_backend.start()

    def tearDown(self):
        super(TestOpenIDCLogin, self).tearDown()
        self.patch_auth_backend.stop()

    def test_openidc_post_unauthorized(self):
        rv = self.client.post("/api/1/composes/", data="")
        self.assertEqual(rv.status, "401 UNAUTHORIZED")

    def test_openidc_patch_unauthorized(self):
        rv = self.client.patch("/api/1/composes/1")
        self.assertEqual(rv.status, "401 UNAUTHORIZED")

    def test_openidc_delete_unauthorized(self):
        rv = self.client.delete("/api/1/composes/1")
        self.assertEqual(rv.status, "401 UNAUTHORIZED")


class TestHandlingErrors(ViewBaseTest):
    """Test registered error handlers"""

    @patch("odcs.server.views.ODCSAPI.delete")
    def test_bad_request_error(self, delete):
        delete.side_effect = BadRequest("bad request to delete")

        resp = self.client.delete("/api/1/composes/100")
        data = json.loads(resp.get_data(as_text=True))

        self.assertEqual("Bad Request", data["error"])
        self.assertEqual(400, data["status"])
        self.assertIn("bad request to delete", data["message"])

    def test_return_internal_server_error_if_error_is_not_caught(self):
        possible_errors = [
            RuntimeError("runtime error"),
            IndexError("out of scope"),
            OSError("os error"),
        ]
        for e in possible_errors:
            with patch("odcs.server.views.filter_composes", side_effect=e):
                resp = self.client.get("/api/1/composes/")
                data = json.loads(resp.get_data(as_text=True))

                self.assertEqual("Internal Server Error", data["error"])
                self.assertEqual(500, data["status"])
                self.assertEqual(str(e), data["message"])


class TestViews(ViewBaseTest):
    maxDiff = None

    def setUp(self):
        super(TestViews, self).setUp()
        self.oidc_base_namespace = patch.object(
            conf, "oidc_base_namespace", new="http://example.com/"
        )
        self.oidc_base_namespace.start()

    def tearDown(self):
        self.oidc_base_namespace.stop()
        super(TestViews, self).tearDown()

    def setup_test_data(self):
        self.initial_datetime = datetime(
            year=2016, month=1, day=1, hour=0, minute=0, second=0
        )
        with freeze_time(self.initial_datetime):
            self.c1 = Compose.create(
                db.session,
                "unknown",
                PungiSourceType.MODULE,
                "testmodule:master",
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
            )
            db.session.add(self.c1)
            db.session.add(self.c2)
            db.session.commit()

    def test_metrics(self):
        rv = self.client.get("/api/1/metrics/")
        data = rv.get_data(as_text=True)
        self.assertTrue("HELP composes_total Total number of composes" in data)

    def test_index(self):
        rv = self.client.get("/")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.content_type, "text/html; charset=utf-8")
        data = rv.get_data(as_text=True)
        self.assertIn("On Demand Compose Service", data)

    def test_about(self):
        rv = self.client.get("/api/1/about/")
        data = json.loads(rv.get_data(as_text=True))
        self.assertEqual(
            data,
            {
                "version": version,
                "auth_backend": "noauth",
                "raw_config_urls": {},
                "allowed_clients": odcs.server.auth.conf.allowed_clients,
                "sigkeys": [],
            },
        )

    def test_submit_invalid_json(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post("/api/1/composes/", data="{")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(rv.status, "400 BAD REQUEST")
        self.assertEqual(data["error"], "Bad Request")
        self.assertEqual(data["status"], 400)
        self.assertTrue(data["message"].find("Failed to decode JSON object") != -1)

    def test_submit_build(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        expected_json = {
            "source_type": 2,
            "state": 0,
            "time_done": None,
            "state_name": "wait",
            "state_reason": None,
            "source": u"testmodule:master",
            "owner": u"dev",
            "result_repo": "http://localhost/odcs/odcs-%d/compose/Temporary"
            % data["id"],
            "result_repofile": "http://localhost/odcs/odcs-%d/compose/Temporary/odcs-%d.repo"
            % (data["id"], data["id"]),
            "time_submitted": data["time_submitted"],
            "id": data["id"],
            "time_started": None,
            "time_removed": None,
            "removed_by": None,
            "time_to_expire": data["time_to_expire"],
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
            "lookaside_repos": "",
            "modular_koji_tags": None,
            "module_defaults_url": None,
            "label": None,
            "compose_type": "test",
            "pungi_compose_id": None,
            "target_dir": "default",
            "scratch_modules": None,
            "modules": None,
            "toplevel_url": "http://localhost/odcs/odcs-%d" % data["id"],
            "parent_pungi_compose_ids": None,
            "scratch_build_tasks": None,
            "respin_of": None,
            "base_module_br_name": None,
            "base_module_br_stream": None,
            "base_module_br_stream_version_lte": None,
            "base_module_br_stream_version_gte": None,
        }
        self.assertEqual(data, expected_json)

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_no_packages(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "tag", "source": "f26"}, "flags": ["no_deps"]}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["state_name"], "wait")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.packages, None)

    def test_submit_build_nodeps(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "flags": ["no_deps"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["flags"], ["no_deps"])

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.flags, COMPOSE_FLAGS["no_deps"])

    def test_submit_build_noinheritance(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "flags": ["no_inheritance"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["flags"], ["no_inheritance"])

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.flags, COMPOSE_FLAGS["no_inheritance"])

    def test_submit_build_boot_iso(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "results": ["boot.iso"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(set(data["results"]), set(["repository", "boot.iso"]))

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(
            c.results, COMPOSE_RESULTS["boot.iso"] | COMPOSE_RESULTS["repository"]
        )

    def test_submit_build_with_koji_event(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "tag",
                            "source": "f26",
                            "packages": ["ed"],
                            "koji_event": 123456,
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["koji_event"], 123456)

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.koji_event, 123456)

    def test_submit_build_sigkeys(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "tag",
                            "source": "f26",
                            "packages": ["ed"],
                            "sigkeys": ["123", "456"],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["sigkeys"], "123 456")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    @patch.object(odcs.server.config.Config, "sigkeys", new_callable=PropertyMock)
    def test_submit_build_default_sigkeys(self, sigkeys):
        with self.test_request_context(user="dev"):
            sigkeys.return_value = ["x", "y"]
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "tag", "source": "f26", "packages": ["ed"]}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["sigkeys"], "x y")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_arches(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "arches": ["ppc64", "s390"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["arches"], "ppc64 s390")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_multilib_arches(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "arches": ["ppc64", "s390"],
                        "multilib_arches": ["x86_64", "ppc64le"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["multilib_arches"], "x86_64 ppc64le")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_multilib_method(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "arches": ["ppc64", "s390"],
                        "multilib_method": ["runtime", "devel"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["multilib_method"],
            MULTILIB_METHODS["runtime"] | MULTILIB_METHODS["devel"],
        )

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_multilib_method_unknown(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26", "packages": ["ed"]},
                        "arches": ["ppc64", "s390"],
                        "multilib_method": ["foo", "devel"],
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["message"], 'Unknown multilib method "foo"')

    def test_submit_build_modular_koji_tags(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "tag",
                            "source": "f26",
                            "modular_koji_tags": ["f26-modules"],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["modular_koji_tags"], "f26-modules")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_target_dir_unknown(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "tag", "source": "f26"}, "target_dir": "foo"}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(data["error"], "Bad Request")
        self.assertEqual(data["message"], 'Unknown "target_dir" "foo"')

    @patch.object(
        odcs.server.config.Config,
        "extra_target_dirs",
        new={"releng-private": "/tmp/private"},
    )
    def test_submit_build_target_not_allowed(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26"},
                        "target_dir": "releng-private",
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 403)
        self.assertEqual(data["error"], "Forbidden")
        self.assertEqual(
            data["message"],
            "User dev not allowed to operate with compose with target_dirs=releng-private.",
        )

    @patch.object(
        odcs.server.config.Config,
        "extra_target_dirs",
        new={"releng-private": "/tmp/private"},
    )
    def test_submit_build_target_dir(self):
        with self.test_request_context(user="dev3"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "tag", "source": "f26"},
                        "target_dir": "releng-private",
                    }
                ),
            )
            self.assertEqual(rv.status, "200 OK")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["target_dir"], "releng-private")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.target_dir, "/tmp/private")

    def test_submit_build_module_defaults_url(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "tag",
                            "source": "f26",
                            "module_defaults_url": "git://localhost.tld/x.git",
                            "module_defaults_commit": "master",
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["module_defaults_url"], "git://localhost.tld/x.git master"
        )

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_module_defaults_url_no_branch(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "tag",
                            "source": "f26",
                            "module_defaults_url": "git://localhost.tld/x.git",
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(data["status"], 400)
            self.assertEqual(data["error"], "Bad Request")
            self.assertEqual(
                data["message"],
                'The "module_defaults_url" and "module_defaults_commit" '
                "must be used together.",
            )

    def test_submit_build_duplicate_sources(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "foo:x foo:x foo:y"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["source"].count("foo:x"), 1)
        self.assertEqual(data["source"].count("foo:y"), 1)

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_submit_build_extra_builds(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "tag",
                            "source": "f26",
                            "packages": ["ed"],
                            "builds": ["foo-1-1", "bar-1-1"],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["builds"], "foo-1-1 bar-1-1")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.builds, "foo-1-1 bar-1-1")

    def test_submit_build_source_type_build(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "build",
                            "packages": ["ed"],
                            "builds": ["foo-1-1", "bar-1-1"],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["builds"], "foo-1-1 bar-1-1")

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.source_type, PungiSourceType.BUILD)
        self.assertEqual(c.builds, "foo-1-1 bar-1-1")

    def test_submit_build_resurrection_removed(self):
        self.c1.state = COMPOSE_STATES["removed"]
        self.c1.reused_id = 1
        db.session.commit()

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch("/api/1/composes/1")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["id"], 3)
        self.assertEqual(data["state_name"], "wait")
        self.assertEqual(data["source"], "testmodule:master")
        self.assertEqual(data["time_removed"], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_build_resurrection_not_allowed_raw_config_key(self):
        self.c1.state = COMPOSE_STATES["removed"]
        self.c1.reused_id = 1
        self.c1.source_type = 5
        self.c1.source = "pungi_cfg#hash"
        db.session.commit()

        with self.test_request_context(user="dev4"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch("/api/1/composes/1")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "User dev4 not allowed to operate with compose with raw_config_keys=pungi_cfg.",
        )

    def test_submit_build_resurrection_allowed_raw_config_key(self):
        self.c1.state = COMPOSE_STATES["removed"]
        self.c1.reused_id = 1
        self.c1.source_type = 5
        self.c1.source = "pungi_cfg2#hash"
        db.session.commit()

        with self.test_request_context(user="dev4"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch("/api/1/composes/1")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["id"], 3)
        self.assertEqual(data["state_name"], "wait")

    def test_submit_build_resurrection_failed(self):
        self.c1.state = COMPOSE_STATES["failed"]
        self.c1.reused_id = 1
        db.session.commit()

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch("/api/1/composes/1")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["id"], 3)
        self.assertEqual(data["state_name"], "wait")
        self.assertEqual(data["source"], "testmodule:master")
        self.assertEqual(data["time_removed"], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_build_resurrection_no_removed(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch("/api/1/composes/1")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["message"], "No compose with id 1 found")

    def test_submit_build_resurrection_not_found(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch("/api/1/composes/100")
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["message"], "No compose with id 100 found")

    def test_submit_build_resurrection_removed_new_sigkeys(self):
        self.c1.state = COMPOSE_STATES["removed"]
        self.c1.reused_id = 1
        db.session.commit()

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch(
                "/api/1/composes/1", data=json.dumps({"sigkeys": ["123", "456"]})
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["id"], 3)
        self.assertEqual(data["state_name"], "wait")
        self.assertEqual(data["source"], "testmodule:master")
        self.assertEqual(data["sigkeys"], "123 456")
        self.assertEqual(data["time_removed"], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_build_resurrection_done_new_sigkeys(self):
        self.c1.state = COMPOSE_STATES["done"]
        self.c1.reused_id = 1
        self.c1.sigkeys = "012 345"
        db.session.commit()

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch(
                "/api/1/composes/1", data=json.dumps({"sigkeys": ["123", "456"]})
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["id"], 3)
        self.assertEqual(data["state_name"], "wait")
        self.assertEqual(data["source"], "testmodule:master")
        self.assertEqual(data["sigkeys"], "123 456")
        self.assertEqual(data["time_removed"], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)

    def test_submit_respin(self):
        self.c1.state = COMPOSE_STATES["done"]
        self.c1.reused_id = 1
        self.c1.koji_event = 123
        self.c1.pungi_config_dump = "some data"
        self.c1.pungi_compose_id = "Fedora-1-1"
        db.session.commit()

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            req = {
                "source": {
                    "modules": ["foo:stream:1:1", "bar:stream:1:1"],
                    "builds": ["foo-1-1", "bar-1-1"],
                    "unknown_arg": "should be ignored",
                }
            }

            rv = self.client.patch("/api/1/composes/1", data=json.dumps(req))
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["id"], 3)
        self.assertEqual(data["state_name"], "wait")
        self.assertEqual(data["modules"], "foo:stream:1:1 bar:stream:1:1")
        self.assertEqual(data["builds"], "foo-1-1 bar-1-1")
        self.assertEqual(data["respin_of"], "Fedora-1-1")
        self.assertEqual(data["koji_event"], 123)
        self.assertEqual(data["time_removed"], None)

        c = db.session.query(Compose).filter(Compose.id == 3).one()
        self.assertEqual(c.reused_id, None)
        self.assertEqual(c.pungi_config_dump, "some data")

    def test_submit_build_not_allowed_source_type(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps({"source": {"type": "repo", "source": "/path"}}),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "User dev not allowed to operate with compose with source_types=repo.",
        )

    @patch.object(
        odcs.server.config.Config,
        "raw_config_urls",
        new={"pungi_cfg": "http://localhost/pungi.conf#%s"},
    )
    def test_submit_build_not_allowed_compose_type(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "raw_config", "source": "pungi_cfg#hash"},
                        "compose_type": "production",
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "User dev2 not allowed to operate with compose with compose_types=production.",
        )

    @patch.object(
        odcs.server.config.Config,
        "raw_config_urls",
        new={"pungi_cfg": "http://localhost/pungi.conf#%s"},
    )
    def test_submit_build_not_allowed_raw_config_key(self):
        with self.test_request_context(user="dev4"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "raw_config", "source": "pungi_cfg#hash"},
                        "compose_type": "production",
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "User dev4 not allowed to operate with compose with raw_config_keys=pungi_cfg.",
        )

    @patch.object(
        odcs.server.config.Config,
        "raw_config_urls",
        new={"pungi_cfg2": "http://localhost/pungi.conf#%s"},
    )
    def test_submit_build_allowed_raw_config_key(self):
        with self.test_request_context(user="dev4"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "raw_config", "source": "pungi_cfg2#hash"},
                        "compose_type": "production",
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["source"], "pungi_cfg2#hash")

    def test_submit_build_unknown_source_type(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps({"source": {"type": "unknown", "source": "/path"}}),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["message"], 'Unknown source type "unknown"')

    def test_submit_module_build_wrong_source(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master x"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            'Module definition must be in "n:s", "n:s:v" or '
            '"n:s:v:c" format, but got x',
        )

    def test_submit_module_build_base_module_in_source(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "module",
                            "source": "testmodule:master platform:x",
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "ODCS currently cannot create compose with base "
            "modules, but platform was requested.",
        )

    def test_submit_build_per_user_source_type_allowed(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["state_name"], "wait")

    def test_submit_build_per_user_source_type_not_allowed(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "tag", "source": "/path", "packages": ["foo"]}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "User dev2 not allowed to operate with compose with source_types=tag.",
        )

    def test_submit_build_per_group_source_type_allowed(self):
        with self.test_request_context(user="unknown", groups=["dev2", "x"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["state_name"], "wait")

    def test_submit_build_per_group_source_type_not_allowed(self):
        with self.test_request_context(user="unknown", groups=["dev2", "x"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "tag", "source": "/path", "packages": ["foo"]}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            data["message"],
            "User unknown not allowed to operate with compose with source_types=tag.",
        )

    def test_submit_scratch_build_tasks(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "module",
                            "source": "testmodule:master",
                            "scratch_build_tasks": [
                                "123456",
                                "123457",
                            ],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(
                data["scratch_build_tasks"],
                "123456 123457",
            )

    def test_submit_build_scratch_modules(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "module",
                            "source": "testmodule:master",
                            "scratch_modules": [
                                "foo:bar:20200806:abcdefgh",
                                "fooo:bar:20200810:abcdefgh",
                            ],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(
                data["source"],
                "testmodule:master",
            )
            self.assertEqual(
                data["scratch_modules"],
                "foo:bar:20200806:abcdefgh fooo:bar:20200810:abcdefgh",
            )

    def test_submit_build_modules(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "module",
                            "source": "testmodule:master",
                            "modules": [
                                "foo:bar:20200806:abcdefgh",
                                "fooo:bar:20200810:abcdefgh",
                            ],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(
                data["source"],
                "testmodule:master",
            )
            self.assertEqual(
                data["modules"],
                "foo:bar:20200806:abcdefgh fooo:bar:20200810:abcdefgh",
            )

    def test_submit_build_only_scratch_modules(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "module",
                            "source": "",
                            "scratch_modules": [
                                "foo:bar:20200806:abcdefgh",
                                "fooo:bar:20200810:abcdefgh",
                            ],
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(data["source"], "")
            self.assertEqual(
                data["scratch_modules"],
                "foo:bar:20200806:abcdefgh fooo:bar:20200810:abcdefgh",
            )

    def test_submit_build_parent_pungi_compose_ids(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "parent_pungi_compose_ids": ["Fedora-1-1", "Fedora-2-2"],
                        "source": {"type": "module", "source": "testmodule:master"},
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(
                data["parent_pungi_compose_ids"],
                "Fedora-1-1 Fedora-2-2",
            )

    def test_submit_build_respin_of(self):
        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "respin_of": "Fedora-1-1",
                        "source": {"type": "module", "source": "testmodule:master"},
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))
            self.assertEqual(
                data["respin_of"],
                "Fedora-1-1",
            )

    def test_query_compose(self):
        resp = self.client.get("/api/1/composes/1")
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["id"], 1)
        self.assertEqual(data["source"], "testmodule:master")
        self.assertEqual(data["pungi_config_dump"], None)
        self.assertEqual(resp.headers["Access-Control-Allow-Origin"], "*")

    def test_query_composes(self):
        resp = self.client.get("/api/1/composes/")
        evs = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual(len(evs), 2)

    def test_query_compose_owner(self):
        resp = self.client.get("/api/1/composes/?owner=me")
        evs = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["source"], "f26")
        self.assertTrue("pungi_config_dump" not in evs[0])

    def test_query_compose_state_done(self):
        resp = self.client.get("/api/1/composes/?state=%d" % COMPOSE_STATES["done"])
        evs = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual(len(evs), 0)

    def test_query_compose_state_wait(self):
        resp = self.client.get("/api/1/composes/?state=%d" % COMPOSE_STATES["wait"])
        evs = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual(len(evs), 2)

    def test_query_compose_source_type(self):
        resp = self.client.get(
            "/api/1/composes/?source_type=%d" % PungiSourceType.MODULE
        )
        evs = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual(len(evs), 1)

    def test_query_compose_source(self):
        resp = self.client.get("/api/1/composes/?source=f26")
        evs = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual(len(evs), 1)

    def test_query_composes_order_by_default(self):
        resp = self.client.get("/api/1/composes/")
        composes = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual([2, 1], [compose["id"] for compose in composes])

    def test_query_composes_order_by_id_asc(self):
        resp = self.client.get("/api/1/composes/?order_by=id")
        composes = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual([1, 2], [compose["id"] for compose in composes])

    def test_query_composes_order_by_id_desc(self):
        resp = self.client.get("/api/1/composes/?order_by=-id")
        composes = json.loads(resp.get_data(as_text=True))["items"]
        self.assertEqual([2, 1], [compose["id"] for compose in composes])

    def test_query_composes_order_by_id_unknown_key(self):
        resp = self.client.get("/api/1/composes/?order_by=foo")
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["status"], 400)
        self.assertEqual(data["error"], "Bad Request")
        self.assertTrue(
            data["message"].startswith(
                "An invalid order_by key was suplied, allowed keys are"
            )
        )

    def test_delete_compose(self):
        with freeze_time(self.initial_datetime) as frozen_datetime:
            c3 = Compose.create(
                db.session,
                "unknown",
                PungiSourceType.MODULE,
                "testmodule:master",
                COMPOSE_RESULTS["repository"],
                60,
            )
            c3.state = COMPOSE_STATES["done"]
            db.session.add(c3)
            db.session.commit()

            self.assertEqual(len(Compose.composes_to_expire()), 0)

            with self.test_request_context(user="root"):
                flask.g.oidc_scopes = [
                    "{0}{1}".format(conf.oidc_base_namespace, "delete-compose")
                ]

                resp = self.client.delete("/api/1/composes/%s" % c3.id)
                data = json.loads(resp.get_data(as_text=True))

            self.assertEqual(resp.status, "202 ACCEPTED")

            self.assertEqual(data["status"], 202)
            self.assertEqual(
                data["message"],
                "The delete request for compose (id=%s) has been accepted and will be processed by backend later."
                % c3.id,
            )

            self.assertEqual(c3.time_to_expire, self.initial_datetime)

            frozen_datetime.tick()
            self.assertEqual(len(Compose.composes_to_expire()), 1)
            expired_compose = Compose.composes_to_expire().pop()
            self.assertEqual(expired_compose.id, c3.id)
            self.assertEqual(expired_compose.removed_by, "root")

    def test_delete_not_allowed_states_compose(self):
        for state in COMPOSE_STATES.keys():
            if state not in ["wait", "done", "failed"]:
                new_c = Compose.create(
                    db.session,
                    "unknown",
                    PungiSourceType.MODULE,
                    "testmodule:master",
                    COMPOSE_RESULTS["repository"],
                    60,
                )
                new_c.state = COMPOSE_STATES[state]
                db.session.add(new_c)
                db.session.commit()
                compose_id = new_c.id

                with self.test_request_context(user="root"):
                    flask.g.oidc_scopes = [
                        "{0}{1}".format(conf.oidc_base_namespace, "delete-compose")
                    ]

                    resp = self.client.delete("/api/1/composes/%s" % compose_id)
                    data = json.loads(resp.get_data(as_text=True))

                self.assertEqual(resp.status, "400 BAD REQUEST")
                self.assertEqual(data["status"], 400)
                six.assertRegex(
                    self,
                    data["message"],
                    r"Compose \(id=%s\) can not be removed, its state need to be in .*."
                    % new_c.id,
                )
                self.assertEqual(data["error"], "Bad Request")

    def test_delete_non_exist_compose(self):
        with self.test_request_context(user="root"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "delete-compose")
            ]

            resp = self.client.delete("/api/1/composes/999999")
            data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(resp.status, "404 NOT FOUND")
        self.assertEqual(data["status"], 404)
        self.assertEqual(data["message"], "No such compose found.")
        self.assertEqual(data["error"], "Not Found")

    def test_delete_compose_with_non_admin_user(self):
        self.c1.state = COMPOSE_STATES["failed"]
        db.session.commit()

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "delete-compose")
            ]

            resp = self.client.delete("/api/1/composes/%s" % self.c1.id)
            data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(resp.status, "403 FORBIDDEN")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data["status"], 403)
        self.assertEqual(data["message"], "User dev is not in role admins.")

    def test_can_not_create_compose_with_non_composer_user(self):
        with self.test_request_context(user="qa"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            resp = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master"}}
                ),
            )
            data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(resp.status, "403 FORBIDDEN")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data["status"], 403)
        self.assertEqual(data["message"], "User qa is not in role allowed_clients.")

    def test_can_create_compose_with_user_in_configured_groups(self):
        with self.test_request_context(user="another_user", groups=["composer"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            resp = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:rawhide"}}
                ),
            )
        db.session.expire_all()

        self.assertEqual(resp.status, "200 OK")
        self.assertEqual(resp.status_code, 200)
        c = (
            db.session.query(Compose)
            .filter(Compose.source == "testmodule:rawhide")
            .one()
        )
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_can_create_compose_with_user_in_multiple_groups(self):
        with self.test_request_context(user="another_user", groups=["dev3", "dev2"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            resp = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:rawhide"}}
                ),
            )
        db.session.expire_all()

        self.assertEqual(resp.status, "200 OK")
        self.assertEqual(resp.status_code, 200)
        c = (
            db.session.query(Compose)
            .filter(Compose.source == "testmodule:rawhide")
            .one()
        )
        self.assertEqual(c.state, COMPOSE_STATES["wait"])

    def test_cannot_create_compose_with_user_in_multiple_groups(self):
        with self.test_request_context(user="another_user", groups=["dev3", "dev2"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            resp = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "tag", "source": "testmodule:rawhide"}}
                ),
            )
            data = json.loads(resp.get_data(as_text=True))
        db.session.expire_all()

        self.assertEqual(resp.status, "403 FORBIDDEN")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            data["message"],
            "User another_user not allowed to operate with compose with source_types=tag.",
        )

    def test_can_delete_compose_with_user_in_configured_groups(self):
        c3 = Compose.create(
            db.session,
            "unknown",
            PungiSourceType.MODULE,
            "testmodule:testbranch",
            COMPOSE_RESULTS["repository"],
            60,
        )
        c3.state = COMPOSE_STATES["done"]
        db.session.add(c3)
        db.session.commit()

        with self.test_request_context(user="another_admin", groups=["admin"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "delete-compose")
            ]

            resp = self.client.delete("/api/1/composes/%s" % c3.id)
            data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(resp.status, "202 ACCEPTED")
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(data["status"], 202)
        six.assertRegex(
            self,
            data["message"],
            r"The delete request for compose \(id=%s\) has been accepted and will be processed by backend later."
            % c3.id,
        )

    def test_can_create_compose_with_permission_overriden_by_username(self):
        with self.test_request_context(user="dev3", groups=["dev2"]):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            resp = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:rawhide"}}
                ),
            )
        db.session.expire_all()

        self.assertEqual(resp.status, "403 FORBIDDEN")
        self.assertEqual(resp.status_code, 403)

    @patch.object(
        odcs.server.config.Config, "max_seconds_to_live", new_callable=PropertyMock
    )
    @patch.object(
        odcs.server.config.Config, "seconds_to_live", new_callable=PropertyMock
    )
    def test_use_seconds_to_live_in_request(
        self, mock_seconds_to_live, mock_max_seconds_to_live
    ):
        # Test that seconds-to-live is still supported to keep backward compatibility.
        for seconds_to_live in ["seconds-to-live", "seconds_to_live"]:
            # if we have 'seconds_to_live' in request < conf.max_seconds_to_live
            # the value from request will be used
            mock_seconds_to_live.return_value = 60 * 60 * 24
            mock_max_seconds_to_live.return_value = 60 * 60 * 24 * 3

            with self.test_request_context(user="dev"):
                flask.g.oidc_scopes = [
                    "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
                ]

                rv = self.client.post(
                    "/api/1/composes/",
                    data=json.dumps(
                        {
                            "source": {"type": "module", "source": "testmodule:master"},
                            "seconds_to_live": 60 * 60 * 12,
                        }
                    ),
                )
                data = json.loads(rv.get_data(as_text=True))

            time_submitted = datetime.strptime(
                data["time_submitted"], "%Y-%m-%dT%H:%M:%SZ"
            )
            time_to_expire = datetime.strptime(
                data["time_to_expire"], "%Y-%m-%dT%H:%M:%SZ"
            )
            delta = timedelta(hours=12)
            self.assertEqual(time_to_expire - time_submitted, delta)

    @patch.object(
        odcs.server.config.Config, "max_seconds_to_live", new_callable=PropertyMock
    )
    @patch.object(
        odcs.server.config.Config, "seconds_to_live", new_callable=PropertyMock
    )
    def test_use_max_seconds_to_live_in_conf(
        self, mock_seconds_to_live, mock_max_seconds_to_live
    ):
        # if we have 'seconds_to_live' in request > conf.max_seconds_to_live
        # conf.max_seconds_to_live will be used
        mock_seconds_to_live.return_value = 60 * 60 * 24
        mock_max_seconds_to_live.return_value = 60 * 60 * 24 * 3

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "module", "source": "testmodule:master"},
                        "seconds_to_live": 60 * 60 * 24 * 7,
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        time_submitted = datetime.strptime(data["time_submitted"], "%Y-%m-%dT%H:%M:%SZ")
        time_to_expire = datetime.strptime(data["time_to_expire"], "%Y-%m-%dT%H:%M:%SZ")
        delta = timedelta(days=3)
        self.assertEqual(time_to_expire - time_submitted, delta)

    @patch.object(
        odcs.server.config.Config, "max_seconds_to_live", new_callable=PropertyMock
    )
    @patch.object(
        odcs.server.config.Config, "seconds_to_live", new_callable=PropertyMock
    )
    def test_use_seconds_to_live_in_conf(
        self, mock_seconds_to_live, mock_max_seconds_to_live
    ):
        # if we don't have 'seconds_to_live' in request, conf.seconds_to_live will be used
        mock_seconds_to_live.return_value = 60 * 60 * 24
        mock_max_seconds_to_live.return_value = 60 * 60 * 24 * 3

        with self.test_request_context(user="dev"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        time_submitted = datetime.strptime(data["time_submitted"], "%Y-%m-%dT%H:%M:%SZ")
        time_to_expire = datetime.strptime(data["time_to_expire"], "%Y-%m-%dT%H:%M:%SZ")
        delta = timedelta(hours=24)
        self.assertEqual(time_to_expire - time_submitted, delta)

    @patch.object(odcs.server.config.Config, "auth_backend", new_callable=PropertyMock)
    def test_anonymous_user_can_submit_build_with_noauth_backend(
        self, mock_auth_backend
    ):
        mock_auth_backend.return_value = "noauth"

        with self.test_request_context():
            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "module", "source": "testmodule:master"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        expected_json = {
            "source_type": 2,
            "state": 0,
            "time_done": None,
            "state_name": "wait",
            "state_reason": None,
            "source": u"testmodule:master",
            "owner": u"unknown",
            "result_repo": "http://localhost/odcs/odcs-%d/compose/Temporary"
            % data["id"],
            "result_repofile": "http://localhost/odcs/odcs-%d/compose/Temporary/odcs-%d.repo"
            % (data["id"], data["id"]),
            "time_submitted": data["time_submitted"],
            "id": data["id"],
            "time_started": None,
            "time_removed": None,
            "removed_by": None,
            "time_to_expire": data["time_to_expire"],
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
            "lookaside_repos": "",
            "modular_koji_tags": None,
            "module_defaults_url": None,
            "label": None,
            "compose_type": "test",
            "pungi_compose_id": None,
            "target_dir": "default",
            "scratch_modules": None,
            "modules": None,
            "toplevel_url": "http://localhost/odcs/odcs-%d" % data["id"],
            "parent_pungi_compose_ids": None,
            "scratch_build_tasks": None,
            "respin_of": None,
            "base_module_br_name": None,
            "base_module_br_stream": None,
            "base_module_br_stream_version_lte": None,
            "base_module_br_stream_version_gte": None,
        }
        self.assertEqual(data, expected_json)

        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])


class TestExtendExpiration(ViewBaseTest):
    """Test view post to extend expiration"""

    def setUp(self):
        super(TestExtendExpiration, self).setUp()
        self.oidc_base_namespace = patch.object(
            conf, "oidc_base_namespace", new="http://example.com/"
        )
        self.oidc_base_namespace.start()

    def tearDown(self):
        self.oidc_base_namespace.stop()
        super(TestExtendExpiration, self).tearDown()

    def setup_test_data(self):
        self.initial_datetime = datetime(
            year=2016, month=1, day=1, hour=0, minute=0, second=0
        )
        with freeze_time(self.initial_datetime):
            self.c1 = Compose.create(
                db.session,
                "me",
                PungiSourceType.KOJI_TAG,
                "f25",
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
            )
            self.c3 = Compose.create(
                db.session,
                "me",
                PungiSourceType.KOJI_TAG,
                "f27",
                COMPOSE_RESULTS["repository"],
                60,
            )
            self.c4 = Compose.create(
                db.session,
                "me",
                PungiSourceType.KOJI_TAG,
                "master",
                COMPOSE_RESULTS["repository"],
                60,
            )

            map(db.session.add, (self.c1, self.c2, self.c3, self.c4))
            db.session.commit()

            self.c1.reused_id = self.c2.id
            self.c2.reused_id = self.c3.id
            db.session.commit()

            # Store for retrieving them back for assertion
            self.c1_id = self.c1.id
            self.c3_id = self.c3.id

    @patch.object(conf, "auth_backend", new="noauth")
    def test_bad_request_if_seconds_to_live_is_invalid(self):
        post_data = json.dumps({"seconds_to_live": "600s"})
        with self.test_request_context():
            rv = self.client.patch(
                "/api/1/composes/{0}".format(self.c1.id), data=post_data
            )
            data = json.loads(rv.get_data(as_text=True))

            self.assertEqual(400, data["status"])
            self.assertEqual("Bad Request", data["error"])
            self.assertIn("seconds_to_live should be an integer", data["message"])

    @patch.object(conf, "auth_backend", new="noauth")
    def test_bad_request_if_request_data_is_not_json(self):
        with self.test_request_context():
            rv = self.client.patch("/api/1/composes/{0}".format(self.c1.id), data="abc")
            data = json.loads(rv.get_data(as_text=True))

            self.assertEqual(400, data["status"])
            self.assertEqual("Bad Request", data["error"])
            self.assertIn("Failed to decode JSON object", data["message"])

    @patch.object(conf, "oidc_base_namespace", new="http://example.com/")
    def test_fail_if_extend_non_existing_compose(self):
        post_data = json.dumps({"seconds_to_live": 600})
        with self.test_request_context():
            flask.g.oidc_scopes = [
                "http://example.com/new-compose",
                "http://example.com/renew-compose",
            ]

            rv = self.client.patch("/api/1/composes/999", data=post_data)
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual("No compose with id 999 found", data["message"])

    def test_fail_if_compose_is_not_done(self):
        self.c1.state = COMPOSE_STATES["wait"]
        db.session.commit()

        post_data = json.dumps({"seconds_to_live": 600})
        with self.test_request_context():
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]

            rv = self.client.patch(
                "/api/1/composes/{0}".format(self.c1.id), data=post_data
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            "No compose with id {0} found".format(self.c1.id), data["message"]
        )

    def test_extend_compose_expiration(self):
        fake_utcnow = datetime.utcnow()

        self.c2.state = COMPOSE_STATES["done"]
        self.c2.time_to_expire = fake_utcnow - timedelta(seconds=10)
        db.session.commit()

        expected_seconds_to_live = 60 * 60 * 3
        expected_time_to_expire = fake_utcnow + timedelta(
            seconds=expected_seconds_to_live
        )
        post_data = json.dumps({"seconds_to_live": expected_seconds_to_live})

        with self.test_request_context():
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "renew-compose")
            ]
            with freeze_time(fake_utcnow):
                url = "/api/1/composes/{0}".format(self.c2.id)
                rv = self.client.patch(url, data=post_data)
                data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(
            Compose._utc_datetime_to_iso(expected_time_to_expire),
            data["time_to_expire"],
        )

        # Compose reusing self.c2 and the one self.c2 reuses should also be
        # extended.
        c1 = db.session.query(Compose).filter(Compose.id == self.c1_id).first()
        self.assertEqual(expected_time_to_expire, c1.time_to_expire)
        c3 = db.session.query(Compose).filter(Compose.id == self.c3_id).first()
        self.assertEqual(expected_time_to_expire, c3.time_to_expire)


class TestViewsRawConfig(ViewBaseTest):
    maxDiff = None

    def setUp(self):
        super(TestViewsRawConfig, self).setUp()
        self.oidc_base_namespace = patch.object(
            conf, "oidc_base_namespace", new="http://example.com/"
        )
        self.oidc_base_namespace.start()

    def tearDown(self):
        super(TestViewsRawConfig, self).tearDown()
        self.oidc_base_namespace.stop()

    def test_submit_build_raw_config_too_many_sources(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {
                            "type": "raw_config",
                            "source": "pungi_cfg#hash pungi2cfg_hash",
                        }
                    }
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(
            data["message"],
            'Only single source is allowed for "raw_config" source_type',
        )

    def test_submit_build_raw_config_no_hash(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "raw_config", "source": "pungi_cfg"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(
            data["message"],
            'Source must be in "source_name#commit_hash" format for '
            '"raw_config" source_type.',
        )

    def test_submit_build_raw_config_empty_hash(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "raw_config", "source": "pungi_cfg#"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(
            data["message"],
            'Source must be in "source_name#commit_hash" format for '
            '"raw_config" source_type.',
        )

    def test_submit_build_raw_config_empty_name(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps({"source": {"type": "raw_config", "source": "#hash"}}),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(
            data["message"],
            'Source must be in "source_name#commit_hash" format for '
            '"raw_config" source_type.',
        )

    def test_submit_build_raw_config_empty_name_hash(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps({"source": {"type": "raw_config", "source": "#"}}),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(
            data["message"],
            'Source must be in "source_name#commit_hash" format for '
            '"raw_config" source_type.',
        )

    def test_submit_build_raw_config_unknown_name(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            rv = self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {"source": {"type": "raw_config", "source": "pungi_cfg#hash"}}
                ),
            )
            data = json.loads(rv.get_data(as_text=True))

        self.assertEqual(data["status"], 400)
        self.assertEqual(
            data["message"],
            'Source "pungi_cfg" does not exist in server configuration.',
        )

    @patch.object(
        odcs.server.config.Config,
        "raw_config_urls",
        new={"pungi_cfg": "http://localhost/pungi.conf#%s"},
    )
    def test_submit_build_raw_config(self):
        with self.test_request_context(user="dev2"):
            flask.g.oidc_scopes = [
                "{0}{1}".format(conf.oidc_base_namespace, "new-compose")
            ]

            self.client.post(
                "/api/1/composes/",
                data=json.dumps(
                    {
                        "source": {"type": "raw_config", "source": "pungi_cfg#hash"},
                        "label": "Beta-1.2",
                        "compose_type": "nightly",
                    }
                ),
            )
        db.session.expire_all()
        c = db.session.query(Compose).filter(Compose.id == 1).one()
        self.assertEqual(c.state, COMPOSE_STATES["wait"])
        self.assertEqual(c.source_type, PungiSourceType.RAW_CONFIG)
        self.assertEqual(c.source, "pungi_cfg#hash")
        self.assertEqual(c.label, "Beta-1.2")
        self.assertEqual(c.compose_type, "nightly")
        self.assertEqual(c.json()["result_repofile"], "")


class TestViewsCancelCompose(ViewBaseTest):
    maxDiff = None

    def setup_test_data(self):
        self.initial_datetime = datetime(
            year=2016, month=1, day=1, hour=0, minute=0, second=0
        )
        with freeze_time(self.initial_datetime):
            self.c1 = Compose.create(
                db.session,
                "dev2",
                PungiSourceType.MODULE,
                "testmodule:master",
                COMPOSE_RESULTS["repository"],
                60,
            )
            db.session.commit()
            self.task_id = "71267f28-5194-4720-b57b-a665fabdb012"
            self.c1.celery_task_id = self.task_id
            db.session.commit()
            self.c1_id = self.c1.id

    @patch("odcs.server.views.CELERY_AVAILABLE", new=False)
    def test_no_celery(self):
        with self.test_request_context(user="dev2"):
            resp = self.client.delete("/api/1/composes/%s" % self.c1.id)
        # Without celery we can't cancel, so the code should try to delete the
        # compose and fail on user not being an admin.
        self.assertEqual(resp.status_code, 403)
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["status"], 403)
        self.assertEqual(data["message"], "User dev2 is not in role admins.")

    def test_bad_owner(self):
        with self.test_request_context(user="dev1"):
            resp = self.client.delete("/api/1/composes/%s" % self.c1.id)
        self.assertEqual(resp.status_code, 403)
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["status"], 403)
        self.assertEqual(
            data["message"],
            "Compose (id=%s) can not be canceled, it's owned by someone else.",
        )

    @patch("odcs.server.views.celery_app")
    def test_cancel(self, app):
        with self.test_request_context(user="dev2"):
            resp = self.client.delete("/api/1/composes/%s" % self.c1_id)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(app.mock_calls, [call.control.revoke(self.task_id)])
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["status"], 202)
        self.assertEqual(
            data["message"], "Compose (id=%s) has been canceled" % self.c1_id
        )
        c1 = db.session.query(Compose).filter(Compose.id == self.c1_id).first()
        self.assertEqual(c1.state, COMPOSE_STATES["failed"])
        self.assertEqual(c1.state_reason, "Canceled by dev2")
