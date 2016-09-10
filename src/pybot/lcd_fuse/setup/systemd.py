# -*- coding: utf-8 -*-

import os
import grp

import pbsystemd.helpers

__author__ = 'Eric Pascual'

SERVICE_NAME = 'lcdfs'

MOUNT_POINT = '/mnt/lcdfs'
GROUP_NAME = 'lcdfs'


def install_service():
    def before_start():
        if not os.path.exists(MOUNT_POINT):
            os.mkdir(MOUNT_POINT, 0o755)
            os.chown(MOUNT_POINT, 0, grp.getgrnam(GROUP_NAME).gr_gid)

    pbsystemd.helpers.install_unit(SERVICE_NAME, __name__, before_start=before_start)


def remove_service():
    pbsystemd.helpers.remove_unit(SERVICE_NAME, __name__)
