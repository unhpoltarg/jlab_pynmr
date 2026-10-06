'''J.Maxwell 2020
'''
import numpy as np
import datetime
import pytz
import json
import os   # UNH-HOOK te-fix
from scipy.constants import physical_constants, k as boltz_const

NUC_MAGNETON = physical_constants['nuclear magneton'][0]   # J/T

# Species name: (magnetic moment in J/T, spin I)
# Proton and deuteron moments are CODATA. Li moments (in nuclear magnetons) are not in CODATA;
# values from N.J. Stone, Table of Nuclear Magnetic Dipole Moments (IAEA INDC(NDS)-0658).
SPECIES = {
    'Proton':    (physical_constants['proton mag. mom.'][0], 1/2),
    'Deuteron':  (physical_constants['deuteron mag. mom.'][0], 1),
    'Lithium-6': (0.822043 * NUC_MAGNETON, 1),
    'Lithium-7': (3.256407 * NUC_MAGNETON, 3/2),
}


def match_species(species):
    '''Map a flexible species string (e.g. "p", "Deuteron", "Li7", "6Li") to a key of SPECIES'''
    s = species.lower()
    if 'li' in s:
        if '6' in s:
            return 'Lithium-6'
        if '7' in s:
            return 'Lithium-7'
        raise ValueError(f'Lithium species must specify isotope 6 or 7: {species}')
    if 'p' in s:
        return 'Proton'
    if 'd' in s:
        return 'Deuteron'
    raise ValueError(f'Incorrect species: {species}')


def te_polarization(mu, spin, field, temps):
    '''Thermal equilibrium vector polarization P = <m>/I from the Boltzmann populations of the
    2I+1 Zeeman sublevels, E_m = -m*mu*B/I. Reduces to tanh(mu*B/kT) for I=1/2 and to
    4t/(3+t^2), t = tanh(mu*B/2kT), for I=1.

    Args:
        mu: magnetic moment in J/T
        spin: nuclear spin I
        field: field in Tesla
        temps: 1-D numpy array of temperatures in K
    '''
    m = np.arange(-spin, spin + 0.5)                               # sublevels -I..I
    x = mu * field / (spin * boltz_const * np.asarray(temps))      # energy step / kT
    weights = np.exp(np.outer(x, m - m.max()))                     # shifted by max to avoid overflow
    return (weights @ m) / weights.sum(axis=1) / spin


class TE():
    '''Class to perform TE measurements, output results. Ignores error in CC due to error in temp, as the contribution to delta CC from delta t is suppressed by 1/pol^2, and pol is small.

    Args:
        species: Nuclear species string, one of SPECIES keys. Flexible matching: p for proton, d for deuteron, li with 6 or 7 for lithium
        field: field value float in Tesla
        areas: 1-D numpy array with areas
        temps: 1-D numpy array with temps
        
    Attributes:
        field: magnetic field used for calculation
        num: number of points in the measurements
        cc: averaged calibration constant from points
        cc_std: standard deviation of calibation constant from points
        te_pol: averaged polarization during TE
        te_pol_std: standard deviation of polarizations
        temp: averaged temperature during TE
        temp_std: standard deviation of temperatures
        area: averaged area during TE
        area_std: standard deviation of areas
    '''    
    def __init__(self, species, field, areas, temps):
    
        areas = np.asarray(areas, dtype=float)
        temps = np.array(temps, dtype=float)   # copy, so the caller's array isn't modified
        temps[temps < 1E-5] = 1E-9     # replace zero values to avoid divide by zero
        self.areas = areas
        self.temps = temps

        self.species = match_species(species)
        mu, spin = SPECIES[self.species]
        te_pols = te_polarization(mu, spin, field, temps)
        ccs = te_pols / areas

        self.field = field
        self.num = len(ccs)
        self.te_pol = np.mean(te_pols)
        self.te_pol_std = np.std(te_pols)
        self.cc = np.mean(ccs)
        self.cc_std = np.std(ccs)
        self.temp = np.mean(temps)
        self.temp_std = np.std(temps)
        self.area = np.mean(areas)  
        self.area_std = np.std(areas) 
        
    def pretty_te(self):
        '''Return formated string short version of TE report'''
        return f"""Material type:  {self.species}                                  Number of Points:  {self.num}
Average Area:  {self.area:.7f} ± {self.area_std:.7f}                 Average Temperature:  {self.temp:.4f} ± {self.temp_std:.4f}
Average Polarization:  {self.te_pol:.5f} ± {self.te_pol_std:.5f}        Average Calibration Constant:  {self.cc:.7f} ± {self.cc_std:.7f}"""

    # >>> UNH-HOOK te-fix: TE report goes to a given folder (settings te_dir), created if needed
    # JLab: def print_te(self):
    def print_te(self, te_dir='te'):
    # <<< UNH-HOOK te-fix
        '''Print long version of TE report to JSON file'''
        now = datetime.datetime.now(tz=pytz.timezone('US/Eastern')).strftime("%Y-%m-%d_%H-%M-%S")
        json_dict = {}
        for key, entry in self.__dict__.items():  
            if isinstance(entry, np.ndarray):       
                json_dict[key] = entry.tolist() 
            else:
                json_dict.update({key:entry})
        # >>> UNH-HOOK te-fix: the hard-coded te/ folder didn't exist, so this raised and the CC was never set
        # JLab: with open(f"te/{self.species}-{now}.json", "w") as outfile:
        # JLab:     json.dump(json_dict, outfile, indent = 4)
        os.makedirs(te_dir, exist_ok=True)
        with open(os.path.join(te_dir, f"{self.species}-{now}.json"), "w") as outfile:
            json.dump(json_dict, outfile, indent = 4)
        # <<< UNH-HOOK te-fix
        return
        
