========================
ODCS command line client
========================

ODCS provides the ``odcs`` command line client which is provided in Fedora
by ``odcs-client`` package.

In this document, most common use-cases of ODCS client are explained.

Generating compose from Koji tag
================================

The most common use-case is generating compose with packages from Koji tag.

For example, you can create compose from ``epel7`` Koji tag with packages
``httpd`` and ``mod_perl`` including their dependencies:

``$ odcs create tag epel7 "httpd mod_perl"``

If you do not want to include the dependencies in a resulting compose,
you can use the ``--flag no_deps`` flag. This will also make compose faster.

In case your Koji tag contains unsigned packages, you need to enable composes
with unsigned packages by using ``--sigkey none`` option.

Generating compose with cherry-picked modules
=============================================

ODCS is used quite often to test modules after they are built. You only
need to know ``NAME:STREAM``, ``NAME:STREA:VERSION`` or
``NAME:STREAM:VERSION:CONTEXT`` of the module you want to include in the
compose.

For example, you can create compose with latest version and all contexts of
``testmodule:master``, including its **modular** dependencies:

``$ odcs create module testmodule:master``

Again, if the packages in a module are not signed yet, you need to use
``--sigkey none``.

In case you do not want the modular dependencies in a compose, you can use
``--flag no_deps``.

**Note** that the ``platform`` module is not treated as modular dependency
and modules generated using ``create module`` sub-commands will not include
RPMs from the virtual ``platform`` module. This is done by design to not
make composes unnecessary big. You can use "hybrid" compose described
later in this doc.

Generating compose with cherry-picked Koji builds
=================================================

In case you have list of Koji builds in the NVR form, you can use them
directly to generate the compose:

``$ odcs create build "httpd-2.4.38-2.fc29 mod_perl-2.0.10-13.fc29"``

Generating hybrid compose with both modules and bare RPMs
=========================================================

TODO

Generating compose with lookaside repositories
==============================================

TODO
