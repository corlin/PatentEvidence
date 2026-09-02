import React from 'react'

interface MarkdownViewerProps {
  content?: string | null
  className?: string
}

function renderInline(text: string): React.ReactNode[] {
  // Regex to match **bold**, `code`, and plain text
  const parts: React.ReactNode[] = []
  let remaining = text

  while (remaining.length > 0) {
    // Check **bold**
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/)
    const codeMatch = remaining.match(/`([^`]+)`/)

    let earliestIndex = remaining.length
    let matchType: 'bold' | 'code' | null = null
    let currentMatch: RegExpMatchArray | null = null

    if (boldMatch && boldMatch.index !== undefined && boldMatch.index < earliestIndex) {
      earliestIndex = boldMatch.index
      matchType = 'bold'
      currentMatch = boldMatch
    }
    if (codeMatch && codeMatch.index !== undefined && codeMatch.index < earliestIndex) {
      earliestIndex = codeMatch.index
      matchType = 'code'
      currentMatch = codeMatch
    }

    if (!matchType || !currentMatch || currentMatch.index === undefined) {
      parts.push(remaining)
      break
    }

    if (currentMatch.index > 0) {
      parts.push(remaining.substring(0, currentMatch.index))
    }

    if (matchType === 'bold') {
      parts.push(<strong key={parts.length}>{renderInline(currentMatch[1])}</strong>)
    } else if (matchType === 'code') {
      parts.push(<code key={parts.length}>{currentMatch[1]}</code>)
    }

    remaining = remaining.substring(currentMatch.index + currentMatch[0].length)
  }

  return parts
}

export const MarkdownViewer: React.FC<MarkdownViewerProps> = ({ content, className }) => {
  if (!content) {
    return <div className="text-secondary text-sm p-md text-center">暂无内容</div>
  }

  const lines = content.split('\n')
  const elements: React.ReactNode[] = []

  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Empty lines
    if (!trimmed) {
      i++
      continue
    }

    // Code block ```
    if (trimmed.startsWith('```')) {
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++ // Skip closing ```
      elements.push(
        <pre key={elements.length} className="p-sm bg-subtle border rounded font-mono text-xs overflow-x-auto my-sm">
          <code>{codeLines.join('\n')}</code>
        </pre>
      )
      continue
    }

    // Markdown Table
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i].trim())
        i++
      }

      if (tableLines.length >= 2) {
        const headerCells = tableLines[0]
          .split('|')
          .slice(1, -1)
          .map((c) => c.trim())
        // tableLines[1] is divider |---|---|
        const bodyRows = tableLines.slice(2).map((r) =>
          r
            .split('|')
            .slice(1, -1)
            .map((c) => c.trim())
        )

        elements.push(
          <div key={elements.length} className="table-responsive my-md border rounded overflow-x-auto">
            <table>
              <thead>
                <tr>
                  {headerCells.map((h, hIdx) => (
                    <th key={hIdx}>{renderInline(h)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bodyRows.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx}>{renderInline(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
        continue
      }
    }

    // Headers
    if (trimmed.startsWith('# ')) {
      elements.push(<h1 key={elements.length}>{renderInline(trimmed.slice(2))}</h1>)
      i++
      continue
    }
    if (trimmed.startsWith('## ')) {
      elements.push(<h2 key={elements.length}>{renderInline(trimmed.slice(3))}</h2>)
      i++
      continue
    }
    if (trimmed.startsWith('### ')) {
      elements.push(<h3 key={elements.length}>{renderInline(trimmed.slice(4))}</h3>)
      i++
      continue
    }
    if (trimmed.startsWith('#### ')) {
      elements.push(<h4 key={elements.length} className="font-bold text-sm text-text my-xs">{renderInline(trimmed.slice(5))}</h4>)
      i++
      continue
    }

    // Blockquote
    if (trimmed.startsWith('>')) {
      const quoteLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoteLines.push(lines[i].trim().replace(/^>\s*/, ''))
        i++
      }
      elements.push(
        <blockquote key={elements.length}>
          {quoteLines.map((ql, qIdx) => (
            <p key={qIdx} className="mb-xs">{renderInline(ql)}</p>
          ))}
        </blockquote>
      )
      continue
    }

    // Horizontal Rule
    if (trimmed === '---' || trimmed === '***') {
      elements.push(<hr key={elements.length} />)
      i++
      continue
    }

    // Bullet List
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      const listItems: string[] = []
      while (i < lines.length && (lines[i].trim().startsWith('- ') || lines[i].trim().startsWith('* '))) {
        listItems.push(lines[i].trim().slice(2))
        i++
      }
      elements.push(
        <ul key={elements.length}>
          {listItems.map((item, lIdx) => (
            <li key={lIdx}>{renderInline(item)}</li>
          ))}
        </ul>
      )
      continue
    }

    // Regular Paragraph
    elements.push(<p key={elements.length}>{renderInline(trimmed)}</p>)
    i++
  }

  return <div className={`markdown-body ${className || ''}`}>{elements}</div>
}
