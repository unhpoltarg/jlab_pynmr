"""
Analysis Tab for PyNMR

Replicates the original 3-PlotWidget structure with event bus integration.
"""

import numpy as np
import time
from scipy import optimize
from PySide6.QtWidgets import QWidget, QLabel, QGroupBox, QHBoxLayout, QVBoxLayout, QGridLayout, QLineEdit, QSpacerItem, QSizePolicy, QComboBox, QPushButton, QProgressBar, QStackedWidget, QDoubleSpinBox
import pyqtgraph as pg
from lmfit import Model

from core.tab_base import EventBusTab, AnalysisTabEventHandler
from core.event_bus import EventType

# Import the existing analysis classes
from .analysis_modules import (StandardBase, PolyFitBase, CircuitBase, NoBase,
                          PolyFitSub, NoFitSub, SumAllRes, SumRangeRes, 
                          PeakHeightRes, FitPeakRes, FitPeakRes2, FitDeuteron)


class AnalTab(EventBusTab):
    """Analysis tab with event bus integration and correct plot structure."""

    def __init__(self, parent=None):
        super().__init__("analysis", parent)

        # Store reference to main window for data access
        self._main_window = parent

        # Color definitions (match original)
        self.base_pen = pg.mkPen(color=(180, 0, 0), width=1.5)
        self.base2_pen = pg.mkPen(color=(0, 0, 150), width=1.5)
        self.base3_pen = pg.mkPen(color=(0, 180, 0), width=1.5)
        self.sub_pen = pg.mkPen(color=(180, 0, 0), width=1.5)
        self.sub2_pen = pg.mkPen(color=(0, 0, 150), width=1.5)
        self.sub3_pen = pg.mkPen(color=(0, 180, 0), width=1.5)
        self.res_pen = pg.mkPen(color=(180, 0, 0), width=1.5)
        self.res2_pen = pg.mkPen(color=(0, 0, 150), width=1.5)
        self.res3_pen = pg.mkPen(color=(0, 180, 0), width=1.5)
        
        self.base_chosen = None
        self.sub_chosen = None
        self.res_chosen = None
        
        self.current_event = None  # Will be updated via event bus
        
        # Analysis throttling to prevent excessive thread creation
        self._last_analysis_time = 0
        self._analysis_throttle_ms = 500  # Minimum time between analysis runs
        
        # Create compatibility layer for existing analysis classes
        # They expect self.parent.parent to have event, config, etc.
        self.parent = self  # For compatibility
        
        self._init_ui()
    
    @property
    def event(self):
        """Get current event for compatibility with existing analysis classes."""
        event = getattr(getattr(self, '_main_window', None), 'event', None) or self.get_current_event() or self.get_previous_event()
        if event is None:
            # Create a minimal event object for initialization
            # This provides the config during startup
            class MinimalEvent:
                def __init__(self, config):
                    self.config = config
                    # Create a minimal scan object with frequency list
                    class MinimalScan:
                        def __init__(self, config):
                            import numpy as np
                            # Use config frequency list or create a default one
                            if hasattr(config, 'freq_list'):
                                self.freq_list = config.freq_list
                            else:
                                self.freq_list = np.linspace(90, 110, 100)  # Default range
                    self.scan = MinimalScan(config)
            config = self.get_config()
            if config:
                event = MinimalEvent(config)
        return event
    
    @property
    def config(self):
        """Get config for compatibility with existing analysis classes. Main window's config is replaced on channel change."""
        return getattr(getattr(self, '_main_window', None), 'config', None) or self.get_config()
    
    @property
    def previous_event(self):
        """Get previous event for compatibility."""
        return self.get_previous_event()
        
    def _init_event_handler(self) -> None:
        """Initialize event handler for analysis tab."""
        self._event_handler = AnalysisTabEventHandler(self)
    
    def _init_ui(self):
        """Initialize the user interface."""
        self.main = QHBoxLayout()
        self.setLayout(self.main)   
        
        # Left Side
        self.left = QVBoxLayout() 
        self.main.addLayout(self.left)
        
        # Baseline options box
        self.base_box = QGroupBox('Baseline Options')
        self.base_box.setLayout(QVBoxLayout())
        self.left.addWidget(self.base_box)
        self.base_combo = QComboBox()
        self.base_box.layout().addWidget(self.base_combo)
        self.base_stack = QStackedWidget()
        self.base_box.layout().addWidget(self.base_stack)

        # Subtraction options box
        self.sub_box = QGroupBox('Subtraction Options')
        self.sub_box.setLayout(QVBoxLayout())
        self.left.addWidget(self.sub_box)
        self.sub_combo = QComboBox()
        self.sub_box.layout().addWidget(self.sub_combo)
        self.sub_stack = QStackedWidget()
        self.sub_box.layout().addWidget(self.sub_stack)

        # Result options box
        self.res_box = QGroupBox('Result Options')
        self.res_box.setLayout(QVBoxLayout())
        self.left.addWidget(self.res_box)
        self.res_combo = QComboBox()
        self.res_box.layout().addWidget(self.res_combo)
        self.res_stack = QStackedWidget()
        self.res_box.layout().addWidget(self.res_stack)
        
        # Right side - plots (CRITICAL: Create the 3 PlotWidget structure)
        self.right = QVBoxLayout()
        self.main.addLayout(self.right)
        
        # Initialize plots using exact same structure as original
        self._init_plots()
        
        # Initialize analysis options after plots/regions are ready
        self._init_baseline_options()
        self._init_subtraction_options()
        self._init_result_options()
        
        # Connect combo boxes
        self.base_combo.currentIndexChanged.connect(self.change_base)
        self.sub_combo.currentIndexChanged.connect(self.change_sub)
        self.res_combo.currentIndexChanged.connect(self.change_res)
        
        # Initialize default selections
        self._init_defaults()
    
    def _init_plots(self):
        """Initialize plot widgets - EXACT replica of original structure."""
        
        # Plot 1: Baseline Subtraction (contains raw_plot, base_plot, basesub_plot)
        self.base_wid = pg.PlotWidget(title='Baseline Subtraction')
        self.base_wid.showGrid(True, True)
        self.base_wid.addLegend(offset=(0.5, 0))
        self.base_wid.setMinimumHeight(100)
        self.base_wid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.raw_plot = self.base_wid.plot([], [], pen=self.base_pen, name='Raw Signal')
        self.base_plot = self.base_wid.plot([], [], pen=self.base2_pen, name='Baseline')
        self.basesub_plot = self.base_wid.plot([], [], pen=self.base3_pen, name='Subtracted') 
        
        # Create regions for base plot (need event for initialization)
        event = self.event
        if event and hasattr(event, 'scan') and hasattr(event.scan, 'freq_list'):
            freq_min = event.scan.freq_list.min()
            freq_max = event.scan.freq_list.max()
        else:
            freq_min, freq_max = 90, 110  # Default range
            
        self.base_region1 = pg.LinearRegionItem(pen=pg.mkPen(0, 180, 0, 0), brush=pg.mkBrush(0, 180, 0, 0))
        self.base_region1.setMovable(False)
        self.base_region1.setRegion([freq_min, freq_min])
        self.base_wid.addItem(self.base_region1)
        self.base_region2 = pg.LinearRegionItem(pen=pg.mkPen(0, 180, 0, 0), brush=pg.mkBrush(0, 180, 0, 0))
        self.base_region2.setMovable(False)
        self.base_region2.setRegion([freq_max, freq_max])
        self.base_wid.addItem(self.base_region2)
        self.right.addWidget(self.base_wid)

        # Plot 2: Fit Subtraction (contains sub_plot, fit_plot, fitsub_plot)
        self.sub_wid = pg.PlotWidget(title='Fit Subtraction')
        self.sub_wid.showGrid(True, True)
        self.sub_wid.addLegend(offset=(0.5, 0))
        self.sub_wid.setMinimumHeight(100)
        self.sub_wid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sub_plot = self.sub_wid.plot([], [], pen=self.sub_pen, name='Baseline Subtracted')
        self.fit_plot = self.sub_wid.plot([], [], pen=self.sub2_pen, name='Fit')
        self.fitsub_plot = self.sub_wid.plot([], [], pen=self.sub3_pen, name='Subtracted') 
        self.sub_region1 = pg.LinearRegionItem(pen=pg.mkPen(0, 180, 0, 0), brush=pg.mkBrush(0, 0, 180, 0))
        self.sub_region1.setMovable(False)
        self.sub_region1.setRegion([freq_min, freq_min])
        self.sub_wid.addItem(self.sub_region1)
        self.sub_region2 = pg.LinearRegionItem(pen=pg.mkPen(0, 180, 0, 0), brush=pg.mkBrush(0, 0, 180, 0))
        self.sub_region2.setMovable(False)
        self.sub_region2.setRegion([freq_max, freq_max])
        self.sub_wid.addItem(self.sub_region2)
        self.right.addWidget(self.sub_wid)
                
        # Plot 3: Results (contains unc_plot, res_plot)
        self.res_wid = pg.PlotWidget(title='Results')
        self.res_wid.showGrid(True, True)
        self.res_wid.addLegend(offset=(0.5, 0))
        self.res_wid.setMinimumHeight(100)
        self.res_wid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.unc_plot = self.res_wid.plot([], [], pen=self.res_pen, name='Fit Subtracted')
        self.res_plot = self.res_wid.plot([], [], pen=self.sub3_pen, name='Result') 
        self.res_region = pg.LinearRegionItem(pen=pg.mkPen(0, 180, 0, 0), brush=pg.mkBrush(0, 180, 0, 0))
        self.res_region.setMovable(False)
        self.res_region.setRegion([freq_max, freq_max])
        self.res_wid.addItem(self.res_region)
        self.right.addWidget(self.res_wid)        
    
    def _init_baseline_options(self):
        """Initialize baseline analysis options."""
        # Create instances of existing analysis classes, adapted for event bus
        self.base_opts = []
        self.base_opts.append(StandardBase(self))   
        self.base_opts.append(PolyFitBase(self))  
        # self.base_opts.append(CircuitBase(self))   # Not ready for prime time
        self.base_opts.append(NoBase(self))        
        
        # Add baseline analysis methods
        for opt in self.base_opts:
            self.base_combo.addItem(opt.name)
            self.base_stack.addWidget(opt)
    
    def _init_subtraction_options(self):
        """Initialize subtraction options."""
        # Create instances of existing subtraction classes
        self.sub_opts = []
        self.sub_opts.append(PolyFitSub(self))
        self.sub_opts.append(NoFitSub(self))
        
        # Add subtraction methods
        for opt in self.sub_opts:
            self.sub_combo.addItem(opt.name)
            self.sub_stack.addWidget(opt)
    
    def _init_result_options(self):
        """Initialize result options."""
        # Create instances of existing result classes
        self.res_opts = []
        self.res_opts.append(SumAllRes(self))
        self.res_opts.append(SumRangeRes(self))
        self.res_opts.append(PeakHeightRes(self))
        self.res_opts.append(FitPeakRes(self))
        self.res_opts.append(FitPeakRes2(self))
        self.res_opts.append(FitDeuteron(self))
        # >>> UNH-HOOK mcclellan-fit: Optimized McClellan Fits (Equilibrium, ssRF), the online fitter's own fits
        try:
            from unh.mcclellan import mcclellan_result_options
            self.res_opts += mcclellan_result_options(self)
        except ImportError:
            pass
        # <<< UNH-HOOK mcclellan-fit
        
        # Add result methods
        for opt in self.res_opts:
            self.res_combo.addItem(opt.name)
            self.res_stack.addWidget(opt)
    
    def _init_defaults(self):
        """Initialize default selections from config."""
        config = self.get_config()
        if config:
            # Setup default methods
            self.base_combo.setCurrentIndex(config.settings['analysis']['base_def'])
            self.change_base(config.settings['analysis']['base_def'])
            
            self.sub_combo.setCurrentIndex(config.settings['analysis']['sub_def'])
            self.change_sub(config.settings['analysis']['sub_def'])
            
            self.res_combo.setCurrentIndex(config.settings['analysis']['res_def'])
            self.change_res(config.settings['analysis']['res_def'])
    
    def change_base(self, i):
        """Change baseline method."""
        self.base_stack.setCurrentIndex(i)
        
        # Set baseline method from existing analysis classes
        if i < len(self.base_opts):
            self.base_chosen = self.base_opts[i].result
            self.base_opts[i].switch_here()
        
        # Run analysis immediately like original analysis tab
        self.run_analysis()
        
        # Also publish parameter change event for consistency
        self.publish_analysis_parameters_changed({
            "base_method": i,
            "source": "baseline_combo"
        })
    
    def change_sub(self, i):
        """Change subtraction method."""
        self.sub_stack.setCurrentIndex(i)
        
        # Set subtraction method from existing analysis classes
        if i < len(self.sub_opts):
            self.sub_chosen = self.sub_opts[i].result
            self.sub_opts[i].switch_here()
        
        # Run analysis immediately like original analysis tab
        self.run_analysis()
        
        # Also publish parameter change event for consistency
        self.publish_analysis_parameters_changed({
            "sub_method": i,
            "source": "subtraction_combo"
        })
    
    def change_res(self, i):
        """Change result method."""
        self.res_stack.setCurrentIndex(i)
        
        # Set result method from existing analysis classes
        if i < len(self.res_opts):
            self.res_chosen = self.res_opts[i].result
            self.res_opts[i].switch_here()
        
        # Run analysis immediately like original analysis tab
        self.run_analysis()
        
        # Also publish parameter change event for consistency
        self.publish_analysis_parameters_changed({
            "res_method": i,
            "source": "result_combo"
        })
    
    def run_analysis(self):
        """Run event signal analysis if needed and call for new plots if base and sub methods are chosen."""
        # Get previous event directly from main window (like original)
        self.current_event = self._main_window.previous_event
        
        if self.base_chosen and self.sub_chosen and self.res_chosen:
            # Always run analysis when parameters change (re-analysis allowed)
            if self.current_event:
                # Reset the analysis_completed flag to allow re-analysis
                self.current_event.analysis_completed = False
                self.current_event.signal_analysis(self.base_chosen, self.sub_chosen, self.res_chosen)
                self.current_event.analysis_completed = True
            self.update_event_plots()

    def update_event_plots(self):
        """Update analysis tab plots using event bus data - EXACT replica of original method."""
        # Use same pattern as original: access parent (main window) directly
        try:
            # Use the stored main window reference
            main_window = self._main_window
            
            if not main_window:
                return
                
            # Get previous_event and event exactly like original
            self.current_event = main_window.previous_event
            
            # Only update plots if analysis has been completed and data exists
            if (self.current_event and hasattr(self.current_event, 'basesweep') and 
                hasattr(self.current_event, 'basesub') and hasattr(self.current_event, 'fitsub') and
                hasattr(self.current_event, 'rescurve') and hasattr(self.current_event, 'fitcurve') and
                isinstance(self.current_event.basesweep, np.ndarray) and
                isinstance(self.current_event.basesub, np.ndarray)):
                
                freqs = self.current_event.scan.freq_list
                fmin, fmax = freqs.min(), freqs.max()

                raw_signal = self.current_event.scan.phase - self.current_event.scan.phase.max()
                baseline_curve = self.current_event.basesweep - self.current_event.basesweep.max()

                self.raw_plot.setData(freqs, raw_signal)
                self.base_plot.setData(freqs, baseline_curve)
                self.basesub_plot.setData(freqs, self.current_event.basesub - self.current_event.basesub.max())

                self.sub_plot.setData(freqs, self.current_event.basesub - self.current_event.basesub.max())
                self.fit_plot.setData(freqs, self.current_event.fitcurve - self.current_event.basesub.max())
                self.fitsub_plot.setData(freqs, self.current_event.fitsub)

                self.unc_plot.setData(freqs, self.current_event.fitsub)
                self.res_plot.setData(freqs, self.current_event.rescurve)

                self.base_wid.setXRange(fmin, fmax, padding=0.02)
                self.sub_wid.setXRange(fmin, fmax, padding=0.02)
                self.res_wid.setXRange(fmin, fmax, padding=0.02)

                # Reposition regions to match new frequency range
                base_opt = self.base_opts[self.base_combo.currentIndex()]
                if hasattr(base_opt, 'wings'):
                    b = [w * (fmax - fmin) + fmin for w in base_opt.wings]
                    self.base_region1.setRegion(b[:2])
                    self.base_region2.setRegion(b[2:])

                sub_opt = self.sub_opts[self.sub_combo.currentIndex()]
                if hasattr(sub_opt, 'wings'):
                    b = [w * (fmax - fmin) + fmin for w in sub_opt.wings]
                    self.sub_region1.setRegion(b[:2])
                    self.sub_region2.setRegion(b[2:])

                res_opt = self.res_opts[self.res_combo.currentIndex()]
                if hasattr(res_opt, 'wings'):
                    b = [w * (fmax - fmin) + fmin for w in res_opt.wings]
                    self.res_region.setRegion(b)
                    self.res_region.setVisible(True)
                else:
                    self.res_region.setVisible(False)
                
        except Exception as e:
            # Log error silently - analysis tab should not crash the application
            pass
    
    def update_plots(self):
        """Called by event handler when plots need updating."""
        self.update_event_plots()
    
    def refresh_analysis(self):
        """Called by event handler when analysis is completed."""
        self.update_event_plots()
    
    def on_event_updated(self, event_data):
        """Handle event updated from event bus."""
        self.current_event = event_data.get('previous_event')
        self.update_event_plots()
    
    def cleanup(self):
        """Clean up tab resources."""
        super().cleanup()