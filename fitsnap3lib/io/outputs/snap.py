from fitsnap3lib.io.outputs.outputs import Output, optional_open
from fitsnap3lib.parallel_tools import ParallelTools
from datetime import datetime
from fitsnap3lib.io.input import Config
import numpy as np


#config = Config()
#pt = ParallelTools()


class Snap(Output):

    def __init__(self, name):
        super().__init__(name)
        self.config = Config()
        self.pt = ParallelTools()

    def output(self, coeffs, errors):
        new_coeffs = None
        # new_coeffs = pt.combine_coeffs(coeffs)
        if new_coeffs is not None:
            coeffs = new_coeffs
        self.write(coeffs, errors)

    #@pt.rank_zero
    def write(self, coeffs, errors):
        @self.pt.rank_zero
        def decorated_write():
            if self.config.sections["EXTRAS"].only_test != 1:
                if self.config.sections["CALCULATOR"].calculator != "LAMMPSSNAP":
                    raise TypeError("SNAP output style must be paired with LAMMPSSNAP calculator")
            with optional_open(self.config.sections["OUTFILE"].potential_name and
                               self.config.sections["OUTFILE"].potential_name + '.snapcoeff', 'wt') as file:
                file.write(_to_coeff_string(coeffs))
            with optional_open(self.config.sections["OUTFILE"].potential_name and
                               self.config.sections["OUTFILE"].potential_name + '.snapparam', 'wt') as file:
                file.write(_to_param_string())
            with optional_open(self.config.sections["OUTFILE"].potential_name and
                               self.config.sections["OUTFILE"].potential_name + '.mod', 'wt') as file:
                file.write(_to_potential_file())
            with optional_open("in.lammps", 'wt') as file:
                file.write(_to_lammps_input())

            self.write_errors(errors)
        decorated_write()

    #@pt.sub_rank_zero
    def read_fit(self):
        @self.pt.sub_rank_zero
        def decorated_read_fit():
            # TODO fix this fix reader for bzeroflag = 0
            if self.config.sections["CALCULATOR"].calculator != "LAMMPSSNAP":
                raise TypeError("SNAP output style must be paired with LAMMPSSNAP calculator")
            with optional_open(self.config.sections["OUTFILE"].potential_name and
                               self.config.sections["OUTFILE"].potential_name + '.snapcoeff', 'r') as file:

                info = file.readline()
                toss = file.readline()
                num_types, ncoeff = [int(i) for i in file.readline().split()]
                try:
                    assert ncoeff == (self.config.sections["BISPECTRUM"].ncoeff+1)
                except AssertionError:
                    raise ValueError("number of coefficients: {} does not match "
                                     "input file ncoeff: {}".format(ncoeff, self.config.sections["BISPECTRUM"].ncoeff+1))
                try:
                    assert num_types == self.config.sections["BISPECTRUM"].numtypes
                except AssertionError:
                    raise ValueError("number of types: {} does not match "
                                     "input file numTypes: {}".format(num_types, self.config.sections["BISPECTRUM"].numtypes))
                fit = np.zeros((num_types, ncoeff-1))
                for i in range(num_types):
                    atom_header = file.readline()
                    zero = file.readline()
                    for j in range(ncoeff-1):
                        fit[i][j] = float(file.readline().split()[0])
            return fit
        fit = decorated_read_fit()
        return fit.flatten()


def _to_param_string():
    config = Config()
    if config.sections["BISPECTRUM"].chemflag != 0:
        chemflag_int = 1
    else:
        chemflag_int = 0
    return f"""
    # required
    rcutfac {config.sections["BISPECTRUM"].rcutfac}
    twojmax {max(config.sections["BISPECTRUM"].twojmax)}

    #  optional
    rfac0 {config.sections["BISPECTRUM"].rfac0}
    rmin0 {config.sections["BISPECTRUM"].rmin0}
    bzeroflag {config.sections["BISPECTRUM"].bzeroflag}
    quadraticflag {config.sections["BISPECTRUM"].quadraticflag}
    wselfallflag {config.sections["BISPECTRUM"].wselfallflag}
    chemflag {chemflag_int}
    bnormflag {config.sections["BISPECTRUM"].bnormflag}
    """


def _to_coeff_string(coeffs):
    """
    Convert a set of coefficients along with bispec options into a .snapparam file
    """
    config = Config()

    numtypes = config.sections["BISPECTRUM"].numtypes
    ncoeff = config.sections["BISPECTRUM"].ncoeff
    coeffs = coeffs.reshape((numtypes, -1))
    blank2Js = config.sections["BISPECTRUM"].blank2J.reshape((numtypes, -1))
    if config.sections["BISPECTRUM"].bzeroflag:
        blank2Js = np.insert(blank2Js, 0, [1.0], axis=1)
    coeffs = np.multiply(coeffs, blank2Js)
    type_names = config.sections["BISPECTRUM"].types
    out = f"# fitsnap fit generated on {datetime.now()}\n\n"
    out += "{} {}\n".format(len(type_names), ncoeff+1)

    for elname, rjval, wjval, column, ielem in zip(type_names,
                                            config.sections["BISPECTRUM"].radelem,
                                            config.sections["BISPECTRUM"].wj,
                                                    coeffs, range(numtypes)):
        bstart = ielem * ncoeff
        bstop = bstart + ncoeff
        bnames = [[0]] + config.sections["BISPECTRUM"].blist[bstart:bstop]

        out += "{} {} {}\n".format(elname, rjval, wjval)
        out += "\n".join(f" {bval:<30.18} #  B{bname} " for bval, bname in zip(column, bnames))
        out += "\n"
    out += "\n# End of potential"
    return out

def _to_potential_file():
    """
    Use config settings to write a LAMMPS potential file.
    """
    config = Config()

    ps = config.sections["REFERENCE"].lmp_pairdecl[0]
    snap_filename = config.sections["OUTFILE"].potential_name.split("/")[-1]
    pc_snap = f"pair_coeff * * {snap_filename}.snapcoeff {snap_filename}.snapparam"
    for t in config.sections["BISPECTRUM"].types:
        pc_snap += f" {t}"

    if "hybrid" in ps:
        # extract non zero parts of pair style
        if "zero" in ps.split():
            split = ps.split()
            zero_indx = split.index("zero")
            del split[zero_indx]
            del split[zero_indx] # delete the zero pair cutoff
            ps = ' '.join(split)
        out = ps + " snap\n"
        # add pair coeff commands from input, ignore if pair zero
        for pc in config.sections["REFERENCE"].lmp_pairdecl[1:]:
            out += f"{pc}\n" if "zero" not in pc else ""
        # add pair coeff command from snap potential
        out += pc_snap
    else:
        out = "pair_style snap\n"
        out += pc_snap

    return out

def _to_lammps_input():
    """
    Use config settings to write a LAMMPS input script.
    """

    config = Config()

    snap_filename = config.sections["OUTFILE"].potential_name.split("/")[-1]
    pot_filename = snap_filename + ".mod"

    out = "# LAMMPS template input written by FitSNAP.\n"
    out += "# Runs a NVE simulation at specified temperature and timestep.\n"
    out += "\n"
    out += "# Declare simulation variables\n"
    out += "\n"
    out += "variable timestep equal 0.5e-3\n"
    out += "variable temperature equal 600\n"
    out += "\n"
    out += f"units {config.sections['REFERENCE'].units}\n"
    out += "\n"
    out += "# Supply your own data file below\n"
    out += "\n"
    out += "read_data DATA\n"
    out += "\n"
    out += "# Include potential file\n"
    out += "\n"
    out += f"include {pot_filename}\n"
    out += "\n"
    out += "# Declare simulation settings\n"
    out += "\n"
    out += "timestep ${timestep}\n"
    out += "neighbor 1.0 bin\n"
    out += "velocity all create ${temperature} 10101 rot yes mom yes\n"
    out += "fix 1 all nve\n"
    out += "\n"
    out += "# Run dynamics\n"
    out += "\n"
    out += "run 1000\n"

    return out