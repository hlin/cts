# ODCS change log

All notable changes to this project will be documented in this file.

## 0.2.50
  - Release date: 2020-09-08
  - Bug fixes for the client code
  - Allow CTS url as an empty string (which disables the integration)
  - Stop creating odcs-$id.repo files for raw config composes
  - Don't remove compose if a latest- symlink points to it
  - Allow module composes with scratch module builds only
  - Add support for RPM scratch builds

## 0.2.49
  - Release date: 2020-08-18
  - Set expiration for `run_cleanup` task
  - Stop creating latest symlinks with Pungi
  - Add metrics for composes and backends
  - Improve error reporting for pulp composes
  - Add support for module scratch builds
  - Allow Jinja2 templating in raw config wrapper config
  - Support regenerating raw config composes using the stored configuration dump
  - Add parent relationship to composes

## 0.2.48
  - Release date: 2020-06-19
  - Add simple index page
  - Remove python3-flower from container image
  - Expose default GPG keys via about API
  - Allow unsigned packages in deployment tests
  - Skip generating composeinfo-base.json if CTS is configured

## 0.2.47
  - Release date: 2020-05-21
  - docs: Improve description of finding latest modules
  - client: Improve documentation for sigkeys
  - client: List all source types
  - Pass compose label to Pungi if set
  - client: Accept OpenIDC token stored in a file
  - Add missing 'modules' parser for create-module <modules>
  - Fix Compose.result_repofile_path

## 0.2.46
  - Release date: 2020-04-29
  - ODCS client: Add --watch argument to watch the compose log.
  - Add missing 'odcs.' prefix for fedora-messaging messages.
  - Install odcs-promote-compose script.
  - Add the --nightly/--ci/--test/--production Pungi options according to compose_type.
  - Reschedule compose task in case it is stuck in 'wait' state.

## 0.2.45
  - Release date: 2020-04-21
  - Set celery task ID for regenerated composes.
  - Really generate the composes in the `odcs-$COMPOSE_ID` directorires.

## 0.2.44
  - Release date: 2020-04-20
  - NOTE: Before upgrading to this version, at first update to
    0.2.43 and run it for some time so all the composes have symlinks
    generated in the new `odcs-$COMPOSE_ID` format.
  - Store composes in directories in `odcs-$COMPOSE_ID` format.
  - Find and use only latest repository from Pulp.
  - Allow limiting the users/groups to execute just particular raw_configs.

## 0.2.43
  - Release date: 2020-04-07
  - Include raw_config_urls and allowed_clients in /api/1/about response.
  - Allow setting `sigkeys` when renewing the compose.
  - Fix traceback when renewing old compose.

## 0.2.42
  - Release date: 2020-04-01
  - Fix bad merge resolution in client
  - Limit Pungi log parsing output to 2kB and stop loading the entire file into
    memory at once.
  - Create `odcs-$ID` symlink pointing to compose top level directory
  - Retry downloading repodata from Pulp

## 0.2.41
  - Release date: 2020-03-19
  - Do not reuse old compose with different target directory.
  - Add --target-dir to ODCS client.
  - Fix API response when older composes have target directories set to None.

## 0.2.40
  - Release date: 2020-03-16
  - Allow reusing old raw config composes to make their generation faster.
  - Store Celery task ID in the database.
  - Support canceling waiting composes by their owners.
  - Allow configuring multiple target directories.

## 0.2.39
  - Release date: 2020-03-04
  - The `seconds-to-live` API argument has been renamed to `seconds_to_live`
    to make the API consistent. The `seconds-to-live` name is still supported,
    but it is not mentioned in documentation anymore.
  - Show URLs to error logs in state_reason in case compose fails.
  - Fix checking of compose input if user is in multiple groups with
    different permissions.
  - Allow setting pungi_timeout per raw_config.
  - Introduce new odcs.client.odcs.ODCS.request_compose method to make
    requests easier.

## 0.2.38
  - Release date: 2020-02-20
  - Use correct ComposeInfo for raw configs
  - Allow limiting which compose types a particular user can use
  - Generate symlinks with real compose ID for easier consumption of raw config
    composes
  - Drop fedmsg for publishing events
  - Add ignore_abset_pulp_repos flag.
  - Run validation on raw configs with optional and configurable schema
    overrides.
  - Store dump of raw config in the database.
  - Allow using regexes in routing_rules.
  - Add timeouts to all download operations.

## 0.2.37
  - Release date: 2019-11-11
  - Handle two pulp repos with the same relative_url in single content set.
  - Add support for fedora-messaging.
  - Set Celery's server_hostname only if requested by config.

## 0.2.36
  - Release date: 2019-10-03
  - Port to libmodulemd version 2.

## 0.2.35
  - Release date: 2019-09-25
  - Track time of transition from waiting to generating state and use it to
    fail stuck composes.
  - Update `time_to_expire` when compose is finished.
  - Use py3 and list all the RPMs included in resulting compose in deployment tests.
  - Group `shutil.rmtree` errors by directory to not flood the ODCS logs.

## 0.2.34
  - Release date: 2019-08-20
  - Add new `include_done_modules` flag to generate compose with modules in
    `done` state.
  - If the input module is defined by complete NSVC, allow using it even if
    it is in `done` state and not in `ready` state.

## 0.2.33
  - Release date: 2019-08-05
  - Fix the wrong order of "modules" and "groups" in variants.xml
  - Cleanup lost Mock chroots before starting new one.
  - Add "quiet" option to odcs client.
  - Add development documentation.

## 0.2.32
  - Release date: 2019-07-15
  - Do not execute generation of compose which is not in 'wait' state.
  - Remove the Mock chroot also in case of exception in runroot command.
  - Disable GssapiBasicAuth in frontend for security reasons.
  - Support generating repo with koji_event.

## 0.2.31
  - Release date: 2019-06-14
  - Remove the Mock runroot root after the last `run` method of session is done.
  - Continue removing expired compose despite the error in `shutil.rmtree`.
  - Add ~ to the list of allowed characters for REST API input.

## 0.2.30
  - Release date: 2019-05-16
  - Use locks which work across multiple backend processes in KojiTagCache.
  - Allow defining extra mount points for odcs-mock-runroot.

## 0.2.29
  - Release date: 2019-05-09
  - Add new `odcs_celery_router_config` to configure how tasks are routed
    into the different Celery queues.

## 0.2.28
  - Release date: 2019-05-07
  - Fix compose renew when using Celery distributed task queue.
  - Do not override commit hash when using raw_config source type.
  - Log Pungi stdout and stderr to compose directory.
  - Add "odcs-mock-runroot" script to allow generating runroot tasks.

## 0.2.27
  - Release date: 2019-04-03
  - Fix issues with generating raw_config composes.

## 0.2.26
  - Release date: 2019-04-03
  - Fix compatibility of Celery code with older versions of python-amqp.
  - Store raw_config composes in the same directory layout as normal ones and
    enable their expiration the same way as we do for normal composes.

## 0.2.25
  - Release date: 2019-03-25
  - Fix compatibility with Pulp > 2.7
  - Allow using SSL with SNI headers in Celery broker URL.
  - Add queue for Celery cleanup tasks.

## 0.2.24
  - Release date: 2019-03-11
  - Fix issue with "include_unpublished_pulp_repos" when compose contains
    two or more content-sets which need to be merged. In this case, ODCS
    overwrote the first merged repo with the second merged repo. In this
    release, this is fixed by storing merged repos in directories prefixed
    with the content-set name.
  - Allow deploying ODCS as Celery application.
  - Include all modules in modular Koji tag in compose by default.
  - Fix traceback when executing "odcs" client without any argument.
    Show help instead.
  - Add "docs" directory with basic ODCS documentation.

## 0.2.23
  - Release date: 2019-02-15
  - Add support for hybrid composes - composes with both modular and normal
    RPMs.
  - Allow creating composes with -devel modules.
  - Fix wrong syntax in "odcs" client tool.

## 0.2.22
  - Release date: 2019-02-01
  - Fix 0.2.21 regression when passing check_deps option to Pungi which
    was wrongly set to int instead of bool.

## 0.2.21
  - Release date: 2019-01-29
  - Add "pungi_compose" source type to generate compose containing the same
    set of packages as another Pungi compose. The packages are still taken
    from the Koji to ensure they come from the trusted source.
  - Add "check_deps" flag. When set, the compose will fail in case some
    dependencies between the packages cannot be resolved.
  - Add "lookaside_repos" variable. It can be set to list of extra repositories
    which are considered when resolving dependencies between packages which
    end up in a compose.

## 0.2.20:
  - Release date: 2019-01-03
  - Return HTTP 401 error instead of HTTP 500 error in case of Unauthorized.
  - Fix generation of composes with modules with the same NSV but different
    contexts.

## 0.2.19:
  - Release date: 2018-11-27
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
