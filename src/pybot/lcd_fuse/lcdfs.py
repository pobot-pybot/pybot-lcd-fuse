# -*- coding: utf-8 -*-

import sys
import os
import errno
import time
import stat
import logging
from argparse import ArgumentTypeError
from binascii import hexlify

from fuse import FUSE, Operations, FuseOSError

from pybot.core import cli
from pybot.lcd import lcd_i2c
from pybot.lcd.ansi import ANSITerm

__author__ = 'Eric Pascual'

_file_timestamp = int(time.time())
_gid = os.getgid()
_uid = os.getuid()

logging.basicConfig(
    format="[%(levelname).1s] %(name)-12s > %(message)s"
)
logger = logging.getLogger('lcdfs')
logger.setLevel(logging.INFO)


class FSEntryDescriptor(object):
    def __init__(self, handler, mtime=_file_timestamp, atime=_file_timestamp):
        self.handler = handler
        self.mtime = mtime
        self.atime = atime


class FileHandler(object):
    data = ''
    do_write = None

    def __init__(self, term):
        """
         :param pybot.lcd.ansi.ANSITerm term:
        """
        self.terminal = term

    @property
    def is_read_only(self):
        return self.do_write is None

    @property
    def size(self):
        return len(self.data)

    def write(self, data):
        if self.is_read_only:
            raise FuseOSError(errno.EACCES)

        try:
            self.data = str(self.do_write(data))
        except ValueError:
            return 0
        else:
            return len(str(data))

    def read(self):
        return self.data


class FHLevelParameter(FileHandler):
    min_level = 0
    max_level = 255

    def normalize_level(self, level):
        if isinstance(level, basestring):
            s = level.strip()
            try:
                value = int(s)
            except ValueError:
                try:
                    value = int(s, 16)
                except ValueError:
                    raise
        elif not isinstance(level, (int, float)):
            raise ValueError()
        else:
            value = level

        return int(min(self.max_level, max(value, self.min_level)))


class FHBrightness(FHLevelParameter):
    def do_write(self, data):
        level = self.normalize_level(data)
        self.terminal.device.set_brightness(level)
        return level


class FHContrast(FHLevelParameter):
    def do_write(self, data):
        level = self.normalize_level(data)
        self.terminal.device.set_contrast(level)
        return level


class FHBackLight(FHLevelParameter):
    max_level = 1

    def do_write(self, data):
        level = self.normalize_level(data)
        self.terminal.device.set_backlight(bool(level))
        return level


class FHKeys(FileHandler):
    @property
    def size(self):
        self.data = str(self.terminal.device.get_keypad_state())
        return len(self.data)


class FHLeds(FileHandler):
    def do_write(self, data):
        data = int(data)
        self.terminal.device.leds = data
        return data


class FHDisplay(FileHandler):
    def do_write(self, data):
        self.terminal.process_sequence(data)
        return len(data)


class FHInfo(FileHandler):
    def __init__(self, term):
        super(FHInfo, self).__init__(term)

        device = term.device
        self.data = ''.join([
            "%-16s : %s\n" % (k, v)
            for k, v in [
                ('rows', device.height),
                ('cols', device.width),
                ('model', device.__class__.__name__),
                ('version', device.get_version()),
                ('brightness', hasattr(device, 'brightness')),
                ('contrast', hasattr(device, 'contrast')),
            ]
        ])


class LCDFileSystem(Operations):
    def __init__(self, terminal):
        logger.setLevel(logging.DEBUG)

        self._content = {
            'backlight': FSEntryDescriptor(FHBackLight(terminal)),
            'keys': FSEntryDescriptor(FHKeys(terminal)),
            'display': FSEntryDescriptor(FHDisplay(terminal)),
            'info': FSEntryDescriptor(FHInfo(terminal)),
        }

        dev_class = terminal.device.__class__

        for attr, fname, handler_class in [
            ('brightness', 'brightness', FHBrightness),
            ('contrast', 'contrast', FHContrast),
            ('set_leds', 'leds', FHLeds),
        ]:
            if hasattr(dev_class, attr):
                logger.info('adding %s entry', fname)
                self._content[fname] = FSEntryDescriptor(handler_class(terminal))

        self._dir_entries = ['.', '..'] + self._content.keys()

        self.reset()

    DEFAULT_CONTENTS = [
            ('backlight', 1),
            ('brightness', 255),
            ('contrast', 255),
            ('leds', 0)
        ]

    def reset(self):
        for file_name, value in self.DEFAULT_CONTENTS:
            try:
                self._content[file_name].handler.write(value)
            except KeyError:
                pass

        # clear the display
        self._content['display'].handler.write('\x0c')

    def _get_descriptor(self, path):
        """
        :param path:
        :return:
        :rtype: FSEntryDescriptor
        """
        if path.startswith('/'):
            path = path[1:]
        return self._content[path]

    def readdir(self, path, fh):
        return self._dir_entries

    def getattr(self, path, fh=None):
        logger.debug('getattr(path=%s, fh=%s)', path, fh)

        fstat = {
            'st_uid': _uid,
            'st_gid': _gid,
            'st_ctime': _file_timestamp,
            'st_atime': _file_timestamp,
            'st_mtime': _file_timestamp,
        }

        if path == '/':
            fstat.update({
                'st_nlink': 2,
                'st_mode': stat.S_IFDIR | 0o755
            })
            return fstat

        try:
            fd = self._get_descriptor(path)
            fstat.update({
                'st_nlink': 1,
                'st_mode': stat.S_IFREG | (0o444 if fd.handler.is_read_only else 0o666),
                'st_size': fd.handler.size,
                'st_mtime': fd.mtime,
                'st_atime': fd.mtime,
            })
            return fstat

        except KeyError:
            raise FuseOSError(errno.ENOENT)

    def open(self, path, flags):
        logger.debug('open(%s, %d)', path, flags)

        return 1024 + self._content.keys().index(path[1:])

    def read(self, path, *args):
        logger.debug('read(%s)', path)

        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            fd.atime = time.time()
            return fd.handler.read()

    def write(self, path, data, offset, fh):
        logger.debug('write(%s, %s, %d)', path, hexlify(data.strip()), offset)

        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            retval = fd.handler.write(data)
            fd.atime = fd.mtime = time.time()
            return retval

    def truncate(self, path, length, fh=None):
        logger.debug('truncate(%s, %d)', path, length)
        pass


class DummyDevice(object):
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        self.height = 4
        self.width = 20
        self._backlight_state = None
        self._brightness_level = None
        self._contrast_level = None

    @property
    def backlight(self):
        return self._backlight_state

    @backlight.setter
    def backlight(self, on):
        self.set_backlight(on)

    @property
    def contrast(self):
        return self._contrast_level

    @contrast.setter
    def contrast(self, value):
        self.set_contrast(value)

    @property
    def brightness(self):
        return self._brightness_level

    @brightness.setter
    def brightness(self, value):
        self.set_brightness(value)

    def get_version(self):
        """ Returns the firmware version. """
        return 42

    def clear(self):
        self.logger.info('clear display')

    def home(self):
        self.logger.info('cursor home')

    def goto_pos(self, pos):
        self.logger.info('cursor moved to position %d', pos)

    def goto_line_col(self, line, col):
        self.logger.info('cursor moved to position line=%d, col=%d', line, col)

    def write(self, s):
        self.logger.info('write text : %s', s)

    def backspace(self):
        self.logger.info('backspace')

    def htab(self):
        self.logger.info('htab')

    def move_down(self):
        self.logger.info('move_down')

    def move_up(self):
        self.logger.info('move_up')

    def cr(self):
        self.logger.info('cr')

    def clear_column(self):
        self.logger.info('clear_column')

    def tab_set(self, pos):
        self.logger.info('tab set to pos=%d', pos)

    def set_backlight(self, on):
        self._backlight_state = bool(on)
        self.logger.info('back light is %s' % ('on' if on else 'off'))

    def set_brightness(self, level):
        self._brightness_level = level
        self.logger.info('back light brightness set to %d' % level)

    def set_contrast(self, level):
        self._contrast_level = level
        self.logger.info('back light contrast set to %d' % level)

    def display(self, data):
        self.logger.info('sending display sequence : %s' % data)

    def get_keypad_state(self):
        return 0b000000001001   # keys '1' and '4'


def main(mount_point, dev_type='panel'):
    device = None
    try:
        from pybot.raspi import i2c_bus

    except ImportError:
        device = DummyDevice()
        logger.warn('not running on RasPi => using dummy device')

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
                device_class = {
                    'lcd03': lcd_i2c.LCD03,
                    'lcd05': lcd_i2c.LCD05
                }[dev_type]
            except KeyError:
                exit('unsupported device type')

        if device_class:
            logger.info('terminal device type : %s', device_class.__name__)
            device = ANSITerm(device_class(i2c_bus))
        else:
            exit('cannot determine device type')

    try:
        FUSE(LCDFileSystem(device), mount_point, nothreads=True, foreground=True, debug=False)
    except RuntimeError as e:
        sys.exit(1)

if __name__ == '__main__':
    VALID_TYPES = ('lcd03', 'lcd05', 'panel')

    def dev_type(s):
        s = str(s).lower()
        if s in VALID_TYPES:
            return s

        raise ArgumentTypeError('invalid LCD type')

    parser = cli.get_argument_parser()
    parser.add_argument(
        'mount_point',
        nargs='?',
        help='file system mount point',
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
    main(args.mount_point, args.dev_type)
