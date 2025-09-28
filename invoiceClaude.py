import subprocess
import os
import csv
import json

def parse_invoice_with_claude(file_path, attempt_num):
    prompt = f"""Analyze this aviation invoice and extract:
1. Date - Look for "DUE" dates or invoice dates (format: MM/DD/YY or MM/DD/YYYY)
2. Tail Number (aircraft registration like N433SP, N8184G, etc)
3. Event Type (100-HR INSPECTION, 50-HR INSPECTION, ANNUAL, REPLACEMENT, SERVICE, REPAIR, etc)
4. Component Description (main component or service)

IMPORTANT: If you see "DUE" followed by a date, use that date.

Respond with ONLY a JSON object like this:
{{"date": "03/15/2024", "tail_number": "N12345", "event_type": "REPLACEMENT", "component_description": "alternator"}}"""

    # Write prompt to temp file to avoid shell escaping issues
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(prompt)
        temp_prompt = f.name

    cmd = f'claude --dangerously-skip-permissions "{file_path}" < "{temp_prompt}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

    # Clean up temp file
    import os as os_module
    os_module.unlink(temp_prompt)

    try:
        response = result.stdout.strip()

        # Remove markdown code block if present
        if response.startswith("```"):
            lines = response.split('\n')
            response = '\n'.join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        # Handle multi-line JSON by removing extra whitespace
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            json_str = response[json_start:json_end]
            # Debug print
            if attempt_num == 1:
                print(f"  DEBUG: Attempting to parse: {repr(json_str[:50])}...")
            # Parse the JSON (handles multi-line automatically)
            parsed = json.loads(json_str)
            return parsed
    except json.JSONDecodeError as e:
        print(f"  JSON decode error in attempt {attempt_num}: {e}")
    except Exception as e:
        print(f"  Error parsing attempt {attempt_num}: {e}")

    return {
        "date": None,
        "tail_number": None,
        "event_type": None,
        "component_description": None
    }

def determine_reason_for_removal(event_type, component):
    component_lower = (component or "").lower()
    event_lower = (event_type or "").lower()

    if "oil filter" in component_lower:
        return "Scheduled"
    elif "air filter" in component_lower:
        if "replacement" in event_lower:
            return "Failure"
        elif "service" in event_lower or "inspection" in event_lower:
            return "Scheduled"
        else:
            return "Failure"
    elif any(x in event_lower for x in ["inspection", "annual", "service"]):
        return "Scheduled"
    else:
        return "Failure"

def process_invoices():
    sample_dir = "/home/seanpatten/projects/invoiceClaude/invoices/all invoices original/invoices/representative sample"
    files = sorted([f for f in os.listdir(sample_dir) if f.endswith(('.pdf', '.txt'))])

    NUM_ATTEMPTS = 1  # Easy to change to 3 for validation

    headers = ["Filename", "Date", "Tail_Number", "Event_Type", "Component_Description", "Reason_for_Removal", "Conflict_Flag", "Conflict_Details"]

    # Initialize CSV with headers
    with open("invoice_analysis.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    print(f"Found {len(files)} files to process")
    print("="*100)

    for idx, file_name in enumerate(files, 1):
        file_path = os.path.join(sample_dir, file_name)
        print(f"\n[{idx}/{len(files)}] Processing: {file_name}")

        runs = []
        for i in range(1, NUM_ATTEMPTS + 1):
            if NUM_ATTEMPTS > 1:
                print(f"  Running attempt {i}/{NUM_ATTEMPTS}...")
            parsed = parse_invoice_with_claude(file_path, i)
            runs.append(parsed)

        date_set = set(r["date"] for r in runs if r["date"])
        tail_set = set(r["tail_number"] for r in runs if r["tail_number"])
        event_set = set(r["event_type"] for r in runs if r["event_type"])
        component_set = set(r["component_description"] for r in runs if r["component_description"])

        has_conflict = len(date_set) > 1 or len(tail_set) > 1 or len(event_set) > 1 or len(component_set) > 1

        final_date = list(date_set)[0] if date_set else None
        final_tail = list(tail_set)[0] if tail_set else None
        final_event = list(event_set)[0] if event_set else None
        final_component = list(component_set)[0] if component_set else None

        reason = determine_reason_for_removal(final_event, final_component)

        conflict_flag = "CONFLICT" if has_conflict else ""
        conflict_details = ""
        if has_conflict:
            conflicts = []
            if len(date_set) > 1:
                conflicts.append(f"Dates: {list(date_set)}")
            if len(tail_set) > 1:
                conflicts.append(f"Tails: {list(tail_set)}")
            if len(event_set) > 1:
                conflicts.append(f"Events: {list(event_set)}")
            if len(component_set) > 1:
                conflicts.append(f"Components: {list(component_set)}")
            conflict_details = "; ".join(conflicts)

        row = [
            file_name[:30],
            final_date or "",
            final_tail or "",
            final_event or "",
            final_component or "",
            reason,
            conflict_flag,
            conflict_details
        ]

        # Append to CSV immediately
        with open("invoice_analysis.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

        # Display the result
        print(f"  ✓ Date: {final_date or 'N/A'}")
        print(f"  ✓ Tail: {final_tail or 'N/A'}")
        print(f"  ✓ Event: {final_event or 'N/A'}")
        print(f"  ✓ Component: {final_component or 'N/A'}")
        print(f"  ✓ Reason: {reason}")
        if conflict_flag:
            print(f"  ⚠ CONFLICTS: {conflict_details}")
        print(f"  → Saved to CSV")

    print("\n" + "="*100)
    print(f"COMPLETE: All {len(files)} files processed and saved to invoice_analysis.csv")
    print("="*100)

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        # Debug mode - process single file
        if len(sys.argv) > 2:
            debug_file = sys.argv[2]
        else:
            # Default to the problematic file
            debug_file = "2023-06-30 Fwd Invoice 1522 from DGM  Justice Air Maintenance.txt"

        sample_dir = "/home/seanpatten/projects/invoiceClaude/invoices/all invoices original/invoices/representative sample"
        file_path = os.path.join(sample_dir, debug_file)

        print("="*80)
        print("DEBUG MODE - SINGLE FILE TEST")
        print("="*80)
        print(f"Testing file: {debug_file}")

        # Show file contents (for text files only)
        if os.path.exists(file_path):
            if file_path.endswith('.txt'):
                with open(file_path, 'r') as f:
                    content = f.read()
                    print("\nFirst 500 characters:")
                    print("-"*40)
                    print(content[:500])
                    print("...")
                    print("-"*40)
            else:
                print(f"\n[Binary file - cannot display contents]")
                print("-"*40)

        # Parse the invoice with raw output display
        print("\nSending to Claude...")
        prompt = """Analyze this aviation invoice and extract:
1. Date - Look for "DUE" dates or invoice dates (format: MM/DD/YY or MM/DD/YYYY)
2. Tail Number (aircraft registration like N433SP, N8184G, etc)
3. Event Type (100-HR INSPECTION, 50-HR INSPECTION, ANNUAL, REPLACEMENT, SERVICE, REPAIR, etc)
4. Component Description (main component or service)

IMPORTANT: If you see "DUE" followed by a date, use that date.

Respond with ONLY a JSON object like this:
{"date": "03/15/2024", "tail_number": "N12345", "event_type": "REPLACEMENT", "component_description": "alternator"}"""
        cmd = f'echo "{prompt}" | claude --dangerously-skip-permissions "{file_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

        print("\nRaw Claude output:")
        print("-"*40)
        print(result.stdout)
        print("-"*40)

        print("\nParsing invoice...")
        parsed = parse_invoice_with_claude(file_path, 1)

        print("\nExtracted data:")
        print("-"*40)
        for key, value in parsed.items():
            print(f"  {key}: {value or 'N/A'}")

        # Determine reason
        reason = determine_reason_for_removal(parsed.get("event_type"), parsed.get("component_description"))
        print(f"  reason_for_removal: {reason}")

        # Save to singleFile.csv
        headers = ["Filename", "Date", "Tail_Number", "Event_Type", "Component_Description", "Reason_for_Removal"]
        row = [
            debug_file,
            parsed.get("date") or "",
            parsed.get("tail_number") or "",
            parsed.get("event_type") or "",
            parsed.get("component_description") or "",
            reason
        ]

        with open("singleFile.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerow(row)

        print("\n✓ Saved to singleFile.csv")
        print("="*80)
    else:
        process_invoices()