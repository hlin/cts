# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
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

import ssl
import os
import re
from celery import Celery
from six.moves.urllib.parse import urlparse
from datetime import datetime, timedelta

from odcs.server import conf, db, log
from odcs.server.backend import (
    generate_compose as backend_generate_compose,
    ComposerThread,
    RemoveExpiredComposesThread,
)
from odcs.server.utils import retry
from odcs.server.models import Compose, COMPOSE_STATES
from odcs.server.pungi import PungiSourceType


# Prepare the instances of classes with worker methods.
composer_thread = ComposerThread()
remove_expired_compose_thread = RemoveExpiredComposesThread()


# Create the Celery app.
if os.environ.get("ODCS_CELERY_BROKER_URL"):
    broker_url = os.environ["ODCS_CELERY_BROKER_URL"]
elif conf.celery_broker_url:
    broker_url = conf.celery_broker_url
else:
    broker_url = "amqp://localhost"

# Although the Celery handles amqps using Kombu Python module,
# it does not do that correctly.
#
# When using "amqps://" protocol, Kombu uses SSLTransport which effectively
# sets the `amqp.Connection.ssl = True`. This enables SSL, but it does it
# in a way when we cannot set any other SSL options like client cert/key
# or for example SNI hostname which needs to be used.
#
# This is done in this commit:
# In the https://github.com/celery/kombu/commit/701672c2ba732883869a42f061a10dbfc8fe2f30
#
# To workaround this, we detect "amqps" here and sets the `broker_use_ssl`. This
# allows us to set any SSL options like client cert/key or SNI header.
# The `broker_use_ssl` is directly passed to `amqp.Connection.ssl` which handles
# it.
#
# In the end, we change the `broker_url` protocol from "amqps" to "amqp", so
# the Celery wont' override the `amps.Connection.ssl` with `True`.
if broker_url.startswith("amqps://"):
    netloc = urlparse(broker_url).netloc
    host_port = netloc.split("@")[-1]
    host = host_port.split(":")[0]

    ssl_ctx = {}

    # Set the server_hostname only if it's configured in the CELERY_CONFIG,
    # otherwise Celery uses SNI everytime even if we don't need it.
    if "server_hostname" in conf.celery_config:
        broker_use_ssl = {
            "server_hostname": host,
            "context": {"purpose": ssl.Purpose.SERVER_AUTH},
        }
    else:
        broker_use_ssl = {}

    # Allow setting certificates using the CELERY_CONFIG.
    for key in ["ca_certs", "keyfile", "certfile"]:
        if key in conf.celery_config:
            broker_use_ssl[key] = conf.celery_config[key]

    conf.celery_config.update({"broker_use_ssl": broker_use_ssl})
    broker_url = broker_url.replace("amqps://", "amqp://")

celery_app = Celery("backend", broker=broker_url)
celery_app.conf.update(conf.celery_config)
celery_app.conf.update({"task_routes": ("odcs.server.celery_tasks.TaskRouter")})


class TaskRouter:
    """ Custom Celery router """

    def __init__(self):
        self.config = conf.celery_router_config

    def route_for_task(self, task_name, *args, **kwargs):
        """
        Method which celery expects to be defined on a custom router. Returns the payload
        with the queue selected for task
        """
        if task_name == self.config["cleanup_task"]:
            return {"queue": conf.celery_cleanup_queue}

        compose_id = args[0][0]
        compose = get_odcs_compose(compose_id)
        compose_md = compose.json()

        queue = self.__get_queue_for_compose(compose_md, task_name)

        return {"queue": queue}

    def __get_queue_for_compose(self, compose_md, task_name):
        """ Goes through routing rules configured for a task returns a queue on the first match. """
        rules = {}
        if self.config["routing_rules"].get(task_name):
            rules.update(self.config["routing_rules"][task_name])

        for queue, rule in rules.items():
            # if the rule has no properties its an automatic match.
            if rule:
                for key, value in rule.items():
                    if not compose_md.get(key):
                        raise ValueError(
                            (
                                "Task Router: Routing rule for queue %s for task %s contains an "
                                "invalid property: %s"
                            )
                            % (queue, task_name, key)
                        )

                    # if the value of the property from the rule and compose does not match, the
                    # whole rule is ignored and we go to the next rule
                    if isinstance(value, (tuple, list)):
                        values = value
                    else:
                        values = [value]

                    if not any(re.match(str(v), str(compose_md[key])) for v in values):
                        break
                else:
                    # if all of the properties and values match then the whole rule match
                    return queue
            else:
                # if the rule is emtpy its an wildcard and an automatic match
                return queue

        # if none of the rules applies the default queue is returned
        return self.config["default_queue"]


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Add the cleanup task every 10 minutes. This can be hardcoded here.
    # It is just internal task to clean up the expired composes, mark
    # stuck composes as failed and so on.
    # This task also expires in 1 hour. This prevents situation when all backends
    # are broken for long time (hours/days) and queue of run_cleanup tasks grow
    # up and once backends come online, they are flooded with run_cleanup tasks.
    sender.add_periodic_task(10 * 60, run_cleanup.s(), expires=3600)


@retry(wait_on=RuntimeError)
def get_odcs_compose(compose_id):
    """
    Gets the compose from ODCS DB.
    """
    compose = Compose.query.filter(Compose.id == compose_id).first()
    if not compose:
        raise RuntimeError("No compose with id %d in ODCS DB." % compose_id)
    return compose


def generate_compose(compose_id):
    """
    Generates the compose with id `compose_id`.
    """
    compose = get_odcs_compose(compose_id)
    if compose.state != COMPOSE_STATES["wait"]:
        raise RuntimeError(
            "The 'generate_compose' called for compose not in 'wait' state: %r"
            % compose
        )
    compose.transition(COMPOSE_STATES["generating"], "Compose thread started")
    db.session.commit()
    backend_generate_compose(compose.id)


@celery_app.task
def generate_pungi_compose(compose_id):
    """
    Generates the Pungi based compose.
    """
    generate_compose(compose_id)


@celery_app.task
def generate_pulp_compose(compose_id):
    """
    Generates the Pungi based compose.
    """
    generate_compose(compose_id)


def get_current_celery_task_ids():
    """
    Returns a set with currently registered task IDs.
    """
    inspection = celery_app.control.inspect()

    # Active tasks are currently running tasks.
    active = []
    act_obj = inspection.active()
    if act_obj is not None:
        for i in act_obj.values():
            active += i
    active = [i["id"] for i in active]

    # Reserved tasks are assigned to particular worker, but
    # are not running yet.
    reserved = []
    res_obj = inspection.reserved()
    if res_obj is not None:
        for i in res_obj.values():
            reserved += i
    reserved = [i["id"] for i in reserved]

    return set(reserved + active)


def schedule_compose(compose):
    """
    Schedules the compose task and sets the `compose.celery_task_id`.
    Returns the updated `compose`.
    """
    if compose.source_type == PungiSourceType.PULP:
        result = generate_pulp_compose.delay(compose.id)
    else:
        result = generate_pungi_compose.delay(compose.id)
    compose.celery_task_id = result.id
    db.session.add(compose)
    db.session.commit()
    return compose


def reschedule_waiting_composes():
    """
    Gets all the composes stuck in the "wait" state and reschedules them.

    This method exists to pro-actively generate "wait" composes in case
    the Celery message from frontend to backend is lost from whatever reason.
    """
    # Composes transition from 'wait' to 'generating' quite fast.
    # The frontend changes the state of compose to 'wait', sends a message
    # to the bus and once some backend receives it, it moves it to
    # 'generating'. This should not take more than 3 minutes, so that's
    # the limit we will use to find out the stuck composes.
    # On the other hand, we don't want to regenerate composes older than
    # 3 days, because nobody is probably waiting for them. Just mark
    # them as "failed".
    now = datetime.utcnow()
    from_time = now - timedelta(days=3)
    to_time = now - timedelta(minutes=3)

    # Get composes which are in 'wait' state for too long.
    composes = (
        Compose.query.filter(
            Compose.state == COMPOSE_STATES["wait"], Compose.time_submitted < to_time
        )
        .order_by(Compose.id)
        .all()
    )

    # Get the current task ids registered by the workers.
    task_ids = get_current_celery_task_ids()

    for compose in composes:
        # Check if the task is already planned.
        if compose.celery_task_id in task_ids:
            continue

        if compose.time_submitted < from_time:
            compose.transition(
                COMPOSE_STATES["failed"],
                "Compose stuck in 'wait' state for longer than 3 days.",
            )
            continue

        log.info("%r: Rescheduling compose stuck in 'wait' state.", compose)
        schedule_compose(compose)


@celery_app.task
def run_cleanup():
    """
    Runs the cleanup.
    """
    remove_expired_compose_thread.do_work()
    composer_thread.fail_lost_generating_composes()
    reschedule_waiting_composes()
