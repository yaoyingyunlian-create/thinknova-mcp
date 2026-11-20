"""Retired publisher. Use the customer AI assistant and Ego Lite."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from delivery_boundary import retired_publication

def main():
    return retired_publication()

if __name__ == '__main__':
    sys.exit(main())
