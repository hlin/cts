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

import copy
import os
import shutil
import tempfile
import jinja2
import time
import threading
import json
from productmd.composeinfo import ComposeInfo
from kobo.conf import PyConfigParser

import odcs.server.utils
from odcs.server import conf, log, db
from odcs.server import comps
from odcs.server.models import Compose
from odcs.common.types import (
    PungiSourceType,
    COMPOSE_RESULTS,
    MULTILIB_METHODS,
    INVERSE_PUNGI_SOURCE_TYPE_NAMES,
    COMPOSE_FLAGS,
)
from odcs.server.utils import makedirs, clone_repo, copytree


class BasePungiConfig(object):
    def __init__(self):
        self.pungi_timeout = conf.pungi_timeout

    def _write(self, path, cfg):
        """
        Writes configuration string `cfg` to file defined by `path`.

        :param str path: Full path to file to write to.
        :param str cfg: Configuration to write.
        """
        with open(path, "w") as f:
            log.info("Writing %s configuration to %s.", os.path.basename(path), path)
            f.write(cfg)

    def write_config_files(self, topdir):
        """Write configuration into files"""
        raise NotImplementedError("Concrete config object must implement.")

    def validate(self, topdir, compose_dir):
        """Validate configuration. Raises an exception of error found."""
        pass


class RawPungiConfig(BasePungiConfig):
    def __init__(self, compose):
        super(RawPungiConfig, self).__init__()
        self.compose = compose
        source_name, source_hash = compose.source.split("#")

        url_data = copy.deepcopy(conf.raw_config_urls[source_name])
        # Do not override commit hash by hash from ODCS client if it is
        # hardcoded in the config file.
        if "commit" not in url_data:
            url_data["commit"] = source_hash

        self.pungi_timeout = url_data.get("pungi_timeout", conf.pungi_timeout)
        self.raw_config_wrapper_conf_path = url_data.get(
            "raw_config_wrapper", conf.raw_config_wrapper_conf_path
        )
        self.pungi_cfg = url_data
        self.pungi_koji_args = conf.raw_config_pungi_koji_args.get(
            source_name, conf.pungi_koji_args
        )

    def apply_raw_config_wrapper_overrides(self, cfg_path):
        try:
            with open(cfg_path) as fd:
                raw_config_wrapper = jinja2.Template(fd.read())
            with open(cfg_path, "w") as fd:
                fd.write(raw_config_wrapper.render(compose=self.compose.json()))
        except Exception as e:
            log.exception(
                "Failed to render raw_config_wrapper template {!r}: {}".format(
                    cfg_path, str(e)
                )
            )
            raise

    def write_config_files(self, topdir):
        """Write raw config files

        :param str topdir: Directory to write the files to.
        """
        # In case the raw_config wrapper config is set, download the
        # original pungi.conf as "raw_config.conf" and use
        # the raw_config wrapper as real "pungi.conf".
        # The reason is that wrapper config can import raw_config
        # and override some variables.
        if self.raw_config_wrapper_conf_path:
            main_cfg_path = os.path.join(topdir, "raw_config.conf")
            shutil.copyfile(
                self.raw_config_wrapper_conf_path, os.path.join(topdir, "pungi.conf")
            )
            self.apply_raw_config_wrapper_overrides(os.path.join(topdir, "pungi.conf"))
        else:
            main_cfg_path = os.path.join(topdir, "pungi.conf")

        # Clone the git repo with raw_config pungi config files.
        repo_dir = os.path.join(topdir, "raw_config_repo")
        clone_repo(self.pungi_cfg["url"], repo_dir, commit=self.pungi_cfg["commit"])

        # If the 'path' is defined, copy only the files form the 'path'
        # to topdir.
        if "path" in self.pungi_cfg:
            repo_dir = os.path.join(repo_dir, self.pungi_cfg["path"])

        copytree(repo_dir, topdir)

        # If pungi_config_dump is defined, it means that we are regenerating
        # already built production compose and this should use the very same
        # Pungi config file as the original one.
        # We still want to use the latest raw_config_wrapper, because this
        # is used to configure some important variables which can change
        # in the future ODCS deployment - like "koji_profile" or "runroot_method".
        # We also want to be able to respin the compose with the very same
        # configuration but include one new package build to fix last-minute
        # issues with the compose - this new build will also be set using the
        # raw_config_wrapper.
        if self.compose.pungi_config_dump:
            # Load the config dump.
            pungi_config_dump = json.loads(self.compose.pungi_config_dump)

            # If raw_config_wrapper is used, update the pungi_config_dump according
            # to it.
            if self.raw_config_wrapper_conf_path:
                # At first create empty "raw_config.conf" file so "raw_config_wrapper.conf"
                # can import it and can be loaded by PyConfigParser.
                with open(main_cfg_path, "w") as fd:
                    fd.write("# empty config file")

                # Load the raw_config_wrapper and update pungi_config_dump.
                raw_config_wrapper = PyConfigParser()
                raw_config_wrapper.load_from_file(os.path.join(topdir, "pungi.conf"))
                pungi_config_dump.update(raw_config_wrapper)

            # Create the pungi.json
            with open(os.path.join(topdir, "pungi.json"), "w") as fd:
                fd.write(json.dumps(pungi_config_dump))
        else:
            # Create the "pungi.conf" from config_filename.
            config_path = os.path.join(topdir, self.pungi_cfg["config_filename"])
            if config_path != main_cfg_path:
                shutil.copy2(config_path, main_cfg_path)
            c = PyConfigParser()

            # Create pungi.json.
            c.load_from_file(os.path.join(topdir, "pungi.conf"))
            with open(os.path.join(topdir, "pungi.json"), "w") as fd:
                fd.write(json.dumps(c))

    def validate(self, topdir, compose_dir):
        if not conf.pungi_config_validate:
            return
        pungi_config_validate_cmd = [conf.pungi_config_validate, "--old-composes"]

        # Apply global schema override.
        if conf.raw_config_schema_override:
            pungi_config_validate_cmd += [
                "--schema-override",
                conf.raw_config_schema_override,
            ]

        # Apply raw_config specific schema override.
        if "schema_override" in self.pungi_cfg:
            pungi_config_validate_cmd += [
                "--schema-override",
                self.pungi_cfg["schema_override"],
            ]

        # Add raw_config configuration file to validate.
        pungi_config_validate_cmd.append(os.path.join(topdir, "pungi.json"))

        # Run the pungi-config-validate. The execute_cmd raises an exception
        # if config is invalid.
        log_out_path = os.path.join(compose_dir, "pungi-config-validate-stdout.log")
        log_err_path = os.path.join(compose_dir, "pungi-config-validate-stderr.log")
        with open(log_out_path, "w") as log_out:
            with open(log_err_path, "w") as log_err:
                odcs.server.utils.execute_cmd(
                    pungi_config_validate_cmd, stdout=log_out, stderr=log_err
                )


class PungiConfig(BasePungiConfig):
    def __init__(
        self,
        release_name,
        release_version,
        source_type,
        source,
        packages=None,
        arches=None,
        sigkeys=None,
        results=0,
        multilib_arches=None,
        multilib_method=0,
        builds=None,
        flags=0,
        lookaside_repos=None,
        modular_koji_tags=None,
        module_defaults_url=None,
        scratch_modules=None,
        scratch_build_tasks=None,
        modules=None,
    ):
        super(PungiConfig, self).__init__()
        self.release_name = release_name
        self.release_version = release_version
        self.bootable = False
        self.sigkeys = sigkeys.split(" ") if sigkeys else []
        self.source_type = source_type
        self.source = source
        self.koji_profile = conf.koji_profile
        self.pkgset_koji_inherit = True
        self.lookaside_repos = lookaside_repos.split(" ") if lookaside_repos else []
        if arches:
            self.arches = arches
        else:
            self.arches = conf.arches
        self.packages = packages or []
        self.builds = builds or []
        self.scratch_modules = scratch_modules.split(" ") if scratch_modules else []
        self.modules = modules.split(" ") if modules else []
        self.scratch_build_tasks = (
            scratch_build_tasks.split(" ") if scratch_build_tasks else []
        )
        self.pkgset_allow_reuse = True

        # Store results as list of strings, so it can be used by jinja2
        # templates.
        self.results = []
        for k, v in COMPOSE_RESULTS.items():
            if results & v:
                self.results.append(k)

        self.multilib_arches = multilib_arches if multilib_arches else []
        self.multilib_method = []
        if multilib_method:
            for k, v in MULTILIB_METHODS.items():
                if multilib_method & v:
                    self.multilib_method.append(k)

        if "boot.iso" in self.results:
            self.bootable = True

        if source_type == PungiSourceType.KOJI_TAG:
            self.koji_module_tags = (
                modular_koji_tags.split(" ") if modular_koji_tags else []
            )
            self.module_defaults_url = (
                module_defaults_url.split(" ") if module_defaults_url else []
            )
            self.koji_tag = source
            self.gather_source = "comps"
            if self.koji_module_tags:
                self.gather_method = "hybrid"
            else:
                self.gather_method = "deps"
        elif source_type == PungiSourceType.MODULE:
            self.koji_tag = None
            self.gather_source = "module"
            self.gather_method = "nodeps"
            self.module_defaults_url = (
                module_defaults_url.split(" ") if module_defaults_url else []
            )

            if self.packages:
                raise ValueError(
                    "Exact packages cannot be set for MODULE " "source type."
                )
        elif source_type in [
            PungiSourceType.BUILD,
            PungiSourceType.PUNGI_COMPOSE,
            PungiSourceType.REPO,
        ]:
            self.gather_source = "comps"
            self.gather_method = "deps"
            self.koji_tag = None
        else:
            raise ValueError("Unknown source_type %r" % source_type)

        self.check_deps = bool(flags & COMPOSE_FLAGS["check_deps"])

    @property
    def source_type_str(self):
        return INVERSE_PUNGI_SOURCE_TYPE_NAMES[self.source_type]

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
            return "repos"
        return "koji"

    @property
    def mbs_api_url(self):
        return os.path.join(conf.mbs_url, "1")

    def get_comps_config(self):
        if self.source_type == PungiSourceType.MODULE:
            return ""
        odcs_comps = comps.Comps()
        odcs_group = comps.Group(
            "odcs-group", "odcs-group", "ODCS compose default group"
        )
        for package in self.packages:
            odcs_group.add_package(comps.Package(package))
        odcs_comps.add_group(odcs_group)

        template = jinja2.Template(comps.COMPS_TEMPLATE)
        return template.render(comps=odcs_comps)

    def get_variants_config(self):
        odcs_product = comps.Product()
        tmp_variant = comps.Variant(
            "Temporary", "Temporary", "variant", self.source_type
        )
        for arch in self.arches:
            tmp_variant.add_arch(comps.Arch(arch))
        if self.source_type == PungiSourceType.MODULE:
            for module in self.source.split(" "):
                if module:
                    tmp_variant.add_module(comps.Module(module))
        elif self.source_type == PungiSourceType.KOJI_TAG:
            if self.packages:
                tmp_variant.add_group(
                    comps.Group(
                        "odcs-group", "odcs-group", "ODCS compose default group"
                    )
                )
            if self.koji_module_tags:
                tmp_variant.add_module(comps.Module("*"))

        odcs_product.add_variant(tmp_variant)

        template = jinja2.Template(comps.VARIANTS_TEMPLATE)
        return template.render(product=odcs_product)

    def get_pungi_config(self):
        try:
            with open(conf.pungi_conf_path) as fd:
                template = jinja2.Template(fd.read())
            c_data = template.render(config=self)
            c = PyConfigParser()
            c.load_from_string(c_data)
            return c
        except Exception as e:
            log.exception(
                "Failed to render pungi conf template {!r}: {}".format(
                    conf.pungi_conf_path, str(e)
                )
            )

    def write_config_files(self, topdir):
        """
        Writes "pungi.conf", "variants.xml" and "comps.xml" defined in
        `self.pungi_cfg` to `topdir` directory.

        :param str topdir: Directory to write the files to.
        """
        main_cfg = self.get_pungi_config()
        variants_cfg = self.get_variants_config()
        comps_cfg = self.get_comps_config()
        log.debug("Main Pungi config:")
        log.debug("%s", main_cfg)
        log.debug("Variants.xml:")
        log.debug("%s", variants_cfg)
        log.debug("Comps.xml:")
        log.debug("%s", comps_cfg)

        self._write(os.path.join(topdir, "pungi.json"), json.dumps(main_cfg))
        self._write(os.path.join(topdir, "variants.xml"), variants_cfg)
        self._write(os.path.join(topdir, "comps.xml"), comps_cfg)


class ReadComposeIdThread(threading.Thread):
    def __init__(self, compose):
        threading.Thread.__init__(self)
        self._stop_event = threading.Event()
        self.compose = compose

    def stop(self):
        self._stop_event.set()

    def run(self):
        p = os.path.join(
            self.compose.toplevel_dir, "work", "global", "composeinfo-base.json"
        )
        while not self._stop_event.is_set():
            time.sleep(1)

            # File does not exist yet.
            if not os.path.exists(p):
                continue

            ci = ComposeInfo()
            try:
                ci.load(p)
            except Exception:
                # This should happen only if file exists, but the data is not
                # written yet.
                continue

            self.compose.pungi_compose_id = ci.compose.id
            db.session.commit()
            break


class Pungi(object):
    def __init__(self, compose_id, pungi_cfg, koji_event=None, old_compose=None):
        self.compose_id = compose_id
        self.pungi_cfg = pungi_cfg
        self.koji_event = koji_event
        self.old_compose = old_compose

    def _write_cfgs(self, topdir):
        """Wrtie pungi config

        :param str topdir: Directory to write the files to.
        """
        self.pungi_cfg.write_config_files(topdir)

    def get_pungi_cmd(self, conf_topdir, compose, compose_dir=None):
        """
        Returns list with pungi command line arguments needed to generate
        the compose.
        :param str conf_topdir: Directory in which to look for Pungi
            configuration files.
        :param str targetdir: Target directory in which the compose should be
            generated.
        :param str compose_dir: If defined, overrides the Pungi compose_dir.
        :rtype: list
        :return: List of pungi command line arguments.
        """
        pungi_cmd = [
            conf.pungi_koji,
            "--config=%s" % os.path.join(conf_topdir, "pungi.json"),
            "--no-latest-link",
        ]

        if compose_dir:
            pungi_cmd.append("--compose-dir=%s" % compose_dir)
        else:
            pungi_cmd.append("--target-dir=%s" % compose.target_dir)

        if isinstance(self.pungi_cfg, RawPungiConfig):
            pungi_cmd += self.pungi_cfg.pungi_koji_args
        elif isinstance(self.pungi_cfg, PungiConfig):
            pungi_cmd += conf.pungi_koji_args
        else:
            raise RuntimeError("Unknown pungi config type to handle.")

        compose_type_to_arg = {
            "test": "--test",
            "ci": "--ci",
            "nightly": "--nightly",
            "production": "--production",
            "development": "--development",
        }
        compose_type = compose.compose_type or "test"

        # Add compose_type arg to pungi_cmd only if it's not set already
        # directly in the configuration.
        if not set(pungi_cmd).intersection(set(compose_type_to_arg.values())):
            # For unknown compose_type, fallback to --test to be safe.
            pungi_cmd.append(compose_type_to_arg.get(compose_type, "--test"))

        if compose.label:
            pungi_cmd.append("--label=%s" % str(compose.label))
        if compose.parent_pungi_compose_ids:
            for compose_id in compose.parent_pungi_compose_ids.split(" "):
                pungi_cmd.append("--parent-compose-id=%s" % str(compose_id))
        if compose.respin_of:
            pungi_cmd.append("--respin-of=%s" % str(compose.respin_of))

        if self.koji_event:
            pungi_cmd += ["--koji-event", str(self.koji_event)]
        if self.old_compose:
            pungi_cmd += ["--old-composes", self.old_compose]
        return pungi_cmd

    def _prepare_compose_dir(self, compose, conf):
        """
        Creates the compose directory and returns the full path to it.
        """
        compose_date = time.strftime("%Y%m%d", time.localtime())
        makedirs(compose.toplevel_dir)

        # If Compose Tracking Service is configured in the config file,
        # we skip the ComposeInfo creation completely and instead let
        # the Pungi to ask CTS to generate unique ComposeInfo.
        if conf.get("cts_url") and conf.get("cts_keytab"):
            return compose.toplevel_dir

        ci = ComposeInfo()
        ci.release.name = conf["release_name"]
        ci.release.short = conf["release_short"]
        ci.release.version = conf["release_version"]
        ci.release.is_layered = True if conf.get("base_product_name", "") else False
        ci.release.type = conf.get("release_type", "ga").lower()
        ci.release.internal = bool(conf.get("release_internal", False))
        if ci.release.is_layered:
            ci.base_product.name = conf["base_product_name"]
            ci.base_product.short = conf["base_product_short"]
            ci.base_product.version = conf["base_product_version"]
            ci.base_product.type = conf.get("base_product_type", "ga").lower()

        ci.compose.label = compose.label
        ci.compose.type = compose.compose_type or "test"
        ci.compose.date = compose_date
        ci.compose.respin = 0

        while True:
            ci.compose.id = ci.create_compose_id()
            existing_compose = Compose.query.filter(
                Compose.pungi_compose_id == ci.compose.id
            ).first()
            if not existing_compose:
                break
            ci.compose.respin += 1

        # Dump the compose info to work/global/composeinfo-base.json.
        work_dir = os.path.join(compose.toplevel_dir, "work", "global")
        makedirs(work_dir)
        ci.dump(os.path.join(work_dir, "composeinfo-base.json"))

        compose.pungi_compose_id = ci.compose.id

        return compose.toplevel_dir

    def run_locally(self, compose):
        """
        Runs local Pungi compose.
        """
        td = None
        compose_id_thread = None
        try:
            td = tempfile.mkdtemp()
            self._write_cfgs(td)

            # Load pungi configuration file.
            with open(os.path.join(td, "pungi.json")) as fd:
                pungi_conf = json.load(fd)

            compose_dir = self._prepare_compose_dir(compose, pungi_conf)
            self.pungi_cfg.validate(td, compose_dir)
            pungi_cmd = self.get_pungi_cmd(td, compose, compose_dir)

            # Commit the session to ensure that all the `compose` changes are
            # stored database before executing the compose and are not just
            # cached locally in the SQLAlchemy.
            db.session.commit()

            # If Compose Tracking Service is configured in the config file,
            # we need to get the Compose ID from Pungi in separate thread.
            if pungi_conf.get("cts_url") and pungi_conf.get("cts_keytab"):
                compose_id_thread = ReadComposeIdThread(compose)
                compose_id_thread.start()

            log_out_path = os.path.join(compose_dir, "pungi-stdout.log")
            log_err_path = os.path.join(compose_dir, "pungi-stderr.log")

            with open(log_out_path, "w") as log_out:
                with open(log_err_path, "w") as log_err:
                    odcs.server.utils.execute_cmd(
                        pungi_cmd,
                        cwd=td,
                        timeout=self.pungi_cfg.pungi_timeout,
                        stdout=log_out,
                        stderr=log_err,
                    )
        finally:
            if compose_id_thread:
                compose_id_thread.stop()
            try:
                if td is not None:
                    shutil.rmtree(td)
            except Exception as e:
                log.warning(
                    "Failed to remove temporary directory {!r}: {}".format(td, str(e))
                )

    def run(self, compose):
        """
        Runs the compose in Pungi. Blocks until the compose is done.
        Raises an exception if compose generation fails.

        :param models.Compose compose: Compose this Pungi process is running
            for.
        """
        self.run_locally(compose)


class PungiLogs(object):
    def __init__(self, compose):
        self.compose = compose

    @property
    def global_log_path(self):
        """
        Returns the path to pungi.global.log if it exists.
        """
        toplevel_dir = self.compose.toplevel_dir
        if not toplevel_dir:
            return None
        return os.path.join(toplevel_dir, "logs", "global", "pungi.global.log")

    @property
    def config_dump_path(self):
        """
        Returns path to Pungi config dump.
        """
        toplevel_dir = self.compose.toplevel_dir
        if not toplevel_dir:
            return None
        return os.path.join(toplevel_dir, "logs", "global", "config-dump.global.log")

    def _get_global_log_errors(self):
        """
        Helper method which opens the `self.global_log_path` and search for
        all errors in that log file.

        :rtype: list
        :return: List of error strings.
        """
        errors = []
        global_log_path = self.global_log_path
        if not global_log_path:
            return errors
        try:
            with open(global_log_path, "r") as global_log:
                error = ""
                for line in global_log:
                    idx = line.find("[ERROR   ]")
                    if idx == -1:
                        if error:
                            error += line
                            errors.append(error)
                            error = ""
                        continue
                    if error:
                        errors.append(error)
                    error = line[idx + len("[ERROR   ] ") :]
        except IOError:
            pass
        return errors

    def get_error_string(self):
        """
        Returns the string with errors parsed from Pungi logs.

        :rtype: str
        :return: String with errors parsed from Pungi logs.
        """
        errors = ""

        global_errors = self._get_global_log_errors()
        for error in global_errors:
            if error.startswith("Extended traceback in:"):
                continue
            errors += error
            if len(errors) > 2000:
                errors = errors[:2000]
                errors += " ...\n Too many errors, see Pungi log for more information."
                break

        if self.compose.on_default_target_dir:
            errors = errors.replace(conf.target_dir, conf.target_dir_url)
        return errors

    def get_config_dump(self):
        config_dump_path = self.config_dump_path
        if not config_dump_path:
            return None

        with open(config_dump_path, "r") as config_dump:
            return config_dump.read()
