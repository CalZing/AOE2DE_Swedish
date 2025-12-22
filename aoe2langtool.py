#!/usr/bin/env python3
"""
aoe2langtool - Age of Empires II Language Translation Tool

Manages game text translations through a CSV intermediate format.
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class ValidationError(Exception):
    """Raised when validation fails"""
    pass


def parse_txt_line(line: str) -> Optional[Tuple[str, str, str]]:
    """
    Parse a line from txt file.
    
    Returns: (id, string_value, rest_of_line) or None if comment/empty
    rest_of_line includes any trailing comment
    """
    stripped = line.rstrip('\r\n')
    
    # Empty line or comment line
    if not stripped or stripped.lstrip().startswith('//'):
        return None
    
    # Match: ID "string" optional_comment
    # ID can be alphanumeric/underscore/dash
    match = re.match(r'^([A-Za-z0-9_-]+)\s+"((?:[^"\\]|\\.)*)"(.*)$', stripped)
    if not match:
        return None
    
    id_val, string_val, rest = match.groups()
    return (id_val, string_val, rest)


def read_txt_file(filepath: Path) -> List[Tuple[str, str]]:
    """
    Read a txt file and return list of (ID, string_value) tuples in order.
    String values are kept with escape sequences as-is.
    Allows duplicate IDs.
    """
    result = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            parsed = parse_txt_line(line)
            if parsed:
                id_val, string_val, _ = parsed
                result.append((id_val, string_val))
    
    return result


def validate_format_specifiers(original: str, translated: str, id_val: str, lang: str) -> None:
    """
    Validate that format specifiers match between original and translated strings.
    Allows reordering arguments with positional specifiers (e.g., %0s, %1d).
    Raises ValidationError if types don't match, warns if order differs.
    Note: "% " (percent followed by space) is NOT a format specifier.
    Note: %0s, %1s, etc. are positional; %10s, %20s are width specifiers.
    """
    # Find all format specifiers
    # Positional: %[0-9]<type> (single digit = position)
    # Width/other: %[width/flags]<type>
    # But NOT "% " (percent followed by space - that's just showing percentage)
    pattern = r'%(?! )[-#0 +]*(?:\*|\d+)?(?:\.(?:\*|\d+)?)?[hlL]?[diouxXeEfFgGaAcspn%]'
    
    original_specs = re.findall(pattern, original)
    translated_specs = re.findall(pattern, translated)
    
    # Extract just the type character (last char of each specifier)
    def extract_types(specs):
        return sorted([spec[-1] for spec in specs])
    
    original_types = extract_types(original_specs)
    translated_types = extract_types(translated_specs)
    
    # Check if types match (regardless of order)
    if original_types != translated_types:
        raise ValidationError(
            f"Format specifier mismatch for ID '{id_val}' in language '{lang}':\n"
            f"  Original: {original_specs} (types: {original_types})\n"
            f"  {lang}: {translated_specs} (types: {translated_types})"
        )
    
    # Warn only if positional specifiers are used
    # Positional: %[0-9]<type> where there's EXACTLY one digit between % and type
    def has_positional(specs):
        for spec in specs:
            # Match pattern: %<exactly_one_digit><type_char>
            # e.g., %0s, %1d, %2s (positional)
            # NOT %10s, %05d (width/precision)
            match = re.match(r'^%(\d)([diouxXeEfFgGaAcspn])$', spec)
            if match:
                return True
        return False
    
    if has_positional(original_specs) or has_positional(translated_specs):
        print(f"Warning: ID '{id_val}' uses positional specifiers - verify argument order manually", file=sys.stderr)


def cmd_import(args):
    """Import: Create new CSV from original txt file"""
    original_data = read_txt_file(args.input)
    
    # Count occurrences of each ID
    id_counts = {}
    rows = []
    
    for id_val, string_val in original_data:
        if id_val not in id_counts:
            id_counts[id_val] = 0
        id_counts[id_val] += 1
        occurrence = id_counts[id_val]
        
        rows.append({
            'ID': id_val,
            'Occurrence': occurrence,
            'original': string_val
        })
    
    # Write CSV
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['ID', 'Occurrence', 'original'])
        writer.writeheader()
        writer.writerows(rows)
    
    duplicates = sum(1 for count in id_counts.values() if count > 1)
    print(f"Created {args.output} with {len(rows)} entries ({duplicates} IDs with duplicates)")



def cmd_add(args):
    """Add: Add a complete language column to existing CSV"""
    # Read existing CSV
    if not args.output.exists():
        print(f"Error: CSV file {args.output} does not exist. Run 'import' first.", file=sys.stderr)
        sys.exit(1)
    
    with open(args.output, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        csv_rows = list(reader)
    
    # Check if language column already exists
    if args.language in headers:
        print(f"Error: Language column '{args.language}' already exists in CSV.", file=sys.stderr)
        sys.exit(1)
    
    # Read translation file
    trans_data = read_txt_file(args.input)
    
    # Count occurrences in both files
    csv_id_counts = {}
    for row in csv_rows:
        id_val = row['ID']
        csv_id_counts[id_val] = csv_id_counts.get(id_val, 0) + 1
    
    trans_id_counts = {}
    for id_val, _ in trans_data:
        trans_id_counts[id_val] = trans_id_counts.get(id_val, 0) + 1
    
    # Validate: For IDs that exist in BOTH files, occurrence counts must match
    # IDs only in translation are ignored (not added)
    mismatches = []
    ignored_ids = set()
    
    for id_val in sorted(trans_id_counts.keys()):
        csv_count = csv_id_counts.get(id_val, 0)
        trans_count = trans_id_counts[id_val]
        
        if csv_count == 0:
            # ID exists in translation but not in CSV - ignore it
            ignored_ids.add(id_val)
        elif csv_count != trans_count:
            # ID exists in both but with different occurrence counts - error
            mismatches.append(f"  {id_val}: CSV has {csv_count} occurrence(s), translation has {trans_count}")
    
    if mismatches:
        error_msg = "Error: Occurrence count mismatch for IDs present in both files.\n" + "\n".join(mismatches[:20])
        if len(mismatches) > 20:
            error_msg += f"\n  ... and {len(mismatches) - 20} more mismatches"
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    
    # Build translation lookup by (ID, occurrence)
    # Only include IDs that exist in CSV (ignore extras from translation file)
    trans_lookup = {}
    trans_id_occ = {}
    for id_val, string_val in trans_data:
        if id_val not in ignored_ids:  # Only process IDs that exist in CSV
            if id_val not in trans_id_occ:
                trans_id_occ[id_val] = 0
            trans_id_occ[id_val] += 1
            trans_lookup[(id_val, trans_id_occ[id_val])] = string_val
    
    # Add language column to CSV rows
    new_headers = list(headers) + [args.language]
    
    for row in csv_rows:
        id_val = row['ID']
        occurrence = int(row['Occurrence'])
        key = (id_val, occurrence)
        # If translation exists, use it; otherwise leave empty
        row[args.language] = trans_lookup.get(key, '')
    
    # Write updated CSV
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=new_headers)
        writer.writeheader()
        writer.writerows(csv_rows)
    
    translated_count = sum(1 for row in csv_rows if row[args.language])
    empty_count = len(csv_rows) - translated_count
    
    print(f"Added language '{args.language}' to {args.output}")
    print(f"  Translated: {translated_count} entries")
    if empty_count > 0:
        print(f"  Empty: {empty_count} entries")
    if ignored_ids:
        print(f"  Ignored: {len(ignored_ids)} IDs not in CSV", file=sys.stderr)



def cmd_update(args):
    """Update: Sync original column with updated original txt file"""
    # Read existing CSV
    if not args.output.exists():
        print(f"Error: CSV file {args.output} does not exist. Run 'import' first.", file=sys.stderr)
        sys.exit(1)
    
    with open(args.output, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        csv_rows = list(reader)
    
    # Build lookup: (ID, Occurrence) -> row
    csv_lookup = {}
    for row in csv_rows:
        key = (row['ID'], row['Occurrence'])
        csv_lookup[key] = row
    
    # Read updated original file
    original_data = read_txt_file(args.input)
    
    # Count occurrences in new file
    new_id_counts = {}
    new_entries = []
    for id_val, string_val in original_data:
        if id_val not in new_id_counts:
            new_id_counts[id_val] = 0
        new_id_counts[id_val] += 1
        new_entries.append((id_val, new_id_counts[id_val], string_val))
    
    # Count occurrences in old CSV
    old_id_counts = {}
    for row in csv_rows:
        id_val = row['ID']
        old_id_counts[id_val] = old_id_counts.get(id_val, 0) + 1
    
    # Build updated rows
    updated_rows = []
    new_occurrence_count = 0
    
    for id_val, occurrence, string_val in new_entries:
        key = (id_val, str(occurrence))
        
        if key in csv_lookup:
            # Update existing entry
            row = csv_lookup[key].copy()
            row['original'] = string_val
            updated_rows.append(row)
        else:
            # New entry or changed occurrence count
            # Check if this ID exists in old CSV
            if id_val in old_id_counts:
                # Occurrence count changed - mark as "new"
                row = {h: '' for h in headers}
                row['ID'] = id_val
                row['Occurrence'] = 'new'
                row['original'] = string_val
                new_occurrence_count += 1
            else:
                # Completely new ID
                row = {h: '' for h in headers}
                row['ID'] = id_val
                row['Occurrence'] = occurrence
                row['original'] = string_val
            
            updated_rows.append(row)
    
    # Write updated CSV
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(updated_rows)
    
    added = len([id for id in new_id_counts if id not in old_id_counts])
    removed = len([id for id in old_id_counts if id not in new_id_counts])
    
    print(f"Updated {args.output}: {len(updated_rows)} entries (added: {added}, removed: {removed})")
    
    if new_occurrence_count > 0:
        print(f"WARNING: {new_occurrence_count} entries have Occurrence='new' due to changed duplicate counts.", 
              file=sys.stderr)
        print(f"Manual intervention required before export.", file=sys.stderr)



def cmd_export(args):
    """Export: Generate txt file from CSV using reference file as template"""
    # Read CSV
    if not args.input.exists():
        print(f"Error: CSV file {args.input} does not exist.", file=sys.stderr)
        sys.exit(1)
    
    with open(args.input, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        csv_rows = list(reader)
    
    # Check for "new" occurrences
    new_occurrences = [row for row in csv_rows if row['Occurrence'] == 'new']
    if new_occurrences:
        print(f"Error: CSV contains {len(new_occurrences)} entries with Occurrence='new'", file=sys.stderr)
        print(f"Manual intervention required before export.", file=sys.stderr)
        print(f"These IDs need resolution:", file=sys.stderr)
        for row in new_occurrences[:10]:
            print(f"  {row['ID']}: {row['original'][:50]}...", file=sys.stderr)
        if len(new_occurrences) > 10:
            print(f"  ... and {len(new_occurrences) - 10} more", file=sys.stderr)
        sys.exit(1)
    
    # Check if language exists
    if args.language not in headers:
        print(f"Error: Language '{args.language}' not found in CSV. Available: {headers}", 
              file=sys.stderr)
        sys.exit(1)
    
    # Build lookup: (ID, Occurrence) -> row
    csv_lookup = {}
    for row in csv_rows:
        key = (row['ID'], int(row['Occurrence']))
        csv_lookup[key] = row
    
    # Read reference file and track occurrence counts
    ref_id_counts = {}
    output_lines = []
    
    with open(args.reference, 'rb') as f:
        # Detect line ending from first line
        first_line = f.readline()
        if first_line.endswith(b'\r\n'):
            line_ending = '\r\n'
        elif first_line.endswith(b'\n'):
            line_ending = '\n'
        else:
            line_ending = '\n'
        
        # Rewind and read all lines
        f.seek(0)
        content = f.read().decode('utf-8')
    
    for line in content.split('\n'):
        # Remove any \r that might be present
        line = line.rstrip('\r')
        
        parsed = parse_txt_line(line + '\n')
        
        if parsed is None:
            # Comment or empty line - keep as-is
            output_lines.append(line)
        else:
            id_val, original_string, rest = parsed
            
            # Track occurrence
            if id_val not in ref_id_counts:
                ref_id_counts[id_val] = 0
            ref_id_counts[id_val] += 1
            occurrence = ref_id_counts[id_val]
            
            # Check if ID+Occurrence exists in CSV
            key = (id_val, occurrence)
            if key not in csv_lookup:
                print(f"Error: ID '{id_val}' (occurrence {occurrence}) found in reference file but not in CSV.", 
                      file=sys.stderr)
                print("Run 'update' to sync the CSV with the reference file.", file=sys.stderr)
                sys.exit(1)
            
            row = csv_lookup[key]
            
            # Get translation or fall back to original
            trans_string = row[args.language]
            if not trans_string:
                trans_string = row['original']
            
            # Validate format specifiers
            try:
                validate_format_specifiers(
                    row['original'], 
                    trans_string, 
                    f"{id_val}[{occurrence}]",
                    args.language
                )
            except ValidationError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            
            # Reconstruct line
            new_line = f'{id_val} "{trans_string}"{rest}'
            output_lines.append(new_line)
    
    # Write output file with correct line endings
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        f.write(line_ending.join(output_lines))
        # Add final newline if original had one
        if content.endswith('\n'):
            f.write(line_ending)
    
    print(f"Exported {args.language} to {args.output}")



def main():
    parser = argparse.ArgumentParser(
        description='Age of Empires II Language Translation Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create new CSV from original
  aoe2langtool import -i english.txt -o game.csv
  
  # Add complete Swedish translation
  aoe2langtool add -i swedish.txt -l swedish -o game.csv
  
  # Update CSV when english.txt changes
  aoe2langtool update -i english.txt -o game.csv
  
  # Export Swedish translation
  aoe2langtool export -l swedish -i game.csv -r english.txt -o swedish.txt
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    subparsers.required = True
    
    # Import command
    import_parser = subparsers.add_parser('import', help='Create new CSV from original txt file')
    import_parser.add_argument('-i', '--input', type=Path, required=True,
                              help='Input txt file (original language)')
    import_parser.add_argument('-o', '--output', type=Path, required=True,
                              help='Output CSV file')
    import_parser.set_defaults(func=cmd_import)
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add complete language column to CSV')
    add_parser.add_argument('-i', '--input', type=Path, required=True,
                           help='Input txt file (translation)')
    add_parser.add_argument('-l', '--language', required=True,
                           help='Language name for column')
    add_parser.add_argument('-o', '--output', type=Path, required=True,
                           help='CSV file to update')
    add_parser.set_defaults(func=cmd_add)
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Sync original column with updated txt file')
    update_parser.add_argument('-i', '--input', type=Path, required=True,
                              help='Updated original txt file')
    update_parser.add_argument('-o', '--output', type=Path, required=True,
                              help='CSV file to update')
    update_parser.set_defaults(func=cmd_update)
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Generate txt file from CSV')
    export_parser.add_argument('-l', '--language', required=True,
                              help='Language column to export')
    export_parser.add_argument('-i', '--input', type=Path, required=True,
                              help='Input CSV file')
    export_parser.add_argument('-r', '--reference', type=Path, required=True,
                              help='Reference txt file (template)')
    export_parser.add_argument('-o', '--output', type=Path, required=True,
                              help='Output txt file')
    export_parser.set_defaults(func=cmd_export)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
