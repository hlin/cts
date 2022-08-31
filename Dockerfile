FROM fedora:36
LABEL \
    name="ODCS application" \
    vendor="ODCS developers" \
    license="GPLv2+" \
    build-date=""
ARG cacert_url=undefined

WORKDIR /src

RUN dnf -y --setopt=install_weak_deps=False update \
    && dnf -y --setopt=install_weak_deps=False install \
        gobject-introspection \
        hardlink \
        httpd \
        libmodulemd \
        mod_auth_gssapi \
        mod_ldap \
        mod_ssl \
        pungi \
        python3-celery \
        python3-defusedxml \
        python3-fedora \
        python3-flask \
        python3-flask-login \
        python3-flask-migrate \
        python3-flask-sqlalchemy \
        python3-flufl-lock \
        python3-funcsigs \
        python3-gobject-base \
        python3-httplib2 \
        python3-kobo \
        python3-koji \
        python3-ldap \
        python3-mod_wsgi \
        python3-openidc-client \
        python3-pip \
        python3-productmd \
        python3-prometheus_client \
        python3-psutil \
        python3-psycopg2 \
        python3-pyOpenSSL \
        python3-requests \
        python3-requests-kerberos \
        python3-six \
        python3-sqlalchemy \
        python3-systemd \
        syslinux \
        systemd \
    && dnf -y clean all \
    && rm -f /tmp/*

RUN if [ "$cacert_url" != "undefined" ]; then \
        cd /etc/pki/ca-trust/source/anchors \
        && curl -O --insecure $cacert_url \
        && update-ca-trust extract; \
    fi

COPY . .
RUN pip3 install . --no-deps

WORKDIR /tmp
USER 1001
EXPOSE 8080
