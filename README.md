# On Demand Compose Service

The main goal of On Demand Compose Service (ODCS) is to allow generation of temporary composes using the REST API calls. By a compose, we mainly mean RPM repository with packages taken from different sources, but in the future, generation of other output types could be possible too.

ODCS can take RPMs for a compose from multiple sources like Koji tag, module built in Koji or external repository provided by Pulp tool.

## Using ODCS - client library

There is client library written in Python which allows easy access to REST API provided by ODCS server.

### Installing the ODCS client library

To install the library from Fedora repositories or from EPEL7 repository, you can run following:

```
$ sudo yum install python2-odcs-client
```

If you want to install using `pip`, you can run following:

```
$ sudo pip install odcs[client]
```

In case you want your python project to depend on ODCS client library and add it to your `requirements.txt`, you can just use following to depend on ODCS client:

```
odcs[client]
```

### ODCS authentication system

ODCS server can be configured to authenticate using OpenIDC, Kerberos or SSL. Eventually it can be set in NoAuth mode to support anonymous access. Depending on the ODCS server configuration, you have to set your authentication method when creating ODCS class instance.

#### Using OpenIDC for authentication

To use OpenIDC, you have to provide the OpenIDC token to ODCS client class constructor. To obtain that OpenIDC token, you can either use `python-openidc-client`, or ask the OpenIDC provider for service token which does not have to be refreshed. Once you have the token, you can create the ODCS instance like this:

```
from odcs.client.odcs import ODCS, AuthMech

odcs = ODCS("https://odcs.fedoraproject.org",
            auth_mech=AuthMech.OpenIDC,
            openidc_token="your_openidc_token")
```

Getting the `openidc_token` using `python-openidc-client` library can be done like this:

```
import openidc_client
staging = False

if staging:
    id_provider = 'https://id.stg.fedoraproject.org/openidc/'
else:
    id_provider = 'https://id.fedoraproject.org/openidc/'

# Get the auth token using the OpenID client.
oidc = openidc_client.OpenIDCClient(
    'odcs',
    id_provider,
    {'Token': 'Token', 'Authorization': 'Authorization'},
    'odcs-authorizer',
    'notsecret',
)

scopes = [
    'openid',
    'https://id.fedoraproject.org/scope/groups',
    'https://pagure.io/odcs/new-compose',
    'https://pagure.io/odcs/renew-compose',
    'https://pagure.io/odcs/delete-compose',
]
try:
    token = oidc.get_token(scopes, new_token=True)
except requests.exceptions.HTTPError as e:
    print(e.response.text)
    raise
```

#### Using Kerberos for authentication

To use Kerberos, you have to have valid Kerberos ticket or you need to have the Kerberos keytab file. If you want to use ODCS client library with Kerberos keytab, you have to set the `KRB5_CLIENT_KTNAME` environment variable to full path to the keytab file you want to use. You can for example do it like this:

```
from odcs.client.odcs import ODCS, AuthMech
from os import environ
environ["KRB5_CLIENT_KTNAME"] = "/full/path/to/ketab"

odcs = ODCS("https://odcs.fedoraproject.org",
            auth_mech=AuthMech.Kerberos)
```

#### Using SSL for authentication

To use SSL, you have to have SSL client certificate and key files. You then have to choose SSL AuthMech and pass the paths to SSL client certificate and key like this:

```
from odcs.client.odcs import ODCS, AuthMech

odcs = ODCS("https://odcs.fedoraproject.org",
            auth_mech=AuthMech.SSL,
            ssl_cert="/path/to/ssl-crt.pem",
            ssl_key="/path/to/ssl-key.pem")
```

### Requesting new compose

The general way how to request new ODCS compose is following:

```
compose = odcs.new_compose(sources, source_type)
```

Both `sources` and `source_type` are strings. Depending on `source_type` value, the `sources` have following meaning:

| `source_type` | `source` |
|---------------|----------|
| tag           | Name of Koji tag to take RPMs from. |
| module        | White-space separated NAME-STREAM or NAME-STREAM-VERSION of modules to include in compose. |
| pulp          | White-space separated list of context-sets. Repositories defined by these contests sets will be included in a compose. |
| raw_config    | String in `name#commit` hash format. The `name` must match one of the raw config locations defined in ODCS server config as `raw_config_urls`. The `commit` is commit hash defining the version of raw config to use. This config is then used as input config for Pungi. |

There are also additional optional attributes you can pass to `new_compose(...)` method:

- `seconds_to_live` - Number of seconds after which the generated compose should expire and will be removed.
- `packages` - List of packages which should be included in a compose. This is used only when `source_type` is set to `tag` to further limit the compose repository.
- `flags` - List of flags to further modify the compose output:
  - `no_deps` - For `tag` `source_type`, do not resolve dependencies between packages and include only packages listed in the `packages` in the compose. For `module` `source_type`, do not resolve dependencies between modules and include only the requested module in the compose.
- `sigkeys` - List of signature keys IDs. Only packages signed by one of these keys will be included in a compose. If there is no signed version of a package, compose will fail. It is also possible to pass an empty-string in a list meaning unsigned packages are allowed. For example if you want to prefer packages signed by key with ID `123` and also allow unsigned packages to appear in a compose, you can do it by setting sigkeys to `["123", ""]`.
- `results` - List of additional results which will be generated as part of a compose. Valid keys are:
  - `iso` - Generates non-installable ISO files with RPMs from a compose.
  - `boot.iso` - Generates `images/boot.iso` file which is needed to build base container images from resulting compose.

The `new_compose` method returns `dict` object describing the compose, for example:

```
{
    "flags": [
    "no_deps"
    ], 
    "id": 1, 
    "owner": "jkaluza", 
    "result_repo": "https://odcs.fedoraproject.org/composes/latest-odcs-1-1/compose/Temporary", 
    "result_repofile": "https://odcs.fedoraproject.org/composes/latest-odcs-1-1/compose/Temporary/odcs-1.repo", 
    "sigkeys": "", 
    "source": "f26", 
    "source_type": 1, 
    "state": 3, 
    "state_name": "wait", 
    "time_done": "2017-10-13T17:03:13Z", 
    "time_removed": "2017-10-14T17:00:00Z", 
    "time_submitted": "2017-10-13T16:59:51Z", 
    "time_to_expire": "2017-10-14T16:59:51Z"
}, 
```

The most useful data there is `result_repofile`, which points to the .repo file with URLs for generated compose. Another very important data there is the `state` and `state_name` field. There are following states of a compose:

| `state` | `state_name` | Description |
|---------|--------------|-------------|
| 0       | wait         | Compose is waiting in a queue to be generated |
| 1       | generating   | Compose is being generated |
| 2       | done         | Compose is generated - done |
| 3       | removed      | Compose has expired and is removed |
| 4       | failed       | Compose generation has failed |

As you can see in our example, compose is in `wait` state and therefore we have to wait until the ODCS generates the compose.

### Waiting until the compose is generated

There are two ways how to wait for the compose generation. The preferred one is listening on fedmsg bus for `odcs.state.change` message with `done` or `failed` state and another one is using HTTP polling implemented in `wait_for_compose(...)` method.

If your application does not allow listening on fedmsg bus for some reason, you can use `wait_for_compose(...)` method like this:

```
compose = odcs.new_compose(sources, source_type)

# Blocks until the compose is ready, but maximally for 600 seconds.
compose = odcs.wait_for_compose(compose["id"], timeout=600)

if compose["state_name"] == "done":
    print "Compose done, URL with repo file", compose["result_repofile"]
else:
    print "Failed to generate compose"
```

### Checking the state of existing ODCS compose

Once you have the compose ready, you might want to check its state later. This can be done using the `get_compose(...)` method like this:

```
compose = odcs.get_compose(compose["id"])
```

### Renewing the compose

If te `time_to_expire` of compose is getting closer and you know you would like to continue using the compose in near future, you can increase the time_to_expire using the `renew_compose(...)` method. This can be also used to regenerate expired compose in `removed` state. Such compose will have the same versions of packages as in the time when it was originally generated.

```
compose = odcs.renew_compose(compose["id"])
```

## Development

### Unit-testing

Install packages required by pip to compile some python packages:

```
$ sudo yum install -y gcc swig redhat-rpm-config python-devel openssl-devel openldap-devel
```

Koji is required but not available on pypi.python.org, we enabled system sitepackages for tox, so koji can be found while running tests.

```
$ sudo yum install -y python2-koji python3-koji
```

Run the tests:

```
$ make check
```

### Testing local composes from plain RPM repositories

You can test ODCS by generating compose form the `./server/tests/repo` repository using following commands:

```
$ ./create_sqlite_db
$ ./start_odcs_from_here
```

Add the `repo` source type to the server configuration in `./server/odcs/server/config.py`. (This will cause some tests to fail, so it needs to be reverted back after you are done with your changes!)

And in another terminal, submit a request to frontend:

```
$ ./submit_test_compose repo `pwd`/server/tests/repo ed
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
