POBOT's ``pybot`` collection
============================

This package is part of POBOT's ``pybot`` packages collection, which aims
at gathering contributions created while experimenting with various technologies or
hardware in the context of robotics projects.

Although primarily focused on robotics applications (taken with its widest acceptation)
some of these contributions can be used in other contexts. Don't hesitate to keep us informed
on any usage you could have made.

Implementation note
-------------------

The collection code is organized using namespace packages, in order to group them in
a single tree rather that resulting in a invading flat collection. Please refer to the official
documentation at <https://www.python.org/dev/peps/pep-0382/> for details.

Package content
===============

FUSE based publication of the `I2C serial LCD <https://www.robot-electronics.co.uk/htm/Lcd05tech.htm>`_
control library.

The package provides the daemon which exposes the LCD API as a virtual file system. The typical
tree which is created and managed is organised as follows :

::

  <mount_point>/
     info
     display
     backlight
     contrast
     brightness
     keys
     leds
     locked

This list is the extensive set of files, some of them not being visible depending on the interfaced
LCD model. In addition the last two items are related to the control panel of the
`Youpi robotic arm <https://github.com/pobot-pybot/pybot-youpi2>`_,
and will not be available with the standard LCD models.

Installation
============

::

    $ cd <PROJECT_ROOT_DIR>
    $ python setup.py install

Dependencies
============

- `pybot-lcd <https://github.com/pobot-pybot/pybot-lcd>`_

External:

- spidev
- RPi.GPIO

The dependencies are declared in `setup.py`, so they are automatically installed if needed.
pybot collection not being on PyPi, you'll have to install it manually before.
