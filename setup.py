from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.readlines()

with open('test-requirements.txt') as f:
    test_requirements = f.readlines()

setup(name='odcs',
      description='On Demand Compose Service',
      version='0.0.1',
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
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requirements,
      tests_require=test_requirements,
      entry_points={
          'console_scripts': ['odcs-upgradedb = odcs.manage:upgradedb',
                              'odcs-gencert = odcs.manage:generatelocalhostcert',
                              'odcs-frontend = odcs.manage:runssl',
                              'odcs-backend = odcs.manage:runbackend',
                              'odcs-manager = odcs.manage:manager_wrapper'],
      },
      data_files=[('/etc/odcs/', ['conf/config.py'])]
      )
