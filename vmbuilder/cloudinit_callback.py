#!/usr/bin/env python
# coding: utf-8
# Purpose: receives provisioned VMs info via cloud-init phone_home

import os
import Queue
import random
import string
import sys
import web
from optparse import OptionParser
from threading import Thread, Event

from sshutils import update_known_hosts, SshConfigGenerator
from miscutils import safe_save_file


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
        }
        cb = web.ctx.globals.callback
        cb(**kwargs)


class InventoryGenerator(object):
    """Generate ansible inventory from data reported by cloud-init
    """
    def __init__(self, hosts_with_roles, filename=None):
        self._filename = filename
        self._inventory = dict((role, [])
                               for _, role in hosts_with_roles.iteritems())
        self._inventory['all'] = []
        self._hosts_with_roles = dict((host.split('.')[0], role)
                                      for host, role
                                      in hosts_with_roles.iteritems())

    def add(self, hostname, ip, ssh_key):
        short_hostname = hostname.split('.')[0]
        entry = {'host': short_hostname, 'ip': ip}
        role = self._hosts_with_roles.get(short_hostname, 'all')
        self._inventory[role].append(entry)

    def update(self, hostname, ip, ssh_key):
        self.add(hostname, ip, ssh_key)
        self.write()

    def _write(self, thefile):
        entry_format = '{hostname} ansible_host={ip} ansible_user=root'
        for role, hosts in self._inventory.iteritems():
            thefile.write('[%s]\n' % role)
            for host in hosts:
                entry = entry_format.format(hostname=host['host'],
                                            ip=host['ip'])
                thefile.write(entry + '\n')
        thefile.flush()

    def write(self):
        if self._filename is None:
            self._write(sys.stdout)
        else:
            with safe_save_file(self._filename) as f:
                self._write(f)


class CloudInitWebCallback(object):
    """Accept cloud-init "phone home" POST requests

    Does two useful things
    - waits for specified VMs to be configured by cloud-init
    - manages VMs' ssh public keys in the local ~/.ssh/known_hosts file
    """
    def __init__(self, httpd_args, vms2wait=None, vm_ready_hooks=None,
                 async_hooks=None,
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

        self._inventory_generator = InventoryGenerator(vms2wait,\
            filename=inventory_filename)
        self._ssh_config_generator = SshConfigGenerator()

        # defines the actual actions with VM info
        self._async_hooks = [
            self._update_ssh_known_hosts,
            self._inventory_generator.update,
            self._ssh_config_generator.update,
            self._report_vm_ready,
        ]
        if async_hooks:
            self._async_hooks.extend(async_hooks)

        urls = ('/', 'VMRegister')
        self._app = web.application(urls, globals())
        self._install_callback()
        self._webapp_thread = Thread(target=self._app.run)

    def _vm_ready_hook(self, **kwargs):
        # invoked by web app on POST
        self._ssh_keys_queue.put(kwargs)

    def _update_ssh_known_hosts(self, hostname, ip, ssh_key):
        update_known_hosts(ssh_key=ssh_key, ips=[(ip, hostname)])

    def _report_vm_ready(self, hostname, ip, ssh_key):
        print("vm {0} ready, ssh_key: {1}".format(hostname, ssh_key))

    def _async_worker(self):
        seen_vms = set()
        vms2wait = set(self.vms2wait.keys())
        while seen_vms != vms2wait:
            vm_dat = self._ssh_keys_queue.get()
            if self._stop_event.is_set():
                break
            if vm_dat is None:
                continue
            for hook in self._async_hooks:
                hook(vm_dat['hostname'], vm_dat['ip'], vm_dat['ssh_key'])
            seen_vms.add(vm_dat['hostname'])
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


def run_cloudinit_callback(httpd_args, vms2wait=None, vm_ready_hook=None):
    vms = {'all': list(vms2wait)}
    server = CloudInitWebCallback(httpd_args, vms2wait=vms,
                                  vm_ready_hooks=[vm_ready_hook]
                                  if vm_ready_hook else None)
    server.start()
    server.join()


def main():
    parser = OptionParser()
    parser.add_option('-l', '--listen', dest='listen',
                      default='0.0.0.0:8080',
                      help='interface/address to listen at')
    options, args = parser.parse_args()
    run_cloudinit_callback([options.listen], vms2wait=set(args))


if __name__ == '__main__':
    main()
