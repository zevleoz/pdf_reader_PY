import * as React from 'react';
function inline(text: string): React.ReactNode { return text.split(/(\*\*[^*]+\*\*)/g).map((s, i) => s.startsWith('**') ? <strong key={i}>{s.slice(2, -2)}</strong> : s); }
/** All source content stays in React text nodes, including HTML-looking names. */
export default function Markdown({ text }: {
  text: string;
}) {
  const lines = text.split('\n');
  const nodes: React.ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line)
      continue;
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const legacy = line.match(/^\*\*(.+?)\*\*(（.*）)?$/);
    if (heading || legacy) {
      const Tag = heading ? (`h${heading[1].length}` as 'h1' | 'h2' | 'h3') : 'h2';
      nodes.push(<Tag key={i} className="mt-5 font-bold text-lg">{inline(heading ? heading[2] : legacy![1] + (legacy![2] || ''))}</Tag>);
    }
    else if (/^[-=━]{3,}$/.test(line))
      nodes.push(<hr key={i} className="border-line" />);
    else if (/^(?:[-•·*]|\d+[.)])\s+/.test(line)) {
      const start = i;
      const ordered = /^\d/.test(line);
      const items: React.ReactNode[] = [];
      while (i < lines.length && (ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-•·*]\s+/).test(lines[i])) {
        let value = lines[i].replace(/^\s*(?:[-•·*]|\d+[.)])\s+/, '');
        value = value.replace(/^\[([xX ])\]\s*/, (_, c: string) => c.trim() ? '☑ ' : '☐ ');
        items.push(<li key={i}>{inline(value)}</li>);
        i++;
      }
      i--;
      nodes.push(ordered ? <ol key={start} className="list-decimal pl-6">{items}</ol> : <ul key={start} className="list-disc pl-6">{items}</ul>);
    }
    else if (line.startsWith('>'))
      nodes.push(<blockquote key={i} className="border-l-2 border-ink pl-3">{inline(line.slice(1).trim())}</blockquote>);
    else
      nodes.push(<p key={i} className="whitespace-pre-wrap">{inline(line)}</p>);
  }
  return <div className="space-y-3 break-words">{nodes}</div>;
}
