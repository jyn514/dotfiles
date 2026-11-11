package skillrules

// #Effect uses caller-supplied identity keys for the actor, operation and target.
// It describes a proposed effect, not the effects actually caused by a command.
#Effect: {
	actor:  #Text
	action: #Text
	target: #Text
}

// #AuthorizedEffects requires an exact actor/action/target grant for each effect.
// Available tools, roles, readiness and a parent's grant confer no extra grant.
// No wildcard, ancestry, implicit read/write relation or revocation is inferred.
// The caller supplies currently applicable grants and their governing sources.
#AuthorizedEffects: {
	grants: [...{
		effect: #Effect
		source: #SourceRef
	}]
	proposed: [...#Effect]
	_authorization: #Subset & {
		superset: [for grant in grants {grant.effect}]
		subset: proposed
	}
}

// #IndependentVerification requires at least one verifier, disjoint from the
// declared constructors. Apply only when independence is actually required.
// It does not require new construction, one worker per role, unique verifier
// entries, or that different identity keys imply intellectual independence.
#IndependentVerification: {
	constructors: [...#Text]
	verifiers: [#Text, ...#Text]
	_independence: #Disjoint & {
		left:  constructors
		right: verifiers
	}
}

// #Prerequisite limits only the dependent action. A satisfied or unnecessary
// prerequisite does not compel proceeding or establish authorization.
// Unresolved remains unresolved; it is not rewritten as a failed prerequisite.
#Prerequisite: {
	required:        bool
	state:           "satisfied" | "unsatisfied" | "unresolved"
	dependentAction: "proceed" | "defer"
	if required && state != "satisfied" {
		dependentAction: "defer"
	}
}
