#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" File system daemon main """

import sys
import os
import logging
from argparse import ArgumentTypeError

from fuse import FUSE

from pybot.core import cli
from .lcdfs import LCDFileSystem

__author__ = 'Eric Pascual'

logging.basicConfig(
    format="[%(levelname).1s] %(name)-12s > %(message)s"
)
logger = logging.getLogger('lcdfs')
daemon_logger = logger.getChild('daemon')


def run_daemon(mount_point, dev_type='panel'):
    device = None
    try:
        from pybot.raspi import i2c_bus

    except ImportError:
        from dummy import DummyDevice
        device = DummyDevice()
        daemon_logger.warn('not running on RasPi => using dummy device')

    else:
        device_class = None
        if dev_type == 'panel':
            try:
                from pybot.youpi2.ctlpanel import ControlPanel
            except ImportError:
                exit('unsupported device type')
            else:
                device_class = ControlPanel

        else:
            try:
                from pybot.lcd import lcd_i2c

                device_class = {
                    'lcd03': lcd_i2c.LCD03,
                    'lcd05': lcd_i2c.LCD05
                }[dev_type]
            except KeyError:
                exit('unsupported device type')

        if device_class:
            from pybot.lcd.ansi import ANSITerm

            daemon_logger.info('terminal device type : %s', device_class.__name__)
            device = ANSITerm(device_class(i2c_bus))
        else:
            exit('cannot determine device type')

    try:
        mount_point = os.path.abspath(mount_point)
        daemon_logger.info('starting FUSE daemon (mount point: %s)', mount_point)
        FUSE(
            LCDFileSystem(device, logger=logger),
            mount_point,
            nothreads=True, foreground=True, debug=False
        )
        daemon_logger.info('FUSE daemon stopped')
    except RuntimeError as e:
        sys.exit(1)


def main():
    """ No-arg main, for usage as console_script setup entry point

    ..see:: setuptools documentation
    """
    try:
        import pkg_resources
    except ImportError:
        pass
    else:
        PKG_NAME = 'pybot-lcd-fuse'
        version = pkg_resources.require(PKG_NAME)[0].version
        logger.info('%s version : %s', PKG_NAME, version)

    VALID_TYPES = ('lcd03', 'lcd05', 'panel')

    def dev_type(s):
        s = str(s).lower()
        if s in VALID_TYPES:
            return s

        raise ArgumentTypeError('invalid LCD type')

    def existing_dir(s):
        if not os.path.isdir(s):
            raise ArgumentTypeError('path not found or not a dir (%s)' % s)

        return s

    parser = cli.get_argument_parser()
    parser.add_argument(
        'mount_point',
        nargs='?',
        help='file system mount point',
        type=existing_dir,
        default='/sys/class/lcd'
    )
    parser.add_argument(
        '-t', '--device-type',
        dest='dev_type',
        type=dev_type,
        default=VALID_TYPES[0],
        help="type of LCD (%s)" % ('|'.join(VALID_TYPES))
    )
    args = parser.parse_args()

    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    run_daemon(args.mount_point, args.dev_type)


if __name__ == '__main__':
    main()
