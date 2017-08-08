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

from logging import getLogger

from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

from odcs.server.logger import init_logging
from odcs.server.config import init_config
from odcs.server.proxy import ReverseProxy
from odcs.server.errors import NotFound

app = Flask(__name__)
app.wsgi_app = ReverseProxy(app.wsgi_app)

db = SQLAlchemy(app)

conf = init_config(app)
init_logging(conf)
log = getLogger(__name__)

login_manager = LoginManager()
login_manager.init_app(app)

from odcs.server import views # noqa

from odcs.server.auth import init_auth # noqa
init_auth(login_manager, conf.auth_backend)


def json_error(status, error, message):
    response = jsonify(
        {'status': status,
         'error': error,
         'message': message})
    response.status_code = status
    return response


@app.errorhandler(NotFound)
def notfound_error(e):
    """Flask error handler for NotFound exceptions"""
    return json_error(404, 'Not Found', e.args[0])


@app.errorhandler(ValueError)
def validationerror_error(e):
    """Flask error handler for ValueError exceptions"""
    return json_error(400, 'Bad Request', e.args[0])


@app.errorhandler(RuntimeError)
def runtimeerror_error(e):
    """Flask error handler for RuntimeError exceptions"""
    return json_error(500, 'Internal Server Error', e.args[0])
