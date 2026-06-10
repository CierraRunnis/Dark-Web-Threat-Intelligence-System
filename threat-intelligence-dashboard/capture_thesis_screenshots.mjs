import fs from "node:fs";
import path from "node:path";

const { chromium } = await import("playwright");

const OUT_DIR = "D:/luwen/thesis_assets";
fs.mkdirSync(OUT_DIR, { recursive: true });

const baseUrl = "http://127.0.0.1:5173";
const apiBase = "http://127.0.0.1:8000";

const apiPayload = await fetch(`${apiBase}/api/intelligence`).then((r) => r.json());
const detailId =
  apiPayload?.dataLeakEvents?.[0]?.id ||
  apiPayload?.ransomwareEvents?.[0]?.id ||
  apiPayload?.vulnerabilityEvents?.[0]?.id;

const shots = [
  { name: "ch6_5_dashboard.png", route: "/" },
  { name: "ch6_6_data_leak.png", route: "/data-leak" },
  { name: "ch6_7_ransomware.png", route: "/ransomware" },
  { name: "ch6_8_vulnerability.png", route: "/vulnerability-alerts" },
  { name: "ch6_9_event_detail.png", route: `/event/${detailId}` },
  { name: "ch6_10_collector_control.png", route: "/collector-control" },
  { name: "ch6_11_threat_situation.png", route: "/threat-situation" },
];

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1200 },
  deviceScaleFactor: 1.25,
});

for (const shot of shots) {
  await page.goto(`${baseUrl}${shot.route}`, { waitUntil: "networkidle" });
  await page.screenshot({
    path: path.join(OUT_DIR, shot.name),
    fullPage: true,
  });
}

await browser.close();
console.log(JSON.stringify({ outDir: OUT_DIR, detailId, shots }, null, 2));
