"use client";

import "@/styles/rich-html.css";

import { useMemo } from "react";

import { extractCitationSources } from "@/core/citations/sources";
import {
  SafeStreamdown,
  toStreamdownComponents,
} from "@/core/streamdown/components";

import { ArtifactLink } from "../citations/artifact-link";
import { CitationSourcesPanel } from "../citations/citation-sources-panel";

import { artifactMarkdownPlugins } from "./markdown-preview-plugins";

export default function ArtifactMarkdownPreview({
  content,
}: {
  content: string;
}) {
  const citationSources = useMemo(
    () => extractCitationSources(content),
    [content],
  );
  return (
    <div className="size-full overflow-auto px-4 py-3">
      <SafeStreamdown
        className="min-w-0"
        {...artifactMarkdownPlugins}
        components={toStreamdownComponents({ a: ArtifactLink })}
      >
        {content}
      </SafeStreamdown>
      <CitationSourcesPanel sources={citationSources} className="mb-4" />
    </div>
  );
}
