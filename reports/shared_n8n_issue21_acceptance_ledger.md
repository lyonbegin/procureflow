# Issue #21 / Draft PR #22 — isolated acceptance evidence ledger

> Scope: `feature/shared-n8n-pan-integration` only. This is an **incomplete** test ledger, not a completion certificate. No production deployment, credential changes, DB writes, or bid submission are authorized.

## Verified by GitHub Actions

| Requirement | Evidence | Status |
|---|---|---|
| Official upstream n8n 2.44.6 pinned | [isolated source build, run 40720510665](https://github.com/lyonbegin/procureflow/actions/runs/40720510665): Docker build and `n8n --version` steps passed | PASS (build) |
| Shared Pan patch on upstream `Canvas.vue` | Same run includes `PAN_PATCH_PATCHED` and source image built | PASS (build) |
| Disposable n8n with SQLite | Same run: `ISOLATED_N8N_READY` | PASS (boot) |
| Google Chrome real user UI test | [first browser run 40720510665](https://github.com/lyonbegin/procureflow/actions/runs/40720510665) blocked by missing ffmpeg; [second run 40721842167](https://github.com/lyonbegin/procureflow/actions/runs/40721842167) blocked by login DTO mismatch. Both test-harness faults have been corrected in feature branch; latest run pending. | **NOT PASSED** |
| 50 UI node-kind contracts and 43 PF operation IDs | [contract CI 40722517537](https://github.com/lyonbegin/procureflow/actions/runs/40722517537), 50 = 14 native + 7 composite + 29 extension; 43 blocks, 15 PF flows, 104 distinct feature IDs | PASS (static contracts only) |
| 43 actual business execution handlers | Registry explicitly sets `executionStatus=BLOCKED_PENDING_VERIFIED_HANDLER`, `canDispatch=false`, `canBid=false` until server-side handler and official evidence checks are implemented and verified | **NOT IMPLEMENTED/VERIFIED** |
| S01–S10 | [native n8n CLI run 40720510659](https://github.com/lyonbegin/procureflow/actions/runs/40720510659), job `Run ALL 10 native workflows in real n8n CLI`; all ten emitted `N8N_NATIVE_EXECUTION_SUCCESS` | PASS (native CLI, **not Chrome**) |
| Separate 80 debugging requirements (81–160) | [baseline report](../reports/workflow_81_160_implementation_20261025.md): 19 implemented, 47 partial, 14 unimplemented; separate `debug-80-audit.mjs` added to CI | **NOT COMPLETE** |
| Production branch preservation | `main` remained at `72cffeb443b8c23a2a9b7a65204f805598c87fdc` at time of audit; changes restricted to feature branch | PASS (source scope) |

## Official Chrome acceptance test details

The feature-branch script `.github/pan-e2e/run.mjs` is configured to drive **real Google Chrome** against the patched upstream n8n instance with a disposable SQLite database. It checks left/middle pan, Shift marquee, viewport and node coordinates, handle drag, node movement, server autosave/reload, zoom controls, palette insertion/deletion, CodeMirror parameter editing, and native execution ID with node output. The script's presence **does not constitute a PASS**; inspect the latest CI verdicts, screenshots and trace before changing the acceptance status.

## Release blockers

1. Obtain **all PASS** verdicts from official Chrome on patched upstream n8n and attach actual screenshots, trace, server logs, viewport before/after, saved workflow and native execution ID.
2. Implement and validate the **29 extension + 7 composite** node runtime mappings, or explicitly disable unavailable kinds in the real editor; 50 UI palette contracts alone are not executable.
3. Implement the 43 block-specific handlers with strict input/output JSON schemas, permissions, provenance, official evidence gates, worker job state, and non-submission safety, then run actual isolated end-to-end tests.
4. Run S01–S10 through official Chrome and compare UI node state with native n8n execution logs; native CLI success alone is insufficient.
5. Close the 47 partial and 14 unimplemented separate debugging requirements (IDs 81–160), verify with real isolated runtime, and retain the original report as an audit baseline.

**Do not mark Issue #21 complete, merge PR #22, or deploy to Railway until every required gate is independently evidenced.**
