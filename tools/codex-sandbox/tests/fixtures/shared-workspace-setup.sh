#!/bin/sh
# Generate all repository metadata with the same JJ that the image probe consumes.
set -eu
root=$1
layout=$2
jj=${JJ_FIXTURE_REAL:-/trusted/bin/jj}
config=${JJ_FIXTURE_CONFIG:-/trusted/jj.toml}

for name in project sibling; do
	"$jj" --config-file "$config" git init --colocate "$root/home/src/$name"
done
project=$root/home/src/project
"$jj" --config-file "$config" --repository "$project" workspace add "$project/preexisting-child"
# This workspace moves with the project bind, not its fixture's absolute path.
printf '%s' '../../.jj/repo' >"$project/preexisting-child/.jj/repo"
"$jj" --config-file "$config" git init --colocate "$project/independent-nested"
if [ "$layout" = linked ]; then
	main=$root/home/src/linked-source
	"$jj" --config-file "$config" git init --colocate "$main"
	"$jj" --config-file "$config" --repository "$main" workspace add --colocate "$root/external-dotfiles"
	# Bind aliases retain different canonical spellings for the same backing store.
	# Native JJ treats every byte as part of the path, including a trailing newline.
	printf '%s' "$main/.jj/repo" >"$root/external-dotfiles/.jj/repo"
else
	"$jj" --config-file "$config" git init --colocate "$root/external-dotfiles"
fi
