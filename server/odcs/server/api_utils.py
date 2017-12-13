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

import copy
from flask import request, url_for
from odcs.server.models import Compose
import six


def validate_json_data(dict_or_list, level=0):
    """
    Checks that json data represented by dict `dict_or_list` is valid ODCS
    input. Raises ValueError in case the json data does not pass validation.

    This mainly checks that any value in json data does not contain forbidden
    characters and data types which could potentially lead to dangerous pungi
    configuration being generated.
    """
    if isinstance(dict_or_list, dict):
        iterator = dict_or_list.items()
    else:
        iterator = enumerate(dict_or_list)
    for k, v in iterator:
        if isinstance(v, dict):
            # Allow only dict with "source" key name in first level of
            # json object.
            if level != 0 or k not in ["source"]:
                raise ValueError(
                    "Only 'source' key is allowed to contain dict.")
            validate_json_data(v, level + 1)
        elif isinstance(v, list):
            validate_json_data(v, level + 1)
        elif isinstance(v, six.string_types):
            allowed_chars = [' ', '-', '/', '_', '.', ':', '#']
            if not all(c.isalnum() or c in allowed_chars for c in v):
                raise ValueError(
                    "Only alphanumerical characters and %r characters "
                    "are allowed in ODCS input variables" % (allowed_chars))
        elif isinstance(v, (int, float)):
            # Allow int, float and also bool, because that's subclass of int.
            continue
        else:
            raise ValueError(
                "Only dict, list, str, unicode, int, float and bool types "
                "are allowed in ODCS input variables, but '%s' has '%s' "
                "type" % (k, type(v)))


def pagination_metadata(p_query, request_args):
    """
    Returns a dictionary containing metadata about the paginated query.
    This must be run as part of a Flask request.
    :param p_query: flask_sqlalchemy.Pagination object
    :param request_args: a dictionary of the arguments that were part of the
    Flask request
    :return: a dictionary containing metadata about the paginated query
    """

    request_args_wo_page = dict(copy.deepcopy(request_args))
    # Remove pagination related args because those are handled elsewhere
    # Also, remove any args that url_for accepts in case the user entered
    # those in
    for key in ['page', 'per_page', 'endpoint']:
        if key in request_args_wo_page:
            request_args_wo_page.pop(key)
    for key in request_args:
        if key.startswith('_'):
            request_args_wo_page.pop(key)
    pagination_data = {
        'page': p_query.page,
        'pages': p_query.pages,
        'per_page': p_query.per_page,
        'prev': None,
        'next': None,
        'total': p_query.total,
        'first': url_for(request.endpoint, page=1, per_page=p_query.per_page,
                         _external=True, **request_args_wo_page),
        'last': url_for(request.endpoint, page=p_query.pages,
                        per_page=p_query.per_page, _external=True,
                        **request_args_wo_page)
    }

    if p_query.has_prev:
        pagination_data['prev'] = url_for(request.endpoint, page=p_query.prev_num,
                                          per_page=p_query.per_page, _external=True,
                                          **request_args_wo_page)

    if p_query.has_next:
        pagination_data['next'] = url_for(request.endpoint, page=p_query.next_num,
                                          per_page=p_query.per_page, _external=True,
                                          **request_args_wo_page)

    return pagination_data


def filter_composes(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()

    for key in ['owner', 'source_type', 'source', 'state', 'koji_task_id']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = Compose.query

    if search_query:
        query = query.filter_by(**search_query)

    page = flask_request.args.get('page', 1, type=int)
    per_page = flask_request.args.get('per_page', 10, type=int)
    return query.paginate(page, per_page, False)
