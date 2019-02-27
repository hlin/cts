FROM fedora:28
LABEL \
    name="ODCS application" \
    vendor="ODCS developers" \
    license="GPLv2+" \
    build-date=""
ARG cacert_url=undefined

WORKDIR /src
RUN cd /etc/yum.repos.d/ \
    && dnf -v -y install 'dnf-command(config-manager)' \
    && dnf config-manager --add-repo http://download-ipv4.eng.brq.redhat.com/rel-eng/RCMTOOLS/latest-RCMTOOLS-2-F-28/compose/Everything/x86_64/os/ \
    && dnf config-manager --add-repo http://download-ipv4.eng.brq.redhat.com/rel-eng/repos/eng-rhel-7/x86_64 \
    && dnf -v --nogpg -y install \
        python3-fedmsg \
        systemd \
        pungi \
        python3-pdc-client \
        python3-fedora \
        python3-funcsigs \
        python3-openidc-client \
        python3-productmd \
        hardlink \
        libmodulemd \
        gobject-introspection \
        python3-flask-sqlalchemy \
        python3-flask-migrate \
        python3-mock \
        python3-systemd \
        python3-six \
        python3-flask \
        python3-defusedxml \
        python3-koji \
        python3-httplib2 \
        python3-pyOpenSSL \
        python3-sqlalchemy \
        python3-flufl-lock \
        python3-moksha-hub \
        python3-fedmsg \
        python3-psycopg2 \
        python3-psutil \
        python3-celery \
        python3-flower \
        python3-ldap \
        python3-gobject-base \
        python3-flask-script \
        python3-flask-login \
        rabbitmq-server \
    && dnf -y clean all \
    && rm -f /tmp/*

RUN if [ "$cacert_url" != "undefined" ]; then \
        cd /etc/pki/ca-trust/source/anchors \
        && curl -O --insecure $cacert_url \
        && update-ca-trust extract; \
    fi

COPY . .
RUN pip3 install . --no-deps
RUN rm -rf ./fedmsg.d

USER 1001
EXPOSE 8080

ENTRYPOINT celery-3 -A odcs.server.celery_tasks worker --loglevel=info -Q pungi_composes,pulp_composes
