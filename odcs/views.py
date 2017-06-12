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

import json
from datetime import datetime

from flask.views import MethodView
from flask import request, jsonify

from odcs import app, db, log, conf
from odcs.models import Compose, COMPOSE_RESULTS, COMPOSE_STATES
from odcs.pungi import PungiSourceType, Pungi, PungiConfig

from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(conf.num_concurrent_pungi)

api_v1 = {
    'composes': {
        'url': '/odcs/1/composes/',
        'options': {
            'defaults': {'id': None},
            'methods': ['GET'],
        }
    },
    'composes_post': {
        'url': '/odcs/1/composes/',
        'options': {
            'methods': ['POST'],
        }
    },
}


def generate_compose(compose_id):
    compose = None
    with app.app_context():
        try:
            compose = Compose.query.filter(Compose.id == compose_id).one()
            log.info("%r: Starting compose generation", compose)

            pungi_cfg = PungiConfig(compose.owner, "1", compose.source_type,
                                    compose.source, packages=compose.packages.split(" "))
            pungi = Pungi(pungi_cfg)
            pungi.run()

            log.info("%r: Compose done", compose)

            compose.state = COMPOSE_STATES["done"]
            compose.time_done = datetime.utcnow()
            db.session.add(compose)
            db.session.commit()
        except:
            if compose:
                log.exception("%r: Error while generating compose", compose)
            else:
                log.exception("Error while generating compose %d", compose_id)
            compose.state = COMPOSE_STATES["failed"]
            compose.time_done = datetime.utcnow()
            db.session.add(compose)
            db.session.commit()


class ODCSAPI(MethodView):
    def get(self, id):
        return "Done", 200

    def post(self):
        owner = "Unknown"  # TODO

        try:
            data = json.loads(request.get_data().decode("utf-8"))
        except Exception:
            log.exception('Invalid JSON submitted')
            raise ValueError('Invalid JSON submitted')

        needed_keys = ["source_type", "source"]
        for key in needed_keys:
            if key not in data:
                err = "Missing %s" % key
                log.error(err)
                raise ValueError(err)

        source_type = data["source_type"]
        if source_type == "module":
            source_type = PungiSourceType.MODULE
        elif source_type == "tag":
            source_type = PungiSourceType.KOJI_TAG
        elif source_type == "repo":
            source_type = PungiSourceType.REPO
        else:
            err = "Unknown source_type %s" % source_type
            log.error(err)
            raise ValueError(err)

        source = data["source"].split(" ")
        if not source:
            err = "No source data provided"
            log.error(err)
            raise ValueError(err)
        source = ' '.join(filter(None, source))

        seconds_to_live = conf.seconds_to_live
        if "seconds-to-live" in data:
            seconds_to_live = max(int(seconds_to_live),
                                  conf.max_seconds_to_live)

        packages = None
        if "packages" in data:
            packages = data["packages"]

        compose = Compose.create(
            db.session, owner, source_type, source,
            COMPOSE_RESULTS["repository"], seconds_to_live,
            ' '.join(packages))
        db.session.add(compose)
        db.session.commit()

        executor.submit(generate_compose, compose.id)

        return jsonify(compose.json()), 200


def register_api_v1():
    """ Registers version 1 of MBS API. """
    module_view = ODCSAPI.as_view('composes')
    for key, val in api_v1.items():
        app.add_url_rule(val['url'],
                         endpoint=key,
                         view_func=module_view,
                         **val['options'])


register_api_v1()
