"""modules/drafting — W1 module wrapper (not a shipped package).

This ``__init__.py`` exists ONLY to make ``modules/drafting/tests`` a proper
pytest package (``drafting.tests.*``) so mandated test-file names can be
repeated across module suites (``test_no_bpy.py`` exists in the document,
interchange and commands suites) without pytest same-basename module
collisions — same pattern W2 landed for modules/document and
modules/interchange. The shipped package is ``bcdraft``
(modules/drafting/bcdraft); nothing may import ``drafting`` itself. Never
imported by the extension build (scripts/build_extension.py copies bcdraft
only).
"""
