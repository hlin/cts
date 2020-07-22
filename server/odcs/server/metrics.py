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

import time
import threading
from sqlalchemy import func
from prometheus_client import CollectorRegistry, Gauge
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from odcs.common.types import COMPOSE_STATES, PUNGI_SOURCE_TYPE_NAMES
from odcs.server.models import Compose
from odcs.server import log, conf, app

try:
    from odcs.server.celery_tasks import celery_app
    from celery.utils.objects import FallbackContext
    import amqp.exceptions

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False


registry = CollectorRegistry()


class ComposesCollector(object):
    def composes_total(self):
        """
        Returns `composes_total` GaugeMetricFamily with number of composes
        for each state and source_type.
        """
        counter = GaugeMetricFamily(
            "composes_total",
            "Total number of composes",
            labels=["source_type", "state"],
        )
        for state in COMPOSE_STATES:
            for source_type in PUNGI_SOURCE_TYPE_NAMES:
                count = Compose.query.filter(
                    Compose.source_type == PUNGI_SOURCE_TYPE_NAMES[source_type],
                    Compose.state == COMPOSE_STATES[state],
                ).count()

                counter.add_metric([source_type, state], count)
        return counter

    def raw_config_composes_count(self):
        """
        Returns `raw_config_composes_count` CounterMetricFamily with number of raw_config
        composes for each `Compose.source`. For raw_config composes, the Compose.source is
        stored in the `raw_config_key#commit_or_branch` format. If particular `Compose.source` is
        generated only few times (less than 5), it is grouped by the `raw_config_key` and
        particular `commit_or_branch` is replaced with "other_commits_or_branches" string.

        This is needed to handle the situation when particular raw_config compose is generated
        just once using particular commit hash (and not a branch name). These single composes
        are not that important in the metrics and therefore we group them like that.
        """
        counter = CounterMetricFamily(
            "raw_config_composes_count",
            "Total number of raw_config composes per source",
            labels=["source"],
        )
        composes = (
            Compose.query.with_entities(Compose.source, func.count(Compose.source))
            .filter(Compose.source_type == PUNGI_SOURCE_TYPE_NAMES["raw_config"])
            .group_by(Compose.source)
            .all()
        )

        sources = {}
        for source, count in composes:
            if count < 5:
                name = "%s#other_commits_or_branches" % source.split("#")[0]
                if name not in sources:
                    sources[name] = 0
                sources[name] += count
            else:
                sources[source] = count

        for source, count in sources.items():
            counter.add_metric([source], count)

        return counter

    def collect(self):
        yield self.composes_total()
        yield self.raw_config_composes_count()


class WorkerCountThread(threading.Thread):
    """
    Thread providing and updating following metrics:

    - celery_workers_totals - Number of alive workers.
    - celery_workers[worker_name] - 1 if worker is online, 0 if offline.
    """

    def __init__(self, registry=None):
        super(WorkerCountThread, self).__init__()
        self.daemon = True
        self.workers_total = Gauge(
            "celery_workers_totals", "Number of alive workers", registry=registry
        )
        self.workers_total.set(0)
        self.workers = Gauge(
            "celery_workers",
            "Number of alive workers",
            ["worker_name"],
            registry=registry,
        )
        self.worker_names = set()

    def update_metrics(self):
        log.info("[metrics] Getting number of workers.")
        try:
            celery_ping = celery_app.control.ping(timeout=15)
        except Exception:  # pragma: no cover
            log.exception("[metrics] Error pinging workers.")
            return

        # Set total number of workers.
        self.workers_total.set(len(celery_ping))

        # Set all known workers to 0 to mark them offline.
        for workers in celery_ping:
            self.worker_names |= set(workers.keys())
        for worker_name in self.worker_names:
            self.workers.labels(worker_name).set(0)

        # Set online workers to 1.
        for workers in celery_ping:
            for worker_name in workers.keys():
                self.workers.labels(worker_name).set(1)

    def run(self):
        while True:
            self.update_metrics()
            time.sleep(30)


class QueueLengthThread(threading.Thread):
    """
    Thread providing and updating following metrics:

    - celery_queue_length[queue_name] - Number of tasks waiting in the queue.
    """

    def __init__(self, registry=None):
        super(QueueLengthThread, self).__init__()
        self.daemon = True
        self.queue_length = Gauge(
            "celery_queue_length",
            "Number of tasks in the queue.",
            ["queue_name"],
            registry=registry,
        )

        # Get all the possible queue names from the config.
        self.queues = [conf.celery_cleanup_queue]
        for rules in conf.celery_router_config["routing_rules"].values():
            self.queues += rules.keys()
        # Initialize the queue length to 0.
        for queue in self.queues:
            self.queue_length.labels(queue).set(0)

        # Get the Celery connetion.
        self.connection = celery_app.connection_or_acquire()
        if isinstance(self.connection, FallbackContext):
            self.connection = self.connection.fallback()

    def update_metrics(self):
        for queue in self.queues:
            try:
                log.info("[metrics] Getting %s queue length." % queue)
                length = self.connection.default_channel.queue_declare(
                    queue=queue, passive=True
                ).message_count
                self.queue_length.labels(queue).set(length)
            except amqp.exceptions.ChannelError:
                # Queue not created yet.
                pass
            except Exception:  # pragma: no cover
                log.exception("[metrics] Error getting queue length.")

    def run(self):
        while True:
            self.update_metrics()
            time.sleep(30)


registry.register(ComposesCollector())


# Start the Celery metrics only on Frontend using the `before_first_request` decorator.
@app.before_first_request
def start_celery_metrics():
    if CELERY_AVAILABLE:
        # These threads are "daemonic". This means they are stopped automatically
        # by Python when main Python thread is stopped. There is no need to .join()
        # and since they are only updating metrics, they do not have to end up
        # gracefully and can just be "killed" by Python.
        worker_count_thread = WorkerCountThread(registry=registry)
        worker_count_thread.start()
        queue_length_thread = QueueLengthThread(registry=registry)
        queue_length_thread.start()
