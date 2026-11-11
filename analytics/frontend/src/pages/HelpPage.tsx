import type { ReactNode } from "react";
import { Card } from "../components/ui";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card title={title}>
      <div className="space-y-2 text-sm leading-relaxed text-slate-700">{children}</div>
    </Card>
  );
}

/** A short user guide for employees (Phase 8): what the app shows, how to ask the assistants, and their limits. */
export default function HelpPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-6 py-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">How to use Ellementry Analytics</h1>
        <p className="mt-1 text-sm text-slate-500">A five-minute guide. The figures come from the company's data warehouse, refreshed after each data load; every page says the date its data runs to.</p>
      </div>

      <Section title="Dashboards">
        <p><b>Dashboards</b> answer the regular questions: sales, stock, purchasing, fulfilment, returns. Change the period or other filters at the top; click a bar or a row to drill into it. A small note on a tile means a known data issue affects it: hover over it to read what and why.</p>
        <p>"<b>Worth a look</b>" lines point to a month or a change that stands out. They are worked out from the data, not written by AI.</p>
      </Section>

      <Section title="Asking a question">
        <p>On <b>Ask AI</b>, type a question in plain words: "net sales by channel last month", "which products sold most at Bagru in September", "returns this year against last year". The answer shows the numbers, the table behind them and how they were worked out.</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>Name the period, the place or the product when it matters; otherwise the assistant uses the dashboard's own defaults and says which.</li>
          <li>Every number in an answer is checked against the data. If one can't be traced, the answer says so; treat it with care.</li>
          <li>Use 👍 or 👎 under an answer. A 👎 with a short note ("wrong month", "should exclude GST") goes to the administrators with everything needed to fix it.</li>
        </ul>
      </Section>

      <Section title="The assistants (where switched on for you)">
        <ul className="list-disc space-y-1 pl-5">
          <li><b>Dashboard chat</b>: the chat button on a dashboard answers about what is on screen, with your filters.</li>
          <li><b>Memory</b>: say "remember that…" to keep a preference or a decision for later conversations. You can see, change or delete everything remembered on the <b>Memory</b> page. Your personal memories are never shown to anyone else.</li>
          <li><b>Alerts</b>: the warehouse checks for stock-outs, low cover and overdue purchase orders after each data load. You decide each alert (acknowledge or dismiss, with a note); the assistant only explains them.</li>
        </ul>
      </Section>

      <Section title="What the assistants can't do">
        <ul className="list-disc space-y-1 pl-5">
          <li>They can't change any data, place orders or decide an alert for you: they only read and explain.</li>
          <li>They only see the dashboards and data you can see yourself.</li>
          <li>They know the data up to the last load, not what happened today in the ERP or the stores.</li>
          <li>There is a limit of a few questions a minute and a daily spending limit per person. If you reach one, wait a little; the free offline answers still work.</li>
        </ul>
      </Section>

      <Section title="Privacy">
        <p>Questions, answers and your 👍/👎 are kept so the team can improve the assistants; administrators can see who asked what and when. Don't type passwords, bank details or customers' personal details into a question. To be answered, a question and the data it needs are sent to Anthropic's Claude.</p>
      </Section>

      <Section title="When something looks wrong">
        <p>Check the date the data runs to and the filters first. If a figure still looks wrong, mark the answer 👎 with a note, or tell an administrator which dashboard and tile. Known problems are listed on the <b>Data issues</b> page.</p>
      </Section>
    </div>
  );
}
