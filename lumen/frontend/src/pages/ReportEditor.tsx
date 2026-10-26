import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Play, Save, Sparkles, X } from "lucide-react";
import { api, emptySpec, QueryResult, QuerySpec, Report } from "../api/client";
import { PointClick } from "../components/Chart";
import { ResultPanel } from "../components/ResultPanel";
import { addToSpec, fieldMap, FieldList, SpecShelves, withAliases } from "../components/SpecBuilder";
import { Badge, Button, Card, Empty, ErrorBox, inputCls, Spinner, useToast } from "../components/ui";
import { useWs } from "./WorkspaceLayout";

export default function ReportEditor() {
  const { reportId } = useParams();
  const isNew = reportId === "new";
  const { ws, model, base, canEdit } = useWs();
  const loc = useLocation() as { state?: { spec?: QuerySpec; chart?: string; title?: string } };
  const nav = useNavigate();
  const toast = useToast();
  const [name, setName] = useState(loc.state?.title || "Untitled report");
  const [chartType, setChartType] = useState(loc.state?.chart || "bar");
  const [spec, setSpec] = useState<QuerySpec>(loc.state?.spec ? { ...emptySpec(), ...loc.state.spec } : emptySpec());
  const [res, setRes] = useState<QueryResult | null>(null);
  const [error, setError] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [loaded, setLoaded] = useState(isNew);
  const [autoChart, setAutoChart] = useState(isNew && !loc.state?.chart);
  const [saving, setSaving] = useState(false);
  const seq = useRef(0);
  const fm = useMemo(() => fieldMap(model), [model]);

  useEffect(() => {
    if (isNew) return;
    api.get<Report>(`/workspaces/${ws.id}/reports/${reportId}`).then((r) => {
      setName(r.name);
      setChartType(r.chart_type);
      setSpec({ ...emptySpec(), ...r.spec });
      setLoaded(true);
    }).catch(setError);
  }, [reportId, ws.id, isNew]);

  const aliased = useMemo(() => withAliases(spec, model), [spec, model]);

  useEffect(() => {
    if (!loaded) return;
    if (!spec.measures.length && !spec.dimensions.length) {
      setRes(null);
      return;
    }
    const my = ++seq.current;
    const t = setTimeout(async () => {
      setRunning(true);
      setError(null);
      try {
        const r = await api.post<QueryResult>(`/workspaces/${ws.id}/query`, aliased);
        if (my !== seq.current) return;
        setRes(r);
        if (autoChart) setChartType(r.suggested_chart);
      } catch (e) {
        if (my === seq.current) setError(e);
      } finally {
        if (my === seq.current) setRunning(false);
      }
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aliased, loaded]);

  const save = async (asNew = false) => {
    setSaving(true);
    try {
      const body = { name, chart_type: chartType, spec: aliased, options: {} };
      if (isNew || asNew) {
        const r = await api.post<Report>(`/workspaces/${ws.id}/reports`, body);
        toast("success", "Report saved");
        nav(`${base}/reports/${r.id}`, { replace: true });
      } else {
        await api.put(`/workspaces/${ws.id}/reports/${reportId}`, body);
        toast("success", "Report saved");
      }
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSaving(false);
    }
  };

  // drill: clicking a category filters to it; if the dimension is a month, drill into days of that month
  const onPoint = (p: PointClick) => {
    const dim = spec.dimensions.find((d) => (d.alias || "") === p.column.name) || spec.dimensions[0];
    if (!dim || p.value === null || p.value === undefined) return;
    if (p.column.type === "date" && dim.grain && dim.grain !== "day") {
      const d = new Date(String(p.value).slice(0, 10) + "T00:00:00");
      const end = new Date(d);
      if (dim.grain === "year") end.setFullYear(end.getFullYear() + 1);
      else if (dim.grain === "quarter") end.setMonth(end.getMonth() + 3);
      else if (dim.grain === "month") end.setMonth(end.getMonth() + 1);
      else end.setDate(end.getDate() + 7);
      end.setDate(end.getDate() - 1);
      const next = { year: "month", quarter: "month", month: "day", week: "day" }[dim.grain] || "day";
      const iso = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
      setSpec({ ...spec, time_range: { from: iso(d), to: iso(end) }, dimensions: spec.dimensions.map((x) => (x === dim ? { ...x, grain: next } : x)) });
      return;
    }
    if (dim.field === "@time") return;
    setSpec({ ...spec, filters: [...spec.filters.filter((f) => f.field !== dim.field), { field: dim.field, op: "in", value: [p.value] }] });
  };

  if (!loaded) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <div className="flex flex-col lg:h-[calc(100vh-40px)]">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link to={`${base}/reports`} className="text-slate-400 hover:text-slate-700"><ArrowLeft className="h-4 w-4" /></Link>
        <input className={inputCls + " max-w-md text-base font-semibold"} value={name} onChange={(e) => setName(e.target.value)} />
        {running && <Badge tone="blue">running…</Badge>}
        <div className="ml-auto flex gap-2">
          <Button onClick={() => { setAutoChart(true); setSpec({ ...spec }); }} title="Let Ellementry pick the best chart"><Sparkles className="h-4 w-4" /> Auto chart</Button>
          {canEdit && !isNew && <Button onClick={() => save(true)} loading={saving}>Save as copy</Button>}
          {canEdit && <Button variant="primary" onClick={() => save(false)} loading={saving}><Save className="h-4 w-4" /> Save</Button>}
        </div>
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[240px_330px_1fr]">
        <Card className="h-[340px] min-h-0 lg:h-auto" bodyClass="h-full p-3"><FieldList model={model} spec={spec} onAdd={(shelf, p) => setSpec(addToSpec(spec, model, shelf, p))} /></Card>
        <Card className="max-h-[520px] min-h-0 overflow-y-auto lg:max-h-none" bodyClass="p-3"><SpecShelves model={model} spec={aliased} onChange={(s) => setSpec(s)} /></Card>
        <Card className="min-h-0 overflow-y-auto" bodyClass="p-3">
          {spec.filters.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {spec.filters.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-800">
                  {fm.get(f.field)?.label || f.field} {f.op.replace("_", " ")} {Array.isArray(f.value) ? f.value.join(", ") : String(f.value ?? "")}
                  <button onClick={() => setSpec({ ...spec, filters: spec.filters.filter((_, j) => j !== i) })}><X className="h-3 w-3" /></button>
                </span>
              ))}
            </div>
          )}
          <ErrorBox error={error} />
          {!res && !error && (
            <Empty icon={<Play className="h-7 w-7" />} title="Build a visualization">
              Drag a metric or numeric field to <b>Measures</b> and a field to <b>Dimensions</b>. The chart updates live; click bars or points to drill down.
            </Empty>
          )}
          {res && <ResultPanel res={res} chartType={chartType} onChartType={(t) => { setAutoChart(false); setChartType(t); }} spec={aliased} title={name} wsId={ws.id} height={420} onPoint={onPoint} />}
        </Card>
      </div>
    </div>
  );
}
