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

from mock import patch

from odcs.server import db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_RESULTS
from odcs.server.pungi import PungiSourceType
from odcs.server.metrics import ComposesCollector, QueueLengthThread, WorkerCountThread
from .utils import ModelsBaseTest


class TestComposesCollector(ModelsBaseTest):
    def setUp(self):
        super(TestComposesCollector, self).setUp()
        self.collector = ComposesCollector()

    def test_composes_total(self):
        Compose.create(
            db.session,
            "unknown",
            PungiSourceType.MODULE,
            "testmodule:master",
            COMPOSE_RESULTS["repository"],
            60,
        )
        Compose.create(
            db.session,
            "me",
            PungiSourceType.KOJI_TAG,
            "f26",
            COMPOSE_RESULTS["repository"],
            60,
        )
        db.session.commit()

        r = self.collector.composes_total()
        for sample in r.samples:
            if (
                sample.labels["source_type"] in ["module", "tag"]
                and sample.labels["state"] == "wait"
            ):
                self.assertEqual(sample.value, 1)
            else:
                self.assertEqual(sample.value, 0)

    def test_raw_config_composes_count(self):
        for i in range(15):
            Compose.create(
                db.session,
                "unknown",
                PungiSourceType.RAW_CONFIG,
                "foo#bar",
                COMPOSE_RESULTS["repository"],
                60,
            )
        for i in range(10):
            Compose.create(
                db.session,
                "me",
                PungiSourceType.RAW_CONFIG,
                "foo#hash%d" % i,
                COMPOSE_RESULTS["repository"],
                60,
            )
        db.session.commit()
        r = self.collector.raw_config_composes_count()
        for sample in r.samples:
            if sample.labels["source"] == "foo#bar":
                self.assertEqual(sample.value, 15)
            elif sample.labels["source"] == "foo#other_commits_or_branches":
                self.assertEqual(sample.value, 10)


class TestQueueLengthThread(ModelsBaseTest):
    @patch("odcs.server.metrics.celery_app")
    def test_update_metrics(self, celery_app):
        conn = celery_app.connection_or_acquire.return_value
        queue_declare = conn.default_channel.queue_declare
        queue_declare.return_value.message_count = 10

        thread = QueueLengthThread()
        thread.update_metrics()
        metrics = thread.queue_length.collect()
        for metric in metrics:
            queues = set()
            for sample in metric.samples:
                queues.add(sample.labels["queue_name"])
                self.assertEqual(sample.value, 10)
            self.assertEqual(
                queues, set(["cleanup", "pungi_composes", "pulp_composes"])
            )


class TestWorkerCountThread(ModelsBaseTest):
    @patch("odcs.server.metrics.celery_app")
    def test_update_metrics(self, celery_app):
        celery_app.control.ping.side_effect = [
            [
                {"worker-1@localhost": {"ok": "pong"}},
                {"worker-2@localhost": {"ok": "pong"}},
            ],
            [{"worker-1@localhost": {"ok": "pong"}}],
        ]

        # Both workers online.
        thread = WorkerCountThread()
        thread.update_metrics()
        metrics = thread.workers_total.collect()
        self.assertEqual(metrics[0].samples[0].value, 2)
        metrics = thread.workers.collect()
        for metric in metrics:
            for sample in metric.samples:
                self.assertEqual(sample.value, 1)

        # The worker-2 went offline.
        thread.update_metrics()
        metrics = thread.workers_total.collect()
        self.assertEqual(metrics[0].samples[0].value, 1)
        metrics = thread.workers.collect()
        for metric in metrics:
            for sample in metric.samples:
                if sample.labels["worker_name"] == "worker-1@localhost":
                    self.assertEqual(sample.value, 1)
                else:
                    self.assertEqual(sample.value, 0)
