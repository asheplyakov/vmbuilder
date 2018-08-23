
from __future__ import absolute_import

import os
import stat
import tempfile

from .py3compat import subprocess


def _check_image_exists(fsimage, writable=False):
    if not os.path.exists(fsimage):
        raise RuntimeError('file %s does not exist' % fsimage)
    if not (os.path.isfile(fsimage) or isblock(fsimage)):
        raise RuntimeError('%s is not a regular file or a block device')
    flags = os.F_OK | os.R_OK | (os.W_OK if writable else 0)
    if not os.access(fsimage, flags):
        op = 'write' if writable else 'read'
        raise RuntimeError('%s: no %s permission' % op)


def isblock(path):
    return stat.S_ISBLK(os.stat(path).st_mode)


def _rm(path, fsimage):
    cmd = ['/sbin/debugfs', '-R', 'rm %s' % path, '-w', fsimage]
    with open(os.devnull, 'w') as null:
        subprocess.check_call(cmd, stdout=null, stderr=null)


def make_empty_file(path, fsimage, mode=0644, force=False):
    # XXX: unfortunately /dev/null is not good enough here since
    # debugfs copies file mode along with the content
    with tempfile.NamedTemporaryFile() as empty:
        os.ftruncate(empty.file.fileno(), 0)
        os.chmod(empty.name, mode)
        copy_file_content(empty.name, path, fsimage, force=force)


def copy_file_content(src, dest, fsimage, force=False):
    """ copy content of a local file into the filesystem image

        Nothing is written if the destination file already exists.
        Destination directory must exist.
    """

    _check_image_exists(fsimage, writable=True)
    if (not force) and file_exists(dest, fsimage):
        raise ValueError('%s already exists in %s' % (dest, fsimage))

    commands = """
    rm {dest}
    cd {dir}
    write {src} {fname}
    """.format(src=src,
               dest=dest,
               dir=os.path.dirname(dest),
               fname=os.path.basename(dest))

    debugfs = subprocess.Popen(['/sbin/debugfs', '-f', '/dev/stdin',
                                '-w', fsimage],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    out, err = debugfs.communicate(commands)
    rc = debugfs.poll()
    if rc != 0:
        raise RuntimeError('debugfs: exit code %d, error %s' % (rc, err))


def file_exists(path, fsimage):
    """ check if a file exists in the filesystem image """
    _check_image_exists(fsimage)
    fname = os.path.basename(path)
    dir = os.path.dirname(path)
    request = 'dirsearch {dir} {fname}'.format(dir=dir, fname=fname)
    cmd = ['/sbin/debugfs', '-R', request, fsimage]
    with open(os.devnull, 'w') as null:
        out = subprocess.check_output(cmd, stderr=null)
    return out.lower().startswith('entry found')


def rm(path, fsimage):
    """ remove a file from the ext[234] filesystem image """
    _check_image_exists(fsimage, writable=True)
    if file_exists(path, fsimage):
        _rm(path, fsimage)
    if file_exists(path, fsimage):
        raise RuntimeError('failed to remove %s from %s' % (path, fsimage))
    return path
