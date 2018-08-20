#!/usr/bin/env python

from __future__ import absolute_import

import copy
import jinja2
import optparse
import os
import shutil
import sys
import uuid

from . import TEMPLATE_DIR
from .autounattend import Woe2008Autounattend
from .py3compat import subprocess


BUILD_DIR = os.path.expanduser('~/.cache/vmbuilder/config-drive')


class NoCloudGenerator(object):
    def __init__(self, vm_name=None, distro=None, template_dir=None):
        self.vm_name = vm_name or 'vm'
        self.distro = distro or 'ubuntu'
        self.template_dir = template_dir or TEMPLATE_DIR
        self._base_dir = os.path.join(BUILD_DIR, vm_name)
        self._iso_path = os.path.join(BUILD_DIR, '%s-config.iso' % vm_name)

    def _write(self, strdat, name):
        if not os.path.exists(self._base_dir):
            print("mkdir -p %s" % self._base_dir)
            os.makedirs(self._base_dir)
        with open(os.path.join(self._base_dir, name), 'w') as f:
            f.write(strdat)
            f.flush()

    def _prepare(self, data):
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(self.template_dir))
        for what in ('user-data', 'meta-data'):
            template_path = '{0}/config-drive/{1}'.format(self.distro, what)
            template = env.get_or_select_template(template_path)
            out = template.render(data)
            self._write(out, what)

    def _make_iso(self):
        tmp_iso = '%s.tmp' % self._iso_path
        subprocess.check_call(['genisoimage',
                               '-quiet',
                               '-input-charset', 'utf-8',
                               '-volid', 'cidata',
                               '-joliet',
                               '-rock',
                               '-output', tmp_iso,
                               self._base_dir])
        shutil.move(tmp_iso, self._iso_path)

    def generate(self, data):
        self._prepare(data)
        self._make_iso()
        return self._iso_path


def pick_generator(distro):
    generators = {
        'woe2008': Woe2008Autounattend,
    }
    return generators.get(distro, NoCloudGenerator)


def generate_cc(dat, vm_name=None, template_dir=TEMPLATE_DIR):
    data = copy.deepcopy(dat)
    extra_data = {
        'vm_name': vm_name,
        'vm_uuid': uuid.uuid4(),
    }
    data.update(extra_data)

    generatorClass = pick_generator(dat['distro'])
    gen = generatorClass(vm_name=vm_name, distro=dat['distro'],
                         template_dir=template_dir)
    return gen.generate(data)


def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--ceph-release', dest='ceph_release',
                      help='ceph release to install')
    parser.add_option('-D', '--distro', dest='distro', default='ubuntu',
                      help='distro (Ubuntu, Fedora)')
    parser.add_option('-d', '--distro-release', dest='distro_release',
                      help='distro release codename (trusty, xenial)')
    parser.add_option('--callback-url', dest='web_callback_url',
                      help='VM phone home URL')
    parser.add_option('-t', '--template-dir', dest='template_dir',
                      default=TEMPLATE_DIR,
                      help='config drive template dir')
    parser.add_option('--http-proxy', dest='http_proxy',
                      help='HTTP proxy for VMs')
    parser.add_option('-i', '--hypervisor-ip', dest='hypervisor_ip',
                      help='hypervisor IP as seen from VMs')
    options, args = parser.parse_args()
    data = {
        'distro': options.distro,
        'ceph_release': options.ceph_release,
        'distro_release': options.distro_release,
        'http_proxy': options.http_proxy,
        'hypervisor_ip': options.hypervisor_ip,
        'web_callback_url': options.web_callback_url,
    }
    for vm_name in args:
        generate_cc(data, vm_name=vm_name, distro=options.distro,
                    template_dir=options.template_dir)


if __name__ == '__main__':
    main()
    sys.exit(0)
