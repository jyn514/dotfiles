#!/usr/bin/env node

import { wrapTextWithAnsiLines } from "@earendil-works/pi-tui";

export class SessionManager {
  static open() {}
}

export function convertToLlm(messages) {
  return messages;
}

export const dependencySource = [...wrapTextWithAnsiLines("workspace")];
