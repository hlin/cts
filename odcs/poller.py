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
import atexit
from datetime import datetime
from odcs import log
from odcs.models import Compose, COMPOSE_STATES

# thread handler
pollerThread = threading.Thread()


def create_poller(poll_seconds=5):
    def interrupt():
        global pollerThread
        pollerThread.cancel()

    def do_work():
        global pollerThread

        log.info("Checking for expired composes")

        composes = Compose.expired_composes()
        for compose in composes:
            log.info("%r: Removing compose")
            compose.state = COMPOSE_STATES["removed"]
            compose.time_removed = datetime.utcnow()
            # TODO: Remove compose data

        # Set the next thread to happen
        pollerThread = threading.Timer(poll_seconds, do_work, ())
        pollerThread.start()

    def start_worker():
        # Do initialisation stuff here
        global pollerThread
        # Create your thread
        pollerThread = threading.Timer(poll_seconds, do_work, ())
        pollerThread.start()

    # Initiate
    start_worker()
    # When Flask gets killed (SIGTERM), clear the trigger for the next thread
    atexit.register(interrupt)
