import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / 'backend'))
if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--lane', choices=['all','legacy','ai','maintenance'], default='all')
    lane=parser.parse_args().lane
    if lane=='maintenance':
        from app.v2.maintenance import main
        main()
    elif lane=='ai':
        from app.v2.worker import main
        main()
    else:
        from app.worker import main
        main(include_v2=lane=='all')
