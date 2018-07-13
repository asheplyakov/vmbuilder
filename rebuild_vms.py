#!/usr/bin/env python

import optparse
import os
import Queue
import subprocess
import yaml

from collections import defaultdict
from multiprocessing.pool import ThreadPool as ThreadPool
from threading import Semaphore

from gen_cloud_conf import generate_cc
from make_vm import os_lv_name, redefine_vm
from miscutils import refresh_sudo_credentials
from provision_vm import provision
from driveutils import vg_is_ssd
from virtutils import destroy_vm, start_vm, libvirt_net_host_ip
from cloudinit_callback import CloudInitWebCallback

MY_DIR = os.path.abspath(os.path.dirname(__file__))
## --- configuration section starts here --- ##
IMG_CACHE_DIR = '/srv/data/Public/img'
## --- configuration section ends here --- ##

WEB_CALLBACK_ADDR = '{hypervisor_ip}:8080'


def rebuild_vms(vm_dict,
                cluster_def=None,
                redefine=False,
                parallel=0,
                parallel_provision=0):
    if vm_dict is None:
        vm_dict = cluster_def['hosts']
    vm_list = [(vm, role) for role in vm_dict for vm in vm_dict[role]]
    vm_count = len(vm_list)

    vm_conf = cluster_def['vm_conf']
    storage_conf = cluster_def['storage_conf']
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
    cloud_conf_data = make_cloud_conf_data(cluster_def)

    vm_start_throttle_sem = Semaphore(parallel)
    provisioned = Queue.Queue()
    vms2wait = set([vm for vm, _ in vm_list])
    web_callback_url = cloud_conf_data['web_callback_url']
    web_callback_addr = web_callback_url.split('http://', 1)[1]

    # runs in the web callback thread
    def vm_ready_cb(**kwargs):
        # invoked when cloud-init "phones home"
        # it's ok to start one more VM
        vm_start_throttle_sem.release()

    callback_worker = CloudInitWebCallback([web_callback_addr],
                                           vms2wait=vms2wait,
                                           vm_ready_hooks=[vm_ready_cb])
    tpool = ThreadPool(processes=parallel_provision)

    # runs in the provisioning thread
    def _rebuild_vm(name_role):
        vm_name, role = name_role
        if redefine:
            redefine_vm(vm_name=vm_name,
                        role=role,
                        vm_conf=vm_conf,
                        storage_conf=storage_conf,
                        net_conf=cluster_def['networks'])
        config_drive_img = generate_cc(cloud_conf_data, vm_name=vm_name, distro=distro)
        vdisk = '/dev/{vg}/{lv}'.format(vg=storage_conf['os']['vg'],
                                        lv=os_lv_name(vm_name))
        destroy_vm(vm_name)
        provision([vdisk],
                  img=source_image,
                  config_drives=[config_drive_img],
                  swap_size=vm_conf['swap_size'] * 1024 * 2,
                  swap_label=vm_conf['swap_label'])
        provisioned.put(vm_name)

    refresh_sudo_credentials()
    callback_worker.start()
    tpool.map_async(_rebuild_vm, vm_list)

    started = set()
    while started != vms2wait:
        vm_name = provisioned.get()
        # at most *parallel* VMs concurrently booting the provisioned OS
        vm_start_throttle_sem.acquire()
        start_vm(vm_name)
        started.add(vm_name)

    tpool.close()
    tpool.join()
    callback_worker.join()


def prepare_cloud_img(source_image_data, cluster_def=None, force=False):
    if 'path' in source_image_data:
        img_path = source_image_data['path']
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


def make_cloud_conf_data(cluster_def):
    cloud_conf_data = {
        'distro': cluster_def['distro'],
        'distro_release': cluster_def['distro_release'],
        'swap_size': cluster_def['vm_conf']['swap_size'],
        'swap_label': cluster_def['vm_conf']['swap_label'],
    }
    if 'ceph_release' in cluster_def:
        cloud_conf_data['ceph_release'] = cluster_def['ceph_release']

    net_conf = cluster_def['networks']
    bridge_ip = libvirt_net_host_ip(net_conf['default']['source_net'])
    cloud_conf_data.update(hypervisor_ip=bridge_ip)

    http_proxy = None
    if 'http_proxy' in cluster_def['net_conf']:
        http_proxy_tpl = cluster_def['net_conf']['http_proxy']
        http_proxy = http_proxy_tpl.format(hypervisor_ip=bridge_ip)
    cloud_conf_data.update(http_proxy=http_proxy)

    web_callback_url = cluster_def['net_conf'].get('web_callback_url')
    if not web_callback_url:
        web_callback_url = ('http://' + WEB_CALLBACK_ADDR)
    web_callback_url = web_callback_url.format(hypervisor_ip=bridge_ip)
    web_callback_addr = web_callback_url.split('http://', 1)[1]
    cloud_conf_data.update(web_callback_url=web_callback_url,
                           web_callback_addr=web_callback_addr)
    return cloud_conf_data


def main():
    parser = optparse.OptionParser()
    parser.add_option('-c', '--cluster', dest='paramsfile',
                      help='cluster definition (yaml)')
    parser.add_option('-r', '--redefine', dest='redefine',
                      default=False, action='store_true',
                      help='redefine VM according to template')
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
        cluster_def = yaml.load(f)

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
                parallel=options.parallel,
                parallel_provision=options.parallel_provision)


if __name__ == '__main__':
    main()
