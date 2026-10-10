"""Check a parsed Gaussian frequency result; this is not IRC connectivity proof."""
import json
import math
import sys
from pathlib import Path


def validate(paths):
    if len(paths) != 1:
        raise ValueError('Gaussian frequency validator requires exactly one parsed.json artifact')
    result = json.loads(Path(paths[0]).read_text())
    summary = result.get('summary', {})
    frequencies = result.get('frequencies', [])
    if not summary.get('normal_termination') or summary.get('error_termination') or not frequencies:
        return {'schema_version': 'validator-output/1', 'verdict': 'inconclusive',
                'reason': 'A normally terminated frequency calculation is required'}
    if not all(type(x) in (int, float) and math.isfinite(x) for x in frequencies):
        return {'schema_version': 'validator-output/1', 'verdict': 'inconclusive',
                'reason': 'Every frequency must be a finite numeric value'}
    negative = [x for x in frequencies if x < 0]
    return {'schema_version': 'validator-output/1', 'verdict': 'pass' if len(negative) == 1 else 'fail',
            'imaginary_frequency_count': len(negative),
            'scope': 'exactly one negative mode in the supplied parsed frequency table; excludes IRC and mode character'}


if __name__ == '__main__':
    Path('validator_result.json').write_text(json.dumps(validate(sys.argv[1:]), sort_keys=True) + '\n')
