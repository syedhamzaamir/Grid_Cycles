import { useEffect, useMemo, useState } from "react";
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

function msToNsString(ms: number) {
  return (BigInt(ms) * 1_000_000n).toString();
}

// Accept both "YYYY-MM-DD" (date input value) and "dd/mm/yyyy" (typed string)
function parseDateToMs(s: string): number | null {
  if (!s) return null;

  // Native <input type="date"> value
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const t = Date.parse(`${s}T00:00:00.000Z`);
    return Number.isNaN(t) ? null : t;
  }

  // dd/mm/yyyy or dd-mm-yyyy
  const m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
  if (m) {
    const dd = m[1].padStart(2, "0");
    const mm = m[2].padStart(2, "0");
    const yyyy = m[3];
    const iso = `${yyyy}-${mm}-${dd}`;
    const t = Date.parse(`${iso}T00:00:00.000Z`);
    return Number.isNaN(t) ? null : t;
  }

  return null;
}

// ----------------- component -----------------
export default function App() {
  const [symbol, setSymbol] = useState("LCID");

  // Date pickers (UTC)
  const [startDate, setStartDate] = useState<string>(""); // accepts YYYY-MM-DD or dd/mm/yyyy
  const [endDate, setEndDate] = useState<string>("");
  const [useFullDays, setUseFullDays] = useState<boolean>(true);

  // Derived ns
  const [startNs, setStartNs] = useState("");
  const [endNs, setEndNs] = useState("");

  // Params
  const [step, setStep] = useState("0.01");
  const [spread, setSpread] = useState("0.01");
  const [rth, setRth] = useState(true);
  const [exactOnly, setExactOnly] = useState(true);
  const [levelMin, setLevelMin] = useState<string>(""); // e.g., 2.21
  const [levelMax, setLevelMax] = useState<string>(""); // e.g., 2.24

  // Results
  const [data, setData] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [dateError, setDateError] = useState<string>("");

  // Auto-fill ns when dates change and full-day mode is on
  useEffect(() => {
    if (!useFullDays) return;

    const sMs = parseDateToMs(startDate);
    const eMs = parseDateToMs(endDate);

    if (!sMs || !eMs) {
      setStartNs("");
      setEndNs("");
      setDateError(startDate || endDate ? "Pick valid dates (YYYY-MM-DD or dd/mm/yyyy)" : "");
      return;
    }
    if (eMs < sMs) {
      setStartNs("");
      setEndNs("");
      setDateError("End date must be on/after start date");
      return;
    }

    setDateError("");

    // End date treated as a whole day → add 24h to make it exclusive window
    const endMsExclusive = eMs + 24 * 60 * 60 * 1000;

    setStartNs(msToNsString(sMs));
    setEndNs(msToNsString(endMsExclusive));
  }, [startDate, endDate, useFullDays]);

  const run = async () => {
    if (!startNs || !endNs) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        symbol,
        start_ns: startNs,
        end_ns: endNs,
        step,
        spread,
        rth: String(rth),
        exact_only: String(exactOnly),
      });
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

  const chartData = useMemo(
    () => (data ? Object.entries(data.totals).map(([level, cycles]) => ({ level, cycles })) : []),
    [data]
  );

  const exportLocal = () => {
    if (!data) return;
    const rows = Object.entries(data.totals).map(([level, cycles]) => ({ level, cycles }));
    const mode = exactOnly ? "exact" : "cross";
    const band = (levelMin || levelMax) ? `_band_${levelMin || ""}-${levelMax || ""}` : "";
    downloadCSV(`${data.symbol}_${data.step}_${data.spread}_${mode}${band}.csv`, rows);
  };

  const exportServer = async () => {
    if (!data) return;
    const params = new URLSearchParams({
      symbol,
      start_ns: startNs,
      end_ns: endNs,
      step,
      spread,
      rth: String(rth),
      exact_only: String(exactOnly),
    });
    if (levelMin) params.set("level_min", levelMin);
    if (levelMax) params.set("level_max", levelMax);

    const res = await apiFetch("/api/export", params.toString());
    const text = await res.text();
    const blob = new Blob([text], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const mode = exactOnly ? "exact" : "cross";
    const band = (levelMin || levelMax) ? `_band_${levelMin || ""}-${levelMax || ""}` : "";
    a.href = url;
    a.download = `${symbol}_${step}_${spread}_${mode}${band}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const canRun = !!startNs && !!endNs && !loading;

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

        <div className="grid md:grid-cols-8 gap-3 items-end bg-white rounded-2xl shadow p-4">
          <div className="md:col-span-1">
            <label className="block text-sm">Symbol</label>
            <input
              className="w-full border rounded p-2"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </div>

          {/* Start / End dates (UTC). Type 'date' works; free-typed dd/mm/yyyy is also parsed. */}
          <div className="md:col-span-2">
            <label className="block text-sm">Start date (UTC)</label>
            <input
              type="date"
              className="w-full border rounded p-2"
              placeholder="dd/mm/yyyy"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>

          <div className="md:col-span-2">
            <label className="block text-sm">End date (UTC)</label>
            <input
              type="date"
              className="w-full border rounded p-2"
              placeholder="dd/mm/yyyy"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
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

          <div className="md:col-span-1">
            <label className="block text-sm">From $ (base ≥)</label>
            <input
              className="w-full border rounded p-2"
              type="number"
              step="0.01"
              placeholder="2.21"
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
              placeholder="2.24"
              value={levelMax}
              onChange={(e) => setLevelMax(e.target.value)}
            />
          </div>

          <label className="inline-flex items-center space-x-2 ml-2">
            <input type="checkbox" checked={rth} onChange={(e) => setRth(e.target.checked)} />
            <span>RTH only (09:30–16:00 ET)</span>
          </label>

          <label className="inline-flex items-center space-x-2 ml-2">
            <input type="checkbox" checked={useFullDays} onChange={(e) => setUseFullDays(e.target.checked)} />
            <span>Use full days</span>
          </label>

          <label className="inline-flex items-center space-x-2 ml-2">
            <input type="checkbox" checked={exactOnly} onChange={(e) => setExactOnly(e.target.checked)} />
            <span>Exact prints only</span>
          </label>

          <div className="md:col-span-8 flex gap-2">
            <button onClick={run} disabled={!canRun} className="bg-black text-white rounded px-4 py-2">
              {loading ? "Running..." : "Run"}
            </button>
            <button onClick={exportLocal} disabled={!data} className="border rounded px-4 py-2">
              Export CSV (client)
            </button>
            <button onClick={exportServer} disabled={!data} className="border rounded px-4 py-2">
              Export CSV (server)
            </button>
          </div>

          {/* Feedback */}
          <div className="md:col-span-8 text-xs">
            {useFullDays && (
              <div className="opacity-70">ns window: start={startNs || "—"} end={endNs || "—"}</div>
            )}
            {dateError && <div className="text-red-600">{dateError}</div>}
          </div>
        </div>

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
