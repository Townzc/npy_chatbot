import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { request, type UsagePolicy, type UsageSummary } from '../api';
import { Badge, Icon } from '../components/ui';

const limitFields = [
  { key: 'monthly_requests', label: '每月请求上限', max: 1000000 },
  { key: 'monthly_input_tokens', label: '每月输入 token 上限', max: 1000000000 },
  { key: 'monthly_output_tokens', label: '每月输出 token 上限', max: 1000000000 },
] as const;
const priceFields = [
  { key: 'input_usd_per_million', label: '输入单价（USD / 百万 token）', max: 10000 },
  { key: 'output_usd_per_million', label: '输出单价（USD / 百万 token）', max: 10000 },
  { key: 'monthly_usd', label: '每月金额上限（USD，可不设置）', max: 100000 },
] as const;
type Draft = Record<
  (typeof limitFields)[number]['key'] | (typeof priceFields)[number]['key'],
  string
>;
function draftOf(policy: UsagePolicy): Draft {
  return {
    monthly_requests: String(policy.monthly_requests),
    monthly_input_tokens: String(policy.monthly_input_tokens),
    monthly_output_tokens: String(policy.monthly_output_tokens),
    input_usd_per_million:
      policy.input_usd_per_million == null ? '' : String(policy.input_usd_per_million),
    output_usd_per_million:
      policy.output_usd_per_million == null ? '' : String(policy.output_usd_per_million),
    monthly_usd: policy.monthly_usd == null ? '' : String(policy.monthly_usd),
  };
}

export default function BudgetPanel({
  token,
  personaId,
  onError,
}: {
  token: string;
  personaId: string;
  onError: (error: unknown) => void;
}) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const result = await request<UsageSummary>(
        token,
        `/usage?persona_id=${encodeURIComponent(personaId)}`,
        { signal },
      );
      if (signal?.aborted) return;
      setUsage(result);
      setDraft(draftOf(result.policy));
      setNotice('');
    },
    [token, personaId],
  );
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal).catch((error) => {
      if (!controller.signal.aborted) onError(error);
    });
    return () => controller.abort();
  }, [refresh, onError]);
  const pricesIncomplete =
    !!draft && (draft.input_usd_per_million === '') !== (draft.output_usd_per_million === '');
  const costWithoutPrices =
    !!draft &&
    draft.monthly_usd !== '' &&
    (draft.input_usd_per_million === '' || draft.output_usd_per_million === '');
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || !usage || pricesIncomplete || costWithoutPrices) return;
    setBusy(true);
    setNotice('');
    try {
      const body: UsagePolicy = {
        persona_id: personaId,
        version: usage.policy.version,
        monthly_requests: Number(draft.monthly_requests),
        monthly_input_tokens: Number(draft.monthly_input_tokens),
        monthly_output_tokens: Number(draft.monthly_output_tokens),
        input_usd_per_million:
          draft.input_usd_per_million === '' ? null : Number(draft.input_usd_per_million),
        output_usd_per_million:
          draft.output_usd_per_million === '' ? null : Number(draft.output_usd_per_million),
        monthly_usd: draft.monthly_usd === '' ? null : Number(draft.monthly_usd),
      };
      const result = await request<UsageSummary>(token, '/usage/policy', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      setUsage(result);
      setDraft(draftOf(result.policy));
      setNotice('预算已保存。调整预算不会恢复 AI；若会话已暂停，请在检查后主动重新开启。');
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel form-panel spaced-panel">
      <div className="panel-header plain">
        <div>
          <Icon name="chart" size={19} />
          <h2>用量与月度预算</h2>
        </div>
        <button
          className="text-button"
          disabled={busy}
          onClick={() => void refresh().catch(onError)}
        >
          重新读取
        </button>
      </div>
      <p className="muted">
        预算作用于当前个人档案下的所有关系。按 UTC
        月份累计；真实模型请求先预留用量，虚构演示不计入。
      </p>
      {usage && draft ? (
        <>
          <div className="budget-summary-heading">
            <span>{usage.month} · 含未结算预留</span>
            <Badge tone={usage.exhausted || usage.alert ? 'amber' : 'green'}>
              {usage.exhausted ? '本月预算已用尽' : usage.alert ? '用量已达到预算的 80%' : '预算内'}
            </Badge>
          </div>
          <div className="budget-metrics">
            {[
              { label: '请求', used: usage.requests, limit: usage.policy.monthly_requests },
              {
                label: '输入 token',
                used: usage.input_tokens,
                limit: usage.policy.monthly_input_tokens,
              },
              {
                label: '输出 token',
                used: usage.output_tokens,
                limit: usage.policy.monthly_output_tokens,
              },
            ].map((metric) => (
              <div key={metric.label}>
                <span>{metric.label}</span>
                <strong>
                  {metric.used.toLocaleString('zh-CN')}{' '}
                  <small>/ {metric.limit.toLocaleString('zh-CN')}</small>
                </strong>
                <progress
                  value={metric.used}
                  max={Math.max(1, metric.limit)}
                  aria-label={`${metric.label}用量`}
                />
              </div>
            ))}
          </div>
          <p className="field-hint">
            未结算请求 {usage.unresolved_requests}{' '}
            次。取消、超时或供应商未提供用量时保留预留额，重启不会清零。
          </p>
          <p className="budget-cost">
            本月金额估算：
            <strong>
              {usage.estimated_usd === null
                ? '尚未配置单价'
                : `USD ${usage.estimated_usd.toFixed(4)}`}
            </strong>
            {usage.policy.monthly_usd != null && <span> / USD {usage.policy.monthly_usd}</span>}
          </p>
          <p className="field-hint">{usage.note}</p>
          <form onSubmit={save} className="budget-form">
            <div className="budget-fields">
              {limitFields.map((field) => (
                <label key={field.key}>
                  {field.label}
                  <input
                    type="number"
                    required
                    min={0}
                    max={field.max}
                    step={1}
                    value={draft[field.key]}
                    onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })}
                  />
                </label>
              ))}
            </div>
            <p className="field-hint">
              上限为 0 时停止接受相应模型调用。降低上限不会取消已经发出的请求。
            </p>
            <div className="budget-fields">
              {priceFields.map((field) => (
                <label key={field.key}>
                  {field.label}
                  <input
                    type="number"
                    min={0}
                    max={field.max}
                    step="any"
                    value={draft[field.key]}
                    placeholder="不设置"
                    onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })}
                  />
                </label>
              ))}
            </div>
            <p className="field-hint">
              如需金额估算，请同时填写输入和输出单价。金额上限依赖这两个单价，不能替代供应商账单或供应商侧限额。
            </p>
            {(pricesIncomplete || costWithoutPrices) && (
              <p className="error" role="alert">
                请同时填写输入、输出单价；清空两者时也需清空金额上限。
              </p>
            )}
            <div className="action-row">
              <button
                className="button primary"
                disabled={busy || pricesIncomplete || costWithoutPrices}
              >
                {busy ? '正在保存…' : '保存当前档案预算'}
              </button>
              <span className="muted">配置版本 {usage.policy.version}</span>
            </div>
          </form>
        </>
      ) : (
        <p className="empty-copy spaced">正在读取当前档案用量…</p>
      )}
      {notice && (
        <p className="success-note" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
