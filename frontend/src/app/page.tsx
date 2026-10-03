"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

const steps = [
  ["1. Report", "Tell us what you lost or found on or around UET Lahore campus: a photo, a few details, where and when."],
  ["2. AI matching", "LostLink AI compares appearance, description, colour, brand, place and time across reports."],
  ["3. Verify", "Possible owners answer private questions. The finder, who holds the item, confirms."],
  ["4. Recover", "Only then can you chat in the app to arrange the handover. No phone numbers or emails shared."],
];

export default function Landing() {
  const { user } = useAuth();
  return (
    <div className="space-y-16">
      <section className="grid items-center gap-10 pt-6 md:grid-cols-2">
        <div>
          <p className="mb-3 inline-block rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
            Lost &amp; found for the UET Lahore community, assisted by AI
          </p>
          <h1 className="text-4xl font-extrabold leading-tight text-slate-900 md:text-5xl">
            Lost something? <br />
            <span className="text-brand-600">Let&apos;s find it together.</span>
          </h1>
          <p className="mt-4 text-lg text-slate-600">
            LostLink AI looks through found-item reports for you, explains why something might be yours, and
            connects you with the finder safely once you have proven it is yours.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href={user ? "/report/lost" : "/register?next=/report/lost"} className="btn-primary px-6 py-3 text-base">
              I lost something
            </Link>
            <Link href={user ? "/report/found" : "/register?next=/report/found"} className="btn-secondary px-6 py-3 text-base">
              I found something
            </Link>
          </div>
        </div>
        <div className="card space-y-3 bg-gradient-to-br from-white to-brand-50">
          <p className="text-sm font-semibold text-slate-500">Example match</p>
          <div className="flex items-center justify-between">
            <span className="font-semibold">Black backpack</span>
            <span className="rounded-full bg-emerald-600 px-3 py-1 text-sm font-semibold text-white">87% relevance</span>
          </div>
          <ul className="space-y-1 text-sm text-slate-600">
            <li>✓ Same item category</li>
            <li>✓ Compatible colour (black)</li>
            <li>✓ Found about 60 m from where it was lost, on UET campus</li>
            <li>✓ Found approximately 30 minutes later</li>
            <li>✓ Similar distinctive feature (red keychain)</li>
          </ul>
          <p className="text-xs text-slate-500">A potential match is not proof of ownership. Verification comes next.</p>
        </div>
      </section>

      <section>
        <h2 className="mb-6 text-2xl font-bold text-slate-900">How it works</h2>
        <div className="grid gap-4 md:grid-cols-4">
          {steps.map(([t, d]) => (
            <div key={t} className="card">
              <h3 className="font-semibold text-slate-900">{t}</h3>
              <p className="mt-2 text-sm text-slate-600">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="card grid gap-6 md:grid-cols-3">
        {[
          ["Private by default", "Your contact details are never shown. Photos are only visible to signed-in users."],
          ["Humans decide", "AI suggests and explains. People verify ownership before anything is shared."],
          ["Your data stays yours", "Reports are not used to train AI models."],
        ].map(([t, d]) => (
          <div key={t}>
            <h3 className="font-semibold text-slate-900">{t}</h3>
            <p className="mt-1 text-sm text-slate-600">{d}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
