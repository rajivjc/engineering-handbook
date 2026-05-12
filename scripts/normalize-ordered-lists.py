#!/usr/bin/env python3
"""
Normalize ordered list numbering in markdown files.

Some markdown formatters and editors collapse `1./2./3.` ordered lists to
`1./1./1.` form. Both render identically (markdown engines auto-renumber)
but the source becomes harder to read.

This script restores sequential numbering. It is idempotent — running it
twice produces the same output as running it once.

Usage:
    python3 scripts/normalize-ordered-lists.py [--dry-run] [PATH...]

If no PATH is given, walks the current directory.
"""
import re
import os
import sys


def fix_ordered_lists(text: str) -> tuple[str, int]:
    """Renumber ordered lists in markdown text. Returns (new_text, changes_count)."""
    lines = text.split('\n')
    result = []
    in_code_block = False
    code_fence = None  # Track which fence opened the block
    # Map from indent prefix (str) to current counter for that list level
    list_counters: dict[str, int] = {}
    changes = 0

    for i, line in enumerate(lines):
        # Detect fenced code blocks
        fence_match = re.match(r'^(\s*)(```|~~~)', line)
        if fence_match:
            fence = fence_match.group(2)
            if not in_code_block:
                in_code_block = True
                code_fence = fence
            elif code_fence == fence:
                in_code_block = False
                code_fence = None
            # Reset list state at code block boundaries to be safe
            list_counters = {}
            result.append(line)
            continue

        if in_code_block:
            result.append(line)
            continue

        # Try to match an ordered list item: ^(indent)(number). (content)
        m = re.match(r'^(\s*)(\d+)\. (.+)$', line)
        if not m:
            # Not a list item. If the line is non-blank and not an indented
            # continuation under any active list, clear those list counters.
            if line.strip():
                # Heading lines break all lists
                if re.match(r'^#{1,6} ', line):
                    list_counters = {}
                else:
                    # Clear counters at indent levels where this line is not a continuation
                    to_remove = []
                    for indent in list_counters:
                        # A continuation must be indented strictly more than the list marker,
                        # OR be a blank line (handled above).
                        if not line.startswith(indent + ' ') and not line.startswith(indent + '\t'):
                            to_remove.append(indent)
                    for indent in to_remove:
                        del list_counters[indent]
            result.append(line)
            continue

        indent = m.group(1)
        current_num = int(m.group(2))
        rest = m.group(3)

        # Determine whether this is a continuation of an existing list at this indent
        is_continuation = indent in list_counters

        if not is_continuation:
            # Start a new list at this indent
            list_counters[indent] = 1
        else:
            list_counters[indent] += 1

        # Clear any deeper-indent counters (a list at this indent terminates deeper lists)
        for deeper in [k for k in list_counters if len(k) > len(indent)]:
            del list_counters[deeper]

        expected = list_counters[indent]
        if current_num != expected:
            changes += 1
            new_line = f'{indent}{expected}. {rest}'
            result.append(new_line)
        else:
            result.append(line)

    return '\n'.join(result), changes


def process_file(filepath: str, dry_run: bool) -> int:
    """Process one file. Returns the number of renumbered items."""
    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()
    fixed, changes = fix_ordered_lists(original)
    if changes > 0 and not dry_run:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(fixed)
    return changes


def walk_paths(paths: list[str]) -> list[str]:
    """Yield .md file paths under each given path (or single file paths directly)."""
    md_files = []
    for path in paths:
        if os.path.isfile(path) and path.endswith('.md'):
            md_files.append(path)
        elif os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                # Skip hidden directories and node_modules
                dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != 'node_modules']
                for fname in filenames:
                    if fname.endswith('.md'):
                        md_files.append(os.path.join(dirpath, fname))
    return sorted(md_files)


def main() -> int:
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    args = [a for a in args if a != '--dry-run']
    paths = args if args else ['.']

    md_files = walk_paths(paths)
    total_changes = 0
    files_changed = 0
    for filepath in md_files:
        changes = process_file(filepath, dry_run)
        if changes > 0:
            files_changed += 1
            total_changes += changes
            verb = 'would renumber' if dry_run else 'renumbered'
            print(f'  {verb} {changes} items in {filepath}')

    if files_changed == 0:
        print(f'No changes needed across {len(md_files)} files.')
    else:
        action = 'Would change' if dry_run else 'Changed'
        print(f'\n{action} {total_changes} items across {files_changed} files (of {len(md_files)} scanned).')

    return 0


if __name__ == '__main__':
    sys.exit(main())
