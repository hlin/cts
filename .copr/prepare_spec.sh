dnf -y install python git fedpkg python-setuptools
ODCS_VERSION=$(python setup.py -V)
ODCS_RELEASE=$(git log -1 --pretty=format:%ct)
sed -e "s|\$ODCS_VERSION|$ODCS_VERSION|g" \
        -e "s|\$ODCS_RELEASE|$ODCS_RELEASE|g" ./.copr/odcs.spec.in > ./.copr/odcs.spec;
