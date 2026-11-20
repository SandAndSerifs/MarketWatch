"use client";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

function Markdown({ text }: { text: string }) {
  const blocks = text.split(/\n\n+/);
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
    p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith("`") ? <code key={i}>{p.slice(1, -1)}</code> : <span key={i}>{p}</span>);
  return (
    <div className="prose-kb">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*[*-]\s+/.test(l))) return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[*-]\s+/, ""))}</li>)}</ul>;
        if (lines.every((l) => /^\s*\d+\.\s+/.test(l))) return <ol key={i} className="list-decimal pl-5">{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*\d+\.\s+/, ""))}</li>)}</ol>;
        return <p key={i}>{inline(b)}</p>;
      })}
    </div>
  );
}

export default function Knowledge() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState("");
  const list = useApi<any>(`/api/knowledge?${query ? `q=${encodeURIComponent(query)}` : ""}${cat ? `&category=${encodeURIComponent(cat)}` : ""}`);
  const all = useApi<any>("/api/knowledge");
  const [slug, setSlug] = useState<string | null>(null);
  const doc = useApi<any>(slug ? `/api/knowledge/${slug}` : null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ title: "", category: "", body: "", source_title: "", source_authors: "", source_year: "", source_type: "educational", source_url: "" });
  const act = useAction();
  useEffect(() => { const id = setTimeout(() => setQuery(q), 250); return () => clearTimeout(id); }, [q]);
  useEffect(() => { if (!slug && list.data?.results?.length) setSlug(list.data.results[0].slug); }, [list.data, slug]);

  const add = async () => {
    const r = await act.run(() => post("/api/knowledge", {
      title: form.title, category: form.category, body: form.body, tags: [],
      sources: [{ title: form.source_title, authors: form.source_authors, year: Number(form.source_year), type: form.source_type, url: form.source_url || undefined, credibility: "user-provided" }],
    }));
    if (r) { setAdding(false); all.reload(); list.reload(); setSlug(r.slug); }
  };

  return (
    <div>
      <PageHeader title="Trading Knowledge Library" subtitle="Curated, original summaries of peer-reviewed research, regulator publications and established practitioner references, with authors, dates and source credibility. The AI analyst retrieves these passages (BM25 search) and cites them."
        right={<Button onClick={() => setAdding((a) => !a)}><Plus className="w-4 h-4" />Add document</Button>} />
      {adding && (
        <Card title="Add a document (a source is required)" className="mb-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Title"><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            <Field label="Category"><input list="cats" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
            <datalist id="cats">{(all.data?.categories || []).map((c: string) => <option key={c} value={c} />)}</datalist>
            <Field label="Source title"><input value={form.source_title} onChange={(e) => setForm({ ...form, source_title: e.target.value })} /></Field>
            <Field label="Source authors"><input value={form.source_authors} onChange={(e) => setForm({ ...form, source_authors: e.target.value })} /></Field>
            <Field label="Source year"><input value={form.source_year} onChange={(e) => setForm({ ...form, source_year: e.target.value })} /></Field>
            <Field label="Source type"><select value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value })}>{["peer-reviewed", "regulator", "exchange", "practitioner-book", "educational", "vendor-documentation"].map((t) => <option key={t}>{t}</option>)}</select></Field>
            <Field label="Source URL (optional)"><input value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} /></Field>
          </div>
          <Field label="Your notes (write in your own words; do not paste copyrighted text)"><textarea rows={6} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></Field>
          <ErrorBox error={act.error} />
          <Button variant="primary" className="mt-2" onClick={add} disabled={act.busy}>Save</Button>
        </Card>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Card title="Browse" pad={false} className="xl:col-span-1">
          <div className="p-3 flex flex-col gap-2 border-b border-line">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search (e.g. position sizing, failed breakout)…" />
            <select value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{(all.data?.categories || []).map((c: string) => <option key={c}>{c}</option>)}</select>
          </div>
          {list.error ? <div className="p-3"><ErrorBox error={list.error} /></div> : !list.data ? <Loading /> : list.data.results.length === 0 ? <Empty>No matches.</Empty> : (
            <ul className="divide-y divide-line max-h-[70vh] overflow-y-auto">{list.data.results.map((d: any) => (
              <li key={d.slug} onClick={() => setSlug(d.slug)} className={`px-3 py-2 cursor-pointer ${slug === d.slug ? "bg-accent/10" : "hover:bg-panel2"}`}>
                <div className="font-medium">{d.title}</div>
                <div className="text-[11px] text-mute flex gap-2"><span>{d.category}</span>{d.score != null && <span>score {d.score}</span>}{d.origin === "user" && <Badge color="sky">yours</Badge>}</div>
              </li>
            ))}</ul>
          )}
        </Card>
        <Card title={doc.data?.category || "Document"} className="xl:col-span-2">
          {!slug ? <Empty>Select a document.</Empty> : doc.error ? <ErrorBox error={doc.error} /> : !doc.data ? <Loading /> : (
            <article>
              <h2 className="text-lg font-semibold">{doc.data.title}</h2>
              <div className="flex flex-wrap gap-1 mt-1">{doc.data.tags.map((t: string) => <Badge key={t}>{t}</Badge>)}</div>
              <div className="mt-3"><Markdown text={doc.data.body} /></div>
              <div className="mt-4 border-t border-line pt-3">
                <div className="text-[11px] uppercase text-mute mb-1">Sources · updated {doc.data.updated_at}</div>
                <ul className="flex flex-col gap-1.5">{doc.data.sources.map((s: any, i: number) => (
                  <li key={i} className="text-[13px]">
                    <Badge color={s.type === "peer-reviewed" || s.type === "regulator" ? "green" : s.type === "practitioner-book" ? "blue" : "gray"}>{s.type}</Badge>{" "}
                    {s.authors} ({s.year}). <i>{s.title}</i>. {s.publisher} {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="text-accent">link</a>}
                    {s.credibility && <span className="text-mute"> · credibility: {s.credibility}</span>}
                  </li>
                ))}</ul>
              </div>
            </article>
          )}
        </Card>
      </div>
    </div>
  );
}
