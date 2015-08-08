#!/usr/bin/env python

from setuptools import setup


setup(name='TangoFS',
      version='0.1',
      description='Filesystem for accessing a Tango control system',
      author='Johan Forsberg',
      author_email='johan.forsberg@gmail.com',
      py_modules=['tangofs'],
      install_requires=["PyTango", "fusepy", "dateutils"],
      entry_points="""
      [console_scripts]
      tangofs=tangofs:main
      """
)
