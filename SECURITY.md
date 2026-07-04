# Security Policy

This project performs READ-ONLY analysis of public on-chain vault state. It
does not custody keys, sign transactions, or submit anything to a blockchain.
The risk surface is limited to:

1. **Incorrect risk metric outputs** that mislead a curator into a wrong
   parameter change. This is the primary concern.
2. **Pydantic / parsing errors** that crash the CLI on malformed API
   responses.
3. **Outdated dependency CVEs** in the runtime dependencies.

## Reporting a vulnerability

If you find a math bug that materially changes a detector's headline metric,
a Pydantic / parsing failure on a real-world Morpho API response, or any
issue where this framework would lead a curator to a wrong action,
please open a private security advisory via
[GitHub Security Advisories](https://github.com/mkzung/morpho-vault-counterfactuals/security/advisories)
rather than a public issue. I respond within ~7 days.

For non-security bugs, please open a regular GitHub issue.

## Supported versions

The latest `main` branch is the only supported version. Tagged releases are
snapshots for reference; no patch backports.

## Out of scope

- Anything in `data/fixtures/*.json` - these are illustrative synthetic
  values, not authoritative on-chain data.
- The Chart.js CDN load in HTML reports. Pin the version locally if your
  environment requires it.
