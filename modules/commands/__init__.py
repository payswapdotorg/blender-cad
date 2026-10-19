"""modules/commands — W1 module wrapper (not a shipped package).

This ``__init__.py`` exists ONLY to make ``modules/commands/tests`` a proper
pytest package (``commands.tests.*``) so the mandated test-file names can be
repeated across module suites (``test_no_bpy.py`` already exists in the
document and interchange suites) without pytest same-basename module
collisions — same pattern W2 landed for modules/document and
modules/interchange. The shipped package is ``bccmd``
(modules/commands/bccmd); nothing may import ``commands`` itself. Never
imported by the extension build (scripts/build_extension.py copies bccmd
only).
"""
