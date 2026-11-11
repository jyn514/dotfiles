package examples

import policy "dotfiles.example/skillrules@v0"

// One connected record: packets use the task's declared grants and identities.
// A source reference is not an authenticated authorization or proof of truth.
#ReviewPlan: {
	task: {
		grants:                          policy.#AuthorizedEffects.grants
		independentVerificationRequired: bool
	}
	packet: {
		owner: policy.#Text
		effects: [...(policy.#Effect & {actor: owner})]
	}
	staffing: {
		constructors: [...policy.#Text]
		verifiers: [...policy.#Text]
	}
	_authority: policy.#AuthorizedEffects & {
		grants:   task.grants
		proposed: packet.effects
	}
	if task.independentVerificationRequired {
		_independence: policy.#IndependentVerification & {
			constructors: staffing.constructors
			verifiers:    staffing.verifiers
		}
	}
}

review: #ReviewPlan & {
	task: {
		grants: [{
			effect: {actor: "qa-a", action: "read", target: "candidate"}
			source: {kind: "inline", text: "qa-a may inspect the candidate and report findings"}
		}]
		independentVerificationRequired: true
	}
	packet: {
		owner: "qa-a"
		effects: [{actor: "qa-a", action: "read", target: "candidate"}]
	}
	staffing: {
		constructors: ["builder-a", "builder-b"]
		verifiers: ["qa-a", "qa-b"]
	}
}

// Complete accounting can still include unfinished work. This is not a claim
// that integration succeeded, nor that these are all of the task's obligations.
coverage: policy.#Coverage & {
	inventory: ["component", "integration"]
	dispositions: {
		component: {
			status: "covered"
			reason: "The recorded component check exercised this obligation."
			evidence: [{kind: "file", path: "component-check.json"}]
		}
		integration: {
			status: "unresolved"
			reason: "The required runtime input is not available."
			evidence: []
		}
	}
}

coupling: policy.#Judgment & {
	question: "Do these changes require coordinated integration?"
	sources: []
	status:  "unresolved"
	missing: "The producer/consumer contract has not been inspected."
}

publication: policy.#Prerequisite & {
	required:        true
	state:           "unresolved"
	dependentAction: "defer"
}
