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

import errno
import itertools
from textwrap import dedent

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
from odcs.server.pungi import (
    Pungi,
    PungiConfig,
    PungiSourceType,
    PungiLogs,
    RawPungiConfig,
)
from odcs.server.pulp import Pulp
from odcs.server.cache import KojiTagCache
from odcs.server.pungi_compose import PungiCompose
from concurrent.futures import ThreadPoolExecutor
import glob
import odcs.server.utils
import odcs.server.mbs
import defusedxml.ElementTree

# Cache last event for each tag since that a compose was generated from that
# tag.
# This is a mapping from tag name to koji event id. For example,
# {
#     'tag1': 123456,
#     'tag2': 123476,
# }
LAST_EVENTS_CACHE = {}


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
        raise NotImplementedError("do_work() method not implemented")

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
        self._rmtree_errors = {}

    def _on_rmtree_error(self, function, path, excinf):
        """
        Helper method passed to `shutil.rmtree` as `onerror` kwarg which stores
        the rmtree errors in the `self._rmtree_errors` dict and allows the rmtree
        to continue removing other files.

        The errors stored in `self._rmtree_errors` are grouped by the
        `dirname(path)`. This is needed to not print thousands of log lines in
        case when directory with wrong permissions contain thousands of files.
        """
        if function == os.remove:
            d = os.path.dirname(path)
        else:
            d = path
        if d in self._rmtree_errors:
            # This directory has been already handled.
            return
        exception_value = excinf[1]
        self._rmtree_errors[d] = repr(exception_value)

    def _remove_compose_dir(self, toplevel_dir):
        """
        Removes the compose toplevel_dir symlink together with the real
        path it points to.
        """

        # Be nice and don't fail when directory does not exist.
        if not os.path.exists(toplevel_dir):
            log.warning("Cannot remove directory %s, it does not exist", toplevel_dir)
            return

        # Temporary dictionary to store errors from `self._on_rmtree_error`.
        self._rmtree_errors = {}

        # If toplevel_dir is a symlink, remove the symlink and
        # its target. If toplevel_dir is normal directory, just
        # remove it using rmtree.
        if os.path.realpath(toplevel_dir) != toplevel_dir:
            targetpath = os.path.realpath(toplevel_dir)
            os.unlink(toplevel_dir)
            if os.path.exists(targetpath):
                shutil.rmtree(targetpath, onerror=self._on_rmtree_error)
        else:
            shutil.rmtree(toplevel_dir, onerror=self._on_rmtree_error)

        for path, error in self._rmtree_errors.items():
            log.warning("Cannot remove some files in %s: %r" % (path, error))

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
            # Check if target_dir is accessible on this backend and if not, skip it.
            if not os.path.exists(compose.target_dir):
                continue

            # Do not remove the latest successfull compose.
            if get_latest_symlink(compose):
                log.info(
                    "%r: Not removing compose, the latest-* symlink points to it.",
                    compose,
                )
                continue

            log.info("%r: Removing compose", compose)
            if compose.removed_by:
                state_reason = "Removed by {}.".format(compose.removed_by)
            else:
                state_reason = "Compose is expired."
            if compose.state_reason:
                state_reason = "{}\n{}".format(compose.state_reason, state_reason)
            compose.transition(COMPOSE_STATES["removed"], state_reason)
            if not compose.reused_id:
                self._remove_compose_dir(compose.toplevel_dir)
                remove_compose_symlink(compose)

                # Remove the `odcs-$COMPOSE_ID` symlink if it's there.
                symlink = os.path.join(compose.target_dir, compose.name)
                if os.path.exists(symlink) and os.path.realpath(symlink) != symlink:
                    os.unlink(symlink)

        # In case of ODCS error, there might be left-over directories
        # belonging to already expired composes. Try to find them in the
        # target_dir.
        # At first, get all the directories in target_dir which are created
        # by ODCS.
        odcs_paths = []
        for dirname in ["latest-odcs-*", "odcs-*"]:
            for target_dir in [conf.target_dir] + list(conf.extra_target_dirs.values()):
                path = os.path.join(target_dir, dirname)
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
                log.info(
                    "Removing data of compose %d - it is not in " "database: %s",
                    compose_id,
                    path,
                )
                self._remove_compose_dir(path)
                continue

            compose = composes[0]
            if compose.state == COMPOSE_STATES["removed"]:
                log.info(
                    "%r: Removing data of compose - it has already "
                    "expired some time ago: %s",
                    compose_id,
                    path,
                )
                self._remove_compose_dir(path)
                continue

        # Remove old Koji tag data from Koji tag cache.
        KojiTagCache.remove_old_koji_tag_cache_data()


def create_koji_session():
    """
    Creates and returns new koji_session based on the `conf.koji_profile`.
    """

    koji_module = koji.get_profile_module(conf.koji_profile)
    session_opts = {}
    for key in (
        "krbservice",
        "timeout",
        "keepalive",
        "max_retries",
        "retry_interval",
        "anon_retry",
        "offline_retry",
        "offline_retry_interval",
        "debug",
        "debug_xmlrpc",
        "krb_rdns",
        "use_fast_upload",
    ):
        value = getattr(koji_module.config, key, None)
        if value is not None:
            session_opts[key] = value
    koji_session = koji.ClientSession(koji_module.config.server, session_opts)
    return koji_session


def koji_get_inherited_tags(koji_session, tag, tags=None):
    """
    Returns list of ids of all tags the tag `tag` inherits from.
    """

    info = koji_session.getTag(tag)
    if not info:
        raise ValueError("Unknown Koji tag %s." % tag)
    ids = [info["id"]]
    seen_tags = tags or set()
    inheritance_data = koji_session.getInheritanceData(tag)
    inheritance_data = [
        data for data in inheritance_data if data["parent_id"] not in seen_tags
    ]

    # Iterate over all the tags this tag inherits from.
    for inherited in inheritance_data:
        # Make a note to ourselves that we have seen this parent_tag.
        parent_tag_id = inherited["parent_id"]
        seen_tags.add(parent_tag_id)

        # Get tag info for the parent_tag.
        info = koji_session.getTag(parent_tag_id)
        if info is None:
            log.error("Cannot get info about Koji tag %s", parent_tag_id)
            return []

        ids += koji_get_inherited_tags(koji_session, info["name"], seen_tags)

    return ids


def tag_changed(koji_session, tag, koji_event):
    """
    Check if tag and its parents in the inheritance have changed since a
    particular koji event

    :param koji_session: instance of :class:`ClientSession`.
    :param str tag: tag name.
    :param int koji_event: the koji event id.
    :return: True if changed, otherwise False.
    :rtype: bool
    """
    tags = koji_get_inherited_tags(koji_session, tag)
    return koji_session.tagChangedSinceEvent(koji_event, tags)


def resolve_compose(compose):
    """
    Resolves various general compose values to the real ones. For example:
    - Sets the koji_event based on the current Koji event, so it can be used
      to generate the compose and we can find out if we can reuse that compose
      later
    - For MODULE PungiSourceType, resolves the modules without the "release"
      field to latest module release using MBS.
    """
    if compose.source_type == PungiSourceType.REPO:
        # We treat "revision" of local repo as koji_event for the simplicity.
        repomd = os.path.join(compose.source, "repodata", "repomd.xml")
        e = defusedxml.ElementTree.parse(repomd).getroot()
        revision = e.find("{http://linux.duke.edu/metadata/repo}revision").text
        compose.koji_event = int(revision)
    elif compose.source_type == PungiSourceType.KOJI_TAG:
        global LAST_EVENTS_CACHE
        koji_session = create_koji_session()
        # If compose.koji_event is set, it means that we are regenerating
        # previous compose and we have to respect the previous koji_event to
        # get the same results.
        if not compose.koji_event:
            if compose.source not in LAST_EVENTS_CACHE:
                event_id = int(koji_session.getLastEvent()["id"])
            elif tag_changed(
                koji_session, compose.source, LAST_EVENTS_CACHE[compose.source]
            ):
                event_id = int(koji_session.getLastEvent()["id"])
            else:
                event_id = LAST_EVENTS_CACHE[compose.source]
                log.info(
                    "Reuse koji event %s to generate compose %s from source %s",
                    event_id,
                    compose.id,
                    compose.source,
                )
            compose.koji_event = event_id
            # event_id could be a new koji event ID. Cache it for next potential
            # reuse for same tag.
            LAST_EVENTS_CACHE[compose.source] = event_id
    elif compose.source_type == PungiSourceType.MODULE:

        # Resolve the latest release of modules which do not have the release
        # string defined in the compose.source.
        mbs = odcs.server.mbs.MBS(conf)
        modules = compose.source.split(" ")

        include_done = compose.flags & COMPOSE_FLAGS["include_done_modules"]
        specified_mbs_modules = []
        for module in modules:
            # In case the module is defined by complete NSVC, include it in a compose
            # even if it is in "done" state, because submitter directly asked for this
            # NSVC.
            is_complete_nsvc = module.count(":") == 3
            specified_mbs_modules += mbs.get_latest_modules(
                module,
                include_done or is_complete_nsvc,
                compose.base_module_br_name,
                compose.base_module_br_stream,
                compose.base_module_br_stream_version_lte,
                compose.base_module_br_stream_version_gte,
            )

        expand = not compose.flags & COMPOSE_FLAGS["no_deps"]
        new_mbs_modules = mbs.validate_module_list(specified_mbs_modules, expand=expand)

        uids = sorted(
            "{name}:{stream}:{version}:{context}".format(**m)
            for m in new_mbs_modules
            if m["name"] not in conf.base_module_names
        )
        compose.source = " ".join(uids)
    elif compose.source_type == PungiSourceType.PUNGI_COMPOSE:
        external_compose = PungiCompose(compose.source)
        rpms_data = external_compose.get_rpms_data()

        # If there is None in the sigkeys, it means unsigned packages are
        # allowed. The sigkeys in the `compose.sigkeys` are sorted by
        # preference and unsigned packages should be tried as last.
        # Therefore we need to remove None from `sigkeys` and handle
        # it as last element in `compose.sigkeys`.
        if None in rpms_data["sigkeys"]:
            allow_unsigned = True
            # Remove None from sigkeys.
            rpms_data["sigkeys"].remove(None)
        else:
            allow_unsigned = False
        compose.sigkeys = " ".join(rpms_data["sigkeys"])
        if allow_unsigned:
            # Unsigned packages are allowed by white-space in the end of
            # `compose.sigkeys`.
            compose.sigkeys += " "

        compose.arches = " ".join(rpms_data["arches"])
        compose.builds = " ".join(rpms_data["builds"].keys())

        packages = set()
        for rpms in rpms_data["builds"].values():
            for rpm_nevra in rpms:
                packages.add(productmd.common.parse_nvra(rpm_nevra)["name"])
        compose.packages = " ".join(packages)
    elif compose.source_type == PungiSourceType.RAW_CONFIG:
        # Set the Koji event id if it is not specified in compose request.
        if not compose.koji_event:
            koji_session = create_koji_session()
            compose.koji_event = int(koji_session.getLastEvent()["id"])


def _raise_if_compose_attr_different(c1, c2, attr_name, string_list=False):
    """
    Helper function for `get_reusable_compose` which compares the value of
    attribute `attr_name` of composes `c1` and `c2` and raises ValueError
    exception if they are not the same.

    if `string_list` is True, the value is treated as white-space separated
    list stored in string.
    """
    c1_value = getattr(c1, attr_name)
    c2_value = getattr(c2, attr_name)

    if string_list:
        c1_value = set(c1_value.split(" ")) if c1_value else set()
        c2_value = set(c2_value.split(" ")) if c2_value else set()

    if c1_value != c2_value:
        raise ValueError("%s not same (%r != %r)" % (attr_name, c1_value, c2_value))


def get_reusable_compose(compose):
    """
    Returns the compose in the "done" state which contains the same artifacts
    and results as the compose `compose` and therefore could be reused instead
    of generating new one.

    :param models.Compose compose: Instance of models.Compose.
    """

    if compose.flags & COMPOSE_FLAGS["no_reuse"]:
        return None

    # RAW_CONFIG composes cannot reuse other composes, we cannot track input
    # for them.
    if compose.source_type == PungiSourceType.RAW_CONFIG:
        return None

    # Get all the active composes of the same source_type
    composes = (
        db.session.query(Compose)
        .filter(
            Compose.state == COMPOSE_STATES["done"],
            Compose.source_type == compose.source_type,
        )
        .all()
    )

    for old_compose in composes:
        # Skip the old_compose in case it reuses another compose. In that case
        # the reused compose is also in composes list, so we won't miss it. We
        # don't want chain of composes reusing each other, because it would
        # break the time_to_expire handling.
        if old_compose.reused_id:
            continue

        try:
            string_list_attrs = [
                "packages",
                "builds",
                "sigkeys",
                "arches",
                "lookaside_repos",
                "multilib_arches",
                "modular_koji_tags",
                "scratch_modules",
                "modules",
                "scratch_build_tasks",
                "parent_pungi_compose_ids",
            ]
            for attr in string_list_attrs:
                _raise_if_compose_attr_different(compose, old_compose, attr, True)
            attrs = [
                "source",
                "flags",
                "results",
                "module_defaults_url",
                "respin_of",
                "target_dir",
                "multilib_method",
            ]
            for attr in attrs:
                _raise_if_compose_attr_different(compose, old_compose, attr, False)
        except ValueError as e:
            log.debug("%r: Cannot reuse %r - %s", compose, old_compose, str(e))
            continue

        # In case of compose renewal, the compose.koji_event will be actually
        # lower than the "old_compose"'s one - the `compose` might have been for
        # example submitted 1 year ago, so koji_event will be one year old.
        # But the `old_compose` was submitted few days ago at max.
        # In this case, we must never reuse the newer compose for old one.
        if (
            compose.koji_event
            and old_compose.koji_event
            and compose.koji_event < old_compose.koji_event
        ):
            log.debug(
                "%r: Cannot reuse %r - koji_event of current compose "
                "is lower than koji_event of old compose.",
                compose,
                old_compose,
            )
            continue

        if compose.source_type == PungiSourceType.KOJI_TAG:
            # For KOJI_TAG compose, check that all the inherited tags by our
            # Koji tag have not changed since previous old_compose.
            koji_session = create_koji_session()
            if tag_changed(koji_session, compose.source, old_compose.koji_event):
                log.debug(
                    "%r: Cannot reuse %r - one of the tags changed "
                    "since previous compose.",
                    compose,
                    old_compose,
                )
                continue
        elif compose.koji_event != old_compose.koji_event:
            log.debug(
                "%r: Cannot reuse %r - koji_events not same, %d != %d",
                compose,
                old_compose,
                compose.koji_event,
                old_compose.koji_event,
            )
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
    compose.time_to_expire = max(
        compose.time_to_expire, compose_to_reuse.time_to_expire
    )
    # NOTE: reuse_compose is only called by generate_pungi_compose at this
    # moment. This change will be committed when compose state is transitted,
    # which will call session's commit. If this method is called from somewhere
    # else in the future, be careful to manage the commit.
    compose_to_reuse.time_to_expire = compose.time_to_expire


def _write_repo_file(compose, data=None):
    """
    Writes main repo file for a resulting compose containing the `data`.
    If `data` is not provided, the default one pointing to pungi compose
    will be generated.
    """
    if not data:
        baseurl = os.path.join(compose.result_repo_url, "$basearch", "os")
        data = """[%s]
name=ODCS repository for compose %s
baseurl=%s
type=rpm-md
skip_if_unavailable=False
gpgcheck=0
repo_gpgcheck=0
enabled=1
enabled_metadata=1
""" % (
            compose.name,
            compose.name,
            baseurl,
        )

    # Ensure the directory exists
    dirname = os.path.dirname(compose.result_repofile_path)
    odcs.server.utils.makedirs(dirname)

    with open(compose.result_repofile_path, "w") as f:
        f.write(data)


def generate_pulp_compose(compose):
    """
    Generates the "compose" of PULP type - this basically means only
    repo file pointing to data in pulp.
    """
    content_sources = compose.source.split(" ")

    pulp = Pulp(
        server_url=conf.pulp_server_url,
        username=conf.pulp_username,
        password=conf.pulp_password,
        compose=compose,
    )
    include_unpublished_repos = (
        compose.flags & COMPOSE_FLAGS["include_unpublished_pulp_repos"]
    )

    repos = pulp.get_repos_from_content_sets(content_sources, include_unpublished_repos)

    found_repo_ids = set(item["id"] for item in itertools.chain(*list(repos.values())))
    remaining_sources = set(content_sources) - set(repos.keys()) - set(found_repo_ids)

    direct_repos = {}
    if remaining_sources:
        direct_repos = pulp.get_repos_by_id(
            remaining_sources, include_unpublished_repos
        )
        remaining_sources -= set(direct_repos.keys())

        if remaining_sources:
            found_content_sets = sorted(set(content_sources) - remaining_sources)
            err = "Failed to find all the source(s) %r in Pulp, found only %r" % (
                content_sources,
                found_content_sets,
            )
            ignore_absent_pulp_repos = (
                compose.flags & COMPOSE_FLAGS["ignore_absent_pulp_repos"]
            )
            if ignore_absent_pulp_repos:
                log.info(err)
                # Update the source in the compose. This ensures the source matches
                # what is actually in the compose. However it makes it invisible
                # that user actually requested something else.
                compose.source = " ".join(found_content_sets)
            else:
                log.error(err)
                raise ValueError(err)

    merged_repos = pulp.merge_repos_by_arch(repos)
    merged_repos.update(direct_repos)

    repofile = ""
    arches = set()
    sigkeys = set()
    for name in sorted(merged_repos.keys()):
        repo_data = merged_repos[name]
        url = repo_data["url"]
        r = dedent(
            """
            [{0}]
            name={0}
            baseurl={1}
            enabled=1
            gpgcheck=0
            """.format(
                name, url
            )
        )
        repofile += r
        arches = arches.union(repo_data["arches"])
        sigkeys = sigkeys.union(repo_data["sigkeys"])

    if not merged_repos:
        log.info("Creating empty repository for %r", compose)
        arches = conf.allowed_arches
        odcs.server.utils.write_empty_repo(compose, arches)

    _write_repo_file(compose, repofile)

    compose.arches = " ".join(arches)
    compose.sigkeys = " ".join(sigkeys)
    compose.transition(COMPOSE_STATES["done"], "Compose is generated successfully")
    log.info("%r: Compose done", compose)


def generate_compose_symlink(compose):
    """
    Generates symlink(s) for compose based on its `compose.pungi_compose_id`.

    It generates following symlinks pointing to the compose:
      - $compose.target_dir/$compose.compose_type/$compose.pungi_compose_id
      - $compose.target_dir/$compose.compose_type/latest-$name-version

    If the latest-* symlink exists, it is replaced with new one pointing to
    the `composes`.
    """
    symlink_dir = os.path.join(compose.target_dir, compose.compose_type)
    odcs.server.utils.makedirs(symlink_dir)

    # Generate the non-latest symlink.
    compose_dir = os.path.relpath(compose.toplevel_dir, symlink_dir)
    symlink = os.path.join(symlink_dir, compose.pungi_compose_id)
    log.info("%r: Generating %s symlink.", compose, symlink)
    os.symlink(compose_dir, symlink)

    # Generate the latest-* symlink.
    latest_name = "latest-%s" % "-".join(compose.pungi_compose_id.split("-")[:2])
    symlink = os.path.join(symlink_dir, latest_name)
    try:
        os.unlink(symlink)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    log.info("%r: Generating %s symlink.", compose, symlink)
    os.symlink(compose_dir, symlink)


def get_latest_symlink(compose):
    """
    Returns the latest-* symlink associated with this compose or None
    if it does not exists.
    """
    # Ignore old composes which do not have the compose_type and pungi_compose_id set.
    if not compose.compose_type or not compose.pungi_compose_id:
        return None

    symlink_dir = os.path.join(compose.target_dir, compose.compose_type)
    symlink = os.path.join(symlink_dir, compose.pungi_compose_id)
    latest_name = "latest-%s" % "-".join(compose.pungi_compose_id.split("-")[:2])
    latest_symlink = os.path.join(symlink_dir, latest_name)

    # Return Non if `latest_symlink` points to the different dir than `symlink`.
    if os.path.realpath(symlink) != os.path.realpath(latest_symlink):
        return None

    return latest_symlink


def remove_compose_symlink(compose):
    """
    Removes non-latest symlink generated by the `generate_compose_symlink`.
    """
    # Do not try to remove symlinks from old composes which do not have
    # the compose_type and pungi_compose_id set.
    if not compose.compose_type or not compose.pungi_compose_id:
        return

    symlink_dir = os.path.join(compose.target_dir, compose.compose_type)
    symlink = os.path.join(symlink_dir, compose.pungi_compose_id)
    latest_symlink = get_latest_symlink(compose)

    # Remove non-latest symlink.
    log.info("%r: Removing %s symlink.", compose, symlink)
    try:
        os.unlink(symlink)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

    # Remove latest symlink.
    if latest_symlink:
        log.info("%r: Removing %s symlink.", compose, latest_symlink)
        try:
            os.unlink(latest_symlink)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise


def generate_pungi_compose(compose):
    """
    Generates the compose of KOJI, TAG, or REPO type using the Pungi tool.

    :param models.Compose compose: Instance of models.Compose.
    """
    koji_tag_cache = KojiTagCache(compose)

    # Resolve the general data in the compose.
    resolve_compose(compose)

    # Reformat the data from database
    packages = compose.packages
    if packages:
        packages = packages.split(" ")
    builds = compose.builds
    if builds:
        builds = builds.split(" ")

    # Check if we can reuse some existing compose instead of
    # generating new one.
    compose_to_reuse = get_reusable_compose(compose)
    if compose_to_reuse:
        log.info("%r: Reusing compose %r", compose, compose_to_reuse)
        reuse_compose(compose, compose_to_reuse)
    else:
        if compose.source_type == PungiSourceType.RAW_CONFIG:
            pungi_cfg = RawPungiConfig(compose)
        else:
            # Generate PungiConfig and run Pungi
            if compose.multilib_arches:
                multilib_arches = compose.multilib_arches.split(" ")
            else:
                multilib_arches = None
            pungi_cfg = PungiConfig(
                compose.name,
                "1",
                compose.source_type,
                compose.source,
                packages=packages,
                sigkeys=compose.sigkeys,
                results=compose.results,
                arches=compose.arches.split(" "),
                multilib_arches=multilib_arches,
                multilib_method=compose.multilib_method,
                builds=builds,
                flags=compose.flags,
                lookaside_repos=compose.lookaside_repos,
                modular_koji_tags=compose.modular_koji_tags,
                module_defaults_url=compose.module_defaults_url,
                scratch_modules=compose.scratch_modules,
                scratch_build_tasks=compose.scratch_build_tasks,
            )
            if compose.flags & COMPOSE_FLAGS["no_deps"]:
                pungi_cfg.gather_method = "nodeps"
            if compose.flags & COMPOSE_FLAGS["no_inheritance"]:
                pungi_cfg.pkgset_koji_inherit = False
            if compose.flags & COMPOSE_FLAGS["no_reuse"]:
                pungi_cfg.pkgset_allow_reuse = False

        koji_event = None
        if compose.source_type == PungiSourceType.KOJI_TAG:
            koji_event = compose.koji_event

        old_compose = None
        if koji_tag_cache.is_cached(compose) and pungi_cfg.pkgset_allow_reuse:
            koji_tag_cache.reuse_cached(compose)
            old_compose = koji_tag_cache.cache_dir

        # For Raw config composes, ODCS generates symlinks named according
        # to Pungi COMPOSE_ID. We can use directory with these symlinks to
        # find out previous old compose.
        if compose.source_type == PungiSourceType.RAW_CONFIG:
            old_compose = os.path.join(compose.target_dir, compose.compose_type)

        pungi = Pungi(compose.id, pungi_cfg, koji_event, old_compose)
        pungi.run(compose)

        # Write the Compose.result_repofile_path. This makes sense only for
        # non raw_config composes, because we have no idea what variants
        # do exist for raw_config composes.
        if compose.source_type != PungiSourceType.RAW_CONFIG:
            _write_repo_file(compose)

    # Raises an exception if invalid
    validate_pungi_compose(compose)

    # Generate symlinks pointing to latest build of raw_config compose.
    if compose.source_type == PungiSourceType.RAW_CONFIG:
        generate_compose_symlink(compose)
        if compose.compose_type in ["production", "development"]:
            pungi_logs = PungiLogs(compose)
            config_dump = pungi_logs.get_config_dump()
            if not config_dump:
                msg = "%r: Cannot load Pungi config dump." % compose
                log.error(msg)
                raise RuntimeError(msg)
            compose.pungi_config_dump = config_dump

    # If there is no exception generated by the pungi.run() and if
    # validation didn't fail, then we know the compose has been
    # successfully generated.
    compose.transition(COMPOSE_STATES["done"], "Compose is generated successfully")
    log.info("%r: Compose done", compose)

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
                        if data["category"] == "source":
                            continue
                        rpm_nevras.append(rpm_nevra)
        rpms = set([productmd.common.parse_nvra(n)["name"] for n in rpm_nevras])
        not_found = []
        for pkg in packages:
            if pkg not in rpms:
                not_found.append(pkg)
        if not_found:
            msg = (
                "The following requested packages are not present in the generated compose: %s."
                % " ".join(not_found)
            )
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

            state_reason = "Error while generating compose: {}".format(str(e))

            try:
                pungi_logs = PungiLogs(compose)
                state_reason += "\n{}".format(pungi_logs.get_error_string())
            except Exception:
                log.exception("Exception raised when getting Pungi logs.")

            # Be nice to end user and replace paths to logs or other files with URL
            # accessible to the user.
            if compose.on_default_target_dir:
                state_reason = state_reason.replace(
                    conf.target_dir, conf.target_dir_url
                )
            compose.transition(COMPOSE_STATES["failed"], state_reason)

        compose = Compose.query.filter(Compose.id == compose_id).one()

        koji_tag_cache = KojiTagCache(compose)
        koji_tag_cache.cleanup_reused(compose)

        # Commit the session to ensure that database transaction is closed and
        # does not remain in Idle state acquiring the table lock.
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
        compose.transition(COMPOSE_STATES["generating"], "Compose thread started")

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
        composes = Compose.query.filter(Compose.state == COMPOSE_STATES["wait"]).all()

        for compose in composes:
            log.info("%r: Going to start compose generation.", compose)
            self.generate_new_compose(compose)

    def fail_lost_generating_composes(self):
        """
        Fails the composes in `generating` state in case they are in this
        state for longer than `2 * conf.pungi_timeout`. Because composes
        can be generating only for `conf.pungi_timeout` seconds, this is enough
        time to generate any compose.
        """
        max_generating_time = 2 * conf.pungi_timeout
        now = datetime.utcnow()
        too_old_datetime = now - timedelta(seconds=max_generating_time)

        # Get composes which are in 'generating' state for too long.
        composes = (
            Compose.query.filter(
                Compose.state == COMPOSE_STATES["generating"],
                Compose.time_started < too_old_datetime,
            )
            .order_by(Compose.id)
            .all()
        )

        for compose in composes:
            # RawConfig composes can have custom pungi_timeout. Filter them
            # out here in case they are not `generating` for longer than their
            # overriden pungi_timeout.
            if compose.source_type == PungiSourceType.RAW_CONFIG:
                # Get the pungi_timeout from RawPungiConfig.
                pungi_cfg = RawPungiConfig(compose)
                max_wait_seconds = timedelta(seconds=pungi_cfg.pungi_timeout * 2)
                if compose.time_started + max_wait_seconds > now:
                    continue

            compose.transition(
                COMPOSE_STATES["failed"],
                "Compose stuck in 'generating' state for longer than %d "
                "seconds." % max_generating_time,
            )

    def generate_lost_composes(self):
        """
        Gets all the composes in "generating" state and continues with
        the generation process.

        This method is here to handle situation where the ODCS is restarted
        in the middle of compose generation.
        """
        composes = Compose.query.filter(
            Compose.state == COMPOSE_STATES["generating"]
        ).all()

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
