if length != 2 then
  error("expected generated policy and exported preferences")
else
  (.[0].domains | to_entries) as $domains
  | if $domains | length != 1 then
      error("generated policy must contain exactly one domain")
    else
      $domains[0].value.preferences == .[1]
    end
end
