'''PyNMR, J.Maxwell 2020
'''
import datetime
import time
import pytz
import numpy as np
from PySide6.QtWidgets import QWidget, QLabel, QGroupBox, QHBoxLayout, QVBoxLayout, QGridLayout, QLineEdit, QSpacerItem, QSizePolicy, QComboBox, QPushButton, QTableView, QAbstractItemView, QAbstractScrollArea
from PySide6.QtGui import QIntValidator, QDoubleValidator, QValidator, QStandardItemModel, QStandardItem
import pyqtgraph as pg
from scipy import optimize
 
from core.calculations import TE, SPECIES

class TETab(QWidget): 
    '''Creates settings tab'''   
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        self.time_pen = pg.mkPen(color=(0, 0, 204), width=1.5)
        self.fit1_pen = pg.mkPen(color=(0, 0, 150), width=1.5)
        self.zoom_pen = pg.mkPen(color=(0, 180, 0), width=1.5)
        self.fit2_pen = pg.mkPen(color=(0, 130, 0), width=1.5)
        
        self.main = QHBoxLayout()            # main layout
        
        # Left Side
        self.left = QVBoxLayout() 
                        
               
        # Populate run box, include exp fit from recent history     
        self.run_box = QGroupBox('Area History')
        self.left.addWidget(self.run_box)
        self.run_box.setLayout(QVBoxLayout())  
        self.time_layout = QGridLayout()
        self.run_box.layout().addLayout(self.time_layout)
        self.range_label = QLabel('History to Show (min):')
        self.time_layout.addWidget(self.range_label, 1, 0) 
        self.range_value = QLineEdit('60')
        self.range_value.setValidator(QIntValidator(1,10000))
        self.time_layout.addWidget(self.range_value, 1, 1)         
        self.run_box.layout().addWidget(self.parent.divider()) 
        self.fit_label = QLabel('Fit info go here when points selected in upper graph')
        self.run_box.layout().addWidget(self.fit_label)
        
            
        self.calc_box = QGroupBox('TE Calculator')
        self.left.addWidget(self.calc_box)
        self.calc_box.setLayout(QVBoxLayout()) 
        self.calc_top = QGridLayout()
        self.species_label = QLabel('Species:')
        self.calc_top.addWidget(self.species_label, 0, 0)
        self.species_box = QComboBox()
        self.species_box.addItems(list(SPECIES))    # currentText() gives status of combobox
        self.calc_top.addWidget(self.species_box, 0, 1)
        self.field_label = QLabel('B Field (T):')
        self.calc_top.addWidget(self.field_label, 0, 2)
        self.field_value = QLineEdit('5.00')
        self.field_value.setValidator(QDoubleValidator(0.0, 10.0, 3))
        self.calc_top.addWidget(self.field_value, 0, 3)
        self.calc_box.layout().addLayout(self.calc_top)
            
        self.calc_box.layout().addWidget(self.parent.divider()) 
        self.fitselect_label = QLabel('Points selected in lower graph appear here. Double-click row to remove point.')
        self.calc_box.layout().addWidget(self.fitselect_label)
        
        self.te_model = QStandardItemModel()
        self.te_model.setHorizontalHeaderLabels(['Date/Time','Area','Temp (K)'])
        self.te_table = QTableView()
        self.te_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.te_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.te_table.resizeColumnsToContents()
        self.te_table.setModel(self.te_model)
        self.te_table.doubleClicked.connect(self.double_clicked)
        self.te_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.calc_box.layout().addWidget(self.te_table)
        self.te_but_lay = QHBoxLayout()
        self.calc_box.layout().addLayout(self.te_but_lay)
        self.te_but = QPushButton('Calculate TE from Points')
        self.te_but.setEnabled(False)
        self.te_but.clicked.connect(self.take_te) 
        self.te_but_lay.addWidget(self.te_but)
        self.set_but = QPushButton('Save Results && Use CC')
        self.set_but.setEnabled(False)
        self.te_but_lay.addWidget(self.set_but)
        self.set_but.clicked.connect(self.use_te)               
        
        
        self.result_box = QGroupBox('TE Results')
        self.calc_box.layout().addWidget(self.result_box)
        self.result_box.setLayout(QVBoxLayout()) 
        self.teselect_label = QLabel('TE results will appear here.')
        self.result_box.layout().addWidget(self.teselect_label)
                
        self.main.addLayout(self.left)
        
        # Right Side
        self.right = QVBoxLayout()    
        # Time/fit plot
        self.time_axis = pg.DateAxisItem(orientation='bottom')    
        self.time_wid = pg.PlotWidget(title='Area vs. Time', axisItems={'bottom': self.time_axis})
        self.time_wid.showGrid(True,True)
        self.time_plot = self.time_wid.plot([], [], pen=self.time_pen) 
        self.region1 = pg.LinearRegionItem(brush=pg.mkBrush(0, 0, 204, 30))
        self.region1.setRegion([datetime.datetime.now(tz=datetime.timezone.utc).timestamp(), datetime.datetime.now(tz=datetime.timezone.utc).timestamp()+60])
        self.region1.sigRegionChangeFinished.connect(self.changed_region1)
        self.time_wid.addItem(self.region1)
        self.right.addWidget(self.time_wid)  
        # Zoom/select plot
        self.time_axis2 = pg.DateAxisItem(orientation='bottom')   
        self.zoom_wid = pg.PlotWidget(title='Select for TE', axisItems={'bottom': self.time_axis2})
        self.zoom_wid.showGrid(True,True)
        self.zoom_plot = self.zoom_wid.plot([], [], pen=self.zoom_pen) 
        self.region2 = pg.LinearRegionItem(brush=pg.mkBrush(0, 180, 0, 30))
        self.region2.setRegion([datetime.datetime.now(tz=datetime.timezone.utc).timestamp(),datetime.datetime.now(tz=datetime.timezone.utc).timestamp()+60])
        self.region2.sigRegionChangeFinished.connect(self.changed_region2)
        self.zoom_wid.addItem(self.region2)
        self.right.addWidget(self.zoom_wid)  
        self.fit1_plot = self.time_wid.plot([], [], pen=self.fit1_pen) 
        self.fit2_plot = self.zoom_wid.plot([], [], pen=self.fit2_pen) 
              
        
        self.main.addLayout(self.right)
        self.setLayout(self.main)   
    
    def changed_region1(self, region1):
        '''Update zoom plot from selection, fit selection'''
        try:
            lo, hi = region1.getRegion()
            self.fit1_plot.setData([lo], np.zeros(1))
            self.zoom_data = self.time_data[np.any((self.time_data > lo)&(self.time_data < hi), axis=1), :]   # select rows within
            self.zoom_plot.setData(self.zoom_data)  
            self.region2.setRegion([self.zoom_data[-1,0] + (self.zoom_data[0,0]-self.zoom_data[-1,0])/4, self.zoom_data[-1,0]])
            self.fit2_plot.setData([self.zoom_data[0,0]], np.zeros(1))
        except IndexError:
            pass
        
        try:
            pf, pstd = self.fit_exp(self.zoom_data)
            space = np.linspace(self.zoom_data[0,0], self.zoom_data[-1,0], 100)
            self.fit1_plot.setData(space, pf[0] + pf[1]*np.exp((space-pf[2])/pf[3]))
            self.fit_label.setText(f'Fit relaxation time {pf[3]:.0e} secs ± {pstd[3]:.0e}, asymptote {pf[0]:.2f} ± {pstd[0]:.2f}.')   
        except RuntimeError as e:
            self.fit_label.setText(f'Fit failed, max iterations reached.')  
        except TypeError as e:
            self.fit_label.setText(f'Fit failed: {e}')          
            
            
    def changed_region2(self, region2):
        '''Update zoom plot from selection, fit selection'''        
        self.te_but.setEnabled(True)
        lo, hi = region2.getRegion()
        self.te_data = self.zoom_data[np.any((self.zoom_data > lo)&(self.zoom_data < hi), axis=1), :]  # select rows 

        pf, pstd = self.fit_lin(self.te_data)
        space = np.linspace(self.te_data[0,0], self.te_data[-1,0], 100)
        self.fit2_plot.setData(space, pf[0] + pf[1]*space)
        self.fitselect_label.setText(f'Double click to remove point. Fit slope {pf[1]:.2e} ± {pstd[1]:.2e}.')
        
        self.te_model.setRowCount(0)    # empty table
        for i,stamp in enumerate(list(self.te_data[:,0])):        # put data in table, hist_points keyed on timestamp
            self.te_model.setItem(i,0,QStandardItem(self.hist_points[stamp].dt.strftime("%H:%M:%S")))
            self.te_model.setItem(i,1,QStandardItem(f"{self.hist_points[stamp].area:.10f}"))
            # >>> UNH-HOOK te-fix: a missing temperature reading shows as nan instead of raising
            # JLab: self.te_model.setItem(i,2,QStandardItem(f"{self.hist_points[stamp].epics_reads[self.parent.settings['epics_settings']['epics_temp']]:.4f}"))
            self.te_model.setItem(i,2,QStandardItem(f"{self.te_temp(stamp):.4f}"))
            # <<< UNH-HOOK te-fix
        
    def double_clicked(self, item):
        '''Remove event from table when double clicked'''
        self.te_data = np.delete(self.te_data, item.row(), 0)
        self.te_model.setRowCount(0)    # empty table
        for i,stamp in enumerate(list(self.te_data[:,0])):        # put data in table, hist_points keyed on timestamp
            self.te_model.setItem(i,0,QStandardItem(self.hist_points[stamp].dt.strftime("%H:%M:%S")))
            self.te_model.setItem(i,1,QStandardItem(str(self.hist_points[stamp].area)))
            # >>> UNH-HOOK te-fix: a missing temperature reading shows as nan instead of raising
            # JLab: self.te_model.setItem(i,2,QStandardItem(str(self.hist_points[stamp].epics_reads[self.parent.settings['epics_settings']['epics_temp']])))
            self.te_model.setItem(i,2,QStandardItem(str(self.te_temp(stamp))))
            # <<< UNH-HOOK te-fix
    
    def update_event_plots(self): 
        '''Update time plot as running'''
        hist_data = {}
        #time_fix = 3600  
        new_hist_data = self.parent.history.to_plot(datetime.datetime.now(tz=datetime.timezone.utc).timestamp() - 60*int(self.range_value.text()), datetime.datetime.now(tz=datetime.timezone.utc).timestamp())  # dict of Hist objects keyed on stamps
        for k,v in new_hist_data.items():
            if 'TE' in v.label or 'None' in v.label:  
                hist_data[k] = v
            # exclude unless labelled as TE, or not labeled
        self.time_data = np.column_stack((list(hist_data.keys()),[hist_data[k].area for k in hist_data.keys()])) # 2-d nparray to plot 
        lo, hi = self.region1.getRegion()
        if np.any(self.time_data):
            if hi < self.time_data[0,0]:
                self.region1.setRegion([self.time_data[0,0],self.time_data[0,0]])     
                self.fit1_plot.setData([self.time_data[0,0]], np.zeros(1))         
        self.time_plot.setData(self.time_data)   #plot
        self.hist_points = {t:hist_data[t] for t in list(self.time_data[:,0])}    # keyed on timestamp
           
            
    def take_te(self):
        '''Send points for TE to make TE object'''
        times, areas = self.te_data.T
        # >>> UNH-HOOK te-fix: refuse a TE without real temperatures (a missing or 0 K reading gave P_TE near 1 silently)
        # JLab: temps = np.fromiter((self.hist_points[k].epics_reads[self.parent.settings['epics_settings']['epics_temp']] for k in times.flatten()), np.double)
        temps = np.array([self.te_temp(k) for k in times.flatten()], dtype=float)
        if not np.all(np.isfinite(temps) & (temps > 0)):
            self.teselect_label.setText(f'TE not taken: {np.sum(~(np.isfinite(temps) & (temps > 0)))} of {len(temps)} '
                                        f'selected events have no temperature reading (is EPICS on?).')
            self.set_but.setEnabled(False)
            return
        # <<< UNH-HOOK te-fix
        self.te = TE(self.species_box.currentText(), float(self.field_value.text()), areas.flatten(), temps)
        self.set_but.setEnabled(True)
        self.teselect_label.setText(self.te.pretty_te())   
        
    def use_te(self):
        '''Print TE out to json file named after time taken, set CC'''
        # >>> UNH-HOOK te-fix: TE report goes to settings te_dir (relative to the working folder)
        # JLab: self.te.print_te()
        self.te.print_te(self.parent.settings.get('te_dir', 'te'))
        # <<< UNH-HOOK te-fix
        self.parent.set_cc(self.te.cc)
    # >>> UNH-HOOK te-fix: temperature of a history point, nan if it wasn't read

    def te_temp(self, stamp):
        '''Temperature (K) recorded with a history point, or nan if the reading is missing'''
        value = self.hist_points[stamp].epics_reads.get(self.parent.settings['epics_settings']['epics_temp'])
        try:
            return float(value)
        except (TypeError, ValueError):
            return float('nan')
    # <<< UNH-HOOK te-fix
        
    def fit_exp(self,data):
        '''Exponential fit to area of time data with scipy
        
        Args:
            data: 2-D numpy array with time and area data
            
        Returns:
            pf: Tuple of final fit coefficient list 
        
        '''
        now = datetime.datetime.now(tz=datetime.timezone.utc).timestamp()
        p0 = [0.05, -0.05, now, 10000]  # initial guess
        x, y = np.hsplit(data,2)
        x, y = x.flatten(), y.flatten()
        pf, pcov = optimize.curve_fit(lambda t, a, b, c, d: a + b*np.exp((t-c)/d), x, y, p0 = p0)
        return pf, np.sqrt(np.diag(pcov))   
        
    def fit_lin(self,data):
        '''Linear fit to area of time data with scipy
        
        Args:
            data: 2-D numpy array with time and area data
            
        Returns:
            pf: Tuple of final fit coefficient list 
        
        '''
        p0 = [0.01, 0.001]  # initial guess
        x, y = np.hsplit(data,2)
        x, y = x.flatten(), y.flatten()
        pf, pcov = optimize.curve_fit(lambda t, a, b: a + t*b, x, y, p0 = p0)
        return pf, np.sqrt(np.diag(pcov))   
        
        
        
