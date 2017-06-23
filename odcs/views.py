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

from flask.views import MethodView
from flask import request, jsonify

from odcs import app, db, log, conf
from odcs.errors import NotFound
from odcs.models import Compose, COMPOSE_RESULTS, COMPOSE_FLAGS, COMPOSE_STATES
from odcs.pungi import PungiSourceType
from odcs.api_utils import pagination_metadata, filter_composes


api_v1 = {
    'composes': {
        'url': '/odcs/1/composes/',
        'options': {
            'defaults': {'id': None},
            'methods': ['GET'],
        }
    },
    'compose': {
        'url': '/odcs/1/composes/<int:id>',
        'options': {
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


class ODCSAPI(MethodView):
    def get(self, id):
        if id is None:
            p_query = filter_composes(request)

            json_data = {
                'meta': pagination_metadata(p_query)
            }
            json_data['items'] = [item.json() for item in p_query.items]

            return jsonify(json_data), 200

        else:
            compose = Compose.query.filter_by(id=id).first()
            if compose:
                return jsonify(compose.json()), 200
            else:
                raise NotFound('No such compose found.')

    def post(self):
        owner = "Unknown"  # TODO

        try:
            data = json.loads(request.get_data().decode("utf-8"))
        except Exception:
            log.exception('Invalid JSON submitted')
            raise ValueError('Invalid JSON submitted')

        # If "id" is in data, it means client wants to regenerate an expired
        # compose.
        if "id" in data:
            old_compose = Compose.query.filter(
                Compose.id == data["id"],
                Compose.state.in_(
                    [COMPOSE_STATES["removed"],
                     COMPOSE_STATES["failed"]])).first()
            if not old_compose:
                err = "No expired or failed compose with id %s" % data["id"]
                log.error(err)
                raise ValueError(err)

            log.info("%r: Going to regenerate the compose", old_compose)

            seconds_to_live = conf.seconds_to_live
            if "seconds-to-live" in data:
                seconds_to_live = max(int(seconds_to_live),
                                      conf.max_seconds_to_live)

            compose = Compose.create_copy(db.session, old_compose, owner,
                                          seconds_to_live)
            db.session.add(compose)
            db.session.commit()
            return jsonify(compose.json()), 200

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
            packages = ' '.join(data["packages"])

        flags = 0
        if "flags" in data:
            for name in data["flags"]:
                if name not in COMPOSE_FLAGS:
                    raise ValueError("Unknown flag %s", name)
                flags |= COMPOSE_FLAGS[name]

        compose = Compose.create(
            db.session, owner, source_type, source,
            COMPOSE_RESULTS["repository"], seconds_to_live,
            packages, flags)
        db.session.add(compose)
        db.session.commit()

        return jsonify(compose.json()), 200


def register_api_v1():
    """ Registers version 1 of ODCS API. """
    module_view = ODCSAPI.as_view('composes')
    for key, val in api_v1.items():
        app.add_url_rule(val['url'],
                         endpoint=key,
                         view_func=module_view,
                         **val['options'])


register_api_v1()
