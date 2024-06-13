@echo off
REM bash, *extremely* frustratingly, does not read startup files if we're entering WSL for the first time
bash ~ -c ". ~/.profile; mosh %*"