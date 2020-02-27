===================
Raw config composes
===================

ODCS can also be used to generate composes defined by the Pungi configuration
file stored in an external git repository. There is special compose source type
called ``raw_config`` which is used for these composes.

This document describes how to configure ODCS server to generate
``raw_config`` composes.


High level overview
===================


Raw config composes are submitted by the ODCS client in the
``raw_config_name#commit_hash`` format. For example
``fedora-30-nightly#master``.

The ODCS server uses ``raw_config_name`` (in our case ``fedora-30-nightly``)
to find matching record in the ``raw_config_urls`` option stored in its main
configuration file.

The ``raw_config_urls`` defines the git repository, branch and config file name.
This is used to fetch the Pungi configuration and ensures that Raw config
configuration can be stored only on trusted git repositories.

The ``raw_config_urls`` option can also define extra options influencing
the generated compose (for example ``schema_override``).

ODCS then fetches the git repository associated with the ``raw_config`` and
wraps the main Pungi configuration file using the ``raw_config_wrapper.conf``
configuration file. This configuration file defines deployment related Pungi
options like Koji profile or for example runroot methods. This ensures
these options cannot be changed by the ODCS user.

Before executing Pungi, final Pungi configuration file is validated using the
``pungi-config-validate`` tool. It is possible to make the validation more
strict by overriding default JSON schema used by Pungi. This can be done on
global level using the ``raw_config_schema_override`` ODCS configuration
option or per ``raw_config_name`` using the ``schema_override`` option in the
``raw_config_urls``. It is also possible to combine these two options.

After the validation is done, ODCS executes Pungi and generates the compose.

Symlinks pointing to the generated compose are stored in the directories
named according to compose type - for example ``nightly``, ``ci`, ``test``
or ``production``.


ODCS server configuration
=========================


Preparing the ``raw_config_wrapper.conf``
-----------------------------------------

The ``/etc/odcs/raw_config_wrapper.conf`` is simple Pungi configuration
script. It must always start with ``from raw_config import *`` to include
the real ``raw_config`` configuration file.

Any further options are then used to override the real ``raw_config``
configuration. For example to set particular Koji profile:


.. sourcecode:: none

    from raw_config import *
    koji_profile = 'odcs_stg'


Adding the ``raw_config_urls`` record
-------------------------------------

The ``raw_config_urls`` in the ODCS configuration is a dict with the name
of ``raw_config`` as a key and another dict as value. The dict used as value
defines the ``raw_config`` and can have following keys:

  - ``url`` - URL to git repository. It is later passed to ``git clone``.
  - ``commit`` [optional] - If set, it is not possible to specify commit using
    the ODCS client and only commit hash (or branch name) defined by this
    option will be used.
  - ``path`` [optional] - If set, defines the path within the git repository
    where the configuration files are stored. This is useful in case when
    there are multiple independent Pungi configuration trees stored in
    the single git repository.
  - ``config_filename`` - Name of the main Pungi configuration file.
  - ``schema_override`` [optional] - If set, defines the path to JSON schema
    override file to be used when validating the main Pungi configuration file.
  - ``pungi_timeout`` - [optional] - If set, defines the timeout in seconds in
    which the compose must be finished, otherwise the compose is marked as
    ``failed``.


Enabling ``pungi-config-validate``
-------------------------------------

By default, the ``pungi-config-validate`` script is not executed for
``raw_config`` composes. It is however recommended to enable it, otherwise
it is not possible to use the ``schema_override`` options.

To enable it, set the ``pungi_config_validate`` ODCS option to
``"pungi-config-validate"`` (Or to full path to the pungi-config-validate
script).


Preparing the ``schema_override`` JSON file
-------------------------------------------

Raw Pungi configuration files can be used to execute any command on the ODCS
backend which might be a security issue in case the people editing the
configuration files cannot be trusted. It is also for example possible to
generate composes with external files coming from untrusted repositories.

It is therefore possible to handle cases like this using the extended JSON
schema validation which will allow only certain values for certain options.

This is possible by creating global ``schema_override.json`` file and setting
it using the ``raw_config_schema_override`` ODCS option. It is also possible
to specify this for each ``raw_config`` using the ``schema_override`` option
in the ``raw_config_urls`` ODCS option.

The ``schema_override.json`` format is the same as the one used by Pungi
for the default JSON schema. The default schema can be obtained by running
``pungi-config-validate --dump-schema``.

The ``schema_override.json`` is merged with this default JSON schema and
overrides its values. For example, to allow only ``koji`` ``pkgset_source``,
the ``schema_override.json`` would look like this:

.. sourcecode:: none

    {
        "properties": {
            "pkgset_source": {
                "enum": ["koji"]
            }
        }
    }


Allowing users/groups to generate ``raw_config`` composes
---------------------------------------------------------

This is done by setting the ``raw_config`` source_type in
the ``allowed_clients`` ODCS option like this:


.. sourcecode:: none

    allowed_clients = {
        "some_username": {"source_types": ["raw_config", ...]}
    }


