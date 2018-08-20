#!/usr/bin/env python

from __future__ import absolute_import

import copy
import jinja2
import os
import sys
import tempfile

from codecs import utf_8_encode
from . import TEMPLATE_DIR
from .mtools import Mtools
from .py3compat import subprocess

BUILD_DIR = os.path.expanduser('~/.cache/vmbuilder/autounattend')


class Woe2008Autounattend(object):

    def __init__(self, vm_name=None, distro=None, template_dir=None):
        self.vm_name = vm_name or 'woe2008'
        self.distro = distro or 'woe2008'
        self.template_dir = os.path.join(template_dir or TEMPLATE_DIR,
                                         self.distro)
        self._files = []
        img_name = '%s-autounattend.img' % vm_name
        self._img_path = os.path.join(BUILD_DIR, img_name)
        self._mtools = Mtools(self._img_path)
        self._env = None

    def _write(self, strdat, rel_path):
        strdat = strdat.replace('\n', '\r\n')
        strdat = utf_8_encode(strdat)[0]
        with tempfile.NamedTemporaryFile() as f:
            f.write(strdat)
            f.flush()
            self._mtools.cp(f.name, rel_path)

    def _process(self, data):
        for rel_path in self._files:
            template = self._env.get_or_select_template(rel_path)
            out = template.render(data)
            self._write(out, rel_path)

    def _find_files(self):
        for subdir, dirs, files in os.walk(self.template_dir):
            rel_subdir = os.path.relpath(subdir, self.template_dir)
            for f in files:
                rel_file_path = os.path.join(rel_subdir, f)
                self._files.append(rel_file_path)

    def generate(self, data):
        self._find_files()
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.template_dir))
        self._mtools.blank()
        self._process(data)
        return self._img_path


def generate_autounattend(dat, vm_name=None, template_dir=TEMPLATE_DIR):
    data = copy.deepcopy(dat)
    extra_data = {
        'vm_name': vm_name,
    }
    data.update(extra_data)
    distro = dat.get('distro', 'woe2008')
    gen = Woe2008Autounattend(vm_name=vm_name,
                              distro=distro,
                              template_dir=os.path.join(template_dir, distro))
    return gen.generate(data)


def main():
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('-p', '--admin-password', default='r00tme')
    options, args = parser.parse_args()
    data = {
        'admin_password': options.admin_password,
    }
    for vm_name in args:
        generate_autounattend(data, vm_name=vm_name)


if __name__ == '__main__':
    main()
