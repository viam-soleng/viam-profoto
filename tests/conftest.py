import pathlib
import sys

# Put src/ on sys.path so `import profoto...` resolves in tests.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
