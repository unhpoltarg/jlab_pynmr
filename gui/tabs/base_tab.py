'''PyNMR, J.Maxwell 2020
'''
import datetime
import re
import json
import os
from dateutil.parser import parse
from PySide6.QtWidgets import QWidget, QLabel, QGroupBox, QHBoxLayout, QVBoxLayout, QGridLayout, QLineEdit, QSpacerItem, QSizePolicy, QComboBox, QPushButton, QTableView, QAbstractItemView, QAbstractScrollArea, QFileDialog
from PySide6.QtCore import QThread, Signal,Qt
from PySide6.QtGui import QIntValidator, QDoubleValidator, QValidator, QStandardItemModel, QStandardItem
import pyqtgraph as pg
import numpy as np

from core.event_bus import get_event_bus, EventType
 

class BaseTab(QWidget): 
    '''Creates baseline tab'''   
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        
        self.sel_pen = pg.mkPen(color=(0, 0, 204), width=1.5)
        self.sub_pen = pg.mkPen(color=(0, 180, 0), width=1.5)
        
        # Populate Base Tab 
        self.main = QHBoxLayout()            # main layout
        
        # Left Side
        self.left = QVBoxLayout() 
                        
        # Baseline controls box     
        #self.basefile_path = self.eventfile.name
        self.basefile_path = ''
        self.basetime = 0        
        self.basefile_name = os.path.join(self.parent.config.settings["event_dir"], f'recent_baselines.txt')
        os.makedirs(self.parent.config.settings["event_dir"], exist_ok=True)
        if os.path.exists(self.basefile_name):
            with open(self.basefile_name, "r") as file:
                count = 0
                for line in file:
                    count+=1
                if count+1 > 30:    # make a new baseline file after 50 lines
                    now = datetime.datetime.now(tz=datetime.timezone.utc)
                    new = f'baselines_{now.strftime("%Y-%m-%d_%H-%M-%S")}.txt'
                    file.close()
                    os.rename(self.basefile_name, os.path.join(self.parent.config.settings["event_dir"], new))
                    newfile = open(self.basefile_name, "x")
               
        self.base_box = QGroupBox('Baseline Controls')
        self.left.addWidget(self.base_box)
        self.base_box.setLayout(QVBoxLayout()) 
        self.base_top = QHBoxLayout()
        self.base_box.layout().addLayout(self.base_top)
        self.curr_base_label = QLabel('Currently selected baseline:')
        self.base_top.addWidget(self.curr_base_label)
        self.curr_base_line = QLineEdit(self.parent.event.base_file+', '+ self.parent.event.base_time.strftime('%H:%M:%S'), enabled=False)
        self.base_top.addWidget(self.curr_base_line)
        
        self.base_box.layout().addWidget(self.parent.divider()) 
        self.button_layout = QHBoxLayout()
        self.base_box.layout().addLayout(self.button_layout)
        self.open_but = QPushButton('Eventfile Selection Dialog')
        self.open_but.clicked.connect(self.pick_basefile) 
        self.button_layout.addWidget(self.open_but)
        self.last_but = QPushButton('Select Current Eventfile')
        self.last_but.clicked.connect(self.use_last) 
        self.button_layout.addWidget(self.last_but)  
        self.recent_but = QPushButton('Show Recent Baselines')
        self.recent_but.clicked.connect(self.show_recent) 
        self.button_layout.addWidget(self.recent_but)         
        # Selection list
        self.event_model = QStandardItemModel()
        self.event_model.setHorizontalHeaderLabels(['Timestamp','Date','Time','Sweep Count','Center (MHz)','Mod (kHz)', 'Channel', 'Label'])
        self.event_table = QTableView()
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.event_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.event_table.resizeColumnsToContents()
        self.event_table.setModel(self.event_model)
        self.event_table.clicked.connect(self.select_event)
        # >>> UNH-HOOK base-drag: a drag, shift-click or Ctrl-A selection also sets the baseline (clicked alone misses drags)
        self.event_table.selectionModel().selectionChanged.connect(
            lambda *_: self.event_table.selectionModel().selectedRows() and self.select_event())
        # <<< UNH-HOOK base-drag
        self.base_box.layout().addWidget(self.event_table)    
        self.base_but = QPushButton('Set Baseline')
        self.base_box.layout().addWidget(self.base_but)
        self.base_but.clicked.connect(self.set_base)
                
        self.main.addLayout(self.left)
        
        # Right Side
        self.right = QVBoxLayout()        
        self.base_wid = pg.PlotWidget(title='Selected Baseline')
        self.base_wid.showGrid(True, True)
        self.base_plot = self.base_wid.plot([], [], pen=self.sel_pen) 
        self.right.addWidget(self.base_wid)  
        self.sub_wid = pg.PlotWidget(title='Current Sweep minus Baseline')
        self.sub_wid.showGrid(True, True)
        self.sub_plot = self.sub_wid.plot([], [], pen=self.sub_pen) 
        self.right.addWidget(self.sub_wid)  
        
        self.main.addLayout(self.right)
        self.setLayout(self.main)
    
    def publish_status_message(self, message):
        """Publish status message via event bus (with fallback to direct access)."""
        try:
            event_bus = get_event_bus()
            event_bus.publish(EventType.STATUS_MESSAGE, "base_tab", {"message": message})
        except Exception as e:
            # Fallback to direct access if event bus is not available
            print(f"Event bus not available, using direct status: {e}")
            if hasattr(self, 'parent') and hasattr(self.parent, 'status_bar'):
                self.parent.status_bar.showMessage(message)
        
    def pick_basefile(self):
        '''Call open file dialog to get eventfile'''
        self.basefile_path = QFileDialog.getOpenFileName(self, "Open Eventfile")[0]        
        self.open_basefile()
        
    def use_last(self):
        '''Open most recent eventfile for baselines'''
        self.basefile_path = self.parent.eventfile.name
        self.open_basefile()
        
    def show_recent(self):
        '''Open recently used baselines file'''
        self.basefile_path = self.basefile_name
        self.open_basefile()
        
    def open_basefile(self):
        '''Open and list contents of eventfile'''
        self.events = {}
        if self.basefile_path:
            with open(self.basefile_path) as json_lines:
                for line in json_lines:
                    jd = json.loads(line.rstrip('\n|\r'))
                    dt = parse(jd['stop_time'])
                    time = dt.strftime("%H:%M:%S")
                    date = dt.strftime("%m/%d/%y")
                    utcstamp = str(jd['stop_stamp'])
                                        
                    if 'base' in self.basefile_path:   # if we are using recent baseline file
                     self.events.update({utcstamp: {'channel':jd['channel'], 
                        'freq_list':jd['freq_list'], 'sweeps':jd['sweeps'], 
                        'phase':jd['phase'], 'cent_freq':jd['cent_freq'], 
                        'mod_freq':jd['mod_freq'], 'stop_time':dt, 'read_time':time,
                        'stop_stamp':jd['stop_stamp'],'date':jd['date'],'label':jd['label'],
                         'base_file':self.basefile_path}})                    
                    else:               # if reading from eventfile
                        self.events.update({utcstamp: {'channel':jd['channel']['name'],
                            'freq_list':jd['freq_list'], 'sweeps':jd['sweeps'], 
                            'phase':jd['phase'], 'cent_freq':jd['channel']['cent_freq'], 
                            'mod_freq':jd['channel']['mod_freq'], 'stop_time':dt, 
                            'read_time':time, 'stop_stamp':jd['stop_stamp'],'date':date,'label':jd['label'],
                            'base_file':self.basefile_path}})
                    # >>> UNH-HOOK quad-phase: keep each row's reference angle, so baselines are built per angle
                    if 'quad_ref_deg' in jd:
                        self.events[utcstamp]['quad_ref_deg'] = jd['quad_ref_deg']
                        self.events[utcstamp]['phase_vout'] = jd.get('phase_vout')
                    # <<< UNH-HOOK quad-phase
                      
            self.publish_status_message('Opened event file '+self.basefile_path)
            #self.event_model.clear()
            self.event_model.removeRows(0, self.event_model.rowCount())
            for i,stamp in enumerate(self.events.keys()):
                self.event_model.setItem(i,0,QStandardItem(str(stamp)))
                self.event_model.setItem(i,1,QStandardItem(self.events[stamp]['date']))
                self.event_model.setItem(i,2,QStandardItem(self.events[stamp]['read_time']))
                self.event_model.setItem(i,3,QStandardItem(str(self.events[stamp]['sweeps'])))
                self.event_model.setItem(i,4,QStandardItem(str(self.events[stamp]['cent_freq'])))
                self.event_model.setItem(i,5,QStandardItem(str(self.events[stamp]['mod_freq'])))
                self.event_model.setItem(i,6,QStandardItem(str(self.events[stamp]['channel'])))
                self.event_model.setItem(i,7,QStandardItem(str(self.events[stamp]['label'])))
        # >>> UNH-HOOK quad-phase: Angle and Phase DAC columns, so quadrature rows can be told apart
        if getattr(self.parent, 'quadrature', None) is not None and self.parent.quadrature.ui is not None:
            self.parent.quadrature.ui.base_table(self)
        # <<< UNH-HOOK quad-phase
 
    def select_event(self):    #,item):      
        '''Choose events selected from table, average to set as baseline and plot'''
        self.base_phase_avg = np.zeros(len(self.parent.event.scan.phase))
        freqs = []
        stamp = 0
        sweeps = 0
        self.base_stamps = []
        self.base_dict = {}
        for index in sorted(self.event_table.selectionModel().selectedRows()):   # average multiple events together, take timestamp of last event
            #print(index.row(), self.event_model.data(self.event_model.index(index.row(),0)))
            #print(self.event_model.data(self.event_model.index(item.row(),0)))
            stamp = self.event_model.data(self.event_model.index(index.row(),0))
            freqs = self.events[stamp]['freq_list']
            new_phase = np.array(self.events[stamp]['phase'])
            self.base_phase_avg = (self.base_phase_avg*sweeps + new_phase*self.events[stamp]['sweeps'])/(sweeps + self.events[stamp]['sweeps'])
            sweeps = sweeps + self.events[stamp]['sweeps']
            self.base_stamps.append(stamp)  
            self.base_dict = dict(self.events[stamp])    # using most entries from last baseline
        self.base_dict['sweeps'] = sweeps 
        self.base_dict['phase'] = self.base_phase_avg
        self.base_dict['base_stamps'] = self.base_stamps
        self.last_stamp = stamp
        #self.base_stamp = self.event_model.data(self.event_model.index(item.row(),0))        #self.base_plot.setData(self.events[self.base_stamp]['freq_list'],self.events[self.base_stamp]['phase'])  
        self.base_plot.setData(freqs, self.base_phase_avg)  
        sub = self.parent.event.scan.phase - self.base_phase_avg        
        self.sub_plot.setData(freqs,sub)    
        # >>> UNH-HOOK quad-phase: quadrature rows are averaged per reference angle, never mixed
        self.quad_bases = None
        if getattr(self.parent, 'quadrature', None) is not None:
            from unh.quadrature.records import group_baselines
            self.quad_bases = group_baselines(self.events, self.base_stamps)
            if self.quad_bases:
                self.base_dict = self.quad_bases[0 if 0 in self.quad_bases else min(self.quad_bases)]
                self.base_phase_avg = self.base_dict['phase']
                self.base_plot.setData(freqs, self.base_phase_avg)
                self.sub_plot.setData(freqs, self.parent.event.scan.phase - self.base_phase_avg)
            if self.parent.quadrature.ui is not None:
                self.parent.quadrature.ui.base_selected(self)     # per-angle summary and plot
        # <<< UNH-HOOK quad-phase

    def set_base(self):
        '''Send baselines chosen to be set as the baseline for future events'''
        try:
            # >>> UNH-HOOK quad-phase: per-angle baselines; the main baseline is replaced only by a 0 deg one
            # JLab: self.parent.new_base(self.base_dict)
            quad_bases = getattr(self, 'quad_bases', None)
            if quad_bases:
                self.parent.quadrature.new_baselines(quad_bases)
                if 0 in quad_bases:
                    self.parent.new_base(quad_bases[0])
                else:
                    self.parent.set_event_base()
            else:
                if getattr(self.parent, 'quadrature', None) is not None:
                    self.parent.quadrature.clear_baselines()     # an untagged baseline replaces all angles'
                self.parent.new_base(self.base_dict)
            # <<< UNH-HOOK quad-phase
        except Exception as e:
            self.publish_status_message(f"Error setting baseline: {self.events[self.last_stamp]['read_time']} {e}")
        #filename = re.findall('data.*\.txt', self.parent.event.base_file)
        #self.curr_base_line.setText(filename[0]+', '+ str(self.parent.event.base_time))
        self.curr_base_line.setText(str(self.parent.event.base_time))
        self.print_to_recent(self.base_dict)    
        # >>> UNH-HOOK quad-phase: the other angles' baselines go to the recent-baselines file too
        for angle, base in (getattr(self, 'quad_bases', None) or {}).items():
            if base is not self.base_dict:
                self.print_to_recent(base)
        # <<< UNH-HOOK quad-phase
        
    def print_to_recent(self, base_dict):
        '''Prints selected baseline information to recent baselines file for reuse'''
        base_dict = dict(base_dict)   # UNH-HOOK base-drag: a copy, so a second Set Baseline still has real dates
        
        recentfile = open(self.basefile_name, "a")
        for key, entry in base_dict.items():   
            if isinstance(entry, np.ndarray):       
                base_dict[key] = entry.tolist()            
            if isinstance(entry, datetime.datetime):
                base_dict.update({key:entry.__str__()})  # datetime to string  
        json_record = json.dumps(base_dict)
        recentfile.write(json_record+'\n')               # write to file as json line
        recentfile.close()
        

    def divider(self):
        div = QLabel ('')
        div.setStyleSheet ("QLabel {background-color: #eeeeee; padding: 0; margin: 0; border-bottom: 0 solid #eeeeee; border-top: 1 solid #eeeeee;}")
        div.setMaximumHeight (2)
        return div   
        
