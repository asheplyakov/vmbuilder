====================================
Quick and dirty VM provisioning tool
====================================

Synopsis
========

A tool to setup a small local virtual lab within a reasonable time (a minute
or two). Makes VMs with a minimal OS installation manageable by ansible.
Can provision Windows VMs too. Intended for functional testing of network
applications.


BIG RED WARNING
===============

The tool manipulates host's logical volumes. Thus it's possible
to wipe out the host drive due to a misconfiguration (or bugs).


Requirements
============

- host: Ubuntu (16.04 or newer) or ALTLinux (p8)
- `sudo` access
- access to the local libvirt daemon (with `virsh` command)
- LVM thin pool for the VMs storage
- ansible


Supported guests
================

- ALTLinux (p8)
- Fedora (28)
- Ubuntu 16.04
- Windows 2008 R2


Preparing the host
==================

* Install ansible
* Clone the repository
  ::
    git clone git://github.com/asheplyakov/vmbuilder.git
    cd vmbuilder
* Run the `host-setup.yml` playbook
  ::
    ansible-playbook -K host-setup.yml
  (omit `-K` if you've got passwordless `sudo`)


Usage
=====

* Define the lab/cluster: how many VMs, RAM, virtual drive size,
  OS/distribution, etc, see the `examples` directory
* Start provisioning ::
    ./bin/vmbuilder -r -c mylab.yml
* Wait until the tool completes
* On success the inventory file (called after the cluster name) and
  `.ssh/config` is created, so one further configure the lab (and/or
  execute tests) with ansible


Removing the lab
================

::
  python -m vmbuilder.vmbuilder -d -c mylab.yml

This will immediately shutdown (`destroy`) VMs, undefine them, and release
their storage (thin volumes). Obviously there's no way to undo this action.

