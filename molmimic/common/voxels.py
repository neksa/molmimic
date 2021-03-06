import os
from cStringIO import StringIO
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import spatial
from Bio import PDB
from Bio.PDB.NeighborSearch import NeighborSearch

from molmimic.common import Structure
from molmimic.ProteinTables import vdw_radii, vdw_aa_radii, surface_areas

class ProteinVoxelizer(Structure):
    def __init__(self, path, pdb, chain, sdi, domNo, input_format="pdb"
      volume=264, voxel_size=1.0, rotate=True):
        Structure.__init__(self, path, pdb, chain, sdi, domNo,
            input_format=input_format, feature_mode="r")

        self.mean_coord = np.zeros(3)
        self.mean_coord_updated = False

        self.volume = volume
        self.voxel_size = voxel_size
        self.voxel_tree = None
        self.atom_tree = None

        if not rotate:
            self.shift_coords_to_volume_center()
        else:
            next(self.rotate())

    def get_flat_features(self, resi=None):
        features = [s.get_features_for_atom(atom, only_aa=only_aa, only_atom=only_atom, non_geom_features=non_geom_features, use_deepsite_features=use_deepsite_features) \
            for atom in s.structure.get_atoms()]

        return features

    def create_full_volume(self, input_shape=(96, 96, 96)):
        truth_grid = np.zeros(list(input_shape)+[1])
        for atom in self.get_atoms():
            grid = self.get_grid_coord(atom, vsize=input_shape[0])
            truth_grid[grid[0], grid[1], grid[2], 0] = 1
        return truth_grid

    def get_features_per_atom(residue_list):
        """Get features for eah atom, but not organized in grid"""
        features = [self.get_features_for_atom(a) for r in residue_list for a in r]
        return features

    def get_features(self, residue_list=None, only_aa=False, only_atom=False,
      non_geom_features=False, use_deepsite_features=False, expand_atom=False,
      undersample=False, autoencoder=False):
        if self.course_grained:
            return self.map_residues_to_voxel_space(
                binding_site_residues=residue_list,
                include_full_protein=include_full_protein,
                only_aa=only_aa,
                non_geom_features=non_geom_features,
                undersample=undersample
            )
        return self.map_atoms_to_voxel_space(
            expand_atom=expand_atom,
            binding_site_residues=residue_list,
            include_full_protein=include_full_protein,
            only_aa=only_aa,
            only_atom=only_atom,
            use_deepsite_features=use_deepsite_features,
            non_geom_features=non_geom_features,
            undersample=undersample)

    def map_atoms_to_voxel_space(self, expand_atom=False, binding_site_residues=None,
      include_full_protein=False, only_aa=False, only_atom=False, use_deepsite_features=False,
      non_geom_features=False, undersample=False, only_surface=True, autoencoder=False):
        """Map atoms to sparse voxel space.

        Parameters
        ----------
        expand_atom : boolean
            If true, atoms will be converted into spheres with their Van der walls
            radii. The features for the atom are copied into all voxels that contain
            the atom and features from overlapping atoms are summed. If false, an atom
            will only occupy one voxel, where overlapping features for overlapping atoms
            are summed.
        binding_site_residues : list of Bio.PDB.Residue objects or None
            If a binding is known, add the list of Bio.PDB.Residue objects, usually
            obtained by Structure.align_seq_to_struc()
        include_full_protein : boolean
            If true, all atoms from the protein are used. Else, just the atoms from the
            defined binding site. Only makes sense if binding_site_residues is not None
        Returns
        -------
        indices : np.array((nVoxels,3))
        data : np.array((nVoxels,nFeatures))
        """
        if binding_site_residues is not None or autoencoder:
            if not include_full_protein:
                atoms = sorted((a for r in binding_site_residues for a in r), key=lambda a: a.get_serial_number())
                atoms = list(self.filter_atoms(atoms))
                binding_site_atoms = [a.get_serial_number() for a in atoms]
                non_binding_site_atoms = []
            else:
                atoms = list(self.get_atoms(include_hetatms=True))
                nAtoms = len(atoms)
                binding_site_atoms = [a.get_serial_number() for r in binding_site_residues for a in r]

                if undersample:
                    non_binding_site_residues = []
                    for r in self.structure.get_residues():
                        if r in binding_site_residues: continue

                        if only_surface and bool(self.precalc_features[r.get_list()[0].serial_number-1][33]):
                            continue

                        non_binding_site_residues.append(r.get_id()[1])

                    try:
                        non_binding_site_residues = np.random.choice(non_binding_site_residues, len(binding_site_residues))
                        non_binding_site_atoms = []
                        for r in non_binding_site_residues:
                            try:
                                r = self.structure[0][self.chain][r]
                            except KeyError:
                                continue
                            for a in r:
                                non_binding_site_atoms.append(a.get_serial_number())
                    except ValueError as e:
                        print(e)
                        #Might give over balance
                        non_binding_site_atoms = []
                else:
                    non_binding_site_atoms = []

                    # non_binding_site_atoms = [a.get_serial_number() for a in atoms if a.get_serial_number() not in binding_site_atoms]
                    # try:
                    #     non_binding_site_atoms = np.random.choice(non_binding_site_atoms, len(binding_site_atoms))
                    # except ValueError:
                    #     #Might give over balance
                    #     non_binding_site_atoms = []

                atoms = list(atoms)

        else:
            atoms = list(self.get_atoms(include_hetatms=True))
            nAtoms = len(atoms)
            binding_site_atoms = []
            non_binding_site_atoms = []


        nFeatures = Structure.number_of_features(
            only_aa=only_aa,
            only_atom=only_atom,
            non_geom_features=non_geom_features,
            use_deepsite_features=use_deepsite_features,
            course_grained=False)

        data_voxels = defaultdict(lambda: np.zeros(nFeatures))
        truth_voxels = {}

        skipped = 0
        for atom in atoms:
            if autoencoder:
                truth = True
            elif binding_site_residues is not None:
                truth = False
            else:
                truth = atom.get_serial_number() in binding_site_atoms


            if not truth and undersample and atom.get_serial_number() not in non_binding_site_atoms:
                skipped += 1
                continue

            if only_surface:
                features, is_buried = self.get_features_for_atom(atom, only_aa=only_aa, only_atom=only_atom, non_geom_features=non_geom_features, use_deepsite_features=use_deepsite_features, warn_if_buried=True)
                if not truth and is_buried:
                    skipped += 1
                    continue
            else:
                features = self.get_features_for_atom(atom, only_aa=only_aa, only_atom=only_atom, non_geom_features=non_geom_features, use_deepsite_features=use_deepsite_features)

            truth_value = np.array([0.,1.]) if truth else np.array([1.,0.])
            for atom_grid in self.get_grid_coords_for_atom_by_kdtree(atom):
                atom_grid = tuple(atom_grid.tolist())
                try:
                    data_value = np.maximum(features, data_voxels[atom_grid])
                    data_voxels[atom_grid] = data_value
                except ValueError:
                    print(nFeatures, data_voxels[atom_grid].shape, features.shape)
                    raise
                truth_voxels[atom_grid] = truth_value

        try:
            if binding_site_residues is None and not autencoder:
                return np.array(list(data_voxels)), np.array(list(data_voxels.values()))
            else:
                data = np.array(list(data_voxels.values()))
                if autoencoder:
                    truth = data
                else:
                    truth = np.array([truth_voxels[grid] for grid in data_voxels])
                return np.array(list(data_voxels)), data, truth
        except Exception as e:
            print(e)
            raise

    def map_residues_to_voxel_space(self, binding_site_residues=None, include_full_protein=False, non_geom_features=True, only_aa=False, use_deepsite_features=False, undersample=False):
        if binding_site_residues is not None:
            if not include_full_protein:
                residues = binding_site_residues
                binding_site_residues = [r.get_id()[1] for r in residues]
            else:
                residues = self.structure.get_residues()
                binding_site_residues = [r.get_id()[1] for r in binding_site_residues]

                if undersample:
                    non_binding_site_residues = [r.get_id()[1] for r in self.structure.get_residues() if r not in binding_site_residues]
                    try:
                        non_binding_site_residues = np.random.choice(non_binding_site_residues, len(binding_site_residues))
                    except ValueError as e:
                        print(e)
                        #Might give over balance
                        non_binding_site_residues = []
        else:
            residues = self.structure.get_residues()
            binding_site_residues = []

        nFeatures = Structure.number_of_features(
            only_aa=only_aa,
            non_geom_features=non_geom_features,
            course_grained=True,
            use_deepsite_features=use_deepsite_features)

        data_voxels = defaultdict(lambda: np.zeros(nFeatures))
        truth_voxels = {}

        residues = list(residues)

        for residue in residues:
            #assert not residue.get_id()[1] in binding_site_residues
            truth = residue.get_id()[1] in binding_site_residues
            if not truth and undersample and residue.get_id()[1] not in non_binding_site_residues:
                continue

            truth = np.array([int(truth)])

            try:
                features = self.get_features_for_residue(residue, only_aa=only_aa, non_geom_features=non_geom_features, use_deepsite_features=False)
            except Exception as e:
                print(e)
                raise
            for residue_grid in self.get_grid_coords_for_residue_by_kdtree(residue):
                residue_grid = tuple(residue_grid.tolist())
                try:
                    data_voxels[residue_grid] = np.maximum(features, data_voxels[residue_grid])
                except ValueError:
                    print(nFeatures, data_voxels[residue_grid].shape, features.shape)
                    raise
                truth_voxels[residue_grid] = truth

        if binding_site_residues is None:
            return np.array(list(data_voxels)), np.array(list(data_voxels.values()))
        else:
            truth = np.array([truth_voxels[grid] for grid in data_voxels.keys()])
            return np.array(list(data_voxels)), np.array(list(data_voxels.values())), truth

    def voxel_set_insection_and_difference(self, atom1, atom2):
        A = self.atom_spheres[atom1.get_serial_number()]
        B = self.atom_spheres[atom2.get_serial_number()]

        nrows, ncols = A.shape
        dtype={'names':['f{}'.format(i) for i in range(ncols)],
               'formats':ncols * [A.dtype]}

        intersection = np.intersect1d(A.view(dtype), B.view(dtype))
        intersection = intersection.view(A.dtype).reshape(-1, ncols)

        onlyA = np.setdiff1d(A.view(dtype), B.view(dtype))
        onlyA = onlyA.view(A.dtype).reshape(-1, ncols)

        onlyB = np.setdiff1d(B.view(dtype), A.view(dtype))
        onlyB = onlyA.view(A.dtype).reshape(-1, ncols)

        return intersection, onlyA, onlyB

    def get_features_for_atom(self, atom, only_aa=False, only_atom=False,
      non_geom_features=False, use_deepsite_features=False, warn_if_buried=False):
        """Calculate FEATUREs"""
        if isinstance(atom, PDB.Atom.DisorderedAtom):
            #All altlocs have been removed so onlt one remains
            atom = atom.disordered_get_list()[0]

        try:
            features = self.precalc_features[atom.serial_number-1]
            is_buried = bool(features[35]) #Residue asa #[self.precalc_features[a.serial_number-1][31] for a in atom.get_parent()]
            # if asa > 0.0:
            #     asa /= surface_areas.get(atom.element.title(), 1.0)
            #     is_buried = asa <= 0.2
            # else:
            #     is_buried = False

            if use_deepsite_features:
                feats = np.concatenate((
                    features[64:70],
                    features[20:22],
                    features[72:]))
                if warn_if_buried:
                    return feats, is_buried
                else:
                    return feats
            if only_atom:
                feats = features[13:18]
                if warn_if_buried:
                    return feats, is_buried
                else:
                    return feats
            elif only_aa:
                feats = features[40:61]
                if warn_if_buried:
                    return feats, is_buried
                else:
                    return feats
            elif non_geom_features:
                feats = np.concatenate((
                    features[13:18],
                    features[19:23],
                    features[30:33], #1]))
                    np.array([float(is_buried)])))
                if warn_if_buried:
                    return feats, is_buried
                else:
                    return feats
            else:
                if warn_if_buried:
                    return features, is_buried
                else:
                    return features
        except ValueError as e:
            # print e
            # pass
            raise

    def get_features_for_residue(self, residue, only_aa=False, non_geom_features=False,
      use_deepsite_features=False):
        """Calculate FEATUREs"""
        try:
            features = self.precalc_features[residue.get_id()[1]-1]
            if non_geom_features:
                return np.concatenate((
                    features[15:36],
                    features[0:4],
                    features[8:12],
                    ))
            elif only_aa:
                return features[15:36]
            else:
                return features[:self.nFeatures]
        except ValueError:
            pass

    def get_grid_coords_for_atom_by_kdtree(self, atom, k=4):
        dist = self.get_vdw(atom)[0]
        neighbors = self.voxel_tree.query_ball_point(atom.coord, r=dist)
        for idx in neighbors:
            yield self.voxel_tree.data[idx]

    def get_grid_coords_for_residue_by_kdtree(self, residue):
        dist = vdw_aa_radii.get(residue.get_resname(), 3.2)
        center = np.mean([a.get_coord() for a in residue], axis=0)
        neighbors = self.voxel_tree.query_ball_point(center, r=dist)
        return [self.voxel_tree.data[idx] for idx in neighbors]

    def set_voxel_size(self, voxel_size=None):
        if not self.course_grained:
            self.voxel_size = voxel_size or 1.0
        else:
            self.voxel_size = 10.0

        coords = self.get_coords()
        min_coord = np.floor(np.min(coords, axis=0))-5
        max_coord = np.ceil(np.max(coords, axis=0))+5
        extent_x = np.arange(min_coord[0], max_coord[0], self.voxel_size)
        extent_y = np.arange(min_coord[1], max_coord[1], self.voxel_size)
        extent_z = np.arange(min_coord[2], max_coord[2], self.voxel_size)
        mx, my, mz = np.meshgrid(extent_x, extent_y, extent_z)
        self.voxel_tree = spatial.cKDTree(list(zip(mx.ravel(), my.ravel(), mz.ravel())))

    def convert_voxels(self, grid, radius=2.75, level="A"):
        """Convert grid points to atoms
        """
        if self.atom_tree is None:
            self.atom_tree = NeighborSearch(list(self.structure.get_atoms()))

        return self.atom_tree.search(grid, radius, level=level)

def voxels_to_unknown_structure(coords, data, bucket_size=10, work_dir=None, job=None):
    from Bio.PDB.kdtrees import KDTree
    from sklearn.metrics.pairwise import euclidean_distances
    from molmimic.parsers.MODELLER import run_ca2model

    assert bucket_size > 1
    assert self.coords.shape[1] == 3

    if work_dir is None:
        work_dir = os.getcwd()

     _a = "{:6s}{:5d} {:<4s}{:1s}{:3s} {:1s}{:4d}{:1s}   {:8.3f}{:8.3f}{:8.3f}"
    _a += "{:6.2f}{:6.2f}      {:<4s}{:<2s}{:2s}"

    #Initalize KD-Tree
    kdt = KDTree(coords, bucket_size)

    #Find all voxels within 2.75 Angstroms from eachother
    #and save all CA that are nearby
    neighbors = kdt.neighbor_search(1) #2.75
    ca_atoms = []
    residue_types = []
    _charges = []

    all_atoms = []

    for neighbor in neighbors:
        i1 = neighbor.index1
        i2 = neighbor.index2
        voxel_1 = data[i1]
        voxel_2 = data[i2]

        atomtype_1 = voxel_1[:13]
        atomtype_2 = voxel_2[:13]
        restype_1 = voxel_1[40:61]
        restype_2 = voxel_2[40:61]
        charge_1 = voxels_1[19]
        charge_2 = voxels_2[19]

        isbond_1 = sum(atomtype_1)>1
        isbond_2 = sum(atomtype_2)>1

        if atomtype_1[2] == atomtype_2[2]:
            #From same reidue

        if atomtype_1[2] == 1 and atomtype_2[2] == 1:
            #Both CA
            for i, ca_atom in enumerate(ca_atoms):
                restype_i = residue_types[i]
                if i1 in ca_atom:
                    assert restype_2 == restype_i
                    ca_atom.append(i2)
                    break
                elif i2 in ca_atom:
                    assert restype_1 == restype_i
                    ca_atom.append(i1)
                    break
            else:
                #Neither in an existing ca_atom
                ca_atoms.append([i1, i2])
                assert restype_1==restype_2
                residue_types.append(restype_1)
                _charges.append(charge_1)

    #Find all CA centers
    ca_centers = [np.mean(coords) for coords in ca_atoms]
    ca_distances = euclidean_distances(ca_centers)

    #Organize CA by distance and sort by backbine order
    backbone = np.sort(ca_distances)
    backbone_idx = np.argsort(ca_distances)

    #Sort residue types by backbone order
    residue_types = np.array(residue_types)
    residues = residue_types[backbone_idx]

    #Sort charges by backbone order
    _charges = np.array(_charges)
    charges = _charges[backbone_idx]

    #Write out CA model
    ca_model_file = os.path.join(work_dir, "temp.pdb")
    with open(ca_model_file, "w") as ca_pdb:
        for i, (residue_type, charge, (x, y, z)) in enumerate(zip(residues, charges, backbone)):
            atom_line = _a.format("ATOM", i, "CA", "", residue_type, "A", i, "",
                x, y, z, 1.0, 20.0, "", "C", charge)
            print(atom_line, file=ca_pdb)
        print("TER", file=ca_pdb)

    #Build full model using MODELLER
    try:
        full_model_file = run_ca2model(ca_model_file, "A", work_dir=work_dir, job=job)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e2:
        raise

    #Turn coords into density map

    #Fit into density


if __name__ == "__main__":
  import sys
  assert len(sys.argv) > 1
  structure = Structure(sys.argv[1], panfs=False).extract_chain("A")
  num_atoms = sum(1 for a in structure.structure.get_atoms() if a.get_parent().get_id()[0] == " ")
  for atom in structure.get_atoms():
    features = structure.get_features_for_atom(atom)
    print(atom.get_full_id(), atom.serial_number, "of", num_atoms, features, len(features))
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         
