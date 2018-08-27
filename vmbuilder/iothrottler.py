
from __future__ import absolute_import

from threading import Semaphore
from .driveutils import vg_is_ssd


def _os_vg(vm):
    return vm['drives']['os']['vg']


def _concurrency_level(vg, max_concurrency_level=8):
    return max_concurrency_level if vg_is_ssd(vg) else 1


class IOThrottler(object):
    """ Prevent provisioning/initial setup from thrashing hard drives """
    def __init__(self, vm_list, max_concurrency_level=8):
        backing_vgs = set(_os_vg(vm) for vm in vm_list)
        self._all_io_throttlers = dict((vg, Semaphore(_concurrency_level(vg, max_concurrency_level)))
                                       for vg in backing_vgs)
        self._io_throttlers = dict((str(vm['instance_id']),
                                    self._all_io_throttlers[_os_vg(vm)])
                                   for vm in vm_list)

    def _semaphore(self, instance_id):
        return self._io_throttlers[str(instance_id)]

    def release(self, **kwargs):
        """ called after provisioning has finished """
        self._semaphore(kwargs['instance_id']).release()

    def acquire(self, instance_id):
        """ called before starting the provisioning """
        self._semaphore(instance_id).acquire()

