'''PyNMR, J.Maxwell 2020
'''
import socket
import time
import json
import telnetlib
import unyt
import numpy as np
import nidaqmx
from nidaqmx.constants import (DigitalWidthUnits, AcquisitionType,
                               ReadRelativeTo, OverwriteMode, DigitalWidthUnits,
                               TriggerType, TaskMode, READ_ALL_AVAILABLE)
from hardware.udp import UDP
from hardware.tcp import TCP
                               
class DAQConnection():
    '''Handle connection to and communication with DAQ system. Designed to hide all the specifics of different DAQ systems with generic actions for all. Init will open connections and send configuration settings to DAQ.
    
    Args:
        config: Config object with settings
        timeout: Timeout for DAQ system
        tune_mode: Use tune mode, with only one chuck
    '''
    
    def __init__(self, config, timeout, tune_mode=False):
        
        self.daq_type = config.settings['daq_type']
        self.tune_mode = tune_mode
        self.config = config
        
        if self.daq_type=='FPGA':
            
            try:
                self.udp = UDP(self.config, tune_mode)
                self.tcp = TCP(self.config, timeout)
                
            except Exception as e:
                raise
                
            self.name = str(self.udp.ip)
            self.message = 'Connected to: '+str(self.udp.ip)+', port '+str(self.udp.port)+', and set registers and frequency table.'
            
        elif self.daq_type=='NIDAQ':          
            try:
                self.ni = NI_Connection(self.config)
                self.message = 'Connected to NI-DAQ.'
                self.name = self.config.settings['nidaq_settings']['phase_chan']
            except Exception as e:
                self.message = 'NI-DAQ Connection failed.'
                self.name = 'Connection failed.'
                print(e)
            
            
        # >>> UNH-HOOK nmr-sim: simulated Test source when settings test_source is 'sim' (1/3)
        elif self.daq_type=='Test' and self.config.settings.get('test_source', 'replay')=='sim':
            from unh.nmr_sim.adapter import SimDAQ   # lazy: replay never imports nmr_sim
            n = self.config.settings['tune_per_chunk' if tune_mode else 'num_per_chunk']
            self.sim = SimDAQ(self.config.settings['nmr_sim'], self.config.freq_list, n)
            self.message, self.name = self.sim.message, self.sim.name
        # <<< UNH-HOOK nmr-sim (1/3)
        elif self.daq_type=='Test':          
            #v, self.test_phase, self.test_diode = np.loadtxt("app/test_data.txt", unpack=True) 
            with open(self.config.settings['test_signal'], 'r') as file:
                for line in file:
                    event = json.loads(line)
                    self.test_phase = np.array(event['phase'])
                    self.test_diode = np.array(event['diode'])
                    self.test_freqs = np.array(event['freq_list'])
            # >>> UNH-HOOK freq-window: replay follows the requested window
            # Return the recorded signal at the requested frequency points, as hardware would:
            # interpolate within the recorded range; outside it, hold the nearest edge value (flat baseline)
            freqs = self.config.freq_list
            self.test_in_range = (freqs >= self.test_freqs.min()) & (freqs <= self.test_freqs.max())
            self.test_phase = np.interp(freqs, self.test_freqs, self.test_phase)
            self.test_diode = np.interp(freqs, self.test_freqs, self.test_diode)
            # <<< UNH-HOOK freq-window
            self.message = 'DAQ Test mode.'
            self.name = 'Test'
            
        else:
            print('Incorrect daq_type setting')


    def __del__(self):
        '''Stop Connections'''
        if self.daq_type=='FPGA':
            try:
                del self.udp
                del self.tcp
            except AttributeError:
                pass
            except Exception as e:
                raise

    def start_sweeps(self):
        '''Send command to sending NMR sweeps'''
        if self.daq_type=='FPGA':
            self.udp.act_sweep()
            
        if self.daq_type=='NIDAQ':   
            self.ni.start()
            
            
    def abort(self):
        '''Send command to abort NMR sweeps'''
            
        if self.daq_type=='FPGA':
            try:
                self.udp.int_sweep()
            except Exception as e:
                raise
            
    def stop(self):
        '''Send command to stop sending NMR sweeps'''
        
        if self.daq_type=='NIDAQ':   
            self.ni.stop()

    def get_chunk(self):
        '''Receive subset of total sweeps for the event'''
        
        if self.daq_type=='FPGA':
            return self.tcp.get_chunk()   
            
        elif self.daq_type=='NIDAQ':          
            return self.ni.get_chunk()            
            
        # >>> UNH-HOOK nmr-sim: chunks from the simulator when enabled (2/3)
        elif self.daq_type=='Test' and getattr(self, 'sim', None) is not None:
            return self.sim.get_chunk()
        # <<< UNH-HOOK nmr-sim (2/3)
        elif self.daq_type=='Test':
            if self.tune_mode:
                num_in_chunk = self.config.settings['tune_per_chunk']
            else:
                num_in_chunk = self.config.settings['num_per_chunk']
            time.sleep(0.005*num_in_chunk)
            
            p_test = self.test_phase + np.random.rand(len(self.test_phase))*0.00001*num_in_chunk   # numpy arrays
            d_test = -self.test_diode + np.random.rand(len(self.test_diode))*0.00001*num_in_chunk 
            return (0, num_in_chunk, p_test, d_test)
      
    def set_dac(self, dac_v, dac_c):
        '''Set DAC value for tuning diode or phase
        '''
        if self.daq_type=='FPGA':
            self.udp.dac_v = dac_v 
            self.udp.dac_c = dac_c    
            return self.udp.set_register()        
        # >>> UNH-HOOK nmr-sim: Tune-tab DACs act on the simulated Q-meter (3/3)
        if self.daq_type=='Test' and getattr(self, 'sim', None) is not None:
            return self.sim.set_dac(dac_v, dac_c)
        # <<< UNH-HOOK nmr-sim (3/3)
        if self.daq_type=='Test':
            #print("DAC", dac_v, dac_c)
            return True
      
    def read_stat(self):
        '''Read back DAQ status
        '''
        if self.daq_type=='FPGA':
            return self.udp.read_stat()            
             

        
        
class NI_Connection():
    '''NI DAQ in and out tasks and methods to use them. Code from C.Carlin.
    
    Arguments:
        config: Current Config object
    
    '''
    
    def __init__(self, config):
    
        self.ai = nidaqmx.Task()
        self.ao = nidaqmx.Task()
    
        ramp_min_V,ramp_max_V = -1 * unyt.V, 1 * unyt.V
        self.pts_per_ramp = config.settings['steps']
        self.pretris = config.settings['nidaq_settings']['pretris']
        self.tris_per_scan = config.controls['sweeps'].value #//2  Difference in nomenclature. My sweeps are same as Carlin's triangles.
        time_per_pt_us = config.settings['nidaq_settings']['time_per_pt'] * unyt.us
        settling_delay_ratio = config.settings['nidaq_settings']['settling_ratio']
        ai_min_V,ai_max_V = -1 * unyt.V, 1 * unyt.V

        phase_chan = config.settings['nidaq_settings']['phase_chan']
        diode_chan = config.settings['nidaq_settings']['diode_chan']
        ao_chan = config.settings['nidaq_settings']['ao_chan']

        self.pts_per_tri = self.pts_per_ramp * 2
        self.total_pts = self.pts_per_tri * (self.tris_per_scan + self.pretris)
        sample_rate_Hz = 1 / time_per_pt_us.to(unyt.s)
        settling_delay_us = time_per_pt_us * settling_delay_ratio
        self.pretri_delay_s = (self.pretris * time_per_pt_us * self.pts_per_tri).to(unyt.s)
        
        self.triangle = list(np.linspace(ramp_min_V, ramp_max_V, self.pts_per_ramp))
        self.triangle += self.triangle[::-1] # Concat the list reversed
        
        self.ao.control(TaskMode.TASK_UNRESERVE)
        self.ao.ao_channels.add_ao_voltage_chan(ao_chan,
                                           min_val=ramp_min_V,
                                           max_val=ramp_max_V)

        self.ao.timing.cfg_samp_clk_timing(sample_rate_Hz,
                                      sample_mode=AcquisitionType.CONTINUOUS,
                                      samps_per_chan=self.pts_per_tri)

        self.ao.triggers.start_trigger.trig_type = TriggerType.NONE
        self.ao_start_terminal = self.ao.triggers.start_trigger.term

        #Setup AI channel
        self.ai.ai_channels.add_ai_voltage_chan(phase_chan, min_val=ai_min_V, max_val=ai_max_V)
        self.ai.ai_channels.add_ai_voltage_chan(diode_chan, min_val=ai_min_V, max_val=ai_max_V)

        self.ai.timing.delay_from_samp_clk_delay = settling_delay_us.to(unyt.s)
        self.ai.timing.delay_from_samp_clk_delay_units = DigitalWidthUnits.SECONDS

        self.ai.timing.cfg_samp_clk_timing(sample_rate_Hz,
                                      sample_mode=AcquisitionType.CONTINUOUS,
                                      samps_per_chan=self.total_pts*2)

        self.ai.in_stream.read_all_avail_samp = True
        self.ai.in_stream.relative_to = ReadRelativeTo.FIRST_SAMPLE
        self.ai.in_stream.over_write = OverwriteMode.OVERWRITE_UNREAD_SAMPLES

        self.ai.triggers.start_trigger.cfg_dig_edge_start_trig(self.ao_start_terminal)
        self.ai.triggers.start_trigger.trig_type = TriggerType.DIGITAL_EDGE
        self.ai.triggers.start_trigger.delay = self.pretri_delay_s
        self.ai.triggers.start_trigger.delay_units = DigitalWidthUnits.SECONDS
    
    def __del__(self):
        self.stop()
        self.ai.close()
        self.ao.close()
    
    def start(self):
        self.ao.stop()
        self.ai.stop()
        self.ao.write(self.triangle)
        self.ai.in_stream.offset = 0
        self.ai.start()
        self.ao.start()

    def stop(self):
        self.ao.stop()
        self.ai.stop()    

    def get_chunk(self):
        '''Get sweeps from NI board, return number of sweeps in chunk, phase np.array, diode np.array
        
        Notes:
            Results stream from the NI board and we ask for them after a second. What comes back is a number of sweeps, probably not ending in a whole numnber of sweeps. Have to save the last set of numbers to tack on to the front of the next chunk. Or we could discard the extra on the end...? 
        
        '''
        samples = self.ai.read(READ_ALL_AVAILABLE, timeout=self.pretri_delay_s)  # list of lists
        pchunks, dchunks = samples              # split into phase and diode        
        num_in_chunk = len(pchunks)//(self.pts_per_ramp)
        if  num_in_chunk < 1:      
            pchunk = np.zeros(self.pts_per_ramp)
            dchunk = np.zeros(self.pts_per_ramp)
            return 0, num_in_chunk, pchunk, dchunk
        pchunks = pchunks[:2*(num_in_chunk*self.pts_per_ramp//2)]    # discard extra samples if partially accumulated
        dchunks = dchunks[:2*(num_in_chunk*self.pts_per_ramp//2)]
        pchunks = np.array(pchunks).reshape(num_in_chunk, self.pts_per_ramp)  # 2D array with steps number of rows
        pchunks[1::2,:] = np.flip(pchunks[1::2,:])  # flip every other row
        dchunks = np.array(dchunks).reshape(num_in_chunk, self.pts_per_ramp)  # 2D array with steps number of rows
        dchunks[1::2,:] = np.flip(dchunks[1::2,:])  # flip every other row
        
        pchunk = np.average(pchunks, axis=0)
        dchunk = np.average(dchunks, axis=0)
        
        time.sleep(1)
        return 0, num_in_chunk, pchunk, dchunk

     
