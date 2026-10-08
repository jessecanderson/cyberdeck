# Workflow inspection and recovery

## Journal recovery

Journal saves compare the disk contents with the version loaded by the editor,
write to a unique temporary file, flush, and atomically replace the destination.
This detects external changes observed before a save; it is not a distributed lock
for simultaneous editors or sync tools. A failed save keeps the editor dirty and
blocks changing dates, changing modules, and normal quit. Copy edits for safekeeping,
resolve the filesystem problem, or use `/journal reload` after preserving your text.
Reload requires confirmation before discarding the buffer; a failed read keeps it intact.
Forced process termination cannot guarantee recovery of unsaved edits.

Quick entries first save the current editor. `/journal DATE` saves the previous
entry before changing the date; the previous buffer is never written to the new day.

## Reading and search

F8 toggles following per agent. `/follow off` holds the current vertical position;
`/follow on` scrolls to the latest output. Search matches loaded messages using
Unicode normalization and case-insensitive comparison. Up/Down moves while search
retains focus; Enter reveals the selected message and disables following. History
must be loaded with `/older` before it can be searched. `/clear` remains display-only.

The operation filter is per agent. `/operations failed` selects failures,
`/operations files` selects file changes, and `/operations all` restores all rows.
Details always refer to the selected filtered operation.

## Pending input

`/queue` keeps its textual inspection behavior. `/queue pause` pauses delivery;
`/queue edit` also opens the editor. Opening it recovers any reserved but unstarted
queue send before allowing mutation. It does not interrupt an already accepted turn.
Only confirmed-unsent prompts can be edited, removed, or reordered. Editing does
not change an active turn, uncertain input, or another agent's queue.

Enter on a list item opens its multiline editor. Ctrl+S saves and returns to the
list; Ctrl+D removes the selected item; Ctrl+Up/Down changes its order. Tab switches
focus. Ctrl+R resumes when READY, after edits have been saved. Escape closes and
leaves the queue paused. `/queue clear` retains its existing behavior of discarding
both pending input and uncertainty records, without unpausing.

## Dispatch results

Each dispatch has an ID and one result per target. Results distinguish SENDING,
RUNNING, COMPLETED, FAILED, and CANCELLED. Successful submission means RUNNING;
only the provider's normalized ready event establishes completion. COMPLETED means
the turn ended; it does not assert that the requested task passed validation. Completion can
precede the return of a provider send call. Errors and disconnects finish only the
affected target; other targets continue independently.

`/results` updates in the background without selecting an agent. Enter opens a
live target. Ctrl+R on a failure opens a confirmation before creating a new attempt
for that target. The agent must first be recovered and READY. Uncertain delivery
blocks retry: inspect the conversation and explicitly resubmit if appropriate.

Up to 50 dispatch runs are retained. Saved records contain status and timestamps;
original prompts and raw failure reasons are process-local. After restart,
unfinished records are UNKNOWN, not assumed successful or automatically replayed.
Offline targets must be restored explicitly through `/sessions` or `/restore`.

## Continuity and privacy

Recent workspaces are retained after use. `/recent` selects a path as the default
for both New Uplink and `/new`; missing paths cannot be selected. Session reference
retention defaults off. `/sessions on` remembers resumable provider IDs, callsigns,
workspace paths, and native-agent identity. `/sessions` restores one chosen reference
using the provider's existing resume contract. No provider process starts merely
because a reference exists. Archive removes the saved reference; disconnect retains
it when retention is enabled. Turning retention off clears saved references.

Metadata uses schema version 1 and atomic replacement in `config.state.json`
beside configuration. Corrupt or unsupported metadata produces a visible fallback
without preventing startup. Limits are 20 workspaces, 50 sessions, and 50 dispatch
runs. `/sessions reset` confirms removal of all this metadata; it leaves live agents,
journal files, and transcripts intact. `/preferences reset` confirms reset of boot,
density, default runtime, workspace, and retention settings. Custom runtimes,
installed modules, themes, journal paths, and provider permission settings remain.

## Rendering measurements

Local Python 3.13 measurements at 160×50 with 1,000 transcript messages and
500 operations: the original benchmark measured 8.4820 seconds before this change
and 3.1667 seconds after widget reuse. With the new settled measurements, an
unchanged refresh took 0.1672 seconds and one streamed update took 0.1619 seconds.
These are local comparison measurements, not CI timing thresholds. Run
`PYTHONPATH=src python scripts/benchmark_rendering.py` to measure another environment.
