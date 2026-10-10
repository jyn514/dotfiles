# Property-based testing: attribution and adaptation

This skill is adapted from Trail of Bits' `property-based-testing` skill at
revision `442fc9d6c89b1e937e6f7a477e7071ea75fcbea4`:
https://github.com/trailofbits/skills/tree/442fc9d6c89b1e937e6f7a477e7071ea75fcbea4/plugins/property-based-testing/skills/property-based-testing

The adapted skill and its references retain the upstream **CC-BY-SA-4.0** license;
see [LICENSE](LICENSE). Changes include portable frontmatter, bounded scope and
existing-framework guidance, contract-specific property selection, corrected
failure/settings advice, and the review checks below. Upstream evaluation tooling
is not bundled; this notice replaces its evaluation README.

Additional review guidance is adapted from Antithesis' Hegel `hegel-review` skill
at revision `a60b28243199b24aeebb2c90aece34082ee4997c`:
https://github.com/hegeldev/hegel-skill/blob/a60b28243199b24aeebb2c90aece34082ee4997c/skills/hegel-review/SKILL.md

Its source is MIT-licensed; the copyright and permission notice are preserved in
[LICENSE.hegel](LICENSE.hegel). Incorporated checks cover missing acceptance or
rejection directions, narrowed domains, fixed configuration/variant coverage,
weakened oracles and tolerances, unrelated properties sharing a failure signal,
and suppressed failing tests.

Other repository-owned skills remain under the repository's Unlicense. The
package's combined license declaration describes its mixed-license contents;
it does not relicense the upstream material as Unlicense.
