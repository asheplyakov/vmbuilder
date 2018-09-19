#!/usr/bin/env python

from setuptools import setup

setup(name='vmbuilder',
      version='0.0.1',
      description='Quick and dirty VM provisioning tool',
      author='Alexey Sheplyakov',
      author_email='asheplyakov@yandex.ru',
      url='https://github.com/asheplyakov/vmbuilder',
      packages=['vmbuilder'],
      scripts=['bin/vmbuilder'],
      package_data={
          'vmbuilder': [
              'templates/altlinux/config-drive/meta-data',
              'templates/altlinux/config-drive/user-data',
              'templates/fedora/config-drive/meta-data',
              'templates/fedora/config-drive/user-data',
              'templates/generic/config-drive/meta-data',
              'templates/generic/config-drive/user-data',
              'templates/ubuntu/config-drive/meta-data',
              'templates/ubuntu/config-drive/user-data',
              'templates/vm.xml',
              'templates/vm_woe.xml',
              'templates/woe2008/AnsibleSetup.bat',
              'templates/woe2008/Autounattend.xml',
              'templates/woe2008/ConfigureRemotingForAnsible.ps1',
              'templates/woe2008/Upgrade-PowerShell.ps1',
              'templates/woe10/AnsibleSetup.bat',
              'templates/woe10/Autounattend.xml',
              'templates/woe10/fixnetwork.ps1',
              'templates/woe10/ConfigureRemotingForAnsible.ps1',
              'templates/woe10/Upgrade-PowerShell.ps1',
          ],
      },
      data_files=[
          ('share/doc/vmbuilder/examples', [
              'examples/alt.yml',
              'examples/linux_woe.yml',
              'examples/mixed.yml',
          ]),
      ],
      install_requires=[
          'Jinja2>=2.8.1,<=2.10.1',
          'web.py>=0.37,<=0.39',
      ],
      classifiers=[
          'Development Status :: 3 - Alpha',
          'Intended Audience :: Developers',
          'License :: DFSG approved',
          'Operating System :: POSIX :: Linux',
          'Programming Language :: Python :: 2.7',
          'Topic :: System :: Installation/Setup',
      ],
)
