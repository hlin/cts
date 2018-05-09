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
import signal
import time
import subprocess
import requests
from distutils.spawn import find_executable
from threading import Timer

from odcs.server import conf, log


def download_file(url, output_path):
    """
    Downloads file from URL `url` to `output_path`.
    """
    r = requests.get(url)
    r.raise_for_status()

    with open(output_path, 'wb') as f:
        f.write(r.content)


def retry(timeout=conf.net_timeout, interval=conf.net_retry_interval, wait_on=Exception, logger=None):
    """A decorator that allows to retry a section of code until success or timeout."""
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    if logger is not None:
                        logger.warn("Exception %r raised from %r.  Retry in %rs",
                                    e, function, interval)
                    time.sleep(interval)
                if (time.time() - start) >= timeout:
                    raise  # This re-raises the last exception.
        return inner
    return wrapper


def makedirs(path, mode=0o775):
    try:
        os.makedirs(path, mode=mode)
    except OSError as ex:
        if ex.errno != errno.EEXIST:
            raise


def _kill_process_group(proc, args):
    log.error("Timeout occured while running: %s", args)
    pgrp = os.getpgid(proc.pid)
    os.killpg(pgrp, signal.SIGINT)


def execute_cmd(args, stdout=None, stderr=None, cwd=None, timeout=None):
    """
    Executes command defined by `args`. If `stdout` or `stderr` is set to
    Python file object, the stderr/stdout output is redirecter to that file.
    If `cwd` is set, current working directory is set accordingly for the
    executed command.

    :param args: list defining the command to execute.
    :param stdout: Python file object to redirect the stdout to.
    :param stderr: Python file object to redirect the stderr to.
    :param cwd: string defining the current working directory for command.
    :param timeout: Timeout in seconds after which the process and all its
        children are killed.
    :raises RuntimeError: Raised when command exits with non-zero exit code.
    """
    out_log_msg = ""
    if stdout:
        out_log_msg += ", stdout log: %s" % stdout.name
    if stderr:
        out_log_msg += ", stderr log: %s" % stderr.name

    # Execute command and use `os.setsid` in preexec_fn to create new process
    # group so we can kill the main process and also children processes in
    # case of timeout.
    log.info("Executing command: %s%s" % (args, out_log_msg))
    proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, cwd=cwd,
                            preexec_fn=os.setsid)

    # Setup timer to kill whole process group if needed.
    if timeout:
        timeout_timer = Timer(timeout, _kill_process_group, [proc, args])

    try:
        if timeout:
            timeout_timer.start()
        proc.communicate()
    finally:
        timeout_expired = False
        if timeout:
            if timeout_timer.finished.is_set():
                timeout_expired = True
            timeout_timer.cancel()

    if timeout_expired:
        raise RuntimeError(
            "Compose has taken more time than allowed by configuration "
            "(%d seconds)" % conf.pungi_timeout)

    if proc.returncode != 0:
        err_msg = "Command '%s' returned non-zero value %d%s" % (args, proc.returncode, out_log_msg)
        raise RuntimeError(err_msg)


def hardlink(dirs, verbose=False):
    """Run hardlink to consolidates duplicate files in dirs"""
    hardlink_exe = find_executable('hardlink')
    if not hardlink_exe:
        raise RuntimeError("hardlink is not available on system")

    args = [hardlink_exe]
    if verbose:
        args.append('-vv')

    if isinstance(dirs, list):
        args.extend(dirs)
    else:
        args.append(dirs)

    execute_cmd(args)
