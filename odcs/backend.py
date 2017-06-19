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

import os
import threading
import shutil
from datetime import datetime
from odcs import log, conf, app, db
from odcs.models import Compose, COMPOSE_STATES, COMPOSE_FLAGS
from odcs.pungi import Pungi, PungiConfig
from concurrent.futures import ThreadPoolExecutor


class BackendThread(object):
    """
    Base BackendThread class.

    The `BackendThread.do_work(...)` is called repeatedly after `timeout`
    seconds.
    """
    def __init__(self, timeout=1):
        """
        Creates new BackendThread instance.

        :param int timeout: Timeout in seconds after which do_work is called.
        """
        self.thread = None
        self.exit = False
        self.exit_cond = threading.Condition()
        self.timeout = timeout

    def do_work(self):
        """
        Reimplement this method in your own BackendThread subclass.
        This method is called every `timeout` seconds.
        """
        raise NotImplemented("do_work() method not implemented")

    def _run(self):
        """
        Main "run" method of a thread. Calls `do_work()` after `self.timeout`
        seconds. Stops then `stop()` is called.
        """
        while not self.exit:
            try:
                self.do_work()
            except:
                log.exception("Exception in backend thread")
            self.exit_cond.acquire()
            self.exit_cond.wait(float(self.timeout))
            self.exit_cond.release()

    def join(self):
        """
        Waits until the thread terminates.
        """
        self.thread.join()

    def stop(self):
        """
        Stops the thread.
        """
        self.exit = True
        self.exit_cond.acquire()
        self.exit_cond.notify()
        self.exit_cond.release()

    def start(self):
        """
        Starts the thread.
        """
        self.thread = threading.Thread(target=self._run)
        self.thread.setDaemon(True)
        self.thread.start()


class ExpireThread(BackendThread):
    """
    Thread used to remove old expired composes.
    """
    def __init__(self):
        """
        Creates new ExpireThread instance.
        """
        super(ExpireThread, self).__init__(10)

    def _remove_compose_dir(self, toplevel_dir):
        """
        Removes the compose toplevel_dir symlink together with the real
        path it points to.
        """
        if os.path.realpath(toplevel_dir) != toplevel_dir:
            targetpath = os.path.realpath(toplevel_dir)
            os.unlink(toplevel_dir)
            shutil.rmtree(targetpath)

    def do_work(self):
        """
        Checks for the expired composes and removes them.
        """
        log.info("Checking for expired composes")

        composes = Compose.composes_to_expire()
        for compose in composes:
            log.info("%r: Removing compose", compose)
            compose.state = COMPOSE_STATES["removed"]
            compose.time_removed = datetime.utcnow()
            db.session.commit()
            if os.path.exists(compose.toplevel_dir):
                self._remove_compose_dir(compose.toplevel_dir)


def generate_compose(compose_id):
    """
    Generates the compose defined by its `compose_id`. It is run by
    ThreadPoolExecutor from the ComposerThread.
    """
    compose = None
    with app.app_context():
        try:
            # Get the compose from database.
            compose = Compose.query.filter(Compose.id == compose_id).one()
            log.info("%r: Starting compose generation", compose)

            # Reformat the data from database
            packages = compose.packages
            if packages:
                packages = packages.split(" ")

            # Generate PungiConfig and run Pungi
            pungi_cfg = PungiConfig(compose.name, "1", compose.source_type,
                                    compose.source, packages=packages)
            if compose.flags & COMPOSE_FLAGS["no_deps"]:
                pungi_cfg.gather_method = "nodeps"

            pungi = Pungi(pungi_cfg)
            pungi.run()

            # If there is no exception generated by the pungi.run(), we know
            # the compose has been successfully generated.
            log.info("%r: Compose done", compose)
            compose.state = COMPOSE_STATES["done"]
            compose.time_done = datetime.utcnow()
            db.session.add(compose)
            db.session.commit()
        except:
            # Something went wrong, log the exception and update the compose
            # state in database.
            if compose:
                log.exception("%r: Error while generating compose", compose)
            else:
                log.exception("Error while generating compose %d", compose_id)
            compose.state = COMPOSE_STATES["failed"]
            compose.time_done = datetime.utcnow()
            db.session.add(compose)
            db.session.commit()


class ComposerThread(BackendThread):
    """
    Thread used to query the database for composes in "wait" state and
    generating the composes using Pungi.
    """
    def __init__(self):
        """
        Creates new ComposerThread instance.
        """
        super(ComposerThread, self).__init__(1)
        self.executor = ThreadPoolExecutor(conf.num_concurrent_pungi)

    def do_work(self):
        """
        Gets all the composes in "wait" state. Generates them using Pungi
        by calling `generate_compose(...)` in ThreadPoolExecutor.
        """
        composes = Compose.query.filter(
            Compose.state == COMPOSE_STATES["wait"]).all()

        for compose in composes:
            log.info("%r: Going to start compose generation.", compose)
            compose.state = COMPOSE_STATES["generating"]
            db.session.add(compose)
            db.session.commit()
            self.executor.submit(generate_compose, compose.id)


def run_backend():
    """
    Runs the backend.
    """
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
