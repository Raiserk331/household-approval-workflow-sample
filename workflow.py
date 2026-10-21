"""Local meeting notes and prewritten draft approval. No outbound actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate input key')
        result[key] = value
    return result


def validate(value):
    if not isinstance(value, dict) or set(value) != {'meeting_id', 'notes', 'proposedDraft'}:
        raise ValueError('input requires meeting_id, notes and proposedDraft only')
    if not isinstance(value['meeting_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value['meeting_id']):
        raise ValueError('meeting_id must use letters, digits, underscore or hyphen')
    for field in ('notes', 'proposedDraft'):
        if not isinstance(value[field], str) or not value[field].strip() or len(value[field].encode()) > 16384:
            raise ValueError('notes and proposedDraft must be nonempty text, at most16KiB each')
    return value


def checked(row):
    value = validate(json.loads(row['payload'], object_pairs_hook=no_duplicate_keys))
    if value['meeting_id'] != row['id'] or digest(value) != row['digest']:
        raise ValueError('stored content changed; approval refused')
    return value


def perform(args):
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    dbfile = state / 'workflow.sqlite'
    if dbfile.is_symlink():
        raise ValueError('database symlink refused')
    db = sqlite3.connect(dbfile, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, approved_digest TEXT)')
        db.execute('BEGIN IMMEDIATE')
        if args.command == 'ingest':
            if args.input.is_symlink() or not args.input.is_file() or args.input.stat().st_size > 65536:
                raise ValueError('input must be a bounded regular JSON file')
            value = validate(json.loads(args.input.read_text(), object_pairs_hook=no_duplicate_keys))
            fingerprint = digest(value)
            row = db.execute('SELECT * FROM drafts WHERE id=?', (value['meeting_id'],)).fetchone()
            if row:
                checked(row)
                if row['digest'] != fingerprint:
                    raise ValueError('conflicting content for existing meeting_id; use a new revision ID')
                result = {'id': row['id'], 'digest': fingerprint, 'state': row['state'], 'duplicate': True}
            else:
                db.execute('INSERT INTO drafts VALUES(?,?,?,?,NULL)', (value['meeting_id'], canonical(value), fingerprint, 'pending'))
                result = {'id': value['meeting_id'], 'digest': fingerprint, 'state': 'pending', 'duplicate': False}
        else:
            row = db.execute('SELECT * FROM drafts WHERE id=?', (args.meeting_id,)).fetchone()
            if row is None:
                raise ValueError('unknown meeting_id')
            value = checked(row)
            if args.command == 'show':
                result = {'content': value, 'digest': row['digest'], 'state': row['state']}
            elif args.command == 'approve':
                if args.digest != row['digest'] or row['state'] not in ('pending', 'approved'):
                    raise ValueError('approval must match reviewed pending content digest')
                db.execute('UPDATE drafts SET state=?,approved_digest=? WHERE id=?', ('approved', row['digest'], row['id']))
                result = {'id': row['id'], 'state': 'approved', 'digest': row['digest']}
            else:
                if row['state'] not in ('approved', 'exported') or row['approved_digest'] != row['digest']:
                    raise ValueError('matching approval required before export')
                folder = state / 'exports'
                if folder.is_symlink():
                    raise ValueError('export directory symlink refused')
                output = folder / (row['id'] + '.md')
                content = (value['proposedDraft'].strip() + '\n').encode()
                if os.path.lexists(state / 'STOP'):
                    raise ValueError('STOP present; export blocked')
                folder.mkdir(exist_ok=True)
                if output.is_symlink():
                    raise ValueError('export symlink refused')
                if output.exists():
                    if output.stat().st_size != len(content) or output.read_bytes() != content:
                        raise ValueError('existing export differs; refusing overwrite')
                else:
                    # Recheck immediately before writing. This is not an OS security boundary.
                    if os.path.lexists(state / 'STOP'):
                        raise ValueError('STOP present; export blocked')
                    with output.open('xb') as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                db.execute('UPDATE drafts SET state=? WHERE id=?', ('exported', row['id']))
                result = {'id': row['id'], 'state': 'exported', 'file': str(output), 'draft_only': True}
        db.execute('COMMIT')
        return result
    finally:
        if db.in_transaction:
            db.execute('ROLLBACK')
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('ingest').add_argument('input', type=Path)
    for name in ('show', 'approve', 'export'):
        command = commands.add_parser(name)
        command.add_argument('meeting_id')
        if name == 'approve':
            command.add_argument('--digest', required=True)
    try:
        print(json.dumps(perform(parser.parse_args()), ensure_ascii=False))
        return 0
    except ValueError as error:
        # Our validation errors are fixed messages and never interpolate meeting text.
        print(json.dumps({'error': str(error)}))
        return 2
    except (OSError, sqlite3.Error):
        print(json.dumps({'error': 'Local file or storage operation failed; no export confirmed.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
