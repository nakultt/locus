import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

/**
 * Renders assistant output as Markdown.
 *
 * The agent writes Markdown — headings, lists, tables, fenced code — so a plain
 * <p> showed literal `**bold**` and pipe-delimited tables. Only assistant text
 * goes through this; user input stays plain so a message about Markdown does
 * not get silently reformatted.
 *
 * react-markdown does not use dangerouslySetInnerHTML and raw HTML is not
 * enabled, so model output cannot inject markup.
 */

const CodeBlock = ({ children }: { children: React.ReactNode }) => {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    // Pull text from the rendered node rather than tracking it separately.
    const text = extractText(children);
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="group relative my-3">
      <button
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy code"}
        className="absolute right-2 top-2 rounded-md border border-border bg-background/80 p-1.5 opacity-0 backdrop-blur transition group-hover:opacity-100 focus:opacity-100"
      >
        {copied ? (
          <Check size={13} className="text-green-500" />
        ) : (
          <Copy size={13} className="text-muted-foreground" />
        )}
      </button>
      <pre className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed">
        {children}
      </pre>
    </div>
  );
};

/** Recursively collect text from a React node tree. */
function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in node) {
    return extractText((node as { props: { children?: React.ReactNode } }).props.children);
  }
  return "";
}

const MarkdownMessage = memo(({ content }: { content: string }) => (
  <div className="text-sm leading-relaxed text-foreground">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Tight spacing: chat bubbles are not documents, so the default
        // prose margins leave too much air between short paragraphs.
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,

        h1: ({ children }) => (
          <h1 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-2 mt-3 text-sm font-semibold first:mt-0">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h3>
        ),

        ul: ({ children }) => (
          <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>
        ),
        li: ({ children }) => <li className="pl-0.5">{children}</li>,

        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            // noreferrer matters: links come from model output and may point
            // anywhere, so the target must not receive the referrer.
            rel="noopener noreferrer"
            className="text-primary underline underline-offset-2 hover:opacity-80"
          >
            {children}
          </a>
        ),

        code: ({ className, children }) => {
          // react-markdown marks fenced blocks with a language- class; inline
          // code has none.
          const isBlock = /language-/.test(className || "");
          if (isBlock) {
            return <code className={className}>{children}</code>;
          }
          return (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.8em]">
              {children}
            </code>
          );
        },
        pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,

        // Wide tables scroll inside their own container so the chat column
        // never scrolls sideways.
        table: ({ children }) => (
          <div className="my-3 overflow-x-auto">
            <table className="w-full border-collapse text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
        th: ({ children }) => (
          <th className="border border-border px-2 py-1.5 text-left font-medium">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border border-border px-2 py-1.5 align-top">{children}</td>
        ),

        blockquote: ({ children }) => (
          <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="my-3 border-border" />,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
      }}
    >
      {content}
    </ReactMarkdown>
  </div>
));

MarkdownMessage.displayName = "MarkdownMessage";

export default MarkdownMessage;
