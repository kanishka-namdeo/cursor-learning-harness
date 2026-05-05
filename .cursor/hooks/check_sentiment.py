import sqlite3

conn = sqlite3.connect('state/narratives.db')
conn.row_factory = sqlite3.Row

print("=== Archetype Distribution ===")
rows = conn.execute('SELECT archetype, COUNT(*) as cnt FROM session_arc_features GROUP BY archetype').fetchall()
for r in rows:
    print(f"  {r['archetype']}: {r['cnt']}")

total = conn.execute('SELECT COUNT(1) FROM session_arc_features').fetchone()[0]
print(f"\nTotal sessions analyzed: {total}")

meaningful = conn.execute("SELECT COUNT(1) FROM session_arc_features WHERE archetype NOT IN ('too_short', 'inconclusive', 'error')").fetchone()[0]
print(f"Meaningful archetypes: {meaningful}")

# Check some meaningful examples if they exist
print("\n=== Sample Meaningful Sessions ===")
rows = conn.execute("SELECT session_id, archetype, archetype_confidence, arc_slope, avg_sentiment FROM session_arc_features WHERE archetype NOT IN ('too_short', 'inconclusive', 'error') LIMIT 5").fetchall()
if rows:
    for r in rows:
        print(f"  {r['session_id'][:12]}... archetype={r['archetype']} confidence={r['archetype_confidence']} slope={r['arc_slope']} avg_sent={r['avg_sentiment']}")
else:
    print("  None found - all sessions are too_short/inconclusive/error")

# Check structured summaries with sentiment data
print("\n=== Structured Summaries with Sentiment ===")
rows = conn.execute("SELECT COUNT(1) as cnt FROM structured_summaries WHERE sentiment_archetype IS NOT NULL AND sentiment_archetype != '' AND sentiment_archetype NOT IN ('too_short', 'inconclusive', 'error')").fetchall()
print(f"  Summaries with meaningful sentiment: {rows[0]['cnt']}")

rows = conn.execute("SELECT COUNT(1) as cnt FROM structured_summaries WHERE sentiment_archetype IS NULL OR sentiment_archetype = ''").fetchall()
print(f"  Summaries with no sentiment data: {rows[0]['cnt']}")

# Check conversation structured summaries
print("\n=== Conversation Structured Summaries ===")
try:
    rows = conn.execute("SELECT dominant_archetype, COUNT(1) as cnt FROM conversation_structured_summaries GROUP BY dominant_archetype").fetchall()
    for r in rows:
        print(f"  {r['dominant_archetype']}: {r['cnt']}")
except:
    print("  Table not found or empty")

conn.close()
