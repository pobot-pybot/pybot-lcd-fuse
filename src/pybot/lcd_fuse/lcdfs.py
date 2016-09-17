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

In addition, the keypad is monitored so that key presses produce evdev key events,
just like a regular keyboard. By default, the keys of the standard 4x3 keypad are mapped to
event codes KEY_NUMERIC_[0..9], KEY_NUMERIC_STAR and KEY_NUMERIC_POUND. This behaviour can
be customized by the device attached to the terminal associated to the file system. If it
implements the :py:meth:`get_keypad_map` method, this one will be called to initialized the
mapping, which is expected to be provided as a 12 items list, each item corresponding to the
12 keys (starting from top-left one) and containing the key code to be used for the produced
event, or None if no event is to be produced (or if the key does not exist on the physical
keypad). Refer to !:py:meht:`LCDFSOperations._kp_monitor_loop` implementation for full detail.
"""

import errno
import logging
import os
import stat
import time
import grp
import threading
import binascii

from fuse import Operations, FuseOSError
from evdev import UInput, ecodes

from pybot.lcd.ansi import ANSITerm

__author__ = 'Eric Pascual'

_file_timestamp = int(time.time())
_uid = os.getuid()
_gid = grp.getgrnam('lcdfs').gr_gid


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

    def __init__(self, term, logger=None):
        """
         :param pybot.lcd.ansi.ANSITerm term: the terminal interfaced by th FS
        """
        self.terminal = term
        self.logger = logger.getChild(self.__class__.__name__) if logger else None

    @property
    def is_read_only(self):
        return self.do_write is None

    @property
    def size(self):
        return len(self.data) + 1   # add 1 for the trailing newline

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
        return self.data + '\n'


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
    """
    @property
    def size(self):
        self.data = str(self.terminal.device.get_keypad_state())
        return len(self.data) + 1

    def read(self):
        self.data = str(self.terminal.device.get_keypad_state())
        return super(FHKeys, self).read()


class FHLocked(FileHandler):
    """ File handler for the 'locked' file.
    """
    @property
    def size(self):
        return 2    # data is always 0 or 1 followed by newline

    def read(self):
        self.data = str(int(self.terminal.device.is_locked()))
        return super(FHLocked, self).read()


class FHLeds(FileHandler):
    """ File handler for the 'leds' file.
    """
    def do_write(self, data):
        data = int(data)
        self.terminal.device.set_leds_state(data)
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
        locked           : True
    """
    def __init__(self, term, **kwargs):
        super(FHInfo, self).__init__(term, **kwargs)

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
                ('locked', hasattr(dev_class, 'is_locked')),
            ]
        ])

    @property
    def size(self):
        return len(self.data)

    def read(self):
        self.logger.info('FHInfo.read')
        return self.data


class LCDFSOperations(Operations):
    """ The file system implementation
    """
    def __init__(self, terminal, no_splash=False):
        """
        :param ANSITerm terminal: the ANSI terminal wrapping the device
        :param bool no_splash: if True, do not display the splash screen after init
        """
        self.no_splash = no_splash

        self._logger = logging.getLogger(self.__class__.__name__)
        self.log_info("initializing FUSE implementation")

        self.terminal = terminal
        dev_class = terminal.device.__class__

        self._content = {
            'backlight': FSEntryDescriptor(FHBackLight(terminal, logger=self._logger)),
            'keys': FSEntryDescriptor(FHKeys(terminal, logger=self._logger)),
            'display': FSEntryDescriptor(FHDisplay(terminal, logger=self._logger)),
            'info': FSEntryDescriptor(FHInfo(terminal, logger=self._logger)),
        }

        def report_entry_creation(name, read_only):
            self.log_info('entry created : %s (%s)', name, 'R' if read_only else 'RW')

        for n, d in self._content.iteritems():
            report_entry_creation(n, d.handler.is_read_only)

        for attr, fname, handler_class in [
            ('brightness', 'brightness', FHBrightness),
            ('contrast', 'contrast', FHContrast),
            ('set_leds', 'leds', FHLeds),
            ('is_locked', 'locked', FHLocked),
        ]:
            if hasattr(dev_class, attr):
                handler = handler_class(terminal, logger=self._logger)
                self._content[fname] = FSEntryDescriptor(handler)
                report_entry_creation(fname, handler.is_read_only)

        self._dir_entries = ['.', '..'] + self._content.keys()
        self._fd = 0

        self._kp_monitor_thread = None
        self._kp_monitor_terminate = False

        self.reset()

    def _kp_monitor_loop(self):
        """ Keypad monitoring loop, running in a thread and responsible for
        sending the evdev key events corresponding to key actions.

        Th uinput instance life-cycle is entirely managed in this method.
        """
        log = logging.getLogger('uinput')
        log.info('starting keypad monitor')

        dev = self.terminal.device
        try:
            keypad_map = dev.get_keypad_map()
        except AttributeError:
            keypad_map = [
                ecodes.KEY_NUMERIC_1,
                ecodes.KEY_NUMERIC_2,
                ecodes.KEY_NUMERIC_3,
                ecodes.KEY_NUMERIC_4,
                ecodes.KEY_NUMERIC_5,
                ecodes.KEY_NUMERIC_6,
                ecodes.KEY_NUMERIC_7,
                ecodes.KEY_NUMERIC_8,
                ecodes.KEY_NUMERIC_9,
                ecodes.KEY_NUMERIC_STAR,
                ecodes.KEY_NUMERIC_0,
                ecodes.KEY_NUMERIC_POUND,
            ]

        keypad_mask = 0
        for k in reversed(keypad_map):
            keypad_mask <<= 1
            if k is not None:
                keypad_mask |= 1

        cap = {
            ecodes.EV_KEY: [ecodes.KEY_PREVIOUS, ecodes.KEY_NEXT, ecodes.KEY_ESC, ecodes.KEY_OK]
        }
        ui = UInput(cap, name='ctrl-panel')
        log.info('uinput created')

        last_state = None
        self._kp_monitor_terminate = False

        while not self._kp_monitor_terminate:
            state = dev.get_keypad_state() & keypad_mask
            changes_mask = state if last_state is None else last_state ^ state
            if changes_mask:
                log.debug('change detected : state=%d last_state=%d', state, last_state)
                last_state = state
                for i, k in enumerate(keypad_map):
                    if k is not None and (changes_mask & 1):
                        key_state = state & 1
                        value = 1 if key_state else 0
                        ui.write(ecodes.EV_KEY, k, value)
                        log.info('EV_KEY event sent (code=%s, value=%d)', ecodes.keys[k], value)
                    state >>= 1
                    changes_mask >>= 1

                ui.syn()
                log.debug('sync event sent')

            time.sleep(0.1)

        ui.close()
        log.info('uinput closed')

    def init(self, path):
        if not self.no_splash:
            import socket
            host_name = socket.gethostname()
            ip = socket.gethostbyname(host_name)
            self.terminal.write_at("host: " + host_name, line=1, col=1)
            self.terminal.write_at("ip: " + ip, line=2, col=1)

        self.log_info('initializing uinput support')
        self._kp_monitor_thread = threading.Thread(target=self._kp_monitor_loop)
        self._kp_monitor_thread.start()

    def log_info(self, *args):
        if self._logger:
            self._logger.info(*args)

    def log_warning(self, *args):
        if self._logger:
            self._logger.warning(*args)

    def log_error(self, *args):
        if self._logger:
            self._logger.error(*args)

    def log_debug(self, *args):
        if self._logger:
            self._logger.debug(*args)

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
            except FuseOSError as e:
                self.log_error("%s (file=%s)", e, file_name)
                raise

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

    def destroy(self, path):
        """ ..see:: :py:class:`fuse.Operations` """
        self.log_debug('destroy(path=%s)', path)

        if self._kp_monitor_thread:
            self.log_info('stopping keypad monitor')
            self._kp_monitor_terminate = True
            self._kp_monitor_thread.join(timeout=1)

        self.log_info('destroying file system')
        self.reset()
        self.terminal.device.set_backlight(False)

    def readdir(self, path, fh):
        """ ..see:: :py:class:`fuse.Operations` """
        return self._dir_entries

    def getattr(self, path, fh=None):
        """ ..see:: :py:class:`fuse.Operations` """
        self.log_debug('getattr(path=%s, fh=%s)', path, fh)

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
                'st_blocks': int((fd.handler.size + 511) / 512),
            })
            return fstat

        except KeyError:
            raise FuseOSError(errno.ENOENT)

    def chmod(self, path, mode):
        self.log_debug('chmod(path=%s, mode=%s)', path, mode)

    def open(self, path, flags):
        """ ..see:: :py:class:`fuse.Operations` """
        self.log_debug('open(path=%s, flags=0x%x)', path, flags)

        self._fd += 1
        return self._fd

    def read(self, path, size, offset, fh):
        """ ..see:: :py:class:`fuse.Operations` """
        self.log_debug('read(path=%s, size=%d, offset=%d)', path, size, offset)
        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            fd.atime = time.time()
            if offset >= fd.handler.size:
                return None

            data = fd.handler.read()
            if self._logger.isEnabledFor(logging.DEBUG):
                self.log_debug("-> %s", binascii.hexlify(data))
            return data

    def write(self, path, data, offset, fh):
        """ ..see:: :py:class:`fuse.Operations` """
        if self._logger.isEnabledFor(logging.DEBUG):
            hexed = ':'.join('%02x' % ord(b) for b in data)
            self.log_debug('write(path=%s, data=[%s], offset=%d)', path, hexed, offset)

        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            retval = fd.handler.write(data)
            fd.mtime = time.time()
            return retval

    def truncate(self, path, length, fh=None):
        """
        ..important:: needs to be overridden otherwise default implementation generates
        a "read-only file system" error.
        """
        self.log_debug('truncate(path=%s, length=%d)', path, length)
        return length

    def utimens(self, path, times=None):
        now = time.time()
        atime, mtime = times if times else (now, now)

        try:
            fd = self._get_descriptor(path)
        except KeyError:
            raise FuseOSError(errno.ENOENT)
        else:
            fd.atime = atime
            fd.mtime = mtime
