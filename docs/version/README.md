# Antigravity Versioning & Maintenance Documentation

This directory contains version specifications, baseline contracts, and upgrade checklists for **Ag Attention Bridge** to ensure compatibility across Antigravity IDE releases.

---

## Documents in this Directory

| Document | Purpose |
|---|---|
| [**`ANTIGRAVITY_1.1.3_SPEC.md`**](./ANTIGRAVITY_1.1.3_SPEC.md) | Baseline technical specification for Antigravity IDE `1.1.3` (Extension `0.2.0`, commit `ecfbad74d93962fc8ca485d93ab9b4f3d4cb6cf8`). Details exact process flags, ports, RPC services, payload schemas, and step types. |
| [**`UPGRADE_GUIDE.md`**](./UPGRADE_GUIDE.md) | Step-by-step runbook and troubleshooting checklist for when Antigravity is updated. Identifies what to inspect, commands to run, and which files in Ag Attention Bridge to modify if breaking changes occur. |

---

## Compatibility Matrix

| Ag Attention Bridge Version | Antigravity IDE Version | Extension Version | Integration Mechanism | Status |
|---|---|---|---|---|
| **0.2.0+** | **1.1.3** (commit `ecfbad74`) | **0.2.0** | Native ConnectRPC (`HandleCascadeUserInteraction`) | **Verified & Working (100%)** |
| 0.1.0 | 1.1.3 | 0.2.0 | Legacy Synthetic `userMessage` injection | Deprecated (available via fallback flag) |

---

## Key Principles for Version Upgrades

1. **Zero Internal Modification**: Never patch or modify Antigravity binaries, JavaScript bundles, or SQLite history.
2. **Reverse Engineer via Read-Only Inspection**: Use `/proc`, `strings`, `lsof`, and JavaScript bundle inspection to verify protocol consistency.
3. **Loopback & Security Constraints**: Maintain loopback (`127.0.0.1`), process UID checking, and dynamic CSRF token handling regardless of Antigravity version.
4. **Test Before Deployment**: Always run the automated suite (`pytest`) and live interaction probe (`ask_question`) after an Antigravity upgrade before committing changes.
