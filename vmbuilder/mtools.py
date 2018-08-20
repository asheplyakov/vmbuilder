
import os
import sys
import threading
from .miscutils import mkdir_p
from .py3compat import subprocess


_PATH_MUTEX = threading.RLock()

with _PATH_MUTEX:
    if '/sbin' not in os.environ['PATH'].split(':'):
        os.environ['PATH'] = '/sbin:' + os.environ['PATH']


class Mtools(object):
    def __init__(self, img_path, size='1M', fat_bits=12):
        self._img = img_path
        self._size = size
        self._fat_bits = fat_bits

    def _fixeperms(self, path):
        if os.path.isfile(path) and not os.access(path, os.W_OK):
            subprocess.check_call(['sudo', 'chown', str(os.getuid()), path])

    def mkdir_p(self, path):
        if path in ('.', '..'):
            return
        subprocess.check_call(['mmd', '-D', 'o', '-i', self._img, path])

    def cp(self, local_path, path):
        self.mkdir_p(os.path.dirname(path))
        subprocess.check_call(['mcopy', '-D', 'o', '-i', self._img,
                               local_path, '::%s' % path])

    def mkfs(self):
        subprocess.check_call(['mkfs.vfat', '-F', str(self._fat_bits),
                               self._img])

    def blank(self):
        mkdir_p(os.path.dirname(self._img))
        self._fixeperms(self._img)
        subprocess.check_call(['dd', 'if=/dev/zero', 'of=%s' % self._img,
                               'bs=%s' % self._size, 'count=1',
                               'oflag=direct'])
        self.mkfs()
