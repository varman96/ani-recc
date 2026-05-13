import sys
import os

# Ensure that modules within this package can import each other directly
# This supports the existing 'import knn' in ani_recc.py
sys.path.append(os.path.dirname(__file__))
