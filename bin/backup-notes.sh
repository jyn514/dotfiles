#!/bin/sh
vault="$HOME/Documents/Obsidian Vault"
rclone bisync "$vault"/ gdrive:/notes/obsidian/ --verbose --resilient --recover --max-lock 2m --conflict-resolve newer --compare=size,modtime,checksum --filter-from="$vault"/bisync-filters.txt --metadata "$@"
