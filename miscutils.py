
# encoding: utf-8
import subprocess


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
