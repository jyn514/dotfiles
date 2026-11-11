package skillrules

import "list"

// #Subset requires every concrete value in subset to occur in superset.
// Lists have set membership semantics here: order and repeated entries do not
// affect membership. This does not require uniqueness or expand scope patterns.
#Subset: {
	superset: [...]
	subset: [...]
	_membership: {
		for index, value in subset {
			"\(index)": true & list.Contains(superset, value)
		}
	}
}

// #Disjoint forbids any shared concrete value. Empty lists are disjoint.
// Callers choose the identity keys; equal labels need not mean equal identities.
#Disjoint: {
	left: [...]
	right: [...]
	_separation: {
		for index, value in left {
			"\(index)": false & list.Contains(right, value)
		}
	}
}
