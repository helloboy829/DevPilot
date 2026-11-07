import { notFound } from "next/navigation";
import { generateStaticParamsFor, importPage } from "nextra/pages";
import { cache } from "react";

import { isDocsLanguage, isDocsPath } from "@/components/docs/page-map";
import { useMDXComponents as getMDXComponents } from "@/mdx-components";

// eslint-disable-next-line @typescript-eslint/unbound-method
const Wrapper = getMDXComponents().wrapper;
type Props = { params: Promise<{ lang: string; mdxPath?: string[] }> };
const loadPage = cache(async (lang: string, mdxPath: string[]) => {
  if (!isDocsLanguage(lang) || !isDocsPath(mdxPath)) notFound();
  return importPage(mdxPath, lang);
});

export async function generateStaticParams() {
  const params = await generateStaticParamsFor("mdxPath", "lang")();
  return params.flatMap((param) => {
    if (typeof param.lang !== "string" || !isDocsLanguage(param.lang))
      return [];
    if (!Array.isArray(param.mdxPath)) return [];
    const mdxPath = param.mdxPath.filter(Boolean);
    return isDocsPath(mdxPath) ? [{ ...param, mdxPath }] : [];
  });
}

export async function generateMetadata({ params }: Props) {
  const { lang, mdxPath = [] } = await params;
  const { metadata } = await loadPage(lang, mdxPath);
  return metadata;
}

export default async function DocsPage({ params }: Props) {
  const { lang, mdxPath = [] } = await params;
  const {
    default: MDXContent,
    toc,
    metadata,
    sourceCode,
  } = await loadPage(lang, mdxPath);
  return (
    <Wrapper toc={toc} metadata={metadata} sourceCode={sourceCode}>
      <MDXContent params={{ lang, mdxPath }} />
    </Wrapper>
  );
}
