#!/bin/sh
if fscrypt status $HOME 2>/dev/null | grep -q "Unlocked: No"; then
  fscrypt unlock $HOME
fi
