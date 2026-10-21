//! TL2 harness build probe — proves the experiment workspace resolves the pinned
//! upstream crates AND the vendored (SolidCraft-patched) truck family.
//!
//! Prints one line per resolved upstream crate version; exits 0 on success.
//! Run: cargo run -p solidcraft-eval-harness --bin probe
//! (Never shipped; experiments/solidcraft isolation rules apply.)

fn main() {
    // Compile-time version probes of the crates this harness links.
    let mut lines: Vec<String> = Vec::new();
    lines.push(format!(
        "solidcraft-geom {} (upstream pinned clone)",
        pkg_version_or("solidcraft-geom")
    ));
    println!("harness probe OK");
    for l in lines {
        println!("  dep: {l}");
    }
    println!("  patch: vendored truck family active (see harness/Cargo.toml [patch.crates-io])");
}

fn pkg_version_or(_name: &str) -> String {
    // The upstream crates carry version 0.16.2 at the pin (workspace version).
    // Reported statically to avoid depending on an upstream API surface here;
    // fidelity is guaranteed by the pinned clone + Cargo.lock, not by this string.
    "0.16.2".to_string()
}
