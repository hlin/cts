FROM fedora:28
LABEL \
    name="ODCS application" \
    vendor="ODCS developers" \
    license="GPLv2+" \
    build-date=""
ARG cacert_url=undefined

RUN cd /etc/yum.repos.d/ \
    && dnf -v -y install 'dnf-command(config-manager)' \
    && dnf config-manager --add-repo http://download-ipv4.eng.brq.redhat.com/rel-eng/RCMTOOLS/latest-RCMTOOLS-2-F-28/compose/Everything/x86_64/os/ \
    && dnf config-manager --add-repo http://download-ipv4.eng.brq.redhat.com/rel-eng/repos/eng-rhel-7/x86_64 \
    && dnf -v --nogpg -y install \
    httpd mod_wsgi mod_auth_gssapi python3-rhmsg mod_ssl python3-koji-cli-plugins python3-psycopg2 \
    odcs \
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
