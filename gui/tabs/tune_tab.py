'''PyNMR, J.Maxwell 2020
'''
import datetime
import time
from PySide6.QtWidgets import QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox, QGridLayout, QLabel, QLineEdit, QSizePolicy, QComboBox, QSpacerItem, QSlider, QDoubleSpinBox, QProgressBar
from PySide6.QtGui import QIntValidator, QDoubleValidator, QValidator
from PySide6.QtCore import QThread, Signal, Qt, QTimer
import pyqtgraph as pg
 
from core import RunningScan
from core.thread_manager import BaseThread
from core.event_bus import get_event_bus, EventType
from hardware import DAQConnection

  
class TuneTab(QWidget):
    '''Creates tune tab'''
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        self.running = False   # False will stop the running thread
        self.dac_v = 0     # Starting DAC channel value   
        self.dac_c = 3      # Starting DAC channel (3 is both)
        
        self.running_scan = RunningScan(self.parent.config, 1000)
        
        self.dio_pen = pg.mkPen(color=(250, 0, 0), width=1.5)
        self.pha_pen = pg.mkPen(color=(0, 0, 204), width=1.5)
        self.progress = 0
        
        # Thread-safe plotting
        self.tune_thread = None
        self.pending_plot_data = None
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self.update_plots_from_timer)
        self.plot_timer.setSingleShot(True)
        
        # Populate Tune Tab
        self.main = QVBoxLayout()            # main layout
        
        self.tune_box = QGroupBox('Tune Controls')      # top tune controls
        self.tune_box.setLayout(QHBoxLayout())
        self.run_button = QPushButton('Run', checkable=True)
        self.tune_box.layout().addWidget(self.run_button)
        self.run_button.clicked.connect(self.run_pushed)
        self.run_button.setEnabled(False)
        self.progress_bar = QProgressBar()                                 # Progress bar
        self.progress_bar = QProgressBar()                                  # Progress bar
        self.progress_bar.setTextVisible(False)
        self.tune_box.layout().addWidget(self.progress_bar)
        self.avg_label = QLabel('Sweeps for Running Average:')
        self.tune_box.layout().addWidget(self.avg_label)
        self.avg_value = QLineEdit('32')
        self.avg_value.setValidator(QIntValidator(1,1000000))
        self.avg_value.textChanged.connect(lambda: self.change_avg(int(self.avg_value.text())))
        self.avg_value.editingFinished.connect(lambda: self.avg_value.setStyleSheet('QLineEdit { background-color: #ffffff }'))
        self.tune_box.layout().addWidget(self.avg_value)
        
        self.lower = QHBoxLayout()
        self.left_layout = QVBoxLayout()     # Left, Diode Side
        # Diode plot
        self.diode_wid = pg.PlotWidget(title='Diode Signal')
        self.diode_wid.showGrid(True,True)
        self.diode_plot = self.diode_wid.plot([], [], pen=self.dio_pen) 
        self.left_layout.addWidget(self.diode_wid)
        self.diode_box = QGroupBox("Diode Tune Control")
        self.diode_box.setLayout(QHBoxLayout())
        self.left_layout.addWidget(self.diode_box)
        self.diode_slider = QSlider(Qt.Horizontal)
        self.diode_slider.setRange(0,1000)
        self.diode_box.layout().addWidget(self.diode_slider)
        self.diode_spin = QDoubleSpinBox()
        self.diode_spin.setDecimals(3)
        self.diode_spin.setRange(0,100)
        self.diode_spin.setSingleStep(0.1)
        self.diode_slider.sliderReleased.connect(self.diode_slider_changed)
        self.diode_spin.valueChanged.connect(self.diode_spin_changed)
        self.diode_box.layout().addWidget(self.diode_spin)
        self.vl1 = QLabel('Percent')
        self.diode_box.layout().addWidget(self.vl1)
        
        self.right_layout = QVBoxLayout()     # Right, Phase Side
        self.phase_wid = pg.PlotWidget(title='Phase Signal')
        self.phase_wid.showGrid(True,True)
        self.phase_plot = self.phase_wid.plot([], [], pen=self.pha_pen) 
        self.right_layout.addWidget(self.phase_wid)
        self.phase_box = QGroupBox("Phase Tune Control")
        self.phase_box.setLayout(QHBoxLayout())
        self.right_layout.addWidget(self.phase_box)
        self.phase_slider = QSlider(Qt.Horizontal)
        self.phase_slider.setRange(0,1000)
        self.phase_box.layout().addWidget(self.phase_slider)
        self.phase_spin = QDoubleSpinBox()
        self.phase_spin.setDecimals(2)
        self.phase_spin.setRange(0,100)
        self.phase_spin.setSingleStep(0.1)
        self.phase_slider.sliderReleased.connect(self.phase_slider_changed)
        self.phase_spin.valueChanged.connect(self.phase_spin_changed)
        self.phase_box.layout().addWidget(self.phase_spin)
        self.vl2 = QLabel('Percent')
        self.phase_box.layout().addWidget(self.vl2)
        
        self.lower.addLayout(self.left_layout)
        self.lower.addLayout(self.right_layout)
        self.main.addWidget(self.tune_box)
        self.main.addLayout(self.lower)
        self.setLayout(self.main)
        
        self.restore()
    
    def __del__(self):
        '''Cleanup when tab is destroyed'''
        try:
            self.abort_run()
        except Exception as e:
            print(f"Error in TuneTab cleanup: {e}")
    
    def closeEvent(self, event):
        '''Handle close event'''
        self.abort_run()
        super().closeEvent(event) if hasattr(super(), 'closeEvent') else None
    
    def publish_status_message(self, message):
        """Publish status message via event bus (with fallback to direct access)."""
        try:
            event_bus = get_event_bus()
            event_bus.publish(EventType.STATUS_MESSAGE, "tune_tab", {"message": message})
        except Exception as e:
            # Fallback to direct access if event bus is not available
            print(f"Event bus not available, using direct status: {e}")
            if hasattr(self, 'parent') and hasattr(self.parent, 'status_bar'):
                self.parent.status_bar.showMessage(message)
        
    def restore(self):
        '''Restore previous session settings'''
        if self.parent.restore_dict:
            self.phase_slider.setValue(int(self.parent.restore_dict['phase_tune']*1000))
            self.phase_spin.setValue(self.parent.restore_dict['phase_tune']*100)
            self.diode_slider.setValue(int(self.parent.restore_dict['diode_tune']*1000))
            self.diode_spin.setValue(self.parent.restore_dict['diode_tune']*100)
        
    def phase_slider_changed(self):
        '''Slider value changed'''
        self.phase_spin.setValue(float(self.phase_slider.value()/10))
        
    def phase_spin_changed(self):
        '''Spinbox value changed, spinbox is 1/10 of slider, value out is 1/100 of spinbox'''
        self.phase_slider.setValue(int(self.phase_spin.value()*10))
        self.parent.config.phase_vout = self.phase_spin.value()/100
        self.send_to_dac(self.parent.config.phase_vout, 1)
        
    def diode_slider_changed(self):
        '''Slider value changed'''
        self.diode_spin.setValue(float(self.diode_slider.value()/10))
        #self.parent.config.diode_vout = float(self.diode_slider.value()/100)
        #self.send_to_dac(self.parent.config.diode_vout, 1)
        
    def diode_spin_changed(self):
        '''Spinbox value changed'''
        self.diode_slider.setValue(int(self.diode_spin.value()*10))
        self.parent.config.diode_vout = self.diode_spin.value()/100
        self.send_to_dac(self.parent.config.diode_vout, 2)
        
    def send_to_dac(self, value, dac_c):
        '''Send DAC voltage to DAQ, check to see if tune is running. If not, start DAQConnection to send.
        
        Arguments:
            value: Relative value to send (0 is no voltage to 1 is max)
            dac_c: channel, 1 (phase), 2 (diode), or 3 (both same)
        
        '''
        self.dac_v = value
        self.dac_c = dac_c
        
        if not self.running:
            time.sleep(0.0001)
            self.daq = DAQConnection(self.parent.config, 4, True)
            if self.daq.set_dac(self.dac_v, self.dac_c):
                pass
                #print("Set DAC:", self.dac_c,  self.dac_v)
            else:
                print("Error setting DAC.")
            self.daq.close()   # UNH-HOOK daq-link
            del self.daq
 
    def run_pushed(self):
        '''Start tune loop if conditions met'''
        
        if self.run_button.isChecked():
        
            self.publish_status_message('Running sweeps to tune...')
            self.run_button.setText('Stop')
            self.start_thread()
            self.parent.run_toggle()
                   
        else:
            self.abort_run()
            self.run_button.setText('Run')
            self.parent.run_toggle()
     
    def start_thread(self):
        '''Open new event instance, create then start threads for data taking and plotting '''
       
        self.running_scan = RunningScan(self.parent.config, int(self.avg_value.text()))
        self.running = True
        
        try:
            from core.thread_manager import get_thread_manager
            
            # Create tune thread
            self.tune_thread = TuneThread(self, self.parent.config)
            
            # Get thread manager and register thread
            thread_manager = get_thread_manager()
            thread_manager.register_thread(self.tune_thread)
            
            # Connect signals
            self.tune_thread.reply.connect(self.add_sweeps)
            self.tune_thread.finished.connect(self.finished)
            self.tune_thread.error.connect(self.on_thread_error)
            
            # Start thread using thread manager
            thread_manager.start_thread(self.tune_thread.thread_name)
            
        except Exception as e:
            print(f'Exception starting tune thread: {e}')
            self.running = False
            
    def on_thread_error(self, error_msg):
        '''Handle thread error'''
        print(f"Tune thread error: {error_msg}")
        self.running = False
    
    def add_sweeps(self, new_sigs):
        '''Add the tuple of sweeps to event - called from thread, so defer plot updates'''
        self.running_scan.running_avg(new_sigs)
        
        # Queue plot update for main thread
        self.pending_plot_data = (self.running_scan.freq_list.copy(), 
                                  self.running_scan.diode.copy(), 
                                  self.running_scan.phase.copy())
        
        # Update progress immediately (this is thread-safe)
        if self.progress < 100:
            self.progress += 10
        else:
            self.progress = 0
        self.progress_bar.setValue(self.progress)
        
        # Start timer to update plots on main thread
        if not self.plot_timer.isActive():
            self.plot_timer.start(50)  # 50ms delay to batch updates   
        
    def update_plots_from_timer(self):
        '''Update plots safely from main thread via timer'''
        if self.pending_plot_data:
            freq_list, diode_data, phase_data = self.pending_plot_data
            self.diode_plot.setData(freq_list, diode_data)
            self.phase_plot.setData(freq_list, phase_data)
            self.pending_plot_data = None
    
    def finished(self):
        '''Run when thread done'''
        self.progress = 0
        self.progress_bar.setValue(self.progress)  
        self.publish_status_message('Ready.')
        
        # Final plot update
        self.update_run_plot()
        
        # Critical: Disconnect all signals before cleanup
        if self.tune_thread:
            try:
                self.tune_thread.reply.disconnect()
                self.tune_thread.finished.disconnect()
                self.tune_thread.error.disconnect()
            except Exception as e:
                print(f"Warning: Error disconnecting tune thread signals: {e}")
            self.tune_thread = None
        
    def abort_run(self):
        '''Quit now - properly clean up thread and timers'''
        self.running = False
        
        # Stop plot timer
        if self.plot_timer.isActive():
            self.plot_timer.stop()
        self.pending_plot_data = None
        
        # Clean up thread if it exists
        if self.tune_thread:
            try:
                # CRITICAL: Disconnect all signals first to prevent segfault
                self.tune_thread.reply.disconnect()
                self.tune_thread.finished.disconnect()
                self.tune_thread.error.disconnect()
                
                # Use thread manager to stop thread properly
                from core.thread_manager import get_thread_manager
                thread_manager = get_thread_manager()
                thread_manager.stop_thread(self.tune_thread.thread_name, timeout=5000)
                self.tune_thread = None
            except Exception as e:
                print(f"Error stopping tune thread: {e}")
                # Force cleanup even if there's an error
                self.tune_thread = None
        
    def change_avg(self,to_avg):
        '''Set the number to average'''
        if to_avg > 0:
            self.running_scan.to_avg = int(to_avg)
        
    def update_run_plot(self):
        '''Update the running plots'''
        self.diode_plot.setData(self.running_scan.freq_list,self.running_scan.diode)
        self.phase_plot.setData(self.running_scan.freq_list,self.running_scan.phase)
 
class TuneThread(BaseThread):
    '''Thread class for tune loop'''
    
    def __init__(self, parent, config):
        '''Make new thread instance for running NMR'''
        super().__init__(name=f"tune_{id(parent)}", parent=None, config=config)  # no Qt parent, so finished threads can be freed
        self.tab_parent = parent  # TuneTab instance
        self.dac_v = 0
        self.dac_c = 0
        self.daq = None
        
    def execute(self):
        '''Main tune loop. Request start of sweeps, receive sweeps, update event, report.'''
        self._logger.info("Starting tune loop")

        try:
            self.daq = DAQConnection(self.config, self.config.settings['fpga_settings']['timeout_tune'], True)
        except Exception as e:
            self._logger.error(f'Exception creating DAQ connection: {e}')
            return

        try:
            while self.tab_parent.running and not self.should_stop():
                # Sync DAC state before each sweep. set_dac calls set_register which
                # keeps all FPGA parameters current without reopening the connection.
                changed = (self.dac_v != self.tab_parent.dac_v) or (self.dac_c != self.tab_parent.dac_c)
                self.dac_v = self.tab_parent.dac_v
                self.dac_c = self.tab_parent.dac_c
                try:
                    # FPGA only latches a new DAC value when the DAC config word changes
                    # from 0, as happens on a fresh connection. Send a no-op write first.
                    if changed:
                        self.daq.set_dac(self.dac_v, 0)
                    if not self.daq.set_dac(self.dac_v, self.dac_c):
                        self._logger.warning(f"set_dac returned False: C={self.dac_c}, V={self.dac_v}")
                except Exception as e:
                    if not self.should_stop():
                        self._logger.warning(f"Exception setting DAC value: {e}")

                try:
                    self.daq.start_sweeps()
                    new_sigs = self.daq.get_chunk()

                    while new_sigs[1] < self.config.settings['tune_per_chunk']:
                        if self.should_stop():
                            break
                        new_sigs = self.daq.get_chunk()

                    if not self.should_stop():
                        self.emit_reply(new_sigs)

                except Exception as e:
                    if not self.should_stop():
                        self._logger.error(f"Exception in tune loop: {e}")
                    break

        finally:
            if self.daq:
                try:
                    # >>> UNH-HOOK daq-link: tune ends on Stop or an error, often mid-sweep: stop the box, then close cleanly
                    try:
                        self.daq.abort()
                    except Exception as e:
                        self._logger.warning(f"Could not send stop to DAQ: {e}")
                    how = self.daq.close()
                    if how:
                        self._logger.info(f"DAQ connection closed: {how}")
                    # <<< UNH-HOOK daq-link
                    del self.daq
                    self.daq = None
                except Exception as e:
                    self._logger.warning(f"Error cleaning up DAQ: {e}")

        self._logger.info("Tune loop completed")


# Legacy compatibility wrapper
class LegacyTuneThread(QThread):
    '''Legacy compatibility wrapper for old TuneThread interface.'''
    reply = Signal(tuple)       # reply signal

    def __init__(self, parent, config):
        QThread.__init__(self)
        self.config = config
        self.parent = parent 
        self.dac_v = 0
        self.dac_c = 0
        self.set_time = 0
        
    def __del__(self):
        if self.isRunning():
            self.quit()

    def run(self):
        while self.parent.running:
            now = time.time()
            try:
                self.daq = DAQConnection(self.config, self.config.settings['fpga_settings']['timeout_tune'], True)
            except Exception as e:
                print('Exception in tune thread: '+str(e))
                
            if now > self.set_time + 0.001:
                if (self.dac_v != self.parent.dac_v) or (self.dac_c != self.parent.dac_c):
                    self.dac_v = self.parent.dac_v
                    self.dac_c = self.parent.dac_c
                    try:
                        if self.daq.set_dac(self.dac_v, self.dac_c):                         
                            pass
                        self.set_time = now
                    except Exception as e:
                        print("Exception setting DAC value: "+str(e))
            self.daq.start_sweeps()
            new_sigs = self.daq.get_chunk()
            while new_sigs[1] < self.config.settings['tune_per_chunk']:
                new_sigs = self.daq.get_chunk()  
            self.reply.emit(new_sigs)
            del self.daq
        self.finished.emit()
        




