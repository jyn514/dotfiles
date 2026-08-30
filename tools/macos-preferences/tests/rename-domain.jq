.domains |= (
  to_entries
  | if length != 1 then error("fixture must contain exactly one domain") else . end
  | map(.key = $domain)
  | from_entries
)
