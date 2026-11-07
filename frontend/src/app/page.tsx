import Link from "next/link";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

const workflow = [
  {
    title: "01 / Connect & debug",
    detail:
      "Import a complete cURL, inspect the parsed request and explicitly authorize a test call.",
    href: "/workspace/component-tests",
  },
  {
    title: "02 / Schedule evaluations",
    detail:
      "Plan bounded effect and performance runs outside peak hours. Effect outputs remain pending human review.",
    href: "/workspace/evaluation-schedules",
  },
  {
    title: "03 / Review & draft reports",
    detail:
      "Confirm AI-suggested fields, enter real results and assemble multiple components into one version-pinned draft.",
    href: "/workspace/reports",
  },
  {
    title: "04 / Configure working models",
    detail:
      "Administrators manage model credentials and assign the default agent and report advisor. More role pipelines are planned.",
    href: "/workspace/models",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen w-full overflow-x-clip bg-[#0a0a0a]">
      <Header locale={DEFAULT_LOCALE} />
      <main className="flex w-full flex-col">
        <Hero />
        <section
          aria-label="Evaluation workflow"
          className="mx-auto grid w-full max-w-6xl gap-5 px-5 pb-12 md:grid-cols-2"
        >
          {workflow.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-2xl border border-white/15 bg-white/5 p-6 transition-colors hover:bg-white/10"
            >
              <h2 className="mb-3 text-xl font-semibold">{item.title}</h2>
              <p className="text-muted-foreground text-sm leading-7">
                {item.detail}
              </p>
            </Link>
          ))}
          <p className="text-muted-foreground text-sm md:col-span-2">
            Evaluation workspace under active development. Report drafts are
            unverified; models cannot invent measurements or approve acceptance.
            Built on the DeerFlow framework, with upstream attribution
            preserved.
          </p>
        </section>
      </main>
      <Footer />
    </div>
  );
}
