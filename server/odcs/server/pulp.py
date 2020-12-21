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
# Written by Chenxiong Qi <cqi@redhat.com>
#            Jan Kaluza <jkaluza@redhat.com>

import copy
import json
import re
import requests
import requests.exceptions

from odcs.server import conf, log
from odcs.server.mergerepo import MergeRepo
from odcs.server.utils import retry


class Pulp(object):
    """Interface to Pulp"""

    def __init__(self, server_url, username, password, compose):
        self.username = username
        self.password = password
        self.server_url = server_url
        self.compose = compose
        self.rest_api_root = "{0}/pulp/api/v2/".format(self.server_url.rstrip("/"))

    @retry(wait_on=requests.exceptions.RequestException)
    def _rest_post(self, endpoint, post_data):
        query_data = json.dumps(post_data)
        try:
            r = requests.post(
                "{0}{1}".format(self.rest_api_root, endpoint.lstrip("/")),
                query_data,
                auth=(self.username, self.password),
                timeout=conf.net_timeout,
            )
        except requests.exceptions.RequestException as e:
            # also catches ConnectTimeout, ConnectionError
            # change message of the catched exception and re-raise
            msg = "Pulp connection has failed: {}".format(e.args)
            raise requests.exceptions.RequestException(msg)

        r.raise_for_status()
        return r.json()

    @retry(wait_on=requests.exceptions.RequestException)
    def _rest_get(self, endpoint):
        try:
            r = requests.get(
                "{0}{1}".format(self.rest_api_root, endpoint),
                auth=(self.username, self.password),
                timeout=conf.net_timeout,
            )
        except requests.exceptions.RequestException as e:
            msg = "Pulp connection has failed: {}".format(e.args)
            raise requests.exceptions.RequestException(msg)

        r.raise_for_status()
        return r.json()

    def _try_arch_merge(self, content_set_repos):
        """
        Tries replacing arch string (e.g. "x86_64" or "ppc64le") in each "url"
        in content_set_repos with "$basearch" and if this results in the same
        repository URL for each repo in the content_set_repos and also
        the sigkeys are the same, returns the single repo with $basearch.
        If not, returns an empty dict.

        The "arches" value of returned repo is set to union of merged "arches".

        For example, for following input:
            [{"url": "http://localhost/x86_64/os", "arches": ["x86_64"]},
             {"url": "http://localhost/ppc64le/os", "arches": ["ppc64le"]}]
        This method returns:
            {"url": "http://localhost/$basearch/os",
             "arches": ["x86_64", "ppc64le"]}
        """
        # For no or exactly one repo, there is nothing to merge.
        if len(content_set_repos) < 2:
            return {}

        first_repo = None
        for repo in content_set_repos:
            if len(repo["arches"]) != 1:
                # This should not happen normally, because each repo has just
                # single arch in Pulp, but be defensive.
                raise ValueError(
                    "Content set repository %s does not have exactly 1 arch: "
                    "%r." % (repo["url"], repo["arches"])
                )
            url = repo["url"].replace(list(repo["arches"])[0], "$basearch")
            if first_repo is None:
                first_repo = copy.deepcopy(repo)
                first_repo["url"] = url
                continue
            if first_repo["url"] != url or first_repo["sigkeys"] != repo["sigkeys"]:
                return {}
            first_repo["arches"] = first_repo["arches"].union(repo["arches"])
        return first_repo

    def _merge_repos(self, content_set, content_set_repos):
        """
        Merges the repositories of the same arch from `content_set_repos`
        and returns the new repository dict pointing to the newly created
        merged repository.

        In case there is just single (or none) repository in
        `content_set_repos`, returns empty dict.
        """
        # For no or exactly one repo, there is nothing to merge.
        if len(content_set_repos) < 2:
            return {}

        # We must merge repos of the same arch only, so group them by arch
        # at first.
        per_arch_repos = {}
        for repo in content_set_repos:
            if len(repo["arches"]) != 1:
                # This should not happen normally, because each repo has just
                # single arch in Pulp, but be defensive.
                raise ValueError(
                    "Content set repository %s does not have exactly 1 arch: "
                    "%r." % (repo["url"], repo["arches"])
                )
            arch = list(repo["arches"])[0]
            if arch not in per_arch_repos:
                per_arch_repos[arch] = []
            per_arch_repos[arch].append(repo)

        merge_repo = MergeRepo(self.compose)

        for arch, repos in per_arch_repos.items():
            urls = [repo["url"] for repo in repos]
            merge_repo.run(arch, urls, content_set)

        return {
            "url": "%s/%s/$basearch" % (self.compose.result_repo_url, content_set),
            "arches": set(per_arch_repos.keys()),
            "sigkeys": content_set_repos[0]["sigkeys"],
        }

    def _make_repo_info(self, raw_repo):
        """
        Convert the raw repo info returned from Pulp to a simple repo object
        for further handling

        :param dict raw_repo: the repo info returned from Pulp API endpoint.
        :return: a simple repo info used internally for further handling.
        :rtype: dict
        """
        notes = raw_repo["notes"]
        url = self.server_url.rstrip("/") + "/" + notes["relative_url"]
        # OSBS cannot verify https during the container image build, so
        # fallback to http for now.
        if url.startswith("https://"):
            url = "http://" + url[len("https://") :]
        return {
            "id": raw_repo["id"],
            "url": url,
            "arches": {notes["arch"]},
            "sigkeys": sorted(notes["signatures"].split(",")),
            "product_versions": notes["product_versions"],
        }

    def get_repos_from_content_sets(
        self, content_sets, include_unpublished_repos=False
    ):
        """
        Returns dictionary with URLs of all shipped repositories defined by
        the content_sets.
        The key in the returned dict is the content_set name and the value
        is the URL to repository with RPMs.

        :param list[str] content_sets: Content sets to look for.
        :param bool include_unpublished_repos: set True to include unpublished repositories.
        :rtype: dict
        :return: Dictionary in following format:
            {
                content_set_1: {
                    "url": repo_url,
                    "arches": set([repo_arch1, repo_arch2]),
                    'sigkeys': ['sigkey1', 'sigkey2', ...]
                },
                ...
            }
        """
        query_data = {
            "criteria": {
                "filters": {"notes.content_set": {"$in": content_sets}},
                "fields": ["notes", "id"],
            }
        }

        if not include_unpublished_repos:
            query_data["criteria"]["filters"][
                "notes.include_in_download_service"
            ] = "True"
        repos = self._rest_post("repositories/search/", query_data)

        per_content_set_repos = {}
        for repo in repos:
            content_set = repo["notes"]["content_set"]
            per_content_set_repos.setdefault(content_set, []).append(
                self._make_repo_info(repo)
            )
        return per_content_set_repos

    def merge_repos_by_arch(self, repos):
        """
        Merge repositories by arch and the repo with highest version within
        a content set will be selected.

        :param repos: a mapping from a content set to its associated repositories.
        :type repos: dict[str, list[dict]]
        :return: a new mapping from a content set to the merged repository by arch.
        :rtype: dict[str, dict]
        """
        ret = {}
        for cs, repos in repos.items():
            can_sort = True
            version_len = None
            arches = None
            for repo in repos:
                if arches and arches != repo["arches"]:
                    log.debug("Skipping sorting repos: arch mismatch.")
                    can_sort = False
                    break
                arches = repo["arches"]
                try:
                    product_versions = json.loads(repo["product_versions"])
                except ValueError:
                    log.debug(
                        "Skipping sorting repos: invalid JSON in product_versions."
                    )
                    can_sort = False
                    break
                if len(product_versions) != 1:
                    log.debug(
                        "Skipping sorting repos: more than one version for a repo."
                    )
                    can_sort = False
                    break
                if not re.match(r"\d+(\.\d+)*$", product_versions[0]):
                    log.debug("Skipping sorting repos: unparsable version string.")
                    can_sort = False
                    break
                # Parse the version into a tuple.
                ver_len = product_versions[0].count(".")
                if version_len and version_len != ver_len:
                    log.debug("Skipping sorting repos: incompatible versions.")
                    can_sort = False
                    break
                version_len = ver_len
            if can_sort:
                repos = [
                    sorted(
                        repos,
                        key=lambda k: tuple(
                            json.loads(k["product_versions"])[0].split(".")
                        ),
                        reverse=True,
                    )[0]
                ]
            # In case there are multiple repos, at first try merging them
            # by replacing arch in repository baseurl with $basearch.
            merged_repos = self._try_arch_merge(repos)
            if not merged_repos:
                # In case we cannot merge repositories by replacing the arch
                # with $basearch, call mergerepo_c.
                merged_repos = self._merge_repos(cs, repos)
            if merged_repos:
                ret[cs] = merged_repos
            else:
                ret[cs] = repos[-1]

        return ret

    def get_repos_by_id(self, repo_ids, include_unpublished_repos=False):
        """Get repositories by id

        :param iterable[str] repo_ids: list of repository ids.
        :param bool include_unpublished_repos: whether the unpublished
            repositories are included in the returned result.
        """
        repos = {}
        for repo_id in repo_ids:
            try:
                repo = self._rest_get("repositories/{}/".format(repo_id))
            except requests.exceptions.HTTPError as e:
                if e.response.status_code != 404:
                    raise
                error_message = e.response.json()["error_message"]
                log.warning(
                    "Cannot find repository for id %s. Error message: %s",
                    repo_id,
                    error_message,
                )
                continue
            if (
                repo["notes"]["include_in_download_service"]
                or include_unpublished_repos
            ):
                repos[repo_id] = self._make_repo_info(repo)
        return repos
