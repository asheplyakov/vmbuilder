#!/usr/bin/env python
# encoding: utf-8
# Make libvirt VMs' names/IPs available via the DNS.
# Generates a config file for dnsmasq managed by NetworkManager so
# the "master" dnsmasq redirects DNS queries to dnsmasq's serving
# libvirt networks

import jinja2
import netaddr
import os
import subprocess
from optparse import OptionParser
from xml.etree import ElementTree

MYDIR = os.path.dirname(os.path.abspath(__file__))
NM_CONF_PATH = '/etc/NetworkManager/dnsmasq.d/libvirt_dnsmasq.conf'
NM_CONF_NAME = os.path.basename(NM_CONF_PATH)


def reverse_dns_str_pattern(vnet_ip, vnet_mask):
    """Pattern for dnsmasq reverse DNS lookups redirection

    Assume there's a libvirt managed network 10.253.0.0/24. We'd like
    to make reverse DNS lookups of VMs' IP addresses. The trick is to
    tell the host dnsmasq to redirect reverse DNS lookups to the dnsmasq
    instance serving the virtual network using

    server=/pattern/libvirt_dnsmasq_ip

    directive. This function calculates such a pattern.
    Note: the trick won't work if the network_bits is not a multiple of 8
    """
    vnet_str = '{0}/{1}'.format(vnet_ip, vnet_mask)
    vnet = netaddr.IPNetwork(vnet_str)
    rev_dns = vnet[0].reverse_dns
    # 0.0.253.10.in-addr.arpa.
    # How many zeros can we strip here?

    mask_rev_dns = vnet.netmask.reverse_dns
    # '0.255.255.255.in-addr.arpa.'
    leading_zeros = 0
    for thebyte in mask_rev_dns.split('.'):
        if thebyte != '0':
            break
        else:
            leading_zeros += 1

    # 0.0.253.10.in-addr.arpa. => 0.253.10.in-addr.arpa.
    pattern = '.'.join(rev_dns.split('.')[leading_zeros:])
    # skip the final dot
    return pattern.rstrip('.')


def get_libvirt_net_info(vnet_name, conn='qemu:///system'):
    """Query basic libvirt network info"""
    cmd = ['virsh', '-c', conn, 'net-dumpxml', vnet_name]
    raw_netxml = subprocess.check_output(cmd)
    netxml = ElementTree.fromstring(raw_netxml)
    # <network connections='1'>
    #   <name>saceph-priv</name>
    #   <bridge name='br-saceph-priv' stp='on' delay='0'/>
    #   <mac address='52:54:00:b2:7f:37'/>
    #   <domain name='vm.ceph.asheplyakov'/>
    #   <ip address='10.253.0.1' netmask='255.255.255.0'>
    ip_xml = netxml.find('ip')
    if ip_xml is None:
        raise RuntimeError("virtual network %s: no IPv4 info" % vnet_name)
    ret = {
        'ip': ip_xml.get('address'),
        'netmask': ip_xml.get('netmask'),
    }
    domain_xml = netxml.find('domain')
    if domain_xml is not None:
        ret.update(domain=domain_xml.get('name'))
    return ret


def make_dnsmasq_redirect_conf(vnet_names, conffile='libvirt_dnsmasq.conf'):
    networks = []
    for vnet_name in vnet_names:
        vnet = get_libvirt_net_info(vnet_name)
        reverse_zone = reverse_dns_str_pattern(vnet['ip'],
                                               vnet['netmask'])
        vnet_inf = {
            'host_side_ip': vnet['ip'],
            'domain': vnet['domain'],
            'reverse_zone': reverse_zone,
        }
        networks.append(vnet_inf)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(MYDIR))
    tpl = env.get_or_select_template(NM_CONF_NAME + '.tpl')
    out = tpl.render(libvirt_networks=networks)

    with open(conffile, 'w') as f:
        f.write(out)
        f.write('\n')
        f.flush()


def main():
    parser = OptionParser()
    parser.add_option('-o', dest='output', default=NM_CONF_NAME,
                      help='output file (default: %s)' % NM_CONF_NAME)
    options, libvirt_network_names = parser.parse_args()
    if len(libvirt_network_names) != 0:
        make_dnsmasq_redirect_conf(libvirt_network_names,
                                   conffile=options.output)


if __name__ == '__main__':
    main()
