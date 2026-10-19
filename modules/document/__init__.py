"""modules/document — W2 module wrapper (not a shipped package).

This ``__init__.py`` exists ONLY to make ``modules/document/tests`` a proper
pytest package (``document.tests.*``) so the mandated test-file names can be
repeated across module suites (``test_no_bpy.py`` in both document and
interchange) without pytest same-basename module collisions. The shipped
package is ``bcdoc`` (modules/document/bcdoc); nothing may import
``document`` itself. Never imported by the extension build
(scripts/build_extension.py copies bcdoc only).
"""
