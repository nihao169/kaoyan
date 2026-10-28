import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / 'backend'))
from app.worker import main

if __name__ == '__main__':
    main()
