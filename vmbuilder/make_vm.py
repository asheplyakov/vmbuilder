#!/usr/bin/env python

from __future__ import (absolute_import, division)

import copy
import jinja2
import optparse
import os
import shutil
import yaml
from xml.etree import ElementTree

from .virtutils import get_vm_macs, define_vm
from .virtutils import LIBVIRT_CONNECTION
from .thinpool import create_thin_lv
from . import TEMPLATE_DIR

VM_TEMPLATE = 'vm.xml'


def data_lv_name(vm_name, osd_idx=None):
    return '{vm_name}_{osd_idx}-data'.format(vm_name=vm_name,
                                             osd_idx=osd_idx)


def journal_lv_name(vm_name, osd_idx=None):
    return '{vm_name}-journal'.format(vm_name=vm_name)


def os_lv_name(vm_name, osd_idx=None):
    return '{vm_name}-os'.format(vm_name=vm_name)


def make_vm_xml(vm_def,
                net_conf=None,
                template=VM_TEMPLATE,
                template_dir=TEMPLATE_DIR,
                conn=LIBVIRT_CONNECTION):

    vm_name = vm_def['vm_name']
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
    vm_params = copy.deepcopy(vm_def)
    # keep MAC addresses stable across VM re-definitions
    old_ifaces = get_vm_macs(vm_name, conn=conn)
    ifaces = dict((name, {'source_net': iface['source_net'],
                          'mac': old_ifaces.get(iface['source_net'])})
                  for name, iface in net_conf.items())
    vm_params.update(interfaces=ifaces)

    env.filters['hex'] = hex
    env.globals.update(osd_lv_name=data_lv_name)
    tpl = env.get_or_select_template(template)
    raw_out = tpl.render(vm_params)
    try:
        new_vm_xml = ElementTree.fromstring(raw_out)
    except:
        num_out = '\n'.join('%d: %s' % (n, s)
                            for n, s in enumerate(raw_out.split('\n')))
        print("failed to parse string as XML:\n %s" % num_out)
        raise
    return new_vm_xml


def create_vm_lvs(vm_name=None,
                  role=None,
                  drives=None,
                  template_dir=TEMPLATE_DIR):

    def make_lvs(group, data, **kwargs):
        # data = {'vg': 'ssd-vg', 'thin_pool': 'vmpool'}
        lv_name = globals()['%s_lv_name' % group](vm_name, **kwargs)
        create_thin_lv(vg=drives[group]['vg'],
                       thin_pool=drives[group]['thin_pool'],
                       size=drives[group]['disk_size'],
                       name=lv_name)

    def make_nop(group, data, **kwargs):
        print('skipping group %s for vm %s' % (group, vm_name))

    def get_maker(data):
        return make_lvs if 'vg' in data else make_nop

    for group, data in drives.items():
        get_maker(data)(group, data)


def redefine_vm(vm_def,
                net_conf=None,
                template=VM_TEMPLATE,
                template_dir=TEMPLATE_DIR,
                dry_run=False,
                conn=LIBVIRT_CONNECTION):

    vm_name = vm_def['vm_name']
    new_vm_xml = make_vm_xml(vm_def,
                             net_conf=net_conf,
                             template=template,
                             template_dir=template_dir,
                             conn=conn)
    if dry_run:
        tmp_file = '%s.xml.tmp' % vm_name
        with open(tmp_file, 'w') as f:
            f.write(ElementTree.tostring(new_vm_xml))
        shutil.move(tmp_file, '%s.xml' % vm_name)
    else:
        define_vm(vm_xml=new_vm_xml, conn=conn)
        create_vm_lvs(vm_name=vm_name,
                      role=vm_def['role'],
                      drives=vm_def['drives'])


def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--cluster', dest='paramfile',
                      help='cluster parameters (yaml)')
    parser.add_option('-t', '--template', dest='template',
                      default='vm.xml',
                      help='VM XML template')
    parser.add_option('-g', '--generate', dest='generate',
                      action='store_true', default=False,
                      help='only write VM XML into file')
    options, args = parser.parse_args()
    if not options.paramfile:
        raise ValueError("cluster parameters file must be given")
    with open(options.paramfile, 'r') as f:
        cluster_def = yaml.load(f)
    if len(args) != 0:
        vms = [vm_entry.split(':') for vm_entry in args]
    else:
        hosts = cluster_def['hosts']
        vms = [(name, role) for role in hosts for name in hosts[role]]

    for vm_name, role in vms:
        redefine_vm(vm_name=vm_name,
                    role=role,
                    vm_conf=cluster_def['vm_conf'],
                    storage_conf=cluster_def['storage_conf'],
                    net_conf=cluster_def['networks'],
                    template=options.template,
                    dry_run=options.generate)


if __name__ == '__main__':
    main()
