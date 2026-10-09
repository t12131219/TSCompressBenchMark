"""Location constants for the byte-preserved legacy generator.

Only the generator uses this module. Runtime validation uses the formal
canonical source registry; the old local bypass loader is not imported.
"""

from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / "Dataset_Verify"
