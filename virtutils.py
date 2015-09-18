#!/usr/bin/env python

import os
import subprocess
from xml.etree import ElementTree

from sshutils import update_known_hosts, KNOWN_HOSTS_FILE

LIBVIRT_CONNECTION = 'qemu:///system'


def _get_device_mac(net_dev_xml):
    mac_node = net_dev_xml.find('mac')
    if mac_node is None:
        raise ValueError('Interface has no mac address [1]')
    mac = mac_node.get('address')
    if mac is None:
        raise ValueError('Interface has no mac address [2]')
    return mac


def _set_device_mac(net_dev_xml, mac):
    mac_node = net_dev_xml.find('mac')
    if mac_node is None:
        mac_node = ElementTree.Element('mac')
        net_dev_xml.insert(0, mac_node)
    mac_node.set('address', mac)


def _get_source_network(net_dev_xml):
    source_node = net_dev_xml.find('source')
    if source_node is None:
        raise ValueError('Interface is not attached to a network')
    return source_node.get('network')


def _get_vm_macs(vm_xml):
    return dict((_get_source_network(netdev_xml),
                 _get_device_mac(netdev_xml))
                for netdev_xml in _enumerate_network_devices(vm_xml))


def _get_leases_file_name(net_name):
    base_dir = '/var/lib/libvirt/dnsmasq/{0}.leases'
    leases_file_name = base_dir.format(net_name)
    return leases_file_name if os.path.exists(leases_file_name) else None


def _enumerate_network_devices(node_xml):
    return node_xml.findall("devices/interface[@type='network']")


def _get_devices_by_source_net(node_xml):
    return dict((_get_source_network(netdev_xml), netdev_xml)
                for netdev_xml in _enumerate_network_devices(node_xml))


def _get_leased_ip_by_mac(mac, leases_file_name):
    if leases_file_name is None:
        return None
    with open(leases_file_name, 'r') as lf:
        for ll in lf:
            # 1429875731 02:23:75:06:69:5a 192.168.122.250 ubuntu-mos *
            time, ifmac, ip, hostname, rest = ll.split()
            if ifmac == mac:
                return ip
    return None


def _get_iface_ip(net_dev_xml, conn=LIBVIRT_CONNECTION):
    mac = _get_device_mac(net_dev_xml)
    source_net = _get_source_network(net_dev_xml)
    domain_name = get_libvirt_net_domain(source_net, conn=conn)
    leases_file_name = _get_leases_file_name(source_net)
    ip = _get_leased_ip_by_mac(mac, leases_file_name)
    return (ip, domain_name)


def _make_fqdn(vm_name, domain_name=None):
    if domain_name:
        return '{0}.{1}'.format(vm_name, domain_name)
    else:
        return vm_name


def _get_vm_ips(dom_xml, conn=LIBVIRT_CONNECTION):
    net_devices_xml = _enumerate_network_devices(dom_xml)
    vm_name = dom_xml.find('name').text
    for dev_xml in net_devices_xml:
        ip, domain_name = _get_iface_ip(dev_xml, conn=conn)
        yield (ip, _make_fqdn(vm_name, domain_name=domain_name))


def get_libvirt_net_domain(net_name, conn=LIBVIRT_CONNECTION):
    # <network connections='1'>
    #   <name>saceph-priv</name>
    #   <uuid>f231c38f-da75-4977-8928-95be84f9953a</uuid>
    #   <bridge name='br-saceph-priv' stp='on' delay='0'/>
    #   <mac address='52:54:00:b2:7f:37'/>
    #   <domain name='vm.ceph.asheplyakov'/>
    #   <ip address='10.253.0.1' netmask='255.255.255.0'>
    #      <dhcp>
    #         <range start='10.253.0.10' end='10.253.0.254'/>
    #      </dhcp>
    #   </ip>
    # </network>
    net_xml = _net_dumpxml(net_name, conn)
    try:
        domain_xml = net_xml.findall('domain')[0]
        return domain_xml.get('name')
    except IndexError:
        return None


def libvirt_net_host_ip(net_name, conn=LIBVIRT_CONNECTION):
    # <network connections='1'>
    #   <name>saceph-priv</name>
    #   <bridge name='br-saceph-priv' stp='on' delay='0'/>
    #   <mac address='52:54:00:b2:7f:37'/>
    #   <ip address='10.253.0.1' netmask='255.255.255.0'>
    net_xml = _net_dumpxml(net_name, conn)
    ip_xml = net_xml.find('ip')
    if ip_xml is None:
        return None
    else:
        return ip_xml.get('address')


def keep_existing_mac_addresses(new_vm_xml, conn=LIBVIRT_CONNECTION):
    """Try to preserve MAC addresses if VM is already defined"""
    name = new_vm_xml.find('name').text
    if not vm_exists(name, conn=conn):
        return
    vm_xml = _virsh_dumpxml(name, conn=conn)
    new_net_devices = _get_devices_by_source_net(new_vm_xml)
    for src_net, old_dev in _get_devices_by_source_net(vm_xml).iteritems():
        if src_net in new_net_devices:
            mac = _get_device_mac(old_dev)
            new_dev = new_net_devices[src_net]
            _set_device_mac(new_dev, mac)


def get_vm_ips(name, conn=LIBVIRT_CONNECTION):
    dom_xml = _virsh_dumpxml(name, conn=conn)
    return _get_vm_ips(dom_xml, conn=conn)


def get_vm_macs(vm_name, conn=LIBVIRT_CONNECTION):
    """Get VM mac addresses along with source network names"""
    if not vm_exists(vm_name, conn):
        return {}
    vm_xml = _virsh_dumpxml(vm_name, conn)
    return _get_vm_macs(vm_xml)


def vm_exists(vm_name, conn=LIBVIRT_CONNECTION):
    try:
        subprocess.check_output(['virsh', '-c', conn, 'domstate', vm_name])
        return True
    except subprocess.CalledProcessError:
        return False


def define_vm(vm_xml=None, raw_vm_xml=None, conn=LIBVIRT_CONNECTION):
    if raw_vm_xml is None:
        raw_vm_xml = ElementTree.tostring(vm_xml)
    else:
        vm_xml = ElementTree.fromstring(raw_vm_xml)
    vm_name = vm_xml.find('name').text
    destroy_vm(vm_name, conn=conn, undefine=True)
    proc = subprocess.Popen(['virsh', '-c', conn, 'define', '/dev/stdin'],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(input=raw_vm_xml)
    except subprocess.CallledProcessError:
        print("define_vm: error: %s" % str(err))
        raise


def destroy_vm(name, undefine=False, conn=LIBVIRT_CONNECTION):
    try:
        cmd = ['virsh', '-c', conn, 'domstate', name]
        state = subprocess.check_output(cmd).strip()
    except subprocess.CalledProcessError:
        # OK, no such VM
        return
    if state.strip() == 'running':
        remove_vm_ssh_keys(vm_name=name, conn=conn)
        subprocess.check_call(['virsh', '-c', conn, 'destroy', name])
    if undefine:
        subprocess.check_call(['virsh', '-c', conn, 'undefine', name])


def update_vm_ssh_keys(ips=None, vm_name=None, ssh_key=None,
                       known_hosts_file=KNOWN_HOSTS_FILE,
                       conn=LIBVIRT_CONNECTION):
    if ips is None:
        ips = list(get_vm_ips(vm_name, conn=conn))
    update_known_hosts(ips=ips, ssh_key=ssh_key,
                       known_hosts_file=known_hosts_file)


def remove_vm_ssh_keys(ips=None, vm_name=None,
                       known_hosts_file=KNOWN_HOSTS_FILE,
                       conn=LIBVIRT_CONNECTION):
    update_vm_ssh_keys(ips=ips, vm_name=vm_name, ssh_key=None,
                       known_hosts_file=known_hosts_file,
                       conn=conn)


def destroy_undefine_vm(name, conn=LIBVIRT_CONNECTION):
    destroy_vm(name, conn=conn, undefine=True)


def start_vm(name, conn=LIBVIRT_CONNECTION):
    subprocess.check_call(['virsh', '-c', conn, 'start', name])


def _net_dumpxml(net_name, conn=LIBVIRT_CONNECTION):
    out = subprocess.check_output(['virsh', '-c', conn,
                                   'net-dumpxml', net_name])
    return ElementTree.fromstring(out.strip())


def _virsh_dumpxml(vm_name, conn=LIBVIRT_CONNECTION):
    out = subprocess.check_output(['virsh', '-c', conn, 'dumpxml', vm_name])
    return ElementTree.fromstring(out.strip())
