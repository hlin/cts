#!/usr/bin/env python
""" submit_test_compose_oidc.py - Submit a test compose, via OpenID Connect.

If you have problems authenticating, try::

    $ rm -rf ~/.openidc/

Example usage::

    export PYTHONPATH=.:$VIRTUAL_ENV/lib/python2.7/site-packages:client
    ./submit_test_compose_oidc.py \
        --staging \
        --source f26 \
        --source-type tag \
        --flag no_deps \
        python-requests python-urllib3

"""
from __future__ import print_function

import argparse
import sys
import textwrap

import openidc_client
import requests.exceptions

import odcs.client.odcs


parser = argparse.ArgumentParser(
    description=textwrap.dedent(__doc__),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument(
    '--staging', default=False, action='store_true',
    help="Use the Fedora Infra staging enbironment.")
parser.add_argument(
    '--source', default=None,
    help="Source for the compose.  May be a koji tag or a "
    "whitespace separated list of modules.")
parser.add_argument(
    '--source-type', default=None,
    choices=['tag', 'module', 'raw_config'],
    help="Type for the source.  Must be 'tag' or 'module'")
parser.add_argument(
    '--flag', default=[], action='append',
    help="Flag to pass to influence the compose.")
parser.add_argument(
    '--result', default=[], action='append',
    help="Results of a compose to influence the compose.")
parser.add_argument(
    'packages', metavar='package', nargs='*',
    help='Packages to be included in the compose.')

args = parser.parse_args()

required = ['source', 'source_type']
for attr in required:
    if getattr(args, attr, None) is None:
        print("%r is required" % attr)
        sys.exit(1)

if args.staging:
    odcs_url = 'https://odcs.stg.fedoraproject.org'
    id_provider = 'https://id.stg.fedoraproject.org/openidc/'
else:
    odcs_url = 'https://odcs.fedoraproject.org'
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
    token = oidc.report_token_issue()
except requests.exceptions.HTTPError as e:
    print(e.response.text)
    raise

client = odcs.client.odcs.ODCS(
    odcs_url,
    auth_mech=odcs.client.odcs.AuthMech.OpenIDC,
    openidc_token=token,
)

result = client.new_compose(
    source=args.source,
    source_type=args.source_type,
    packages=args.packages,
    results=args.result,
    flags=args.flag,
)
print(result)
