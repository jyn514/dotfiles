#!/usr/bin/env python3
import ast


print("".join(chr(c) for c in ast.literal_eval(input())))
