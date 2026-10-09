"""Registered gaussian_saddle validator; shared implementation is pinned by the descriptor."""
import sys
from path_validation import main

if __name__ == '__main__':
    main('saddle', sys.argv[1:])
