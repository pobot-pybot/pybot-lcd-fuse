# -*- coding: utf-8 -*-

""" Implementation of a virtual file system for interfacing an LCD based display.

It supports the LCD03 and LCD05 from Devantech (including the optional keypad
attached), and also the custom panel built for Youpi arm, based on a LCD05
plus a 4 keys keypad and 4 LEDs.

The file system implementation is based on Terence Honles' fusepy library
(https://github.com/terencehonles/fusepy).

The exposed file system is composed of the following files:
- all types of device:
  - backlight (RW) : on/off state of the backlight (0=off, other values = on)
  - keys (R) : bit pattern of the pressed keys, as an integer value
  - info (R) : technical information about the device (inspired from the content of /proc/cpuinfo)
  - display (W) : used to send the content of the display, using ANSI sequences for text position,
    screen partial or total clearing,...
- LCD05 based devices:
  - brightness (RW) : brightness level of the backlight (0-255)
  - contrast (RW) : contrast level of the LCD (0-255)
- custom panel with LEDs:
  - leds (RW) : bit pattern of the LEDs state, as an integer value

Which files are created is automatically handled, based on the type of the used device.

The mtime of the files is updated to reflect their real modification time.
"""

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
    """ Descriptor of the file system entries.

    It bundles the file stats (atime and mtime) and the handler of the file content.
    """
    def __init__(self, handler, mtime=_file_timestamp, atime=_file_timestamp):
        self.handler = handler
        self.mtime = mtime
        self.atime = atime


class FileHandler(object):
    """ File content handler base class.

    The FH is responsible for handling the content of a file for read and/or write operations.

    This base class does not implement the real data processing for read/write operations,
    this being left to subclasses associated to each of the involved file types.
    """
    data = ''
    do_write = None

    def __init__(self, term):
        """
         :param pybot.lcd.ansi.ANSITerm term: the terminal interface by th FS
        """
        self.terminal = term

    @property
    def is_read_only(self):
        return self.do_write is None

    @property
    def size(self):
        return len(self.data)

    def write(self, data):
        """ Write operation wrapper.

        It takes care of the shared part of the process, including keeping a cache of
        the written data when the device does not provide an equivalent read feature.
        The specific one is delegated to the :py:meth:`_do_write` method, implemented
        by concrete classes

        It must be noted that write always occur from the start of the file, which means
        that its content is overwritten each time data are written into it.

        :param Any data: the data to be written, either as a string or as a numerical (integer) value
        :return: the length of the data contained in the virtual file
        :rtype: int
        """
        if self.is_read_only:
            raise FuseOSError(errno.EACCES)

        try:
            self.data = str(self.do_write(data))
        except ValueError:
            return 0
        else:
            return len(str(data))

    def _do_write(self, data):
        """ Write operation real job.

        The overridden method must implement the interaction which is supposed to
        happen with the device.

        :param Any data: the data to be written
        :return: the data to be stored in the cache of the simulated file (they will be converted
        to a string before storage)
        """
        raise NotImplementedError()

    def read(self):
        """ File content read.

        By default, returns the cache content.

        :return: the data "read" from the file
        :rtype: str
        """
        return self.data


class FHLevelParameter(FileHandler):
    """ Specialized file handler for contents representing a level in the 0-255 range.

    It adds a value normalization which clamps data provided in write operations into the
    right range.
    """
    min_level = 0
    max_level = 255

    def normalize_level(self, level):
        """ Normalizes a level by clamping it in the correct range.

        The value can be provided as a numerical one or as a string, in which case
        it will be automatically converted to an integer.

        :param level: the level to be normalized
        :return: the normalize value as an integer in 0-255 range
        :rtype: int
        """
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
    """ File handler for the 'brightness' file """
    def do_write(self, data):
        level = self.normalize_level(data)
        self.terminal.device.set_brightness(level)
        return level


class FHContrast(FHLevelParameter):
    """ File handler for the 'contrast' file """
    def do_write(self, data):
        level = self.normalize_level(data)
        self.terminal.device.set_contrast(level)
        return level


class FHBackLight(FHLevelParameter):
    """ File handler for the 'backlight' file.

    Restricts the level to the (0, 1) choices.
    """
    max_level = 1

    def do_write(self, data):
        level = self.normalize_level(data)
        self.terminal.device.set_backlight(bool(level))
        return level


class FHKeys(FileHandler):
    """ File handler for the 'keys' file.

    Since the data size is always queried by the OS when a read operation
    is made, the size evaluation process gets the data from the device and
    cache them, so that the inherited read process can work as is.
    """
    @property
    def size(self):
        self.data = str(self.terminal.device.get_keypad_state())
        return len(self.data)


class FHLeds(FileHandler):
    """ File handler for the 'leds' file.
    """
    def do_write(self, data):
        data = int(data)
        self.terminal.device.leds = data
        return data


class FHDisplay(FileHandler):
    """ File handler for the 'display' file.
    """
    def do_write(self, data):
        self.terminal.process_sequence(data)
        return len(data)


class FHInfo(FileHandler):
    """ File handler for the 'info' file.

    Since it is immutable, the content of the file is evaluated when creating
    the handler and stored in the cache.

    The content is formatted the same way as the ̀ /proc/cpuinfo` file. Here is
    an example for a panel device:

        rows             : 4
        cols             : 20
        model            : ControlPanel
        version          : 1
        brightness       : True
        contrast         : True
    """
    def __init__(self, term):
        super(FHInfo, self).__init__(term)

        device = term.device
        dev_class = device.__class__
        self.data = ''.join([
            "%-16s : %s\n" % (k, v)
            for k, v in [
                ('rows', device.height),
                ('cols', device.width),
                ('model', dev_class.__name__),
                ('version', device.get_version()),
                ('brightness', hasattr(dev_class, 'brightness')),
                ('contrast', hasattr(dev_class, 'contrast')),
            ]
        ])


class LCDFileSystem(Operations):
    """ The file system implementation
    """
    def __init__(self, terminal, logging_level=logging.INFO):
        """
        :param ANSITerm terminal: the ANSI terminal wrapping the device
        :param int logging_level: the logging level, as defined in the logging standard module
        """
        logger.setLevel(logging_level)

        dev_class = terminal.device.__class__

        self._content = {
            'backlight': FSEntryDescriptor(FHBackLight(terminal)),
            'keys': FSEntryDescriptor(FHKeys(terminal)),
            'display': FSEntryDescriptor(FHDisplay(terminal)),
            'info': FSEntryDescriptor(FHInfo(terminal)),
        }

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
        """ Resets the file system content and synchronizes the terminal state accordingly. """
        for file_name, value in self.DEFAULT_CONTENTS:
            try:
                self._content[file_name].handler.write(value)
            except KeyError:
                pass

        # clear the display
        self._content['display'].handler.write('\x0c')

    def _get_descriptor(self, path):
        """ Returns the file descriptor corresponding to a file path.

        :param str path: teh file path (relative to the file system)
        :return: the corresponding descriptor
        :rtype: FSEntryDescriptor
        :raise KeyError: if path does not exist
        """
        if path.startswith('/'):
            path = path[1:]
        return self._content[path]

    def readdir(self, path, fh):
        """ ..see:: :py:class:`fuse.Operations` """
        return self._dir_entries

    def getattr(self, path, fh=None):
        """ ..see:: :py:class:`fuse.Operations` """
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
        """ ..see:: :py:class:`fuse.Operations` """
        logger.debug('open(%s, %d)', path, flags)

        return 1024 + self._content.keys().index(path[1:])

    def read(self, path, *args):
        """ ..see:: :py:class:`fuse.Operations` """
        logger.debug('read(%s)', path)

        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            fd.atime = time.time()
            return fd.handler.read()

    def write(self, path, data, offset, fh):
        """ ..see:: :py:class:`fuse.Operations` """
        logger.debug('write(%s, %s, %d)', path, hexlify(data.strip()), offset)

        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            retval = fd.handler.write(data)
            fd.atime = fd.mtime = time.time()
            return retval


class DummyDevice(object):
    """ A dummy device for tests on a dev station """
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


def main(mount_point, dev_type='panel', logging_level=logging.INFO):
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
        FUSE(
            LCDFileSystem(device, logging_level=logging_level),
            mount_point,
            nothreads=True, foreground=True, debug=False
        )
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
    main(args.mount_point, args.dev_type, logging_level=logging.DEBUG if args.verbose else logging.INFO)
