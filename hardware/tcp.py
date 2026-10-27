'''PyNMR, J.Maxwell 2020
'''
import socket
import numpy as np
# >>> UNH-HOOK daq-link: clean close and logging of the box connection
import logging
import time
log = logging.getLogger('PyNMR.hardware.tcp')
# <<< UNH-HOOK daq-link

class TCP():
    '''Handle TCP commands and responses

    Args:
        config: Config object with settings
        timeout: Int for TCP timeout time (secs)

    '''

    HEADER = b'\xff\xff\xff\xff\xff'

    def __init__(self, config, timeout):
        '''Start connection'''
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.s.settimeout(timeout)
        self.ip = config.settings['fpga_settings']['ip']
        self.port = config.settings['fpga_settings']['port']
        self.buffer_size = config.settings['fpga_settings']['tcp_buffer']
        self.s.connect((self.ip, self.port))
        self.freq_num = config.settings['steps']
        self.phase_cal = config.settings['fpga_settings']['phase_cal']
        self.diode_cal = config.settings['fpga_settings']['diode_cal']
        self._rx = bytearray()   # received bytes not yet parsed, kept between get_chunk calls
        self.close_wait = config.settings['fpga_settings'].get('close_wait', 0.5)   # UNH-HOOK daq-link

        if config.settings['fpga_settings']['phase_adc_number'] == 2:
            self.adc_one = 'diode'
            self.adc_two = 'phase'
        else:
            self.adc_one = 'phase'
            self.adc_two = 'diode'

    def __del__(self):
        '''Stop connection'''
        try:
            self.s.close()
        except Exception as e:
            raise

    # >>> UNH-HOOK daq-link: close the box connection cleanly instead of leaving it to garbage collection
    def close(self):
        '''Close the connection the way the box expects: tell it we are done (FIN), read off anything it is
        still sending, and wait up to close_wait s for it to close its side. Closing a socket that still has
        unread data makes Windows abort (reset) the connection instead, which can leave the box's network
        stack stuck until it is power cycled. Safe to call more than once.

        Returns:
            Short description of how the close went, for the log
        '''
        if getattr(self, '_closed', False):
            return 'already closed'
        self._closed = True
        start = time.monotonic()
        how = None
        drained = 0
        try:
            self.s.shutdown(socket.SHUT_WR)
            while time.monotonic() - start < self.close_wait:
                self.s.settimeout(max(0.01, self.close_wait - (time.monotonic() - start)))
                data = self.s.recv(65536)
                if not data:
                    how = 'box closed its side'
                    break
                drained += len(data)
        except socket.timeout:
            pass
        except OSError as e:
            how = f'error ({e})'
        finally:
            self.s.close()
        how = how or f'box did not close its side within {self.close_wait} s'
        ms = (time.monotonic() - start) * 1000
        return f'{how} after {ms:.0f} ms' + (f'; discarded {drained} unread bytes' if drained else '')

    # <<< UNH-HOOK daq-link
    def get_chunk(self):
        '''Receive chunks over tcp

        Returns:
            Number of sweeps in chunk, phase chunk and diode chunk numpy arrays
        '''
        # Chunk layout: FF FF FF FF FF header, 2 chunk number bytes, 2 chunk sweep count bytes, adc_one block
        # (freq_num 5-byte signed sums), then a BB marker byte before the adc_two block. Packet boundaries don't
        # line up with any of these, so parse from a buffer that persists between calls.
        block_len = self.freq_num * 5
        chunk = {}

        header_at = self._fill_until(lambda: self._rx.find(self.HEADER), len(self.HEADER) + 4)
        if header_at > 0:
            print(f"TCP: discarded {header_at} bytes before chunk header")
            log.warning(f"Discarded {header_at} bytes from the DAQ before a chunk header.")   # UNH-HOOK daq-link
        del self._rx[:header_at + len(self.HEADER)]
        chunk_num = int.from_bytes(self._rx[0:2], 'little')
        num_in_chunk = int.from_bytes(self._rx[2:4], 'little')
        del self._rx[:4]

        chunk[self.adc_one] = self._take(block_len)
        marker_at = self._fill_until(lambda: self._rx.find(b'\xbb'), 1)
        del self._rx[:marker_at + 1]
        chunk[self.adc_two] = self._take(block_len)

        if num_in_chunk == 0:   # nothing accumulated; caller skips chunks with no sweeps
            return chunk_num, 0, np.zeros(self.freq_num), np.zeros(self.freq_num)

        # average (number of sweeps times two for up and down)
        pchunk = self._decode(chunk['phase']) / (num_in_chunk * 2)
        dchunk = self._decode(chunk['diode']) / (num_in_chunk * 2)
        return chunk_num, num_in_chunk, pchunk / self.phase_cal, dchunk / self.diode_cal  # converting value to voltage

    def _recv(self):
        '''Append next packet to receive buffer'''
        data = self.s.recv(self.buffer_size)
        if not data:
            raise ConnectionError('TCP connection closed by DAQ')
        self._rx += data

    def _fill_until(self, find, need):
        '''Receive until find() returns an index i with at least need bytes buffered from i. Returns i.'''
        while True:
            i = find()
            if i >= 0 and len(self._rx) >= i + need:
                return i
            self._recv()

    def _take(self, n):
        '''Remove and return the next n bytes, receiving more as needed'''
        while len(self._rx) < n:
            self._recv()
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    @staticmethod
    def _decode(block):
        '''Convert block of 5-byte little-endian signed integers to float array'''
        return np.array([int.from_bytes(block[i:i + 5], 'little', signed=True) for i in range(0, len(block), 5)],
                        dtype=np.float64)
        # 11/20/2020: phase 1V is roughly 211692085, diode 1V is 829421
        # return chunk_num, num_in_chunk, pchunk*3/8388607/0.5845, dchunk*3/8388607/0.5845  # converting value to voltage
