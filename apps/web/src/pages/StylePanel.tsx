import { useCallback, useEffect, useState } from 'react';
import { request, scopeQuery, type Binding, type StyleInput } from '../api';
import { Badge, Icon } from '../components/ui';

interface Example {
  message_id: string;
  text: string;
}
interface Profile {
  id: string;
  version: number;
  status: string;
  rules: string;
  examples: Example[];
  source_message_ids: string[];
}
interface StyleResult {
  draft: { count: number; mean_length: number; examples: Example[]; rules: string };
  approved: Profile | null;
  history: Profile[];
  version: number;
}

export default function StylePanel({
  token,
  binding,
  onError,
}: {
  token: string;
  binding: Binding;
  onError: (error: unknown) => void;
}) {
  const [result, setResult] = useState<StyleResult | null>(null);
  const [rules, setRules] = useState('');
  const [examples, setExamples] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const query = scopeQuery(binding);
  const applyResult = useCallback((value: StyleResult) => {
    setResult(value);
    const editable = value.history[0]?.status === 'draft' ? value.history[0] : value.approved;
    setRules(editable?.rules ?? value.draft.rules);
    const eligibleIds = new Set([
      ...value.draft.examples.map((example) => example.message_id),
      ...(value.approved?.source_message_ids ?? []),
    ]);
    setExamples(
      (
        editable?.source_message_ids ?? value.draft.examples.map((example) => example.message_id)
      ).filter((id) => eligibleIds.has(id)),
    );
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    request<StyleResult>(token, `/styles${query}`, { signal: controller.signal })
      .then(applyResult)
      .catch((error) => {
        if (!controller.signal.aborted) onError(error);
      });
    return () => controller.abort();
  }, [token, query, applyResult, onError]);
  async function save(confirmed: boolean) {
    if (!result) return;
    setBusy(true);
    setNotice('');
    try {
      const updated = await request<Profile>(token, '/styles', {
        method: 'PUT',
        body: JSON.stringify({
          persona_id: binding.persona_id,
          relationship_id: binding.relationship_id,
          rules,
          example_message_ids: examples,
          confirmed,
          expected_version: result.version,
        } satisfies StyleInput),
      });
      applyResult(await request<StyleResult>(token, `/styles${query}`));
      setNotice(
        confirmed
          ? `风格版本 ${updated.version} 已确认，用于此关系的风格增强。`
          : `已保存草稿版本 ${updated.version}，尚未启用。`,
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  const choices = result
    ? Array.from(
        new Map(
          [...(result.approved?.examples ?? []), ...result.draft.examples].map((example) => [
            example.message_id,
            example,
          ]),
        ).values(),
      )
    : [];
  return (
    <div className="form-grid">
      <section className="panel form-panel">
        <div className="panel-header plain">
          <h2>表达习惯与风格</h2>
          <Badge tone={result?.approved ? 'green' : 'amber'}>
            {result?.approved ? `已确认 · v${result.approved.version}` : '等待确认'}
          </Badge>
        </div>
        <p className="muted">
          从当前关系内、已确认的本人发言生成风格草稿。只有你确认的版本会参与风格增强。
        </p>
        <div className="mini-metrics">
          <div>
            <small>本人样本</small>
            <strong>{result?.draft.count ?? '—'}</strong>
          </div>
          <div>
            <small>平均句长</small>
            <strong>{result ? Number(result.draft.mean_length).toFixed(1) : '—'}</strong>
          </div>
          <div>
            <small>已选示例</small>
            <strong>{examples.length} / 20</strong>
          </div>
        </div>
        <label htmlFor="style-rules">可编辑的表达规则</label>
        <textarea
          id="style-rules"
          rows={7}
          maxLength={4000}
          value={rules}
          disabled={!result || busy}
          onChange={(event) => setRules(event.target.value)}
          placeholder="例如：回复简短自然，不使用陌生的称呼。"
        />
        <p className="field-hint">规则描述语气和表达方式，不应写入其他联系人的私密事实。</p>
        <div className="action-row">
          <button
            className="button secondary"
            disabled={!result || busy}
            onClick={() => void save(false)}
          >
            保存草稿
          </button>
          <button
            className="button primary"
            disabled={!result || busy}
            onClick={() => void save(true)}
          >
            <Icon name="check" size={16} />
            确认并启用
          </button>
        </div>
        {notice && (
          <p className="success-note" role="status">
            {notice}
          </p>
        )}
      </section>
      <section className="panel form-panel">
        <div className="card-title">
          <Icon name="leaf" size={19} />
          <h2>选择风格示例</h2>
        </div>
        <p className="muted">
          示例保留消息出处；已划入验证集、测试集或被删除的消息不会进入可用草稿。
        </p>
        {choices.length ? (
          <div className="style-examples">
            {choices.map((example) => (
              <label key={example.message_id} className="source-option">
                <input
                  type="checkbox"
                  disabled={
                    busy || (examples.length >= 20 && !examples.includes(example.message_id))
                  }
                  checked={examples.includes(example.message_id)}
                  onChange={(event) =>
                    setExamples((previous) =>
                      event.target.checked
                        ? [...previous, example.message_id]
                        : previous.filter((id) => id !== example.message_id),
                    )
                  }
                />
                <span>
                  <span>{example.text}</span>
                  <small>来源：{example.message_id}</small>
                </span>
              </label>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <Icon name="leaf" size={28} />
            <p>
              {result
                ? '当前关系暂无可用的本人风格示例。先导入记录并确认身份与真人来源。'
                : '正在读取风格草稿…'}
            </p>
          </div>
        )}
        {result?.history.length ? (
          <details className="compact-details">
            <summary>查看 {result.history.length} 个历史版本</summary>
            <ul className="simple-list">
              {result.history.map((profile) => (
                <li key={profile.id}>
                  <strong>v{profile.version}</strong>
                  <span>
                    {profile.status === 'approved'
                      ? '已确认'
                      : profile.status === 'superseded'
                        ? '已替代'
                        : profile.status === 'revoked'
                          ? '已失效'
                          : '草稿'}{' '}
                    · {profile.source_message_ids.length} 条来源
                  </span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
    </div>
  );
}
