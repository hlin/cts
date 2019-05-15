# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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
#
# This script is executed on runroot hosts when Pungi needs to execute runroot
# tasks. It is therefore execute with "root" permissions, initializes the
# Mock environment and allows installing packages and running commands in
# the Mock environment.
#
# The script is executed using SSH from the ODCS backend.
#
# The workflow is following:
#
#   1) The `mock_runroot_init` is called. This generates unique ID defining
#      the Mock chroot. It initializes the Mock environment and prints
#      the unique ID ("runroot_key") to stdout. The "runroot_key" is later
#      used to identify the Mock chroot.
#   2) The `mock_runroot_install` is called to install the requested packages
#      in the Mock chroot for the runroot task. The "runroot_key" is used
#      to get the particular Mock chroot.
#   3) The `mock_runroot_run` is called to run the runroot command in
#      the Mock chroot. The conf.target_dir is mounted in the Mock chroot, so
#      the output of this command can be stored there.

from __future__ import print_function
import platform
import sys
import koji
import os
import uuid
import tempfile
import logging

from odcs.server import conf
from odcs.server.backend import create_koji_session
from odcs.server.utils import makedirs, execute_cmd


def do_mounts(rootdir, mounts):
    """
    Mounts the host `mounts` in the Mock chroot `rootdir`.

    :param str rootdir: Full path to root directory for Mock chroot.
    :param list mounts: Full paths to mount directories which will be mounted
        in the `rootdir`.
    """
    for mount in mounts:
        mpoint = "%s%s" % (rootdir, mount)
        makedirs(mpoint)
        cmd = ["mount", "-o", "bind", mount, mpoint]
        execute_cmd(cmd)


def undo_mounts(rootdir, mounts):
    """
    Umounts the host `mounts` from the Mock chroot `rootdir`.

    :param str rootdir: Full path to root directory for Mock chroot.
    :param list mounts: Full paths to mount directories which will be umounted
        from the `rootdir`.
    """
    for mount in mounts:
        mpoint = "%s%s" % (rootdir, mount)
        cmd = ["umount", "-l", mpoint]
        execute_cmd(cmd)


def runroot_tmp_path(runroot_key):
    """
    Creates and returns the temporary path to store the configuration files
    or logs for the runroot task.

    :param str runroot_key: The Runroot key.
    :return str: Full-path to temporary directory.
    """
    path = os.path.join(tempfile.gettempdir(), "odcs-runroot-%s" % runroot_key)
    makedirs(path)
    return path


def execute_mock(runroot_key, args, log_output=True):
    """
    Executes the Mock command with `args` for given `runroot_key` Mock chroot.

    :param str runroot_key: Runroot key.
    :param list args: The "mock" command arguments.
    :param bool log_output: When True, stdout and stderr of Mock command are
        redirected to logs.
    """
    runroot_path = runroot_tmp_path(runroot_key)
    mock_cfg_path = os.path.join(runroot_path, "mock.cfg")
    cmd = ["mock", "-r", mock_cfg_path] + args
    if log_output:
        stdout_log_path = os.path.join(runroot_path, "mock-stdout.log")
        stderr_log_path = os.path.join(runroot_path, "mock-stderr.log")
        with open(stdout_log_path, "a") as stdout_log:
            with open(stderr_log_path, "a") as stderr_log:
                execute_cmd(cmd, stdout=stdout_log, stderr=stderr_log)
    else:
        execute_cmd(cmd)


def mock_runroot_init(tag_name):
    """
    Creates and initializes new Mock chroot for runroot task.
    Prints the unique ID of chroot ("runroot_key") to stdout.

    :param str tag_name: Koji tag name from which the default packages for
        the Mock chroot are taken.
    """
    # Generate the runroot_key.
    runroot_key = str(uuid.uuid1())

    # Disable logging completely for the rest of execution, because the only
    # thing we must print is the runroot_key and the general logging to stdout
    # would confuse Pungi when calling this method.
    logging.disable(logging.CRITICAL)

    # Get the latest Koji repo associated with the tag.
    koji_module = koji.get_profile_module(conf.koji_profile)
    koji_session = create_koji_session()
    repo = koji_session.getRepo(tag_name)
    if not repo:
        raise ValueError("Repository for tag %s does not exist." % tag_name)

    # Set the default options for Mock configuration.
    opts = {}
    opts["topdir"] = koji_module.pathinfo.topdir
    opts["topurl"] = koji_module.config.topurl
    opts["use_host_resolv"] = True
    opts["package_manager"] = "dnf"
    arch = koji.canonArch(platform.machine())

    # Generate the Mock configuration using the standard Koji way.
    output = koji_module.genMockConfig(
        runroot_key, arch, repoid=repo["id"], tag_name=tag_name, **opts)

    # Write the Mock configuration to /tmp/`runroot_key`/mock.cfg.
    mock_cfg_path = os.path.join(runroot_tmp_path(runroot_key), "mock.cfg")
    with open(mock_cfg_path, "w") as mock_cfg:
        mock_cfg.write(output)

    # Print the runroot_key to stdout, so the caller can store it and use it
    # in the future calls.
    print(runroot_key)

    # Run the `mock --init` with some log files.
    execute_mock(runroot_key, ["--init"])


def raise_if_runroot_key_invalid(runroot_key):
    """
    Raise an ValueError exception in case the `runroot_key` contains forbidden
    characters.
    """
    for c in runroot_key:
        if c != "-" and not c.isalnum():
            raise ValueError(
                "Unexpected character '%s' in the runroot key \"%s\"."
                % (c, runroot_key))


def mock_runroot_install(runroot_key, packages):
    """
    Installs the `packages` in the Mock chroot defined by `runroot_key`.

    :param str runroot_key: Runroot key.
    :param list packages: List of packages to install.
    """
    raise_if_runroot_key_invalid(runroot_key)
    execute_mock(runroot_key, ["--install"] + packages)


def mock_runroot_run(runroot_key, cmd):
    """
    Executes the `cmd` in the Mock chroot defined by `runroot_key`.

    :param str runroot_key: Runroot key.
    :param list cmd: Command to execute.
    """
    raise_if_runroot_key_invalid(runroot_key)
    rootdir = "/var/lib/mock/%s/root" % runroot_key

    try:
        # Mount the conf.targetdir in the Mock chroot.
        do_mounts(rootdir, [conf.target_dir] + conf.runroot_extra_mounts)

        # Wrap the runroot command in /bin/sh, because that's how Koji does
        # that and we need to stay compatible with this way...
        sh_wrapper = ['/bin/sh', '-c', "{ %s; }" % (" ".join(cmd))]

        # Run the command in Mock chroot. We need to use the `--old-chroot`
        # here, otherwise Lorax fails.
        args = ["--old-chroot", "--chroot", "--"] + sh_wrapper
        execute_mock(runroot_key, args, False)
    finally:
        # In the end of run, umount the conf.targetdir.
        undo_mounts(rootdir, [conf.target_dir] + conf.runroot_extra_mounts)


def mock_runroot_main(argv=None):
    """
    Main method handling the subcommands.

    :param list argv: List of arguments. If None, sys.argv is used.
    """
    argv = argv or sys.argv
    if argv[1] == "init":
        mock_runroot_init(argv[2])
    elif argv[1] == "install":
        mock_runroot_install(argv[2], argv[3:])
    elif argv[1] == "run":
        mock_runroot_run(argv[2], argv[3:])
