from pathlib import Path


repository_root = Path(__file__).resolve().parents[2]
screen = (repository_root / "threat-intelligence-dashboard/src/prototype/screens/monitoring.html").read_text(
    encoding="utf-8"
)
runtime = (repository_root / "threat-intelligence-dashboard/src/prototype/dataRuntime.js").read_text(
    encoding="utf-8"
)
styles = (repository_root / "threat-intelligence-dashboard/src/prototype/styles.css").read_text(
    encoding="utf-8"
)

for marker in (
    'data-code-scan-panel',
    'data-code-scan-watchlist',
    'data-code-scan-toggle',
    '默认每 1 小时',
):
    assert marker in screen, f"missing continuous-scan UI marker: {marker}"

for marker in (
    '/api/code-monitoring/continuous-status',
    '/api/code-monitoring/continuous/start',
    '/api/code-monitoring/continuous/stop',
    'CODE_CONTINUOUS_INTERVAL_SECONDS = 3600',
    '/api/code-monitoring/hits/page',
    'last_success_at',
):
    assert marker in runtime, f"missing continuous-scan runtime binding: {marker}"

assert '.code-scan-panel' in styles
assert screen.count('data-server-pagination="true"') >= 2
for field in ("watchlist_id", "platform", "severity", "result_layer", "recent_hours", "query"):
    assert f'data-code-hit-filter="{field}"' in screen

print("New UI continuous code monitoring controls are wired.")
