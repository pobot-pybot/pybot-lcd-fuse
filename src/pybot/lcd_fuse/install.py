# -*- coding: utf-8 -*-

import os
import sys
import shutil
import pkg_resources
import subprocess

__author__ = 'Eric Pascual'

ETC_INIT_D = '/etc/init.d'
INIT_SCRIPT = 'lcdfs'
DAEMON_SCRIPT = 'lcdfsd'
MOUNT_POINT = '/mnt/lcdfs'
BIN = '/home/pi/.local/bin/'
GROUP_NAME = 'lcdfs'


def install_init():
    if os.geteuid() != 0:
        sys.exit("ERROR: must be root to execute")

    fn = pkg_resources.resource_filename('pybot.lcd_fuse', 'pkg_data/%s') % INIT_SCRIPT
    shutil.copy(fn, ETC_INIT_D)
    os.chmod(os.path.join(ETC_INIT_D, INIT_SCRIPT), 0o755)
    subprocess.call('update-rc.d %s defaults' % INIT_SCRIPT, shell=True)

    fn = pkg_resources.resource_filename('pybot.lcd_fuse', 'pkg_data/%s') % DAEMON_SCRIPT
    shutil.copy(fn, BIN)
    os.chmod(os.path.join(BIN, DAEMON_SCRIPT), 0o755)

    if not os.path.exists(MOUNT_POINT):
        os.mkdir(MOUNT_POINT, 0o755)
