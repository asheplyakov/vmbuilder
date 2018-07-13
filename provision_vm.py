#!/usr/bin/env python

import os
import glob
import stat
import subprocess
import sys
from optparse import OptionParser

from miscutils import padded

SWAP_MB = 4096
SWAP_LABEL = 'MOREVM'
CONFIG_DRIVE_MB = 4


def _provision(vdisk, img=None,
               config_drive_img=None,
               swap_size=None,
               swap_label=None,
               orig_size=None,
               first_partition_offset=None):
    # skip verification of the source image
    vdisk = get_dm_lv_name(vdisk)
    verify_blockdev(vdisk)
    fixup_vdisk_ownership(vdisk)
    deactivate_partitions(vdisk, permissive=True)
    partition_vhd(vdisk,
                  root_start=first_partition_offset,
                  swap_size=swap_size,
                  config_drive_size=CONFIG_DRIVE_MB * 1024 * 2,
                  min_root_size=orig_size)
    copy_boot_loader(vdisk, img=img,
                     first_partition_offset=first_partition_offset)
    activate_partitions(vdisk)
    rootdev = '{0}1'.format(vdisk)
    clone_rootfs(rootdev, img=img, offset=first_partition_offset)
    if config_drive_img:
        config_drive_dev = '{0}3'.format(vdisk)
        copy_config_drive(config_drive_img, config_drive_dev)

    swapdev = '{0}2'.format(vdisk)
    run_mkswap(swapdev, '-f', '-L', swap_label)
    deactivate_partitions(vdisk)


def provision(vdisks,
              img=None,
              config_drives=None,
              swap_size=SWAP_MB * 1024 * 2,
              swap_label=SWAP_LABEL):
    verify_raw_image(img)
    orig_size, first_partition_offset = guess_first_partition_size_offset(img)

    for vdisk, config_drive_img in zip(vdisks, padded(config_drives)):
        _provision(vdisk, img=img,
                   config_drive_img=config_drive_img,
                   orig_size=orig_size,
                   first_partition_offset=first_partition_offset,
                   swap_size=swap_size,
                   swap_label=swap_label)


def clone_rootfs(dst, img=None, offset=0):
    cmd = ['e2image', '-p', '-aro', str(offset * 512), img, dst]
    subprocess.check_call(cmd)
    disable_ext4_journal(dst)
    run_e2fsck(dst, '-f', '-p')
    resize2fs(dst, '-p')
    run_e2fsck(dst, '-f', '-p', '-D')


def copy_boot_loader(vdisk, img=None,
                     first_partition_offset=None):
    def run_dd(**kwargs):
        cmd = ['dd', 'if=%s' % img, 'of=%s' % vdisk]
        cmd.extend('{0}={1}'.format(k, v) for k, v in kwargs.iteritems())
        cmd.extend(['conv=fsync'])
        subprocess.check_call(cmd)

    bootarea_size = first_partition_offset - 1
    run_dd(bs='446c', count=1)
    run_dd(bs='512c', seek=1, skip=1, count=bootarea_size)


def partition_vhd(vdisk,
                  root_start=None,
                  swap_size=None,
                  min_root_size=None,
                  config_drive_size=None):
    vdisk = get_dm_lv_name(vdisk)
    disk_size = subprocess.check_output(['blockdev', '--getsz', vdisk])
    disk_size = int(disk_size.strip())
    min_disk_size = swap_size + min_root_size + root_start + config_drive_size
    if disk_size < min_disk_size:
        raise RuntimeError("disk too small: {0}s < {1}s".format(disk_size,
                                                                min_disk_size))
    root_size = disk_size - root_start - swap_size - config_drive_size
    swap_start = root_start + root_size
    config_drive_start = swap_start + swap_size
    subprocess.check_call(['dd', 'if=/dev/zero', 'of=%s' % vdisk,
                           'bs=1M', 'count=1', 'conv=fsync'])
    sfdisk = subprocess.Popen(['sfdisk', '--force', '-u', 'S', vdisk],
                              stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    partition_table_tpl = """
    {vdisk}1 : start= {root_start}, size= {root_size}, Id=83, bootable
    {vdisk}2 : start= {swap_start}, size= {swap_size}, Id=82
    {vdisk}3 : start= {config_drive_start}, size= {config_drive_size}, Id=83
    {vdisk}4 : start= 0, size= 0, Id= 0
    """
    partition_table = partition_table_tpl.format(
        vdisk=vdisk,
        root_start=root_start,
        root_size=root_size,
        swap_size=swap_size,
        swap_start=swap_start,
        config_drive_start=config_drive_start,
        config_drive_size=config_drive_size)

    out, err = sfdisk.communicate(partition_table)
    rc = sfdisk.poll()
    if rc != 0:
        raise RuntimeError("sfdisk: error %d, message: %s" % (rc, err))


def guess_first_partition_size_offset(img):
    out = subprocess.check_output(['sudo', 'kpartx', '-l', img])
    # loop0p1 : 0 4192256 /dev/loop0 2048
    # loop deleted : /dev/loop0
    first_part_txt = out.split('\n')[0].strip()
    # loop0p1 : 0 4192256 /dev/loop0 2048
    part, _, start_s, end_s, bdev, offset_s = first_part_txt.split()
    size = int(end_s) - int(start_s)
    return size, int(offset_s)


def get_dm_lv_name(lvpath):
    if lvpath.startswith('/dev/mapper/'):
        return lvpath
    # lvpath = /dev/as-ubuntu-vg/saceph-osd1-os
    _, _, vg, lv = lvpath.strip().split('/')

    def escape(s):
        return s.replace('-', '--')
    return '/dev/mapper/{0}-{1}'.format(escape(vg), escape(lv))


def activate_partitions(vdisk):
    vdisk = get_dm_lv_name(vdisk)
    subprocess.check_call(['sudo', 'kpartx', '-a', vdisk])
    fixup_vdisk_ownership(vdisk)


def deactivate_partitions(vdisk, permissive=False):
    vdisk = get_dm_lv_name(vdisk)
    try:
        subprocess.check_call(['sudo', 'kpartx', '-d', vdisk])
    except subprocess.CalledProcessError:
        if not permissive:
            raise


def disable_ext4_journal(bdev):
    cmd = 'tune2fs -O ^has_journal'.split()
    cmd.append(bdev)
    subprocess.check_call(cmd)


def resize2fs(bdev, *args):
    cmd = ['resize2fs']
    cmd.extend(args)
    cmd.append(bdev)
    subprocess.check_call(cmd)


def run_e2fsck(bdev, *args):
    cmd = ['e2fsck']
    cmd.extend(args)
    cmd.append(bdev)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        good_retcodes = (
            0,  # everything is OK
            1,  # errors have been fixed
        )
        if e.returncode not in good_retcodes:
            raise


def run_mkswap(bdev, *args):
    cmd = ['mkswap']
    cmd.extend(args)
    cmd.append(bdev)
    subprocess.check_call(cmd)


def verify_blockdev(vdisk):
    st_mode = os.stat(vdisk).st_mode
    if stat.S_ISLNK(st_mode):
        verify_blockdev(os.path.realpath(vdisk))
    if not stat.S_ISBLK(st_mode):
        raise ValueError("{0} is not a block device: {1} ({2}".
                         format(vdisk, st_mode, stat.S_ISBLK))


def verify_raw_image(img):
    cmd = 'qemu-img info -f raw'.split()
    cmd.append(img)
    subprocess.check_call(cmd)


def fixup_vdisk_ownership(vdisk):
    gid = os.getgid()
    for bdev in glob.glob(vdisk + '*'):
        subprocess.check_call(['sudo', 'chmod', '660', bdev])
        subprocess.check_call(['sudo', 'chgrp', str(gid), bdev])


def run_dd(src, dst, **kwargs):
    cmd = ['dd', 'if=%s' % src, 'of=%s' % dst]
    cmd.extend('{0}={1}'.format(k, v) for k, v in kwargs.iteritems())
    subprocess.check_call(cmd)


def copy_config_drive(src, dst):
    run_dd(src, dst, bs='512c', conv='fsync')


def main():
    parser = OptionParser()
    parser.add_option('-i', dest='image', help='source image, must be raw')
    parser.add_option('-c', dest='config_drive', help='config drive image')
    parser.add_option('-l', '--swap-label', dest='swap_label',
                      default=SWAP_LABEL,
                      help='swap partition label')
    parser.add_option('-s', '--swap-size', dest='swap_size', type=int,
                      default=SWAP_MB,
                      help='swap size in MBs')
    options, args = parser.parse_args()
    if (not options.image) or len(args) == 0:
        print("image and vdisk parameters are mandatory")
        sys.exit(1)
    provision(args,
              img=options.image,
              config_drives=[options.config_drive],
              swap_size=options.swap_size * 1024 * 2,
              swap_label=options.swap_label)
    sys.exit(0)


if __name__ == '__main__':
    main()
