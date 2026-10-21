# Local draft approval workflow

Original synthetic Python work sample for a small part of an automation pilot. It stores supplied notes and a **prewritten draft** in SQLite, then exports a plain-text draft only after approval of the exact content. It does not generate text or send messages.

## Run

Python standard library only; no packages, accounts or network access required. Tested with Python 3.14.

```sh
python3 workflow.py --state ./demo-state ingest synthetic-meeting.json
python3 workflow.py --state ./demo-state show synthetic-visit-001
python3 workflow.py --state ./demo-state approve synthetic-visit-001 --digest DIGEST_FROM_SHOW
python3 workflow.py --state ./demo-state export synthetic-visit-001
```

Read both `notes` and `proposedDraft` before approving. Replace `DIGEST_FROM_SHOW` with the exact digest printed by `show`. Output is `demo-state/exports/synthetic-visit-001.md`, a local draft file. Create `demo-state/STOP` to block subsequent export attempts.

## Verified behavior

- State persists across separate process launches.
- Identical IDs and content are idempotent; conflicting content requires a new revision ID.
- Export requires approval bound to the content digest.
- Changing stored content or its digest cannot reuse the previous approval.
- A different existing export is not overwritten.
- STOP created after approval blocks a subsequent export.

```sh
python3 -m unittest discover -s . -p test_workflow.py -v
```

Seven automated tests passed. A separate review passed 14 scoped checks across 13 actual CLI subprocesses. All inputs were synthetic. See `validation-summary.json`.

## Limits

This is a component demonstration, not a deployed household assistant. No text extraction, local language model, n8n, Google, Notion, email or calendar integration is implemented. No client work or prior household deployment is claimed.

Approval is a same-user CLI command, not authenticated human identity. Any process with the same OS permissions can approve, edit the program/database, remove STOP or forge all fields. Hashes check consistency, not authorization. Storage is plaintext. Authentication, encryption, UI, backups and independently protected execution are outside this example.

STOP is checked before export; it cannot cancel an in-flight system write. Concurrent races and sudden power loss were not tested. Restart checks demonstrate process persistence, not full machine recovery.
