#!/usr/bin/env python3
"""Quick status check for the hooks and LangGraph system."""

import sqlite3
import os

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
DB_PATH = os.path.join(STATE_DIR, "narratives.db")

print("=" * 60)
print("HOOKS & LANGGRAPH SYSTEM STATUS")
print("=" * 60)

# 1. Check narratives database
print("\n[1] Narratives Database")
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM narratives")
total = c.fetchone()[0]
print(f"  Total narratives: {total}")

c.execute("SELECT session_id, strategy, word_count, narrative, generated_at FROM narratives ORDER BY generated_at DESC LIMIT 3")
rows = c.fetchall()
print(f"  Recent entries:")
for r in rows:
    sid = r[0]
    strat = r[1] or "N/A"
    wc = r[2] or 0
    date = r[4] or "N/A"
    narrative_preview = (r[3][:80] + "...") if r[3] and len(r[3]) > 80 else (r[3] or "None")
    print(f"    {sid[:8]}... | strategy={strat} | words={wc} | {date}")
    print(f"    Preview: {narrative_preview}")

conn.close()

# 2. Check hooks debug log
print("\n[2] Hooks Debug Log")
debug_log = os.path.join(STATE_DIR, "hooks-debug.log")
if os.path.exists(debug_log):
    with open(debug_log, "r") as f:
        content = f.read()

    hook_types = {}
    for line in content.splitlines():
        if "HOOK TRIGGERED:" in line:
            parts = line.split("HOOK TRIGGERED: ")
            if len(parts) > 1:
                hook_name = parts[1].split()[0]
                hook_types[hook_name] = hook_types.get(hook_name, 0) + 1

    print(f"  Total hook triggers: {sum(hook_types.values())}")
    print(f"  Hook type distribution:")
    for name, count in sorted(hook_types.items(), key=lambda x: -x[1]):
        print(f"    {name}: {count}")

# 3. Check test log
print("\n[3] Hooks Test Log")
test_log = os.path.join(STATE_DIR, "hooks-test.log")
if os.path.exists(test_log):
    with open(test_log, "r") as f:
        lines = [l.strip() for l in f if l.strip()]
    print(f"  Total entries: {len(lines)}")
    if lines:
        print(f"  Last entry: {lines[-1]}")

# 4. Check for errors
print("\n[4] Error Check")
errors = []
for log_file in [debug_log, test_log]:
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            content = f.read().lower()
            if "error" in content or "traceback" in content or "exception" in content:
                errors.append(log_file)

if errors:
    print(f"  Warnings: Found errors in logs: {', '.join(errors)}")
else:
    print("  No errors found in logs")

# 5. Check key files exist
print("\n[5] Key Components")
key_files = [
    "summarizer_agent.py",
    "summarizer_daemon.py",
    "summarizer_daemon_launcher.py",
    "summarizer_trigger.py",
    "conversation_summarizer_agent.py",
    "conversation_recorder.py",
    "narratives_db.py",
    "session_start.py",
    "session_end.py",
    "stop.py",
    "subagent_start.py",
    "subagent_stop.py",
    "pre_tool_use.py",
    "post_tool_use.py",
    "post_tool_use_failure.py",
    "after_agent_response.py",
    "after_agent_thought.py",
    "before_shell_execution.py",
    "after_shell_execution.py",
    "before_mcp_execution.py",
    "after_mcp_execution.py",
    "before_read_file.py",
    "after_file_edit.py",
    "before_tab_file_read.py",
    "after_tab_file_edit.py",
    "before_submit_prompt.py",
    "pre_compact.py",
]
hooks_dir = os.path.dirname(__file__)
for f in key_files:
    path = os.path.join(hooks_dir, f)
    exists = os.path.exists(path)
    print(f"  {'OK' if exists else 'MISSING'}: {f}")

print("\n" + "=" * 60)
print("STATUS CHECK COMPLETE")
print("=" * 60)
