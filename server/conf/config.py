from os import path, mkdir


# FIXME: workaround for this moment till confdir, dbdir (installdir etc.) are
# declared properly somewhere/somehow
confdir = path.abspath(path.dirname(__file__))
# use parent dir as dbdir else fallback to current dir
dbdir = path.abspath(path.join(confdir, '../..')) if confdir.endswith('conf') \
    else confdir


class BaseConfiguration(object):
    # Make this random (used to generate session keys)
    SECRET_KEY = '74d9e9f9cd40e66fc6c4c2e9987dce48df3ce98542529fd0'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(path.join(
        dbdir, 'odcs.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    HOST = '127.0.0.1'
    PORT = 5005

    DEBUG = False
    # Global network-related values, in seconds
    NET_TIMEOUT = 120
    NET_RETRY_INTERVAL = 30

    # Available backends are: console, file, journal.
    LOG_BACKEND = 'journal'

    # Path to log file when LOG_BACKEND is set to "file".
    LOG_FILE = 'odcs.log'

    # Available log levels are: debug, info, warn, error.
    LOG_LEVEL = 'info'

    SSL_ENABLED = False

    PDC_URL = 'https://pdc.fedoraproject.org/rest_api/v1'
    PDC_INSECURE = False
    PDC_DEVELOP = True

    # Users are required to be in allowed_clients to generate composes,
    # you can add group names or usernames (it can be normal user or host
    # principal) into ALLOWED_CLIENTS. The group names are from ldap for
    # kerberos users or FAS for openidc users.
    ALLOWED_CLIENTS = {
        'groups': [],
        'users': [],
    }

    # Users in ADMINS are granted with admin permission.
    ADMINS = {
        'groups': [],
        'users': [],
    }

    # Select which authentication backend to work with. There are 3 choices
    # noauth: no authentication is enabled. Useful for development particularly.
    # kerberos: Kerberos authentication is enabled.
    # openidc: OpenIDC authentication is enabled.
    AUTH_BACKEND = ''

    # Used for Kerberos authentication and to query user's groups.
    # Format: ldap://hostname[:port]
    # For example: ldap://ldap.example.com/
    AUTH_LDAP_SERVER = ''

    # Group base to query groups from LDAP server.
    # Generally, it would be, for example, ou=groups,dc=example,dc=com
    AUTH_LDAP_GROUP_BASE = ''

    AUTH_OPENIDC_USERINFO_URI = 'https://id.fedoraproject.org/openidc/UserInfo'

    # Scope requested from Fedora Infra for permission of submitting request to
    # run a new compose.
    # See also: https://fedoraproject.org/wiki/Infrastructure/Authentication
    # Add additional required scope in following list
    AUTH_OPENIDC_REQUIRED_SCOPES = [
        'openid',
        'https://id.fedoraproject.org/scope/groups',
        'https://pagure.io/odcs/new-compose',
        'https://pagure.io/odcs/renew-compose',
        'https://pagure.io/odcs/delete-compose',
    ]


class DevConfiguration(BaseConfiguration):
    DEBUG = True
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'

    # Global network-related values, in seconds
    NET_TIMEOUT = 5
    NET_RETRY_INTERVAL = 1
    TARGET_DIR = path.join(dbdir, "test_composes")
    try:
        mkdir(TARGET_DIR)
    except:
        pass

    # Disable login_required in development environment
    LOGIN_DISABLED = True
    # Disable authorize in development environment
    AUTHORIZE_DISABLED = True

    AUTH_BACKEND = 'noauth'
    AUTH_OPENIDC_USERINFO_URI = 'https://iddev.fedorainfracloud.org/openidc/UserInfo'


class TestConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(
        path.join(dbdir, 'test_odcs.db'))

    # Global network-related values, in seconds
    NET_TIMEOUT = 3
    NET_RETRY_INTERVAL = 1

    AUTH_BACKEND = 'noauth'
    AUTH_LDAP_SERVER = 'ldap://ldap.example.com'
    AUTH_LDAP_GROUP_BASE = 'ou=groups,dc=example,dc=com'


class ProdConfiguration(BaseConfiguration):
    pass
