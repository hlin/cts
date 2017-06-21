from os import path, mkdir


# FIXME: workaround for this moment till confdir, dbdir (installdir etc.) are
# declared properly somewhere/somehow
confdir = path.abspath(path.dirname(__file__))
# use parent dir as dbdir else fallback to current dir
dbdir = path.abspath(path.join(confdir, '..')) if confdir.endswith('conf') \
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
    PDC_INSECURE = True
    PDC_DEVELOP = True


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


class TestConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(
        path.join(dbdir, 'tests', 'test_odcs.db'))

    # Global network-related values, in seconds
    NET_TIMEOUT = 3
    NET_RETRY_INTERVAL = 1


class ProdConfiguration(BaseConfiguration):
    pass
