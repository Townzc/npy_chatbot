import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  post,
  request,
  type Binding,
  type ModeStatus,
  type ReconcileInput,
  type ResolveInput,
} from '../api';
import { Badge, Icon } from '../components/ui';

interface PendingSend {
  id: string;
  kind: string;
  status: string;
  text: string;
  started_at: string | null;
  platform_message_id: string | null;
  history: unknown[];
}
interface PendingList {
  binding_id: string;
  control_epoch: number;
  items: PendingSend[];
}
interface ResolutionResult {
  item: PendingSend;
  status: ModeStatus;
  resolved: boolean;
}
const kindLabels: Record<string, string> = {
  enable_notice: '开启通知',
  takeover_notice: '接管通知',
  ai_reply: 'AI 回复',
};

export default function ReconciliationPanel({
  token,
  binding,
  status,
  onStatus,
  onError,
}: {
  token: string;
  binding: Binding;
  status: ModeStatus | null;
  onStatus: (status: ModeStatus) => void;
  onError: (error: unknown) => void;
}) {
  const [pending, setPending] = useState<PendingList | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [outcome, setOutcome] = useState<'' | 'sent' | 'not_sent'>('');
  const [evidence, setEvidence] = useState('');
  const [messageId, setMessageId] = useState('');
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const selected = pending?.items.find((item) => item.id === selectedId);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const result = await request<PendingList>(
        token,
        `/outbox/unresolved?binding_id=${encodeURIComponent(binding.id)}`,
        { signal },
      );
      if (!signal?.aborted) {
        setPending(result);
        setSelectedId((previous) =>
          result.items.some((item) => item.id === previous) ? previous : '',
        );
      }
    },
    [token, binding.id],
  );
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal).catch((error) => {
      if (!controller.signal.aborted) onError(error);
    });
    return () => controller.abort();
  }, [refresh, status?.control_epoch, onError]);
  async function reconcile(item: PendingSend) {
    setBusy(item.id);
    setNotice('');
    try {
      const result = await post<ResolutionResult>(
        token,
        `/outbox/${encodeURIComponent(item.id)}/reconcile`,
        { binding_id: binding.id } satisfies ReconcileInput,
      );
      onStatus(result.status);
      await refresh();
      setNotice(
        result.resolved
          ? '渠道核对已得到确定结果，AI 保持停止。'
          : '渠道尚不能确认发送结果。请到原平台核对，不能将超时当作未送达。',
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  function choose(item: PendingSend) {
    setSelectedId(item.id);
    setOutcome('');
    setEvidence('');
    setMessageId(item.platform_message_id ?? '');
    setChecked(false);
    setNotice('');
  }
  async function resolve(event: FormEvent) {
    event.preventDefault();
    if (!selected || !outcome || !checked || evidence.trim().length < 6 || !status) return;
    setBusy(selected.id);
    setNotice('');
    try {
      const result = await post<ResolutionResult>(
        token,
        `/outbox/${encodeURIComponent(selected.id)}/resolve`,
        {
          binding_id: binding.id,
          outcome,
          platform_message_id: outcome === 'sent' ? messageId.trim() || null : null,
          evidence: evidence.trim(),
          expected_control_epoch: status.control_epoch,
        } satisfies ResolveInput,
      );
      onStatus(result.status);
      setSelectedId('');
      setChecked(false);
      await refresh();
      setNotice(
        result.resolved
          ? '已记录本人核对结论，证据来源为人工核对。此次操作没有重发消息，AI 保持停止；重新开启须由你主动操作。'
          : '记录仍待核对，AI 不会自动恢复。',
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  return (
    <section className="panel form-panel spaced-panel">
      <div className="panel-header plain">
        <div>
          <Icon name="refresh" size={19} />
          <h2>待核对发送</h2>
        </div>
        <button className="text-button" onClick={() => void refresh().catch(onError)}>
          刷新
        </button>
      </div>
      <p className="muted">
        发送超时不等于消息未送达。先查询渠道或核对原平台，再记录结论；这里不会自动重发。
      </p>
      {pending?.items.length ? (
        <div className="pending-sends">
          {pending.items.map((item) => (
            <article key={item.id}>
              <div className="job-heading">
                <strong>{kindLabels[item.kind] ?? item.kind}</strong>
                <Badge tone="amber">
                  {item.status === 'unknown'
                    ? '结果未知'
                    : item.status === 'submitting'
                      ? '传输中，等待回执'
                      : item.status}
                </Badge>
              </div>
              <p className="pending-text">{item.text}</p>
              <small>
                {item.started_at
                  ? `传输开始：${new Date(item.started_at).toLocaleString('zh-CN')}`
                  : '尚无可靠的传输开始记录'}
              </small>
              <div className="action-row">
                <button
                  className="button secondary small-button"
                  disabled={!!busy}
                  onClick={() => void reconcile(item)}
                >
                  尝试渠道核对
                </button>
                <button
                  className="button secondary small-button"
                  disabled={!!busy || item.status !== 'unknown'}
                  onClick={() => choose(item)}
                >
                  记录本人核对结论
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="empty-copy spaced">
          {pending ? '当前绑定没有待核对发送。' : '正在读取发送状态…'}
        </p>
      )}
      {notice && (
        <p className="success-note" role="status">
          {notice}
        </p>
      )}
      {selected && (
        <form className="resolution-form" onSubmit={resolve}>
          <h3>核对这条记录</h3>
          <blockquote>{selected.text}</blockquote>
          <label>
            原平台核对结论
            <select
              required
              value={outcome}
              onChange={(event) => {
                setOutcome(event.target.value as typeof outcome);
                if (event.target.value === 'not_sent') setMessageId('');
              }}
            >
              <option value="">请选择明确核对结果</option>
              <option value="sent">确认已送达</option>
              <option value="not_sent">确认未送达</option>
            </select>
          </label>
          <label>
            平台消息 ID（如能取得）
            <input
              value={messageId}
              disabled={outcome === 'not_sent'}
              maxLength={200}
              onChange={(event) => setMessageId(event.target.value)}
              placeholder="原平台提供的稳定消息 ID"
            />
          </label>
          <label>
            核对依据
            <textarea
              required
              minLength={6}
              maxLength={2000}
              rows={3}
              value={evidence}
              onChange={(event) => setEvidence(event.target.value)}
              placeholder="记录核对的原会话、时间和可确认结果的依据；不要仅填写“请求超时”。"
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={checked}
              onChange={(event) => setChecked(event.target.checked)}
            />
            <span>
              我已在原平台核对这条消息。此结论来自实际核对，而非仅根据超时或本地队列状态推断。
            </span>
          </label>
          <div className="action-row">
            <button
              className="button primary"
              disabled={!!busy || !checked || !outcome || evidence.trim().length < 6 || !status}
            >
              保存核对结论
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={!!busy}
              onClick={() => setSelectedId('')}
            >
              取消
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
