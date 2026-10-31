#!/usr/bin/env node
// postinstall: verifies that the environment can run ViaRoma.
// NEVER causes the installation to fail (npm postinstall which exits with an error
// breaks the install for everyone): we alert on stderr and we continue.
import { findPython, missingDeps, depsHint, eprint, PKG_ROOT } from "../bin/_python.mjs";

const py = findPython();
if (!py) {
  eprint("");
  eprint("[via-roma] Python 3.12+ is required but not found.");
  eprint("[via-roma] Definissez VIAROMA_PYTHON=/chemin/vers/python puis relancez.");
  eprint("");
  process.exit(0);
}

const missing = missingDeps(py);
if (missing.length) {
  eprint("");
  eprint("[via-roma] Missing Python dependencies: " + missing.join(", "));
  eprint(depsHint(py));
  eprint("");
  process.exit(0);
}

eprint("[via-roma] pret (Python " + py.version + ") - config/ and data/ in " + PKG_ROOT);
process.exit(0);
