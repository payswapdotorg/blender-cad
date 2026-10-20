#ifndef PLANEGCS_STUB_FCGLOBAL_H
#define PLANEGCS_STUB_FCGLOBAL_H
// ============================================================================
// EVALUATION-ONLY COMPAT SHIM — NOT PRODUCT CODE, NEVER SHIPPED.
// Minimal stand-in for FreeCAD's src/FCGlobal.h. The real file (282-line pin
// checkout verified) is consumed in its GUI branch (Qt, FCGlobal.h:89
// "#include <QtCore.h>" behind the Qt build path); planegcs needs ONLY
// FREECAD_DECL_EXPORT / FREECAD_DECL_IMPORT (used by SketcherGlobal.h to
// define SketcherExport). A static Linux build has no DLL boundary — both
// expand to nothing.
// ============================================================================
#define FREECAD_DECL_EXPORT
#define FREECAD_DECL_IMPORT
#endif
