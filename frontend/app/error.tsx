"use client";

import { useEffect } from "react";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return <main className="mx-auto flex min-h-[70vh] max-w-7xl items-center px-5 py-12 sm:px-8"><section className="surface mx-auto max-w-md rounded-3xl p-8 text-center"><span className="mx-auto grid size-11 place-items-center rounded-2xl bg-indigo-50 text-lg font-semibold text-indigo-600">S</span><h1 className="mt-5 text-xl font-semibold tracking-[-.03em] text-slate-900">Unable to load this page</h1><p className="mt-3 text-sm leading-6 text-slate-600">The service may be temporarily unavailable. Please try again.</p><button type="button" onClick={reset} className="mt-6 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2">Try again</button></section></main>;
}
