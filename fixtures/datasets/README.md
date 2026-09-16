# Layer 1 synthetic and adversarial fixtures

These fixtures are declarative source material for dataset-contract, boundary, and
cross-language tests. Decimal text is not a canonical representation; tests must parse
it through an explicit manifest. Floating-point edge cases are stored as IEEE bit
patterns so NaN payloads and signed zero survive every language boundary.

