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
import six
import flask
from flask import request, url_for, Response
from functools import wraps
from odcs.server.models import Compose
from odcs.server import conf
from odcs.server.errors import Forbidden
from odcs.common.types import (
    COMPOSE_RESULTS,
    COMPOSE_FLAGS,
    INVERSE_PUNGI_SOURCE_TYPE_NAMES,
)


def _set_default_client_allowed_attrs(ret_attrs, attrs):
    """
    Helper method adding default allowed_client_attrs into `ret_attrs`.

    If some requested attributes from `attrs` are missing in `ret_attrs` list,
    try to get them from "conf.allowed_$attr_name". If they are not there
    too, use empty list to disallow everything.
    """
    for attr in attrs:
        if attr not in ret_attrs:
            # If raw_config_keys is not set, it means all the `raw_config_urls` keys
            # are allowed for this client.
            if attr == "raw_config_keys":
                ret_attrs[attr] = conf.raw_config_urls.keys()
            else:
                ret_attrs[attr] = getattr(conf, "allowed_%s" % attr, [])
    return ret_attrs


def _load_allowed_clients_attr(attrs):
    """
    Loads attributes from the conf.allowed_clients dict based on the logged
    in user and its groups. If the requested attribute is not found in
    the loaded dict, the conf.allowed_$attr_name is used as a default.

    :param list attrs: List of attribute names to load from the dict.
    :return: Generator of Dicts with loaded attributes.
    """
    # Check if logged user exists in "users" definition of allowed_clients.
    clients = conf.allowed_clients.get("users", {})
    if flask.g.user.username in clients:
        ret_attrs = dict(copy.deepcopy(clients[flask.g.user.username]))
        ret_attrs = _set_default_client_allowed_attrs(ret_attrs, attrs)
        yield ret_attrs
    else:
        # Check if group is defined in allowed_clients "groups".
        clients = conf.allowed_clients.get("groups", {})
        for group in flask.g.groups:
            if group in clients:
                ret_attrs = dict(copy.deepcopy(clients[group]))
                ret_attrs = _set_default_client_allowed_attrs(ret_attrs, attrs)
                yield ret_attrs


def _enum_int_to_str_list(enum_dict, val):
    """
    Convenient method converting int value to list of strings
    according to enum dict.

    For example for {"a": 1, "b": 2, "c": 4} and val=6, this method
    returns ["b", "c"].
    """
    tmp = []
    for enum_name, enum_val in enum_dict.items():
        if val & enum_val == enum_val:
            tmp.append(enum_name)
    return tmp


def raise_if_input_not_allowed(**kwargs):
    """
    Raises `Forbidden` exception if currently logged in user is not allowed
    to operate with a compose of given attributes passed as kwargs.

    Following attributes are valid:
      - flags - compose.flags int
      - results - copose.reults int
      - source_types - compose.source_type
      - sources - compose.source
      - arches - compose.arches
      - compose_types - compose.compose_type
      - raw_config_keys - compose.source.split("#")[0]

    The decision whether the user is allowed or not is done based on
    conf.allowed_clients value.
    """
    if conf.auth_backend == "noauth":
        return

    errors = set()
    for attrs in _load_allowed_clients_attr(kwargs.keys()):
        found_error = False
        for name, values in kwargs.items():
            if name not in attrs:
                # This should not happen, but be defensive in this part of code...
                errors.add(
                    "User %s not allowed to operate with compose with %s=%r."
                    % (flask.g.user.username, name, values)
                )
                continue

            # Convert integers from db format to string list.
            if name == "source_types":
                values = INVERSE_PUNGI_SOURCE_TYPE_NAMES[values]
            elif name == "flags":
                values = _enum_int_to_str_list(COMPOSE_FLAGS, values)
            elif name == "results":
                values = _enum_int_to_str_list(COMPOSE_RESULTS, values)
            elif name == "target_dirs":
                # The default conf.target_dir is always allowed.
                if values == conf.target_dir:
                    continue
                inverse_extra_target_dirs = {
                    v: k for k, v in conf.extra_target_dirs.items()
                }
                values = inverse_extra_target_dirs[values]

            if type(values) == int:
                values = [values]
            elif isinstance(values, six.string_types):
                # `arches` and `sources` are white-space separated lists.
                values = values.split(" ")
            elif values is None:
                # If value is not set, it means it is not available for this compose
                # type and we need to skip its check later. Set the values to empty
                # list to do that.
                values = []

            for value in values:
                allowed_values = attrs[name]
                if (
                    not allowed_values or value not in allowed_values
                ) and allowed_values != [""]:
                    errors.add(
                        "User %s not allowed to operate with compose with %s=%s."
                        % (flask.g.user.username, name, value)
                    )
                    found_error = True
                    break
        if not found_error:
            return
    if errors:
        raise Forbidden(" ".join(list(errors)))
    else:
        raise Forbidden(
            "User %s not allowed to operate with any compose." % flask.g.user.username
        )


def validate_json_data(dict_or_list, level=0, last_dict_key=None):
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
        list_expected = [
            "builds",
            "multilib_method",
            "packages",
            "scratch_build_tasks",
            "scratch_modules",
            "sigkeys",
            "modules",
        ]
        if k in list_expected and not isinstance(v, list):
            raise ValueError("%s should be a list" % k)

        str_expected = [
            "base_module_br_name",
            "base_module_br_stream",
            "compose_type",
            "label",
            "target_dir",
            "type",
        ]
        if k in str_expected and not isinstance(v, six.string_types):
            raise ValueError("%s should be a string" % k)

        int_expected = [
            "seconds_to_live",
            "koji_event",
            "base_module_br_stream_version_lte",
            "base_module_br_stream_version_gte",
        ]
        if k in int_expected and not isinstance(v, int):
            raise ValueError("%s should be an integer" % k)

        if isinstance(v, dict):
            # Allow only dict with "source" key name in first level of
            # json object.
            if level != 0 or k not in ["source"]:
                raise ValueError("Only 'source' key is allowed to contain dict.")
            validate_json_data(v, level + 1, k)
        elif isinstance(v, list):
            validate_json_data(v, level + 1, k)
        elif isinstance(v, six.string_types):
            # Packages are stored in comps.xml, not in pungi.conf, so it is
            # not exploitable.
            if last_dict_key in ["packages"]:
                continue
            allowed_chars = [" ", "-", "/", "_", ".", ":", "#", "+", "?", "$", "~"]
            if not all(c.isalnum() or c in allowed_chars for c in v):
                raise ValueError(
                    "Only alphanumerical characters and %r characters "
                    "are allowed in ODCS input variables" % (allowed_chars)
                )
        elif isinstance(v, (int, float)):
            # Allow int, float and also bool, because that's subclass of int.
            continue
        else:
            raise ValueError(
                "Only dict, list, str, unicode, int, float and bool types "
                "are allowed in ODCS input variables, but '%s' has '%s' "
                "type" % (k, type(v))
            )


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
    for key in ["page", "per_page", "endpoint"]:
        if key in request_args_wo_page:
            request_args_wo_page.pop(key)
    for key in request_args:
        if key.startswith("_"):
            request_args_wo_page.pop(key)
    pagination_data = {
        "page": p_query.page,
        "pages": p_query.pages,
        "per_page": p_query.per_page,
        "prev": None,
        "next": None,
        "total": p_query.total,
        "first": url_for(
            request.endpoint,
            page=1,
            per_page=p_query.per_page,
            _external=True,
            **request_args_wo_page
        ),
        "last": url_for(
            request.endpoint,
            page=p_query.pages,
            per_page=p_query.per_page,
            _external=True,
            **request_args_wo_page
        ),
    }

    if p_query.has_prev:
        pagination_data["prev"] = url_for(
            request.endpoint,
            page=p_query.prev_num,
            per_page=p_query.per_page,
            _external=True,
            **request_args_wo_page
        )

    if p_query.has_next:
        pagination_data["next"] = url_for(
            request.endpoint,
            page=p_query.next_num,
            per_page=p_query.per_page,
            _external=True,
            **request_args_wo_page
        )

    return pagination_data


def _order_by(flask_request, query, base_class, allowed_keys, default_key):
    """
    Parses the "order_by" argument from flask_request.args, checks that
    it is allowed for ordering in `allowed_keys` list and sets the ordering
    in the `query`.
    In case "order_by" is not set in flask_request.args, use `default_key`
    instead.

    If "order_by" argument starts with minus sign ('-'), the descending order
    is used.
    """
    order_by = flask_request.args.get("order_by", default_key, type=str)
    if order_by and len(order_by) > 1 and order_by[0] == "-":
        order_asc = False
        order_by = order_by[1:]
    else:
        order_asc = True

    if order_by not in allowed_keys:
        raise ValueError(
            "An invalid order_by key was suplied, allowed keys are: "
            "%r" % allowed_keys
        )

    order_by_attr = getattr(base_class, order_by)
    if not order_asc:
        order_by_attr = order_by_attr.desc()
    return query.order_by(order_by_attr)


def filter_composes(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()

    for key in [
        "owner",
        "source_type",
        "source",
        "state",
        "koji_task_id",
        "pungi_compose_id",
        "compose_type",
        "label",
    ]:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = Compose.query

    if search_query:
        query = query.filter_by(**search_query)

    query = _order_by(
        flask_request,
        query,
        Compose,
        [
            "id",
            "owner",
            "source_Type",
            "koji_event",
            "state",
            "time_to_expire",
            "time_submitted",
            "time_done",
            "time_removed",
        ],
        "-id",
    )

    page = flask_request.args.get("page", 1, type=int)
    per_page = flask_request.args.get("per_page", 10, type=int)
    return query.paginate(page, per_page, False)


def cors_header(allow="*"):
    """
    A decorator that sets the Access-Control-Allow-Origin header to
    the desired value on a Flask route.
    :param allow: a string of the domain to allow. This defaults to '*'.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            rv = func(*args, **kwargs)
            if rv:
                # If a tuple was provided, then the Flask Response should be the first object
                if isinstance(rv, tuple):
                    response = rv[0]
                else:
                    response = rv
                # Make sure we are dealing with a Flask Response object
                if isinstance(response, Response):
                    response.headers.add("Access-Control-Allow-Origin", allow)
            return rv

        return wrapper

    return decorator
