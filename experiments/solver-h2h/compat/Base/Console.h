#ifndef PLANEGCS_STUB_BASE_CONSOLE_H
#define PLANEGCS_STUB_BASE_CONSOLE_H
// ============================================================================
// EVALUATION-ONLY COMPAT SHIM — NOT PRODUCT CODE, NEVER SHIPPED.
// Minimal stand-in for FreeCAD's Base/Console.h for the planegcs standalone
// build in this lane. planegcs/GCS.cpp (FreeCAD 1.1.4 pin) uses exactly:
//   Base::Console().log(...), Base::Console().warning(...)  (printf-style,
//   GCS.cpp:5578,4868), Base::TimeElapsed + TimeElapsed::diffTimeF
//   (GCS.cpp:4885,4948-4950). All output goes to a null sink — the harness
//   records its own machine-readable results; no console side effects.
// ============================================================================
#include <chrono>
#include <cstdarg>
#include <string>
namespace Base {
class ConsoleSingleton {
public:
    void log(const char* /*fmt*/, ...) {}
    void warning(const char* /*fmt*/, ...) {}
    void error(const char* /*fmt*/, ...) {}
    void message(const char* /*fmt*/, ...) {}
};
inline ConsoleSingleton& Console() { static ConsoleSingleton c; return c; }
class TimeElapsed {
public:
    TimeElapsed() : t0(std::chrono::steady_clock::now()) {}
    std::chrono::steady_clock::time_point t0;
    static double diffTimeF(const TimeElapsed& a, const TimeElapsed& b) {
        return std::chrono::duration<double>(b.t0 - a.t0).count();
    }
};
} // namespace Base
#endif
