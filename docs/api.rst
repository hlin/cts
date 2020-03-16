=========
ODCS APIs
=========

.. _compose_json:

ODCS Compose JSON representation
================================

The ODCS compose is always represented in the API request as JSON, for example:

.. sourcecode:: none

    {
        "arches": "x86_64",
        "builds": null,
        "flags": [],
        "id": 470,
        "koji_event": null,
        "lookaside_repos": "",
        "modular_koji_tags": null,
        "module_defaults_url": null,
        "multilib_arches": "",
        "multilib_method": 0,
        "owner": "osbs@service",
        "packages": null,
        "removed_by": null,
        "result_repo": "https://localhost/latest-odcs-470-1/...",
        "result_repofile": "https://localhost/.../odcs-470.repo",
        "sigkeys": "",
        "source": "flatpak-common:f30:3020190718103837:548d4c8d",
        "source_type": 2,
        "state": 2,
        "state_name": "done",
        "state_reason": "Compose is generated successfully",
        "time_done": "2019-07-23T11:26:26Z",
        "time_removed": null,
        "time_submitted": "2019-07-23T11:24:54Z",
        "time_to_expire": "2019-07-24T11:24:54Z",
        "time_started": "2019-07-23T11:25:01Z"
    }

The fields used in the ODCS compose JSON have following meaning:

.. _arches:

*arches* - ``(white-space separated list of strings)``
    List of architectures the compose is generated for. The strings to express particular architecture are the same as the ones used by Koji build systemd.

.. _compose_type:

*compose_type* - ``(string)``
    Type of the compose when generating raw_config compose. Can be "test", "nightly", "ci", "production".

.. _builds:

*builds* - ``(white-space separated list of strings or null)``
    List of NVRs of Koji builds defining the set of package which can be included in a resulting compose. If ``null``, all Koji builds tagged to requested Koji tags can appear in the compose.

.. _id:

*id* - ``(number)``
    The ID of ODCS compose.

.. _flags:

*flags* - ``(list of strings)``
    Flags influencing the way how compose is generated:

    - *no_deps* - Compose will contain only the requested packages/modules without pulling-in their RPM-level or Module-level dependencies.
    - *no_inheritance* - Only packages/modules directly tagged in the requested Koji tag will be added to the module. Inherited tags will be ignored.
    - *include_unpublished_pulp_repos* - Even unpublished Pulp repositories will be included in the resulting compose.
    - *ignore_absent_pulp_repos* - Ignore non-existing content sets in the source of Pulp compose. The source field on the compose will be updated to match what was actually used in the compose.
    - *check_deps* - Compose will fail if the RPM-level dependencies between packages in the compose are not satisfied.
    - *include_done_modules* - Compose can include also modules which are in the ``done`` state. By default, only modules in ``ready`` state are allowed to be included in a composes.

.. _koji_event:

*koji_event* - ``(number or null)``
    The Koji event defining the point in Koji history when the compose was generated. It can be ``null`` if source type does not relate to Koji tag.

.. _label:

*label* - ``(string)``
    Compose label when generating raw_config compose.

.. _lookaside_repos:

*lookaside_repos* - ``(white-space separated list of strings or null)``
    List of URLs pointing to RPM repositories with packages which will be used by internal dependency resolver to resolve dependencies. Packages from these repositories **will not** appear in the resulting ODCS compose, but they are considered while checking whether the RPM dependencies are satisfied in the resulting compose when  ``check_deps`` ODCS flag.

    This is useful for example when creating compose from small Koji tag which is for example based on Fedora RPM repository and verifying that the dependencies of RPMs in the small tag are satisfied when used together with the Fedora repository.

.. _modular_koji_tags:

*modular_koji_tags* - ``(white-space separated list of strings or null)``
    List of Koji tags with modules which should appear in the resulting compose.

.. _multilib_arches:

*multilib_arches* - ``(white-space separated list of strings)``
    List of architectures for which the multilib should be enabled. This must be subset of ``arches``. When architecture is listed in the ``multilib_arches``, even the packages from binary compatible archictures will end up in a resulting compose for this architecture. For example, if ``x86_64`` is in ``multilib_arches``, then even the ``i686`` packages will appear in the resulting compose for ``x86_64`` architecture.

.. _multilib_method:

*multilib_method* - ``(number)``
    Number defining the way how are the multilib packages identified:

    - 0 (``none``) - Multilib is disabled.
    - 1 (``runtime``) - Packages whose name ends with "-devel" or "-static" suffix will be considered as multilib.
    - 2 (``devel``) - Packages that install some shared object file "*.so.*" will be considered as multilib.
    - 4 (``all``) - All packages will be considered as multilib packages.

.. _owner:

*owner* - ``(string)``
    The name of owner (requester) of the compose.

.. _packages:

*packages* - ``(white-space separated list of strings or null)``
    List of names of RPMs (packages) which should appear in the compose. The list of packages to choose from is defined by the content of Koji builds defined in ``builds``. If ``null``, all packages from ``builds`` will be included in a compose.

.. _pungi_config_dump:

*pungi_config_dump* - ``(string)``
    Full dump of Pungi configuration used to generate the compose. It is stored only when ``compose_type`` is set to ``production``. This field appears in the API responses only if single compose is returned.

.. _removed_by:

*removed_by* - ``(string)``
    The name of user who removed (or cancelled) the compose manually.

.. _result_repo:

*result_repo* - ``(string)``
    The URL to top directory where per-architecture repositories are stored. Only set for composes which generate such repositories on ODCS server.

    .. note::
        If ``target_dir`` is set to non-default value, then the ``result_repo`` might be an empty string, because ODCS might not have enough data to generate the URL.

.. _result_repofile:

*result_repofile* - ``(string)``
    The URL to .repo file which points to resulting compose. Only set for composes which generate such single repository.

    .. note::
        If ``target_dir`` is set to non-default value, then the ``result_repofile`` might be an empty string, because ODCS might not have enough data to generate the URL.

.. _sigkeys:

*sigkeys* - ``(white-space separated list of strings)``
    List of signing keys. The packages in a resulting compose must be signed by one of those keys. If not set, unsigned packages can appear in a compose.

.. _source:

*source* - ``(white-space separated list of strings)``
    Based on the ``source_type``, defines the sources of RPMs for resulting compose. See ``source_type`` for more info.

.. _source_type:

*source_type* - ``(number)``
    Number defining the type of ``source`` giving it particular meaning:

    - 1 (``tag``) - The ``source`` is name of Koji tag to take the builds from. Additional Koji builds can be added by when the ``builds`` option is set.
    - 2 (``module``) - The ``source`` is the list of modules in ``N:S``, ``N:S:V`` or ``N:S:V:C`` format. When using ``N:S`` format, the latest version found in MBS is used. When using ``N:S`` or ``N:S:V``, the module needs to be in the ``ready`` state in the MBS. When using ``N:S:V:C``, the module can be even in the ``done`` state in the MBS.
    - 3 (``repo``) - The ``source`` is full path to repository from which the packages are taken. This is often disabled source type by deployed ODCS servers.
    - 4 (``pulp``) - The ``source`` is the list of Pulp content-sets. Repositories defined by these content-sets will be included in the compose.
    - 5 (``raw_config``) - The ``source`` is string in the ``name#commit`` hash format. The ``name`` must match one of the raw config locations defined in ODCS server config as ``raw_config_urls``. The ``commit`` is commit hash defining the version of raw config to use. This config is then used as input config for Pungi.
    - 6 (``build``) - The ``source`` is set to empty string. The list of Koji builds included in a compose is defined by the ``builds`` attribute.
    - 7 (``pungi_compose``) - The ``source`` is URL to variant repository of external compose generated by the Pungi. For example https://kojipkgs.fedoraproject.org/compose/rawhide/latest-Fedora-Rawhide/compose/Server/. The generated compose will contain the same set of RPMs as the given external compose variant. The packages will be taken from the configured Koji instance.

.. _state:

*state* - ``(number)``
    Number defining the state the compose is currently in:

    - 0 (``wait``) - Compose is waiting in a queue to be generated.
    - 1 (``generating``) - Compose is being generated by one of the backends.
    - 2 (``done``) - Compose is generated.
    - 3 (``removed``) - Compose has been removed.
    - 4 (``failed``) - Compose generation has failed.

.. _state_name:

*state_name* - ``(string)``
    Name of the state the compose is currently in. See ``state`` for more info.

.. _target_dir:

*target_dir* - ``(string)``
    Name of the target directory for the compose. No value or the ``default`` value means that default target directory is used. This default target directory is always served using the ODCS Frontend. Other possible values depend on the ODCS server configuration.

    .. note::
        If ``target_dir`` is set to non-default value, then the ``result_repo`` and ``result_repofile`` might be an empty string, because ODCS might not have enough data to generate the URL.

.. _time_done:

*time_done* - ``(datetime)``
    The date and time on which the compose has been done - either moved to ``failed`` or ``done`` state.

.. _time_removed:

*time_removed* - ``(datetime)``
    The date and time on which the compose has been removed from ODCS storage (either cancelled or expired).

.. _time_submitted:

*time_submitted* - ``(datetime)``
    The date and time on which the compose request has been submitted by ``owner``.

.. _time_to_expire:

*time_to_expire* - ``(datetime)``
    The date and time on which the compose is planned to expire. After this time, the compose is removed from ODCS storage.

.. _time_started:

*time_started* - ``(datetime)``
    The date and time on which the compose was started by a backend.

REST API pagination
===================

When multiple objects (currently just ODCS composes) are returned by the ODCS REST API, they are wrapped in the following JSON which allows pagination:

.. sourcecode:: none

    {
        "items": [
            {odcs_compose_json},
            ...
        ],
        "meta": {
            "first": "http://odcs.localhost/api/1/composes/?per_page=10&page=1",
            "last": "http://odcs.localhost/api/1/composes/?per_page=10&page=14890",
            "next": "http://odcs.localhost/api/1/composes/?per_page=10&page=2",
            "page": 1,
            "pages": 14890,
            "per_page": 10,
            "prev": null,
            "total": 148898
        }
    }

The ``items`` list contains the ODCS compose JSONs. The ``meta`` dict contains metadata about pagination. It is possible to use ``per_page`` argument to set the number of composes showed per single page and ``page`` to choose the page to show.

.. _http-api:

HTTP REST API
=============

.. automodule:: odcs

.. autoflask:: odcs.server:app
    :undoc-static:
    :modules: odcs.server.views
    :order: path


Messaging API
=============

ODCS also sends AMQP or Fedmsg messages when compose request changes its state. These messages have ``odcs.compose.state-changed`` topic and contains the :ref:`compose_json` as described earlier in this document.
