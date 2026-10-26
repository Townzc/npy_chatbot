import { useState, type ReactNode } from 'react';

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    chat: (
      <>
        <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2v-9.5A8.5 8.5 0 0 1 10.5 4H13a8 8 0 0 1 8 7.5Z" />
        <path d="M7 10h9M7 14h6" />
      </>
    ),
    import: (
      <>
        <path d="M12 3v12m-4-4 4 4 4-4M5 15v5h14v-5" />
      </>
    ),
    leaf: (
      <>
        <path d="M20 3c-8-1-15 2-15 8a6 6 0 0 0 10 4c3-3 4-8 5-12Z" />
        <path d="M4 21c1-5 4-9 9-12" />
      </>
    ),
    train: (
      <>
        <rect x="6" y="6" width="12" height="12" rx="3" />
        <path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4" />
        <path d="M10 10h4v4h-4z" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="9" cy="7" r="3" />
        <circle cx="15" cy="17" r="3" />
      </>
    ),
    arrow: (
      <>
        <path d="m5 12 14 0m-5-5 5 5-5 5" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    check: <path d="m5 12 4 4L19 6" />,
    lock: (
      <>
        <rect x="5" y="10" width="14" height="11" rx="3" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 7V3l-4 1M4 17v4l4-1M20 7a9 9 0 0 0-15-2M4 17a9 9 0 0 0 15 2" />
      </>
    ),
    stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
    logout: (
      <>
        <path d="M10 3H4v18h6M10 12h11m-4-4 4 4-4 4" />
      </>
    ),
    file: (
      <>
        <path d="M14 2H5v20h14V7l-5-5v5h5M8 12h8M8 16h6" />
      </>
    ),
    chart: <path d="M4 3v17h17M8 16v-4m5 4V8m5 8V5" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.chat}
    </svg>
  );
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'green' | 'amber' | 'neutral';
}) {
  return (
    <span className={`badge badge-${tone}`}>
      <span className="status-dot" />
      {children}
    </span>
  );
}

export function Report({ value }: { value: unknown }) {
  const [showDetail, setShowDetail] = useState(false);
  const result = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  const fields = [
    ['total', '消息总数'],
    ['inserted', '新增记录'],
    ['duplicates', '重复记录'],
    ['bad_rows', '错误行'],
    ['valid_text', '有效文本'],
    ['candidate_training_targets', '可训练目标'],
  ] as const;
  const counts =
    result.counts && typeof result.counts === 'object'
      ? (result.counts as Record<string, unknown>)
      : {};
  const splitFields = [
    ['train', '训练样本'],
    ['validation', '验证样本'],
    ['test', '测试样本'],
  ] as const;
  const preview = Array.isArray(result.preview)
    ? (result.preview.slice(0, 4) as Record<string, unknown>[])
    : [];
  const senders = Array.isArray(result.senders)
    ? (result.senders as { id: string; name: string }[])
    : [];
  const errors = Array.isArray(result.errors)
    ? (result.errors.slice(0, 3) as { record_index?: number; error?: string }[])
    : [];
  const formatDate = (date: unknown) =>
    typeof date === 'string' && !Number.isNaN(Date.parse(date))
      ? new Date(date).toLocaleString('zh-CN')
      : '未提供';
  return (
    <section className="result-report" aria-label="处理结果">
      <div className="result-report-heading">
        <strong>
          {typeof result.inserted === 'number'
            ? '导入结果'
            : typeof result.total === 'number'
              ? '记录预览'
              : '数据集结果'}
        </strong>
        {typeof result.identity_confirmed === 'boolean' && (
          <Badge tone={result.identity_confirmed ? 'green' : 'amber'}>
            {result.identity_confirmed ? '本人身份已确认' : '本人身份待选择'}
          </Badge>
        )}
      </div>
      <dl className="result-metrics">
        {fields.map(([key, label]) =>
          typeof result[key] === 'number' ? (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{result[key].toLocaleString('zh-CN')}</dd>
            </div>
          ) : null,
        )}
        {splitFields.map(([key, label]) =>
          typeof counts[key] === 'number' ? (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{counts[key].toLocaleString('zh-CN')}</dd>
            </div>
          ) : null,
        )}
      </dl>
      {result.start || result.end ? (
        <p className="result-date">
          记录时间：{formatDate(result.start)} — {formatDate(result.end)}
        </p>
      ) : null}
      {typeof result.human_origin_confirmed === 'boolean' && (
        <p className="result-note">
          {result.human_origin_confirmed
            ? '已确认选定的本人记录为真人发言。'
            : '未确认真人来源；未知来源不会成为训练标签。'}
        </p>
      )}
      {preview.length > 0 && (
        <div className="result-preview">
          <span>内容抽样 · 前 {preview.length} 条</span>
          {preview.map((message, index) => {
            const content =
              message.content && typeof message.content === 'object'
                ? (message.content as Record<string, unknown>)
                : {};
            const senderId =
              typeof message.sender_id === 'string' ? message.sender_id : '未知发送者';
            const text =
              typeof content.text === 'string' && content.text ? content.text : '[非文字内容]';
            return (
              <article key={typeof message.id === 'string' ? message.id : index}>
                <small>
                  {senders.find((sender) => sender.id === senderId)?.name || senderId}
                  <time>{formatDate(message.occurred_at)}</time>
                </small>
                <p>{text.length > 160 ? `${text.slice(0, 160)}…` : text}</p>
              </article>
            );
          })}
        </div>
      )}
      {errors.length > 0 && (
        <div className="result-errors" role="status">
          <strong>需要处理的错误</strong>
          {errors.map((error, index) => (
            <p key={index}>
              第 {error.record_index ?? '?'} 行：{error.error ?? '无法解析该记录'}
            </p>
          ))}
          {typeof result.bad_rows === 'number' && result.bad_rows > errors.length && (
            <small>其余错误可在详细报告中查看。</small>
          )}
        </div>
      )}
      <details className="report" onToggle={(event) => setShowDetail(event.currentTarget.open)}>
        <summary>查看详细报告（JSON）</summary>
        {showDetail && <pre>{JSON.stringify(value, null, 2)}</pre>}
      </details>
    </section>
  );
}
