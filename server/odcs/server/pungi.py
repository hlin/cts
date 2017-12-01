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
import shutil
import tempfile
import jinja2
import koji
import munch
import time
import random
import string

import odcs.server.utils
from odcs.server import conf, log
from odcs.server import comps
from odcs.common.types import PungiSourceType, COMPOSE_RESULTS
from odcs.server.utils import makedirs


class PungiConfig(object):
    def __init__(self, release_name, release_version, source_type, source,
                 packages=None, arches=None, sigkeys=None, results=0):
        self.release_name = release_name
        self.release_version = release_version
        self.bootable = False
        self.sigkeys = sigkeys.split(" ") if sigkeys else []
        self.pdc_url = conf.pdc_url
        self.pdc_insecure = conf.pdc_insecure
        self.pdc_develop = conf.pdc_develop
        self.source_type = source_type
        self.source = source
        self.koji_profile = conf.koji_profile
        self.pkgset_koji_inherit = True
        if arches:
            self.arches = arches
        else:
            self.arches = conf.arches
        self.packages = packages or []

        # Store results as list of strings, so it can be used by jinja2
        # templates.
        self.results = []
        for k, v in COMPOSE_RESULTS.items():
            if results & v:
                self.results.append(k)

        if source_type == PungiSourceType.KOJI_TAG:
            self.koji_tag = source
            self.gather_source = "comps"
            self.gather_method = "deps"
        elif source_type == PungiSourceType.MODULE:
            # We have to set koji_tag to something even when we are not using
            # it.
            self.koji_tag = None
            self.gather_source = "module"
            self.gather_method = "nodeps"

            if self.packages:
                raise ValueError("Exact packages cannot be set for MODULE "
                                 "source type.")
        elif source_type == PungiSourceType.REPO:
            self.gather_source = "comps"
            self.gather_method = "deps"
            self.koji_tag = None
        else:
            raise ValueError("Unknown source_type %r" % source_type)

    @property
    def release_short(self):
        return self.release_name[:16]

    @property
    def comps_file(self):
        if self.source_type == PungiSourceType.MODULE:
            return None
        else:
            return "comps.xml"

    @property
    def pkgset_source(self):
        if self.source_type == PungiSourceType.REPO:
            return 'repos'
        return 'koji'

    def get_comps_config(self):
        if self.source_type == PungiSourceType.MODULE:
            return ""
        odcs_comps = comps.Comps()
        odcs_group = comps.Group('odcs-group', 'odcs-group', 'ODCS compose default group')
        for package in self.packages:
            odcs_group.add_package(comps.Package(package))
        odcs_comps.add_group(odcs_group)

        template = jinja2.Template(comps.COMPS_TEMPLATE)
        return template.render(comps=odcs_comps)

    def get_variants_config(self):
        odcs_product = comps.Product()
        tmp_variant = comps.Variant('Temporary', 'Temporary', 'variant', self.source_type)
        for arch in self.arches:
            tmp_variant.add_arch(comps.Arch(arch))
        if self.source_type == PungiSourceType.MODULE:
            for module in self.source.split(" "):
                tmp_variant.add_module(comps.Module(module))
        elif self.source_type == PungiSourceType.KOJI_TAG:
            if self.packages:
                tmp_variant.add_group(comps.Group('odcs-group', 'odcs-group', 'ODCS compose default group'))

        odcs_product.add_variant(tmp_variant)

        template = jinja2.Template(comps.VARIANTS_TEMPLATE)
        return template.render(product=odcs_product)

    def get_pungi_config(self):
        try:
            with open(conf.pungi_conf_path) as fd:
                template = jinja2.Template(fd.read())
            return template.render(config=self)
        except Exception as e:
            log.exception(
                "Failed to render pungi conf template {!r}: {}".format(conf.pungi_conf_path,
                                                                       str(e)))


class Pungi(object):
    def __init__(self, pungi_cfg, koji_event=None):
        self.pungi_cfg = pungi_cfg
        self.koji_event = koji_event

    def _write_cfg(self, path, cfg):
        """
        Writes configuration string `cfg` to file defined by `path`.
        :param str path: Full path to file to write to.
        :param str cfg: Configuration to write.
        """
        with open(path, "w") as f:
            log.info("Writing %s configuration to %s.", os.path.basename(path), path)
            f.write(cfg)

    def _write_cfgs(self, topdir):
        """
        Writes "pungi.conf", "variants.xml" and "comps.xml" defined in
        `self.pungi_cfg` to `topdir` directory.
        :param str topdir: Directory to write the files to.
        """
        main_cfg = self.pungi_cfg.get_pungi_config()
        variants_cfg = self.pungi_cfg.get_variants_config()
        comps_cfg = self.pungi_cfg.get_comps_config()
        log.debug("Main Pungi config:")
        log.debug("%s", main_cfg)
        log.debug("Variants.xml:")
        log.debug("%s", variants_cfg)
        log.debug("Comps.xml:")
        log.debug("%s", comps_cfg)

        self._write_cfg(os.path.join(topdir, "pungi.conf"), main_cfg)
        self._write_cfg(os.path.join(topdir, "variants.xml"), variants_cfg)
        self._write_cfg(os.path.join(topdir, "comps.xml"), comps_cfg)

    def make_koji_session(self):
        """
        Creates new KojiSession according to odcs.server.conf, logins to
        Koji using this session and returns it.
        :rtype: koji.KojiSession
        :return: KojiSession
        """
        koji_config = munch.Munch(koji.read_config(
            profile_name=conf.koji_profile,
            user_config=conf.koji_config,
        ))

        address = koji_config.server
        authtype = koji_config.authtype
        log.info("Connecting to koji %r with %r." % (address, authtype))
        koji_session = koji.ClientSession(address, opts=koji_config)
        if authtype == "kerberos":
            ccache = getattr(conf, "krb_ccache", None)
            keytab = getattr(conf, "krb_keytab", None)
            principal = getattr(conf, "krb_principal", None)
            log.debug("  ccache: %r, keytab: %r, principal: %r" % (
                ccache, keytab, principal))
            if keytab and principal:
                koji_session.krb_login(
                    principal=principal,
                    keytab=keytab,
                    ccache=ccache,
                )
            else:
                koji_session.krb_login(ccache=ccache)
        elif authtype == "ssl":
            koji_session.ssl_login(
                os.path.expanduser(koji_config.cert),
                None,
                os.path.expanduser(koji_config.serverca),
            )
        else:
            raise ValueError("Unrecognized koji authtype %r" % authtype)

        return koji_session

    def get_pungi_cmd(self, conf_topdir, targetdir):
        """
        Returns list with pungi command line arguments needed to generate
        the compose.
        :param str conf_topdir: Directory in which to look for Pungi
            configuration files.
        :param str targetdir: Target directory in which the compose should be
            generated.
        :rtype: list
        :return: List of pungi command line arguments.
        """
        pungi_cmd = [
            conf.pungi_koji, "--config=%s" % os.path.join(conf_topdir, "pungi.conf"),
            "--target-dir=%s" % targetdir, "--nightly"]

        if self.koji_event:
            pungi_cmd += ["--koji-event", str(self.koji_event)]
        return pungi_cmd

    def run_locally(self):
        """
        Runs local Pungi compose.
        """
        td = None
        try:
            td = tempfile.mkdtemp()
            self._write_cfgs(td)
            pungi_cmd = self.get_pungi_cmd(td, conf.target_dir)
            odcs.server.utils.execute_cmd(pungi_cmd, cwd=td)
        finally:
            try:
                if td is not None:
                    shutil.rmtree(td)
            except Exception as e:
                log.warning(
                    "Failed to remove temporary directory {!r}: {}".format(
                        td, str(e)))

    def _unique_path(prefix):
        """
        Create a unique path fragment by appending a path component
        to prefix.  The path component will consist of a string of letter and numbers
        that is unlikely to be a duplicate, but is not guaranteed to be unique.
        """
        # Use time() in the dirname to provide a little more information when
        # browsing the filesystem.
        # For some reason repr(time.time()) includes 4 or 5
        # more digits of precision than str(time.time())
        # Unnamed Engineer: Guido v. R., I am disappoint
        return '%s/%r.%s' % (prefix, time.time(),
                                ''.join([random.choice(string.ascii_letters)
                                        for i in range(8)]))

    def upload_files_to_koji(self, koji_session, localdir):
        """
        Uploads files from `localdir` directory to Koji server using
        `koji_session`. The unique server-side directory containing
        the uploaded files is returned.
        :param koji.KojiSession koji_session: Koji session.
        "param str localdir: Path to directory with files to upload.
        """
        serverdir = self._unique_path("odcs")

        for name in os.listdir(localdir):
            path = os.path.join(localdir, name)
            koji_session.uploadWrapper(path, serverdir, callback=None)

        return serverdir

    def run_in_runroot(self):
        """
        Runs the compose in runroot, waits for a result and raises an
        exception if the Koji runroot tasks failed.
        """
        conf_topdir = os.path.join(conf.target_dir, "runroot_configs",
                                   self.pungi_cfg.release_name)
        makedirs(conf_topdir)
        self._write_cfgs(conf_topdir)

        koji_session = self.make_koji_session()
        serverdir = self.upload_files_to_koji(koji_session, conf_topdir)

        # TODO: Copy keytab from secret repo and generate koji profile.
        cmd = []
        cmd += ["cp", "/mnt/koji/work/%s/*" % serverdir, ".", "&&"]
        cmd += self.get_pungi_cmd("./", conf.pungi_runroot_target_dir)

        kwargs = {
            'channel': conf.pungi_parent_runroot_channel,
            'packages': conf.pungi_parent_runroot_packages,
            'mounts': conf.pungi_parent_runroot_mounts,
            'weight': conf.pungi_parent_runroot_weight
        }

        task_id = koji_session.runroot(
            conf.pungi_parent_runroot_tag, conf.pungi_parent_runroot_arch,
            " ".join(cmd), **kwargs)

        while True:
            # wait for the task to finish
            if koji_session.taskFinished(task_id):
                break
            log.info("Waiting for Koji runroot task %r to finish...", task_id)
            time.sleep(60)

        info = koji_session.getTaskInfo(task_id)
        if info is None:
            raise RuntimeError("Cannot get status of Koji task %r" % task_id)
        state = koji.TASK_STATES[info['state']]
        if state in ('FAILED', 'CANCELED'):
            raise RuntimeError("Koji runroot task %r failed." % task_id)

    def run(self):
        """
        Runs the compose in Pungi. Blocks until the compose is done.
        Raises an exception if compose generation fails.
        """
        if conf.pungi_runroot_enabled:
            self.run_in_runroot()
        else:
            self.run_locally()
