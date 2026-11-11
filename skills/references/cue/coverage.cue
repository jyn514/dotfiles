package skillrules

// #Coverage accounts for every declared inventory item, without inventing
// obligations from the observed results. Keys outside the inventory are errors.
// Every item has one disposition; covered requires an evidence reference.
// Excluded, unresolved and unexamined rows remain valid accounting, not success.
// The caller determines inventory completeness, exclusion authority and whether
// the evidence actually supports the claimed property or acceptance boundary.
#Coverage: {
	inventory: [...#Text]
	dispositions: [#Text]: {
		status: "covered" | "excluded" | "unresolved" | "unexamined"
		reason: #Text
		evidence: [...#SourceRef]
		if status == "covered" {
			evidence: [#SourceRef, ...#SourceRef]
		}
	}
	for identity in inventory {
		dispositions: "\(identity)": {}
	}
	_inventoryKeys: #Subset & {
		superset: inventory
		subset: [for identity, _ in dispositions {identity}]
	}
}
