"""Pure argument contract shared by request preparation and execution."""
import argparse

def parse_arguments(argv=None):
    p = argparse.ArgumentParser(description="GFN2-xTB opt/SP", allow_abbrev=False)
    p.add_argument('--xyz', required=True)
    p.add_argument('--task', choices=['opt', 'sp', 'opt-sp'], required=True)
    p.add_argument('--executable', required=True, help='configured xTB executable, resolved after activation')
    p.add_argument('--output-dir', required=True)
    p.add_argument('--charge', type=int, default=0)
    p.add_argument('--multiplicity', type=int, default=1, help='spin multiplicity 2S+1')
    p.add_argument('--opt-level', default='tight', choices=['normal','tight','verytight'])
    a = p.parse_args(argv)
    if a.multiplicity < 1: p.error("multiplicity must be positive")
    return a
