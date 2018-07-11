#!/usr/bin/env python

import copy
import jinja2
import optparse
import os
import shutil
import yaml
from xml.etree import ElementTree

from virtutils import get_vm_macs, define_vm
from virtutils import LIBVIRT_CONNECTION
from thinpool import create_thin_lv

MY_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(MY_DIR, 'templates')
VM_TEMPLATE = 'vm.xml'


def calc_ram_size(role, base_ram=2048, osds_per_node=2):
    if role == 'osds':
        return base_ram * osds_per_node
    elif role == 'clients':
        return base_ram / 2
    else:
        return base_ram


def vm_cpu_count(role, osds_per_node=2, base_cpu_count=2):
    if role == 'osds':
        return base_cpu_count * osds_per_node
    else:
        return base_cpu_count


def data_lv_name(vm_name, osd_idx=None):
    return '{vm_name}_{osd_idx}-data'.format(vm_name=vm_name,
                                             osd_idx=osd_idx)


def journal_lv_name(vm_name, osd_idx=None):
    return '{vm_name}-journal'.format(vm_name=vm_name)


def os_lv_name(vm_name, osd_idx=None):
    return '{vm_name}-os'.format(vm_name=vm_name)


def make_vm_xml(vm_name=None,
                role=None,
                vm_conf=None,
                storage_conf=None,
                net_conf=None,
                template=VM_TEMPLATE,
                template_dir=TEMPLATE_DIR,
                conn=LIBVIRT_CONNECTION):
    if vm_conf is None:
        raise ValueError("make_vm_xml: vm_conf=None")

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
    vm_params = copy.deepcopy(vm_conf)
    vm_params.update(vm_name=vm_name, role=role)
    osds_per_node = vm_params.get('osds_per_node', 1)
    vm_params.update(ram_mb=calc_ram_size(role,
                                          vm_conf['base_ram'],
                                          osds_per_node),
                     cpu_count=vm_cpu_count(role, osds_per_node),
                     journal_lv_name=journal_lv_name(vm_name),
                     drives=storage_conf)
    # keep MAC addresses stable across VM re-definitions
    old_ifaces = get_vm_macs(vm_name, conn=conn)
    ifaces = dict((name, {'source_net': iface['source_net'],
                          'mac': old_ifaces.get(iface['source_net'])})
                  for name, iface in net_conf.iteritems())
    vm_params.update(interfaces=ifaces)

    env.filters['hex'] = hex
    env.globals.update(osd_lv_name=data_lv_name)
    tpl = env.get_or_select_template(template)
    raw_out = tpl.render(vm_params)
    new_vm_xml = ElementTree.fromstring(raw_out)
    return new_vm_xml


def create_vm_lvs(vm_name=None,
                  role=None,
                  vm_params=None,
                  storage_conf=None,
                  template_dir=TEMPLATE_DIR):

    def make_lvs(group, **kwargs):
        # { 'os': {'vg': 'ssd-vg', 'thin_pool': 'vmpool'}, }
        drives_conf = storage_conf[group]
        lv_name = globals()['%s_lv_name' % group](vm_name, **kwargs)
        create_thin_lv(vg=drives_conf['vg'],
                       thin_pool=drives_conf['thin_pool'],
                       size=vm_params['drives'][group]['disk_size'],
                       name=lv_name)

    make_lvs('os')
    if role == 'osds':
        make_lvs('journal')
        for osd_idx in range(0, vm_params['osds_per_node']):
            make_lvs('data', osd_idx=osd_idx)


def redefine_vm(vm_name=None,
                role=None,
                vm_conf=None,
                storage_conf=None,
                net_conf=None,
                template=VM_TEMPLATE,
                template_dir=TEMPLATE_DIR,
                dry_run=False,
                conn=LIBVIRT_CONNECTION):
    new_vm_xml = make_vm_xml(vm_name=vm_name,
                             role=role,
                             vm_conf=vm_conf,
                             storage_conf=storage_conf,
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
                      role=role,
                      vm_params=vm_conf,
                      storage_conf=storage_conf)


def make_ansible_inventory(hosts_by_role,
                           template_dir=TEMPLATE_DIR,
                           template='ansible_hosts',
                           filename='hosts'):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
    tpl = env.get_or_select_template(template)
    raw_out = tpl.render(hosts_by_role)
    with open(filename, 'w') as f:
        f.write(raw_out)
        f.flush()


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
    parser.add_option('-i', '--inventory', dest='inventory',
                      action='store_true', default=False,
                      help='write ansible inventory file')
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
    if options.inventory:
        make_ansible_inventory(cluster_def['hosts'])


if __name__ == '__main__':
    main()
