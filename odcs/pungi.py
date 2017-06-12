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
from odcs import conf, log
import odcs.utils


class PungiSourceType:
    KOJI_TAG = 1
    MODULE = 2
    REPO = 3


class PungiConfig(object):
    def __init__(self, release_name, release_version, source_type, source,
                 packages=None, arches=None):
        self.release_name = release_name
        self.release_version = release_version
        self.bootable = None
        self.sigkeys = []
        self.pdc_url = conf.pdc_url
        self.pdc_insecure = conf.pdc_insecure
        self.pdc_develop = conf.pdc_develop
        self.source_type = source_type
        self.source = source
        self.koji_profile = conf.koji_profile
        if arches:
            self.arches = arches
        else:
            self.arches = conf.arches
        self.packages = packages or []

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

    def _get_bootable(self):
        if not self.bootable:
            return ""
        return "bootable = True\n"

    def _get_sigkeys(self):
        if not self.sigkeys:
            return "sigkeys = [None]\n"

    def _get_pkgset(self):
        ret = ""
        if self.source_type == PungiSourceType.REPO:
            ret += "pkgset_source = 'repos'\n"
            ret += "pkgset_repos = {\n"
            for arch in self.arches:
                ret += "'%s': [\n" % arch
                ret += "   '%s',\n" % self.source
                ret += "],\n"
            ret += "}\n"
        else:
            ret += "pkgset_source = 'koji'\n"
            ret += "pkgset_koji_tag = '%s'\n" % self.koji_tag
            ret += "pkgset_koji_inherit = False\n"

        return ret

    def get_comps_config(self):
        if self.source_type == PungiSourceType.MODULE:
            return ""

        cfg = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE comps PUBLIC "-//Red Hat, Inc.//DTD Comps info//EN" "comps.dtd">
<comps>
  <group>
    <id>odcs-group</id>
    <name>odcs-group</name>
    <description>ODCS compose default group</description>
    <default>false</default>
    <uservisible>true</uservisible>
    <packagelist>
"""

        for package in self.packages:
            cfg += '      <packagereq type="default">%s</packagereq>\n' % package

        cfg += """
    </packagelist>
  </group>
</comps>
"""

        return cfg

    def get_variants_config(self):
        cfg = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE variants PUBLIC "-//Red Hat, Inc.//DTD Variants info//EN" "variants2012.dtd">
<variants>
    <variant id="Temporary" name="Temporary" type="variant">
        <arches>
"""

        for arch in self.arches:
            cfg += "            <arch>%s</arch>\n" % arch
        cfg += "        </arches>\n"

        if self.source_type == PungiSourceType.MODULE:
            cfg += "        <modules>\n"
            for module in self.source.split(" "):
                cfg += "            <module>%s</module>\n" % module
            cfg += "        </modules>"
        elif self.source_type == PungiSourceType.KOJI_TAG:
            if self.packages:
                cfg += "        <groups>\n"
                cfg += "            <group default=\"true\">odcs-group</group>\n"
                cfg += "        </groups>"
        cfg += """    </variant>
</variants>
"""

        return cfg

    def get_pungi_config(self):
        cfg = """ # Automatically generated by ODCS.
# PRODUCT INFO
release_name = '{release_name}'
release_short = '{release_short}'
release_version = '{release_version}'
release_is_layered = False

# GENERAL SETTINGS
{bootable}

variants_file='variants.xml'
{sigkeys}

hashed_directories = True

# RUNROOT settings
runroot = False

# PDC settings
pdc_url = '{pdc_url}'
pdc_insecure = {pdc_insecure}
pdc_develop = {pdc_develop}

# PKGSET
{pkgset}

filter_system_release_packages = False

# GATHER
gather_source = '{gather_source}'
gather_method = '{gather_method}'
{comps_file}
comps_file = 'comps.xml'
check_deps = False
greedy_method = 'build'

# CREATEREPO
createrepo_c = True
createrepo_checksum = 'sha256'

# CHECKSUMS
media_checksums = ['sha256']
create_jigdo = False

skip_phases = ["buildinstall", "live_media", "live_images", "ostree"]

translate_paths = [
   ('/mnt/koji/compose/', 'http://kojipkgs.fedoraproject.org/compose/'),
]

koji_profile = '{koji_profile}'

""".format(release_name=self.release_name, release_version=self.release_version,
           release_short=self.release_name[:16], bootable=self._get_bootable(),
           sigkeys=self._get_sigkeys(), pdc_url=self.pdc_url,
           pdc_insecure=self.pdc_insecure, pdc_develop=self.pdc_develop,
           pkgset=self._get_pkgset(), gather_source=self.gather_source,
           gather_method=self.gather_method, koji_profile=self.koji_profile,
           comps_file = "comps_file = 'comps.xml'" if self.source_type != PungiSourceType.REPO else "")

        return cfg


class Pungi(object):
    def __init__(self, pungi_cfg):
        self.pungi_cfg = pungi_cfg

    def _write_cfg(self, fn, cfg):
        with open(fn, "w") as f:
            log.info("Writing %s configuration to %s.", os.path.basename(fn), fn)
            f.write(cfg)

    def run(self):
        td = None
        try:
            td = tempfile.mkdtemp()

            main_cfg = self.pungi_cfg.get_pungi_config()
            variants_cfg = self.pungi_cfg.get_variants_config()
            comps_cfg = self.pungi_cfg.get_comps_config()
            log.debug("Main Pungi config:")
            log.debug("%s", main_cfg)
            log.debug("Variants.xml:")
            log.debug("%s", variants_cfg)
            log.debug("Comps.xml:")
            log.debug("%s", comps_cfg)

            self._write_cfg(os.path.join(td, "pungi.conf"), main_cfg)
            self._write_cfg(os.path.join(td, "variants.xml"), variants_cfg)
            self._write_cfg(os.path.join(td, "comps.xml"), comps_cfg)

            odcs.utils.execute_cmd([
                conf.pungi_koji, "--config=%s" % os.path.join(td, "pungi.conf"),
                "--target-dir=%s" % conf.target_dir, "--nightly"], cwd=td)
        finally:
            try:
                if td is not None:
                    shutil.rmtree(td)
            except Exception as e:
                log.warning(
                    "Failed to remove temporary directory {!r}: {}".format(
                        td, str(e)))
