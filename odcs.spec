Name:       odcs
Version:    0.0.1
Release:    1%{?dist}
Summary:    The On Demand Compose Service


Group:      Development/Tools
License:    MIT
URL:        https://pagure.io/odcs
Source0:    https://files.pythonhosted.org/packages/source/o/%{name}/%{name}-%{version}.tar.gz

%if 0%{?rhel} && 0%{?rhel} <= 7
# In EL7 we need flask which needs python-itsdangerous which comes from
# rhel7-extras which is only available on x86_64 for now.
ExclusiveArch: %{ix86} x86_64
%else
BuildArch:    noarch
%endif

BuildRequires:    python2-devel

BuildRequires:    git
BuildRequires:    help2man
BuildRequires:    pdc-client
BuildRequires:    pyOpenSSL
BuildRequires:    python-fedora
BuildRequires:    python-flask
BuildRequires:    python-flask-script
BuildRequires:    python-httplib2
BuildRequires:    python-m2ext
BuildRequires:    python-munch
BuildRequires:    python-six
BuildRequires:    python-sqlalchemy
BuildRequires:    python2-funcsigs
BuildRequires:    python2-modulemd >= 1.1.0
BuildRequires:    python-qpid
BuildRequires:    python-futures
BuildRequires:    python-openidc-client

%if 0%{?rhel} && 0%{?rhel} <= 7
BuildRequires:    python-setuptools
BuildRequires:    python-flask-sqlalchemy
BuildRequires:    python-flask-migrate
BuildRequires:    python-nose
BuildRequires:    python-mock
%else
BuildRequires:    python2-setuptools
BuildRequires:    python2-flask-sqlalchemy
BuildRequires:    python2-flask-migrate
BuildRequires:    python2-nose
BuildRequires:    python2-mock
BuildRequires:    python2-tabulate
%endif

BuildRequires:    systemd
%{?systemd_requires}

Requires:    systemd
Requires:    pungi
Requires:    pdc-client
Requires:    pyOpenSSL
Requires:    python-fedora
Requires:    python-flask
Requires:    python-flask-script
Requires:    python-httplib2
Requires:    python-m2ext
Requires:    python-munch
Requires:    python-six
Requires:    python-sqlalchemy
Requires:    python2-funcsigs
Requires:    python2-modulemd >= 1.1.0
Requires:    python-qpid
Requires:    python-futures
Requires:    python-openidc-client

%if 0%{?rhel} && 0%{?rhel} <= 7
Requires:    python-flask-sqlalchemy
Requires:    python-flask-migrate
Requires:    python-mock
%else
Requires:    python2-flask-sqlalchemy
Requires:    python2-flask-migrate
Requires:    python2-mock
Requires:    python2-systemd
%endif


%description
The On Demand Compose Service (ODCS) creates temporary composes using Pungi
tool and manages their lifetime. The composes can be requested by external
services or users using the REST API provided by Flask frontend.


%prep
%setup -q


%build
%py2_build


%install
%py2_install

export PYTHONPATH=%{buildroot}%{python2_sitelib}
mkdir -p %{buildroot}/%{_mandir}/man1
for command in odcs-manager odcs-frontend odcs-gencert odcs-upgradedb ; do
ODCS_CONFIG_FILE=conf/config.py help2man -N --version-string=%{version} \
    %{buildroot}/%{_bindir}/$command > \
    %{buildroot}/%{_mandir}/man1/$command.1
done


%check
nosetests-2.7 -v


%files
%doc README.md
%license LICENSE
%{python2_sitelib}/odcs*
%{_bindir}/odcs-*
%{_mandir}/man1/odcs-*.1*
%dir %{_sysconfdir}/odcs
%config(noreplace) %{_sysconfdir}/odcs/config.py
%exclude %{_sysconfdir}/odcs/*.py[co]
%exclude %{python2_sitelib}/conf/


%changelog
* Mon Jun 19 2017 Jan Kaluza <jkaluza@redhat.com> - 0.0.1-1
- Initial version of spec file
