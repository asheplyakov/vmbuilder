#!/usr/bin/env python

from __future__ import absolute_import

import copy
import optparse
import os
try:
    import Queue
except ImportError:
    import queue as Queue
import uuid
import yaml

from collections import defaultdict
from multiprocessing.pool import ThreadPool as ThreadPool
from threading import Semaphore

from .gen_cloud_conf import generate_cc
from .make_vm import redefine_vm
from .miscutils import (
    forward_thread_exceptions,
    refresh_sudo_credentials,
    yaml_ordered_load,
)

from .provision_vm import get_provision_method
from .driveutils import vg_is_ssd
from .py3compat import (
    subprocess,
    raise_exception,
)
from .sshutils import get_authorized_keys
from .virtutils import destroy_vm, start_vm, libvirt_net_host_ip
from .cloudinit_callback import CloudInitWebCallback

MY_DIR = os.path.abspath(os.path.dirname(__file__))
## --- configuration section starts here --- ##
IMG_CACHE_DIR = '/srv/data/Public/img'
## --- configuration section ends here --- ##

WEB_CALLBACK_URL = 'http://{hypervisor_ip}:8080'


def rebuild_vms(vm_dict,
                cluster_def=None,
                redefine=False,
                delete=False,
                parallel=0,
                parallel_provision=0):
    if vm_dict is None:
        vm_dict = cluster_def['hosts']
    vm_list = [(vm, role) for role in vm_dict for vm in vm_dict[role]]
    vm_count = len(vm_list)
    if delete:
        for vm, _ in vm_list:
            destroy_vm(vm['name'], undefine=True, purge=True)
        return

    storage_conf = cluster_def['machine']['drives']
    source_image_data = cluster_def['source_image']
    distro = cluster_def.get('distro', 'ubuntu')

    # VMs heavily use disk on first boot (dist-upgrade, install additional
    # packages, etc). Therefore one might want to limit the number of VMs
    # which do initial configuration step concurrently.
    if not parallel:
        parallel = vm_count
    # Typically all virtual hard drives are backed by the same physical hard
    # drive, therefore having too many e2image processes increases the
    # provisioning time due to extra disk seeks. However for SSD backed LVs
    # having multiple writers is OK and improves the performance.
    if not parallel_provision:
        os_vg = storage_conf['os']['vg']
        parallel_provision = max(vm_count / 2, 1) if vg_is_ssd(os_vg) else 1

    source_image = prepare_cloud_img(source_image_data,
                                     cluster_def=cluster_def)

    vm_start_throttle_sem = Semaphore(parallel)
    provisioned = Queue.Queue()
    vms2wait = set([vm['name'] for vm, _ in vm_list])

    # runs in the web callback thread
    def vm_ready_cb(**kwargs):
        # invoked when cloud-init "phones home"
        # it's ok to start one more VM
        vm_start_throttle_sem.release()

    inventory = 'hosts_%s.txt' % cluster_def.get('cluster_name', 'unknown')
    callback_worker = CloudInitWebCallback([web_callback_addr(cluster_def)],
                                           vms2wait=dict((vm['name'], role)
                                                         for vm, role in vm_list),
                                           vm_ready_hooks=[vm_ready_cb],
                                           inventory_filename=inventory)
    tpool = ThreadPool(processes=parallel_provision)

    # runs in the provisioning thread
    @forward_thread_exceptions(provisioned)
    def _rebuild_vm(vm_and_role):
        vm_def = copy.deepcopy(vm_and_role[0])
        vm_def['role'] = vm_and_role[1]
        vm_def = merge_vm_info(cluster_def, vm_def)
        vm_name = vm_def['vm_name']
        vm_def['drives']['config_image'] = generate_cc(vm_def)
        if redefine:
            redefine_vm(vm_def,
                        template=vm_def['vm_template'])
        vdisk = '/dev/{vg}/{vm}-os'.format(vg=vm_def['drives']['os']['vg'],
                                           vm=vm_name)
        destroy_vm(vm_name)

        provision = get_provision_method(vm_def['distro'])

        provision([vdisk],
                  img=vm_def['drives']['install_image'],
                  config_drives=[vm_def['drives']['config_image']],
                  swap_size=vm_def['swap_size'] * 1024 * 2,
                  swap_label=vm_def['swap_label'])
        provisioned.put(vm_name)

    refresh_sudo_credentials()
    callback_worker.start()
    tpool.map_async(_rebuild_vm, vm_list)

    started = set()
    extype, exvalue, bt = None, None, None
    while started != vms2wait:
        vm_name = provisioned.get()
        if isinstance(vm_name, tuple):
            # error happend while provisioning the VM
            callback_worker.stop()
            extype, exvalue, bt = vm_name
            break
        # at most *parallel* VMs concurrently booting the provisioned OS
        vm_start_throttle_sem.acquire()
        start_vm(vm_name)
        started.add(vm_name)

    tpool.close()
    tpool.join()
    callback_worker.join()
    if extype is not None:
        raise_exception(extype, exvalue, bt)


def prepare_cloud_img(source_image_data, cluster_def=None, force=False):
    if 'path' in source_image_data:
        img_path = os.path.expanduser(source_image_data['path'])
    elif 'url' in source_image_data:
        img_url_tpl = source_image_data['url']
        distro_release = cluster_def['distro_release']
        img_url = img_url_tpl.format(distro_release=distro_release)
        img_name = img_url.split('/')[-1] + '.raw'
        img_path = os.path.join(IMG_CACHE_DIR, img_name)
    else:
        raise ValueError("Either image path or URL must be specified")

    if os.path.isfile(img_path) and not force:
        return img_path

    orig_img = img_path.rsplit('.raw', 1)[0]
    if not os.path.isfile(orig_img) or force:
        subprocess.check_call(['wget', '-N', '-O', orig_img, img_url])

    cmd = 'qemu-img convert -f qcow2 -O raw'.split()
    cmd.extend([orig_img, '{}.tmp'.format(img_path)])
    subprocess.check_call(cmd)
    os.rename('{}.tmp'.format(img_path), img_path)
    return img_path


def merge_vm_info(cluster_def, vm_def):

    new_vm_def = copy.deepcopy(vm_def)
    new_vm_def['vm_name'] = new_vm_def['name']

    builtin_machine = {
        'cpu_count': 1,
        'base_ram': 1024,
        'max_ram': 2048,
        'swap_size': 2048,
        'swap_label': 'MOREVM',
        'vm_template': 'vm.xml',
        'graphics': {},
        'vm_uuid': uuid.uuid4(),
    }

    def _base_param(var):
        val = vm_def.get(var)
        if val is None:
            val = cluster_def['machine'].get(var)
        if val is None:
            val = builtin_machine[var]
        return val

    for var in builtin_machine.keys():
        new_vm_def[var] = _base_param(var)

    required_params = (
        'distro',
        'distro_release',
        'admin_password',
    )

    for var in required_params:
        new_vm_def[var] = vm_def.get(var, cluster_def[var])

    def _param(name):
        return vm_def.get(name, cluster_def[name])

    def copy_optional_param(dst, var):
        if var in vm_def:
            dst[var] = vm_def[var]

    drives = copy.deepcopy(cluster_def['machine']['drives'])
    drives.update(vm_def.get('drives', {}))

    extra_drives = {
        'install_image': os.path.expanduser(_param('source_image')['path']),
    }
    # copy_optional_param(extra_drives, 'config_image')
    drives.update(extra_drives)
    new_vm_def.update(drives=drives)

    interfaces = copy.deepcopy(cluster_def['machine']['interfaces'])
    interfaces.update(vm_def.get('interfaces', {}))
    new_vm_def.update(interfaces=interfaces)

    auth_data = {
        'ssh_authorized_keys': get_authorized_keys(),
        'whoami': os.environ['USER'],
    }
    new_vm_def.update(auth_data)

    interfaces = cluster_def['machine']['interfaces']
    bridge_ip = libvirt_net_host_ip(interfaces['default']['source_net'])
    new_vm_def.update(hypervisor_ip=bridge_ip)

    http_proxy_tpl = cluster_def.get('net_conf', {}).get('http_proxy')
    http_proxy = http_proxy_tpl.format(hypervisor_ip=bridge_ip) \
       if http_proxy_tpl else None
    new_vm_def.update(http_proxy=http_proxy)

    web_callback_url = cluster_def.get('net_conf', {}).\
        get('web_callback_url', WEB_CALLBACK_URL)
    web_callback_url = web_callback_url.format(hypervisor_ip=bridge_ip)
    web_callback_addr = web_callback_url.split('http://', 1)[1]
    new_vm_def.update(web_callback_url=web_callback_url,
                      web_callback_addr=web_callback_addr)
    return new_vm_def


def web_callback_addr(cluster_def):
    stub = {'name': 'dummy', 'role': 'dummy'}
    return merge_vm_info(cluster_def, stub)['web_callback_addr']


def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--cluster', dest='paramsfile',
                      help='cluster definition (yaml)')
    parser.add_option('-r', '--redefine', dest='redefine',
                      default=False, action='store_true',
                      help='redefine VM according to template')
    parser.add_option('-d', '--delete', dest='delete',
                      default=False, action='store_true',
                      help='remove specified VMs and reclaim their disk space')
    parser.add_option('-j', '--parallel', dest='parallel',
                      type=int, default=0,
                      help='concurrency level (default: # of VMs)')
    parser.add_option('-p', '--provision-jobs', dest='parallel_provision',
                      type=int, default=0,
                      help='privisioning concurrency level ('
                      'default: 1 for HDD, # of VMs for SSD)')
    options, args = parser.parse_args()

    if not options.paramsfile:
        raise ValueError('cluster definition file must be specified')

    with open(options.paramsfile, 'r') as f:
        cluster_def = yaml_ordered_load(f)

    vm_dict = None
    if args:
        # saceph-mon:mons saceph-mon2:mons
        vm_dict = defaultdict(list)
        for entry in args:
            name, role = entry.split(':')
            vm_dict[role].append(name)
        vm_dict = dict(vm_dict)

    rebuild_vms(vm_dict,
                cluster_def=cluster_def,
                redefine=options.redefine,
                delete=options.delete,
                parallel=options.parallel,
                parallel_provision=options.parallel_provision)


if __name__ == '__main__':
    main()
