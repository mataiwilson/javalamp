# Javalamp Build Log

## 2026-11-15 - Kiosk optimization: preflight and baseline preparation

- Scope: checkout-only optimization on MATAI-LINUX-SERVER. No installation,
  console restart, autologin/vlock changes, unrelated workload changes, commit
  or push is authorized.
- Clean starting checkout: `feature/server-kiosk`, `edd0797` (CPU percentage
  footer change). Origin is `mataiwilson/javalamp`; upstream is
  `breschio/javalamp`, both GitHub HTTPS. Required infra-map pull was current.
- Live process: PID 8509, expected java/12 FPS/no-caffeinate/no-splash/sysinfo/
  mono command, approximately 100% CPU in the read-only process snapshot.
- Checkout and pipx runner, canvas and scenes/plasma initially match exactly.
  Both environments use Python 3.12.3 and Rich 15.0.0.
- Installed `sysinfo.py` SHA256:
  `96b7c951ddf06b0b089ea1277c86d4c5928bab992fc713100f34f109e6f8a9ae`.
  Checkout SHA256:
  `358a7a5374c8580e8a89125abce7bc56ce0b38f7a8afe9b6468d1e972d0056dc`.
  The complete installed-minus-checkout difference is the extra import below.
  Both files remain untouched; reconcile this recorded difference explicitly
  before any separately approved installation.

```diff
--- checkout/src/javalamp/sysinfo.py
+++ pipx/site-packages/javalamp/sysinfo.py
@@
 import socket
+import struct
 import time
```

- Hypothesis: per-cell trigonometry/style construction and Rich assembly cost
  dominate; independent Live refresh may duplicate serialization or contend
  for the GIL. Discriminate with separate update, Canvas-to-Text and full Rich
  refresh timings plus a captured-output real Runner measurement.
- Added finite [benchmark](scripts/benchmark_kiosk.py): 240 x 66 animation cells
  plus the footer, 12 FPS, mono, standard ANSI colors, counting output sink.
  Fixed system-stats fixture isolates rendering without sensor/network probes;
  it does not measure actual collector or Linux-console device write costs.
- Resource-limit no-op probe passed using a transient user-systemd unit:
  CPUQuota=50%, MemoryMax=256M, MemorySwapMax=0, TasksMax=16, Nice=15,
  RuntimeMaxSec=10s, TimeoutStopSec=1s, KillMode=control-group. All tests and
  measurements must retain aggregate limits and an external deadline.

Next: run this unchanged-source baseline, then optimize and add exact-output
and loop-control regressions, repeat identical measurements, record outcomes.

## 2026-11-15 - Baseline, plasma and canvas checks

- Baseline command: transient user unit with the limits above, RuntimeMaxSec=40s,
  inner `timeout --kill-after=1s 38s`, checkout `PYTHONPATH`, then
  `.venv/bin/python scripts/benchmark_kiosk.py --frames 12 --seconds 3`.
- Original means: update 71.050 ms CPU / 141.975 ms wall; Canvas-to-Text
  7.133 / 15.419 ms; Rich Live refresh 13.153 / 29.804 ms. Capped runner:
  1.558 CPU seconds / 3.209 wall seconds, 13 updates (4.051/s), 48.56% of
  one logical CPU. CPU quota throttles wall time; do not treat that percentage
  as uncapped production CPU or claim actual terminal rendering throughput.
- Cached exact horizontal/vertical/diagonal phase calculations, spatial radii
  and immutable styles. No sine approximation, changed summation order,
  resolution or animation-time changes. Nine reference-formula tests passed
  in 1.42s including full kiosk frames, themes, resize and allocation guards.
- Plasma-only same-command comparison: update 24.239 ms CPU; text assembly
  8.569 ms; Rich refresh 15.512 ms; runner 1.417 CPU / 3.009 wall seconds,
  36 updates (11.966/s). Shared-host noise is visible between stages.
- Added Canvas identity fast path with equality fallback, avoiding repeated
  Rich Style hash comparisons. Exact run-span regression and the existing
  test module passed: 27 tests in 2.33s, under the same aggregate caps and
  a 25s external unit deadline. Intermediate units were verified absent.
- Next edit: disable Live's background thread and explicitly refresh once per
  runner/picker tick. Picker's adjacent one-line change is required because
  it previously relied on that thread; wipe transitions already refresh.

## 2026-11-15 - Explicit-refresh checks and combined measurement

- Runner now uses `auto_refresh=False` and one `refresh=True` update per tick;
  rendering is included in the existing FPS sleep budget. Picker updates now
  explicitly refresh too. Transition refresh behavior is unchanged.
- Initial standalone runner tests failed because their import did not register
  the java scene. Fixed the test-only import rather than application behavior;
  the same five tests then passed in 0.20s. Finite clock-read budgets protect
  these mocked loops in addition to the external process-tree limits.
- Combined original-fixture benchmark: update 24.532 ms CPU, Canvas-to-Text
  2.924 ms, Rich refresh 13.940 ms. Runner: 1.371 CPU / 3.006 wall seconds,
  36 updates (11.975/s), 45.62% logical CPU under the 50% ceiling.
- Complete suite passed: 41 tests in 3.52s, capped at 256 MiB/half a CPU/16
  tasks/40s including its scene-loader subprocess. No editor diagnostics in
  touched Python files. Live PID 8509 still has its November 10 start time;
  all temporary measurement/test units were absent after completion.
- Final measurement fixture now uses the real, unchanged system-stats
  formatter with a fixed complete SystemStats snapshot (no metric probes),
  and records the loaded source path. Add an exact full-footer regression,
  then repeat both installed-original and checkout measurements with this
  identical revised harness. Earlier fixture measurements remain above.

## 2026-11-15 - Final paired results and handoff

Both runs used the final [benchmark](scripts/benchmark_kiosk.py), 24 samples
per stage, a three-second Runner duration, 240 columns x 67 total rows
(66 animation rows plus the footer), mono, 12 FPS, standard ANSI colors and
the real footer formatter with identical fixed complete stats. Output was
counted and discarded, never sent to the physical terminal. The benchmark
prints its loaded package path to distinguish the source under test.

| CPU Time Per Operation | Installed Original | Optimized Checkout |
| --- | ---: | ---: |
| Plasma update, mean | 71.636 ms | 24.009 ms |
| Plasma update, median | 67.738 ms | 23.360 ms |
| Canvas-to-Text, mean | 6.586 ms | 3.950 ms |
| Rich Live refresh, mean | 11.534 ms | 12.862 ms |
| Sum of stage means | 89.757 ms | 40.821 ms |

- Plasma CPU time fell about 66%; summed stage cost fell about 55%. Rich
  refresh itself was not optimized; its small increase is visible rather
  than hidden. Short samples on a shared production CPU have scheduling,
  frequency and scene-content variation.
- Original capped Runner: 1.561637 CPU seconds / 3.161868 wall seconds,
  13 updates (4.111/s), 49.39% logical CPU. Optimized: 1.381790 CPU seconds /
  3.052874 wall seconds, 36 updates (11.792/s including startup/teardown),
  45.26% logical CPU. The earlier combined run achieved 11.975 updates/s.
  These percentages are constrained by the 50% ceiling, not an uncapped
  before/after live-console CPU measurement. The target and dt remain 12 FPS.
- Final stage wall means (quota-throttled): original update/text/refresh
  142.468 / 12.830 / 21.884 ms; optimized 49.085 / 8.031 / 23.920 ms.
- Commands used the same user-systemd caps as the baseline, 40s unit deadline,
  38s inner timeout plus one-second forced kill, and `--frames 24 --seconds 3`.
  Original used `PYTHONPATH` pointing to pipx's Python 3.12 site-packages;
  optimized used this checkout's `src`. Neither run installed anything.
  Effective cgroup files were independently asserted before the final run:
  `cpu.max=50000 100000`, `memory.max=268435456`, `memory.swap.max=0`,
  `pids.max=16`. KillMode remained control-group, Nice=15.
- Final complete suite: **42 passed in 3.28s**. Exact full custom-footer test
  and runner slice: six passed in 0.21s. Focused Ruff check passed for new
  Python files and plasma; two initially missing strict-zip arguments were
  fixed and the whole suite rerun. Diff whitespace and editor checks passed.
- Unchanged installed SHA256 values were reverified:
  runner `69b6192bef14f9b0b2c7e0ce509848d15a08d237872402af001e0a8091c149e2`;
  canvas `2d084cc70a220ad342906d89920ac2d8ee05f205ad801ee6e69dafe483d60137`;
  plasma `768668bec68184372f8ec7790a7bffe9e14a66ff3e69730eb1604d430e61ebfd`.
  Both sysinfo hashes still match the preflight record, preserving its exact
  installed-only import. No dependency or package metadata was changed.

Limitations and approval boundary: physical-console device writes and real
stats-collection costs were intentionally not benchmarked. Physical appearance
and real-key verification on the installed console remain pending a separately
approved deployment/restart. Tests verify original per-cell output, pacing,
dimensions, resize, hotkeys, picker refresh and full footer text in isolation.
No install/reinstall, live-console restart/signal, autologin/vlock edit,
unrelated-workload change, commit or push was performed. Changes remain
uncommitted on `feature/server-kiosk`. Deployment requires separate approval
and explicit preservation/reconciliation of the sysinfo difference above.

## 2026-11-15 - Second pass: baseline and plasma hot-loop overhead

- Owner requested another efficiency pass retaining roughly the same 12 FPS
  experience. Original checkout-only scope and all deployment/commit/push
  approval boundaries remain in force. Prior edits were intact; no abandoned
  benchmark units existed; live PID 8509 retained its November 10 start time.
- Fresh first-pass baseline using the unchanged final harness, 24 samples,
  three-second Runner, and the same 50% CPU/256 MiB/zero swap/16-task caps:
  update 24.079 ms CPU, Canvas-to-Text 2.876 ms, Rich refresh 11.600 ms.
  Runner: 1.481463 CPU / 3.010669 wall seconds, 35 updates (11.625/s),
  49.21% logical CPU under the quota. Unit deadline 40s, inner timeout 38s
  plus 1s forced kill, Nice=15, KillMode=control-group.
- Four-frame CPU-clock cProfile sample, separately capped at 20s: 253,440
  min/max calls, 63,360 bounds-checked Canvas.set calls, 67,232 sin calls.
  Profile overhead makes these timings unsuitable for before/after comparison;
  the call counts identify repeated work left after the first pass.
- Second-pass hypothesis: the average of four finite sine values stays in
  [-1, 1], so intensity is in [0, 1] and the two index clamps are redundant.
  Prebuild the small glyph/color cell palette and fill known in-bounds rows
  directly, eliminating clamp calls, Canvas.set calls and new cell tuples.
  Geometry, arithmetic order, sine evaluation, dt and rendering are unchanged.
- Added endpoint tests, alternate ramp lengths and cell-reuse checks alongside
  the existing exact original-formula/theme/full-size/resize regressions.
  Next: validate the focused change and repeat the same bounded benchmark.

## 2026-11-15 - Second-pass results and verification

Same unchanged harness and parameters on both sides: 24 samples per stage,
three-second Runner, 240 x 66 scene plus one footer row, mono, 12 FPS, real
footer formatter with fixed stats, counting output sink, identical limits.

| Mean CPU Time Per Frame | First-Pass Checkout | Second-Pass Checkout |
| --- | ---: | ---: |
| Plasma update | 24.079 ms | 8.794 ms |
| Canvas-to-Text | 2.876 ms | 2.903 ms |
| Rich Live refresh | 11.600 ms | 10.943 ms |
| Sum of stage means | 38.555 ms | 22.639 ms |

- Update CPU cost fell another 63.5%; summed stage cost fell 41.3% compared
  with the fresh first-pass baseline. Relative to the earlier installed-original
  89.757 ms stage sum, the cumulative reduction is approximately 74.8%.
  Update median fell from 24.735 ms to 7.690 ms. No rendering code changed in
  this pass; small rendering-stage differences reflect sample variation.
- Runner: first pass 1.481463 CPU / 3.010669 wall seconds, 35 updates and
  49.21% logical CPU; second pass 0.867474 CPU / 3.034774 wall seconds,
  37 updates and 28.58% logical CPU. The short window includes an immediate
  first tick and teardown, so 12.192 measured updates/s is not a changed FPS
  setting. The target and animation dt remain 12 FPS and 1/12 second.
- Optimized wall-stage means under quota: update 19.240 ms, text 4.980 ms,
  refresh 23.466 ms. CPU-time comparisons avoid interpreting quota stalls as
  computation. The benchmark excludes physical-terminal device-write and
  live metric-collection costs; no claim of deployed CPU reduction is made.
- Fourteen plasma tests passed in 1.49s. The complete suite then passed:
  **47 tests in 2.89s**, including all prior runner/picker/keyboard/pacing/
  footer regressions. Added endpoint, variable-ramp and allocation tests
  passed; existing original-formula comparisons retain exact characters and
  styles. No approximation, sine lookup quantization, dependency, FPS or
  resolution change was introduced.
- Focused Ruff and editor diagnostics passed; `git diff --check` passed.
  Installed runner/canvas/plasma and both sysinfo hashes remain exactly as
  recorded above, including the installed-only `import struct` difference.
- Second-pass edits are limited to plasma, its regression tests and this
  chronological log; first-pass changes remain intact. No installation,
  restart, console signal, autologin/vlock edit, unrelated workload change,
  commit or push. Any deployment still requires separate approval.

## 2026-11-15 - Third pass: rendering and actual console color mode

- Owner requested an attempt below 10% logical CPU at roughly 12 FPS, then
  noted the console is monochrome. Read-only confirmation: PID 8509 runs
  `java --fps 12 --no-caffeinate --no-splash --sysinfo --theme mono`, stdout
  `/dev/tty1`, `TERM=linux`; no NO_COLOR/COLORTERM/FORCE_COLOR variables.
  Mono is a grayscale palette, not disabled ANSI styling. Rich selects
  standard terminal colors here, matching the benchmark's existing mode.
- A three-refresh bounded cProfile identified Rich Text span/layout overhead.
  Added a plasma-only native Rich Segments renderable; shared Canvas, other
  scenes, Runner and footer remain on their existing APIs. Segment snapshots
  remain independent of later scene updates and resizes.
- First usable segment test run: 21 passed, six cross-color-mode failures.
  Rich Style._add retains ANSI codes across consoles; isolated its cache in
  tests. Recheck: all 27 plasma tests passed in 1.47s, including byte-for-byte
  captured output versus Text across color modes, sizes and clipping.
- The normal terminal tool repeatedly returned only "opened the alternate
  buffer". Temporary VS Code tasks were required for reliable diagnostics;
  tests remain in the same bounded user-systemd units. Existing workspace-root
  tasks.json was absent; this generated task file must be removed at handoff.
  Status check confirmed no abandoned javalamp units or pytest processes.
- Segment-only benchmark, unchanged 24-sample/three-second fixture: update
  6.254 ms CPU, scene render 2.048 ms (old harness canvas_to_text label),
  Rich refresh 4.033 ms. Runner 0.632719 CPU / 3.025968 wall seconds,
  37 updates, 20.91% logical CPU. The under-10% goal is not yet reached.
- An interrupted exact-threshold lookup patch did not land; source/tests/log
  were rechecked before proceeding. No unvalidated lookup change is present.
- Next hypothesis: standard-color terminals map several grayscale source
  styles to identical visible colors. Canonicalize only that output mode and
  coalesce adjacent equivalent segments through Rich. Tests now compare
  decoded styled runs: fewer redundant escape sequences are allowed, but
  characters, colors, attributes, dimensions and footer placement must match.

## 2026-11-15 - Third-pass comparisons and rejected color optimization

- Applied the exact palette-transition lookup after confirming the interrupted
  attempt was absent. Uses native bisect and float-neighbor-corrected transition
  values, not approximate sine or intensity tables. Thirty-one plasma tests
  passed in 1.28s including every threshold's immediate neighbors, dense
  intensity samples, variable ramps, original formula and captured rendering.
- Harness now labels scene.render timing `scene_render` (formerly misleading
  `canvas_to_text`) and allows a finite 12-second Runner window. All production
  dimensions, 12 FPS, real fixed-fixture footer and standard ANSI mode remain.
- Initial 12-second candidate: update 5.735 ms CPU, scene render 3.958 ms,
  refresh 6.434 ms; 145 updates over 12.029s at 18.32% logical CPU. Not under 10%.
- Same-process bounded A/B, 12s per variant, 24 samples per stage, 40s external
  deadline and unchanged aggregate caps:

| Variant | Update CPU | Scene Render CPU | Refresh CPU | Runner CPU |
| --- | ---: | ---: | ---: | ---: |
| Extra standard-color coalescing | 5.422 ms | 3.548 ms | 6.923 ms | 19.53% |
| Native Rich Segments only | 4.894 ms | 2.877 ms | 4.396 ms | 16.48% |

- Both variants produced 5,010,266 captured characters and 145 updates. Native
  path: 1.982480 CPU seconds / 12.033240 wall seconds (12.050 updates/s,
  including the immediate first tick). Extra color coalescing was rejected
  and removed: more work with no output-size benefit in this measured path.
- Restored byte-for-byte escaped ANSI comparisons and strengthened them to
  include an actual 240 x 66 scene plus footer, not just a smaller scene in
  a 240-column console. Final full-suite and preservation checks follow.
- Current conclusion: meaningful further improvement, but under 10% has NOT
  been demonstrated. No colors, frame rate or resolution were removed to make
  the number look better. Real terminal writes and metric probes remain
  excluded. Any proposal for native/vectorized dependencies or a deliberately
  reduced-styling mode requires a separate discussion, not an implicit change.

## 2026-11-15 - Third-pass final verification

- Final suite: **64 passed in 3.20s** under the existing 40s/256 MiB/zero-swap/
  half-CPU/16-task envelope. Focused Ruff, editor diagnostics and diff whitespace
  checks passed. Full kiosk-size ANSI output matches the original Text path;
  keyboard, resize, pacing, picker and complete custom-footer tests still pass.
- Kept only native Rich Segments for plasma plus exact palette-transition
  lookup. Removed the rejected terminal-color merge. No new dependency,
  approximate waves, reduced dimensions, frame skipping or FPS change.
- Final preservation check confirmed all original installed-file hashes and
  both sysinfo hashes unchanged, including the installed-only import. PID 8509
  retained its November 10 start time and exact original command. No javalamp
  transient units or benchmark/pytest/unittest runners remained at that check.
- Temporary editor task definitions are removed during final cleanup; the
  pre-existing empty workspace .vscode directory is retained. No production
  configuration, unrelated workload, autologin or vlock changes were made.
- Result to report: confirmed grayscale mono on Linux standard-color ANSI,
  measured about 16.5% logical CPU in a 12-second captured-output run at the
  12 FPS target; under 10% not achieved. Physical-terminal writes and live
  metric-collection costs remain unmeasured. No installation, console restart,
  commit or push; deployment still requires separate approval.

## 2026-11-15 - Read-only deployment and boot-readiness review

- Owner asked whether deployment preserves current behavior, including boot.
  This was a readiness question, not authorization to install or restart.
- Read the actual getty tty1 override: agetty autologin for mataiwilson with
  noclear. Read the actual .bash_profile: tty1-only gate, .local/bin PATH,
  Ctrl-Z suppression, one-second initialization delay, the exact existing
  java/12 FPS/no-caffeinate/no-splash/sysinfo/mono invocation, then `vlock -a`
  after javalamp exits and restoration of the TSTP trap. None were edited.
- The CLI entry point remains `javalamp.cli:main`. Installing the optimized
  package at the existing pipx entry point should therefore leave the boot
  and post-exit lock sequence unchanged; no boot configuration edit is needed.
- Pipx metadata explicitly records `/julia/Server/repos/javalamp[sysinfo]`,
  Python 3.12.3, and the existing javalamp executable path. Preserve that extra
  and the already-tested dependency versions during a controlled deployment.
  The generic Makefile reinstall target requests only `.` with --force, not
  `[sysinfo]`; do not assume it preserves the optional GPU-stat dependency.
- Preserve/reconcile the recorded installed-only sysinfo import and retain
  a rollback copy before replacement. These are deployment prerequisites,
  not changes made during this review.
- Assessment: source is ready for a controlled deployment, supported by 64
  passing tests. Appearance, timing, controls and footer have isolated
  regression evidence. Installed-package startup, physical console operation,
  exit-to-vlock and an actual reboot have NOT been tested with the new code.
  No guarantee of end-to-end boot verification is implied; those checks remain
  behind separate deployment/restart approval. No install, restart, boot/lock
  edit, commit or push was performed.

## 2026-11-15 - Approved deployment preparation, explicitly no restart

- Owner approved deployment but explicitly prohibited restart and required
  avoiding interruption to parallel work and other server services.
- Plan: build a staged wheel carrying the exact installed sysinfo file, back
  up the existing pipx environment, and install only javalamp into that same
  environment with --no-deps/--no-index. Do not use pipx's environment-recreating
  reinstall target, touch boot/lock configuration, or signal any live process.
- No build backend is installed in the checkout venv. Build isolation may
  fetch packaging tools into temporary staging; none go into the application
  environment or other services. All work retains strict CPU/memory/PID/time
  limits. Runtime Rich 15.0.0, Click 8.4.1, GPU-stat dependencies and pipx
  metadata are protected by before/after file and version checks.
- Added a one-time recovery/verification helper under
  `maintenance/javalamp-deploy-20261115` outside the source checkout. It records
  only filtered container identity/start data, selected host service identities,
  boot-file hashes, package/dependency files and console PID/start identity.
  It checks that the staged wheel changes exactly runner, canvas, picker and
  plasma, preserves installed sysinfo bytes, and retains the same entry point.
- PID 8509 will continue executing its already-loaded old Python code. The
  optimization takes effect on the next normal launch, not immediately after
  the disk update. No restart is required merely to place the files on disk.

## 2026-11-15 - Deployment completed without restart

- Prepared the original full pipx-environment backup and an isolated source
  snapshot. Copied the exact installed sysinfo.py into staging; its original
  SHA256 and extra import are preserved. Audited wheel changes exactly four
  modules: canvas, runner, picker and scenes/plasma. Entry point is unchanged.
- Built `javalamp-0.1.0-py3-none-any.whl`, 50,757 bytes, SHA256
  `38813035181d9b04cca2dfa55afc1da34ef75da4449d262f4c3f7cc2b725ea57`.
  Build-only tooling used pip's isolated temporary environment, not the running
  app environment. Build completed in 13.69s wall / 2.11s CPU under the caps.
- Immediately before installation, the audited wheel, 596 protected environment
  files, dependency versions, boot/shell files, pipx metadata, launcher symlink
  and console identity passed. All 45 running containers and checked host
  services retained their original identities and start information.
- Installed only the local wheel using the existing pipx Python and
  `pip install --no-index --no-deps --no-compile --no-cache-dir --force-reinstall`.
  AF_UNIX-only, half-CPU/256 MiB/zero-swap/16-task limits and a 40s external
  deadline applied. Install took 0.77s wall / 0.42s CPU. No pipx environment
  recreation, dependency update, system package command or service operation.
- Immediate post-install audit passed: expected package hashes installed;
  all protected files/dependencies/sysinfo/boot configuration unchanged;
  original PID 8509 and command/start identity unchanged; all 45 containers
  and checked host service identities/start information unchanged.
- Installed-path assertions and CLI `java --help` confirmed the existing
  executable and --fps/--sysinfo/--theme options. Full regression suite using
  the installed modules: **64 passed in 3.58s**, within the same resource and
  network limits. Tests used captured output and fixtures, not the live TTY.
- Recovery archive SHA256:
  `01efc55e8cbfc4879c2dd5b3292013bb23728174bbaf08a01cdf6d98f7b9fc38`.
  Backup, wheel, filtered pre/post reports and procedure notes are retained in
  [the private recovery directory](../../maintenance/javalamp-deploy-20261115/README.md).
  Directory mode 0700; generated evidence/archive files are owner-only. No
  rollback was needed, and archive restoration has not been rehearsed.
- Important: deployment is complete on disk, but the current console keeps
  running its old loaded code. The new code takes effect on the next normal
  launch. No immediate live CPU improvement is claimed. No console restart,
  signal, boot/vlock edit, other-service interruption, commit or push occurred.

## 2026-11-15 - Live old-process CPU sample after disk deployment

- Owner asked for the current physical-console CPU usage. Read-only pidstat
  sample at 23:43:19-23:43:22 server local time, three one-second intervals:
  101%, 102%, 99%; average **100.67% of one logical CPU** (96.00% user,
  4.67% system). Command used an eight-second external timeout and low priority.
- PID 8509 still has its November 10 start time and original 12 FPS mono/sysinfo
  invocation. This is the old code already loaded in memory, not the deployed
  optimization. No process was signaled or restarted.
- This live measurement includes terminal/device and real collector work;
  the optimized 16.5% captured-output benchmark excludes those costs, so the
  two percentages are not a controlled before/after live-console comparison.

## 2026-11-15 - Session finish

- Reread finish configuration and infra-map conventions. The bounded map pull
  reported already up to date; the unrelated existing host-file edit remained
  untouched. No topology criteria changed, so finish steps 5-11 were skipped:
  no discovery, Mermaid validation, map edit, commit, push or site refresh.
- Created the initiative-level
  [console optimization changelog](../../changelog/2026-11-15-javalamp-console-optimization.md)
  covering the three optimization passes, final measurements, no-restart
  installation, preservation checks, limitations and a staged rollback.
- Changelog section/date/author, local-link, ASCII, whitespace and rollback
  shell-syntax checks passed under bounded resource limits. Rollback commands
  were parsed only, not executed. No new runtime deployment or restart occurred.
- Next runtime check remains the optimized physical console after a separately
  authorized or normal future launch. Under-10% CPU, live optimized CPU usage,
  reboot/physical controls and archive restore remain unverified or unmet as
  documented above. Source changes remain uncommitted and unpushed.

## 2026-11-15 - Source-control approval

- Owner explicitly approved committing and pushing the completed optimization
  after accepting the editor changes. Earlier no-commit/no-push restrictions
  are superseded for these javalamp changes only; no restart was authorized.
- Reviewed the four application modules, three test files, benchmark and this
  log. Private deployment archives, audit reports and recovery tooling remain
  outside the repository and outside the commit.
- Target remains origin `mataiwilson/javalamp`, branch `feature/server-kiosk`.
  Remote inspection returned the original `edd0797` tip; no force push or new
  branch is planned. Existing Git hooks contain only inactive sample files.
- The 64-test checkout and installed-code results above remain the validation
  baseline. GitHub CLI has no current login; attempt the configured Git
  authentication without changing credentials, remotes or global settings.
  The commit/push outcome will be recorded in the server-local changelog.