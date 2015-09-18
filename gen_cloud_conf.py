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
TEMPLATE_DIR = os.path.join(MY_DIR, 'templates/config-drive')


def render_and_save(data, vm_name=None, tmpl_dir=TEMPLATE_DIR):
    base_dir = os.path.join(BUILD_DIR, vm_name)
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_dir))
    templates = {
        'user_data': 'user-data',
        'meta-data': 'meta-data',
    }

    for tmpl_name, out_name in templates.iteritems():
        template = env.get_or_select_template(tmpl_name)
        out = template.render(data)
        out_file = os.path.join(base_dir, out_name)
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


def generate_cc(dat, vm_name=None, tmpl_dir=TEMPLATE_DIR):
    data = copy.deepcopy(dat)
    data['ssh_authorized_keys'] = get_authorized_keys()
    data['my_name'] = vm_name
    data['my_uuid'] = uuid.uuid4()
    out_dir = render_and_save(data, vm_name=vm_name, tmpl_dir=tmpl_dir)
    conf_img = os.path.join(BUILD_DIR, '{}-config.iso'.format(vm_name))
    gen_iso(out_dir, conf_img)
    return conf_img


def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--ceph-release', dest='ceph_release',
                      help='ceph release to install')
    parser.add_option('-d', '--distro-release', dest='distro_release',
                      help='distro release codename (trusty, xenial)')
    parser.add_option('--callback-url', dest='web_callback_url',
                      help='VM phone home URL')
    parser.add_option('-t', '--template-dir', dest='tmpl_dir',
                      default=TEMPLATE_DIR,
                      help='config drive template dir')
    parser.add_option('--http-proxy', dest='http_proxy',
                      help='HTTP proxy for VMs')
    parser.add_option('-i', '--hypervisor-ip', dest='hypervisor_ip',
                      help='hypervisor IP as seen from VMs')
    options, args = parser.parse_args()
    data = {
        'ceph_release': options.ceph_release,
        'distro_release': options.distro_release,
        'http_proxy': options.http_proxy,
        'hypervisor_ip': options.hypervisor_ip,
        'web_callback_url': options.web_callback_url,
    }
    for vm_name in args:
        generate_cc(data, vm_name=vm_name, tmpl_dir=options.tmpl_dir)


if __name__ == '__main__':
    main()
    sys.exit(0)
