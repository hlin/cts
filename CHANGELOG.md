# ODCS change log

All notable changes to this project will be documented in this file.

## 0.2.12:
  - Release date: 2018-09-03
  - When renewing old compose, do not reuse newer compose, but always
    renegerate the compose instead.
  - Remove limit of number of Pulp composes picked up in
    the pickup_waiting_composes().

## 0.2.11:
  - Release date: 2018-08-16
  - Regenerate the composes stuck in the 'wait' state automatically.
  - Fix the caching code so parts of the older composes are reused by newer
    Pungi versions.
  - Validate the Pungi compose before marking it as "complete", so it cannot
    go from "complete" to "failed" state in case validation fails.
  - Keep the original state_reason when removing the compose.

## 0.2.10:
  - Release date: 2018-07-31
  - Fix the mergerepo_c call once again to use the right argument names
    after mergerepo_c upstream changed the arguments before the official
    mergerepo_c release.

## 0.2.9
  - Release date: 2018-07-30
  - Cache Pulp repos and fix the mergerepo_c call used in some corner cases
    when repositories for multiple architectures are in single Pulp
    content set.

## 0.2.8
  - Release date: 2018-07-17
  - ODCS now uses MBS instead of PDC to lookup modules. All "PDC_*" config
    options have been removed and new MBS_URL config option has been added.
  - Only modules in n:s, n:s:v or n:s:v:c format are allowed as input.
  - Raw config is now downloaded using the "git clone".
  - The RAW_CONFIG syntax has changed, see the default config for more info.
  - Add 'include_unpublished_pulp_repos' compose flag for "pulp" source type.

## 0.2.7
  - Release date: 2018-06-20
  - OIDC: service tokens are treated as having "no groups".

## 0.2.6.2
  - Release date: 2018-06-20
  - Added "get" option to the client cli

## 0.2.6.1
  - Release date: 2018-06-14
  - Bugfix to the `packages` list change.

## 0.2.6
  - Release date: 2018-06-14
  - Any character is now allowed in the `packages` list (allowing gcc-c++).
  - Custom ODCS server can be set in ODCS client.-

## 0.2.5
  - Release date: 2018-06-07
  - Improve handling of Pulp content_sets with multiple repositories.

## 0.2.4
  - Release date: 2018-06-04
  - ODCS backend can now be run as fedmsg-hub consumer.
  - Pulp composes are now not limited by `NUM_CONCURRENT_PUNGI` config
    variable.

## 0.2.3
  - Release date: 2018-05-07
  - REST API now accepts new `order_by` key. The value defines the ordering
    of composes in response. It can be one of: "id", "owner", "source_Type",
    "koji_event", "state", "time_to_expire", "time_submitted", "time_done" or
    "time_removed". If the value is prefixed with minus sign ("-"), the order
    is descending. Default ordering value is "-id".
  - Rare traceback caused by None compose.id while sending UMB or fedmsg
    messages is now fixed.

## 0.2.2
  - Release date: 2018-04-19.
  - The `packages` field is now requested for `tag` source type by frontend.
  - The `state_reason` field in frontend response now contains the error
    messages from the `pungi.global.log`, so the `state_reason` field is much
    more useful in case the compose fails.
  - New Koji Tag Cache feature is introduced to cache the Koji tag repodata.
    The cached data is reused for future composes from the same Koji tag and
    should make them much more faster.
