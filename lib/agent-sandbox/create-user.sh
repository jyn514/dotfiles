#!/bin/sh

set -eu

uid=$1
gid=$2
name=$3
home=$4

group_entry=$(awk -F: -v gid="$gid" '$3 == gid { print; exit }' /etc/group)
if [ -z "$group_entry" ]; then
    groupadd --gid "$gid" "$name"
    group_name=$name
else
    group_name=${group_entry%%:*}
fi

user_entry=$(awk -F: -v uid="$uid" '$3 == uid { print; exit }' /etc/passwd)
if [ -z "$user_entry" ]; then
    useradd --uid "$uid" --gid "$group_name" --home-dir "$home" \
        --shell /bin/sh --no-create-home "$name"
fi

mkdir -p "$home"
chown "$uid:$gid" "$home"
