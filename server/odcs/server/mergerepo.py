# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
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

from odcs.server import log
from odcs.server.utils import makedirs, find_executable, execute_cmd


class MergeRepo(object):
    def __init__(self, compose):
        self.compose = compose

    def run(self, arch, repos):
        """
        Merges multiple RPM repositories and stores the output to
        `os.path.join(compose.result_repo_dir, arch)`.

        Raises an RuntimeError in case of error.

        :param str arch: Architecture of RPMs in repositories.
        :param list repos: List of URLs pointing to repos to merge.
        """
        log.info("%r: Starting mergerepo_c: %r", self.compose, repos)

        mergerepo_exe = find_executable('mergerepo_c')
        if not mergerepo_exe:
            raise RuntimeError("mergerepo_c is not available on system")

        result_repo_dir = os.path.join(self.compose.result_repo_dir, arch)
        makedirs(result_repo_dir)

        args = [mergerepo_exe, "-v", "-o", result_repo_dir]
        for repo in repos:
            args.append("-r")
            args.append(repo)

        execute_cmd(args)
