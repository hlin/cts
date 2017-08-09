# On Demand Compose Service

Currently, there is no API which can be used by other services or even people to generate temporary composes with limited content. There is increasing need for such composes from various reasons:

To rebuild Docker images automatically with updated packages (for example when there is OpenSSL security update), we need a repository containing the updated packages, so we can point Koji to take the packages from these repositories without waiting for the packages to appear in the official public repository.


To test modules right after the build, QA team needs a compose containing the built module together with all the modules this module depends on, so QA team is able to install the module and run the tests.
 
Furthermore:

In the mid-/long-term, Fedora releng would like to generate the main compose from the smaller composes generated by the ODCS, so the composing would be faster.
Current composes are also not event-based. For example in Fedora, the composes are built even when nothing changed on input side of a compose.


More information can be find in the On Demand Compose Service Focus document: https://fedoraproject.org/wiki/Infrastructure/Factory2/Focus/ODCS.

## Dependencies

On top of the classic `requirements.txt`, ODCS depends on Pungi (https://pagure.io/pungi/) in version 4.1.15 or newer.

## Unit-testing

```
$ tox -e py27,py35,flake8
```

## Testing local composes from plain RPM repositories

You can test ODCS by generating compose form the `./tests/repo` repository using following commands:

```
$ ./create_sqlite_db
$ ./start_odcs_from_here
```

And in another terminal, submit a request to frontend:

```
$ ./submit_test_compose repo `pwd`/tests/repo ed
{
  "id": 1,
  "owner": "Unknown",
  "result_repo": null,
  "source": "/home/hanzz/code/fedora-modularization/odcs/tests/repo",
  "source_type": 3,
  "state": 0,
  "state_name": "wait",
  "time_done": null,
  "time_removed": null,
  "time_submitted": "2017-06-12T14:18:19Z"
}
```

You should then see the backend process generating the compose and once it's done, the resulting compose in `./test_composes/latest-Unknown-1/compose/Temporary` directory.

## REST API

### Submitting new compose request

To submit new compose request, you can send POST request in the following format to `/odcs/1/composes`:

```
{
  "source_type": "tag",
  "source": "f26",
  "packages": ["httpd"]
}
```

This tells ODCS to create new compose from the Koji tag "f26" with the "httpd" packages and all the dependencies this package has in the "f26" Koji tag.

The example above is the minimal example, but there are more JSON fields which can be used to influence the resulting compose:

- **source_type** - "tag" for compose from Koji tag, "module" for compose from the Fedora module, "repo" for compose from local RPM repository.
- **source** - For "tag" source_type, name of the tag. For "module" source_type, white-space separated list of module name-stream or name-stream-version. For "repo" source_type, full path to repository.
- **packages** - List of packages to include in a compose. Must not be set for "module" source_type.
- **seconds-to-live** - Number of seconds for which the compose should become available. After that, the compose is removed. The default and maximum value is defined by server-side configuration.
- **flags** - List of flags influencing the resulting compose:
    - **no_deps** - The resulting compose will contain only packages defined in the "packages" list without their dependencies, or for a module compose, only the modules listed in "source" without their dependencies.

