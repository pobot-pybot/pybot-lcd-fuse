# -*- coding: utf-8 -*-
import logging

__author__ = 'Eric Pascual'


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