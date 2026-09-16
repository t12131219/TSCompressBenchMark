# Source onboarding cards

Before a real source adapter is authored, add one `*.json` admission card validated by
`tscompbench.codecs.validate_onboarding_card`. A card freezes the source/commit and
translation-unit evidence; records API, input/output, output-bound, error, reset and
finalize semantics; inventories stream components and dependencies; preserves upstream
test logs and hashed release/debug/sanitizer builds; and makes license restrictions and
unsupported reason codes explicit.

The shared source checkout remains read-only. Any required patch belongs under the
algorithm adapter directory and changes SourceArtifactID/BuildID evidence. An upstream
test pass or a discovered benchmark file is evidence only, never qualification.
