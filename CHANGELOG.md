# ODCS change log

All notable changes to this project will be documented in this file.

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
