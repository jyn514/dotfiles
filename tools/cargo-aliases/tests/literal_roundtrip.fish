# The producer supplies exactly one quoted expression. Fish is the decoder.
# Only the expression is generated; keep the consumer in its own language file.
eval "set --local decoded $argv[1]"
or exit 1
printf '%s\0' "$decoded"
