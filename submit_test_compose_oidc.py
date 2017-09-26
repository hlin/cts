#!/usr/bin/env python

import openidc_client
import requests.exceptions

import odcs.client.odcs

# Get the auth token using the OpenID client.
id_provider = 'https://id.stg.fedoraproject.org/openidc/'
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
    print e.response.text
    raise

client = odcs.client.odcs.ODCS(
    'https://odcs.stg.fedoraproject.org',
    auth_mech=odcs.client.odcs.AuthMech.OpenIDC,
    openidc_token=token,
)

result = client.new_compose(
    source='module-base-runtime-master-20170313200124',
    source_type='tag',
    packages=['libselinux'],
    flags=['nodeps'],
)
print result
