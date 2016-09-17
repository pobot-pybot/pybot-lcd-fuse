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
from pybot.core import log
from .lcdfs import LCDFSOperations

__author__ = 'Eric Pascual'


def run_daemon(mount_point, dev_type='LCD03', no_splash=False):
    daemon_logger = log.getLogger('daemon')

    try:
        from pybot.raspi import i2c_bus

    except ImportError:
        from dummy import DummyDevice
        device = DummyDevice()
        daemon_logger.warn('not running on RasPi => using dummy device')

    else:
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
                raise DaemonError('unsupported device type (module not found: %s)' % module_name)
            else:
                try:
                    device_class = getattr(module, class_name)
                except AttributeError:
                    raise DaemonError('unsupported device type (class not found: %s)' % dev_type)

        else:
            raise DaemonError('unsupported device type (%s)' % dev_type)

        if device_class:
            from pybot.lcd.ansi import ANSITerm

            daemon_logger.info('terminal device type : %s', device_class.__name__)
            device = ANSITerm(device_class(i2c_bus))
        else:
            raise DaemonError('cannot determine device type')

    def cleanup_mount_point(mp):
        [os.remove(p) for p in glob.glob(os.path.join(mp, '*'))]

    exit_code = 1     # suppose error by default
    try:
        mount_point = os.path.abspath(mount_point)
        cleanup_mount_point(mount_point)
        daemon_logger.info('starting FUSE daemon (mount point: %s)', mount_point)
        FUSE(
            LCDFSOperations(device, no_splash),
            mount_point,
            nothreads=True, foreground=False, debug=False,
            direct_io=True,
            allow_other=True
        )
        daemon_logger.info('returned from FUSE()')

    except Exception as e:
        daemon_logger.fatal(e)
        exit_code = 1
    else:
        exit_code = 0
    finally:
        daemon_logger.info("cleaning up mount point")
        cleanup_mount_point(mount_point)
        daemon_logger.info('exiting with code=%d', exit_code)
        return exit_code


def main():
    """ No-arg main, for usage as console_script setup entry point

    ..see:: setuptools documentation
    """
    log_dir = "/var/log" if os.geteuid() == 0 else os.path.expanduser('~')

    logging.config.dictConfig(log.get_logging_configuration({
        'handlers': {
            'file': {
                'filename': os.path.join(log_dir, 'lcdfs.log'),
            }
        }
    }))

    logger = log.getLogger()
    logger.info('-' * 40)
    logger.info('Starting')

    try:
        import pkg_resources
    except ImportError:
        pass
    else:
        PKG_NAME = 'pybot-lcd-fuse'
        version = pkg_resources.require(PKG_NAME)[0].version
        logger.info('Version : %s', version)
    logger.info('-' * 40)

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
    parser.add_argument(
        '--no-splash',
        dest='no_splash',
        action='store_true',
        help="do not display the default splash text (host name, IP,...)"
    )
    args = parser.parse_args()

    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    def log_error_banner(error, unexpected=False):
        title = 'unexpected error' if unexpected else 'abnormal termination '
        logger.fatal((' ' + title + ' ').center(40, '!'))
        logger.fatal(error)
        logger.fatal('!' * 40)

    try:
        run_daemon(args.mount_point, args.dev_type, args.no_splash)
    except DaemonError as e:
        log_error_banner(e)
    except Exception as e:
        log_error_banner(e, unexpected=True)
    else:
        logger.info(' terminated normally '.center(40, '='))


class DaemonError(Exception):
    pass

if __name__ == '__main__':
    sys.exit(main())
