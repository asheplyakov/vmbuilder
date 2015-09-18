#!/usr/bin/env python

import glob
import subprocess
import sys
from optparse import OptionParser
from xml.etree import ElementTree


def get_vm_harddrives(vmname, host_path_filter=None):
    vmxml_str = subprocess.check_output(['virsh', 'dumpxml', vmname])
    vmxml = ElementTree.fromstring(vmxml_str)
    # Extract virtual hard drives list (excluding CD-ROMs) from libvirt XML
    #
    # <devices>
    #   <disk type='file' device='disk'>
    #     <driver name='qemu' type='raw'/>
    #     <source dev='/dev/wdgreen/saceph-mon-os'/>
    #  </disk>
    disks_xml = vmxml.findall("devices/disk[@device='disk']")
    # Get the backing (host) device from the virtual HD description
    #     <source dev='/dev/wdgreen/saceph-mon-os'/>

    def get_host_bdev_or_file(dxml):
        # <source dev='/dev/wdgreen/saceph-mon-os'/>
        # <source file='/srv/libvirt/images/saceph-mon-os.qcow2'/>
        # <source pool='foo' volume='bar'/>
        src_xml = dxml.findall('source')[0]
        pool = src_xml.get('pool')
        volume = src_xml.get('volume')
        if pool:
            hfile = subprocess.check_output(['virsh', 'vol-path',
                                             '--pool', pool, volume]).strip()
        else:
            hfile = src_xml.get('dev') or src_xml.get('file')
        return hfile

    bdevs = [get_host_bdev_or_file(dxml) for dxml in disks_xml]
    if host_path_filter:
        return glob.fnmatch.filter(bdevs, host_path_filter)
    else:
        return bdevs


def main():
    parser = OptionParser()
    parser.add_option('-f', dest='path_filter',
                      help='show only drives having the host path '
                      'matching the specified pattern')
    options, args = parser.parse_args()
    if len(args) < 1:
        print("Usage: get-vm-harddrives <VM-name> [-f filter]")
        sys.exit(1)
    for vmname in args:
        host_devices = get_vm_harddrives(vmname,
                                         host_path_filter=options.path_filter)
        print('\n'.join(host_devices))
    sys.exit(0)


if __name__ == '__main__':
    main()
