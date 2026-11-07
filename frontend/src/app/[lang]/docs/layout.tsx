import "katex/dist/katex.min.css";
import "nextra-theme-docs/style.css";

import { notFound } from "next/navigation";
import { getPageMap } from "nextra/page-map";
import { Layout } from "nextra-theme-docs";
import type { ReactNode } from "react";

import {
  isDocsLanguage,
  localizeDocsPageMap,
} from "@/components/docs/page-map";
import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";

type Props = { children: ReactNode; params: Promise<{ lang: string }> };

export default async function DocsLayout({ children, params }: Props) {
  const { lang } = await params;
  if (!isDocsLanguage(lang)) notFound();
  const pageMap = localizeDocsPageMap(await getPageMap(`/${lang}`), lang);
  return (
    <Layout
      navbar={
        <Header
          className="relative max-w-full px-10"
          homeURL="/"
          locale={lang === "zh" ? "zh-CN" : "en-US"}
        />
      }
      pageMap={pageMap}
      sidebar={{ defaultOpen: true }}
      docsRepositoryBase="https://github.com/helloboy829/DevPilot/tree/main/frontend"
      feedback={{ link: "https://github.com/helloboy829/DevPilot/issues/new" }}
      footer={<Footer />}
    >
      {children}
    </Layout>
  );
}
