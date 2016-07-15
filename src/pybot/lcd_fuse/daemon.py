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


def run_daemon(mount_point, dev_type='LCD03', logger=None):
    daemon_logger = logger or logging.getLogger('daemon')

    device = None
    try:
        from pybot.raspi import i2c_bus

    except ImportError:
        from dummy import DummyDevice
        device = DummyDevice()
        daemon_logger.warn('not running on RasPi => using dummy device')

    else:
        device_class = None
        if dev_type == 'lcd03':
            from pybot.lcd.lcd_i2c import LCD03
            device_class = LCD03

        elif dev_type == 'lcd05':
            from pybot.lcd.lcd_i2c import LCD05
            device_class = LCD05

        elif '.' in dev_type:
            parts = dev_type.split('.')
            module_name = '.'.join(parts[:-1])
            class_name = parts[-1]
            try:
                import importlib
                module = importlib.import_module(module_name)

            except ImportError:
                exit('unsupported device type (module not found: %s)' % dev_type)
            else:
                try:
                    device_class = getattr(module, class_name)
                except AttributeError:
                    exit('unsupported device type (class not found: %s)' % dev_type)

        else:
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
            LCDFileSystem(device, logger=daemon_logger.getChild('fuse')),
            mount_point,
            nothreads=True, foreground=False, debug=False, direct_io=True,
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

    BUILTIN_TYPES = ('lcd03', 'lcd05')

    def dev_type(s):
        if '.' in s or s.lower() in BUILTIN_TYPES:
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
        default=BUILTIN_TYPES[0],
        help="type of LCD, either builtin (%s) or fully qualified class name" % ('|'.join(BUILTIN_TYPES))
    )
    args = parser.parse_args()

    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    run_daemon(args.mount_point, args.dev_type, logger=logger)

    logger.info('-' * 10 + ' terminated')

if __name__ == '__main__':
    main()
