
import exceptions
import subprocess

from collections import defaultdict

LVM_NO_SUCH_LV = 5


class NoSuchLV(exceptions.Exception):
    pass


class NoSuchVG(exceptions.Exception):
    pass


def remove_lv(lv=None, vg=None):
    cmd = ['sudo', 'lvremove', '-f', '{0}/{1}'.format(vg, lv)]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        if e.returncode != LVM_NO_SUCH_LV:
            raise


def rename_lv(vg=None, old_lv=None, lv=None):
    cmd = ['sudo', 'lvrename', '{0}/{1}'.format(vg, old_lv),
           '{0}/{1}'.format(vg, lv)]
    print("renaming LV: %s" % ' '.join(cmd))
    subprocess.check_call(cmd)


def query_thin_lv(vg=None, lv=None, thin_pool=None):
    fields = ['pool_lv', 'data_percent', 'lv_size', 'lv_uuid']
    separator = '|'
    cmd = ['sudo', 'lvs', '--noheadings', '--nosuffix', '--units', 'm',
           '--separator', separator, '-o', ','.join(fields),
           '{0}/{1}'.format(vg, lv)]
    try:
        raw_params = subprocess.check_output(cmd).strip().split(separator)
    except subprocess.CalledProcessError as e:
        if e.returncode == LVM_NO_SUCH_LV:
            raise NoSuchLV('{0}/{1}'.format(vg, lv))
        else:
            raise
    params = dict((var, raw_params[fields.index(var)]) for var in fields)
    for numeric_var in ('lv_size', 'data_percent'):
        params[numeric_var] = float(params[numeric_var])
    if thin_pool and params['pool_lv'] != thin_pool:
        err = "lv {lv}: wrong thin pool: {actual} (expected {thin_pool})"
        raise RuntimeError(err.format(lv=lv, thin_pool=thin_pool,
                                      actual=params['pool_lv']))
    return params


def _create_thin_lv(name=None, thin_pool=None, size=None, vg=None):
    cmd = ['sudo', 'lvcreate', '-T', '{0}/{1}'.format(vg, thin_pool),
           '-n', name, '-V', '{}M'.format(size)]
    subprocess.check_call(cmd)


def thin_lv_exists(name=None, thin_pool=None, size=None, vg=None):
    """Return
    - True, True, params if LV exists and has the specified size
    - True, False, params if LV exists but has a different size/thin pool
    - False, False, None if LV does not exist (in specified VG)
    """
    try:
        params = query_thin_lv(vg=vg, lv=name)
        exists, matches = True, False
    except NoSuchLV:
        return (False, False, None)

    for var in ('pool_lv', 'lv_size'):
        if var not in params:
            msg = "lv {0}: can't find out {1}".format(name, var)
            raise RuntimeError(msg)

    if params['pool_lv'] == thin_pool:
        if size == params['lv_size']:
            return (True, True, params)
        else:
            return (True, False, params)
    else:
        return (True, False, params)


def create_thin_lv(name=None, thin_pool=None, size=None, vg=None, force=False):
    exists, matches, params = thin_lv_exists(vg=vg, thin_pool=thin_pool,
                                             name=name, size=size)
    if exists:
        if matches and not force:
            return
        else:
            remove_lv(vg=vg, lv=name)
    _create_thin_lv(name=name, thin_pool=thin_pool, size=size, vg=vg)


def create_thin_snapshot(name=None, vg=None, lv=None):
    exists, _, _ = thin_lv_exists(vg=vg, name=name)
    if exists:
        print("removing old snapshot '{0}/{1}'".format(vg, lv))
        remove_lv(vg=vg, lv=name)
    cmd = ['sudo', 'lvcreate', '-s', '-n', name, '{0}/{1}'.format(vg, lv)]
    print("creating thin snapshot: %s" % ' '.join(cmd))
    subprocess.check_call(cmd)


def revert_thin_snapshot(name=None, vg=None, lv=None, lv_path=None):
    if (not vg) or (not lv):
        vg, lv = _canonicalize_lv_path(lv_path)
    if name.startswith('/dev'):
        check_vg, new_name = _canonicalize_lv_path(name)
        if check_vg != vg:
            raise RuntimeError("can't revert snapshots across VGs")
        name = new_name

    exists, _, _ = thin_lv_exists(vg=vg, name=lv)
    if exists:
        remove_lv(vg=vg, lv=lv)
    rename_lv(vg=vg, old_lv=name, lv=lv)
    create_thin_snapshot(name=name, vg=vg, lv=lv)


def vgs():
    """ List all VGs along with their physical volumes"""
    separator = ';'
    fields = ['vg_name', 'pv_name']
    cmd = ['sudo', 'pvs', '--noheadings', '--separator', separator,
           '-o', ','.join(fields)]
    entries = subprocess.check_output(cmd).strip().split('\n')
    ret = defaultdict(list)
    for line in entries:
        values = line.strip().split(separator)
        print(values)
        vg = values[fields.index('vg_name')]
        pv = values[fields.index('pv_name')]
        ret[vg].append(pv)
    return dict(ret)


def _canonicalize_lv_path(lv_path):
    """Convert LV path to a (vg, lv) tuple"""
    if lv_path.startswith('/dev'):
        # '/dev/vg/lv'
        _, _, vg, lv = lv_path.split('/')
    else:
        # vg/lv
        vg, lv = lv_path.split('/')
    return vg, lv
