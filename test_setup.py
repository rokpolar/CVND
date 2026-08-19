import sys

print("Python version:", sys.version)
print("-" * 40)

packages = [
    ("pandas", "pd"),
    ("numpy", "np"),
    ("geopandas", "gpd"),
    ("scipy", "scipy"),
    ("statsmodels.api", "sm"),
    ("sklearn.preprocessing", "sklearn"),
    ("matplotlib.pyplot", "plt"),
    ("seaborn", "sns"),
    ("requests", "requests"),
    ("tqdm", "tqdm"),
]

all_ok = True
for package, alias in packages:
    try:
        mod = __import__(package, fromlist=[alias])
        version = getattr(mod, "__version__", "ok")
        print(f"  OK  {package} — {version}")
    except ImportError as e:
        print(f"  FAIL  {package} — {e}")
        all_ok = False

print("-" * 40)
if all_ok:
    print("ALL IMPORTS OK — ready for CP-02")
else:
    print("SOME IMPORTS FAILED")