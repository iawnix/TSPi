"""Strict XYZ geometry and trajectory readers shared by scientific runners.

Coordinates are angstrom. Extended atom properties and changing atom order are
not accepted; callers must explicitly select one frame from a trajectory.
"""
import math
from pathlib import Path
import re

PERIODIC_TABLE = [''] + '''H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca
Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd
Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu
Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk
Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'''.split()
_ATOMIC_NUMBERS = {symbol: index for index, symbol in enumerate(PERIODIC_TABLE) if symbol}
_FLOAT = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'


def _number(text):
    value = float(text.replace('D', 'E').replace('d', 'e'))
    if not math.isfinite(value):
        raise ValueError('non-finite XYZ value')
    return value


def read_xyz_frames(path):
    path = Path(path)
    lines = path.read_text(encoding='utf-8').splitlines()
    frames, identity, index = [], None, 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        try:
            count = int(lines[index].strip())
        except ValueError as exc:
            raise ValueError(f'invalid XYZ atom count at line {index + 1}') from exc
        if count < 1 or index + count + 2 > len(lines):
            raise ValueError('incomplete XYZ frame')
        atoms = []
        for line in lines[index + 2:index + count + 2]:
            parts = line.split()
            if len(parts) != 4 or parts[0] not in _ATOMIC_NUMBERS:
                raise ValueError('expected an element symbol and three XYZ coordinates')
            atoms.append((parts[0], *(_number(value) for value in parts[1:])))
        symbols = [atom[0] for atom in atoms]
        if identity is not None and symbols != identity:
            raise ValueError('XYZ trajectory atom count or element order changed')
        identity = symbols
        frames.append((lines[index + 1].strip(), atoms))
        index += count + 2
    if not frames:
        raise ValueError('XYZ file contains no frames')
    return frames


def select_frame(frames, selector='only'):
    selector = str(selector).strip().lower()
    if selector == 'only':
        if len(frames) != 1:
            raise ValueError('expected exactly one XYZ frame; select first, last or an index explicitly')
        index = 0
    elif selector in {'first', 'last'}:
        index = 0 if selector == 'first' else len(frames) - 1
    else:
        try:
            index = int(selector)
        except ValueError as exc:
            raise ValueError('frame selector must be only, first, last or an integer') from exc
        if index < 0:
            index += len(frames)
        if not 0 <= index < len(frames):
            raise ValueError('XYZ frame index is out of range')
    title, atoms = frames[index]
    return index, title, atoms


def read_xyz(path, frame='only'):
    return select_frame(read_xyz_frames(path), frame)[2]


def xyz_frame_metadata(path):
    frames = read_xyz_frames(path)
    result = []
    for index, (title, _) in enumerate(frames):
        match = re.search(rf'(?:^|\s)energy:\s*({_FLOAT})(?=\s|$)', title, re.I)
        energy = _number(match.group(1)) if match else _number(title) if re.fullmatch(_FLOAT, title) else None
        result.append({'index': index, 'title': title, 'energy_hartree': energy})
    return {'atom_count': len(frames[0][1]), 'frame_count': len(frames), 'frames': result}


def validate_electronic_state(atoms, charge, multiplicity):
    if type(charge) is not int or type(multiplicity) is not int or multiplicity < 1:
        raise ValueError('charge must be an integer and multiplicity a positive integer')
    electrons = sum(_ATOMIC_NUMBERS[atom[0]] for atom in atoms) - charge
    spin_twice = multiplicity - 1
    if electrons < spin_twice or (electrons - spin_twice) % 2:
        raise ValueError('multiplicity is incompatible with electron count')
