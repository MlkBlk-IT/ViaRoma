#!/usr/bin/env node
// postinstall: verifie que l'environnement peut faire tourner ViaRoma.
// Ne fait JAMAIS echouer l'installation (npm postinstall qui sort en erreur
// casse l'install pour tout le monde): on alerte sur stderr et on continue.
import { findPython, missingDeps, depsHint, eprint, PKG_ROOT } from "../bin/_python.mjs";

const py = findPython();
if (!py) {
  eprint("");
  eprint("[via-roma] Python 3.12+ est requis mais n'a pas ete trouve.");
  eprint("[via-roma] Definissez VIAROMA_PYTHON=/chemin/vers/python puis relancez.");
  eprint("");
  process.exit(0);
}

const missing = missingDeps(py);
if (missing.length) {
  eprint("");
  eprint("[via-roma] Dependances Python manquantes: " + missing.join(", "));
  eprint(depsHint(py));
  eprint("");
  process.exit(0);
}

eprint("[via-roma] pret (Python " + py.version + ") - config/ et data/ dans " + PKG_ROOT);
process.exit(0);
