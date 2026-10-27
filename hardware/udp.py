'''PyNMR, J.Maxwell 2020
'''

import socket
# >>> UNH-HOOK daq-link: box errors go to the log file too, not only the console
import logging
log = logging.getLogger('PyNMR.hardware.udp')
# <<< UNH-HOOK daq-link

class UDP():
    '''Handle UDP commands and responses

    Args:
        config: Config object with settings

    Attributes:
        dac_v: DAC value for given dac_c channel to set, from 0 (off) to 1 (max)
        dac_c: DAC channel to set (1 is phase, 2 is diode, 3 is both)
    '''

    def __init__(self, config, tune_mode):
        '''Start connection, send nmr_settings dict'''
        self.tune_mode = tune_mode
        self.ok = bytes.fromhex('0300FA')
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        self.s.settimeout(config.settings['fpga_settings']['timeout_udp'])
        self.config = config
        self.dac_v = 0
        self.dac_c = 0
        self.ip = config.settings['fpga_settings']['ip']
        self.port = config.settings['fpga_settings']['port']
        try:
            self.s.connect((self.ip, self.port))
            # >>> UNH-HOOK daq-link: box errors go to the log file too, not only the console
            # JLab: if not self.set_register(): print("Set register error")
            if not self.set_register():
                print("Set register error")
                log.error(f"DAQ at {self.ip} did not accept the register settings.")
            # <<< UNH-HOOK daq-link
            # print(self.read_stat())
            # >>> UNH-HOOK daq-link: box errors go to the log file too, not only the console
            # JLab: if not self.set_freq(config.freq_bytes): print("Set frequency error")
            if not self.set_freq(config.freq_bytes):
                print("Set frequency error")
                log.error(f"DAQ at {self.ip} did not accept the frequency table.")
            # <<< UNH-HOOK daq-link
            self.read_freq()
        except Exception as e:
            print("Error in UDP connection to DAQ at", self.ip, ":", e)
            log.error(f"UDP connection to DAQ at {self.ip} failed: {e}")   # UNH-HOOK daq-link
            raise

    def __del__(self):
        '''Stop connection'''
        try:
            self.s.close()
        except Exception as e:
            raise

    # >>> UNH-HOOK daq-link: close now instead of at garbage collection
    def close(self):
        '''Close the UDP socket. Safe to call more than once.'''
        self.s.close()

    # <<< UNH-HOOK daq-link
    def read_stat(self):
        '''Read status command
        Returns:
            Data sent back as hex
        '''
        self.s.send(bytes.fromhex('0F0001000000000000000000000000'))
        data, addr = self.s.recvfrom(1024)
        # print("Read Stat Message: ", data.hex())
        return data.hex()

    def read_freq(self):
        '''Read frequency command
        Returns:
            Data sent back as hex
        '''
        self.s.send(bytes.fromhex('0F0003000000000000000000000000'))
        data, addr = self.s.recvfrom(1028)  # buffer size is 1027 to get all of the points
        # print("Read Freq Message: ", data.hex())
        return data.hex()

    def set_register(self):
        '''Send set register command and string
        Returns:
            Boolean denoting success
            '''

        # Make ADC Config int from list of bools
        test_mode = self.config.settings['fpga_settings']['adc_test']
        reset = False
        phase_drate1 = self.config.settings['fpga_settings']['adc_drate1']
        phase_drate0 = self.config.settings['fpga_settings']['adc_drate0']
        phase_fpath = self.config.settings['fpga_settings']['adc_fpath']
        diode_drate1 = self.config.settings['fpga_settings']['adc_drate1']
        diode_drate0 = self.config.settings['fpga_settings']['adc_drate0']
        diode_fpath = self.config.settings['fpga_settings']['adc_fpath']
        rf_off = False
        states = [test_mode, reset, False, False, False, False, False, False, False, rf_off, phase_drate1, phase_drate0,
                  phase_fpath, diode_drate1, diode_drate0, diode_fpath]
        adcbits = ''.join([str(int(i)) for i in states])
        ADCConfig = int(adcbits, 2)
        # ADCConfig = 0x0036

        # dac_value = int(self.dac_v * (65535/5/3.2037))
        # Set up DAC value from desired percentage:
        # voltage =~ (16/65535) * DAC value 1/12/2021
        dac_value = int(self.dac_v * 65535)
        # print(self.dac_v, dac_value, dac_value.to_bytes(2,'little').hex())

        # Make Resiter byte string from other inputs
        # Number Bytes LSB, Nymber Bytes MSB, LSByte GenSetTime, MSByte GenSetTime, LSByte NumOfSamToAve, MByte NumOfSamToAve, LSByte TotSweepCycle, MSByte TotSweepCycle, LSByte IntSweepCycle, MSByte IntSweepCycle, LSByte AdcConfig, MSByte AdcConfig, LSByte Dac Value, MSByte Dac Value, LSByte Dac Config, MSByte Dac Config
        RegSets = [bytes.fromhex('1100'), bytes.fromhex('02')]
        RegSets.append(self.config.settings['fpga_settings']['dwell'].to_bytes(2, 'little'))
        RegSets.append(self.config.settings['fpga_settings']['per_point'].to_bytes(2, 'little'))
        if self.tune_mode:
            RegSets.append(self.config.settings['tune_per_chunk'].to_bytes(2, 'little'))
            RegSets.append(self.config.settings['tune_per_chunk'].to_bytes(2, 'little'))
        else:
            RegSets.append(self.config.controls['sweeps'].value.to_bytes(2, 'little'))
            RegSets.append(self.config.settings['num_per_chunk'].to_bytes(2, 'little'))
        RegSets.append(ADCConfig.to_bytes(2, 'little'))
        RegSets.append(dac_value.to_bytes(2, 'little'))
        RegSets.append(self.dac_c.to_bytes(2, 'little'))
        # print("Last two reg bytes:",RegSets[-2].hex(), RegSets[-1].hex())
        return self.write_register(self.s, RegSets)

    def write_register(self, socket, RegSets):
        ''' Join byte array (RegSets) into string and send to socket, return True if ok returned
        '''
        RegSetString = b''.join(RegSets)
        socket.send(RegSetString)
        data, addr = socket.recvfrom(1024)  # buffer size is 1024
        # print("Set string:",RegSetString.hex())
        # print("Read string:",self.read_stat())
        if data == self.ok:
            return True
        else:
            return False

    def set_freq(self, freq_bytes):
        '''Send frequency points, converts freq list into bytes
        Args:
            freq_bytes: List of bytes for R&S frequency modulation

        Returns:
            Boolean denoting success
        '''

        NumBytes_byte = (self.config.settings['steps'] * 2 + 3).to_bytes(2, 'little')  # number of bytes to send
        freqs = NumBytes_byte + bytes.fromhex('04') + b''.join(freq_bytes)  # freq string to send, including
        # [print(f.hex()) for f in freq_bytes]
        if self.config.settings['fpga_settings']['test_freqs']:
            NumBytes_byte = (self.config.settings['steps'] * 2 + 3).to_bytes(2, 'little')
            # FreqList = range(1,self.config.settings['steps']+1)
            FreqList = range(-self.config.settings['steps'], 0)
            FreqBytes = [b.to_bytes(2, 'little', signed=True) for b in FreqList]
            TestTable = NumBytes_byte + bytes.fromhex('04') + b''.join(FreqBytes)
            self.s.send(TestTable)
            # print("Set Freq: ", TestTable.hex())
        else:
            self.s.send(freqs)
            # print("Set Freq: ", freqs.hex())
        data, addr = self.s.recvfrom(1024)  # buffer size is 1024
        # print("Set Freq Message: ", data.hex())
        if data == self.ok:
            return True
        else:
            return False

    def act_sweep(self):
        '''Send activate sweep command
        Returns:
            Boolean denoting success
        '''
        self.s.send(bytes.fromhex('0F0005000000000000000000000000'))
        data, addr = self.s.recvfrom(1024)  # buffer size is 1024
        if data == self.ok:
            return True
        else:
            return False

    def int_sweep(self):
        '''Send interrupt sweep command
        Returns:
            Boolean denoting success
        '''
        self.s.send(bytes.fromhex('0F0006000000000000000000000000'))
        data, addr = self.s.recvfrom(1024)  # buffer size is 1024
        if data == self.ok:
            return True
        else:
            return False
