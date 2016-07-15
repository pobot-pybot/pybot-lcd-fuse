#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" File system daemon main """

import sys
import os
import glob
import logging
import logging.config
from argparse import ArgumentTypeError

from fuse import FUSE

from pybot.core import cli
from .lcdfs import LCDFileSystem

__author__ = 'Eric Pascual'


def run_daemon(mount_point, dev_type='panel'):
    daemon_logger = logging.getLogger('daemon')

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
                from pybot.youpi2.ctlpanel.direct import ControlPanel
            except ImportError:
                exit('unsupported device type (%s)' % dev_type)
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
                exit('unsupported device type (%s)' % dev_type)

        if device_class:
            from pybot.lcd.ansi import ANSITerm

            daemon_logger.info('terminal device type : %s', device_class.__name__)
            device = ANSITerm(device_class(i2c_bus))
        else:
            exit('cannot determine device type')

    def cleanup_mount_point(mp):
        [os.remove(p) for p in glob.glob(os.path.join(mp, '*'))]

    try:
        mount_point = os.path.abspath(mount_point)
        cleanup_mount_point(mount_point)
        daemon_logger.info('starting FUSE daemon (mount point: %s)', mount_point)
        FUSE(
            LCDFileSystem(device, logger=logging.getLogger()),
            mount_point,
            nothreads=True, foreground=False, debug=False,
            allow_other=True
        )
        daemon_logger.info('FUSE daemon stopped')
    except RuntimeError as e:
        sys.exit(1)
    finally:
        cleanup_mount_point(mount_point)


def main():
    """ No-arg main, for usage as console_script setup entry point

    ..see:: setuptools documentation
    """
    log_dir = "/var/log" if os.geteuid() == 0 else os.path.expanduser('~')

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'verbose': {
                'format': '%(asctime)s [%(levelname).1s] %(name)s > %(message)s'
            },
            'simple': {
                'format': '%(levelname)s %(message)s'
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'verbose',
                'filename': os.path.join(log_dir, 'lcdfs.log'),
                'maxBytes': 100 * 1024,
                'backupCount': 3,
            },
            'null': {
                'class': 'logging.NullHandler'
            }
        },
        'root': {
            'handlers': ['console', 'file']
        },
        'loggers': {
            'daemon': {
                'handlers': ['null'],
            },
            'LCDFileSystem': {
                'handlers': ['null'],
            }
        }
    })

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.info('-' * 10 + ' starting')

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
        default='/mnt/lcdfs'
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

    logger.info('-' * 10 + ' terminated')

if __name__ == '__main__':
    main()
