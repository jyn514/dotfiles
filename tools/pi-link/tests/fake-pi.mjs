#!/usr/bin/env node
// Launcher fixture: report the handoff without loading Pi or touching sessions.
console.log(JSON.stringify({ args: process.argv.slice(2), linkName: process.env.PI_LINK_NAME }));
