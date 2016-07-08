# -*- coding: utf-8 -*-

import os
import sys
import grp
import shutil
import pkg_resources
import subprocess

__author__ = 'Eric Pascual'

ETC_INIT_D = '/etc/init.d'
INIT_SCRIPT = 'lcdfs'
MOUNT_POINT = '/mnt/lcdfs'
GROUP_NAME = 'lcdfs'

SERVICE_FILE = 'lcdfs.service'
ETC_SYSTEMD_SYSTEM = '/etc/systemd/system/'


def check_if_root():
    if os.geteuid() != 0:
        sys.exit("ERROR: must be root to execute")


def create_mount_point():
    if not os.path.exists(MOUNT_POINT):
        os.mkdir(MOUNT_POINT, 0o755)
        os.chown(MOUNT_POINT, 0, grp.getgrnam(GROUP_NAME).gr_gid)


def install_initd():
    check_if_root()

    fn = pkg_resources.resource_filename('pybot.lcd_fuse', 'pkg_data/%s') % INIT_SCRIPT
    shutil.copy(fn, ETC_INIT_D)
    os.chmod(os.path.join(ETC_INIT_D, INIT_SCRIPT), 0o755)
    subprocess.call('update-rc.d %s defaults' % INIT_SCRIPT, shell=True)

    create_mount_point()


def install_systemd():
    check_if_root()

    if not os.path.exists(ETC_SYSTEMD_SYSTEM):
        sys.exit("ERROR: systemd is not used in this distribution")

    fn = pkg_resources.resource_filename('pybot.lcd_fuse', 'pkg_data/%s') % SERVICE_FILE
    shutil.copy(fn, ETC_SYSTEMD_SYSTEM)
    subprocess.call('systemctl daemon-reload', shell=True)
    subprocess.call('systemctl enable %s' % SERVICE_FILE, shell=True)

    create_mount_point()

    subprocess.call('systemctl start %s' % SERVICE_FILE, shell=True)
