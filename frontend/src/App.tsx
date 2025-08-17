import { useMemo, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";
import { downloadCSV } from "./lib/csv";

type TopLevel = {
  level: string;
  cycles: number;
  first_close_ns?: number | null;
  last_close_ns?: number | null;
  median_secs: number | null;
};

type Result = {
  symbol: string;
  step: string;
  spread: string;
  totals: Record<string, number>;
  top_levels: TopLevel[];
  start_iso: string;
  end_iso: string;
  rth: boolean;
  samples: number;
};

// ----------------- helpers -----------------
const API_BASE = import.meta.env.VITE_API_BASE || ""; // e.g. https://your-backend.onrender.com/api
const apiFetch = (path: string, qs: string) => fetch(`${API_BASE}${path}?${qs}`);
const apiPost = (path: string, body: BodyInit) => fetch(`${API_BASE}${path}`, { method: "POST", body });

// Use ET for date/time picking
const TZ = "America/New_York";

// ----------------- component -----------------
export default function App() {
  // tabs: "polygon" or "csv"
  const [mode, setMode] = useState<"polygon" | "csv">("polygon");

  // Shared params
  const [step, setStep] = useState("0.01");
  const [spread, setSpread] = useState("0.01");
  const [rth, setRth] = useState(true);
  const [exactOnly, setExactOnly] = useState(true);
  const [levelMin, setLevelMin] = useState<string>(""); // optional
  const [levelMax, setLevelMax] = useState<string>(""); // optional

  // Result
  const [data, setData] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);

  // ---------------- Polygon tab state ----------------
  const [symbol, setSymbol] = useState("LCID");
  const [startDate, setStartDate] = useState<string>(""); // "YYYY-MM-DD"
  const [endDate, setEndDate] = useState<string>("");     // "YYYY-MM-DD"
  const [startTime, setStartTime] = useState<string>(""); // optional "HH:MM" (24h)
  const [endTime, setEndTime] = useState<string>("");     // optional "HH:MM"

  const runPolygon = async () => {
    if (!startDate || !endDate) {
      alert("Pick start and end dates (ET).");
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({
        symbol,
        start_date: startDate,
        end_date: endDate,
        tz: TZ,
        step,
        spread,
        rth: String(rth),
        exact_only: String(exactOnly),
      });
      if (startTime) params.set("start_time", startTime);
      if (endTime) params.set("end_time", endTime);
      if (levelMin) params.set("level_min", levelMin);
      if (levelMax) params.set("level_max", levelMax);

      const res = await apiFetch("/api/backtest", params.toString());
      if (!res.ok) throw new Error(await res.text());
      const json: Result = await res.json();
      setData(json);
    } catch (e) {
      alert(String(e));
    } finally {
      setLoading(false);
    }
  };

  // ---------------- CSV tab state ----------------
  const [csvSymbol, setCsvSymbol] = useState("TEST");
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const runCSV = async () => {
    if (!csvFile) return;
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", csvFile);
      fd.append("symbol", csvSymbol);
      fd.append("step", step);
      fd.append("spread", spread);
      fd.append("rth", String(rth));
      fd.append("exact_only", String(exactOnly));
      if (levelMin) fd.append("level_min", levelMin);
      if (levelMax) fd.append("level_max", levelMax);

      const res = await apiPost("/api/backtest_csv", fd);
      if (!res.ok) throw new Error(await res.text());
      const json: Result = await res.json();
      setData(json);
    } catch (e) {
      alert(String(e));
    } finally {
      setLoading(false);
    }
  };

  // ---------------- shared outputs ----------------
  const chartData = useMemo(
    () => (data ? Object.entries(data.totals).map(([level, cycles]) => ({ level, cycles })) : []),
    [data]
  );

  const exportLocal = () => {
    if (!data) return;
    const rows = Object.entries(data.totals).map(([level, cycles]) => ({ level, cycles }));
    const modeTag = exactOnly ? "exact" : "cross";
    const band = (levelMin || levelMax) ? `_band_${levelMin || ""}-${levelMax || ""}` : "";
    downloadCSV(`${data.symbol}_${data.step}_${data.spread}_${modeTag}${band}.csv`, rows);
  };

  const exportServer = async () => {
    if (!data) return;
    if (mode !== "polygon") return; // export from server only for Polygon (uses Polygon data)
    if (!startDate || !endDate) return;

    const params = new URLSearchParams({
      symbol,
      start_date: startDate,
      end_date: endDate,
      tz: TZ,
      step,
      spread,
      rth: String(rth),
      exact_only: String(exactOnly),
    });
    if (startTime) params.set("start_time", startTime);
    if (endTime) params.set("end_time", endTime);
    if (levelMin) params.set("level_min", levelMin);
    if (levelMax) params.set("level_max", levelMax);

    const res = await apiFetch("/api/export", params.toString());
    const text = await res.text();
    const blob = new Blob([text], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const modeTag = exactOnly ? "exact" : "cross";
    const band = (levelMin || levelMax) ? `_band_${levelMin || ""}-${levelMax || ""}` : "";
    a.href = url;
    a.download = `${symbol}_${step}_${spread}_${modeTag}${band}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const canRunPolygon = !!startDate && !!endDate && !loading;
  const canRunCSV = !!csvFile && !loading;

  return (
    <div className="min-h-screen p-6 bg-gray-50 text-gray-900">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-baseline justify-between">
          <h1 className="text-3xl font-bold">Grid Cycle Backtester</h1>
          {data && (
            <div className="text-sm opacity-70">
              {data.symbol} · step {data.step} · spread {data.spread} · ticks {data.samples.toLocaleString()}
            </div>
          )}
        </header>

        {/* Tabs */}
        <div className="bg-white rounded-2xl shadow p-2 flex gap-2">
          <button
            className={`px-4 py-2 rounded ${mode === "polygon" ? "bg-black text-white" : "bg-gray-100"}`}
            onClick={() => setMode("polygon")}
          >
            Polygon
          </button>
          <button
            className={`px-4 py-2 rounded ${mode === "csv" ? "bg-black text-white" : "bg-gray-100"}`}
            onClick={() => setMode("csv")}
          >
            Upload CSV
          </button>
        </div>

        {/* Forms */}
        {mode === "polygon" ? (
          <div className="grid md:grid-cols-12 gap-3 items-end bg-white rounded-2xl shadow p-4">
            <div className="md:col-span-2">
              <label className="block text-sm">Symbol</label>
              <input className="w-full border rounded p-2" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm">Start date (ET)</label>
              <input type="date" className="w-full border rounded p-2" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm">End date (ET)</label>
              <input type="date" className="w-full border rounded p-2" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm">Start time (ET, optional)</label>
              <input
                type="time"
                className="w-full border rounded p-2"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm">End time (ET, optional)</label>
              <input
                type="time"
                className="w-full border rounded p-2"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
            </div>

            <div className="md:col-span-1">
              <label className="block text-sm">Step</label>
              <select className="w-full border rounded p-2" value={step} onChange={(e) => setStep(e.target.value)}>
                <option>0.01</option>
                <option>0.05</option>
              </select>
            </div>

            <div className="md:col-span-1">
              <label className="block text-sm">Spread</label>
              <select className="w-full border rounded p-2" value={spread} onChange={(e) => setSpread(e.target.value)}>
                <option>0.01</option>
                <option>0.05</option>
              </select>
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm">From $ (base ≥)</label>
              <input
                className="w-full border rounded p-2"
                type="number"
                step="0.01"
                placeholder="e.g. 2.21"
                value={levelMin}
                onChange={(e) => setLevelMin(e.target.value)}
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm">To $ (base ≤)</label>
              <input
                className="w-full border rounded p-2"
                type="number"
                step="0.01"
                placeholder="e.g. 2.24"
                value={levelMax}
                onChange={(e) => setLevelMax(e.target.value)}
              />
            </div>

            <label className="inline-flex items-center space-x-2 ml-2">
              <input type="checkbox" checked={rth} onChange={(e) => setRth(e.target.checked)} />
              <span>RTH only (09:30–16:00 ET)</span>
            </label>

            <label className="inline-flex items-center space-x-2 ml-2">
              <input type="checkbox" checked={exactOnly} onChange={(e) => setExactOnly(e.target.checked)} />
              <span>Exact prints only</span>
            </label>

            <div className="md:col-span-12 flex gap-2">
              <button onClick={runPolygon} disabled={!canRunPolygon} className="bg-black text-white rounded px-4 py-2">
                {loading ? "Running..." : "Run"}
              </button>
              <button onClick={exportLocal} disabled={!data} className="border rounded px-4 py-2">
                Export CSV (client)
              </button>
              <button onClick={exportServer} disabled={!data} className="border rounded px-4 py-2">
                Export CSV (server)
              </button>
            </div>
          </div>
        ) : (
          <div className="grid md:grid-cols-8 gap-3 items-end bg-white rounded-2xl shadow p-4">
            <div className="md:col-span-2">
              <label className="block text-sm">CSV Symbol label</label>
              <input className="w-full border rounded p-2" value={csvSymbol} onChange={(e) => setCsvSymbol(e.target.value)} />
            </div>

            <div className="md:col-span-3">
              <label className="block text-sm">Upload CSV</label>
              <input
                type="file"
                accept=".csv,text/csv"
                className="w-full border rounded p-2 bg-white"
                onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
              />
              <p className="text-xs opacity-70 mt-1">
                Columns expected: <code>participant_timestamp_ns</code> (or ISO time) and <code>price</code>.
              </p>
            </div>

            <div className="md:col-span-1">
              <label className="block text-sm">Step</label>
              <select className="w-full border rounded p-2" value={step} onChange={(e) => setStep(e.target.value)}>
                <option>0.01</option>
                <option>0.05</option>
              </select>
            </div>

            <div className="md:col-span-1">
              <label className="block text-sm">Spread</label>
              <select className="w-full border rounded p-2" value={spread} onChange={(e) => setSpread(e.target.value)}>
                <option>0.01</option>
                <option>0.05</option>
              </select>
            </div>

            <div className="md:col-span-1">
              <label className="block text-sm">From $ (base ≥)</label>
              <input
                className="w-full border rounded p-2"
                type="number"
                step="0.01"
                placeholder="e.g. 2.99"
                value={levelMin}
                onChange={(e) => setLevelMin(e.target.value)}
              />
            </div>

            <div className="md:col-span-1">
              <label className="block text-sm">To $ (base ≤)</label>
              <input
                className="w-full border rounded p-2"
                type="number"
                step="0.01"
                placeholder="e.g. 3.00"
                value={levelMax}
                onChange={(e) => setLevelMax(e.target.value)}
              />
            </div>

            <label className="inline-flex items-center space-x-2 ml-2">
              <input type="checkbox" checked={rth} onChange={(e) => setRth(e.target.checked)} />
              <span>RTH only (09:30–16:00 ET)</span>
            </label>

            <label className="inline-flex items-center space-x-2 ml-2">
              <input type="checkbox" checked={exactOnly} onChange={(e) => setExactOnly(e.target.checked)} />
              <span>Exact prints only</span>
            </label>

            <div className="md:col-span-8 flex gap-2">
              <button onClick={runCSV} disabled={!canRunCSV} className="bg-black text-white rounded px-4 py-2">
                {loading ? "Running..." : "Run on CSV"}
              </button>
              <button onClick={exportLocal} disabled={!data} className="border rounded px-4 py-2">
                Export CSV (client)
              </button>
            </div>
          </div>
        )}

        {/* Output */}
        {data && (
          <>
            <div className="bg-white rounded-2xl shadow p-4">
              <h2 className="text-xl font-semibold mb-2">Cycles per Price Level</h2>
              <div className="w-full h-96">
                <ResponsiveContainer>
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="level" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="cycles" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-sm mt-2 opacity-70">
                Window: {data.start_iso} → {data.end_iso} · RTH {data.rth ? "on" : "off"}
              </p>
            </div>

            <div className="bg-white rounded-2xl shadow p-4">
              <h2 className="text-xl font-semibold mb-2">Top Oscillating Levels</h2>
              <table className="w-full text-sm">
                <thead className="text-left">
                  <tr>
                    <th className="p-2">Level</th>
                    <th className="p-2">Cycles</th>
                    <th className="p-2">Median secs</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_levels.map((r, i) => (
                    <tr key={i} className="odd:bg-gray-50">
                      <td className="p-2">{r.level}</td>
                      <td className="p-2">{r.cycles}</td>
                      <td className="p-2">{r.median_secs ?? "NA"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
