
# encoding: utf-8
import os
import random
import string
import subprocess

from contextlib import contextmanager


def make_temp_filename(filename, prefix_len=8):
    """Make a temporary filename in the same directory as the given one"""
    suffix = ''.join(random.choice(string.ascii_letters + string.digits)
                      for _ in range(prefix_len))
    tmp_name = '.' + suffix + '_' + os.path.basename(filename)
    return os.path.join(os.path.dirname(filename), tmp_name)


@contextmanager
def safe_save_file(filename):
    """Write all data to a new file, and rename it afterwards"""
    temp_filename = make_temp_filename(filename)
    temp_file = open(temp_filename, 'w')
    try:
        yield temp_file
        temp_file.flush()
        temp_file.close()
        os.rename(temp_filename, filename)
    except:
        temp_file.close()
        raise


def padded(seq):
    """Pad the sequence with infinite None, None, None, ..."""
    try:
        for elt in seq:
            yield elt
        while True:
            yield None
    except GeneratorExit:
        pass


def refresh_sudo_credentials():
    subprocess.check_call(['sudo', '--validate'])
