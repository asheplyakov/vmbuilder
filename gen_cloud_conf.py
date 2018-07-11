#!/usr/bin/env python

import copy
import jinja2
import optparse
import os
import shutil
import subprocess
import sys
import uuid

from sshutils import get_authorized_keys

MY_DIR = os.path.abspath(os.path.dirname(__file__))
BUILD_DIR = os.path.join(MY_DIR, '.build/config-drive')
TEMPLATE_DIR = os.path.join(MY_DIR, 'templates/{distro}/config-drive')


def render_and_save(data, vm_name=None, template_dir=None):
    base_dir = os.path.join(BUILD_DIR, vm_name)
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))

    for name in ('user-data', 'meta-data'):
        template = env.get_or_select_template(name)
        out = template.render(data)
        out_file = os.path.join(base_dir, name)
        with open(out_file, 'w') as f:
            f.write(out)

    return base_dir


def gen_iso(src, dst):
    subprocess.check_call(['genisoimage',
                           '-quiet',
                           '-input-charset', 'utf-8',
                           '-volid', 'cidata',
                           '-joliet',
                           '-rock',
                           '-output', '{}.tmp'.format(dst),
                           src])
    shutil.move('{}.tmp'.format(dst), dst)


def generate_cc(dat, vm_name=None, tmpl_dir=TEMPLATE_DIR, distro='ubuntu'):
    template_dir = tmpl_dir.format(distro=distro)
    data = copy.deepcopy(dat)
    data['ssh_authorized_keys'] = get_authorized_keys()
    data['my_name'] = vm_name
    data['my_uuid'] = uuid.uuid4()
    out_dir = render_and_save(data, vm_name=vm_name, template_dir=template_dir)
    conf_img = os.path.join(BUILD_DIR, '{}-config.iso'.format(vm_name))
    gen_iso(out_dir, conf_img)
    return conf_img


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
