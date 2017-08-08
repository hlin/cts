from setuptools import setup
import os

extras_require = {}
for package in ["common", "client", "server"]:
    with open(os.path.join(package, "requirements.txt")) as f:
        extras_require[package] = f.readlines()

extras_require['all'] = list(set(
    requirement
    for requirements in extras_require.values()
    for requirement in requirements
))

with open('test-requirements.txt') as f:
    test_requirements = f.readlines()

setup(name='odcs',
      description='On Demand Compose Service',
      version='0.0.4',
      classifiers=[
          "Programming Language :: Python",
          "Topic :: Software Development :: Build Tools"
      ],
      keywords='on demand compose service modularity fedora',
      author='The Factory 2.0 Team',
      # TODO: Not sure which name would be used for mail alias,
      # but let's set this proactively to the new name.
      author_email='odcs-owner@fedoraproject.org',
      url='https://pagure.io/odcs/',
      license='GPLv2+',
      packages=["odcs", "odcs.client", "odcs.server", "odcs.common"],
      package_dir={
          "odcs": "common/odcs",
          "odcs.client": "client/odcs/client",
          "odcs.server": "server/odcs/server",
          "odcs.common": "common/odcs/common",
      },
      extras_require=extras_require,
      include_package_data=True,
      zip_safe=False,
      install_requires=extras_require["client"],
      tests_require=test_requirements,
      entry_points={
          'console_scripts': ['odcs-upgradedb = odcs.server.manage:upgradedb [server]',
                              'odcs-gencert = odcs.server.manage:generatelocalhostcert [server]',
                              'odcs-frontend = odcs.server.manage:runssl [server]',
                              'odcs.server.backend = odcs.server.manage:runbackend [server]',
                              'odcs-manager = odcs.server.manage:manager_wrapper [server]'],
      },
      )
