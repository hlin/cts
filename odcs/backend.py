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

import threading
from datetime import datetime
from odcs import log, conf, app, db
from odcs.models import Compose, COMPOSE_STATES
from odcs.pungi import Pungi, PungiConfig
from concurrent.futures import ThreadPoolExecutor


class BackendThread(object):
    """
    Basic Worker class.
    """
    def __init__(self, timeout=1):
        """
        Creates new Worker instance.
        """
        self.thread = None
        self.exit = False
        self.exit_cond = threading.Condition()
        self.timeout = timeout

    def do_work(self):
        raise NotImplemented("do_work() method not implemented")

    def _run(self):
        while not self.exit:
            self.do_work()
            self.exit_cond.acquire()
            self.exit_cond.wait(float(self.timeout))
            self.exit_cond.release()

    def join(self):
        self.thread.join()

    def stop(self):
        self.exit = True
        self.exit_cond.acquire()
        self.exit_cond.notify()
        self.exit_cond.release()

    def start(self):
        self.thread = threading.Thread(target=self._run)
        self.thread.setDaemon(True)
        self.thread.start()


class ExpireThread(BackendThread):
    def __init__(self):
        super(ExpireThread, self).__init__(1)

    def do_work(self):
        log.info("Checking for expired composes")

        composes = Compose.expired_composes()
        for compose in composes:
            log.info("%r: Removing compose")
            compose.state = COMPOSE_STATES["removed"]
            compose.time_removed = datetime.utcnow()
            # TODO: Remove compose data


def generate_compose(compose_id):
    compose = None
    with app.app_context():
        try:
            compose = Compose.query.filter(Compose.id == compose_id).one()
            log.info("%r: Starting compose generation", compose)

            packages = compose.packages
            if packages:
                packages = packages.split(" ")

            pungi_cfg = PungiConfig(compose.owner, "1", compose.source_type,
                                    compose.source, packages=packages)
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


class ComposerThread(BackendThread):
    def __init__(self):
        super(ComposerThread, self).__init__(1)
        self.executor = ThreadPoolExecutor(conf.num_concurrent_pungi)

    def do_work(self):
        composes = Compose.query.filter(
            Compose.state == COMPOSE_STATES["wait"]).all()

        for compose in composes:
            log.info("%r: Going to start compose generation.", compose)
            compose.state = COMPOSE_STATES["generating"]
            db.session.add(compose)
            db.session.commit()
            self.executor.submit(generate_compose, compose.id)


def run_backend():
    while True:
        expire_thread = ExpireThread()
        composer_thread = ComposerThread()
        try:
            expire_thread.start()
            composer_thread.start()
            expire_thread.join()
            composer_thread.join()
        except KeyboardInterrupt:
            expire_thread.stop()
            composer_thread.stop()
            expire_thread.join()
            composer_thread.join()
            return 0
        except:
            log.exception("Exception in backend")
            expire_thread.stop()
            composer_thread.stop()
            expire_thread.join()
            composer_thread.join()

    return 0
