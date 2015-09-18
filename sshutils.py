
import os
import subprocess

from dnsutils import guess_fqdn

KNOWN_HOSTS_FILE = os.path.expanduser('~/.ssh/known_hosts')


def get_authorized_keys(authorized_keys_file=None):
    if not authorized_keys_file:
        authorized_keys_file = os.path.expanduser('~/.ssh/authorized_keys')
    with open(authorized_keys_file, 'r') as f:
        keys = f.readlines()
    return keys


def check_ssh_known_host(name_or_ip, known_hosts_file=KNOWN_HOSTS_FILE):
    """Check if the known_hosts_file contains ssh key of the given host"""
    try:
        subprocess.check_call(['ssh-keygen', '-F', name_or_ip,
                               '-f', known_hosts_file])
        return True
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return False
        else:
            raise


def remove_ssh_known_host(name_or_ip, known_hosts_file=KNOWN_HOSTS_FILE):
    """Remove ssh keys of the given host from known_hosts_file"""
    if not known_hosts_file:
        known_hosts_file = os.path.expanduser('~/.ssh/known_hosts')
    while check_ssh_known_host(name_or_ip, known_hosts_file=known_hosts_file):
        subprocess.call(['ssh-keygen', '-f', known_hosts_file,
                         '-R', name_or_ip])


def update_known_hosts(ips=None, ssh_key=None,
                       known_hosts_file=KNOWN_HOSTS_FILE):
    """Update ssh key of the specified host from known_hosts_file

    ips = [('10.20.0.2', 'fuelmaster'), ('10.20.0.3', 'node1')]
    update_known_hosts(ips=ips, ssh_key='foobar')
    """

    for ip, hostname in ips:
        # wipe out the old keys (if any)
        remove_ssh_known_host(hostname)
        remove_ssh_known_host(guess_fqdn(ip=ip, hostname=hostname))
        # Remove entries having the same IP just in a case. Note that
        # addr might be None for several reasons (VM is down at the moment,
        # network configuration is still in progress, etc)
        if ip:
            remove_ssh_known_host(ip)

    if ssh_key:
        with open(known_hosts_file, 'a') as f:
            for ip, hostname in ips:
                fqdn = guess_fqdn(ip=ip, hostname=hostname)
                f.write('{fqdn} {key}\n'.format(fqdn=fqdn, key=ssh_key))
            f.flush()
