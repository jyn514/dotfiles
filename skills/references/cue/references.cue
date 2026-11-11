package skillrules

#Text: string & !=""

// #SourceRef identifies supplied material without resolving or authenticating it.
// Paths and URLs are nonempty strings, not parsed or checked for existence.
// Inline material remains representable when no stable source ID is available.
#SourceRef: {
	kind:      "file"
	path:      #Text
	revision?: #Text
	selector?: #Text
} | {
	kind:    "message"
	session: #Text
	entry:   #Text
} | {
	kind:    "ticket"
	tracker: #Text
	id:      #Text
} | {
	kind: "url"
	url:  #Text
} | {
	kind:         "inline"
	text:         #Text
	attribution?: #Text
}

// #Judgment keeps an unresolved question distinct from a resolved false value.
// It requires an explanation, not a new investigation or an external source.
// A resolved value can be any concrete data; callers can refine its type.
#Judgment: {
	question: #Text
	sources: [...#SourceRef]
} & ({
	status:    "resolved"
	value:     _
	rationale: #Text
} | {
	status:  "unresolved"
	missing: #Text
})
