FROM fedora:42 AS builder
WORKDIR /src
RUN dnf -y install git
COPY . .
RUN sed -i -e "s/version=.*/version='$(./get-version.sh)',/" setup.py


FROM fedora:42

ARG cacert_url=undefined
ARG build_date=unknown

LABEL \
    build-date=$build_date \
    description="Compose Tracking Service" \
    distribution-scope="public" \
    io.k8s.description="Compose Tracking Service" \
    license="MIT" \
    maintainer="CTS developers" \
    name="CTS" \
    url="https://github.com/release-engineering/cts"

WORKDIR /src

RUN dnf -y --setopt=install_weak_deps=False update \
    && dnf -v -y --setopt=install_weak_deps=False install \
        httpd \
        mod_auth_gssapi \
        mod_auth_openidc \
        mod_ldap \
        mod_ssl \
        python3-defusedxml \
        python3-fedora \
        python3-flask \
        python3-flask-login \
        python3-flask-migrate \
        python3-flask-sqlalchemy \
        python3-ldap \
        python3-marshmallow \
        python3-mod_wsgi \
        python3-openidc-client \
        python3-pip \
        python3-productmd \
        python3-prometheus_client \
        python3-psutil \
        python3-psycopg2 \
        python3-pyOpenSSL \
        python3-pyyaml \
        python3-sqlalchemy \
        python3-opentelemetry-sdk \
        python3-opentelemetry-instrumentation-flask \
        python3-opentelemetry-instrumentation-sqlalchemy \
        python3-opentelemetry-exporter-otlp-proto-http \
        # Debugging packages \
        net-tools \
        iproute \
        iputils \
        traceroute \
    && dnf -y clean all \
    && rm -f /tmp/*

RUN chmod 755 /var/log/httpd

RUN if [ "$cacert_url" != "undefined" ]; then \
        cd /etc/pki/ca-trust/source/anchors \
        && curl -O --insecure $cacert_url \
        && update-ca-trust extract; \
    fi

COPY --from=builder /src .

RUN mkdir -p /usr/share/cts && cp contrib/cts.wsgi /usr/share/cts/

# Install dependencies not available in fedora
RUN pip3 install --trusted-host pypi.org -r requirements.txt

RUN pip3 install --trusted-host pypi.org --no-deps -e .

RUN mkdir -p cts/static/ && CTS_DEVELOPER_ENV=1 cts-manager openapispec > cts/static/openapispec.json

EXPOSE 5005

CMD ["./start_cts_from_here"]
