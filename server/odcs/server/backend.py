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

import koji
import os
import threading
import shutil
import six
import productmd.compose
import productmd.common
from datetime import datetime, timedelta
from odcs.server import log, conf, app, db
from odcs.server.models import Compose, COMPOSE_STATES, COMPOSE_FLAGS
from odcs.server.pungi import Pungi, PungiConfig, PungiSourceType, PungiLogs
from odcs.server.pulp import Pulp
from odcs.server.cache import KojiTagCache
from concurrent.futures import ThreadPoolExecutor
import glob
import odcs.server.utils
import odcs.server.mbs
import defusedxml.ElementTree


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
            except Exception:
                log.exception("Exception in backend thread")
                try:
                    db.session.rollback()
                except Exception:
                    log.exception("Cannot rollback DB session")

            # If the self.stop has been called from the do_work, break earlier
            # so we don't wait on exit_cond.
            if self.exit:
                break

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


class RemoveExpiredComposesThread(BackendThread):
    """
    Thread used to remove old expired composes.
    """
    def __init__(self):
        """
        Creates new RemoveExpiredComposesThread instance.
        """
        super(RemoveExpiredComposesThread, self).__init__(10)

    def _remove_compose_dir(self, toplevel_dir):
        """
        Removes the compose toplevel_dir symlink together with the real
        path it points to.
        """

        # Be nice and don't fail when directory does not exist.
        if not os.path.exists(toplevel_dir):
            log.warn("Cannot remove directory %s, it does not exist",
                     toplevel_dir)
            return

        # If toplevel_dir is a symlink, remove the symlink and
        # its target. If toplevel_dir is normal directory, just
        # remove it using rmtree.
        if os.path.realpath(toplevel_dir) != toplevel_dir:
            targetpath = os.path.realpath(toplevel_dir)
            os.unlink(toplevel_dir)
            if os.path.exists(targetpath):
                shutil.rmtree(targetpath)
        else:
            shutil.rmtree(toplevel_dir)

    def _get_compose_id_from_path(self, path):
        """
        Returns the ID of compose from directory path in conf.target_dir.
        """
        parts = os.path.basename(path).split("-")
        while parts and parts[0] != "odcs":
            del parts[0]

        if not parts or len(parts) < 2 or not parts[1].isdigit():
            log.error("Directory %s is not valid compose directory", path)
            return None

        return int(parts[1])

    def do_work(self):
        """
        Checks for the expired composes and removes them.
        """
        log.info("Checking for expired composes")

        composes = Compose.composes_to_expire()
        for compose in composes:
            log.info("%r: Removing compose", compose)
            compose.state = COMPOSE_STATES["removed"]
            if compose.removed_by:
                state_reason = "Removed by {}.".format(compose.removed_by)
            else:
                state_reason = "Compose is expired."
            if compose.state_reason:
                compose.state_reason += "\n%s" % state_reason
            else:
                compose.state_reason = state_reason
            compose.time_removed = datetime.utcnow()
            db.session.commit()
            if not compose.reused_id:
                self._remove_compose_dir(compose.toplevel_dir)

        # In case of ODCS error, there might be left-over directories
        # belonging to already expired composes. Try to find them in the
        # target_dir.
        # At first, get all the directories in target_dir which are created
        # by ODCS.
        odcs_paths = []
        for dirname in ["latest-odcs-*", "odcs-*"]:
            path = os.path.join(conf.target_dir, dirname)
            odcs_paths += glob.glob(path)

        # Then try removing them if they are left there by some error.
        for path in odcs_paths:
            # Check that we are really going to remove a directory.
            if not os.path.isdir(path):
                continue

            compose_id = self._get_compose_id_from_path(path)
            if not compose_id:
                # Error logged in _get_compose_id_from_dirname already.
                continue

            composes = Compose.query.filter(Compose.id == compose_id).all()
            if not composes:
                log.info("Removing data of compose %d - it is not in "
                         "database: %s", compose_id, path)
                self._remove_compose_dir(path)
                continue

            compose = composes[0]
            if compose.state == COMPOSE_STATES["removed"]:
                log.info("%r: Removing data of compose - it has already "
                         "expired some time ago: %s", compose_id, path)
                self._remove_compose_dir(path)
                continue


def create_koji_session():
    """
    Creates and returns new koji_session based on the `conf.koji_profile`.
    """

    koji_module = koji.get_profile_module(conf.koji_profile)
    session_opts = {}
    for key in ('krbservice', 'timeout', 'keepalive',
                'max_retries', 'retry_interval', 'anon_retry',
                'offline_retry', 'offline_retry_interval',
                'debug', 'debug_xmlrpc', 'krb_rdns',
                'use_fast_upload'):
        value = getattr(koji_module.config, key, None)
        if value is not None:
            session_opts[key] = value
    koji_session = koji.ClientSession(koji_module.config.server,
                                      session_opts)
    return koji_session


def koji_get_inherited_tags(koji_session, tag, tags=None):
    """
    Returns list of ids of all tags the tag `tag` inherits from.
    """

    info = koji_session.getTag(tag)
    ids = [info["id"]]
    seen_tags = tags or set()
    inheritance_data = koji_session.getInheritanceData(tag)
    inheritance_data = [data for data in inheritance_data
                        if data['parent_id'] not in seen_tags]

    # Iterate over all the tags this tag inherits from.
    for inherited in inheritance_data:
        # Make a note to ourselves that we have seen this parent_tag.
        parent_tag_id = inherited['parent_id']
        seen_tags.add(parent_tag_id)

        # Get tag info for the parent_tag.
        info = koji_session.getTag(parent_tag_id)
        if info is None:
            log.error("Cannot get info about Koji tag %s", parent_tag_id)
            return []

        ids += koji_get_inherited_tags(koji_session, info['name'], seen_tags)

    return ids


def resolve_compose(compose):
    """
    Resolves various general compose values to the real ones. For example:
    - Sets the koji_event based on the current Koji event, so it can be used
      to generate the compose and we can find out if we can reuse that compose
      later
    - For MODULE PungiSourceType, resolves the modules without the "release"
      field to latest module release using PDC.
    """
    if compose.source_type == PungiSourceType.REPO:
        # We treat "revision" of local repo as koji_event for the simplicity.
        repomd = os.path.join(compose.source, "repodata", "repomd.xml")
        e = defusedxml.ElementTree.parse(repomd).getroot()
        revision = e.find("{http://linux.duke.edu/metadata/repo}revision").text
        compose.koji_event = int(revision)
    elif compose.source_type == PungiSourceType.KOJI_TAG:
        # If compose.koji_event is set, it means that we are regenerating
        # previous compose and we have to respect the previous koji_event to
        # get the same results.
        if not compose.koji_event:
            koji_session = create_koji_session()
            compose.koji_event = int(koji_session.getLastEvent()['id'])
    elif compose.source_type == PungiSourceType.MODULE:
        # Resolve the latest release of modules which do not have the release
        # string defined in the compose.source.
        mbs = odcs.server.mbs.MBS(conf)
        modules = compose.source.split(" ")

        specified_mbs_modules = []
        for module in modules:
            specified_mbs_modules += mbs.get_latest_modules(module)

        expand = not compose.flags & COMPOSE_FLAGS["no_deps"]
        new_mbs_modules = mbs.validate_module_list(specified_mbs_modules, expand=expand)

        uids = sorted(
            "{name}:{stream}:{version}:{context}".format(**m)
            for m in new_mbs_modules)
        compose.source = ' '.join(uids)


def get_reusable_compose(compose):
    """
    Returns the compose in the "done" state which contains the same artifacts
    and results as the compose `compose` and therefore could be reused instead
    of generating new one.
    """

    # RAW_CONFIG composes cannot reuse other composes, we cannot track input
    # for them.
    if compose.source_type == PungiSourceType.RAW_CONFIG:
        return None

    # Get all the active composes of the same source_type
    composes = db.session.query(Compose).filter(
        Compose.state == COMPOSE_STATES["done"],
        Compose.source_type == compose.source_type).all()

    for old_compose in composes:
        # Skip the old_compose in case it reuses another compose. In that case
        # the reused compose is also in composes list, so we won't miss it. We
        # don't want chain of composes reusing each other, because it would
        # break the time_to_expire handling.
        if old_compose.reused_id:
            continue

        packages = set(compose.packages.split(" ")) \
            if compose.packages else set()
        old_packages = set(old_compose.packages.split(" ")) \
            if old_compose.packages else set()
        if packages != old_packages:
            log.debug("%r: Cannot reuse %r - packages not same", compose,
                      old_compose)
            continue

        source = set(compose.source.split(" "))
        old_source = set(old_compose.source.split(" "))
        if source != old_source:
            log.debug("%r: Cannot reuse %r - sources not same", compose,
                      old_compose)
            continue

        if compose.flags != old_compose.flags:
            log.debug("%r: Cannot reuse %r - flags not same, %d != %d",
                      compose, old_compose, compose.flags,
                      old_compose.flags)
            continue

        if compose.results != old_compose.results:
            log.debug("%r: Cannot reuse %r - results not same, %d != %d",
                      compose, old_compose, compose.results,
                      old_compose.results)
            continue

        sigkeys = set(compose.sigkeys.split(" ")) \
            if compose.sigkeys else set()
        old_sigkeys = set(old_compose.sigkeys.split(" ")) \
            if old_compose.sigkeys else set()
        if sigkeys != old_sigkeys:
            log.debug("%r: Cannot reuse %r - sigkeys not same", compose,
                      old_compose)
            continue

        arches = set(compose.arches.split(" ")) \
            if compose.arches else set()
        old_arches = set(old_compose.arches.split(" ")) \
            if old_compose.arches else set()
        if arches != old_arches:
            log.debug("%r: Cannot reuse %r - arches not same", compose,
                      old_compose)
            continue

        if compose.source_type == PungiSourceType.KOJI_TAG:
            # For KOJI_TAG compose, check that all the inherited tags by our
            # Koji tag have not changed since previous old_compose.
            koji_session = create_koji_session()
            tags = koji_get_inherited_tags(koji_session, compose.source)
            if not tags:
                continue
            changed = koji_session.tagChangedSinceEvent(
                old_compose.koji_event, tags)
            if changed:
                log.debug("%r: Cannot reuse %r - one of the tags changed "
                          "since previous compose: %r", compose, old_compose,
                          tags)
                continue
        elif compose.koji_event != old_compose.koji_event:
            log.debug("%r: Cannot reuse %r - koji_events not same, %d != %d",
                      compose, old_compose, compose.koji_event,
                      old_compose.koji_event)
            continue

        return old_compose

    return None


def reuse_compose(compose, compose_to_reuse):
    """
    Changes the attribute of `compose` in a way it reuses
    the `compose_to_reuse`.
    """

    # Set the reuse_id
    compose.reused_id = compose_to_reuse.id
    # Set the time_to_expire to bigger value from both composes.
    compose.time_to_expire = max(compose.time_to_expire,
                                 compose_to_reuse.time_to_expire)
    compose_to_reuse.time_to_expire = compose.time_to_expire


def _write_repo_file(compose, data=None):
    """
    Writes main repo file for a resulting compose containing the `data`.
    If `data` is not provided, the default one pointing to pungi compose
    will be generated.
    """
    if not data:
        baseurl = os.path.join(
            compose.result_repo_url, "$basearch", "os")
        data = """[%s]
name=ODCS repository for compose %s
baseurl=%s
type=rpm-md
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1
""" % (compose.name, compose.name, baseurl)

    # Ensure the directory exists
    dirname = os.path.dirname(compose.result_repofile_path)
    odcs.server.utils.makedirs(dirname)

    with open(compose.result_repofile_path, "w") as f:
        f.write(data)


def generate_pulp_compose(compose):
    """
    Generates the compose of PULP type - this basically means only
    repo file pointing to data in pulp.
    """
    content_sets = compose.source.split(" ")

    pulp = Pulp(server_url=conf.pulp_server_url,
                username=conf.pulp_username,
                password=conf.pulp_password,
                compose=compose)

    repofile = ""
    repos = pulp.get_repos_from_content_sets(
        content_sets,
        compose.flags & COMPOSE_FLAGS["include_unpublished_pulp_repos"])
    if len(repos) != len(content_sets):
        err = "Failed to find all the content_sets %r in the Pulp, " \
            "found only %r" % (content_sets, repos.keys())
        log.error(err)
        raise ValueError(err)

    arches = set()
    sigkeys = set()
    for name in sorted(repos.keys()):
        repo_data = repos[name]
        url = repo_data["url"]
        r = """
[%s]
name=%s
baseurl=%s
enabled=1
gpgcheck=0
""" % (name, name, url)
        repofile += r
        arches = arches.union(repo_data["arches"])
        sigkeys = sigkeys.union(repo_data["sigkeys"])

    _write_repo_file(compose, repofile)

    compose.arches = " ".join(arches)
    compose.sigkeys = " ".join(sigkeys)
    compose.state = COMPOSE_STATES["done"]
    compose.state_reason = "Compose is generated successfully"
    log.info("%r: Compose done", compose)
    compose.time_done = datetime.utcnow()
    db.session.add(compose)
    db.session.commit()


def generate_pungi_compose(compose):
    """
    Generates the compose of KOJI, TAG, or REPO type using the Pungi tool.
    """
    koji_tag_cache = KojiTagCache()

    # Reformat the data from database
    packages = compose.packages
    if packages:
        packages = packages.split(" ")

    # Resolve the general data in the compose.
    resolve_compose(compose)

    # Check if we can reuse some existing compose instead of
    # generating new one.
    compose_to_reuse = get_reusable_compose(compose)
    if compose_to_reuse:
        log.info("%r: Reusing compose %r", compose, compose_to_reuse)
        reuse_compose(compose, compose_to_reuse)
    else:
        if compose.source_type == PungiSourceType.RAW_CONFIG:
            source_name, source_hash = compose.source.split("#")
            url_data = conf.raw_config_urls[source_name]
            # Do not override commit hash by hash from ODCS client if it is
            # hardcoded in the config file.
            if "commit" not in url_data:
                url_data["commit"] = source_hash
            pungi_cfg = url_data
        else:
            # Generate PungiConfig and run Pungi
            pungi_cfg = PungiConfig(compose.name, "1", compose.source_type,
                                    compose.source, packages=packages,
                                    sigkeys=compose.sigkeys,
                                    results=compose.results,
                                    arches=compose.arches.split(" "))
            if compose.flags & COMPOSE_FLAGS["no_deps"]:
                pungi_cfg.gather_method = "nodeps"
            if compose.flags & COMPOSE_FLAGS["no_inheritance"]:
                pungi_cfg.pkgset_koji_inherit = False

        koji_event = None
        if compose.source_type == PungiSourceType.KOJI_TAG:
            koji_event = compose.koji_event

        old_compose = None
        if koji_tag_cache.is_cached(compose):
            koji_tag_cache.reuse_cached(compose)
            old_compose = koji_tag_cache.cache_dir

        pungi = Pungi(pungi_cfg, koji_event, old_compose)
        pungi.run(compose)

        _write_repo_file(compose)

    # Raises an exception if invalid
    validate_pungi_compose(compose)

    # If there is no exception generated by the pungi.run() and if
    # validation didn't fail, then we know the compose has been
    # successfully generated.
    compose.state = COMPOSE_STATES["done"]
    compose.state_reason = "Compose is generated successfully"
    log.info("%r: Compose done", compose)
    compose.time_done = datetime.utcnow()
    db.session.add(compose)
    db.session.commit()

    koji_tag_cache.update_cache(compose)


def validate_pungi_compose(compose):
    """
    Validate the compose is generated by pungi as expected.
    """
    # the requested packages should be present in the generated compose
    if compose.packages:
        packages = compose.packages.split()
        pungi_compose = productmd.compose.Compose(compose.toplevel_dir)
        rm = pungi_compose.rpms.rpms
        rpm_nevras = []
        for variant in rm:
            for arch in rm[variant]:
                for srpm_nevra, data in six.iteritems(rm[variant][arch]):
                    for rpm_nevra, data in six.iteritems(rm[variant][arch][srpm_nevra]):
                        if data['category'] == 'source':
                            continue
                        rpm_nevras.append(rpm_nevra)
        rpms = set([productmd.common.parse_nvra(n)['name'] for n in rpm_nevras])
        not_found = []
        for pkg in packages:
            if pkg not in rpms:
                not_found.append(pkg)
        if not_found:
            msg = "The following requested packages are not present in the generated compose: %s." % \
                  " ".join(not_found)
            log.error(msg)
            raise RuntimeError(msg)


def generate_compose(compose_id, lost_compose=False):
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

            if compose.source_type == PungiSourceType.PULP:
                # Pulp compose is special compose not generated by Pungi.
                # The ODCS in this case just creates .repo file which points
                # to composes generated by pulp/pub.
                generate_pulp_compose(compose)
            else:
                generate_pungi_compose(compose)
        except Exception as e:
            # Something went wrong, log the exception and update the compose
            # state in database.
            if compose:
                log.exception("%r: Error while generating compose", compose)
            else:
                log.exception("Error while generating compose %d", compose_id)
            compose.state = COMPOSE_STATES["failed"]
            compose.time_done = datetime.utcnow()

            pungi_logs = PungiLogs(compose)
            compose.state_reason = "Error while generating compose: %s\n" % str(e)
            compose.state_reason += pungi_logs.get_error_string()

            db.session.add(compose)
            db.session.commit()

        compose = Compose.query.filter(Compose.id == compose_id).one()

        koji_tag_cache = KojiTagCache()
        koji_tag_cache.cleanup_reused(compose)
        # consolidate duplicate files in compose target dir
        if compose and compose.reused_id is None and compose.source_type != PungiSourceType.PULP:
            try:
                log.info("Running hardlink to consolidate duplicate files in compose target dir")
                odcs.server.utils.hardlink(conf.target_dir)
            except Exception as ex:
                # not fail, just show warning message
                log.warn("Error while running hardlink on system: %s" % str(ex), exc_info=True)


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
        # ThreadPool to execute composes which calls "pungi" process.
        self.executor = ThreadPoolExecutor(conf.num_concurrent_pungi)
        # Threadpool to execute Pulp composes. These composes take just
        # few seconds and do just single HTTP call to Pulp, so there is
        # no need to put them into the same queue as Pungi based composes.
        self.pulp_executor = ThreadPoolExecutor(2)

        # List of composes which are being currently generated by this ODCS
        # instance.
        self.currently_generating = []

    def generate_new_compose(self, compose):
        """
        Adds the compose to queue of composes to generate, so
        the ThreadPoolExecutor can start working on it.
        """
        compose.state = COMPOSE_STATES["generating"]
        compose.state_reason = "Compose thread started"
        db.session.add(compose)
        db.session.commit()
        self.currently_generating.append(compose.id)
        if compose.source_type == PungiSourceType.PULP:
            self.pulp_executor.submit(generate_compose, compose.id)
        else:
            self.executor.submit(generate_compose, compose.id)

    def generate_new_composes(self):
        """
        Gets all the composes in "wait" state. Generates them using Pungi
        by calling `generate_compose(...)` in ThreadPoolExecutor.
        """
        composes = Compose.query.filter(
            Compose.state == COMPOSE_STATES["wait"]).all()

        for compose in composes:
            log.info("%r: Going to start compose generation.", compose)
            self.generate_new_compose(compose)

    def pickup_waiting_composes(self):
        """
        Gets all the composes in "wait" state and starts generating them.

        This method exists to pro-actively generate "wait" composes in case
        the UMB message from frontend to backend is lost from whatever reason.
        """
        # Composes transition from 'wait' to 'generating' quite fast.
        # The frontend changes the state of compose to 'wait', sends a message
        # to the bus and once some backend receives it, it moves it to
        # 'generating'. This should not take more than 3 minutes, so that's
        # the limit we will use to find out the stuck composes.
        limit = datetime.utcnow() - timedelta(minutes=3)
        # We don't want to be to greedy here, because there are other backends
        # which can handle the lost composes too later, so just take few of
        # them in each run in each backend to balance the load.
        composes = Compose.query.filter(
            Compose.state == COMPOSE_STATES["wait"],
            Compose.time_submitted < limit).order_by(
                Compose.id).limit(4).all()

        for compose in composes:
            log.info("%r: Going to regenerate compose stuck in 'wait' "
                     "state.", compose)
            self.generate_new_compose(compose)

    def generate_lost_composes(self):
        """
        Gets all the composes in "generating" state and continues with
        the generation process.

        This method is here to handle situation where the ODCS is restarted
        in the middle of compose generation.
        """
        composes = Compose.query.filter(
            Compose.state == COMPOSE_STATES["generating"]).all()

        for compose in composes:
            if compose.id in self.currently_generating:
                # We already have a thread working on this compose.
                continue

            log.info("%r: Going to regenerate lost compose.", compose)
            self.generate_new_compose(compose)

    def refresh_currently_generating(self):
        """
        Checks the status of all composes in self.currently_generating
        and removes those which have been already done from this list.
        """

        new_currently_generating_list = []
        for compose_id in self.currently_generating:
            compose = Compose.query.filter(Compose.id == compose_id).one()
            if compose.state != COMPOSE_STATES["generating"]:
                continue

            new_currently_generating_list.append(compose_id)
        self.currently_generating = new_currently_generating_list

    def do_work(self):
        """
        Gets all the composes in "wait" state. Generates them using Pungi
        by calling `generate_compose(...)` in ThreadPoolExecutor.
        """
        self.generate_lost_composes()
        self.generate_new_composes()
        self.refresh_currently_generating()


def run_backend():
    """
    Runs the backend.
    """
    while True:
        remove_expired_composes_thread = RemoveExpiredComposesThread()
        composer_thread = ComposerThread()
        try:
            remove_expired_composes_thread.start()
            composer_thread.start()
            remove_expired_composes_thread.join()
            composer_thread.join()
        except KeyboardInterrupt:
            remove_expired_composes_thread.stop()
            composer_thread.stop()
            remove_expired_composes_thread.join()
            composer_thread.join()
            return 0
        except Exception:
            log.exception("Exception in backend")
            remove_expired_composes_thread.stop()
            composer_thread.stop()
            remove_expired_composes_thread.join()
            composer_thread.join()

    return 0
