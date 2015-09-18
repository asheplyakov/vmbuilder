
import os
import stat

from thinpool import vgs as lvm_vgs, NoSuchVG


def partition_base_device(dev, abspath=False):
    """Guess the base device for a given partition
    Example: partition_base_device('/dev/loop0p1') == '/dev/loop0'
    """
    dev = os.path.realpath(dev)
    if not stat.S_ISBLK(os.lstat(dev).st_mode):
        raise ValueError("{}: not a block device".format(dev))
    devname = os.path.basename(dev)
    if os.path.isdir(os.path.join('/sys/block', devname)):
        return dev
    for base in os.listdir('/sys/block'):
        if os.path.exists(os.path.join('/sys/block', base, devname)):
            fmt = '/dev/{}' if abspath else '{}'
            return fmt.format(base)
    raise ValueError("no base device for {}".format(dev))


def drive_is_ssd(orig_dev):
    """Check if device (whole drive or a partition) is an SSD"""
    dev = orig_dev
    while True:
        dev = os.path.realpath(dev)
        st = os.lstat(dev)
        if not stat.S_ISBLK(st.st_mode):
            raise ValueError("{}: not a block device".format(dev))
        M, m = os.major(st.st_rdev), os.minor(st.st_rdev)
        sysfs_dir = '/sys/dev/block/{M}:{m}'.format(M=M, m=m)
        if not os.path.exists(sysfs_dir):
            raise RuntimeError("device {0}: no sysfs entry {1}"
                               .format(dev, sysfs_dir))
        rotational = '{}/queue/rotational'.format(sysfs_dir)
        if os.path.isfile(rotational):
            break
        else:
            base_dev = partition_base_device(dev, abspath=True)
            if base_dev == dev:
                return False
            dev = base_dev

    with open(rotational, 'r') as f:
        return int(f.read()) == 0


def vg_is_ssd(vg_name):
    """Check if the drive backing the volume group is an SSD"""
    vg = lvm_vgs().get(vg_name)
    if not vg:
        raise NoSuchVG(vg_name)
    return all(drive_is_ssd(pv) for pv in vg)
