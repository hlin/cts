# ODCS change log

All notable changes to this project will be documented in this file.

## [0.2.2] - 2018-04-19

  - The `packages` field is now requested for `tag` source type by frontend.
  - The `state_reason` field in frontend response now contains the error
    messages from the `pungi.global.log`, so the `state_reason` field is much
    more useful in case the compose fails.
  - New Koji Tag Cache feature is introduced to cache the Koji tag repodata.
    The cached data is reused for future composes from the same Koji tag and
    should make them much more faster.
