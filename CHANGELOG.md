# ODCS change log

All notable changes to this project will be documented in this file.

## 0.2.19:
  - Release data: 2018-11-27
  - Remove old cached data from Koji tag cache directory.
  - Fail composes in 'generating' state older than `2 * conf.pungi_timeout`.

## 0.2.18:
  - Release date: 2018-11-08
  - When no `packages` are set in input, include all the packages in a compose.

## 0.2.17:
  - Release date: 2018-11-07
  - Retry when there are issues with communication with Pulp.
  - Commit the session at the end of ODCS jobs to ensure there is no idle
    transaction.

## 0.2.16:
  - Release date: 2018-11-06
  - Fix exception in get_reusable_compose with Python3.
  - Add support for building composes including particular Koji builds.
    See README.md for more infomration.
  - Show proper error message when requested Koji tag does not exist.
  - Fix composes stuck in "generating" state in case of compose failing
    early in the compose process.

## 0.2.15:
  - Release date: 2018-10-03
  - Do not add base module into the compose and do not accept it in 'source'.

## 0.2.14:
  - Release date: 2018-09-21
  - Fix issue when renewed compose did not respect the `sigkeys` value of
    original compose.
  - Fix issue with missing Pungi errors in `Compose.state_reason`.

## 0.2.13:
  - Release date: 2018-09-12
  - Add `multilib_arch` and `multilib_method` lists to the API - see the
    README.md description for more infomration.
  - The Koji event value is reused for composes from the same Koji tag if
    the Koji tag and its parents did not change since the last compose. This
    makes composes comming in bursts from the same Koji tag much faster.

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
