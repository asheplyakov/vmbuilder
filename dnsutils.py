
# encoding: utf-8
# Poor man's dnspython to avoid dependencies on non-standard modules

import exceptions
import subprocess


class NoSuchHost(exceptions.Exception):
    pass


class NoSuchIp(exceptions.Exception):
    pass


def dns_reverse_resolve(ip, server=None):
    cmd = ['dig', '+noall', '+answer', '-x', ip]
    if server:
        cmd.append('@' + server)
    out = subprocess.check_output(cmd)
    if not out:
        raise NoSuchIp(ip)
    # 21.0.253.10.in-addr.arpa. 0   IN  PTR saceph-mon.vm.ceph.asheplyakov.
    try:
        fqdn = out.strip().rsplit(None, -1)[-1]
    except IndexError:
        if server:
            msg = "server {0} can't resolve {1}".format(server, ip)
        else:
            msg = "can't resolve {}".format(ip)
        raise NoSuchIp(msg)
    return fqdn.rstrip('.')


def dns_resolve(name, server=None):
    cmd = ['dig', '+noall', '+answer', name]
    if server:
        cmd.append('@' + server)
    out = subprocess.check_output(cmd)
    # saceph-adm.vm.ceph.asheplyakov. 0 IN    A      10.253.0.142
    try:
        return out.strip().rsplit(None, -1)[-1]
    except IndexError:
        msg = "DNS can't resolve {}".format(name)
        if server:
            msg = "DNS server {0} can't resolve {1}".format(server, name)
        raise NoSuchHost(msg)


def guess_fqdn(ip=None, hostname=None):
    if '.' in hostname:
        return hostname
    else:
        try:
            return dns_reverse_resolve(ip) if ip else hostname
        except NoSuchIp:
            print("WARNING: ip %s can't be resolved" % ip)
            return hostname
