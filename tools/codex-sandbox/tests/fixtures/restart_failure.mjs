#!/usr/bin/env node
// Fail Pi startup with a stable diagnostic for tmux error-retention tests.
console.error("restart fixture: intentional Pi startup failure");
process.exit(23);
