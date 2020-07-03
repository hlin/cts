from mock import patch, Mock, call
from datetime import datetime, timedelta

import pytest
from .utils import ModelsBaseTest

from odcs.server import conf, db
from odcs.server.celery_tasks import TaskRouter, reschedule_waiting_composes
from odcs.common.types import COMPOSE_STATES, COMPOSE_RESULTS
from odcs.server.pungi import PungiSourceType
from odcs.server.models import Compose


class TestCeleryRouter:
    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_empty_rule(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {"source_type": 3}

        mock_conf = {
            "routing_rules": {
                "odcs.server.celery_tasks.generate_pungi_compose": {
                    "pungi_composes": {},
                    "other_composes": {"source_type": 4},
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        queue = tr.route_for_task(
            "odcs.server.celery_tasks.generate_pungi_compose", *args, **kwargs
        )
        assert queue == {"queue": "pungi_composes"}

    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_default_queue(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {"source_type": 3}

        mock_conf = {
            "routing_rules": {
                "some.other.task": {
                    "pungi_composes": {},
                    "other_composes": {"source_type": 4},
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        queue = tr.route_for_task(
            "odcs.server.celery_tasks.generate_pungi_compose", *args, **kwargs
        )
        assert queue == {"queue": "default_queue"}

    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_rule_with_single_property(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {"source_type": 3}

        mock_conf = {
            "routing_rules": {
                "odcs.server.celery_tasks.generate_pungi_compose": {
                    "pungi_composes": {"source_type": 3},
                    "other_composes": {"source_type": 4},
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        queue = tr.route_for_task(
            "odcs.server.celery_tasks.generate_pungi_compose", *args, **kwargs
        )
        assert queue == {"queue": "pungi_composes"}

    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_rule_with_list_property(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {
            "source_type": 3,
            "user": "mprahl",
        }

        mock_conf = {
            "routing_rules": {
                "odcs.server.celery_tasks.generate_pungi_compose": {
                    "pungi_composes": {
                        "source_type": 3,
                        "user": ["mcurlej", "jkaluza"],
                    },
                    "other_composes": {
                        "source_type": 3,
                        "user": ["mprahl", "lucarval"],
                    },
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        queue = tr.route_for_task(
            "odcs.server.celery_tasks.generate_pungi_compose", *args, **kwargs
        )
        assert queue == {"queue": "other_composes"}

    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_cleanup_queue(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {"source_type": 3}

        mock_conf = {
            "routing_rules": {
                "odcs.server.celery_tasks.generate_pungi_compose": {
                    "pungi_composes": {"source_type": 3},
                    "other_composes": {"source_type": 4},
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        queue = tr.route_for_task(
            "odcs.server.celery_tasks.run_cleanup", *args, **kwargs
        )
        assert queue == {"queue": conf.celery_cleanup_queue}

    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_invalid_rule_property_exception(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {"source_type": 3}

        mock_conf = {
            "routing_rules": {
                "odcs.server.celery_tasks.generate_pungi_compose": {
                    "pungi_composes": {"bad_compose_prop": 3},
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        with pytest.raises(ValueError) as e:
            tr.route_for_task(
                "odcs.server.celery_tasks.generate_pungi_compose", *args, **kwargs
            )
            assert "invalid property" in e.args[0]
            assert "bad_compose_prop" in e.args[0]

    @patch("odcs.server.celery_tasks.get_odcs_compose")
    def test_rule_with_regexp(self, mock_get_compose):
        mock_compose = Mock()

        compose_md = {
            "source_type": 3,
            "source": "fedora30#commithash",
        }

        mock_conf = {
            "routing_rules": {
                "odcs.server.celery_tasks.generate_pungi_compose": {
                    "pungi_composes": {"source_type": 3, "source": "^fedora30#.*"},
                },
            },
            "cleanup_task": "odcs.server.celery_tasks.run_cleanup",
            "default_queue": "default_queue",
        }

        tr = TaskRouter()
        tr.config = mock_conf

        mock_compose.json.return_value = compose_md
        mock_get_compose.return_value = mock_compose
        args = [[1], {}]
        kwargs = {}
        queue = tr.route_for_task(
            "odcs.server.celery_tasks.generate_pungi_compose", *args, **kwargs
        )
        assert queue == {"queue": "pungi_composes"}


class TestRescheduleWaitingComposes(ModelsBaseTest):
    def _add_test_compose(
        self,
        state,
        time_submitted=None,
        time_started=None,
        source_type=PungiSourceType.KOJI_TAG,
    ):
        compose = Compose.create(
            db.session,
            "unknown",
            source_type,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
            "",
            0,
        )
        compose.state = state
        compose.celery_task_id = "1"
        if time_submitted:
            compose.time_submitted = time_submitted
        if time_started:
            compose.time_started = time_started
        db.session.add(compose)
        db.session.commit()
        return compose

    @patch("odcs.server.celery_tasks.get_current_celery_task_ids")
    @patch("odcs.server.celery_tasks.schedule_compose")
    def test_reschedule_waiting_composes_generating_state(
        self, schedule_compose, task_ids
    ):
        task_ids.return_value = set(["2"])
        time_submitted = datetime.utcnow() - timedelta(minutes=5)
        composes = []
        for i in range(10):
            composes.append(
                self._add_test_compose(
                    COMPOSE_STATES["wait"], time_submitted=time_submitted
                )
            )
        composes = sorted(composes, key=lambda c: c.id)
        reschedule_waiting_composes()
        schedule_compose.assert_has_calls(
            [call(composes[0]), call(composes[1]), call(composes[2]), call(composes[3])]
        )

    @patch("odcs.server.celery_tasks.get_current_celery_task_ids")
    @patch("odcs.server.celery_tasks.schedule_compose")
    def test_reschedule_waiting_composes_generating_state_not_old_enough(
        self, schedule_compose, task_ids
    ):
        task_ids.return_value = set(["2"])
        composes = []
        for i in range(10):
            composes.append(self._add_test_compose(COMPOSE_STATES["wait"]))
        composes = sorted(composes, key=lambda c: c.id)
        reschedule_waiting_composes()
        schedule_compose.assert_not_called()

    @patch("odcs.server.celery_tasks.get_current_celery_task_ids")
    @patch("odcs.server.celery_tasks.schedule_compose")
    def test_reschedule_waiting_composes_generating_state_old(
        self, schedule_compose, task_ids
    ):
        task_ids.return_value = set(["2"])
        time_submitted = datetime.utcnow() - timedelta(days=5)
        composes = []
        for i in range(10):
            composes.append(
                self._add_test_compose(
                    COMPOSE_STATES["wait"], time_submitted=time_submitted
                )
            )
        composes = sorted(composes, key=lambda c: c.id)
        reschedule_waiting_composes()
        schedule_compose.assert_not_called()

    @patch("odcs.server.celery_tasks.get_current_celery_task_ids")
    @patch("odcs.server.celery_tasks.schedule_compose")
    def test_generate_lost_composes_generating_state(self, schedule_compose, task_ids):
        task_ids.return_value = set(["2"])
        composes = []
        for i in range(10):
            composes.append(self._add_test_compose(COMPOSE_STATES["generating"]))
        composes = sorted(composes, key=lambda c: c.id)
        reschedule_waiting_composes()
        schedule_compose.assert_not_called()
