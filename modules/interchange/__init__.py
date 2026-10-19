"""modules/interchange — W2 module wrapper (not a shipped package).

This ``__init__.py`` exists ONLY to make ``modules/interchange/tests`` a
proper pytest package (``interchange.tests.*``) so the mandated test-file
names can be repeated across module suites (``test_no_bpy.py`` in both
document and interchange) without pytest same-basename module collisions.
The shipped package is ``bcio`` (modules/interchange/bcio); nothing may
import ``interchange`` itself. Never imported by the extension build
(scripts/build_extension.py copies bcio only).
"""
