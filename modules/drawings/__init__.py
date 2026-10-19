"""modules/drawings — module wrapper (not a shipped package).

This ``__init__.py`` exists ONLY to make ``modules/drawings/tests`` a
proper pytest package (``drawings.tests.*``) so mandated test-file names
can be repeated across module suites (``test_no_bpy.py`` already exists
in the document, interchange, commands and drafting suites) without pytest
same-basename module collisions — same pattern as modules/document,
modules/interchange, modules/commands and modules/drafting. The shipped
package is ``bcdraw`` (modules/drawings/bcdraw); nothing may import
``drawings`` itself. Never imported by the extension build.
"""
