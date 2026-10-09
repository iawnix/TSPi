"""Pure candidate generation CLI contract; no scientific imports."""
import argparse
from pathlib import Path


def parse_arguments(argv=None):
    p=argparse.ArgumentParser(description="Prepare candidate or IRC inputs", allow_abbrev=False)
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('candidates','irc'):
        command=sub.add_parser(name,allow_abbrev=False);command.add_argument('--spec',required=True,type=Path);command.add_argument('--output-dir',required=True,type=Path)
        if name=='candidates':
            command.add_argument('--conformers',type=int,default=1);command.add_argument('--enumerate-stereo',action='store_true')
        else:
            command.add_argument('--checkpoint',type=Path,required=True);command.add_argument('--max-points',type=int,default=80)
    return p.parse_args(argv)
