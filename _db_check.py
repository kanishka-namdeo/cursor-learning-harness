import sqlite3
conn = sqlite3.connect('.cursor/hooks/state/narratives.db')
cur = conn.cursor()
cur.execute("SELECT session_id, archetype, turn_count, arc_slope, avg_sentiment, model_used FROM session_arc_features ORDER BY analyzed_at DESC LIMIT 5")
rows = cur.fetchall()
print("=== session_arc_features (latest 5) ===")
for r in rows:
    sid = r[0][:16] + "..."
    print(f"  {sid} archetype={r[1]} turns={r[2]} slope={r[3]} avg_sent={r[4]} model={r[5]}")
cur.execute("SELECT total_sessions_analyzed, model_used, avg_arc_slope FROM arc_analysis_stats")
stats = cur.fetchall()
print("=== arc_analysis_stats ===")
for s in stats:
    print(f"  total={s[0]} model={s[1]} avg_slope={s[2]}")
conn.close()
