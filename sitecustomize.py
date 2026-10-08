import sys
import os

# Auto-add user site-packages to sys.path
_site_pkg = os.path.expanduser(r"~\AppData\Local\Programs\Python\Python314\Lib\site-packages")
if os.path.exists(_site_pkg) and _site_pkg not in sys.path:
    sys.path.insert(0, _site_pkg)

