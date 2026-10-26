import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  post,
  request,
  type Binding,
  type Memory,
  type MemoryInput,
  type MemoryPatch,
} from '../api';
import { Icon } from '../components/ui';

type SourceMessage = {
  id: string;
  sender_id: string;
  occurred_at: string;
  origin: string;
  content: { type: string; text: string | null };
};

export default function MemoryPanel({
  token,
  binding,
  onError,
}: {
  token: string;
  binding: Binding;
  onError: (e: unknown) => void;
}) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [messages, setMessages] = useState<SourceMessage[]>([]);
  const [text, setText] = useState('');
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [sourceFilter, setSourceFilter] = useState('');
  const [loadingSources, setLoadingSources] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Memory | null>(null);
  const [editText, setEditText] = useState('');
  const [editConfirmed, setEditConfirmed] = useState(false);
  const [editExpiry, setEditExpiry] = useState('');
  const query = `?persona_id=${encodeURIComponent(binding.persona_id)}&relationship_id=${encodeURIComponent(binding.relationship_id)}`;
  const refresh = useCallback(async () => {
    setMemories(await request<Memory[]>(token, `/memories${query}`));
  }, [token, query]);
  useEffect(() => {
    const controller = new AbortController();
    const fetchMemories = request<Memory[]>(token, `/memories${query}`, {
      signal: controller.signal,
    });
    const fetchSources = request<SourceMessage[]>(token, `/messages${query}`, {
      signal: controller.signal,
    });
    void Promise.allSettled([fetchMemories, fetchSources]).then(([memoryResult, messageResult]) => {
      if (controller.signal.aborted) return;
      if (memoryResult.status === 'fulfilled') setMemories(memoryResult.value);
      else onError(memoryResult.reason);
      if (messageResult.status === 'fulfilled')
        setMessages(
          messageResult.value.filter(
            (message) =>
              message.content.type === 'text' &&
              !['ai', 'mode_notice', 'platform_system'].includes(message.origin),
          ),
        );
      else onError(messageResult.reason);
      setLoadingSources(false);
    });
    return () => controller.abort();
  }, [token, query, onError]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!sourceIds.length || !text.trim()) return;
    setBusy(true);
    try {
      const body: MemoryInput = {
        persona_id: binding.persona_id,
        relationship_id: binding.relationship_id,
        text: text.trim(),
        source_message_ids: sourceIds,
        confirmed: true,
      };
      await post(token, '/memories', body);
      setText('');
      setSourceIds([]);
      await refresh();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    setBusy(true);
    try {
      await request(token, `/memories/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await refresh();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  function startEdit(memory: Memory) {
    setEditing(memory);
    setEditText(memory.text ?? memory.payload?.text ?? '');
    setEditConfirmed(false);
    const expiry = memory.expires_at ? new Date(memory.expires_at) : null;
    setEditExpiry(
      expiry && !Number.isNaN(expiry.getTime())
        ? new Date(expiry.getTime() - expiry.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
        : '',
    );
  }
  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing || !editText.trim()) return;
    setBusy(true);
    try {
      await request(token, `/memories/${encodeURIComponent(editing.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          persona_id: binding.persona_id,
          relationship_id: binding.relationship_id,
          text: editText.trim(),
          confirmed: editConfirmed,
          expires_at: editExpiry ? new Date(editExpiry).toISOString() : null,
          expected_version: editing.version,
        } satisfies MemoryPatch),
      });
      setEditing(null);
      await refresh();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  const filteredSources = messages.filter((message) =>
    `${message.sender_id} ${message.content.text ?? ''}`
      .toLocaleLowerCase()
      .includes(sourceFilter.toLocaleLowerCase()),
  );
  return (
    <div className="form-grid">
      <section className="panel form-panel">
        <div className="panel-header plain">
          <h2>已保存的关系记忆</h2>
          <span className="count">{memories.length}</span>
        </div>
        {memories.length ? (
          <div className="memory-list">
            {memories.map((memory) => (
              <article key={memory.id}>
                <Icon name="leaf" size={20} />
                <div>
                  {editing?.id === memory.id ? (
                    <form className="inline-edit" onSubmit={saveEdit}>
                      <label>
                        修改记忆内容
                        <textarea
                          rows={3}
                          required
                          maxLength={2000}
                          value={editText}
                          onChange={(event) => setEditText(event.target.value)}
                        />
                      </label>
                      <label>
                        有效期（本地时间，可留空）
                        <input
                          type="datetime-local"
                          value={editExpiry}
                          onChange={(event) => setEditExpiry(event.target.value)}
                        />
                      </label>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={editConfirmed}
                          onChange={(event) => setEditConfirmed(event.target.checked)}
                        />
                        <span>我已核对修改内容和原始出处，重新确认这条记忆。</span>
                      </label>
                      <div className="action-row">
                        <button
                          type="submit"
                          className="button primary"
                          disabled={busy || !editText.trim()}
                        >
                          保存修改
                        </button>
                        <button
                          type="button"
                          className="button secondary"
                          disabled={busy}
                          onClick={() => setEditing(null)}
                        >
                          取消
                        </button>
                      </div>
                    </form>
                  ) : (
                    <p>{memory.text ?? memory.payload?.text}</p>
                  )}
                  <small>
                    {(memory.confirmed ?? memory.payload?.confirmed)
                      ? '已确认'
                      : '候选 · 未用于检索'}{' '}
                    ·{' '}
                    {(memory.source_message_ids ?? memory.payload?.source_message_ids ?? []).length}{' '}
                    条来源
                  </small>
                  {memory.expires_at && (
                    <small className="memory-expiry">
                      有效至 {new Date(memory.expires_at).toLocaleString('zh-CN')}
                      {Date.parse(memory.expires_at) <= Date.now() ? ' · 已过期，不参与检索' : ''}
                    </small>
                  )}
                  <details>
                    <summary>查看来源</summary>
                    {(memory.source_message_ids ?? memory.payload?.source_message_ids ?? []).map(
                      (id) => {
                        const source = messages.find((message) => message.id === id);
                        return (
                          <p key={id} className="source-ids">
                            {source ? `${source.sender_id}：${source.content.text}` : id}
                          </p>
                        );
                      },
                    )}
                  </details>
                </div>
                <div className="row-actions">
                  <button className="text-button" disabled={busy} onClick={() => startEdit(memory)}>
                    编辑
                  </button>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => void remove(memory.id)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <Icon name="leaf" size={32} />
            <h3>给重要的事留个位置</h3>
            <p>从当前关系的聊天记录中选择出处，再确认值得保存的记忆。</p>
          </div>
        )}
      </section>
      <section className="panel form-panel">
        <div className="section-number">
          + <span>确认一条记忆</span>
        </div>
        <form onSubmit={save}>
          <label htmlFor="memory-text">记忆内容</label>
          <textarea
            id="memory-text"
            rows={4}
            required
            maxLength={2000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="例如：这位朋友更喜欢安静、不拥挤的展览。"
          />
          <fieldset className="source-fieldset">
            <legend>
              选择来源消息 <span>已选 {sourceIds.length} 条</span>
            </legend>
            {loadingSources ? (
              <p className="field-hint" role="status">
                正在载入当前关系的消息…
              </p>
            ) : messages.length ? (
              <>
                <label htmlFor="source-filter" className="sr-only">
                  筛选来源消息
                </label>
                <input
                  id="source-filter"
                  type="search"
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                  placeholder="搜索已加载的消息内容或发送者"
                />
                <div className="source-options">
                  {filteredSources.map((message) => (
                    <label key={message.id} className="source-option">
                      <input
                        type="checkbox"
                        checked={sourceIds.includes(message.id)}
                        onChange={(e) =>
                          setSourceIds((previous) =>
                            e.target.checked
                              ? [...previous, message.id]
                              : previous.filter((id) => id !== message.id),
                          )
                        }
                      />
                      <span>
                        <small>
                          {message.sender_id} ·{' '}
                          {new Date(message.occurred_at).toLocaleString('zh-CN')}
                        </small>
                        <span>{message.content.text}</span>
                      </span>
                    </label>
                  ))}
                  {filteredSources.length === 0 && (
                    <p className="field-hint">已加载的消息中没有匹配内容。</p>
                  )}
                </div>
                <p className="field-hint">
                  当前已加载 {messages.length} 条可用文字消息（服务端最多返回 200
                  条）。AI、通知和媒体不会作为事实来源。
                </p>
              </>
            ) : (
              <div className="source-empty">
                <Icon name="file" size={20} />
                <p>当前关系还没有可用的来源消息。请先在「导入与身份」导入聊天记录。</p>
              </div>
            )}
          </fieldset>
          <p className="field-hint">保存表示你已核对内容与出处，这条记忆仅在当前关系中使用。</p>
          <button className="button primary" disabled={busy || !text.trim() || !sourceIds.length}>
            确认并保存
            <Icon name="check" size={17} />
          </button>
        </form>
        <p className="fine-print">
          删除记忆不等于已训练的模型权重自动遗忘。相关模型产物需另行停用或重新训练。
        </p>
      </section>
    </div>
  );
}
