#!/usr/bin/env python

"""
tailed_parameters.py

For distributions of RMSD or TFDs of force field geometries with respect to
reference geometries, identify outlier molecules in the high RMSD (TFD) tails
above a predetermined cutoff value. For each force field parameter in the
molecule set, determine the fraction of outlier molecules with that parameter.
Compare that to the fraction of all molecules that use that parameter.

By:      Victoria T. Lim
Version: Jan 28 2020

References:
https://github.com/openforcefield/openforcefield/blob/master/examples/inspect_assigned_parameters/inspect_assigned_parameters.ipynb

Note:
- Make sure to use the same FFXML file that was used to generate the minimized geometries.

Examples:
$ python tailed_parameters.py -i refdata_parsley.sdf -f openff_unconstrained-1.0.0-RC2.offxml --rmsd --cutoff 1.0  --tag "RMSD to qcarchive.sdf" --tag_smiles "SMILES QCArchive" > tailed.dat
$ python tailed_parameters.py -i refdata_parsley.sdf -f openff_unconstrained-1.0.0-RC2.offxml --tfd  --cutoff 0.12 --tag "TFD to qcarchive.sdf"  --tag_smiles "SMILES QCArchive" >> tailed.dat

"""

import os
import re
import numpy as np
import pickle
import matplotlib.pyplot as plt
from collections import OrderedDict

import openeye.oechem as oechem

from openforcefield.topology import Molecule
from openforcefield.typing.engines.smirnoff import ForceField
from openforcefield.utils.structure import get_molecule_parameterIDs

import reader


### ------------------- Functions -------------------


def natural_keys(text):
    """
    Natural sorting of strings containing numbers.
    https://stackoverflow.com/a/5967539/8397754
    """
    def atoi(text):
        return int(text) if text.isdigit() else text
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]


def write_mols(mols_dict, outfile):
    """
    Save all mols in the given dictionary to 'outfile'.

    Parameters
    ----------
    mols_dict : dict
        TODO
    outfile : string
        name of output file
    """

    # open an outstream file
    ofs = oechem.oemolostream()
    if not ofs.open(outfile):
        oechem.OEThrow.Fatal("Unable to open %s for writing" % outfile)

    # go through all the molecules
    for key in mols_dict:
        print(f"writing out {key}")
        mymol = mols_dict[key]['structure']
        oechem.OEWriteConstMolecule(ofs, mymol)


def get_parameters(mols_dict, ffxml):
    """
    Parameters
    ----------
    mols_dict : dict
        TODO
    ffxml : string
        name of FFXML force field file
    """

    # load in force field
    ff = ForceField(ffxml)

    # convert OEMols to open force field molecules
    off_mols = []

    for i, key in enumerate(mols_dict):
        # get mol from the dict
        mymol = mols_dict[key]['structure']

        # create openforcefield molecule from OEMol
        # note: stereo error raised even though coordinates present (todo?)
        off_mol = Molecule.from_openeye(mymol, allow_undefined_stereo=True)
        off_mols.append(off_mol)

    # form a dictionary to backtrace the iso_smiles to original molecule
    iso_smiles = [ molecule.to_smiles() for molecule in off_mols ]
    smi_list = mols_dict.keys()
    smi_dict = dict(zip(iso_smiles, smi_list))

    # remove duplicate molecules (else get_molecule_parameterIDs gives err)
    idx_of_duplicates = [idx for idx, item in enumerate(iso_smiles) if item in iso_smiles[:idx]]
    for index in sorted(idx_of_duplicates, reverse=True):
        del off_mols[index]

    # create dictionaries describing parameter assignment,
    # grouped both by molecule and by parameter
    parameters_by_molecule, parameters_by_ID = get_molecule_parameterIDs(off_mols, ff)

    return parameters_by_molecule, parameters_by_ID, smi_dict


def count_mols_by_param(full_params, params_id_all, params_id_out):
    """
    """

    nmols_cnt_all = []
    nmols_cnt_out = []

    for i, p in enumerate(full_params):

        # count number of mols in the COMPLETE set which use this parameter
        cnt_all = len(params_id_all[p])

        # count number of mols in the OUTLIER set which use this parameter
        try:
            cnt_out = len(params_id_out[p])
        except KeyError:
            cnt_out = 0

        nmols_cnt_all.append(cnt_all)
        nmols_cnt_out.append(cnt_out)

    return np.array(nmols_cnt_all), np.array(nmols_cnt_out)


def plot_by_paramtype(prefix, max_ratio, labels, plot_data, metric_type):
    """
    prefix : string
        specify parameter type to generate plot.
        options: 'a' 'b' 'i' 'n' 't'
    """

    # create the plot and set label sizes
    fig, ax = plt.subplots()
    fig.set_size_inches(5, len(plot_data)/2)
    fs1 = 20
    fs2 = 16

    # set x locations and bar widths
    y = np.arange(len(plot_data))
    width = 0.3

    # plot the bars
    ax.barh(y, plot_data, width, color='darkcyan')

    # add plot labels, ticks, and tick labels
    ax.set_xlabel('fraction', fontsize=fs1)
    #ax.set_ylabel('force field parameter', fontsize=fs1)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=fs2)
    plt.xticks(fontsize=fs2)

    # invert for horizontal bars
    plt.gca().invert_yaxis()

    # set plot limits
    ax.set_xlim(0, max_ratio)

    # set alternating colors for background for ease of visualizing
    locs, labels = plt.xticks()
    for i in range(1, len(locs)-1, 2):
        ax.axvspan(locs[i], locs[i+1], facecolor='lightgrey', alpha=0.25)

    # save figure
    plt.grid()
    fig.tight_layout()
    plt.savefig(f'bars_{metric_type.lower()}_params_{prefix}.png', bbox_inches='tight')


def tailed_parameters(in_sdf, ffxml, cutoff, tag, tag_smiles, metric_type):

    # load molecules from open reference and query files
    print(f"Opening SDF file {in_sdf}...")
    mols = reader.read_mols(in_sdf)
    print(f"Looking for outlier molecules with {metric_type} above {cutoff}...\n")

    # find the molecules with the metric above the cutoff
    all_smiles    = []
    mols_all      = OrderedDict()
    mols_out      = OrderedDict()
    count_all     = 0
    count_out     = 0

    for mol in mols:
        for conf in mol.GetConfs():

            value  = float(oechem.OEGetSDData(conf, tag))
            smiles = oechem.OEGetSDData(conf, tag_smiles)

            if value >= cutoff:
                mols_out[smiles] = {'metric': value, 'structure': oechem.OEGraphMol(conf)}
                count_out += 1

            mols_all[smiles] = {'structure': oechem.OEGraphMol(conf)}
            all_smiles.append(smiles)
            count_all += 1

    # save outliers molecules to file
    write_mols(mols_out, f'outliers_{metric_type.lower()}.mol2')

    # analyze parameters in the outlier and full sets
    params_mol_out, params_id_out, smi_dict_out = get_parameters(mols_out, ffxml)
    params_mol_all, params_id_all, smi_dict_all = get_parameters(mols_all, ffxml)

    # organize all computed data to encompassing dictionary
    # all values in data_* are dictionaries except for data_*['count']
    data_all = {'count': count_all, 'mols_dict': mols_all,
        'params_mol': params_mol_all, 'params_id': params_id_all,
        'smi_dict': smi_dict_all}
    data_out = {'count': count_out, 'mols_dict': mols_out,
        'params_mol': params_mol_out, 'params_id': params_id_out,
        'smi_dict': smi_dict_out}

    # save the params organized by id to pickle
    with open(f'tailed_{metric_type.lower()}.pickle', 'wb') as f:
        pickle.dump((data_all, data_out), f)

    return data_all, data_out


def main(in_sdf, ffxml, cutoff, tag, tag_smiles, metric_type, inpickle=None):
    """
    """

    if inpickle is not None and os.path.exists(inpickle):

        # load in analysis from pickle file
        with open(inpickle, 'rb') as f:
            data_all, data_out = pickle.load(f)

    else:
        data_all, data_out = tailed_parameters(
            in_sdf, ffxml, cutoff, tag, tag_smiles, metric_type)

    # count number of unique mols
    params_mol_all = data_all['params_mol']
    params_mol_out = data_out['params_mol']
    uniq_n_all = len(params_mol_all)
    uniq_n_out = len(params_mol_out)

    # count number of unique params
    params_id_all = data_all['params_id']
    params_id_out = data_out['params_id']

    full_params = list(set(params_id_all.keys()))
    full_params.sort(key=natural_keys)

    uniq_p_all = len(full_params)
    uniq_p_out = len(list(set(params_id_out.keys())))

    # print stats on number of outliers
    print(f"\nNumber of structures in full set: {data_all['count']} ({uniq_n_all} unique)")
    print(f"Number of structures in outlier set: {data_out['count']} ({uniq_n_out} unique)")
    print(f"Number of unique parameters in full set: {uniq_p_all}")
    print(f"Number of unique parameters in outlier set: {uniq_p_out}")

    # go through all parameters and find number of molecules which use each one
    nmols_cnt_all, nmols_cnt_out = count_mols_by_param(full_params, params_id_all, params_id_out)
    write_data = np.column_stack((full_params, nmols_cnt_out, nmols_cnt_all))
    with open(f'params_{metric_type.lower()}.dat', 'w') as f:
        f.write("# param\tnmols_out\tnmols_all\n")
        f.write(f"NA_total\t{uniq_n_out}\t{uniq_n_all}\n")
        np.savetxt(f, write_data, fmt='%-8s', delimiter='\t')

    # compare fractions in the all set vs the outliers set
    fraction_cnt_all = nmols_cnt_all/uniq_n_all
    fraction_cnt_out = nmols_cnt_out/uniq_n_out

    # exclude parameters for which outliers set AND full set
    # both have less than 5 matches; do this BEFORE excluding nonzero_inds
    # TODO: make this more general? e.g., nmols_cnt_all < nsamples
    ones_nmols_all = np.where(nmols_cnt_all == 1)[0]
    ones_nmols_out = np.where(nmols_cnt_out == 1)[0]
    ones_both = np.intersect1d(ones_nmols_all, ones_nmols_out)
    fraction_cnt_all = np.delete(fraction_cnt_all, ones_both)
    fraction_cnt_out = np.delete(fraction_cnt_out, ones_both)
    full_params = [v for index, v in enumerate(full_params) if index not in ones_both] # exclude ones

    # exclude parameters which are not used in outliers set
    nonzero_inds = np.nonzero(fraction_cnt_out)
    fraction_cnt_out = fraction_cnt_out[nonzero_inds]
    fraction_cnt_all = fraction_cnt_all[nonzero_inds]
    full_params = [full_params[i] for i in nonzero_inds[0]] # keep nonzeroes

    # get ratio of fraction_outliers to fraction_all
    fraction_ratio = fraction_cnt_out / fraction_cnt_all
    max_ratio = np.max(fraction_ratio)

    # plot fraction of molecules which use each parameter
    # separate plot by parameter type
    for t in ['a', 'b', 'i', 'n', 't']:

        # get the subset of data based on parameter type
        plot_inds = [full_params.index(i) for i in full_params if i.startswith(t)]
        fraction_subset = fraction_ratio[plot_inds]
        label_subset = [full_params[index] for index in plot_inds]

        plot_by_paramtype(t, max_ratio, label_subset, fraction_subset, metric_type)


### ------------------- Parser -------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-i", "--infile", required=True,
            help="Input molecule file")

    parser.add_argument("-f", "--ffxml", required=True,
            help="Open force field ffxml file")

    parser.add_argument("--cutoff", required=True, type=float,
            help="Cutoff value for which to separate outliers")

    parser.add_argument("--tag", required=True,
            help="SDF tag from which to obtain RMSDs or TFDs")

    parser.add_argument("--tag_smiles", required=True,
            help="SDF tag from which to identify conformers")

    parser.add_argument("--rmsd", action="store_true", default=False,
        help="Tag and cutoff value refer to RMSD metrics.")

    parser.add_argument("--tfd", action="store_true", default=False,
        help="Tag and cutoff value refer to TFD metrics.")

    parser.add_argument("--inpickle", default=None,
        help="Name of pickle file with already-computed data")

    # TODO: plot what_for

    args = parser.parse_args()
    if args.rmsd:
        metric_type = 'RMSD'
    elif args.tfd:
        metric_type = 'TFD'
    else:
        pass
        # TODO

    main(args.infile, args.ffxml,
        args.cutoff, args.tag, args.tag_smiles, metric_type,
        args.inpickle)

