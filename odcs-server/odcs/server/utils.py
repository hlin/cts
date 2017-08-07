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

import errno
import functools
import os
import time
import subprocess

from odcs.server import conf, log


def retry(timeout=conf.net_timeout, interval=conf.net_retry_interval, wait_on=Exception, logger=None):
    """A decorator that allows to retry a section of code until success or timeout."""
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                if (time.time() - start) >= timeout:
                    raise  # This re-raises the last exception.
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    if logger is not None:
                        logger.warn("Exception %r raised from %r.  Retry in %rs",
                                    e, function, interval)
                    time.sleep(interval)
        return inner
    return wrapper


def makedirs(path, mode=0o775):
    try:
        os.makedirs(path, mode=mode)
    except OSError as ex:
        if ex.errno != errno.EEXIST:
            raise


def execute_cmd(args, stdout=None, stderr=None, cwd=None):
    """
    Executes command defined by `args`. If `stdout` or `stderr` is set to
    Python file object, the stderr/stdout output is redirecter to that file.
    If `cwd` is set, current working directory is set accordingly for the
    executed command.

    :param args: list defining the command to execute.
    :param stdout: Python file object to redirect the stdout to.
    :param stderr: Python file object to redirect the stderr to.
    :param cwd: string defining the current working directory for command.
    :raises RuntimeError: Raised when command exits with non-zero exit code.
    """
    out_log_msg = ""
    if stdout:
        out_log_msg += ", stdout log: %s" % stdout.name
    if stderr:
        out_log_msg += ", stderr log: %s" % stderr.name

    log.info("Executing command: %s%s" % (args, out_log_msg))
    proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, cwd=cwd)
    proc.communicate()

    if proc.returncode != 0:
        err_msg = "Command '%s' returned non-zero value %d%s" % (args, proc.returncode, out_log_msg)
        raise RuntimeError(err_msg)
