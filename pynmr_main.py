#!/usr/bin/env python3
"""PyNMR, J.Maxwell 2020

Main entry point for the PyNMR application.
"""

import sys
import getopt
import yaml
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QVBoxLayout, QListWidget, QLabel)

from gui import MainWindow


class ProfileDialog(QDialog):
    """Startup dialog to select a named profile from the config file."""

    def __init__(self, profiles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PyNMR — Select Profile")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a profile:"))

        self._list = QListWidget()
        for name in profiles:
            self._list.addItem(name)
        self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        item = self._list.currentItem()
        return item.text() if item else None


def main():
    """Main executable calls main gui"""
    config_file = 'pynmr_config.yaml'
    profile = None

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hc:p:")
    except getopt.GetoptError:
        print('Error: pynmr_main.py [-c <config_file>] [-p <profile>]')
        sys.exit(2)

    for opt, arg in opts:
        if opt in ['-h']:
            print('Usage: pynmr_main.py [-c <config_file>] [-p <profile>]')
            sys.exit()
        elif opt in ['-c']:
            config_file = arg
        elif opt in ['-p']:
            profile = arg

    # >>> UNH-HOOK lab-env: inside WSL use Qt's xcb backend; WSLg sometimes doesn't draw drop-down lists
    try:
        from unh.lab_env import prefer_xcb_on_wsl
        prefer_xcb_on_wsl()
    except ImportError:
        pass
    # <<< UNH-HOOK lab-env
    app = QApplication(sys.argv)
    app.setApplicationName("JLab Polarization Display")

    if profile is None:
        with open(config_file) as f:
            config_data = yaml.load(f, Loader=yaml.FullLoader)
        profiles = list(config_data.get('profiles', {}).keys())
        if profiles:
            dialog = ProfileDialog(profiles)
            if dialog.exec() != QDialog.Accepted:
                sys.exit(0)
            profile = dialog.selected()

    gui = MainWindow(config_file, profile=profile)
    gui.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()