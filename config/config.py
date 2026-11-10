"""Configuration classes for PyNMR application"""

from PySide6.QtGui import QIntValidator, QDoubleValidator, QRegularExpressionValidator
import os.path
import numpy as np


class ConfigItem:
    """Single configurable item with validator
            
    Args:
        value: Value of item
        text: Text string describing item for label
        valid: QValidator object for the value string
    """
    
    def __init__(self, value, text, valid):
        self.value = value
        self.text = text
        self.valid = valid
        
    def set_config(self, value):
        """Change config settings to those in the LineEdit boxes, changing string to correct type based on validator
        
        Args:
            value: Value to change the config item to.
        """
        if isinstance(self.valid, QIntValidator):
            self.value = int(value)
        elif isinstance(self.valid, QDoubleValidator):
            self.value = float(value)
        else:
            self.value = value


class Config:
    """Contains all relevant settings data for NMR measurement
    
    Arguments:
        channel: Dict of current channel setting, selected from config file
        settings: Dict of settings from config file
    
    Attributes:
        channel: Dict of channel settings; keys are species, cent_freq, mod_freq, power
        controls: Dict of ConfigItems for controls
        freq_list: 1D Numpy array of frequency points in sweep as a float, in MHz
        freq_bytes: List of frequency steps, as bytes of 16 bit binary word for R&S
        diode_vout: DAC percentage on tank circuit varactor capacitor for tuning
        phase_vout: DAC percentage on electronic phase adjust for tuning
    """
    
    def __init__(self, channel, settings):
        self.channel = channel
        self.settings = settings  
        self.diode_vout = 0   
        self.phase_vout = 0

        self.controls = {}  # NMR settings requiring control on run tab     
        # >>> UNH-HOOK sweep-blocks: Sweeps per Event starts at 64 x 1 (Ells, 2026-11-10)
        # JLab: self.controls['sweeps'] = ConfigItem(640, 'Sweeps per Event', QIntValidator(10, 65535))  # FPGA register is 16 bits
        self.controls['sweeps'] = ConfigItem(64, 'Sweeps per Event', QIntValidator(10, 65535))  # FPGA register is 16 bits
        # <<< UNH-HOOK sweep-blocks
        self.controls['cc'] = ConfigItem(-.08, 'Calibration Constant', QDoubleValidator(-1000, 1000, 7))
        
        # Make list of frequencies and list of bytes to send to R&S
        # https://www.rohde-schwarz.com/webhelp/sma100a_webhelp_1/Content/fb359696521a42fa.htm
        # go from -32768 to 32767, convert to bytes twos complement        
        # even distribution of steps in range
        if os.path.exists(channel['sweep_file']):
            freq_ints = np.loadtxt(channel['sweep_file'], dtype=np.int32)
            print('Using sweep profile from '+channel['sweep_file']+'.')
        else:
            print('Using standard sweep profile.')
            freq_ints = np.linspace(-32768, 32767, num=self.settings['steps']).astype('int32')
            
        self.freq_list = self.channel['cent_freq'] + self.channel['mod_freq']/1000*(freq_ints)/32768  # in MHz
        self.freq_bytes = [int(i).to_bytes(2, byteorder='little', signed=True) for i in freq_ints]  # bytes for 16-bit word