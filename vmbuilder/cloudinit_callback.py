#!/usr/bin/env python
# coding: utf-8
# Purpose: receives provisioned VMs info via cloud-init phone_home

from __future__ import absolute_import

import os
try:
    import Queue
except ImportError:
    import queue as Queue
import random
import string
import sys
import web

from collections import OrderedDict
from optparse import OptionParser
from threading import Thread, Event

from .sshutils import update_known_hosts, SshConfigGenerator
from .miscutils import (
    safe_save_file,
    mkdir_p,
)


class VMRegister(object):
    """POST handler which invokes CloudInitWebCallback

    web.py can't handle requests by an arbitrary callback, instead it
    insists on a class with a POST/GET/DELETE/UPDATE methods.
    """

    def POST(self):
        kwargs = {
            'hostname': web.input().hostname,
            'ip': web.ctx.ip,
            'ssh_key': web.input().pub_key_rsa.strip(),
            'instance_id': web.input().instance_id.strip(),
            'user_agent': web.ctx.env['HTTP_USER_AGENT'],
        }
        cb = web.ctx.globals.callback
        cb(**kwargs)


class InventoryGenerator(object):
    """Generate ansible inventory from data reported by cloud-init
    """
    def __init__(self, vms, filename=None):
        self._filename = filename
        self._inventory = OrderedDict((role, []) for role in
            ['all'] + sorted(set(vm['role'] for vm in vms)))
        self._hosts_by_id = dict((vm['instance_id'], vm) for vm in vms)
        self._hosts_by_name = dict((vm['vm_name'].lower(), vm) for vm in vms)

    def _get_host(self, entry):
        host = self._hosts_by_id.get(entry['instance_id'])
        if host is None:
            host = self._hosts_by_name.get(entry['short_hostname'].lower(), {})
        return host

    def _role_of(self, entry):
        return self._get_host(entry).get('role', 'all')

    def _copy_extra_info(self, host, entry):
        extra_info = {}
        if entry['os'] == 'windows':
            admin_password = host.get('admin_password')
            if admin_password:
                extra_info['ansible_password'] = admin_password
        return extra_info

    def add(self, hostname, ip, **kwargs):
        short_hostname = hostname.split('.')[0]
        entry = {
            'short_hostname': short_hostname,
            'ip': ip,
            'instance_id': kwargs['instance_id'],
            'os': kwargs.get('os', 'unix'),
        }
        host = self._get_host(entry)
        entry.update(self._copy_extra_info(host, entry))
        role = host.get('role', 'all')
        self._inventory[role].append(entry)

    def _make_host_entry(self, host):
        if host['os'] == 'windows':
            fmt = '{short_hostname} ansible_host={ip} ansible_port=5985 '\
                  'ansible_connection=winrm ansible_winrm_scheme=http '\
                  'ansible_winrm_transport=basic ansible_user=administrator '\
                  'ansible_password={ansible_password}'
        else:
            fmt = '{short_hostname} ansible_host={ip} ansible_user=root'
        return fmt.format(**host)

    def update(self, hostname, ip, **kwargs):
        self.add(hostname, ip, **kwargs)
        self.write()

    def _write(self, thefile):
        for role, hosts in self._inventory.items():
            thefile.write('[%s]\n' % role)
            for host in hosts:
                entry = self._make_host_entry(host)
                thefile.write(entry + '\n')
        thefile.flush()

    def write(self):
        if self._filename is None:
            self._write(sys.stdout)
        else:
            mkdir_p(os.path.dirname(self._filename))
            with safe_save_file(self._filename) as f:
                self._write(f)



def guess_os(user_agent):
    if user_agent is not None and 'Windows' in user_agent:
        return 'windows'
    else:
        return 'unix'


class CloudInitWebCallback(object):
    """Accept cloud-init "phone home" POST requests
    Does two useful things
    - waits for specified VMs to be configured by cloud-init
    - manages VMs' ssh public keys in the local ~/.ssh/known_hosts file
    """
    def __init__(self, httpd_args, vms2wait=None, vm_ready_hooks=None,
                 async_hooks=[],
                 inventory_filename=None):
        self.vms2wait = vms2wait if vms2wait else {}
        self._stop_event = Event()

        self._ssh_keys_queue = Queue.Queue()
        self._async_hooks_thread = Thread(target=self._async_worker)

        # mangle sys.argv to pass the listen address to webpy
        new_argv = [sys.argv[0]]
        new_argv.extend(httpd_args)
        sys.argv = new_argv

        self._hooks = [self._vm_ready_hook]
        if vm_ready_hooks:
            self._hooks.extend(vm_ready_hooks)

        # defines the actual actions with VM info
        self._async_hooks = [
            self._update_ssh_known_hosts,
        ]
        self._async_hooks.extend(async_hooks)
        self._async_hooks.append(self._report_vm_ready)

        urls = ('/', 'VMRegister')
        self._app = web.application(urls, globals())
        self._install_callback()
        self._webapp_thread = Thread(target=self._app.run)

    def _vm_ready_hook(self, **kwargs):
        # invoked by web app on POST
        self._ssh_keys_queue.put(kwargs)

    def _update_ssh_known_hosts(self, hostname, ip, **kwargs):
        if kwargs.get('os', 'unix') == 'windows':
            return
        ssh_key = kwargs['ssh_key']
        update_known_hosts(ssh_key=ssh_key, ips=[(ip, hostname)])

    def _report_vm_ready(self, hostname, ip, **kwargs):
        ssh_key = kwargs['ssh_key']
        print("vm {0} ready, ssh_key: {1}".format(hostname, ssh_key))

    def _async_worker(self):
        seen_vms = set()
        vms2wait = set(name.lower() for name in self.vms2wait.keys())
        while seen_vms != vms2wait:
            vm_dat = self._ssh_keys_queue.get()
            if self._stop_event.is_set():
                break
            if vm_dat is None:
                continue
            extra_args = dict((k, v) for k, v in vm_dat.items()
                              if k not in ('hostname', 'ip'))
            extra_args.update(os=guess_os(vm_dat.get('user_agent')))
            for hook in self._async_hooks:
                hook(vm_dat['hostname'], vm_dat['ip'], **extra_args)
            seen_vms.add(vm_dat['hostname'].lower())
        self._app.stop()

    def _vm_called_back(self, **kwargs):
        for f in self._hooks:
            f(**kwargs)

    def _install_callback(self):
        def _install_callback():
            g = web.storage({
                'callback': self._vm_called_back
            })

            def _wrapper(handler):
                web.ctx.globals = g
                return handler()

            return _wrapper

        self._app.add_processor(_install_callback())

    def start(self):
        self._async_hooks_thread.start()
        self._webapp_thread.start()

    def join(self):
        self._webapp_thread.join()
        self._async_hooks_thread.join()

    def stop(self):
        self._stop_event.set()
        # _async_worker can be blocked on get(), so put something to
        # the queue to wake it up
        self._ssh_keys_queue.put(None)


def run_cloudinit_callback(httpd_args, vms2wait=None, vm_ready_hook=None,
                           ssh_config=None):
    vms = dict((vm, 'all') for vm in vms2wait)
    async_hooks = []
    if ssh_config:
        ssh_conf_gen = SshConfigGenerator(path=ssh_config)
        async_hooks.append(ssh_config.update)

    server = CloudInitWebCallback(httpd_args, vms2wait=vms,
                                  async_hooks=async_hooks,
                                  vm_ready_hooks=[vm_ready_hook]
                                  if vm_ready_hook else None)
    server.start()
    server.join()


def main():
    parser = OptionParser()
    parser.add_option('-l', '--listen', dest='listen',
                      default='0.0.0.0:8080',
                      help='interface/address to listen at')
    parser.add_option('-s', '--ssh-config', dest='ssh_config',
                      help='write ssh config file here')

    options, args = parser.parse_args()
    run_cloudinit_callback([options.listen], vms2wait=set(args),
                           ssh_config=options.ssh_config)


if __name__ == '__main__':
    main()
